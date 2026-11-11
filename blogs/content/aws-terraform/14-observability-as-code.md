---
title: "Observability as Code: Dashboards, Alarms and Log Metrics"
date: 2026-11-11
tags: [aws, terraform, cloudwatch, alarms, dashboards, metric-filters, container-insights, sns, intermediate]
description: Post 14 of the AWS on Terraform series. Five alarms with the right namespaces and dimensions, a log metric filter that counts failures, and a dashboard whose body is built from a list in locals, all conditional on the components they watch actually existing.
---

# Knowing When It Breaks 📈

By now there are eleven kinds of resource producing metrics and logs. This stack, `stacks/90-observe`, turns them into five alarms, a log-derived metric and one dashboard. It follows AWS series Post 21 almost exactly, with one change in approach: **an alarm only exists if the thing it watches exists**.

That rule matters because the platform has switches. An alarm on a service that was never created would sit in `INSUFFICIENT_DATA` forever, and an alarm with a "treat missing data as breaching" setting would be in `ALARM` the moment it exists.

---

## The Pieces 🧱

| Piece | Resource(s) | Created when |
|---|---|---|
| `plat-ingest-errors` | `aws_cloudwatch_metric_alarm.ingest_errors` | Always |
| `plat-dlq-not-empty` | `aws_cloudwatch_metric_alarm.dlq_not_empty` | Always |
| `plat-api-errors`, `plat-api-running-tasks` | `aws_cloudwatch_metric_alarm.api_errors`, `.api_running_tasks` | The ECS service exists |
| `plat-ec2-data-disk-high` | `aws_cloudwatch_metric_alarm.ec2_disk_high` | The instance exists |
| Log metric filter `plat-ingest-failures` | `aws_cloudwatch_log_metric_filter.ingest_failures` | Always |
| Dashboard `plat-overview` | `aws_cloudwatch_dashboard.overview` | Always (widgets vary) |

![Observability](content/aws-terraform/images/14-observe.svg)

```hcl
# stacks/90-observe/main.tf
locals {
  topic_arn   = data.terraform_remote_state.events.outputs.topic_arn
  dlq_name    = data.terraform_remote_state.events.outputs.dlq_name
  ingest_fn   = data.terraform_remote_state.events.outputs.ingest_function_name
  instance_id = data.terraform_remote_state.ec2.outputs.instance_id
  cluster     = data.terraform_remote_state.ecs.outputs.cluster_name
  service     = data.terraform_remote_state.ecs.outputs.service_name
  alb_suffix  = data.terraform_remote_state.ecs.outputs.alb_arn_suffix
  tg_suffix   = data.terraform_remote_state.ecs.outputs.target_group_arn_suffix

  ingest_log_group = "/aws/lambda/${local.ingest_fn}"

  # Alarms on things that are switched off would sit in ALARM or INSUFFICIENT_DATA forever.
  has_service  = local.service != null
  has_instance = local.instance_id != null
}
```

The first `locals` block reads the **outputs** of other stacks. `service` and `instance_id` are `null` when their stacks have the component switched off (that is what `one(...)` returned in Posts 08 and 09). `has_service` and `has_instance` turn that into booleans for `count`.

---

## Reading the Stack 📖

### Alarms: the namespace and dimensions are the whole point

```hcl
# stacks/90-observe/main.tf
resource "aws_cloudwatch_metric_alarm" "api_errors" {
  count = local.has_service ? 1 : 0

  alarm_name          = "plat-api-errors"
  alarm_description   = "The API returned 5 or more 5xx responses in 5 minutes"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  dimensions          = { LoadBalancer = local.alb_suffix }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [local.topic_arn]
  ok_actions          = [local.topic_arn]
}

resource "aws_cloudwatch_metric_alarm" "api_running_tasks" {
  count = local.has_service ? 1 : 0

  alarm_name          = "plat-api-running-tasks"
  alarm_description   = "Fewer than one API task is running"
  namespace           = "ECS/ContainerInsights"
  metric_name         = "RunningTaskCount"
  dimensions          = { ClusterName = local.cluster, ServiceName = coalesce(local.service, "none") }
  statistic           = "Minimum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [local.topic_arn]
}
```

An alarm names a metric with **four** things: namespace, name, dimensions and statistic. Getting any wrong produces a valid alarm that watches nothing.

