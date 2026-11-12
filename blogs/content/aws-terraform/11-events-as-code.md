---
title: "Events as Code: S3, SQS, Lambda, EventBridge and SNS"
date: 2026-11-10
tags: [aws, terraform, s3, sqs, lambda, eventbridge, sns, dead-letter-queue, intermediate]
description: Post 11 of the AWS on Terraform series. An upload pipeline with a dead-letter queue and partial batch failure, Lambda code packaged by Terraform, a nightly schedule, an EC2 state-change rule, and the resource policies that every one of those connections needs.
---

# Things That React 📬

Everything so far waits to be called. `stacks/60-events` is the part of the platform that reacts. A file lands in S3 and a record appears in DynamoDB. A clock fires at night and an email arrives with a summary. An instance stops and someone hears about it. It combines AWS series Posts 11 to 13 (queues, Lambda, EventBridge and SNS).

The central skill here is not any single service. It is the **resource policy**: each arrow in the diagram is a service that must be allowed to call another, and Terraform will happily create the pieces without the permission between them.

---

## The Pieces 🧱

| Piece | Resource(s) | Always on? |
|---|---|---|
| Topic `plat-alerts` + policy + email subscription | `aws_sns_topic.alerts`, `aws_sns_topic_policy.alerts`, `aws_sns_topic_subscription.email` | Yes (subscription only if `alert_email` is set) |
| Queue, dead-letter queue and queue policy | `aws_sqs_queue.ingest`, `.dlq`, `aws_sqs_queue_policy.ingest` | Yes |
| S3 notification | `aws_s3_bucket_notification.raw` | Yes |
| `plat-ingest`: role, policy, log group, function, queue trigger | `aws_iam_role.ingest` and friends, `aws_lambda_function.ingest`, `aws_lambda_event_source_mapping.ingest` | Yes |
| `plat-report`: role, policy, log group, function | `aws_iam_role.report` and friends, `aws_lambda_function.report` | Yes |
| Nightly schedule | `aws_cloudwatch_event_rule.nightly`, `_target.nightly`, `aws_lambda_permission.nightly` | Yes |
| EC2 state-change rule | `aws_cloudwatch_event_rule.ec2_state`, `_target.ec2_state` | Yes |

Everything here is serverless and bills per use, so there are no toggles. Lambda functions are **not** in the VPC, so no NAT is needed.

![Events stack](content/aws-terraform/images/11-events.svg)

---

## Reading the Stack 📖

### Alerts: the topic and its policy

```hcl
# stacks/60-events/main.tf
resource "aws_sns_topic" "alerts" {
  name = "plat-alerts"
}

data "aws_iam_policy_document" "alerts" {
  statement {
    sid       = "OwnerAccount"
    actions   = ["sns:Publish", "sns:Subscribe", "sns:GetTopicAttributes", "sns:SetTopicAttributes", "sns:ListSubscriptionsByTopic"]
    resources = [aws_sns_topic.alerts.arn]

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${local.account_id}:root"]
    }
  }

  statement {
    sid       = "EventsAndAlarmsMayPublish"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com", "cloudwatch.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }

  statement {
    sid       = "BudgetsMayPublish"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]

    principals {
      type        = "Service"
      identifiers = ["budgets.amazonaws.com"]
    }
  }
}

resource "aws_sns_topic_policy" "alerts" {
  arn    = aws_sns_topic.alerts.arn
  policy = data.aws_iam_policy_document.alerts.json
}

resource "aws_sns_topic_subscription" "email" {
  count = var.alert_email == "" ? 0 : 1

  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
```

An SNS topic has a **resource policy** that decides who may publish. By default only the account's own principals can. EventBridge, CloudWatch alarms and Budgets are **services**, and each must be named as a principal, or its publishes are dropped. Note the two conditions: `aws:SourceAccount` stops another account's alarm from publishing to our topic through a confused-deputy path.

The topic is deliberately **not encrypted with `plat-data`**. Encrypting it would require the key policy to allow EventBridge, CloudWatch and Budgets as well, which is a bigger change than the lesson needs. If you add it, expect silent drops until the key policy lists those services.

