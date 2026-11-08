---
title: "CloudWatch, Agent and Alarms"
date: 2026-11-08
tags: [aws, cloudwatch, alarms, metrics, logs, metric-filters, cloudwatch-agent, dashboards, intermediate]
description: Post 21 of the AWS series. How metrics, logs and alarms relate, why memory and disk are invisible by default, how alarms evaluate missing data, and a lab that installs the CloudWatch agent on plat-ec2, turns log lines into metrics and wires alarms across the platform into plat-alerts.
---

# Knowing It's Broken Before Dave Tells You 🔭

The platform has about a dozen moving parts, and every one can fail in a way that produces no error at all: a queue that stops draining, a disk that fills, an endpoint that bills quietly, an API that returns 502 to the one route nobody tests. **CloudWatch** is where AWS services report on themselves, and where you decide which signals deserve to wake somebody.

![Metrics, logs, alarms and where each signal comes from](content/aws/images/21-cloudwatch.svg)

---

## The Model in One Table 📊

| Concept | Meaning |
|---|---|
| **Namespace** | A container for metrics, for example `AWS/SQS`, `AWS/Lambda`, `CWAgent`, or your own |
| **Metric** | A named series of data points: `ApproximateNumberOfMessagesVisible` |
| **Dimensions** | Name/value pairs that identify *which* series: `QueueName = plat-ingest-dlq`. **A different set of dimensions is a different metric** |
| **Statistic and period** | How raw points are combined (Sum, Average, Maximum, percentiles) over a window (60 s, 300 s, ...) |
| **Log group / stream** | A group of logs with shared retention and permissions; a stream is one source within it |
| **Metric filter** | A pattern that turns matching log lines into metric data points |
| **Logs Insights** | A query language for searching and aggregating logs |
| **Alarm** | Watches one metric (or a math expression) against a threshold and takes actions on state change |
| **Dashboard** | A page of widgets for people |

### Alarm states and evaluation

| State | Meaning |
|---|---|
| **OK** | Not breaching |
| **ALARM** | Breaching for `M` out of `N` evaluation periods |
| **INSUFFICIENT_DATA** | Not enough data to decide (new alarm, or the metric stopped reporting) |

Every alarm has a **treat missing data** setting: `missing` (stay as is), `notBreaching`, `breaching`, `ignore`. The right choice depends on the metric. A queue-depth metric that only exists while there are messages needs `notBreaching`. A heartbeat metric that should always arrive wants `breaching`.

### What CloudWatch can't see by itself

AWS sees an EC2 instance **from outside**: CPU, network, disk I/O, status checks. It can't see **inside** the operating system: used memory, filesystem usage, processes. That needs the **CloudWatch agent**, which publishes to the `CWAgent` namespace and ships log files.

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "EC2 shows memory and disk in CloudWatch." | Not by default. Only the **agent** (or a script) reports memory and filesystem usage. |
| "My alarm never fires, so everything is healthy." | Maybe it's in **INSUFFICIENT_DATA** because the dimensions don't match any real metric. Check the alarm's state and graph. |
| "Dimensions are loose labels." | They are part of the metric's **identity**. `path=/data,device=nvme1n1,fstype=xfs` is a different metric from `path=/`. Copy dimensions from `list-metrics`. |
| "Basic EC2 monitoring is real time." | Default is **5-minute** granularity. Detailed monitoring is 1 minute (extra cost). Agent metrics can be 60 s or finer. |
| "Metric filters analyse my existing logs." | They apply only to **new events** after the filter is created. |
| "Logs are kept for as long as I need." | The default retention is **never expire**, and storage bills forever. Set retention on every group. |
| "One alarm per resource is fine." | Alarms cost per alarm per month and per metric. Alarm on **symptoms that matter**, not every metric. |
| "A single bad data point triggers the alarm." | Only if the alarm is `1 out of 1`. Using `2 out of 3` reduces false alarms and noise. |
| "High-cardinality dimensions are fine." | A dimension with unbounded values (a request ID, a user ID) creates **a new billed metric for each value**. Never use them. |
| "Alarm actions always work." | The target must **allow CloudWatch** to publish. The default `plat-alerts` policy does. A topic policy you rewrote may not. |
| "Average CPU is the best statistic." | For spikes and latency, use **Maximum** or **p95/p99**. Averages hide the bad requests. |
| "Insights queries are free." | They charge per GB of log data **scanned**. Narrow the time range and the log groups. |
| "The agent works once installed." | It needs a **config file**, a **role** with `CloudWatchAgentServerPolicy`, and a **network path** to the CloudWatch endpoints. |
| "Stopping the instance keeps the alarm green." | Metrics stop, and the alarm drifts to INSUFFICIENT_DATA (or ALARM, if you chose `breaching`). Decide what a stopped instance should mean. |

