---
title: "SQS, SNS and EventBridge"
date: 2026-11-08
tags: [aws, sqs, sns, eventbridge, dead-letter-queue, fan-out, event-driven, intermediate]
description: Post 14 of the AWS series. What each messaging service is for, visibility timeouts and dead-letter queues, why every cross-service permission is a resource policy, and a lab that rebuilds the ingest flow as S3, SNS, SQS, Lambda with a DLQ, then adds scheduled and event-driven EventBridge rules.
---

# Three Services That Move Events Around 📨

In Post 13, S3 called Lambda directly. It worked, until we broke a permission and the event vanished after two retries. Real pipelines add a **buffer** between producer and consumer so a failure becomes a *delay* and not a *loss*.

AWS has three messaging services that are easy to mix up:

| Service | Shape | Delivery | Use it when |
|---|---|---|---|
| **SNS** (Simple Notification Service) | **Publish/subscribe**: one message, many subscribers | **Pushes** to each subscriber (SQS, Lambda, email, HTTPS, ...) | One event must reach several consumers, or notify humans |
| **SQS** (Simple Queue Service) | **Queue**: messages wait until a consumer takes one | Consumers **pull** (Lambda does the polling for you) | You need buffering, retries and a dead-letter queue |
| **EventBridge** | **Event bus + rules**: match events and route them | Pushes to targets; also runs **schedules** | Reacting to AWS service events, SaaS events, or time |

This post wires all three into the platform.

![The ingest flow with SNS, SQS, a DLQ and EventBridge](content/aws/images/14-messaging.svg)

---

## SQS: the Details That Matter 📬

| Concept | Detail |
|---|---|
| **Standard queue** | At-least-once delivery, best-effort ordering, nearly unlimited throughput |
| **FIFO queue** | Exactly-once processing within a deduplication window, strict order per message group, lower throughput. Name must end in `.fifo` |
| **Visibility timeout** | After a consumer receives a message it is **hidden** for this long. If it isn't deleted in time, it becomes visible and is delivered again |
| **Long polling** | `ReceiveMessageWaitTimeSeconds` up to 20 s, which reduces empty receives and cost |
| **Retention** | 1 minute to 14 days (default 4 days) |
| **Message size** | Up to 256 KB |
| **Dead-letter queue (DLQ)** | A second queue that receives messages after **`maxReceiveCount`** failed receives |
| **Redrive** | Moves messages from the DLQ back to a source queue after you fix the bug |

### Lambda as the consumer

Lambda's **event source mapping** polls the queue, invokes your function with a **batch**, and deletes the messages **only if the invocation succeeds**. With **partial batch response** enabled, your function lists the failed message IDs and only those return to the queue. `plat-ingest` already does this.

---

## SNS: the Details That Matter 📣

| Concept | Detail |
|---|---|
| **Topic** | A named channel. Publishers send to it |
| **Subscription** | A destination plus a protocol. Email subscriptions need **confirmation** |
| **Filter policy** | Delivers only matching messages to a subscriber. By default it matches **message attributes**, not the body |
| **Raw message delivery** | For SQS/HTTP, delivers just the payload and not the JSON envelope with metadata |
| **Topic policy** | Controls **who may publish** and subscribe |
| **Fan-out** | One topic, several SQS queues or Lambdas, each independent |

## EventBridge: the Details That Matter 🕸️