The subscription is `count`-gated: `alert_email = ""` means no subscription. An email subscription stays **pending** until you click the confirmation link. Terraform cannot click it, and reports success anyway.

### The ingest path

```hcl
# stacks/60-events/main.tf
resource "aws_sqs_queue" "dlq" {
  name                      = "plat-ingest-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "ingest" {
  name                       = "plat-ingest-queue"
  visibility_timeout_seconds = 60
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 3
  })
}
```

* The queue's **visibility timeout (60 s)** is six times the function timeout (10 s). The rule is: at least the function timeout, and the event source mapping insists on it.
* `redrive_policy` sends a message to the dead-letter queue after it has been received **three** times without being deleted.
* The DLQ keeps messages for 14 days, the maximum, so you have time to look.

```hcl
# stacks/60-events/main.tf
data "aws_iam_policy_document" "queue" {
  statement {
    sid       = "S3MaySend"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.ingest.arn]

    principals {
      type        = "Service"
      identifiers = ["s3.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [local.bucket_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_sqs_queue_policy" "ingest" {
  queue_url = aws_sqs_queue.ingest.id
  policy    = data.aws_iam_policy_document.queue.json
}

resource "aws_s3_bucket_notification" "raw" {
  bucket = local.bucket

  queue {
    queue_arn     = aws_sqs_queue.ingest.arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "raw/"
  }

  depends_on = [aws_sqs_queue_policy.ingest]
}
```

Here is the S3 side of the arrow. The queue policy lets **S3** send messages, but only from our bucket and our account. The notification resource then tells the bucket to send `ObjectCreated` events for the `raw/` prefix to the queue. `depends_on` puts the policy first: if it doesn't exist when the notification is created, S3 refuses with `Unable to validate the following destination configurations`.

Two properties of `aws_s3_bucket_notification` matter. It manages the bucket's **whole** notification configuration, so there must be exactly one per bucket across all your code. And the bucket is created by a different stack (`40-data`), which is why this resource lives here: **the stack that owns the consumer owns the wiring**.

```python
# stacks/60-events/src/ingest.py
"""plat-ingest: SQS -> DynamoDB.

S3 announces each new object under raw/ to the queue. For every announcement this function reads the
object, counts its rows and records a job item in plat-jobs. Any record that fails is reported back
individually, so the rest of the batch is not retried.
"""
import json
import os
import time
import urllib.parse

import boto3

TABLE = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
S3 = boto3.client("s3")
TTL_DAYS = int(os.environ.get("TTL_DAYS", "30"))


def handle_s3_record(rec):
    bucket = rec["s3"]["bucket"]["name"]
    key = urllib.parse.unquote_plus(rec["s3"]["object"]["key"])
    body = S3.get_object(Bucket=bucket, Key=key, Range="bytes=0-1048575")["Body"].read().decode("utf-8", "replace")
    if "POISON" in body:  # lets you rehearse the dead-letter queue on purpose
        raise ValueError(f"poison message in {key}")
    now = int(time.time())
    TABLE.put_item(Item={
        "job_id": key,
        "status": "INGESTED",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "rows": max(len(body.splitlines()) - 1, 0),
        "expires_at": now + TTL_DAYS * 86400,
    })


def handler(event, context):
    failures = []
    for message in event["Records"]:
        try:
            for rec in json.loads(message["body"]).get("Records", []):  # s3:TestEvent has no Records
                handle_s3_record(rec)
        except Exception as exc:  # noqa: BLE001
            print(f"failed {message['messageId']}: {exc}")
            failures.append({"itemIdentifier": message["messageId"]})
    return {"batchItemFailures": failures}
```

The function accepts an SQS batch. Each message body is the S3 event (a JSON string). The code returns **`batchItemFailures`**: only the messages that failed go back to the queue. Without `ReportBatchItemFailures`, one bad record would send the entire batch of five back, and the four good ones would be processed again. The test message S3 sends when you create a notification (`s3:TestEvent`) has no `Records`, and the handler skips it.

