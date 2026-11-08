---
title: "Foundations: Account, Region and the Platform Map"
date: 2026-11-08
tags: [aws, foundations, account-setup, regions, budgets, cloudshell, intermediate]
description: The first post in the AWS series. The platform we build across 23 posts, how every service connects to the next, the account and region decisions you can't easily undo, and a lab that locks down the root user, sets a cost guard and opens your first CloudShell session.
---

# Why This Series Exists ☁️

Most AWS content is a catalogue. One post per service, each starting with a definition and ending with a screenshot. You finish it knowing what S3 *is* and still can't answer the question that matters at work: **"why can't my Lambda read this bucket?"**

The answer is almost never inside one service. It lives in the connections: an IAM policy here, a route table there, a KMS key policy you forgot existed.

So this series builds **one platform**, layer by layer, and every post plugs into the last. By the end you will have created every piece by hand in the console, and you'll know which connection to check when something breaks.

This is an **intermediate** series. It assumes you already have an AWS account and know what a VM, a container and a JSON policy are. It does not assume you know *why* things fail, which is what we'll spend our time on.

---

## The Platform We're Building 🏗️

A small, secure **data and ML platform** (we'll call it the *Platform Lab*):

1. A user uploads a CSV of customer activity to an encrypted S3 bucket.
2. The upload raises an event that flows through SNS and SQS to a Lambda function.
3. The function records the job in DynamoDB; dataset metadata lives in RDS.
4. An API container, running on ECS and on EKS, serves job status from those stores.
5. A SageMaker processing job cleans the data, a training job fits a churn model, and an endpoint serves predictions.
6. A pipeline builds and deploys the API on every `git push`.
7. CloudWatch watches all of it, and a budget makes sure the bill never surprises you.

Two people use it. **Jim** is the platform engineer who builds and operates it. **Dave** is the data scientist who uses it and must *not* be able to break it.

![The Platform Lab, layer by layer](content/aws/images/01-platform-map.svg)

---

## The Series Map 🗺️

| Part | Posts | What you build |
|---|---|---|
| **Part 1: Identity & Networking** | 01 – 05 | Safe account access, SSO, a private VPC, encryption keys and secrets |
| **Part 2: Storage & Databases** | 06 – 08 | S3 data lake, security groups, EFS, RDS and DynamoDB |
| **Part 3: Compute & Containers** | 09 – 12 | Linux and Docker, EC2, ECR and ECS, EKS |
| **Part 4: Serverless & Automation** | 13 – 14 | Lambda, SQS, SNS and EventBridge wired into one flow |
| **Part 5: CI/CD & IaC** | 15 – 18 | Git and webhooks, CloudFormation, Terraform, Service Catalog, CodeBuild and CodePipeline |
| **Part 6: Machine Learning** | 19 – 20 | ML environments, SageMaker Studio, processing, training, endpoints |
| **Part 7: Observability & Governance** | 21 – 22 | CloudWatch, the agent and alarms, Cost Explorer and Budgets |
| **Capstone** | 23 | The whole platform, end to end, then a safe teardown |

Every post has the same shape:

| Section | What it gives you |
|---|---|
| **Concepts** | Only what you need to make the lab make sense |
| **Nuances & Misconceptions** | The things people assume, and what's actually true |
| **How This Connects** | What the post builds on, and what later posts consume |
| **Lab** | Numbered console steps, a CLI check with expected output, and a cleanup |
| **Quick Quiz** | Four or five questions with full answers |

---

## Four Decisions You Can't Easily Undo 🔒

Before the lab, four choices that are painful to change later.

### 1. The Region

Almost everything in AWS is **regional**: a bucket, a VPC, a Lambda function and a KMS key all live in exactly one region and can't see their siblings in another. We'll use **US East (N. Virginia), `us-east-1`** for every lab.

A few things are **global** (IAM users and roles, Route 53, CloudFront) or *act* global but have a home region (Billing, Budgets, Cost Explorer). Look at the region selector at the top right of the console *before* you create anything.

### 2. The Account Layout

One account is fine for learning. Real platforms use **many accounts** (dev, prod, security, shared tooling) under AWS Organizations, because the account is the strongest boundary AWS offers for permissions, blast radius and billing. We'll stay in one account but write every policy as if there were several.

### 3. The Naming Convention

Everything we create starts with `plat-`. Names with a predictable prefix make IAM policies, cost reports and cleanup scripts easy to write.

| Resource | Pattern | Example |
|---|---|---|
| S3 bucket | `plat-<purpose>-<account-id>-<region>` | `plat-data-123456789012-us-east-1` |
| IAM role | `plat-<service>-<purpose>-role` | `plat-ecs-exec-role` |
| Everything else | `plat-<name>` | `plat-vpc`, `plat-jobs`, `plat-cluster` |

Bucket names are **globally unique across all of AWS**, which is why the account ID goes in.

### 4. The Tag

Every resource we create gets the tag `project = plat`. In Post 22 we'll switch that tag on for cost reporting, and tags only count from the day you activate them, so start now.

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "I'm on the free tier, so I can't be charged." | The free tier is a set of **limits and credits**. NAT gateways, load balancers, EKS control planes and public IPv4 addresses start billing the minute they exist. Newer accounts also use a credit-based plan (AWS's pricing pages describe up to $200 in credits at the time of writing), and when credits run out, charges begin. |
| "The root user is the admin account." | Root is the **account owner**. It can do a few things nobody else can (close the account, change the support plan), but it's too powerful for daily work. Secure it with MFA, then stop using it. |
| "A budget stops me overspending." | A budget **sends alerts**. It does not stop anything unless you attach a budget action, and even then it reacts with a delay, because billing data isn't real-time. |
| "`us-east-1a` is the same data centre for everyone." | AZ **names are shuffled per account**. Your `us-east-1a` may be someone else's `us-east-1c`. The stable identifier is the **AZ ID** (like `use1-az4`). It matters the day you share subnets or endpoints across accounts. |
| "The console and the CLI use the same login." | They don't. The console uses your sign-in session. The CLI needs credentials of its own. This series uses **CloudShell** first, then **SSO-backed CLI profiles** in Post 03. We never create long-lived access keys. |
| "CloudShell is just a terminal." | It's a free, browser-based shell that already holds **your console identity and region**. It's the safest way to run CLI commands before you set up local credentials. |

---

## The Meter Is Always Running 💸

These are the services we'll create that bill **by the hour** whether or not you're using them. Prices are approximate US East on-demand figures at the time of writing, so confirm each against the linked AWS pricing page before you rely on it.

| Resource | Approx. cost | Where we create it | Our rule |
|---|---|---|---|
| NAT gateway | ~$0.045/hour + ~$0.045/GB processed | Post 04 | Delete at the end of each session |
| Application Load Balancer | ~$0.0225/hour + usage | Post 11 | Delete at the end of each session |
| EKS control plane | $0.10/hour (extended support $0.60/hour) | Post 12 | Delete at the end of each session |
| Interface VPC endpoint | ~$0.01/hour per AZ + data | Posts 05, 10 | Delete when done |
| RDS `db.t4g.micro` | ~$0.016/hour + storage | Post 08 | Stop or delete when done |
| SageMaker endpoint | Per hour, per instance | Post 20 | **Delete the same day** |
| Public IPv4 address | ~$0.005/hour each | Several | Attached to almost everything public |

Every lab ends with a **Cleanup** section that lists what to delete and what's safe to keep. IAM, KMS keys (about $1 a month each), S3 buckets, VPC, subnets and route tables cost nothing or almost nothing while idle.

> **Key insight:** The expensive mistakes on AWS are rarely big. They're small hourly things left running. A cleanup habit and a budget alert are worth more than any optimisation you'll learn later.

---

## How This Connects 🔗

This is the root of the series, so it builds on nothing. Everything after it consumes three things from this post:

| You create here | Used by |
|---|---|
| A secured account and a console sign-in that isn't root | Every lab |
| The `plat-` naming convention and `project = plat` tag | Every post, and Post 22 for cost reports |
| A budget alert | Post 22, where we upgrade it with actions |
| CloudShell as a safe CLI | Posts 02 – 08 (until Post 03 gives you SSO profiles) |

---

## Lab: Lock Down the Account 🛠️

> **Console labels drift.** AWS renames buttons and reshuffles pages regularly. The steps here follow the console as documented at the time of writing. If a label differs, the intent of the step is what matters. Where I'm describing something I'd expect you to double-check, I'll say so.

### 1. Sign in as root and enable MFA

1. Sign in at `https://console.aws.amazon.com` as the **root user** (the email you registered with).
2. Click your account name at the top right and choose **Security credentials**.
3. Under **Multi-factor authentication (MFA)**, choose **Assign MFA device**.
4. Name it `root-mfa` and pick a **passkey or security key**, or an **authenticator app**. Complete the prompts.

AWS lets you register more than one MFA device on the root user. Register a second one, and keep it somewhere safe. Losing your only device means a slow recovery.

### 2. Allow IAM users to see billing

Still as root:

1. Account menu, then **Account**.
2. Scroll to **IAM user and role access to Billing information** and choose **Edit**.
3. Tick **Activate IAM Access** and save.

Without this, an admin with full IAM permissions still can't open the Billing console. It's a classic first-week surprise.

### 3. Set an account alias

1. Open **IAM**, then **Dashboard**.
2. Next to **Account Alias**, choose **Create**.
3. Enter `plat-lab-<your-name>` (lowercase, globally unique).

Your sign-in URL becomes `https://plat-lab-<your-name>.signin.aws.amazon.com/console`, and it's easier to remember than a 12-digit account ID.

### 4. Create a cost guard

1. Open **Billing and Cost Management**, then **Budgets**, then **Create budget**.
2. Choose **Use a template (simplified)** and **Monthly cost budget**.
3. Name it `plat-monthly-guard`, set the amount to **$20** (or whatever you're comfortable with), and add your email.
4. Create the budget.

It will alert you at 85% of actual spend, 100% of actual spend and 100% of forecasted spend. We'll rebuild it properly in Post 22. For now, the point is that **something** will email you.

### 5. Create a temporary administrator

You shouldn't live as root, and we won't install SSO until Post 03. So we create one **temporary** administrator and delete it in Post 03.

1. In **IAM**, choose **Users**, then **Create user**.
2. User name: `plat-bootstrap`. Tick **Provide user access to the AWS Management Console** and choose **I want to create an IAM user**.
3. Set a custom password and untick **Users must create a new password at next sign-in**.
4. On the permissions step, choose **Attach policies directly** and select **AdministratorAccess**.
5. Add the tag `project = plat`, then create the user.
6. Sign out of root. Sign in at your alias URL as `plat-bootstrap`.
7. Click your name, then **Security credentials**, and assign an MFA device to this user too.

Do **not** create access keys for this user. Everything this series needs from the CLI will go through CloudShell.

### 6. Open CloudShell and check your identity

1. In the top-right region selector, choose **US East (N. Virginia) us-east-1**.
2. Click the **CloudShell** icon in the top navigation bar and wait for the prompt.
3. Run:

```bash
aws sts get-caller-identity
```

Expected output (your IDs will differ):

```json
{
    "UserId": "AIDAEXAMPLEEXAMPLE",
    "Account": "123456789012",
    "Arn": "arn:aws:iam::123456789012:user/plat-bootstrap"
}
```

4. Save your account ID for later commands:

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
echo $ACCOUNT
```

5. See AZ names *and* IDs side by side:

```bash
aws ec2 describe-availability-zones \
  --query 'AvailabilityZones[].[ZoneName,ZoneId]' --output table
```

Note the two columns. The name is yours alone. The ID is what AWS uses to mean the same data centre for everybody.

### 7. Resources you now have 📦

| Resource | Name | Notes |
|---|---|---|
| Root MFA | `root-mfa` | Root is now locked away |
| Account alias | `plat-lab-<your-name>` | Your sign-in URL |
| Budget | `plat-monthly-guard` | Email alerts only |
| IAM user | `plat-bootstrap` | **Temporary.** Deleted in Post 03 |

### Cleanup 🧹

Nothing to clean. Everything here is free.

---

## Quick Quiz 🧠

**Q1.** You create an S3 bucket in `us-east-1`. Can a Lambda function in `eu-west-1` list it with no extra configuration?

<details>
<summary>Show answer</summary>

**Network-wise yes, resource-wise it isn't "the same region" at all.** S3 bucket names are global, and the Lambda can call the bucket's `us-east-1` endpoint over the internet if its IAM role allows it. But it's cross-region traffic, which adds latency and data-transfer cost. Most other resources (VPCs, KMS keys, queues) can't be referenced across regions at all.

</details>

**Q2.** Why is `plat-bootstrap` marked "temporary", and what's the risk of leaving it?

<details>
<summary>Show answer</summary>

It's a **long-lived IAM user with admin rights and a static password**. Even with MFA, it's a standing credential that can be phished, shared or forgotten. Identity Center (Post 03) replaces it with short-lived sessions tied to a person, and once that works we delete this user.

</details>

**Q3.** Your budget is $20 and you've spent $19. A NAT gateway keeps running. What happens to the bill?

<details>
<summary>Show answer</summary>

**The bill keeps growing.** A budget alerts. It does not shut anything down. Only a **budget action** (Post 22) can react, and even that has a delay because cost data arrives several times a day, not instantly.

</details>

**Q4.** Two colleagues each see `us-east-1a` in their own accounts. Are their subnets in the same data centre?

<details>
<summary>Show answer</summary>

**Not necessarily.** AWS maps AZ names to physical zones **per account** to spread load. The AZ ID (`use1-az4`, for example) is identical across accounts. When you coordinate across accounts, use AZ IDs.

</details>

**Q5.** Name two reasons we use CloudShell instead of creating access keys for `plat-bootstrap`.

<details>
<summary>Show answer</summary>

Access keys are **long-lived secrets** that can leak into shell history, code or screenshots. CloudShell inherits your short-lived console session, so there's **nothing to store, rotate or revoke**. In Post 03 we replace even that with SSO profiles that expire on their own.

</details>

---

## What's Next? 🚀

We have an account that's locked down and a way to run commands. But `plat-bootstrap` has `AdministratorAccess`, and "admin" is a sentence you'll type a hundred times before you understand what it grants. What does a policy really say? Who is allowed to *assume* a role? And why does an explicit deny beat everything?

👉 **[Post 02: IAM in Depth](content/aws/02-iam-in-depth.md)**: principals, policies, trust, and the evaluation logic that decides every `AccessDenied` you'll ever see.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
