---
title: "ECR and ECS"
date: 2026-11-08
tags: [aws, ecr, ecs, fargate, alb, task-role, containers, intermediate]
description: Post 11 of the AWS series. How a private registry, a task definition, two different IAM roles and a load balancer fit together, and a lab that pushes plat-api to ECR and runs it on Fargate behind an Application Load Balancer, talking to S3, DynamoDB and RDS.
---

# From an Image on Your Laptop to a Service ⚓

In Post 09 you built `plat-api` and ran it on your own machine with your own credentials mounted in. That was a shortcut. Now it needs to run somewhere that isn't your laptop, with an identity of its own, behind a stable address, and replaced automatically when it fails.

Two services do that job:

- **ECR** stores the image.
- **ECS** runs it, on **Fargate**, where AWS provides the compute and you manage no servers.

The part people get wrong is not the clicking. It's the **two IAM roles**, the **three networking layers**, and what ECS does and doesn't promise.

![ECR, ECS and the load balancer](content/aws/images/11-ecr-and-ecs.svg)

---

## ECR: the Private Registry 📦

| Concept | Detail |
|---|---|
| **Repository** | One per image name, for example `plat/api`. Holds many tags |
| **URI** | `<account>.dkr.ecr.us-east-1.amazonaws.com/plat/api:1.0.0` |
| **Login** | `aws ecr get-login-password` gives a token valid for **12 hours**. Docker stores it |
| **Tag mutability** | **Mutable** by default (a tag can be re-pointed). **Immutable** refuses overwrites |
| **Scan on push** | Basic vulnerability scanning of OS packages |
| **Lifecycle policy** | Rules that expire old images, so storage doesn't grow forever |
| **Encryption** | At rest by default. Can use a KMS key |

Pulling is an **IAM action**. The identity that pulls needs `ecr:GetAuthorizationToken` and the layer-pull actions. That identity is **not** the one your code uses.

---

## ECS: the Vocabulary 🧱

| Term | Meaning |
|---|---|
| **Cluster** | A logical grouping. With Fargate it holds no servers |
| **Task definition** | The versioned blueprint: image, CPU, memory, ports, environment, roles, logging. Each change is a new **revision** |
| **Task** | One running copy of a task definition |
| **Service** | Keeps **N tasks running**, replaces failed ones, registers them with a load balancer, and performs rolling deployments |

### The two roles

| | **Task execution role** | **Task role** |
|---|---|---|
| Used by | **ECS itself**, before and around your container starts | **Your code**, inside the container |
| Does | Pull the image from ECR, write logs to CloudWatch, read secrets for injection | Call S3, DynamoDB, Secrets Manager, and so on, via the SDK |
| Credentials reach the code through | Not available to your code | A credentials endpoint ECS exposes to the container |
| Missing it causes | `CannotPullContainerError`, no logs | `AccessDenied` in your application logs |

### Three layers of networking

| Layer | Controls |
|---|---|
| **Load balancer SG** | Who on the internet may reach the load balancer (80) |
| **Task SG** | Who may reach the tasks (8080), here only the load balancer's SG |
| **Subnets and routes** | Whether tasks can reach ECR, S3, AWS APIs: through NAT or endpoints |

With Fargate and `awsvpc` mode, **every task gets its own network interface and private IP**, and a security group is attached to the task itself.

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "One role is enough for a task." | **Two roles with different jobs.** Giving the execution role your application's permissions works, but then ECS-level plumbing and app logic share a blast radius. |
| "`CannotPullContainerError` is an ECR permission problem." | Often it's **network**: a private-subnet task with **no NAT and no ECR/S3 endpoints** can't reach the registry. Also check the image tag and **CPU architecture**. |
| "Tag `latest` always runs the newest image." | A task definition holds a tag, and tasks resolve it **when they start**. Running tasks never change. Deploy by registering a **new revision with a new tag** and updating the service. |
| "ECR charges only when I pull." | You pay for **storage** (per GB-month). Add a **lifecycle policy**. Pulls through NAT also incur NAT data charges. |
| "The ALB health check and the container health check are the same." | They're **separate**. The target group health check decides whether the ALB sends traffic. The task-definition health check decides whether ECS replaces the task. |
| "A service with desired count 2 means two AZs." | Tasks are spread over the **subnets you give the service**. Give it two subnets in two AZs, or both tasks may share one. |
| "The target group type is Instance." | Fargate tasks have their own ENI, so the target type is **IP**. |
| "Fargate means I don't need to think about CPU/memory." | CPU and memory are set at **task level** and only valid in certain **pairs** (for example 0.5 vCPU with 1–4 GB). Too little memory shows up as the task being **killed (exit code 137)**. |
| "Environment variables are a fine place for passwords." | They show in the console and in `describe-task-definition`. Reference **Secrets Manager** (`secrets` block) so the value is injected at start, or fetch it in code as `plat-api` does. |
| "Deleting the service deletes the logs." | Log groups **persist** until you delete them (and keep billing for storage). |
| "The image must be pushed as `amd64`." | It must match the **task's CPU architecture** (X86_64 or ARM64). Building on an Apple-silicon laptop without `--platform linux/amd64` gives `exec format error`. |
| "ECS rolling deployments are instant." | They respect **minimum healthy percent / maximum percent** and the load balancer's **deregistration delay** (default 300 s). A deploy can take minutes. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| The `plat-api:1.0.1` image and its environment variables | Post 09 |
| `plat-public-a/b`, `plat-private-a/b`, NAT | Post 04 |
| `plat-app-sg`, `plat-rds-sg` | Posts 05, 07, 08 |
| Bucket, KMS key, `plat-jobs`, RDS managed secret | Posts 05, 06, 08 |