The word `POISON` in a file makes the function fail on purpose, so you can watch the DLQ work.

```hcl
# stacks/60-events/main.tf
data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ingest" {
  name               = "plat-ingest-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy_attachment" "ingest_logs" {
  role       = aws_iam_role.ingest.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "ingest_access" {
  statement {
    sid       = "ReadQueue"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.ingest.arn]
  }

  statement {
    sid       = "ReadRawObjects"
    actions   = ["s3:GetObject"]
    resources = ["${local.bucket_arn}/raw/*"]
  }

  statement {
    sid       = "WriteJobs"
    actions   = ["dynamodb:PutItem"]
    resources = [local.table_arn]
  }

  statement {
    sid       = "UseDataKey"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
    resources = [local.kms_arn]
  }
}

resource "aws_iam_role_policy" "ingest_access" {
  name   = "plat-ingest-access"
  role   = aws_iam_role.ingest.id
  policy = data.aws_iam_policy_document.ingest_access.json
}
```

The role can read from the queue, read `raw/*` objects (note the prefix: not the whole bucket), put items in the table, and use the key. The managed `AWSLambdaBasicExecutionRole` provides the log permissions.

### Packaging and creating the function

```hcl
# stacks/60-events/main.tf
data "archive_file" "ingest" {
  type        = "zip"
  source_file = "${path.module}/src/ingest.py"
  output_path = "${path.module}/ingest.zip"
}

resource "aws_cloudwatch_log_group" "ingest" {
  name              = "/aws/lambda/plat-ingest"
  retention_in_days = 14
}

resource "aws_lambda_function" "ingest" {
  function_name    = "plat-ingest"
  role             = aws_iam_role.ingest.arn
  runtime          = "python3.12"
  handler          = "ingest.handler"
  filename         = data.archive_file.ingest.output_path
  source_code_hash = data.archive_file.ingest.output_base64sha256
  timeout          = 10
  memory_size      = 128

  environment {
    variables = {
      TABLE_NAME = local.table
      TTL_DAYS   = tostring(var.ttl_days)
    }
  }

  depends_on = [aws_cloudwatch_log_group.ingest, aws_iam_role_policy_attachment.ingest_logs]
}

resource "aws_lambda_event_source_mapping" "ingest" {
  event_source_arn        = aws_sqs_queue.ingest.arn
  function_name           = aws_lambda_function.ingest.arn
  batch_size              = 5
  function_response_types = ["ReportBatchItemFailures"]

  depends_on = [aws_iam_role_policy.ingest_access]
}
```

* **`archive_file`** zips `src/ingest.py` at plan time. `source_code_hash` is the hash of the zip, so Terraform updates the function when, and only when, the code changes. Edit `ingest.py`, run `plan`, and you see an in-place change to `source_code_hash`.
* The **log group is created by Terraform** so that it has a retention (14 days). If you let Lambda create it, it is created on first invocation with **no expiry**, and Terraform would then fail to create its own (it already exists).
* The mapping is a separate resource from the function: it is the poller that reads the queue and invokes the function. `batch_size = 5` and `function_response_types` give the partial-failure behaviour above.

### The nightly report

```python
# stacks/60-events/src/report.py
"""plat-report: runs on a schedule, counts jobs by status and publishes the summary to SNS."""
import os
from collections import Counter

import boto3

TABLE = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
SNS = boto3.client("sns")


def handler(event, context):
    counts, kwargs = Counter(), {"ProjectionExpression": "#s", "ExpressionAttributeNames": {"#s": "status"}}
    while True:
        page = TABLE.scan(**kwargs)
        counts.update(item["status"] for item in page["Items"])
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    lines = [f"{status}: {n}" for status, n in sorted(counts.items())] or ["no jobs"]
    SNS.publish(TopicArn=os.environ["TOPIC_ARN"], Subject="plat nightly report", Message="\n".join(lines))
    return dict(counts)
```

