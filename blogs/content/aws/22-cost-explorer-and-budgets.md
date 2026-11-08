---
title: "Cost Explorer and Budgets"
date: 2026-11-08
tags: [aws, cost-explorer, budgets, cost-allocation-tags, anomaly-detection, finops, intermediate]
description: Post 22 of the AWS series. How AWS cost data actually works, why tags only count from the day you activate them, which line items belong to which service in the platform, and a lab that builds tag-based reports, forecast alerts to SNS, anomaly detection and a pause-and-resume routine.
---

# The Meter Is Always Running 💸

Post 01 said the expensive mistakes are small hourly things left running. We have now built nearly every one of them: a NAT gateway, a load balancer, an RDS instance, two Fargate tasks, an EKS control plane, a SageMaker endpoint, a Studio space. This post makes cost *visible* and *accountable*, and gives you a routine that stops the platform costing money while you aren't using it.

![Where cost data comes from and who gets told](content/aws/images/22-cost.svg)

---

## The Cost Tools, Compared 🧮

| Tool | Answers | Notes |
|---|---|---|
| **Cost Explorer** | "What did we spend, on what, and what will we spend?" | Charts and filters over cost and usage data. Needs enabling, and takes up to 24 hours to populate the first time |
| **Budgets** | "Tell me (or act) when spend crosses a line" | Cost, usage and coverage budgets. Alerts on **actual** or **forecasted** values |
| **Cost Anomaly Detection** | "Something unusual happened" | Learns normal patterns per service or tag, alerts on spikes |
| **Cost and Usage Report** | "Give me every line item" | The raw dataset, delivered to S3, for deep analysis |
| **CloudWatch billing alarm** | "Estimated charges crossed X" | Older approach, based on a billing metric in us-east-1 |

### Cost allocation tags

A tag helps with cost only after you **activate it as a cost allocation tag** in the Billing console. The tag then appears in cost data **from that point on**. Costs are not re-labelled for earlier days.

| Kind | Example | Notes |
|---|---|---|
| **User-defined** | `project = plat` | Appears in the list only after a tagged resource has incurred cost, then you activate it |
| **AWS-generated** | `aws:createdBy` | Must also be activated |

### Which cost views exist

| View | Meaning |
|---|---|
| **Unblended** | The price you were charged on the day of use |
| **Amortized** | Spreads upfront payments (reservations, savings plans) over the term |
| **Net** | After discounts and credits |

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "Cost data is real time." | Data arrives **several times a day**, and a day's costs can still change afterwards. Budgets and anomaly alerts lag accordingly. |
| "I tagged everything, so the cost report is complete." | Only after you **activate** the tag, only for **taggable** resources, and only **going forward**. Many charges (data transfer, some support, tax) carry no tag. Expect an "untagged" remainder. |
| "A budget limit stops spending." | It sends alerts. Only a **budget action** (apply an IAM or service control policy, or stop instances) reacts, and still after a delay. |
| "Free tier means no bill." | Specific services have monthly allowances. Others (NAT, ELB, EKS, public IPv4 addresses) bill from the first hour. Check what your account's plan includes. |
| "I deleted the instance, so the cost is gone." | EBS volumes, snapshots, Elastic IPs, load balancers, NAT gateways, log storage and RDS snapshots **survive** and bill. |
| "Forecasts are accurate on day one." | Forecasting needs history. Early in a new account, forecast alerts can be wildly wrong. |
| "The Cost Explorer API is free." | Each API request has a **small charge**. Don't poll it in a loop. |
| "Stopping RDS stops it for good." | AWS **restarts a stopped RDS instance after seven days**. Storage still bills while it is stopped. |
| "Stopped EC2 costs nothing." | Compute is free, but **EBS** and any **Elastic IP** are not (Post 10). |
| "Budget alerts go to SNS automatically." | The topic's access policy must allow `budgets.amazonaws.com` to publish. Otherwise the notification silently has nowhere to go. |
| "One big budget is enough." | A single number hides which piece is growing. Combine a **total**, a **tag-filtered** budget and **anomaly detection**. |
| "Data transfer is small." | Traffic through NAT, across AZs or out to the internet is charged **per GB**. It's often the surprise item. |

---

## Where the Money Goes in This Platform 🗺️

Line items appear under **usage types**. Names vary by region and change over time; these are the families to recognise (look for items shaped like these in **Group by: Usage type**):

