---
title: "Cost as Code: Budgets, Anomaly Detection and Tags"
date: 2026-11-11
tags: [aws, terraform, budgets, cost-explorer, cost-allocation-tags, anomaly-detection, default-tags, intermediate]
description: Post 15 of the AWS on Terraform series. A whole-account budget and a tag-filtered budget, the default_tags that make the tag filter possible, cost allocation tags that need a day to appear, and an anomaly monitor that needs Cost Explorer enabled first.
---

# Paying Attention to the Bill 💸

The platform has switches because several parts cost money by the hour. A switch does not help if you forget it is on, so this stack adds two safety nets and one report: **budgets** that tell you when spend crosses a line, **anomaly detection** that tells you when something unusual starts, and **cost allocation tags** that let you ask "what did *this project* cost?".

It is `stacks/95-cost` and follows AWS series Post 22.

---

## The Pieces 🧱

| Piece | Resource(s) | Created when |
|---|---|---|
| Whole-account budget `plat-monthly-guard` | `aws_budgets_budget.monthly` | Always |
| Tag-filtered budget `plat-tagged-monthly` | `aws_budgets_budget.tagged` | Always |
| Cost allocation tags | `aws_ce_cost_allocation_tag.this` | **Toggle** `enable_cost_allocation_tags` |
| Anomaly monitor and subscription | `aws_ce_anomaly_monitor.services`, `aws_ce_anomaly_subscription.email` | **Toggle** `enable_anomaly_detection` (subscription also needs `alert_email`) |

![Cost controls](content/aws-terraform/images/15-cost.svg)

Both toggles are about **prerequisites**, not about money: these resources are free. They are off by default because each needs something that exists only after a delay, as explained below.

---

## Reading the Stack 📖

### Where the tags come from

Every stack declares `default_tags` in its provider:

```hcl
# stacks/95-cost/providers.tf
provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project    = "plat"
      managed_by = "terraform"
      stack      = "95-cost"
    }
  }
}
```

This is Post 02's `default_tags`, and here it pays off. Every taggable resource in every stack carries `project = plat`, `managed_by = terraform` and `stack = <the stack's name>` without a single resource asking for it. That uniform tag is what the budget and the cost report filter on.

### The whole-account budget

```hcl
# stacks/95-cost/main.tf
locals {
  topic_arn  = data.terraform_remote_state.events.outputs.topic_arn
  subscriber = var.alert_email == "" ? [] : [var.alert_email]
}

resource "aws_budgets_budget" "monthly" {
  name         = "plat-monthly-guard"
  budget_type  = "COST"
  limit_amount = var.monthly_limit_usd
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = local.subscriber
    subscriber_sns_topic_arns  = [local.topic_arn]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = local.subscriber
    subscriber_sns_topic_arns  = [local.topic_arn]
  }
}
```

One budget with two notifications:

* **80% of the limit, `ACTUAL`**: you have really spent 80% of $20.
* **100% of the limit, `FORECASTED`**: AWS **predicts** you will reach 100% by month end. This is the early warning: it fires while there is still time to act.

Each notification goes to the email address (if set) and to the SNS topic. The topic policy from Post 11 names `budgets.amazonaws.com`; without that statement the SNS delivery fails silently, though email still works. `limit_amount` is a **string**, which surprises people: the provider models it that way.

### The tag-filtered budget

```hcl
# stacks/95-cost/main.tf
resource "aws_budgets_budget" "tagged" {
  name         = "plat-tagged-monthly"
  budget_type  = "COST"
  limit_amount = var.tagged_limit_usd
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = ["user:project$plat"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = local.subscriber
    subscriber_sns_topic_arns  = [local.topic_arn]
  }
}
```

The filter `TagKeyValue = "user:project$plat"` reads: user-defined tag `project`, value `plat`. The format is the quirk: the prefix `user:` marks it as a user tag, and a **dollar sign** separates key and value. It only counts spend on resources carrying the tag **and** whose tag has been activated for cost allocation, which is the next resource.

### Cost allocation tags

```hcl
# stacks/95-cost/main.tf
resource "aws_ce_cost_allocation_tag" "this" {
  for_each = var.enable_cost_allocation_tags ? toset(["project", "managed_by", "stack"]) : toset([])

  tag_key = each.key
  status  = "Active"
}
```

A tag on a resource is not automatically visible in billing. You must **activate** the key for cost allocation, and AWS lets you do so only once the key has **appeared in your billing data**, which means a tagged resource has incurred a charge, usually after about a day. That is why this is a toggle that defaults to off: on a brand-new account the first apply would fail with an error that the tag keys were not found.

Activation also takes up to 24 hours to take effect in reports, and it is **not retroactive**: spend before activation isn't attributed.

### Anomaly detection

```hcl
# stacks/95-cost/main.tf
resource "aws_ce_anomaly_monitor" "services" {
  count = var.enable_anomaly_detection ? 1 : 0

  name              = "plat-services"
  monitor_type      = "DIMENSIONAL"
  monitor_dimension = "SERVICE"
}