---

## How This Connects 🔗

| This post watches | From |
|---|---|
| `plat-ec2`, its role, the `/data` disk | Post 10 |
| ALB `plat-alb`, the service, Container Insights on `plat-cluster`, log group `/ecs/plat-api` | Post 11 |
| `plat-ingest-dlq` and `plat-ingest-queue`, `plat-ingest` | Posts 13, 14 |
| Endpoint `plat-churn` | Post 20 |
| Topic `plat-alerts` with your email | Post 14 |

| You create here | Used by |
|---|---|
| Alarms (disk, DLQ, API errors, running tasks) | Everyone who reads email |
| Metric filter and the `Plat/ApiErrors` metric | The API-error alarm and dashboard |
| Dashboard **`plat-overview`** | Jim's morning check |
| Log retention settings | Cost control (22) |

---

## Lab: Observe the Platform 🛠️

Work as Jim, in **N. Virginia**. Start `plat-ec2` (Post 10) and make sure the NAT gateway is running. Your email subscription to `plat-alerts` must be **Confirmed**.

### 1. Let the instance publish metrics

**IAM, Roles, `plat-ec2-role`, Add permissions, Attach policies**: **`CloudWatchAgentServerPolicy`**.

Connect to `plat-ec2` with Session Manager and install the agent:

```bash
sudo dnf install -y amazon-cloudwatch-agent
```

Create a log file the agent will watch, and the agent configuration:

```bash
sudo touch /var/log/plat-demo.log
sudo chmod 644 /var/log/plat-demo.log

sudo tee /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json > /dev/null <<'EOF'
{
  "agent": { "metrics_collection_interval": 60, "run_as_user": "root" },
  "metrics": {
    "namespace": "CWAgent",
    "append_dimensions": { "InstanceId": "${aws:InstanceId}" },
    "metrics_collected": {
      "mem":  { "measurement": ["mem_used_percent"] },
      "disk": {
        "measurement": ["used_percent"],
        "resources": ["/", "/data"],
        "drop_device": false
      }
    }
  },
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/cloud-init-output.log",
            "log_group_name": "/plat/ec2/cloud-init",
            "log_stream_name": "{instance_id}",
            "retention_in_days": 7
          },
          {
            "file_path": "/var/log/plat-demo.log",
            "log_group_name": "/plat/ec2/demo",
            "log_stream_name": "{instance_id}",
            "retention_in_days": 7
          }
        ]
      }
    }
  }
}
EOF

sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config -m ec2 -s \
  -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json

sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -m ec2 -a status
```

```text
{
  "status": "running",
  "starttime": "2026-11-08T12:10:44+00:00",
  "configstatus": "configured",
  "version": "1.300..."
}
```

Write a few lines into the demo log:

```bash
for i in 1 2 3; do echo "$(date -u +%FT%TZ) INFO heartbeat $i" | sudo tee -a /var/log/plat-demo.log; done
```

Within two minutes, in CloudShell:

```bash
aws cloudwatch list-metrics --namespace CWAgent --query "Metrics[].[MetricName,Dimensions[].Value|join(',',@)]" --output text
```

```text
mem_used_percent    i-0abc123def4567890
disk_used_percent   i-0abc123def4567890,/data,nvme1n1,xfs
disk_used_percent   i-0abc123def4567890,/,nvme0n1p1,xfs
```

Those exact dimension values (`path`, `device`, `fstype`) identify the series. Open **CloudWatch, Log groups** and see `/plat/ec2/demo` with your three lines. If nothing appears, read the agent log on the instance: `sudo tail -20 /opt/aws/amazon-cloudwatch-agent/logs/amazon-cloudwatch-agent.log`. A timeout there means no network path, and an access error means the role policy is missing.

### 2. An alarm on disk usage

**CloudWatch, Alarms, Create alarm, Select metric**: **CWAgent**, then the dimension set that includes `path=/data`, select `disk_used_percent`.