| Concept | Detail |
|---|---|
| **Event bus** | The default bus receives events from AWS services. You can create custom buses |
| **Rule** | Either an **event pattern** (match on JSON fields) or a **schedule** (`rate(...)` or `cron(...)`, in **UTC**) |
| **Target** | Lambda, SNS, SQS, Step Functions, ECS tasks, and more. A rule can have several |
| **Target DLQ** | An optional SQS queue for events EventBridge cannot deliver |
| **EventBridge Scheduler** | A newer, separate scheduling service with time zones and one-time schedules. Rules remain the classic "CloudWatch Events" way |

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "The visibility timeout can be anything." | For Lambda it must be **at least the function timeout**, and AWS recommends about **six times** it, so a batch isn't redelivered while still being processed. |
| "The DLQ must be FIFO if the source is FIFO." | The DLQ **type must match** the source: a FIFO queue's DLQ must be FIFO, and a standard queue's must be standard. |
| "A message sits in the DLQ for 4 days." | The **original enqueue time** is kept. If the DLQ retention equals the source's, a message can expire almost immediately. Give the DLQ **longer retention** (up to 14 days). |
| "SQS guarantees one delivery." | Standard queues deliver **at least once**. Duplicates happen. Your consumer must be idempotent (as `plat-ingest` is). |
| "A Lambda consumer deletes a message after it reads it." | Only after the function **returns successfully**. If the function raises, the whole batch returns, unless you use partial batch responses. |
| "SNS filter policies look at the message body." | By default only **message attributes**. Filtering on body content needs the policy scope **`MessageBody`**. S3 notifications have no attributes, so key filtering belongs in the S3 notification settings or the consumer. |
| "S3 can publish to any topic in my account." | The **topic policy** must allow `s3.amazonaws.com` to publish, and good policies add `aws:SourceArn` and `aws:SourceAccount` conditions to prevent the **confused deputy** problem. |
| "Encrypting the topic with the AWS managed key is safe." | **AWS services can't publish** to a topic encrypted with `aws/sns`, because that key's policy can't be changed to allow them. Use a customer-managed key whose policy allows the service, or leave the topic unencrypted for service events. |
| "SNS to SQS 'just works' once subscribed." | The **queue policy** must allow `sns.amazonaws.com` to `sqs:SendMessage` from that topic. The console adds this when you subscribe from the queue page. A missing policy shows as a subscription that never delivers. |
| "Cron in EventBridge uses my time zone." | Rules use **UTC**. The expression also has **six fields** (`cron(0 6 * * ? *)`) and requires `?` in either day-of-month or day-of-week. Scheduler supports time zones. |
| "An event pattern with extra fields still matches." | A pattern must match the fields **it names**; fields it doesn't mention are ignored. But values match **exactly** and arrays mean *any of*. A misspelled key matches nothing, silently. |
| "Scheduled rules are precise." | Granularity is **one minute**, and the run may be a little late. Delivery is at least once. |
| "Email subscriptions are active immediately." | The recipient must click **Confirm subscription**. Until then, publishes go nowhere. |
| "S3 can send the same event to Lambda and SNS." | Event configurations must not **overlap** (same event type, same prefix and suffix) on one bucket. Replace one destination with the other, or route everything through SNS or EventBridge. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| Bucket, `raw/` prefix, `events.csv` | Post 06 |
| `plat-ingest` (already handles SNS-wrapped SQS messages and partial batch failures) | Post 13 |
| `plat-jobs` and `status-created_idx` | Post 08 |
| `plat-ec2` (a source of state-change events) | Post 10 |

| You create here | Used by |
|---|---|
| Topic `plat-uploads`, queue `plat-ingest-queue`, DLQ `plat-ingest-dlq` | The production ingest path |
| Topic **`plat-alerts`** with your email subscribed | **CloudWatch alarms** (21), **Budgets** (22), pipeline notifications (18) |
| Function `plat-report` and the nightly rule | Operational reporting |
| Metrics `ApproximateNumberOfMessagesVisible`, `Errors` | Alarms in Post 21 |

---

## Lab: Build the Messaging Backbone 🛠️

Work as Jim, in **N. Virginia**. Replace `123456789012` with your account ID everywhere.

### 1. Create the queues (DLQ first)

**SQS, Create queue**:

1. **Standard**, name **`plat-ingest-dlq`**. Message retention **14 days**. Leave encryption at **SSE-SQS** (the default). Create.
2. **Standard**, name **`plat-ingest-queue`**:

| Setting | Value |
|---|---|
| Visibility timeout | **180 seconds** (six times the 30 s function timeout) |
| Message retention | 4 days |
| Receive message wait time | **20 seconds** (long polling) |
| Dead-letter queue | **Enabled**, choose `plat-ingest-dlq` |
| Maximum receives | **3** |