resource "aws_ce_anomaly_subscription" "email" {
  count = var.enable_anomaly_detection && var.alert_email != "" ? 1 : 0

  name             = "plat-anomaly-alerts"
  frequency        = "DAILY"
  monitor_arn_list = [aws_ce_anomaly_monitor.services[0].arn]

  subscriber {
    type    = "EMAIL"
    address = var.alert_email
  }

  threshold_expression {
    dimension {
      key           = "ANOMALY_TOTAL_IMPACT_ABSOLUTE"
      match_options = ["GREATER_THAN_OR_EQUAL"]
      values        = ["5"]
    }
  }
}
```

The monitor learns the normal spend of each AWS **service** (dimension `SERVICE`) and flags deviations. The subscription emails a daily summary when an anomaly's total impact is at least $5. Two requirements are hidden here:

* **Cost Explorer must be enabled** on the account. That is a one-time console action (Billing, Cost Explorer, enable). It cannot be done through Terraform, and data starts to flow within about a day.
* **A `DAILY` frequency needs an email subscriber.** SNS subscribers are only allowed with `IMMEDIATE` frequency. This is why the subscription is conditioned on `alert_email != ""`.

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "A budget stops spending at the limit." | It only **notifies**. Nothing is shut down. |
| "Budget alerts are real time." | Budgets refresh a few times a day. Usage can run well past a threshold before the email. |
| "`FORECASTED` needs no history." | A forecast needs about five weeks of usage; on a young account it may not fire. |
| "Tagging resources is enough to filter costs." | The tag must also be **activated** for cost allocation, and appear in billing first. |
| "I can activate the tag today and see last month's split." | Activation is not retroactive. |
| "`limit_amount = 20` as a number." | The attribute is a string. |
| "The filter value is `project=plat`." | It is `user:project$plat`. |
| "Anomaly detection works from day one." | It needs Cost Explorer enabled and some days of data. |
| "A budget notification to SNS always arrives." | Only if the topic policy allows `budgets.amazonaws.com`. |
| "Free-tier usage never alerts." | Budgets measure **cost**. Free-tier use costs zero and won't trip a cost budget (there's a separate usage budget type). |
| "`default_tags` tags everything." | Only resources that support tags. Some resources, and some attributes like launch templates' inner resources, need explicit tags. |
| "Destroying the tag resource deletes the tag." | It sets the status back to `Inactive`. The tag remains on resources. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| `topic_arn` and its policy | `60-events` (Post 11) |
| `default_tags` set in every stack | Post 02 |

| You create here | Used by |
|---|---|
| Budgets | Your inbox, `plat-alerts` |
| Tag activation | Cost Explorer filters |
| Anomaly monitor | Daily email |

### Console clicks you no longer make

| In the AWS series you... | Here it is |
|---|---|
| **Billing, Budgets, Create budget** (cost budget, amount, alerts) | `aws_budgets_budget` x2 |
| Add a **tag filter** to the budget | `cost_filter` |
| **Cost allocation tags, Activate** | `aws_ce_cost_allocation_tag` |
| **Cost Anomaly Detection, Create monitor, Create alert subscription** | `aws_ce_anomaly_*` |

---

## Lab: Put a Fence Around the Bill 🛠️

### 1. Budgets

```bash
export AWS_PROFILE=plat-admin AWS_REGION=us-east-1
scripts/tf.sh 95-cost plan -var alert_email=you@example.com
```

```
Plan: 2 to add, 0 to change, 0 to destroy.
```

```bash
scripts/tf.sh 95-cost apply -var alert_email=you@example.com
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
aws budgets describe-budgets --account-id $ACCOUNT --query 'Budgets[].[BudgetName,BudgetLimit.Amount,TimeUnit]' --output text
aws budgets describe-notifications-for-budget --account-id $ACCOUNT --budget-name plat-monthly-guard \
  --query 'Notifications[].[NotificationType,Threshold]' --output text
