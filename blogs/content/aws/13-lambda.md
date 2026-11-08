---
title: "Lambda"
date: 2026-11-08
tags: [aws, lambda, serverless, s3-events, dynamodb, idempotency, execution-role, intermediate]
description: Post 13 of the AWS series. How a Lambda invocation really works, the two policies every function needs, why retries and idempotency matter, and a lab that builds the plat-ingest function, triggers it from S3 and records every upload in DynamoDB.
---

# Code That Runs Only When Something Happens ⚡

Everything so far has been something that *stays running*: an instance, a service, a pod. Many tasks on a data platform aren't like that. A file arrives, you process it, and you're done. Paying for a server that waits is a poor fit.

**Lambda** runs your function when an event arrives and bills for the milliseconds it ran. The function we build here, **`plat-ingest`**, is the first link of the platform's event flow: *a CSV lands in S3, and a record of that job appears in DynamoDB*.

In this post S3 calls the function directly. In Post 14 we will put SNS and SQS in between, and we'll write the code **now** so it works for both.

![Lambda: who invokes it, and what it can reach](content/aws/images/13-lambda.svg)

---

## How an Invocation Works 🔬

| Concept | Detail |
|---|---|
| **Function** | Your code, its runtime (Python 3.12 here), memory, timeout and role |
| **Handler** | The entry point: `lambda_function.handler(event, context)` |
| **Execution environment** | A sandbox that AWS creates to run your code. It may be **reused** for later invocations |
| **Cold start** | Creating a new environment: download code, start the runtime, run your **init code** (everything outside the handler). Shown as *Init Duration* in logs |
| **Warm start** | Reusing an existing environment: only the handler runs |
| **Memory** | 128 MB to 10,240 MB. **CPU is allocated in proportion to memory** |
| **Timeout** | Up to **15 minutes**. Default is only 3 seconds |
| **Concurrency** | Each in-flight request needs its own environment. Many events at once means many environments |

### Three ways to be invoked

| Style | Examples | If it fails |
|---|---|---|
| **Synchronous** | API Gateway, function URL, a direct `invoke` | The **caller** gets the error and decides what to do |
| **Asynchronous** | **S3 events**, SNS, EventBridge | Lambda **retries twice** (three attempts in total), then drops the event, unless you configure a **dead-letter queue or on-failure destination** |
| **Poll-based** | **SQS**, DynamoDB Streams, Kinesis | Lambda **polls** for you. Failed messages return to the queue (SQS) and retry |

### The two policies every function needs

| Policy | Question it answers | Where it lives |
|---|---|---|
| **Execution role** (identity policy) | What may this function **do**? | On the role |
| **Resource-based policy** | Who may **invoke** this function? | On the function |

When you add an S3 trigger in the console, it quietly creates a resource-based statement that lets `s3.amazonaws.com` invoke the function **from your bucket in your account**. Without it, the notification fails and nobody tells you why.

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "Lambda scales automatically, so I never need to think about limits." | There is an **account concurrency limit** per region (1,000 by default, adjustable). One busy function can starve others. Use **reserved concurrency** to cap or protect a function. |
| "The 3-second default timeout is fine." | Reading a file from S3 can exceed it. The function is killed with `Task timed out` and **no code of yours runs afterwards**. Set it deliberately. |
| "Global variables are reset every call." | Anything outside the handler persists while the **environment is warm**. Create clients there (faster), but never keep per-request state in globals. |
| "Lambda runs once per event." | Delivery is **at least once**. Asynchronous retries and SQS redelivery mean the same event can run more than once. Code must be **idempotent**. |
| "Failed S3-triggered runs are retried forever." | Twice, then they're **dropped**. Without a DLQ or destination you only find out by reading the `Errors` metric. |
| "`/tmp` is lost when the function returns." | It can survive between warm invocations (512 MB by default, configurable up to 10 GB), but never rely on it. |
| "More memory just costs more." | More memory also means more CPU, so a function can finish sooner and **cost the same or less**. Test, don't guess. |
| "Putting a function in my VPC makes it more secure." | It gives it **private network reach** (to RDS). It also **removes its default internet path**: S3, DynamoDB and other AWS APIs now need NAT or **endpoints**. Don't attach a VPC unless the function needs private resources. |
| "I can put a big dependency in the zip." | Packages are limited (50 MB zipped upload, 250 MB unzipped, including layers). Use **layers** or a **container image** (up to 10 GB) for large libraries. |
| "The `boto3` in the runtime is always the version I want." | It's provided by the runtime and **updated on AWS's schedule**. Pin your own copy if your code relies on new APIs. |
| "Environment variables are secret." | They are **encrypted at rest** but visible to anyone who can read the function configuration. Store secrets in **Secrets Manager** and fetch them. |
| "Lambda logs themselves." | Only if the **role** allows `logs:CreateLogGroup`, `CreateLogStream` and `PutLogEvents`. And the log group **never expires** by default. |
| "An S3 trigger on the same prefix I write to is harmless." | If the function writes output into the prefix that triggers it, you create an **infinite loop** and a large bill. Write results to a **different prefix or bucket**. |
| "Arm is a risk." | `arm64` (Graviton) is cheaper per GB-second and works for pure-Python code. Native dependencies need arm builds. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| Bucket `plat-data-<acct>-us-east-1`, the `raw/` prefix and `events.csv` | Post 06 |
| SSE-KMS and the `kms:ViaService` pattern | Posts 05, 06 |
| DynamoDB `plat-jobs` with key `job_id` and GSI `status-created_idx` | Post 08 |
| The role-instead-of-keys pattern | Posts 10, 11, 12 |