* **`AWS/ApplicationELB` dimensions use the ARN suffix**, such as `app/plat-alb/50dc6c495c0c9188`, not the name. That is why `52-ecs` exports `alb_arn_suffix`.
* **`ECS/ContainerInsights`** only exists because Post 09 enabled Container Insights on the cluster. Without it the metric `RunningTaskCount` is never published.
* `treat_missing_data`: `notBreaching` for error counts (no data means no errors), `breaching` for running tasks (no data means no tasks).
* `alarm_actions` sends to `plat-alerts`. `ok_actions` on the first alarm also tells you when it recovers.
* `coalesce(local.service, "none")` keeps the expression valid when the value is null. It is only evaluated when `count` is 1, but Terraform still type-checks it.

```hcl
# stacks/90-observe/main.tf
resource "aws_cloudwatch_metric_alarm" "ingest_errors" {
  alarm_name          = "plat-ingest-errors"
  alarm_description   = "plat-ingest reported an error"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = local.ingest_fn }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [local.topic_arn]
}

resource "aws_cloudwatch_metric_alarm" "dlq_not_empty" {
  alarm_name          = "plat-dlq-not-empty"
  alarm_description   = "A message landed in the dead-letter queue"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = local.dlq_name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [local.topic_arn]
}

resource "aws_cloudwatch_metric_alarm" "ec2_disk_high" {
  count = local.has_instance ? 1 : 0

  alarm_name          = "plat-ec2-data-disk-high"
  alarm_description   = "Root volume of plat-ec2 is above the threshold (metric comes from the CloudWatch agent)"
  namespace           = "CWAgent"
  metric_name         = "disk_used_percent"
  dimensions          = { InstanceId = coalesce(local.instance_id, "none"), path = "/" }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = var.disk_alarm_percent
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [local.topic_arn]
}
```

The **dead-letter queue** alarm is the most important of the five. A message in the DLQ means work was lost to a bug; it fires at a threshold of one, with a one-minute period. The **EC2 disk** alarm watches the `CWAgent` namespace, which exists only because the instance runs the agent configured in Post 08, with the dimensions `InstanceId` and `path` set there. The dimension list must match **exactly**; a missing `path` and the alarm sees no data.

### Turning log lines into a number

```hcl
# stacks/90-observe/main.tf
resource "aws_cloudwatch_log_metric_filter" "ingest_failures" {
  name           = "plat-ingest-failures"
  log_group_name = local.ingest_log_group
  pattern        = "\"failed\""

  metric_transformation {
    name          = "IngestFailures"
    namespace     = "Plat"
    value         = "1"
    default_value = "0"
    unit          = "Count"
  }
}
```

The function prints `failed <id>: <reason>` for every record it can't process. The filter pattern `"failed"` matches lines containing the word, and each match adds `1` to a metric called `IngestFailures` in the `Plat` namespace. Two details:

* **`default_value = "0"`** publishes a zero when there are no matches, so graphs show a flat line, not gaps.
* Filters count only lines logged **after** they exist. They don't read history.

### The dashboard

The widgets are plain HCL objects in a list.

```hcl
# stacks/90-observe/main.tf
resource "aws_cloudwatch_dashboard" "overview" {
  dashboard_name = "plat-overview"
  dashboard_body = jsonencode({ widgets = local.widgets })
}
```

The body is `jsonencode` over `local.widgets`, and `local.widgets` is a `concat` of three lists: the two always-present widgets, then the service widgets **or an empty list**, then the instance widget **or an empty list**. The conditional-list idiom is the same one `dynamic` blocks use, applied to data. Written as a JSON file you would have to maintain three versions; as a list expression you have one.