Tag both `project = plat`.

### 2. Create the topics

**SNS, Topics, Create topic**, type **Standard**.

**`plat-uploads`**: leave encryption **off** (see the nuance above). Under **Access policy**, switch to **Advanced** and replace it with:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowS3Publish",
      "Effect": "Allow",
      "Principal": { "Service": "s3.amazonaws.com" },
      "Action": "SNS:Publish",
      "Resource": "arn:aws:sns:us-east-1:123456789012:plat-uploads",
      "Condition": {
        "ArnLike":      { "aws:SourceArn": "arn:aws:s3:::plat-data-123456789012-us-east-1" },
        "StringEquals": { "aws:SourceAccount": "123456789012" }
      }
    }
  ]
}
```

The default policy that the console shows (which allows your account's owner to publish) is replaced, so you'll still administer the topic through IAM. If the editor insists on keeping the owner statement, add it back.

**`plat-alerts`**: a second Standard topic, default settings. Create a subscription: protocol **Email**, endpoint **your address**. Open the confirmation email and click **Confirm subscription**. The subscription's status must read **Confirmed**.

### 3. Subscribe the queue to the topic

Open the queue **`plat-ingest-queue`**, tab **SNS subscriptions**, **Subscribe to Amazon SNS topic**, choose `plat-uploads`, **Save**. Leave **raw message delivery off**; the function unwraps the envelope. Now read the **Access policy** tab of the queue and look for the statement the console added:

```json
{
  "Effect": "Allow",
  "Principal": { "Service": "sns.amazonaws.com" },
  "Action": "sqs:SendMessage",
  "Resource": "arn:aws:sqs:us-east-1:123456789012:plat-ingest-queue",
  "Condition": { "ArnEquals": { "aws:SourceArn": "arn:aws:sns:us-east-1:123456789012:plat-uploads" } }
}
```

That statement is what allows SNS to deliver. If it's missing, add it by hand.

### 4. Move the S3 notification from Lambda to SNS

1. Open the function `plat-ingest`, **Configuration, Triggers**, select the S3 trigger and **Delete**.
2. **S3, `plat-data-...` bucket, Properties, Event notifications, Create event notification**:

| Field | Value |
|---|---|
| Name | `raw-csv-created` |
| Prefix / suffix | `raw/` / `.csv` |
| Event types | **All object create events** |
| Destination | **SNS topic** `plat-uploads` |

Save. If S3 reports *Unable to validate the destination configuration*, the topic policy has the wrong bucket ARN or account ID. S3 sends a test event while saving, which is why the policy must be right first.

### 5. Connect the queue to the function

1. Add `AWSLambdaSQSQueueExecutionRole` to **`plat-ingest-role`** (it allows `ReceiveMessage`, `DeleteMessage` and `GetQueueAttributes`).
2. Function `plat-ingest`, **Add trigger, SQS**:

| Setting | Value |
|---|---|
| Queue | `plat-ingest-queue` |
| Batch size | **5** |
| Batch window | **5 seconds** |
| Report batch item failures | **Enabled** |
| Maximum concurrency | **5** |

Add it. (Lambda requires a minimum of 2 for maximum concurrency.) The mapping starts in `Enabling`; wait until it says **Enabled**.

### 6. Send a real file through the whole path

In CloudShell:

```bash
BUCKET=plat-data-$(aws sts get-caller-identity --query Account --output text)-us-east-1
aws s3 cp s3://$BUCKET/raw/events.csv events.csv
head -2001 events.csv > day4.csv                     # header + 2000 rows
aws s3 cp day4.csv s3://$BUCKET/raw/day4.csv