```hcl
# stacks/60-events/main.tf
resource "aws_cloudwatch_event_rule" "nightly" {
  name                = "plat-nightly-report"
  description         = "Run plat-report every night"
  schedule_expression = var.report_cron
}

resource "aws_cloudwatch_event_target" "nightly" {
  rule = aws_cloudwatch_event_rule.nightly.name
  arn  = aws_lambda_function.report.arn
}

resource "aws_lambda_permission" "nightly" {
  statement_id  = "AllowEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.report.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.nightly.arn
}
```

Three resources for one schedule, and each answers a different question: **when** (rule), **what to call** (target) and **may it call** (the Lambda permission). EventBridge cron expressions are in **UTC**; the default `cron(30 20 * * ? *)` is 02:00 in Bengaluru. The report role (`aws_iam_role.report` and its policy, in the same file) can scan the table and publish to the topic, but nothing else.

### Instance state changes

```hcl
# stacks/60-events/main.tf
resource "aws_cloudwatch_event_rule" "ec2_state" {
  name        = "plat-ec2-state-change"
  description = "Tell plat-alerts when any EC2 instance starts, stops or terminates"

  event_pattern = jsonencode({
    source        = ["aws.ec2"]
    "detail-type" = ["EC2 Instance State-change Notification"]
    detail        = { state = ["running", "stopped", "terminated"] }
  })
}

resource "aws_cloudwatch_event_target" "ec2_state" {
  rule = aws_cloudwatch_event_rule.ec2_state.name
  arn  = aws_sns_topic.alerts.arn

  depends_on = [aws_sns_topic_policy.alerts]
}
```

An **event pattern** instead of a schedule: match EC2 state-change notifications for the three states. The target is the SNS topic itself, so no function is involved. This is why the topic policy names `events.amazonaws.com`. Many people build this rule and see nothing happen: the rule works, and the publish is rejected.

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "An SNS email subscription is active after apply." | It is `PendingConfirmation` until the recipient clicks the link. |
| "EventBridge can publish to my topic because I own both." | Only if the topic policy names `events.amazonaws.com`. Otherwise the event is dropped, with no error you will see. |
| "The queue receives S3 events as soon as the notification exists." | Only if the queue policy allows S3 to `SendMessage`. Without it the notification fails to create. |
| "Each stack can add its own notification to the bucket." | One `aws_s3_bucket_notification` per bucket. A second overwrites the first. |
| "A failed message is lost." | It returns to the queue and, after three receives, goes to the DLQ for 14 days. |
| "A failure in one record retries the whole batch." | Only with plain behaviour. `ReportBatchItemFailures` retries just the failed ones. |
| "The visibility timeout can be short." | It must be at least the function timeout. Too short and healthy messages are delivered twice. |
| "Lambda creates its log group, so I don't need one." | It then has no retention and conflicts with a Terraform-created group of the same name. |
| "`cron(...)` runs at my local time." | UTC always. |
| "Terraform deploys the new code when I edit the file." | Only through `source_code_hash`. Without it the zip changes and Terraform shows no diff. |
| "The Lambda permission is optional because the rule targets the function." | Without `aws_lambda_permission` the rule fires and the invoke is denied. |
| "A message in the DLQ will be reprocessed automatically." | Never. Use **StartMessageMoveTask** (redrive) or a script, after fixing the cause. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| `kms_key_arn` | `30-security` |
| bucket name and ARN, `jobs_table_name`, `jobs_table_arn` | `40-data` |
| An instance to start and stop | `50-ec2` |

| You create here | Used by |
|---|---|
| Topic `plat-alerts` | Alarms (Post 14), the budget (Post 15), the pipeline (Post 12) |
| Queue and DLQ names | Alarms on queue depth (Post 14) |
| Function names | Dashboard and the verification script |

### Console clicks you no longer make

| In the AWS series you... | Here it is |
|---|---|
| **SQS, Create queue** twice, set redrive, edit access policy | `aws_sqs_queue.*` + `aws_sqs_queue_policy` |
| **S3, Properties, Event notifications, Create** | `aws_s3_bucket_notification.raw` |
| **Lambda, Create function**, upload code, set role, add trigger | `aws_lambda_function.*` + `aws_lambda_event_source_mapping` + `archive_file` |
| **SNS, Create topic, Create subscription, Access policy** | `aws_sns_topic*` |
| **EventBridge, Create rule** two times, with targets and permissions | `aws_cloudwatch_event_*` + `aws_lambda_permission` |