| Setting | Value |
|---|---|
| Statistic / period | **Maximum** / **1 minute** |
| Condition | **Greater than 80** |
| Datapoints to alarm | **2 out of 2** |
| Missing data | **Treat missing data as missing** |
| Notification | Alarm state, **existing SNS topic `plat-alerts`** |
| Name | `plat-ec2-data-disk-high` |

Create it. It starts in **INSUFFICIENT_DATA** for a minute, then **OK**.

Now cause the problem on the instance (the data disk is 5 GiB):

```bash
sudo fallocate -l 4G /data/fill.bin
df -h /data
```

```text
/dev/nvme1n1    5.0G  4.1G  0.9G  82% /data
```

Within about three minutes the alarm turns **ALARM** and you receive an email whose subject begins `ALARM:`. Remove the file and watch it recover:

```bash
sudo rm /data/fill.bin
```

You get an `OK:` email a few minutes later. Open the alarm's **History** tab to see each transition and its reason.

### 3. Turn log lines into a metric

The API logs JSON, including `"level": "error"` when something fails (Post 11). Open **CloudWatch, Log groups, `/ecs/plat-api`, Metric filters, Create metric filter**:

| Field | Value |
|---|---|
| Filter pattern | `{ $.level = "error" }` |
| Filter name | `api-errors` |
| Metric namespace | `Plat` |
| Metric name | `ApiErrors` |
| Metric value | `1` |
| Default value | `0` |

Also set the log group's **retention to 7 days**. Now generate errors. The endpoint was deleted in Post 20, so `/predict` fails by design:

```bash
for i in $(seq 1 6); do curl -s -o /dev/null -w "%{http_code} " "http://$ALB/predict?sessions=1&minutes=10&tickets=2&pro=0"; done; echo
```

```text
502 502 502 502 502 502
```

Query the logs with **Logs Insights** (select `/ecs/plat-api`, last 15 minutes):

```text
fields @timestamp, path, error
| filter level = "error"
| stats count() as errors by path, error
| sort errors desc
```

```text
path       error         errors
/predict   ClientError   6
```

The metric filter is already counting them. Create the alarm from **Metrics, Plat, ApiErrors**:

| Setting | Value |
|---|---|
| Statistic / period | **Sum** / **1 minute** |
| Condition | **Greater than or equal to 3** |
| Datapoints to alarm | **1 out of 1** |
| Missing data | **Treat as good (not breaching)** |
| Action | `plat-alerts` |
| Name | `plat-api-errors` |

Run the loop above again to trigger it, and note that the filter only counts events **after** its creation.

### 4. Alarms on built-in metrics

Create these in the same way (**Alarms, Create alarm, Select metric**). For each choose SNS action `plat-alerts`:

| Alarm name | Metric (namespace, name, dimensions) | Statistic, period | Condition | Missing data |
|---|---|---|---|---|
| `plat-dlq-not-empty` | `AWS/SQS`, `ApproximateNumberOfMessagesVisible`, `QueueName = plat-ingest-dlq` | Maximum, 1 min | `>= 1` for 1 of 1 | not breaching |
| `plat-api-running-tasks` | `ECS/ContainerInsights`, `RunningTaskCount`, `ClusterName = plat-cluster`, `ServiceName = plat-api-svc` | Minimum, 1 min | `< 2` for 3 of 3 | missing |
| `plat-ingest-errors` | `AWS/Lambda`, `Errors`, `FunctionName = plat-ingest` | Sum, 5 min | `>= 1` for 1 of 1 | not breaching |

For the ALB metrics, the dimension values look like `app/plat-alb/50dc6c495c0c9188` and `targetgroup/plat-api-tg/6d0ecf831eec9f09`. Pick them from the console list rather than typing them.

Test the DLQ alarm properly:

```bash
DLQ=$(aws sqs get-queue-url --queue-name plat-ingest-dlq --query QueueUrl --output text)
aws sqs send-message --queue-url $DLQ --message-body "alarm test"
```

Within a few minutes `plat-dlq-not-empty` fires. Purge the DLQ to recover. For a **fast** notification test that doesn't depend on a metric, force an alarm's state:

```bash
aws cloudwatch set-alarm-state --alarm-name plat-api-running-tasks \
  --state-value ALARM --state-reason "manual test of notification path"
```

You get the email immediately, and CloudWatch moves the alarm back to its real state on the next evaluation. It is the quickest way to prove "if this alarm fired, would anyone hear it?".

