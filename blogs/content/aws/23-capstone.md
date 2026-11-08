---
title: "Capstone: One Request, Every Layer"
date: 2026-11-08
tags: [aws, capstone, troubleshooting, architecture, teardown, intermediate]
description: Post 23 of the AWS series. A full end-to-end run of the Platform Lab, the permission map behind every hop, a failure drill that crosses six services, the order for tearing everything down, and where to go next.
---

# Putting It All Together 🧩

Twenty-two posts built the pieces one at a time. This one runs the whole thing, then breaks it on purpose. The skill that separates intermediate from beginner on AWS isn't knowing more services. It's being able to look at a symptom and say **which layer** it belongs to: identity, network, encryption, a resource policy, or the application.

![The finished Platform Lab](content/aws/images/23-capstone.svg)

---

## The Permission Map 🗝️

For every hop in the platform, four questions have answers. Keep this table; it is the debugging checklist.

| Hop | Who is calling | What allows it (identity) | What else must allow it | Network path | Encryption |
|---|---|---|---|---|---|
| Dave uploads a CSV | Dave's session | His role's permissions, or Jim's | Bucket policy (TLS only) | Internet to S3 | SSE-KMS: the caller needs `kms:GenerateDataKey` |
| S3 to SNS | The S3 service | n/a | **Topic policy** (`s3.amazonaws.com`, source bucket) | AWS network | Topic unencrypted |
| SNS to SQS | The SNS service | n/a | **Queue policy** (`sns.amazonaws.com`, source topic) | AWS network | SSE-SQS |
| SQS to Lambda | The event source mapping | `plat-ingest-role` (receive and delete) | n/a | AWS network | SSE-SQS |
| Lambda reads S3 | `plat-ingest-role` | `s3:GetObject` | Bucket policy | Public endpoint | **KMS key policy and `kms:Decrypt` via S3** |
| Lambda writes DynamoDB | `plat-ingest-role` | `dynamodb:PutItem` | n/a | Public endpoint | AWS-owned key |
| ALB to task | The load balancer | n/a | **Security group**: `plat-app-sg` allows `plat-alb-sg` on 8080 | Private subnets | HTTP inside the VPC |
| API reads S3, DynamoDB | `plat-ecs-task-role` | S3 read, `dynamodb:GetItem` | Bucket policy | NAT or gateway endpoints | KMS via S3 |
| API reads RDS | The task (password from Secrets Manager) | `secretsmanager:GetSecretValue` | **`plat-rds-sg` allows `plat-app-sg` on 5432** | Private subnets | TLS to the database |
| Processing and training | `plat-sm-role` | S3, KMS, ECR pull | n/a | NAT and S3 endpoint | KMS via S3 |
| API calls the endpoint | `plat-ecs-task-role` | `sagemaker:InvokeEndpoint` | n/a | NAT to the runtime API | TLS |
| Pipeline deploys | Pipeline and CodeBuild roles | ECR push, ECS update, `iam:PassRole` | Connection to GitHub | NAT | n/a |
| Alarms notify | The CloudWatch service | n/a | **Topic policy** allows publish | AWS network | n/a |

Look at the "What else must allow it" column. **Half of the failures in AWS are not in the caller's IAM policy.** They are in a resource policy, a security group, or a key policy.

---

## The Debugging Order 🔎

When something fails, go down this list rather than guessing.

| Step | Question | Tool |
|---|---|---|
| 1 | **Who am I, really?** | `aws sts get-caller-identity` (or the log line showing the assumed role) |
| 2 | **Is the error a denial, or a hang?** | `AccessDenied` means identity, resource policy or KMS. A **timeout** means network. *Connection refused* means nothing is listening |
| 3 | **Which policy denied it?** | The error message often names the action and the resource. Use the policy simulator or **CloudTrail event history** (below) |
| 4 | **Is there an explicit deny, or a missing allow?** | Remember the evaluation order from Post 02 |
| 5 | **Does the network path exist?** | Route table, NAT state, security groups on **both** sides, endpoint policies |
| 6 | **Is a key involved?** | The key policy, `kms:ViaService`, key state (Enabled?) |
| 7 | **Is it a quota or a limit?** | Service Quotas, timeouts, concurrency |
| 8 | **What did the application log?** | CloudWatch Logs and Insights |