| You create here | Used by |
|---|---|
| ECR repository **`plat/api`** | The EKS deployment (12), the CI/CD pipeline (18) |
| `plat-ecs-task-role` | Pattern reused for IRSA / Pod Identity (12) |
| ALB **`plat-alb`** and target group **`plat-api-tg`** | Alarms on 5xx and latency (21) |
| Log group **`/ecs/plat-api`** | Metric filters and agent logs (21) |

---

## Lab: Push, Deploy and Reach `plat-api` 🛠️

Work as Jim, in **N. Virginia**. Docker and your SSO profile are set up from Posts 03 and 09. Make sure the NAT gateway and RDS instance are running.

### 1. Create the repository and push

1. **ECR, Private repositories, Create repository**. Name **`plat/api`**, tag immutability **Mutable** for now, **AES-256** encryption. Create.
2. Open it and click **View push commands**. They match the following, with your account ID:

```bash
aws sso login --profile plat-admin
ACCT=$(aws sts get-caller-identity --profile plat-admin --query Account --output text)
REG=$ACCT.dkr.ecr.us-east-1.amazonaws.com

aws ecr get-login-password --profile plat-admin --region us-east-1 \
  | docker login --username AWS --password-stdin $REG

docker tag plat-api:1.0.1 $REG/plat/api:1.0.1
docker push $REG/plat/api:1.0.1
```

```text
1.0.1: digest: sha256:4b2c...e91 size: 1783
```

3. Confirm in the console that the image shows with tag **1.0.1** and its size.

Optional but wise: **Lifecycle rules, Create rule**: *image count more than 10, expire*.

### 2. Create the roles

**Task execution role.** IAM, Roles, Create role, **Elastic Container Service Task** use case. Attach **`AmazonECSTaskExecutionRolePolicy`**. Name it **`plat-ecs-exec-role`**.