| Piece | What bills | Usage-type clue |
|---|---|---|
| NAT gateway (Post 4) | Hours, and per GB processed | `NatGateway-Hours`, `NatGateway-Bytes` |
| Public IPv4 addresses | Hours per address, including the NAT's and the ALB's | `PublicIPv4` |
| Load balancer (11) | Hours plus capacity units | `LoadBalancerUsage`, `LCUUsage` |
| ECS on Fargate (11) | vCPU-hours and GB-hours of memory | `Fargate-vCPU-Hours`, `Fargate-GB-Hours` |
| EKS (12) | Control plane hours, plus node instances | `AmazonEKS-Hours` |
| EC2 and EBS (10) | Instance hours, volume GB-months | `BoxUsage`, `EBS:VolumeUsage` |
| RDS (8) | Instance hours, storage, backups | `InstanceUsage`, `RDS:StorageUsage` |
| SageMaker (19, 20) | Studio apps, processing, training, endpoint hours | `Hosting`, `Processing`, `Training`, `Studio` |
| KMS and Secrets Manager (5) | Per key and per secret per month | `KMS-Keys`, `AWSSecretsManager-Secrets` |
| CloudWatch (21) | Logs ingestion and storage, custom metrics, alarms | `DataProcessing-Bytes`, `MetricMonitorUsage`, `AlarmMonitorUsage` |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| The tag `project = plat` on resources | Every post |
| Budget `plat-monthly-guard` and IAM access to Billing | Post 01 |
| SNS topic `plat-alerts` | Post 14 |
| Every billable piece listed above | Posts 4 to 21 |

| You create here | Used by |
|---|---|
| Activated cost allocation tag `project` | Cost Explorer and tag budgets |
| Budgets and an anomaly monitor sending to `plat-alerts` | The same inbox as the CloudWatch alarms |
| `pause-platform.sh` and `resume-platform.sh` | The routine at the end of every session, and the capstone |

---

## Lab: See It, Cap It, Pause It 🛠️

Work as Jim, in **N. Virginia**. (Billing pages are global, but the console may switch you to us-east-1 for them.)

### 1. Activate the tag

**Billing and Cost Management, Cost allocation tags**. Under **User-defined cost allocation tags** find **`project`**, tick it, and **Activate**. If it isn't listed yet, resources tagged `project` haven't produced billed usage in the data seen so far; check again tomorrow. Remember: costs are labelled with the tag only **from activation onward**.

### 2. Cost Explorer

**Billing and Cost Management, Cost Explorer**. The first time you open it, enable it and come back after up to 24 hours. Then build these views:

| View | Settings | What you learn |
|---|---|---|
| By service | Range **last 7 days**, granularity **daily**, **Group by Service** | The few services that dominate |
| By usage type | Filter **Service = EC2-Other**, **Group by Usage type** | Your NAT hours and bytes, EBS, data transfer |
| By tag | **Group by Tag: project** (once active) | Tagged versus untagged cost |
| Forecast | Range **this month to month-end** | Where the month will land |

Save each as a **report** (`plat-by-service`, `plat-nat-detail`). Try the **Resource-level data** option, if available, to find an individual NAT gateway or load balancer.

From CloudShell, the same data as a table (each API request has a small charge, so run it sparingly). Adjust the dates to the current month:

```bash
aws ce get-cost-and-usage \
  --time-period Start=2026-11-01,End=2026-11-09 \
  --granularity MONTHLY \
  --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE \
  --query "ResultsByTime[0].Groups[].[Keys[0],Metrics.UnblendedCost.Amount]" --output text | sort -k2 -nr | head
```

```text
Amazon Elastic Compute Cloud - Compute     2.41
EC2 - Other                                 1.87
Amazon Relational Database Service          1.12
Amazon Elastic Container Service            0.88
...
```

(The figures are illustrative; yours depend on how long things ran.)

### 3. Let SNS receive budget and anomaly alerts