---

## Lab: Watch It React 🛠️

### 1. Plan and apply

```bash
export AWS_PROFILE=plat-admin AWS_REGION=us-east-1
scripts/tf.sh 60-events plan -var alert_email=you@example.com
```

```
Plan: 23 to add, 0 to change, 0 to destroy.
```

Twelve for the topic, queues and ingest function, five for the report function, three for the schedule, two for the state-change rule, and the email subscription. Without `alert_email` it's 22.

```bash
scripts/tf.sh 60-events apply -var alert_email=you@example.com
```

**Check your inbox and click "Confirm subscription"** or you will not receive anything below. Verify:

```bash
aws sns list-subscriptions-by-topic --topic-arn $(terraform -chdir=stacks/60-events output -raw topic_arn) \
  --query 'Subscriptions[0].SubscriptionArn' --output text
```

It prints an ARN once confirmed, and `PendingConfirmation` before.

### 2. Upload a file and follow it

```bash
B=$(terraform -chdir=stacks/40-data output -raw data_bucket)
printf 'id,value\n1,a\n2,b\n3,c\n' > /tmp/sample.csv
aws s3 cp /tmp/sample.csv s3://$B/raw/sample.csv
sleep 10
aws dynamodb get-item --table-name plat-jobs --key '{"job_id":{"S":"raw/sample.csv"}}' \
  --query 'Item.[status.S,rows.N,expires_at.N]' --output text
```

```
INGESTED  3  1789000000
```