**Task role.** Create another role, same trusted use case, **no managed policy**, name **`plat-ecs-task-role`**. Add an inline policy named `plat-api-access`, replacing the account ID, bucket and secret ARN with yours (copy the RDS secret ARN from Secrets Manager, name starts `rds!db-`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadRawData",
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetObject"],
      "Resource": [
        "arn:aws:s3:::plat-data-123456789012-us-east-1",
        "arn:aws:s3:::plat-data-123456789012-us-east-1/*"
      ]
    },
    {
      "Sid": "DecryptViaS3",
      "Effect": "Allow",
      "Action": "kms:Decrypt",
      "Resource": "arn:aws:kms:us-east-1:123456789012:key/<your-key-id>",
      "Condition": { "StringEquals": { "kms:ViaService": "s3.us-east-1.amazonaws.com" } }
    },
    {
      "Sid": "ReadJobs",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:Query"],
      "Resource": [
        "arn:aws:dynamodb:us-east-1:123456789012:table/plat-jobs",
        "arn:aws:dynamodb:us-east-1:123456789012:table/plat-jobs/index/*"
      ]
    },
    {
      "Sid": "ReadDbSecret",
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "arn:aws:secretsmanager:us-east-1:123456789012:secret:rds!db-*"
    },
    {
      "Sid": "DecryptDbSecret",
      "Effect": "Allow",
      "Action": "kms:Decrypt",
      "Resource": "arn:aws:kms:us-east-1:123456789012:key/<your-key-id>",
      "Condition": { "StringEquals": { "kms:ViaService": "secretsmanager.us-east-1.amazonaws.com" } }
    }
  ]
}
```

The secret was encrypted with the `plat-data` key in Post 08, so reading it needs **two** permissions: `GetSecretValue` on the secret and `kms:Decrypt` on the key (here only when the call comes through Secrets Manager). Notice the application can **read** only. The ingestion path will get write access in its own role in Post 13.

### 3. Open the app port to the load balancer

First create the load balancer's security group. **EC2, Security Groups, Create**:

| Field | Value |
|---|---|
| Name | `plat-alb-sg` |
| VPC | `plat-vpc` |
| Inbound | **HTTP 80** from `0.0.0.0/0` |
| Tag | `project = plat` |

Then open **`plat-app-sg`**, **Edit inbound rules, Add rule**: **Custom TCP 8080**, source **`plat-alb-sg`** (select it by name). Do not use a CIDR.

### 4. Create the load balancer

**EC2, Load Balancers, Create, Application Load Balancer**:

| Setting | Value |
|---|---|
| Name | `plat-alb` |
| Scheme | **Internet-facing** |
| VPC and subnets | `plat-vpc`: **`plat-public-a`** and **`plat-public-b`** |
| Security group | **`plat-alb-sg`** (remove the default) |
| Listener | HTTP :80, forward to a **new target group** |

Create the target group inside the wizard:

| Setting | Value |
|---|---|
| Target type | **IP addresses** |
| Name | `plat-api-tg` |
| Protocol and port | HTTP **8080** |
| Health check path | `/health` |
| Healthy threshold | 2, interval 15 s |

On the **Register targets** page register nothing and continue (ECS will do it). Under **Attributes** of the target group, set **Deregistration delay** to **30 seconds** so deployments are quick in a lab.

### 5. Create the cluster and task definition

1. **ECS, Clusters, Create cluster**. Name **`plat-cluster`**, infrastructure **AWS Fargate (serverless)**. Under Monitoring, turn on **Container Insights**. Create.
2. **Task definitions, Create new task definition**:

| Setting | Value |
|---|---|
| Family | `plat-api` |
| Launch type | **AWS Fargate** |
| OS / architecture | **Linux / X86_64** |
| CPU / memory | **0.5 vCPU / 1 GB** |
| Task role | **`plat-ecs-task-role`** |
| Task execution role | **`plat-ecs-exec-role`** |
| Container name | `api` |
| Image URI | `<acct>.dkr.ecr.us-east-1.amazonaws.com/plat/api:1.0.1` |
| Container port | **8080** (TCP) |
| Essential | Yes |
| Log collection | **awslogs**, group `/ecs/plat-api`, region us-east-1, prefix `api`, **create group = on** |

Environment variables (**Key / Value**):

| Key | Value |
|---|---|
| `APP_VERSION` | `1.0.1` |
| `DATA_BUCKET` | `plat-data-<acct>-us-east-1` |
| `JOBS_TABLE` | `plat-jobs` |
| `DB_HOST` | your RDS endpoint (RDS, `plat-meta`, Connectivity) |
| `DB_NAME` | `platmeta` |
| `DB_SECRET_ARN` | the RDS managed secret ARN |

Create it. This is **revision 1**.

> **Note:** The execution role created by the console path above must be allowed to create the log group. If you see `ResourceInitializationError` about logs, add `logs:CreateLogGroup` to `plat-ecs-exec-role`, or create the log group (`/ecs/plat-api`) yourself in CloudWatch first.

### 6. Create the service

Open `plat-cluster`, **Services, Create**:

| Setting | Value |
|---|---|
| Compute | **Launch type: Fargate**, latest platform version |
| Task definition | `plat-api`, latest revision |
| Service name | `plat-api-svc` |
| Desired tasks | **2** |
| Networking | VPC `plat-vpc`, subnets **`plat-private-a`** and **`plat-private-b`** |
| Security group | **`plat-app-sg`** (remove the default) |
| Public IP | **Turned off** |
| Load balancing | **Application Load Balancer**, existing `plat-alb`, listener 80, target group `plat-api-tg`, container `api:8080` |
| Health check grace period | 30 s |

Create. Watch **Tasks** move from `PROVISIONING` to `PENDING` to `RUNNING`, and **Targets** in the target group go from `initial` to `healthy`.

### 7. Call it

Copy the ALB **DNS name** (EC2, Load Balancers). Then:

```bash
ALB=plat-alb-1234567890.us-east-1.elb.amazonaws.com