Open the SNS topic `plat-alerts`, **Edit**, **Access policy**. Add these two statements to the existing statement list (keep what's there), with your account ID:

```json
{
  "Sid": "AllowBudgets",
  "Effect": "Allow",
  "Principal": { "Service": "budgets.amazonaws.com" },
  "Action": "SNS:Publish",
  "Resource": "arn:aws:sns:us-east-1:123456789012:plat-alerts",
  "Condition": { "StringEquals": { "aws:SourceAccount": "123456789012" } }
},
{
  "Sid": "AllowCostAnomaly",
  "Effect": "Allow",
  "Principal": { "Service": "costalerts.amazonaws.com" },
  "Action": "SNS:Publish",
  "Resource": "arn:aws:sns:us-east-1:123456789012:plat-alerts"
}
```

### 4. Budgets that mean something

You already have `plat-monthly-guard` (email). **Budgets, Create budget, Customize (advanced), Cost budget**:

**Budget A: forecast-aware total**

| Field | Value |
|---|---|
| Name | `plat-total-monthly` |
| Period / type | Monthly, recurring, fixed amount (choose a figure that suits you, for example $30) |
| Alert 1 | **Actual** greater than **50%**, email + SNS `plat-alerts` |
| Alert 2 | **Actual** greater than **90%** |
| Alert 3 | **Forecasted** greater than **100%** |

**Budget B: tagged costs**

| Field | Value |
|---|---|
| Name | `plat-tagged-monthly` |
| Filters | **Tag: project = plat** (the tag must already be active; filters appear after activation) |
| Amount | A slightly smaller figure, for example $25 |
| Alerts | Actual greater than 80% to `plat-alerts` |

The forecast alert is the valuable one: it fires **early in the month** when your burn rate says you'll overshoot, not after you have.

**Budget action (read, don't rush).** On a budget alert you can attach an **action**: apply an IAM policy to a role or user, apply a service control policy, or stop specific EC2 or RDS instances, with or without your approval. Use **manual approval** and test on a non-critical role first. Remember the delay: an action reacts to *reported* spend.

### 5. Anomaly detection

**Billing and Cost Management, Cost Anomaly Detection, Create monitor**: type **AWS services** (the simplest and recommended starting monitor), name `plat-services`. **Create alert subscription**:

| Field | Value |
|---|---|
| Name | `plat-anomaly-alerts` |
| Threshold | Total impact greater than **$5** (an absolute amount) |
| Frequency | **Individual alerts** to SNS |
| Recipient | `plat-alerts` |

Anomaly detection needs some history before it is useful, and it flags *unusual* cost, not high cost. A steadily expensive NAT gateway is not an anomaly; a new service suddenly appearing is.

### 6. The pause and resume routine

Create two scripts in the repository under `scripts/`. They are deliberately plain shell around the CLI so you can read every line before it touches anything.

**`scripts/pause-platform.sh`**

```bash
#!/usr/bin/env bash
# Stop the billable parts of the Platform Lab that are safe to stop, and
# list the ones that must be deleted or stopped by hand.
set -uo pipefail
REGION=${REGION:-us-east-1}
export AWS_DEFAULT_REGION=$REGION

echo "== ECS: scale plat-api-svc to 0"
aws ecs update-service --cluster plat-cluster --service plat-api-svc \
  --desired-count 0 --query 'service.desiredCount' --output text 2>&1 | sed 's/^/   desired=/'

echo "== RDS: stop plat-meta (AWS restarts it after 7 days)"
aws rds stop-db-instance --db-instance-identifier plat-meta \
  --query 'DBInstance.DBInstanceStatus' --output text 2>&1 | sed 's/^/   status=/'

echo "== EC2: stop running instances tagged project=plat"
IDS=$(aws ec2 describe-instances \
  --filters Name=tag:project,Values=plat Name=instance-state-name,Values=running \
  --query 'Reservations[].Instances[].InstanceId' --output text)
if [ -n "$IDS" ]; then aws ec2 stop-instances --instance-ids $IDS --query 'StoppingInstances[].InstanceId' --output text; else echo "   none running"; fi

echo "== SageMaker: delete endpoint plat-churn if it exists"
if aws sagemaker describe-endpoint --endpoint-name plat-churn >/dev/null 2>&1; then
  aws sagemaker delete-endpoint --endpoint-name plat-churn && echo "   deleted"
else
  echo "   not present"
fi

echo
echo "== STILL BILLING: delete these by hand if you are done for the day"
echo "-- NAT gateways (available):"
aws ec2 describe-nat-gateways --filter Name=state,Values=available \
  --query 'NatGateways[].[NatGatewayId,Tags[?Key==`Name`]|[0].Value]' --output text
echo "-- Load balancers:"
aws elbv2 describe-load-balancers --query 'LoadBalancers[].[LoadBalancerName,Type]' --output text
echo "-- EKS clusters:"
aws eks list-clusters --query 'clusters' --output text
echo "-- Unattached Elastic IPs:"
aws ec2 describe-addresses --query 'Addresses[?AssociationId==null].[PublicIp,AllocationId]' --output text
echo "-- Studio spaces still running (stop in the Studio console):"
aws sagemaker list-apps --query 'Apps[?Status==`InService`].[SpaceName,AppType]' --output text
```

**`scripts/resume-platform.sh`**

```bash
#!/usr/bin/env bash
# Start what pause-platform.sh stopped. The NAT gateway, load balancer and
# EKS cluster are not restarted here: recreate them from Posts 4, 11 and 12.
set -uo pipefail
export AWS_DEFAULT_REGION=${REGION:-us-east-1}

echo "== RDS: start plat-meta"
aws rds start-db-instance --db-instance-identifier plat-meta \
  --query 'DBInstance.DBInstanceStatus' --output text

echo "== EC2: start instances tagged project=plat"
IDS=$(aws ec2 describe-instances \
  --filters Name=tag:project,Values=plat Name=instance-state-name,Values=stopped \
  --query 'Reservations[].Instances[].InstanceId' --output text)
if [ -n "$IDS" ]; then aws ec2 start-instances --instance-ids $IDS --query 'StartingInstances[].InstanceId' --output text; else echo "   none stopped"; fi

echo "== Wait for the database, then scale the API back up"
aws rds wait db-instance-available --db-instance-identifier plat-meta
aws ecs update-service --cluster plat-cluster --service plat-api-svc \
  --desired-count 2 --query 'service.desiredCount' --output text
```

Run the pause script in CloudShell (`bash scripts/pause-platform.sh`) and read its output:

```text
== ECS: scale plat-api-svc to 0
   desired=0
== RDS: stop plat-meta (AWS restarts it after 7 days)
   status=stopping
== EC2: stop running instances tagged project=plat
i-0abc123def4567890
...
== STILL BILLING: delete these by hand if you are done for the day
-- NAT gateways (available):
nat-0123456789abcdef0   plat-nat-a
-- Load balancers:
plat-alb   application
```

The second half of the output is the important one: the NAT gateway and the ALB still bill. Delete them yourself when you finish for the day, and recreate them from Posts 4 and 11 (the target group, listener and service configuration are the quickest to rebuild from memory, which is exactly what Terraform or CloudFormation would remove; consider it your first real IaC project).

With the ECS service at zero, the `plat-api-running-tasks` alarm from Post 21 goes quiet because its missing-data setting is `missing`.

### 7. Resources you now have 📦

| Resource | Name |
|---|---|
| Cost allocation tag | `project` (active) |
| Cost Explorer reports | `plat-by-service`, `plat-nat-detail` |
| Budgets | `plat-monthly-guard`, `plat-total-monthly`, `plat-tagged-monthly` |
| Anomaly | Monitor `plat-services`, subscription `plat-anomaly-alerts` |
| Scripts | `scripts/pause-platform.sh`, `scripts/resume-platform.sh` |

### Cleanup 🧹

These are all free. Make `pause-platform.sh` the last thing you run each session.

---

## Quick Quiz 🧠

**Q1.** You activated `project` as a cost allocation tag today. Why doesn't last week's spend show under it?

<details>
<summary>Show answer</summary>

Activation applies **going forward**. Cost data already recorded isn't re-labelled. Activate tags *before* you need the report.

</details>

**Q2.** Your total budget is $30 and you hit $28 on day 20. Which alert type would have warned you earlier, and how?

<details>
<summary>Show answer</summary>

A **forecasted** alert. It compares the projected month-end spend with the budget, so it fires when the *burn rate* implies an overshoot, often days earlier than an actual-spend threshold.

</details>

**Q3.** The budget threshold passes but no message arrives in `plat-alerts`. Where do you look?

<details>
<summary>Show answer</summary>

The topic's **access policy** must allow `budgets.amazonaws.com` to publish. Also check that the email subscription is confirmed and the budget alert actually lists the topic.

</details>

**Q4.** You stopped the RDS instance on Friday. What can surprise you the following week?

<details>
<summary>Show answer</summary>

AWS **starts it again automatically after seven days**, and storage billed throughout. Snapshot and delete it if you won't need it for longer.

</details>

**Q5.** Name three things that keep billing after you "delete" an EC2-based workload.

<details>
<summary>Show answer</summary>

Any of: **EBS volumes and snapshots**, **Elastic IPs**, **NAT gateways**, **load balancers**, **log storage**, and **data transfer** that is already underway.

</details>

---

## What's Next? 🚀

That's every service in the original list, built by hand and observed. The last post puts them together: it traces one request through all layers, lists the dependencies that bite when you turn things off in the wrong order, and gives you a rebuild plan so you can do the whole thing again, faster and as code.

👉 **[Post 23: Capstone](content/aws/23-capstone.md)**: the full flow end to end, a failure drill that crosses six services, the order for tearing down and rebuilding, and where to go next.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