```

```
plat-monthly-guard    20.0  MONTHLY
plat-tagged-monthly   15.0  MONTHLY
ACTUAL  80.0
FORECASTED  100.0
```

### 2. Provoke an alert on purpose

Set the limit absurdly low so the first evaluation trips it:

```bash
scripts/tf.sh 95-cost apply -var alert_email=you@example.com -var monthly_limit_usd=0.01
```

Within about **half a day** (budget data refreshes a few times daily) an email arrives from AWS Budgets saying that actual cost has exceeded 80% of your budget. You can also see it right away in the console. It proves the path from budget to email and to the SNS topic. Restore the limit:

```bash
scripts/tf.sh 95-cost apply -var alert_email=you@example.com
```

### 3. Enable Cost Explorer

In the console: **Billing and Cost Management, Cost Explorer, Launch Cost Explorer**. It takes up to 24 hours before data appears. This is the one manual step in this stack.

### 4. Activate the tags (after a day)

Come back once the lab has been running for a day and has accrued some charge. Check that AWS has seen the tag:

```bash
aws ce list-cost-allocation-tags --status Inactive --query 'CostAllocationTags[].TagKey' --output text
```

```
managed_by  project  stack
```

Only keys that appear here can be activated. Then:

```bash
scripts/tf.sh 95-cost plan -var alert_email=you@example.com -var enable_cost_allocation_tags=true
```

```
Plan: 3 to add, 0 to change, 0 to destroy.
```

```bash
scripts/tf.sh 95-cost apply -var alert_email=you@example.com -var enable_cost_allocation_tags=true
aws ce list-cost-allocation-tags --status Active --query 'CostAllocationTags[].TagKey' --output text
```

```
managed_by  project  stack
```

In Cost Explorer, group by **Tag: project** and you will see `plat` within a day.

### 5. Anomaly detection

```bash
scripts/tf.sh 95-cost plan -var alert_email=you@example.com -var enable_cost_allocation_tags=true -var enable_anomaly_detection=true
```

```
Plan: 2 to add, 0 to change, 0 to destroy.
```

The monitor and the subscription. Apply, and then:

```bash
aws ce get-anomaly-monitors --query 'AnomalyMonitors[].[MonitorName,MonitorDimension]' --output text
```

```
plat-services  SERVICE
```

### 6. Break it: ask for a tag AWS has never seen

On a fresh account, or with a made-up key, activation fails. Try it on the command line:

```bash
aws ce update-cost-allocation-tags-status --cost-allocation-tags-status TagKey=no-such-tag,Status=Active
```

```
{
    "Errors": [
        {
            "Code": "TagKeyNotResolvable",
            "Message": "Tag keys not found"
        }
    ]
}
```

Terraform's `enable_cost_allocation_tags = true` on day zero produces the same refusal as an apply error. The fix is time: wait until the key appears in `list-cost-allocation-tags`. This is a real example of a configuration that is **correct and cannot be applied yet**, and why the toggle exists.

### 7. Cause drift: raise the limit by hand

```bash
aws budgets describe-budget --account-id $ACCOUNT --budget-name plat-monthly-guard --query Budget > /tmp/b.json
python3 - <<'PY'
import json
b = json.load(open("/tmp/b.json"))
for k in ("CalculatedSpend", "LastUpdatedTime"):
    b.pop(k, None)
b["BudgetLimit"]["Amount"] = "500"
json.dump(b, open("/tmp/b.json", "w"))
PY
aws budgets update-budget --account-id $ACCOUNT --new-budget file:///tmp/b.json
scripts/tf.sh 95-cost plan -var alert_email=you@example.com
```

```
  # aws_budgets_budget.monthly will be updated in-place
  ~ limit_amount = "500.0" -> "20"
Plan: 0 to add, 1 to change, 0 to destroy.
```

The classic way budgets are defeated: the limit is quietly raised until alerts stop coming. A scheduled `plan` (Post 18) catches it. Apply to restore it.

### 8. Resources you now have 📦

| Resource | Name | Notes |
|---|---|---|
| Budgets | `plat-monthly-guard`, `plat-tagged-monthly` | Free (the first two are free per account) |
| Tag activations | `project`, `managed_by`, `stack` | After the first day |
| Anomaly monitor and subscription | `plat-services`, `plat-anomaly-alerts` | Free |

### Cleanup 🧹

Free resources: leave them. Destroying `aws_ce_cost_allocation_tag` sets the keys back to `Inactive`; it does not remove the tags from resources.

---

## Quick Quiz 🧠

**Q1.** Your tag-filtered budget reports $0 although the resources are tagged `project = plat`. Why?

<details>
<summary>Show answer</summary>

The tag has not been **activated** for cost allocation (or activation hasn't taken effect yet, which can take 24 hours), so the billing data carries no `project` tag for the filter to match. Check `list-cost-allocation-tags --status Active`.

</details>

**Q2.** Why does `FORECASTED` at 100% give more useful warning than `ACTUAL` at 100%?

<details>
<summary>Show answer</summary>

`FORECASTED` predicts that you **will** exceed the budget by the end of the month, so it can fire days earlier while you can still act. `ACTUAL` fires only once the money is spent.

</details>

**Q3.** Why does the anomaly subscription require `alert_email`?

<details>
<summary>Show answer</summary>

A `DAILY` summary can be delivered only by **email**. SNS subscribers work only with `IMMEDIATE` frequency, so without an address there is nobody to subscribe.

</details>

**Q4.** What exactly does a budget do when spend passes the limit?

<details>
<summary>Show answer</summary>

It **sends notifications** and nothing more. (Budget *actions* can apply policies or stop instances, but they are a separate, opt-in feature that this stack does not use.)

</details>

**Q5.** Why are the tag activations behind a toggle that defaults to off?

<details>
<summary>Show answer</summary>

AWS accepts activation only for tag keys already present in billing data, which needs a charged, tagged resource and about a day. On a new account the first apply would fail, so activation is a deliberate second step.

</details>

---

## What's Next? 🚀

The platform is complete. The next three posts are about **operating Terraform itself**: moving and importing resources, keeping the code honest with tests and scanners, and running it all from a pipeline.

👉 [Post 16: State in Depth: import, moved, removed and Recovery](content/aws-terraform/16-state-in-depth.md)

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