curl -s http://$ALB/health
curl -s http://$ALB/
curl -s http://$ALB/data
curl -s http://$ALB/jobs/job-001
curl -s http://$ALB/datasets
```

```text
{"status": "ok"}
{"app": "plat-api", "version": "1.0.1", "host": "ip-10-20-10-87.ec2.internal"}
{"bucket": "plat-data-123456789012-us-east-1", "raw_objects": ["raw/events.csv"]}
{"job_id": "job-001", "status": "DONE", "created_at": "2026-11-08T09:00:00Z", "rows": "5050"}
[{"id": 1, "name": "events_2026_11", "s3_key": "raw/events.csv", "row_count": 5050}]
```

Run `curl -s http://$ALB/` several times: the `host` value changes between **two different task IPs** as the ALB spreads requests across tasks.

One call per dependency proves each connection: **S3** (and the KMS condition), **DynamoDB**, and **RDS through Secrets Manager**, all with no keys in the container.

### 8. Break it, and read the evidence

The task role is why those calls work. Prove it. In the IAM console remove the **`ReadJobs`** statement from `plat-api-access` (or deny it), wait about a minute, then:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://$ALB/jobs/job-001
```

```text
502
```

Open **CloudWatch, Log groups, `/ecs/plat-api`** and search `AccessDeniedException`. The log line carries the exception class and the missing action. Restore the statement and confirm `200` returns.

### 9. Deploy a new version

Change something visible in the task definition: **Create new revision**, set `APP_VERSION=1.0.2`. Then **Update service** and choose the new revision. Watch tasks start, targets turn healthy, and old tasks drain. `curl -s http://$ALB/` now shows `1.0.2`, with no downtime.

### 10. Resources you now have 📦

| Resource | Name | Cost behavior |
|---|---|---|
| ECR repository | `plat/api` | Storage only |
| IAM roles | `plat-ecs-exec-role`, `plat-ecs-task-role` | Free |
| Security group | `plat-alb-sg` (and a new rule on `plat-app-sg`) | Free |
| ALB + target group | `plat-alb`, `plat-api-tg` | **Hourly + LCU while it exists** |
| ECS cluster / task definition / service | `plat-cluster`, `plat-api`, `plat-api-svc` | Fargate charges per vCPU/GB-second while tasks run |
| Log group | `/ecs/plat-api` | Storage; set retention |

### Cleanup 🧹

When you pause, set the service's desired count to **0** (tasks stop and billing stops). Delete the ALB when you finish the day (it bills hourly even with no traffic). Keep the repository, roles, cluster and task definition, they cost nothing. Set the log group retention to **7 days**.

---

## Quick Quiz 🧠

**Q1.** Your task shows `STOPPED` with `CannotPullContainerError: ... i/o timeout`. The image exists. What do you check first?

<details>
<summary>Show answer</summary>

The **network path** from the task's subnet to ECR (and S3, which serves the layers). A private-subnet task needs a **NAT route** or **ECR (api, dkr) and S3 endpoints**. Then confirm the tag and CPU architecture.

</details>

**Q2.** `/jobs/job-001` returns 502 and the logs show `AccessDeniedException`. Which role do you fix, the execution role or the task role?

<details>
<summary>Show answer</summary>

The **task role**. Your application code runs with it. The execution role is only for ECS pulling images, writing logs and injecting secrets.

</details>

**Q3.** The service has desired count 2 but both targets stay `unhealthy`, while the container runs fine. List three likely causes.

<details>
<summary>Show answer</summary>

(1) The task SG doesn't allow **8080 from the ALB's SG**. (2) The target group's **health check path or port** is wrong (it must be `/health` on 8080). (3) The target group port or container port mapping doesn't match. Also possible: the app takes longer to start than the grace period allows.

</details>

**Q4.** You push a fixed image to tag `1.0.1` (mutable) and nothing changes in production. Why?

<details>
<summary>Show answer</summary>

Running tasks keep the image they started with, and the service only starts new tasks on deployment. Re-pushing a tag doesn't trigger anything. Use a **new tag**, register a **new task-definition revision**, and update the service (or force a new deployment).

</details>

**Q5.** Why is the Fargate target group type **IP**?

<details>
<summary>Show answer</summary>

In `awsvpc` mode each task has its **own network interface and private IP**, there is no instance to register. The service registers and deregisters the task IPs.

</details>

---

## What's Next? 🚀

ECS is the straightforward way to run containers. Kubernetes is the one most teams are asked about. You already know the model from the Kubernetes series, so the interesting part is how it plugs into **AWS identity and networking**.

👉 **[Post 12: EKS](content/aws/12-eks.md)**: create a cluster, add a managed node group, give a pod its own IAM role, and expose `plat-api` through the AWS Load Balancer Controller.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