The dashboard is cheap, but remember it is **one API object**: any single widget with a bad metric definition rejects the whole `PutDashboard` call with `InvalidParameterInput`.

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "An alarm in `INSUFFICIENT_DATA` is fine, it just hasn't fired." | It often means the **dimensions or namespace are wrong**, or the thing isn't emitting. A healthy alarm moves to `OK` within a few periods. |
| "ALB metrics use the load balancer name." | They use the **ARN suffix** (`app/name/hash`). |
| "ECS task metrics are always available." | `ECS/ContainerInsights` needs Container Insights enabled on the cluster. |
| "The CloudWatch agent metrics are in `AWS/EC2`." | They are in **`CWAgent`** and carry only the dimensions in the agent configuration. |
| "An alarm with no `alarm_actions` still helps." | It changes state silently. Nothing is notified unless an action is attached. |
| "`treat_missing_data = notBreaching` is always safe." | For a metric that must exist, such as running tasks, it hides the outage it should report. |
| "A metric filter backfills old logs." | It counts new lines only. |
| "Create the alarms first, the service later." | Terraform reads the service from remote state at plan time. If you switch the service on later, **re-apply this stack** so the alarms and widgets appear. |
| "A dashboard is configuration, so errors surface late." | A bad widget makes the whole dashboard call fail at apply. |
| "Alarms are free." | Each standard alarm bills a small monthly amount. Five is negligible; five hundred isn't. |
| "The SNS topic needs no policy for alarms." | CloudWatch must be allowed to publish. It is, in Post 11's topic policy. |
| "A single threshold fits every environment." | Disk percent is a variable (`disk_alarm_percent`) so a test environment can differ from production. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| `topic_arn`, `dlq_name`, `ingest_function_name` | `60-events` |
| `instance_id` | `50-ec2` |
| `cluster_name`, `service_name`, `alb_arn_suffix`, `target_group_arn_suffix` | `52-ecs` |

| You create here | Used by |
|---|---|
| Alarms | Your inbox, through `plat-alerts` |
| Dashboard `plat-overview` | You |
| Metric `Plat/IngestFailures` | Dashboard and future alarms |

### Console clicks you no longer make

| In the AWS series you... | Here it is |
|---|---|
| **CloudWatch, Alarms, Create alarm**, five times, picking each metric and its dimensions | five `aws_cloudwatch_metric_alarm` resources |
| **Log groups, Metric filters, Create** | `aws_cloudwatch_log_metric_filter` |
| **Dashboards, Create, Add widget** several times | `aws_cloudwatch_dashboard.overview` and `local.widgets` |
| Select the SNS action on every alarm | `alarm_actions = [local.topic_arn]` |

---

## Lab: Watch the Watchers 🛠️

### 1. Plan and apply

At this point the instance exists and the service does not:

```bash
export AWS_PROFILE=plat-admin AWS_REGION=us-east-1
scripts/tf.sh 90-observe plan
```

```
Plan: 5 to add, 0 to change, 0 to destroy.
```

Two always-on alarms, the instance alarm, the metric filter and the dashboard.

```bash
scripts/tf.sh 90-observe apply
aws cloudwatch describe-alarms --alarm-name-prefix plat- --query 'MetricAlarms[].[AlarmName,StateValue]' --output text
```

```
plat-dlq-not-empty        OK
plat-ec2-data-disk-high   OK
plat-ingest-errors        OK
```

Some may say `INSUFFICIENT_DATA` for the first few minutes. That is normal.

### 2. Bring up the service and re-apply

Make the downstream change visible:

```bash
scripts/tf.sh 52-ecs apply -var enable_service=true
scripts/tf.sh 90-observe plan
```

```
  # aws_cloudwatch_dashboard.overview will be updated in-place
  # aws_cloudwatch_metric_alarm.api_errors[0] will be created
  # aws_cloudwatch_metric_alarm.api_running_tasks[0] will be created
Plan: 2 to add, 1 to change, 0 to destroy.
```

The stack noticed, through remote state, that the service now exists. Apply it. The dashboard now has six widgets:

```bash
scripts/tf.sh 90-observe apply
aws cloudwatch get-dashboard --dashboard-name plat-overview --query DashboardBody --output text | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["widgets"]))'
```

```
6
```

Two always-on, three for the service, one for the instance. Open the dashboard in the console to see them.

### 3. Fire an alarm and receive the email

Waiting for a real failure is slow. Set the state by hand to test the path from alarm to inbox:

```bash
aws cloudwatch set-alarm-state --alarm-name plat-dlq-not-empty --state-value ALARM --state-reason "lab test"
```

An email from `plat-alerts` arrives within a minute, subject starting `ALARM: "plat-dlq-not-empty"`. CloudWatch re-evaluates the alarm on its next period and sets it back to `OK`, which sends a second email only if an OK action exists (this alarm has none).

### 4. Fire it for real

```bash
B=$(terraform -chdir=stacks/40-data output -raw data_bucket)
printf 'POISON\n' > /tmp/poison.csv && aws s3 cp /tmp/poison.csv s3://$B/raw/poison2.csv
```