CloudTrail records API calls and their outcome, including `errorCode` and `errorMessage`. In the console open **CloudTrail, Event history**, filter by **Event name** (for example `Decrypt`) or **User name**, and read the failed event's JSON. It is the fastest way to answer *who tried what, and what did AWS say*.

---

## Lab: Run It, Break It, Fix It, Remove It 🛠️

You will need the platform running: NAT gateway, RDS, ECS service (desired 2), the ALB, the SQS/SNS/Lambda path, and the pipeline. If you paused it, run `scripts/resume-platform.sh` and recreate the NAT gateway and ALB from Posts 4 and 11. Redeploy the SageMaker endpoint with the Post 20 cell if you want the prediction step; delete it afterwards.

### Part A: The end-to-end run

Create a fresh dataset and send it in as Dave would, then follow it through every layer. In CloudShell:

```bash
ACCT=$(aws sts get-caller-identity --query Account --output text)
BUCKET=plat-data-$ACCT-us-east-1
aws s3 cp s3://$BUCKET/raw/events.csv events.csv
head -3001 events.csv > week2.csv           # header + 3000 rows
aws s3 cp week2.csv s3://$BUCKET/raw/week2.csv
```

Now check each hop, in order. Every command has an expected result.

| # | Hop | Check | You should see |
|---|---|---|---|
| 1 | S3 notification | `aws sqs get-queue-attributes --queue-url $Q --attribute-names ApproximateNumberOfMessages` right after upload | `0` or a very small number (the Lambda is quick) |
| 2 | Lambda | `aws logs tail /aws/lambda/plat-ingest --since 5m --format short \| grep recorded` | `recorded ingest-... rows=3000 key=raw/week2.csv` |
| 3 | DynamoDB | `aws dynamodb scan --table-name plat-jobs --query "Items[].[job_id.S,rows.N]" --output text` | A new row with `3000` |
| 4 | API | `curl -s http://$ALB/jobs/<that job id>` | The job as JSON, `"status": "DONE"` |
| 5 | Processing | Run the Post 19 processing cell against `raw/week2.csv` (change the `S3Uri`) | `Completed`; `train` and `validation` files appear under `processed/` |
| 6 | Training | Run the Post 20 training cell | `validation:auc` above the baseline |
| 7 | Endpoint and API | Deploy, then `curl "http://$ALB/predict?sessions=2&minutes=20&tickets=3&pro=0"` | A probability |
| 8 | Observability | Open `plat-overview` | Request counts, task count, Lambda invocations, no alarm in ALARM |
| 9 | Cost | `plat-by-service` report | The services above, with tagged cost under `project = plat` |

If a hop fails, you now have the permission map and the debugging order. Fix it before moving on.

### Part B: The failure drill

Each fault is reversible and teaches one layer. **Predict the symptom first** (write it down), inject the fault, observe, then restore.

**Fault 1: Remove an IAM allow.** In `plat-ingest-role` remove `kms:Decrypt` (or detach the whole inline policy), then upload `week3.csv`.

| Predict | Observe |
|---|---|
| Messages are received, the function fails, and they return to the queue, then land in the DLQ after three tries | Lambda `Errors` rise, logs show `AccessDenied` on KMS or S3, `plat-dlq-not-empty` alarms. Open CloudTrail event history and find the failed `Decrypt` |

Restore the permission. Redrive the DLQ message back to `plat-ingest-queue`.

**Fault 2: Break a security group.** Remove the inbound rule on `plat-rds-sg` that allows `plat-app-sg`, then call `/datasets`.

| Predict | Observe |
|---|---|
| A **hang** and then an error from the API (timeout), not an immediate refusal | `curl` takes several seconds then returns `502`. Logs show a timeout. IAM was fine the whole time |

Restore the rule. Note how different "timeout" feels from "AccessDenied".

**Fault 3: Stop the NAT gateway** (delete it, as in the Post 4 cleanup, and recreate afterwards).

| Predict | Observe |
|---|---|
| Existing tasks keep serving. Anything that needs the internet from a private subnet fails: new task starts (image pull from ECR), SSM sessions to `plat-ec2`, Studio package installs, the pipeline's deploy | Start a deployment and watch tasks fail with `CannotPullContainerError`; Session Manager shows the instance Offline |