| You create here | Used by |
|---|---|
| Function **`plat-ingest`** and role **`plat-ingest-role`** | Post 14 puts SNS and SQS in front of it with **no code change** |
| Job records with deterministic IDs | The API's `/jobs/<id>` route (11, 12), the nightly report (14) |
| Log group `/aws/lambda/plat-ingest` | Alarms (21) |

---

## Lab: The `plat-ingest` Function 🛠️

Sign in as Jim, in **N. Virginia**.

### 1. Create the execution role

**IAM, Roles, Create role**. Use case **Lambda**. Attach **`AWSLambdaBasicExecutionRole`** (logging only). Name **`plat-ingest-role`**. Then add this inline policy, **`plat-ingest-access`**, with your own account ID and key ID:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadRawFiles",
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": "arn:aws:s3:::plat-data-123456789012-us-east-1/raw/*"
    },
    {
      "Sid": "DecryptViaS3",
      "Effect": "Allow",
      "Action": "kms:Decrypt",
      "Resource": "arn:aws:kms:us-east-1:123456789012:key/<your-key-id>",
      "Condition": { "StringEquals": { "kms:ViaService": "s3.us-east-1.amazonaws.com" } }
    },
    {
      "Sid": "RecordJobs",
      "Effect": "Allow",
      "Action": ["dynamodb:PutItem"],
      "Resource": "arn:aws:dynamodb:us-east-1:123456789012:table/plat-jobs"
    }
  ]
}
```

Note what it can't do: no `ListBucket`, no `DeleteObject`, no reads from DynamoDB. A function that only ingests needs only these.

> **Note:** `s3:GetObject` alone is enough here because we use the exact key from the event. But with only `GetObject`, a request for a missing key returns **AccessDenied** and not "not found", because the caller isn't allowed to list. Remember that when debugging.

### 2. Create the function

**Lambda, Create function, Author from scratch**:

| Setting | Value |
|---|---|
| Function name | `plat-ingest` |
| Runtime | **Python 3.12** |
| Architecture | **x86_64** |
| Execution role | **Use an existing role: `plat-ingest-role`** |

After it is created, open the **Code** tab, replace `lambda_function.py` with this, and click **Deploy**:

**`lambda_function.py`**

```python
import hashlib
import json
import logging
import os
import urllib.parse
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger()
log.setLevel(logging.INFO)

# Created once per execution environment, reused while it stays warm.
s3 = boto3.client("s3")
table = boto3.resource("dynamodb").Table(os.environ["JOBS_TABLE"])


def extract(record):
    """Yield (bucket, key) pairs from an S3 notification, whether it arrived
    directly from S3 or wrapped in an SNS envelope inside an SQS message."""
    if record.get("eventSource") == "aws:sqs":
        body = json.loads(record["body"])
        if "Message" in body:                     # SNS envelope
            body = json.loads(body["Message"])
        for inner in body.get("Records", []):
            yield from extract(inner)
    elif "s3" in record:
        yield (record["s3"]["bucket"]["name"],
               urllib.parse.unquote_plus(record["s3"]["object"]["key"]))


def ingest(bucket, key):
    if not (key.startswith("raw/") and key.endswith(".csv")):
        log.info("skipping %s", key)
        return

    head = s3.head_object(Bucket=bucket, Key=key)
    etag = head["ETag"].strip('"')
    # One object version always gives the same job id, so a redelivered
    # notification for it is harmless.
    job_id = "ingest-" + hashlib.sha1(f"{bucket}/{key}/{etag}".encode()).hexdigest()[:12]

    body = s3.get_object(Bucket=bucket, Key=key)["Body"]
    rows = sum(1 for _ in body.iter_lines()) - 1       # minus the header line

    item = {
        "job_id": job_id,
        "status": "DONE",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rows": rows,
        "s3_key": key,
        "bytes": head["ContentLength"],
    }
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(job_id)")
        log.info("recorded %s rows=%d key=%s", job_id, rows, key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            log.info("duplicate delivery ignored job=%s key=%s", job_id, key)
        else:
            raise


def handler(event, context):
    failures = []
    for record in event.get("Records", []):
        try:
            for bucket, key in extract(record):
                ingest(bucket, key)
        except Exception:
            log.exception("record failed")
            if record.get("eventSource") == "aws:sqs":
                failures.append({"itemIdentifier": record["messageId"]})  # retry only this one
            else:
                raise                                                      # let async retry handle it
    return {"batchItemFailures": failures}
```

Go to **Configuration**:

- **General configuration, Edit**: memory **256 MB**, timeout **30 seconds**.
- **Environment variables, Edit**: add `JOBS_TABLE` = `plat-jobs`.

### 3. Test it by hand

On the **Test** tab create an event named `s3-put` with this JSON (your own bucket name):

```json
{
  "Records": [
    {
      "eventSource": "aws:s3",
      "s3": {
        "bucket": { "name": "plat-data-123456789012-us-east-1" },
        "object": { "key": "raw/events.csv" }
      }
    }
  ]
}
```

Click **Test**. The response is `{"batchItemFailures": []}`. Open the **Log output**; the end looks like this:

```text
[INFO] recorded ingest-3f9a1c2b7d40 rows=5050 key=raw/events.csv
REPORT RequestId: ...  Duration: 612.40 ms  Billed Duration: 613 ms
Memory Size: 256 MB  Max Memory Used: 94 MB  Init Duration: 428.11 ms
```

`Init Duration` is the **cold start**. Run the test again and the second `REPORT` has no `Init Duration`; the log line says:

```text
[INFO] duplicate delivery ignored job=ingest-3f9a1c2b7d40 key=raw/events.csv
```

The condition expression turned a repeat into a no-op. Check the table (in CloudShell):

```bash
aws dynamodb scan --table-name plat-jobs --query "Items[].[job_id.S,status.S,rows.N]" --output text
```

```text
job-001                 DONE    5050
ingest-3f9a1c2b7d40     DONE    5050
```

If the first test returns an `AccessDeniedException` in the log, the cause is in the role (names, ARNs or the key condition). Compare against the policy, not the code.

### 4. Add the S3 trigger

On the function page: **Add trigger**:

| Setting | Value |
|---|---|
| Source | **S3** |
| Bucket | `plat-data-<acct>-us-east-1` |
| Event types | **All object create events** |
| Prefix | `raw/` |
| Suffix | `.csv` |
| Recursive invocation | Tick the acknowledgement |

Add it. Then look at what the console created for you:

```bash
aws lambda get-policy --function-name plat-ingest --query Policy --output text | python3 -m json.tool
```

```json
{
    "Sid": "lambda-...",
    "Effect": "Allow",
    "Principal": { "Service": "s3.amazonaws.com" },
    "Action": "lambda:InvokeFunction",
    "Resource": "arn:aws:lambda:us-east-1:123456789012:function:plat-ingest",
    "Condition": {
        "StringEquals": { "AWS:SourceAccount": "123456789012" },
        "ArnLike": { "AWS:SourceArn": "arn:aws:s3:::plat-data-123456789012-us-east-1" }
    }
}
```

That's the resource-based policy. Only S3, from your account, from this bucket, may invoke.

### 5. Let an upload trigger it

In CloudShell create a second, smaller file and upload it:

```bash
BUCKET=plat-data-$(aws sts get-caller-identity --query Account --output text)-us-east-1
aws s3 cp s3://$BUCKET/raw/events.csv events.csv
head -1001 events.csv > day2.csv          # header + 1000 rows
aws s3 cp day2.csv s3://$BUCKET/raw/day2.csv

sleep 10
aws logs tail /aws/lambda/plat-ingest --since 5m --format short | grep -E "recorded|duplicate|ERROR"
```

```text
[INFO] recorded ingest-a81e0c55f2b9 rows=1000 key=raw/day2.csv
```

You didn't invoke anything. The upload did. Confirm with the index from Post 08:

```bash
aws dynamodb query --table-name plat-jobs --index-name status-created_idx \
  --key-condition-expression "#s = :d" \
  --expression-attribute-names '{"#s":"status"}' \
  --expression-attribute-values '{":d":{"S":"DONE"}}' \
  --query "Items[].[job_id.S,rows.N,s3_key.S]" --output text
```

Upload `day2.csv` again and a **second job** appears. With SSE-KMS every upload is encrypted under a fresh data key, so the ETag differs even for identical content, which makes this a distinct object version and a legitimately new job. The job ID only repeats when **the same notification is delivered twice**, as you simulated in step 3 with the console test.

### 6. Break the permission, see how it fails

Remove (or add a `Deny` for) `kms:Decrypt` from `plat-ingest-access`, wait a minute, then upload a new file:

```bash
head -501 events.csv > day3.csv
aws s3 cp day3.csv s3://$BUCKET/raw/day3.csv
sleep 20
aws logs tail /aws/lambda/plat-ingest --since 2m --format short | grep -E "ERROR|AccessDenied|KMS" | head
```

Because the invocation is **asynchronous**, the failure is retried. You'll see the same error about **one minute** and **two minutes** later. After the third attempt the event is dropped, and **no job record exists for `day3.csv`**. On the **Monitor** tab, the `Errors` graph shows it.

Restore the policy statement. The dropped event isn't replayed, so re-upload with `aws s3 cp day3.csv s3://$BUCKET/raw/day3.csv` after changing the content (for example, `head -502`). That fragility is why Post 14 puts a **queue with a dead-letter queue** in front.

### 7. Housekeeping

- **Configuration, Monitoring and operations tools**, or in CloudWatch **Log groups**, set `/aws/lambda/plat-ingest` retention to **7 days**.
- Keep the function and trigger. In Post 14 you move the trigger from S3 to SQS.

### 8. Resources you now have 📦

| Resource | Name |
|---|---|
| Role | `plat-ingest-role` (logs, S3 read on `raw/*`, KMS decrypt via S3, DynamoDB `PutItem`) |
| Function | `plat-ingest` (Python 3.12, 256 MB, 30 s, env `JOBS_TABLE`) |
| S3 event notification | `raw/*.csv` object create, to the function |
| Resource-based policy | S3 may invoke the function |
| DynamoDB items | `ingest-<hash>` jobs for `events.csv` and `day2.csv` |
| Log group | `/aws/lambda/plat-ingest` |

### Cleanup 🧹

Lambda costs nothing while idle. Nothing to pause. Delete the S3 trigger only if you plan to stop here.

---

## Quick Quiz 🧠

**Q1.** Your function times out after 3 seconds reading a 40 MB file. What are the two things you change?

<details>
<summary>Show answer</summary>

Raise the **timeout** (up to 15 minutes) and consider more **memory**, which gives proportionally more CPU and network throughput. Better yet, stream the object, as `iter_lines` does here.

</details>

**Q2.** Which policy lets S3 invoke your function and which lets your function read the bucket?

<details>
<summary>Show answer</summary>

S3 invoking the function is the function's **resource-based policy**. The function reading S3 and DynamoDB is the **execution role's identity policy**. Both are required.

</details>

**Q3.** The same upload event is delivered twice. Name the mechanism in `plat-ingest` that stops a duplicate record.

<details>
<summary>Show answer</summary>

The **deterministic job ID** (hash of bucket, key and ETag) plus the **conditional write** `attribute_not_exists(job_id)`. The second attempt fails the condition and is logged and ignored.

</details>

**Q4.** An async-invoked function fails three times. What happens to the event, and how would you avoid losing it?

<details>
<summary>Show answer</summary>

It's **dropped**. Configure a **dead-letter queue / on-failure destination**, or put an **SQS queue** (with a DLQ) between the source and the function.

</details>

**Q5.** You attach `plat-ingest` to your VPC "for security", and it starts timing out when reaching DynamoDB. Why?

<details>
<summary>Show answer</summary>

A VPC-attached function has **no internet path** by default and its ENIs live in your subnets. It needs a **NAT gateway** or a **DynamoDB gateway endpoint** (and an S3 endpoint) to reach those services.

</details>

---

## What's Next? 🚀

Right now S3 calls Lambda directly, and a permissions mistake means a lost event. Real pipelines put **messaging** in the middle: a topic that fans out, a queue that buffers and retries, and a scheduler that triggers work when nothing happened at all.

👉 **[Post 14: SQS, SNS and EventBridge](content/aws/14-sqs-sns-and-eventbridge.md)**: S3 to SNS to SQS (with a dead-letter queue) to the same Lambda, plus a scheduled rule and an alarm topic.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