### 5. A dashboard

**CloudWatch, Dashboards, Create dashboard** named **`plat-overview`**. Add these widgets (type **Line** unless noted):

| Widget | Metric |
|---|---|
| API traffic and errors | ALB `RequestCount`, `HTTPCode_Target_5XX_Count` (Sum), and `Plat/ApiErrors` |
| Running tasks | `ECS/ContainerInsights`, `RunningTaskCount` for the service |
| Ingest backlog | SQS `ApproximateNumberOfMessagesVisible` for `plat-ingest-queue` and `plat-ingest-dlq` |
| Lambda | `Invocations` and `Errors` for `plat-ingest` |
| Data disk | `CWAgent` `disk_used_percent` for `/data` |
| Alarm status (type **Alarm status**) | All `plat-` alarms |

Save it. The last widget shows every alarm's current state at a glance.

### 6. Optional: the endpoint's view

Redeploy the endpoint by re-running the step 4 cell from Post 20 (about ten minutes), invoke it a few times, then add its `ModelLatency` (namespace `AWS/SageMaker`, dimensions `EndpointName = plat-churn`, `VariantName = AllTraffic`; the value is in **microseconds**) to the dashboard. An alarm like **p95 `ModelLatency` greater than 500,000 for 3 of 3** would catch a slow model. **Delete the endpoint again** afterwards.

### 7. Housekeeping

Set retention to 7 days on every log group you own (CloudWatch, Log groups, Actions, **Edit retention**): `/aws/lambda/plat-*`, `/ecs/plat-api`, `/aws/codebuild/*`, `/aws/sagemaker/*`. Check `aws logs describe-log-groups --query "logGroups[?retentionInDays==null].logGroupName"` lists none you care about.

Stop `plat-ec2` when done. The agent restarts with the instance.

### 8. Resources you now have 📦

| Resource | Name |
|---|---|
| Agent and config | On `plat-ec2`; log groups `/plat/ec2/cloud-init`, `/plat/ec2/demo` |
| Metric filter and metric | `api-errors` on `/ecs/plat-api`, `Plat/ApiErrors` |
| Alarms | `plat-ec2-data-disk-high`, `plat-api-errors`, `plat-dlq-not-empty`, `plat-api-running-tasks`, `plat-ingest-errors` |
| Dashboard | `plat-overview` |

### Cleanup 🧹

Alarms cost a small fixed amount each per month. Agent metrics are billed as custom metrics (a few series here). Keep them. Delete the endpoint if you started it.

---

## Quick Quiz 🧠

**Q1.** Your disk alarm stays in `INSUFFICIENT_DATA` though the agent runs. What do you check first?

<details>
<summary>Show answer</summary>

That the alarm's **dimensions exactly match** the published metric (`InstanceId`, `path`, `device`, `fstype`). A mismatch creates a different metric with no data. Confirm with `list-metrics`.

</details>

**Q2.** You add a metric filter, but the metric stays at zero although old log lines match. Why?

<details>
<summary>Show answer</summary>

Metric filters only process **log events ingested after the filter exists**. Generate new events.

</details>

**Q3.** Which missing-data setting suits a queue-depth alarm for a queue that is often empty?

<details>
<summary>Show answer</summary>

**Not breaching** (treat missing data as good). Otherwise a quiet period might be seen as a problem, or leave the alarm undecided.

</details>

**Q4.** Why is `request_id` a bad dimension for a custom metric?

<details>
<summary>Show answer</summary>

Each distinct value creates a **separate metric** that is stored and billed, so cost and clutter grow without bound. Dimensions must have a small, bounded set of values.

</details>

**Q5.** How do you test that an alarm's email path works without causing a real failure?

<details>
<summary>Show answer</summary>

Use `aws cloudwatch set-alarm-state` to force the alarm into `ALARM`. The action runs as if it had fired.

</details>

---

## What's Next? 🚀

You can now see failures. The remaining question is the one managers ask: **what is this costing us, and did something change?** The last technical post covers cost allocation and spending alerts, then the capstone brings the whole platform together.

👉 **[Post 22: Cost Explorer and Budgets](content/aws/22-cost-explorer-and-budgets.md)**: tags that make costs attributable, Cost Explorer to find the expensive pieces, budgets with forecasts and alerts, and a pause/resume routine for the platform.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