sleep 30
aws logs tail /aws/lambda/plat-ingest --since 5m --format short | grep -E "recorded|duplicate|ERROR"
```

```text
[INFO] recorded ingest-5d7e9b21c03a rows=2000 key=raw/day4.csv
```

Trace what happened: **S3 → SNS (`plat-uploads`) → SQS (`plat-ingest-queue`) → Lambda → DynamoDB**. Verify the queue is empty again:

```bash
Q=$(aws sqs get-queue-url --queue-name plat-ingest-queue --query QueueUrl --output text)
aws sqs get-queue-attributes --queue-url $Q \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible
```

```json
{ "Attributes": { "ApproximateNumberOfMessages": "0", "ApproximateNumberOfMessagesNotVisible": "0" } }
```

### 7. Break it on purpose: a poison message

Send a message the function can't parse. **SQS, `plat-ingest-queue`, Send and receive messages**, body `this is not json`, **Send message**. Or:

```bash
aws sqs send-message --queue-url $Q --message-body "this is not json"
```

The function raises `JSONDecodeError`, reports the message ID as failed, and the **same message** returns after the 180 s visibility timeout. After the **third** failed receive, SQS moves it to the DLQ. Meanwhile real uploads keep flowing, because only that message was returned. This takes about **7 minutes**. Continue with the next two steps and check back:

```bash
DLQ=$(aws sqs get-queue-url --queue-name plat-ingest-dlq --query QueueUrl --output text)
aws sqs get-queue-attributes --queue-url $DLQ --attribute-names ApproximateNumberOfMessages
```

```json
{ "Attributes": { "ApproximateNumberOfMessages": "1" } }
```

In the console, **`plat-ingest-dlq`, Poll for messages** to read it. Then **Purge** the DLQ. For a real incident you would fix the bug and use **Start DLQ redrive** to send the messages back to the source queue.

### 8. A scheduled report with EventBridge

**The function.** Lambda, Create function, `plat-report`, Python 3.12, new role **`plat-report-role`** (basic execution). Add this inline policy `plat-report-access` to the role (use your account ID):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": "dynamodb:Query",
      "Resource": "arn:aws:dynamodb:us-east-1:123456789012:table/plat-jobs/index/status-created_idx" },
    { "Effect": "Allow", "Action": "sns:Publish",
      "Resource": "arn:aws:sns:us-east-1:123456789012:plat-alerts" }
  ]
}
```

Replace the code, set the environment variable `ALERT_TOPIC_ARN` to the `plat-alerts` ARN, set the timeout to 30 s, and **Deploy**:

**`report.py`** (paste into `lambda_function.py`)

```python
import os

import boto3

ddb = boto3.client("dynamodb")
sns = boto3.client("sns")
TOPIC = os.environ["ALERT_TOPIC_ARN"]


def handler(event, context):
    jobs, rows, token = 0, 0, None
    while True:
        kwargs = dict(
            TableName="plat-jobs",
            IndexName="status-created_idx",
            KeyConditionExpression="#s = :d",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":d": {"S": "DONE"}},
        )
        if token:
            kwargs["ExclusiveStartKey"] = token
        page = ddb.query(**kwargs)
        for item in page["Items"]:
            jobs += 1
            rows += int(item.get("rows", {}).get("N", "0"))
        token = page.get("LastEvaluatedKey")
        if not token:
            break

    message = f"Platform report: {jobs} completed jobs, {rows} rows ingested in total."
    sns.publish(TopicArn=TOPIC, Subject="plat report", Message=message)
    return {"jobs": jobs, "rows": rows}
```

Click **Test** with an empty event `{}`. The response shows the totals, and an email arrives from `plat-alerts`.

**The schedule.** **EventBridge, Rules, Create rule**:

| Field | Value |
|---|---|
| Name | `plat-nightly-report` |
| Event bus | `default` |
| Rule type | **Schedule** |
| Schedule pattern | **A schedule that runs at a regular rate**, `5 minutes` for the demo |
| Target | **Lambda function**, `plat-report` |

Create it. The console adds the permission that lets `events.amazonaws.com` invoke the function (check **Configuration, Permissions, Resource-based policy**). Wait for one email, then **edit the rule** to a cron expression, **`cron(0 6 * * ? *)`** (06:00 UTC daily), so it doesn't keep emailing you.

### 9. An event-pattern rule

React to something that *happened* in AWS. **EventBridge, Create rule**:

| Field | Value |
|---|---|
| Name | `plat-ec2-state-change` |
| Rule type | **Rule with an event pattern** |
| Event source | **AWS events**, service **EC2**, event type **EC2 Instance State-change Notification** |
| Target | **SNS topic** `plat-alerts` |

Or paste this pattern in **Custom pattern**:

```json
{
  "source": ["aws.ec2"],
  "detail-type": ["EC2 Instance State-change Notification"],
  "detail": { "state": ["running", "stopped"] }
}
```

Then start your `plat-ec2` instance from Post 10. Within a minute you receive an email whose body is the event JSON (`"state": "pending"` is not matched; `"running"` is). Stop the instance again.

If no email arrives, add this statement to the `plat-alerts` topic policy, because EventBridge needs permission to publish to it:

```json
{
  "Sid": "AllowEventBridgePublish",
  "Effect": "Allow",
  "Principal": { "Service": "events.amazonaws.com" },
  "Action": "SNS:Publish",
  "Resource": "arn:aws:sns:us-east-1:123456789012:plat-alerts"
}
```

### 10. Resources you now have 📦

| Resource | Name |
|---|---|
| Queues | `plat-ingest-queue` (visibility 180 s, maxReceive 3), `plat-ingest-dlq` (14 days) |
| Topics | `plat-uploads` (S3 may publish), `plat-alerts` (your email, confirmed) |
| S3 notification | `raw-csv-created` to `plat-uploads` |
| Event source mapping | `plat-ingest-queue` to `plat-ingest` (batch 5, partial failures) |
| Function + role | `plat-report`, `plat-report-role` |
| EventBridge rules | `plat-nightly-report` (cron), `plat-ec2-state-change` (pattern) |

### Cleanup 🧹

SQS, SNS and EventBridge cost almost nothing at lab volumes. Keep everything: Posts 18, 21 and 22 reuse `plat-alerts`. Make sure `plat-nightly-report` is on the cron schedule, not 5 minutes.

---

## Quick Quiz 🧠

**Q1.** Your Lambda timeout is 60 seconds and the queue's visibility timeout is 30. What can go wrong?

<details>
<summary>Show answer</summary>

Messages become visible again **while the function is still working**, so another invocation processes them concurrently: duplicate work. Set the visibility timeout to at least the function timeout, ideally about six times it.

</details>

**Q2.** A poisoned message keeps failing. Where does it end up and what stops it blocking other messages?

<details>
<summary>Show answer</summary>

After **`maxReceiveCount`** failed receives it moves to the **DLQ**. With **partial batch responses** only the failed message returns to the queue, so valid messages in the same batch complete.

</details>

**Q3.** The S3 notification to your SNS topic can't be saved. What do you check first?

<details>
<summary>Show answer</summary>

The **topic policy**: it must allow `s3.amazonaws.com` to `SNS:Publish` with a `SourceArn` that matches the bucket and a `SourceAccount` that matches your account. Also check the topic isn't encrypted with an AWS managed key.

</details>

**Q4.** Why does the queue keep an SNS envelope, and how does `plat-ingest` cope?

<details>
<summary>Show answer</summary>

Without **raw message delivery**, SNS wraps the S3 event JSON inside a `Message` field alongside metadata. The function checks for `Message` and parses the inner JSON before reading `Records`.

</details>

**Q5.** Your `cron(0 6 * * ? *)` rule fires at 1 a.m. New York time in winter and 2 a.m. in summer. Why?

<details>
<summary>Show answer</summary>

EventBridge rules always use **UTC**. New York's offset changes with daylight saving time. For a fixed local time use **EventBridge Scheduler**, which supports time zones.

</details>

---

## What's Next? 🚀

You now have the platform's data path and its event spine, all created by hand in the console. That works for learning, and it is exactly what you cannot do for the second environment. Before we automate the build, we need the habit that makes automation safe: **version control**, and the way a `git push` can start things.

👉 **[Post 15: Git and Webhooks](content/aws/15-git-and-webhooks.md)**: the Git model you actually need, a GitHub repository for the platform, and a webhook that proves how a push becomes an event.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