Recreate the NAT gateway, point `plat-private-rt` at it, and release the old Elastic IP. This is the best argument for **VPC endpoints** that you will find.

**Fault 4: Disable the KMS key** (use the key `plat-data`, then re-enable it within a few minutes).

| Predict | Observe |
|---|---|
| Everything encrypted with the key stops working, **in many services at once**: S3 reads and writes, Lambda, the API's `/data`, processing jobs. A stopped EC2 instance with an encrypted volume would not start | After a short propagation delay, `/data` returns `502` with `KMSInvalidStateException` or `AccessDenied`. Lambda errors. Re-enable the key and the platform recovers without any other change |

This is why Post 05 said a key is a dependency of everything it protects. Do not run this fault if `plat-ec2` is stopped with an encrypted root volume that you need, because stopped instances cannot start until the key is enabled again.

**Debrief.** Which of the four faults would a *CloudWatch alarm* have caught, and which would only a person notice? (Faults 1 and 3 have metric signals. Fault 2 shows up as API errors. Fault 4 shows up as errors everywhere.) Which alarm did you wish you had? Add it.

### Part C: Tear it down

Do this when you finish the series. The **order** matters because of dependencies. Work through the list and tick each:

| # | Delete | Why this position |
|---|---|---|
| 1 | SageMaker endpoint, config, model; stop and delete Studio spaces and apps; delete the domain | Stops the largest hourly charges first |
| 2 | CodePipeline `plat-api-pipeline`, CodeBuild project, GitHub connection | Nothing should redeploy while you delete things |
| 3 | EKS: Kubernetes load balancer service, then node group, then cluster | Delete from the inside out |
| 4 | ECS service (desired 0, then delete), cluster, task definitions (deregister) | |
| 5 | ALB, target group, `plat-alb-sg` | After the service no longer references them |
| 6 | Lambda functions, event source mapping, S3 notification, SNS topics (after removing subscriptions), SQS queues | Remove the S3 notification first so uploads don't trigger deleted targets |
| 7 | EventBridge rules, CloudWatch alarms, dashboard, metric filters, log groups | |
| 8 | EC2 `plat-ec2` (terminate), the CloudShell VPC environment | Before the subnets |
| 9 | RDS `plat-meta` (take a final snapshot if you want one), DynamoDB `plat-jobs`, EFS (mount targets first, then the file system) | Mount targets and the DB subnet group block deleting subnets |
| 10 | VPC endpoints, NAT gateway, Elastic IP, then **the VPC** (subnets, route tables, internet gateway, security groups) | Everything above holds ENIs in these subnets |
| 11 | ECR repositories (delete images), the S3 buckets (delete **all versions** and delete markers, then the bucket) | Versioned buckets don't delete while any version exists |
| 12 | CloudFormation stacks (`plat-bucket-demo`), Terraform stacks (`terraform destroy`), Service Catalog provisioned products, portfolio | Each through its own tool |
| 13 | Secrets in Secrets Manager (they have a recovery window), **schedule the KMS key for deletion** (minimum 7 days) | Last, so nothing that needs them is left |
| 14 | IAM roles and policies you created, Identity Center users and permission sets if you wish, the budgets and anomaly monitor | Last of all |

Afterwards, wait a day and open **Cost Explorer** for the last 7 days grouped by service. Anything still showing cost is something you forgot. This check is how you learn to trust your own cleanup.

### Part D: Rebuild it as code

You clicked everything once. The next pass is where Posts 16 and 18 pay off. A realistic plan:

| Stage | Put in Git | Tool |
|---|---|---|
| 1. Network | VPC, subnets, route tables, endpoints, NAT | Terraform or CloudFormation |
| 2. Security | KMS key, roles, security groups | Same, in a separate stack, with outputs |
| 3. Data | S3, DynamoDB, RDS, EFS | Same |
| 4. Compute | ECR, ECS cluster and service, ALB | Same |
| 5. Events | SNS, SQS, Lambda, EventBridge | Same |
| 6. ML | Roles, ECR image build, training pipeline | Pipeline stages |
| 7. Delivery | CodePipeline and CodeBuild themselves | Same, once |