Three rows (the header isn't counted), and an expiry about 30 days from now: the TTL attribute from Post 07 filled in by code.

### 3. Rehearse a failure

```bash
printf 'POISON\n' > /tmp/poison.csv
aws s3 cp /tmp/poison.csv s3://$B/raw/poison.csv
aws logs tail /aws/lambda/plat-ingest --since 5m | grep failed
```

```
failed 7d3e...: poison message in raw/poison.csv
```

The function fails, the message becomes visible again after 60 seconds, and the cycle repeats. After the **fourth** attempt it moves. Wait about four minutes:

```bash
DLQ=$(terraform -chdir=stacks/60-events output -raw dlq_url)
aws sqs get-queue-attributes --queue-url $DLQ --attribute-names ApproximateNumberOfMessages \
  --query 'Attributes.ApproximateNumberOfMessages' --output text
aws sqs receive-message --queue-url $DLQ --query 'Messages[0].Body' --output text | head -c 200
```

```
1
{"Records":[{"eventVersion":"2.1","eventSource":"aws:s3", ...
```

The DLQ holds the original S3 event. Fix the cause, then redrive:

```bash
aws sqs start-message-move-task --source-arn $(aws sqs get-queue-attributes --queue-url $DLQ --attribute-names QueueArn --query Attributes.QueueArn --output text)
```

(It fails again, of course, because the file still says `POISON`. Delete `raw/poison.csv` and purge the DLQ when you are done: `aws sqs purge-queue --queue-url $DLQ`.)

### 4. Run the report now

```bash
aws lambda invoke --function-name plat-report --cli-binary-format raw-in-base64-out /tmp/out.json >/dev/null && cat /tmp/out.json
```

```
{"INGESTED": 1}
```

Within a minute, an email with the subject **plat nightly report** arrives, with the same counts.

### 5. Trigger the state-change rule

If you have the instance from Post 08:

```bash
aws ec2 stop-instances --instance-ids $(terraform -chdir=stacks/50-ec2 output -raw instance_id)
```

You receive a notification for `stopping`'s final state, `stopped`, with a JSON body containing the instance id. Start it again afterwards. Because the stop and start are done outside Terraform, the instance state isn't drift as far as the plan is concerned.

### 6. Break it: remove the topic policy

```bash
aws sns set-topic-attributes --topic-arn $(terraform -chdir=stacks/60-events output -raw topic_arn) \
  --attribute-name Policy \
  --attribute-value '{"Version":"2012-10-17","Statement":[]}'
aws ec2 start-instances --instance-ids $IID; sleep 90; aws ec2 stop-instances --instance-ids $IID
```

No email arrives. The rule matched, EventBridge tried to publish and the topic refused. To see it: `aws cloudwatch get-metric-statistics --namespace AWS/Events --metric-name FailedInvocations --dimensions Name=RuleName,Value=plat-ec2-state-change --start-time $(date -u -d '15 min ago' +%FT%TZ) --end-time $(date -u +%FT%TZ) --period 900 --statistics Sum`. Then:

```bash
scripts/tf.sh 60-events plan
```

```
  # aws_sns_topic_policy.alerts will be updated in-place
Plan: 0 to add, 1 to change, 0 to destroy.
```

Apply, and the next state change reaches your inbox again.

### 7. Cause drift: disable the schedule

```bash
aws events disable-rule --name plat-nightly-report
scripts/tf.sh 60-events plan
```

```
  # aws_cloudwatch_event_rule.nightly will be updated in-place
  ~ state = "DISABLED" -> "ENABLED"
Plan: 0 to add, 1 to change, 0 to destroy.
```

A report that silently stops running is exactly the failure nobody notices for a month. `scripts/verify.sh` checks this rule's state for the same reason. Apply to re-enable it.

### 8. Resources you now have 📦

| Resource | Name | Notes |
|---|---|---|
| SNS topic | `plat-alerts` | Policy allows EventBridge, CloudWatch, Budgets |
| Queues | `plat-ingest-queue`, `plat-ingest-dlq` | Redrive after 3 receives |
| Functions | `plat-ingest`, `plat-report` | Python 3.12, 14-day log retention |
| Rules | `plat-nightly-report`, `plat-ec2-state-change` | |
| S3 notification | on `plat-data-...`, prefix `raw/` | One per bucket |

### Cleanup 🧹

Nothing here bills while idle. Leave it running: the next posts watch it. If you want to remove it: `scripts/tf.sh 60-events destroy`. The S3 notification is removed first, so the bucket is left with no notifications.

---

## Quick Quiz 🧠

**Q1.** You create the S3 notification and `apply` fails with `Unable to validate the following destination configurations`. What did you forget?

<details>
<summary>Show answer</summary>

The **queue policy** that allows `s3.amazonaws.com` to `SendMessage` from this bucket. S3 checks it when the notification is created, which is why the stack has `depends_on = [aws_sqs_queue_policy.ingest]`.

</details>

**Q2.** The EC2 state-change rule matches, but no email arrives. Where do you look first?

<details>
<summary>Show answer</summary>

At the **SNS topic policy**: it must allow `events.amazonaws.com` to publish. Check the rule's `FailedInvocations` metric to confirm EventBridge is being refused rather than not matching.

</details>

**Q3.** Why does `ingest.py` return a list of failed message ids instead of raising an exception?

<details>
<summary>Show answer</summary>

Raising fails the whole batch and all five messages return to the queue, including the four that were processed. Returning `batchItemFailures` (with `ReportBatchItemFailures` set on the mapping) retries **only** the failed ones.

</details>

**Q4.** How many times is a poison message tried before it lands in the DLQ with `maxReceiveCount = 3`?

<details>
<summary>Show answer</summary>

It is delivered three times; on the next receive attempt SQS moves it to the DLQ instead. With a 60-second visibility timeout that is roughly three to four minutes.

</details>

**Q5.** Why is the Lambda log group a Terraform resource?

<details>
<summary>Show answer</summary>

To control **retention**. If Lambda creates the group on first invocation, it never expires and has no tags, and a later attempt by Terraform to create the same name fails because it already exists.

</details>

---

## What's Next? 🚀

The platform runs and reacts. The next question is how new code gets to it without anyone typing commands: a connection to GitHub, a build, and a pipeline that deploys to the ECS service.

👉 [Post 12: Delivery as Code: GitHub, CodeBuild and CodePipeline](content/aws-terraform/12-delivery-as-code.md)

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