About four minutes later (Post 11), the message reaches the DLQ and the alarm goes to `ALARM`. Check both the alarm and the new metric:

```bash
aws cloudwatch describe-alarms --alarm-names plat-dlq-not-empty --query 'MetricAlarms[0].StateValue' --output text
aws cloudwatch get-metric-statistics --namespace Plat --metric-name IngestFailures \
  --start-time $(date -u -d '30 min ago' +%FT%TZ) --end-time $(date -u +%FT%TZ) --period 300 --statistics Sum \
  --query 'sort_by(Datapoints,&Timestamp)[].Sum' --output text
```

```
ALARM
0.0  3.0  0.0
```

Three failed attempts, counted by the metric filter from the function's log lines, and none of those numbers existed before the filter. Delete the file and purge the DLQ to clear the alarm: `aws sqs purge-queue --queue-url $(terraform -chdir=stacks/60-events output -raw dlq_url)`.

### 5. Break it: remove the service and look at the stale alarms

```bash
scripts/tf.sh 52-ecs apply
sleep 150
aws cloudwatch describe-alarms --alarm-names plat-api-running-tasks --query 'MetricAlarms[0].StateValue' --output text
```

```
ALARM
```

You switched the service off on purpose and the alarm, which still exists, reports a missing task as `breaching`. Plan this stack and the picture is clear:

```bash
scripts/tf.sh 90-observe plan
```

```
Plan: 0 to add, 1 to change, 2 to destroy.
```

Two alarms to destroy and the dashboard to shrink. **Each toggle in an upstream stack needs a re-apply of its observers**; `make up` and `make pause` do that in the right order for you (Post 19).

### 6. Cause drift: mute an alarm

```bash
aws cloudwatch disable-alarm-actions --alarm-names plat-dlq-not-empty
scripts/tf.sh 90-observe plan
```

```
  # aws_cloudwatch_metric_alarm.dlq_not_empty will be updated in-place
  ~ actions_enabled = false -> true
```

The most dangerous kind of change: nothing looks different in the console list, and no notification ever comes again. Apply to re-enable it. `verify.sh` counts alarms for a similar reason: it catches a missing alarm, though not a muted one, which only the plan finds.

### 7. Resources you now have 📦

| Resource | Name | Notes |
|---|---|---|
| Alarms | `plat-dlq-not-empty`, `plat-ingest-errors`, `plat-ec2-data-disk-high`, and with the service `plat-api-errors`, `plat-api-running-tasks` | Cents per month |
| Metric filter | `plat-ingest-failures` | Namespace `Plat` |
| Dashboard | `plat-overview` | |

### Cleanup 🧹

Nothing to switch off. These cost cents; keep them.

---

## Quick Quiz 🧠

**Q1.** The ALB alarm exists and stays in `INSUFFICIENT_DATA` although the site gets traffic. What do you check?

<details>
<summary>Show answer</summary>

The **dimension**. ALB metrics are keyed by the load balancer's **ARN suffix** (`app/plat-alb/<hash>`), not its name. A name there gives a valid alarm on a metric that does not exist.

</details>

**Q2.** Why is `treat_missing_data` `breaching` for running tasks and `notBreaching` for 5xx errors?

<details>
<summary>Show answer</summary>

For errors, no data means no errors. For running tasks, **no data means no tasks**, which is the outage the alarm exists to report.

</details>

**Q3.** You switch the service on, but the dashboard doesn't show the API widgets. What is missing?

<details>
<summary>Show answer</summary>

A re-apply of `90-observe`. It reads the service name from remote state at plan time, so the widgets and alarms appear only after the next plan and apply of this stack.

</details>

**Q4.** What does `default_value = "0"` do on the metric filter?

<details>
<summary>Show answer</summary>

It publishes a zero data point for periods with no matching log lines, so the metric is a continuous line, and alarms and graphs don't need to treat missing data specially.

</details>

**Q5.** Why is a muted alarm worse than a missing one for operations?

<details>
<summary>Show answer</summary>

It looks present and healthy in lists and dashboards, and it never notifies anyone. Only a **plan** reveals `actions_enabled` differing from the configuration.

</details>

---

## What's Next? 🚀

A platform that nobody pays attention to still costs money. Next: a budget, anomaly detection, and the cost allocation tags that make the bill readable.

👉 [Post 15: Cost as Code: Budgets, Anomaly Detection and Tags](content/aws-terraform/15-cost-as-code.md)

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