Split the stacks by **how often they change and who owns them**: the network changes rarely, the application changes daily.

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "If it works in the console, it will work in the pipeline." | The pipeline runs as a **different role**, from a different network. Permissions, endpoints and proxies don't carry over. |
| "AccessDenied is always an IAM problem." | It can come from a resource policy, an SCP, a KMS key policy or key state, or a permissions boundary. |
| "A timeout and an AccessDenied are the same kind of failure." | A timeout is almost always **network**. An access error means the request arrived and was refused. |
| "Delete the VPC first to save time." | It fails while any ENI, endpoint, NAT gateway, load balancer or database still sits in it. Delete from the top down. |
| "Cleanup is done when the console is empty." | Check **every region you used**, the **billing report the next day**, and snapshots, logs, volumes, addresses and buckets. |
| "I understand IAM, so I understand security." | Identity is one layer. Networks, encryption, logging and **change control** (Git, pipelines, approvals) are the rest. |

---

## Quick Quiz 🧠

**Q1.** A request to `/datasets` takes eight seconds and then returns 502. A request to `/data` returns 502 immediately with `AccessDenied` in the logs. Which one is a network problem?

<details>
<summary>Show answer</summary>

`/datasets`: the delay and timeout point to a blocked network path (security group, route, or DB subnet). `/data` is an immediate denial, which is an identity, bucket policy or KMS problem.

</details>

**Q2.** You disable the `plat-data` key and several unrelated services fail. Why?

<details>
<summary>Show answer</summary>

Anything encrypted with that key (S3 objects, EBS volumes, jobs reading them) needs the key to be **enabled** to decrypt. Disabling it breaks them all at once. A key is a shared dependency.

</details>

**Q3.** Why can't you delete the subnets while the RDS subnet group exists?

<details>
<summary>Show answer</summary>

The DB subnet group references the subnets, and the database holds network interfaces in them. Delete the **database**, then the subnet group, then the subnets.

</details>

**Q4.** An S3 notification delivers to SNS, but the queue stays empty. List the first two places to check.

<details>
<summary>Show answer</summary>

(1) The **queue access policy**: it must allow `sns.amazonaws.com` to `sqs:SendMessage` from the topic. (2) The **subscription**: it exists, is confirmed or auto-confirmed for SQS, and isn't filtered out by a filter policy.

</details>

**Q5.** After teardown, Cost Explorer still shows cost for the day after you finished. Is that necessarily a problem?

<details>
<summary>Show answer</summary>

Not necessarily: cost data **lags**, and the last hours of use appear a day later. Check again after a further day. If the same line keeps appearing, find the resource (use the usage type and resource-level data).

</details>

---

## Where to Go Next 🧭

This series stayed deliberately in one account, one region and the console. The natural next topics, roughly in order of payoff:

| Topic | Why it's next |
|---|---|
| **AWS Organizations, SCPs and multiple accounts** | The strongest boundary AWS offers; separate dev and prod |
| **Infrastructure as code for the whole platform** | Part D above, with remote state and a pipeline that applies it |
| **CloudTrail, Config and GuardDuty** | Audit, compliance and threat detection |
| **Autoscaling** (ECS, endpoints, node groups) | Cost and resilience |
| **Step Functions and SageMaker Pipelines** | Orchestrating multi-step data and ML flows |
| **Private networking: PrivateLink, no NAT** | A tighter and cheaper network |
| **Secrets rotation, WAF, and certificates (ACM, HTTPS on the ALB)** | Real production hardening |

---

## The Series in One Page 🗺️

| Part | Posts | You built |
|---|---|---|
| Foundations | 1 | Account safety, the map, the budget |
| Identity and Networking | 2 to 5 | IAM, Identity Center, VPC, KMS, Secrets Manager |
| Storage and Databases | 6 to 8 | S3, security groups, EFS, RDS, DynamoDB |
| Compute | 9 to 12 | Linux, Docker, EC2, ECR, ECS, EKS |
| Serverless | 13 to 14 | Lambda, SQS, SNS, EventBridge |
| Delivery | 15 to 18 | Git, webhooks, CloudFormation, Terraform, Service Catalog, CodeBuild, CodePipeline |
| Machine learning | 19 to 20 | Environments, Studio, processing, training, endpoint |
| Observability and cost | 21 to 22 | CloudWatch, the agent, alarms, Cost Explorer, Budgets |
| Capstone | 23 | The whole flow, failures, teardown |

Thanks for building it with me. Open the console, break something, and find out why.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
