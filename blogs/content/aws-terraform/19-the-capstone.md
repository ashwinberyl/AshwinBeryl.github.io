---
title: "The Capstone: Bring It Up, Check It, Break It, Tear It Down"
date: 2026-11-11
tags: [aws, terraform, capstone, verification, failure-drills, cost, teardown, intermediate]
description: Post 19 of the AWS on Terraform series. The whole platform from one command, a verification script that skips what is switched off, four failure drills repaired through the code, an honest cost table, and the exact order to remove everything including the state bucket.
---

# Putting It All Together 🧩

Eighteen posts built the pieces. This one runs the whole thing the way you would run a real environment: bring it up, **check it from outside Terraform's point of view**, break it on purpose, repair it through the code, and take it away completely.

Everything here mirrors the capstone of the AWS series (its Post 23), with one difference that matters: where that post told you which console pages to open, this one is `make` targets and a script you can read.

![The platform](content/aws-terraform/images/19-the-platform.svg)

---

## The Map: Where Each Hop Is Built 🗝️

The AWS series ended with a **permission map**: for each hop in the platform, who calls, what allows it, what else must allow it. Here is the same map with the place in this repository where each rule lives:

| Hop | Allowed by | Also needed | Defined in |
|---|---|---|---|
| Upload to S3 | Caller's role | Bucket policy (TLS only), `kms:GenerateDataKey` | `modules/s3-bucket`, `30-security` |
| S3 to SQS | **Queue policy** for `s3.amazonaws.com` from this bucket | | `60-events` |
| SQS to Lambda | `plat-ingest-role` (receive, delete) | | `60-events` |
| Lambda reads S3 | `s3:GetObject` on `raw/*` | **`kms:Decrypt`** | `60-events` |
| Lambda writes DynamoDB | `dynamodb:PutItem` | **`kms:GenerateDataKey`** (table uses the key) | `60-events` |
| Failed message to DLQ | `redrive_policy` | | `60-events` |
| ALB to task | `plat-alb-sg` egress, `plat-api-sg` ingress | Private subnets | `52-ecs` |
| Task reads S3, DynamoDB | `plat-ecs-task-role` | `kms:Decrypt` | `52-ecs` |
| Task reads RDS | `GetSecretValue` on the managed secret | `plat-rds-sg` allows `plat-app-sg` on 5432 | `40-data`, `52-ecs` |
| Pods read the same | Pod Identity role | `rds_from_cluster` rule | `55-eks` |
| Processing and training | `plat-sm-role` | `kms:CreateGrant` | `70-ml` |
| Pipeline deploys | Pipeline and build roles | `iam:PassRole` with condition | `80-delivery` |
| Alarms notify | CloudWatch | **Topic policy** | `60-events`, `90-observe` |
| Terraform itself | `plat-tf-plan`, `plat-tf-apply` | OIDC `sub` conditions | `bootstrap`, Post 18 |

The highlighted cells are the same ones that caused the mistakes in the AWS series, and they are the ones the tests, checks and drills below exercise.

---

## What Costs What 💸

Prices are approximate on-demand figures for `us-east-1`, rounded, and **change**: treat them as orders of magnitude and check the pricing pages before relying on them.

| Switch | Stack | About per hour | About per day |
|---|---|---|---|
| `enable_nat` | 20-network | $0.045 + data | $1.10 |
| `enable_secretsmanager_endpoint` | 30-security | $0.01 per endpoint per AZ | $0.25 |
| `enable_rds` (db.t4g.micro) | 40-data | $0.02 | $0.40 |
| `enable_ec2` (t3.micro) | 50-ec2 | $0.01 | $0.25 |
| `enable_ssm_endpoints` | 50-ec2 | $0.03 (three) | $0.75 |
| `enable_service` (ALB + one Fargate task) | 52-ecs | $0.04 | $1.00 |
| `enable_eks` (control plane + one t3.medium) | 55-eks | $0.14 | $3.40 |
| `enable_endpoint` (ml.t2.medium) | 70-ml | $0.06 | $1.35 |
| Everything else | | cents per month | |

The two that surprise people: **the NAT gateway** (it bills just for existing, and the `full` configuration needs it) and **EKS** (the control plane bills whether or not a pod is running). `make pause` switches all of these off in one command, and `make full` switches them on again.

---

## Reading the Tools 📖

### Bring it up

```hcl
# Makefile
# Stacks apply in this order and destroy in the reverse order.
STACKS := 10-identity 20-network 30-security 40-data 50-ec2 52-ecs 55-eks 60-events 70-ml 80-delivery 90-observe 95-cost
REVERSE := $(shell echo $(STACKS) | tr ' ' '\n' | tac | tr '\n' ' ')

.PHONY: fmt validate plan up full down pause verify smoke test destroy-bootstrap

fmt:
	terraform fmt -recursive

validate:
	@for d in bootstrap stacks/* modules/* labs/*; do \
	  echo "== $$d"; terraform -chdir=$$d init -backend=false -input=false >/dev/null && terraform -chdir=$$d validate || exit 1; \
	done

plan:
	@for s in $(STACKS); do echo "== plan $$s"; scripts/tf.sh $$s plan -input=false || exit 1; done

# Everything at its defaults: the cheap configuration. Switches you turned on by hand go back off.
up:
	@for s in $(STACKS); do echo "== apply $$s"; scripts/tf.sh $$s apply -input=false -auto-approve || exit 1; done

# Everything on except EKS and the SageMaker endpoint (those need a decision of their own).
# Usage: make full ALERT_EMAIL=you@example.com
ALERT_EMAIL ?=
full:
	scripts/tf.sh 10-identity apply -input=false -auto-approve
	scripts/tf.sh 20-network apply -input=false -auto-approve -var enable_nat=true
	scripts/tf.sh 30-security apply -input=false -auto-approve
	scripts/tf.sh 40-data apply -input=false -auto-approve -var enable_rds=true
	scripts/tf.sh 50-ec2 apply -input=false -auto-approve
	scripts/tf.sh 52-ecs apply -input=false -auto-approve -var enable_service=true
	scripts/tf.sh 60-events apply -input=false -auto-approve -var alert_email=$(ALERT_EMAIL)
	scripts/tf.sh 70-ml apply -input=false -auto-approve
	scripts/tf.sh 80-delivery apply -input=false -auto-approve -var enable_deploy_stage=true
	scripts/tf.sh 90-observe apply -input=false -auto-approve
	scripts/tf.sh 95-cost apply -input=false -auto-approve -var alert_email=$(ALERT_EMAIL)

down:
	@for s in $(REVERSE); do echo "== destroy $$s"; scripts/tf.sh $$s destroy -input=false -auto-approve || exit 1; done

# Turn off the hourly-billed pieces but keep everything else.
pause:
	scripts/tf.sh 20-network apply -input=false -auto-approve -var enable_nat=false
	scripts/tf.sh 30-security apply -input=false -auto-approve -var enable_secretsmanager_endpoint=false
	scripts/tf.sh 40-data apply -input=false -auto-approve -var enable_rds=false
	scripts/tf.sh 52-ecs apply -input=false -auto-approve -var enable_service=false
	scripts/tf.sh 55-eks apply -input=false -auto-approve -var enable_eks=false
	scripts/tf.sh 70-ml apply -input=false -auto-approve -var enable_endpoint=false
	scripts/tf.sh 50-ec2 apply -input=false -auto-approve -var enable_ssm_endpoints=false
	scripts/tf.sh 80-delivery apply -input=false -auto-approve
	scripts/tf.sh 90-observe apply -input=false -auto-approve

verify:
	scripts/verify.sh

smoke:
	scripts/verify.sh --smoke --poison

test:
	terraform -chdir=modules/s3-bucket init -backend=false -input=false >/dev/null && terraform -chdir=modules/s3-bucket test
	terraform -chdir=modules/vpc init -backend=false -input=false >/dev/null && terraform -chdir=modules/vpc test

# The very last step, after `make down`. Asks you to type the account id.
destroy-bootstrap:
	scripts/destroy-bootstrap.sh
```

Three targets do different jobs:

* **`make up`**: every stack at its **defaults**, the cheap configuration. Switches you turned on by hand go back **off**, because variables passed with `-var` are never stored.
* **`make full`**: the hourly-billed switches on (NAT, RDS, service, deploy stage), except EKS and the SageMaker endpoint, which need decisions of their own. Pass your address: `make full ALERT_EMAIL=you@example.com`.
* **`make pause`**: the hourly pieces off, and the stacks that observe them re-applied so alarms and widgets for a missing service disappear.

If you adopted the pipeline in Post 18, remember that **a switch is a commit** (`toggles.auto.tfvars`); these targets are for working locally.

### Check it

```bash
# scripts/verify.sh
#!/usr/bin/env bash
# End-to-end check of the whole platform, from the AWS side (not from Terraform's point of view).
#   scripts/verify.sh            checks every component that exists and skips the switched-off ones
#   scripts/verify.sh --smoke    also uploads a CSV and waits for the ingest pipeline to record it
#   scripts/verify.sh --poison   also drops a poison file and waits for it to reach the dead-letter queue
set -uo pipefail

REGION="${AWS_REGION:-us-east-1}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
DATA="plat-data-${ACCOUNT}-${REGION}"
STATE="plat-tfstate-${ACCOUNT}-${REGION}"
pass=0; fail=0; skip=0

ok()   { echo "PASS  $1"; pass=$((pass+1)); }
bad()  { echo "FAIL  $1${2:+ -> $2}"; fail=$((fail+1)); }
skp()  { echo "SKIP  $1 ($2)"; skip=$((skip+1)); }

# expect <name> <expected output> <command...>
expect() {
  local name="$1" want="$2"; shift 2
  local got; got="$("$@" 2>&1 | tr -d '\r' | head -c 300)"
  if [ "$got" = "$want" ]; then ok "$name"; else bad "$name" "wanted '$want', got '$got'"; fi
}

echo "== account $ACCOUNT, region $REGION"

echo "== foundations"
expect "state bucket versioned"      "Enabled" aws s3api get-bucket-versioning --bucket "$STATE" --query Status --output text
expect "VPC exists"                  "1"       aws ec2 describe-vpcs --filters Name=tag:Name,Values=plat-vpc --query 'length(Vpcs)' --output text
expect "4 subnets"                   "4"       aws ec2 describe-subnets --filters Name=tag:project,Values=plat --query 'length(Subnets)' --output text
NAT=$(aws ec2 describe-nat-gateways --filter Name=state,Values=available,pending --query 'length(NatGateways)' --output text)
echo "INFO  NAT gateways running: $NAT"
expect "KMS key rotation on"         "True"    aws kms get-key-rotation-status --key-id alias/plat-data --query KeyRotationEnabled --output text
expect "secret encrypted with plat-data" "True" bash -c "aws secretsmanager describe-secret --secret-id plat/demo/api-key --query KmsKeyId --output text | grep -q key/ && echo True"
expect "demo reader role"            "plat-demo-reader" aws iam get-role --role-name plat-demo-reader --query Role.RoleName --output text

echo "== data"
expect "data bucket uses KMS"        "aws:kms" aws s3api get-bucket-encryption --bucket "$DATA" --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault.SSEAlgorithm' --output text
expect "jobs table active"           "ACTIVE"  aws dynamodb describe-table --table-name plat-jobs --query Table.TableStatus --output text
expect "jobs TTL on"                 "ENABLED" aws dynamodb describe-time-to-live --table-name plat-jobs --query TimeToLiveDescription.TimeToLiveStatus --output text
expect "EFS available"               "available" aws efs describe-file-systems --query 'FileSystems[?Name==`plat-efs`]|[0].LifeCycleState' --output text
RDS=$(aws rds describe-db-instances --query 'length(DBInstances[?DBInstanceIdentifier==`plat-meta`])' --output text)
if [ "$RDS" = "1" ]; then expect "RDS available" "available" aws rds describe-db-instances --db-instance-identifier plat-meta --query 'DBInstances[0].DBInstanceStatus' --output text; else skp "RDS plat-meta" "enable_rds is off"; fi

echo "== compute"
IID=$(aws ec2 describe-instances --filters Name=tag:Name,Values=plat-ec2 Name=instance-state-name,Values=running --query 'Reservations[0].Instances[0].InstanceId' --output text 2>/dev/null)
if [ -n "$IID" ] && [ "$IID" != "None" ]; then
  ok "plat-ec2 running ($IID)"
  expect "plat-ec2 reachable by Session Manager" "Online" aws ssm describe-instance-information --filters Key=InstanceIds,Values="$IID" --query 'InstanceInformationList[0].PingStatus' --output text
else skp "plat-ec2" "not running"; fi
expect "ECR repo"                    "plat-api" aws ecr describe-repositories --repository-names plat-api --query 'repositories[0].repositoryName' --output text
expect "ECS cluster"                 "ACTIVE"   aws ecs describe-clusters --clusters plat-cluster --query 'clusters[0].status' --output text
SVC=$(aws ecs describe-services --cluster plat-cluster --services plat-api-svc --query 'services[?status==`ACTIVE`]|length(@)' --output text 2>/dev/null)
if [ "$SVC" = "1" ]; then
  expect "API tasks running" "1" bash -c "aws ecs describe-services --cluster plat-cluster --services plat-api-svc --query 'services[0].runningCount>=\`1\`' --output text | sed 's/True/1/;s/False/0/'"
  ALB=$(aws elbv2 describe-load-balancers --names plat-alb --query 'LoadBalancers[0].DNSName' --output text)
  expect "ALB answers (HTTP status)" "200" curl -s -o /dev/null -w '%{http_code}' "http://$ALB/"
else skp "ECS service plat-api-svc" "enable_service is off"; fi
EKS=$(aws eks list-clusters --query 'length(clusters[?@==`plat-eks`])' --output text)
if [ "$EKS" = "1" ]; then expect "EKS cluster" "ACTIVE" aws eks describe-cluster --name plat-eks --query cluster.status --output text; else skp "EKS plat-eks" "enable_eks is off"; fi

echo "== events"
expect "ingest Lambda"               "Active"  aws lambda get-function --function-name plat-ingest --query Configuration.State --output text
expect "report Lambda"               "Active"  aws lambda get-function --function-name plat-report --query Configuration.State --output text
expect "nightly rule enabled"        "ENABLED" aws events describe-rule --name plat-nightly-report --query State --output text
expect "ec2 state rule enabled"      "ENABLED" aws events describe-rule --name plat-ec2-state-change --query State --output text
QURL=$(aws sqs get-queue-url --queue-name plat-ingest-queue --query QueueUrl --output text)
expect "ingest queue has a DLQ"      "1"       bash -c "aws sqs get-queue-attributes --queue-url $QURL --attribute-names RedrivePolicy --query 'length(Attributes)' --output text"

echo "== ml, delivery, observability, cost"
SM=$(aws sagemaker list-domains --query 'length(Domains[?DomainName==`plat-studio`])' --output text)
if [ "$SM" = "1" ]; then ok "SageMaker domain plat-studio"; else skp "SageMaker domain" "enable_studio is off"; fi
EP=$(aws sagemaker list-endpoints --name-contains plat-churn --query 'length(Endpoints)' --output text)
if [ "$EP" != "0" ]; then expect "churn endpoint in service" "InService" aws sagemaker describe-endpoint --endpoint-name plat-churn --query EndpointStatus --output text; else skp "plat-churn endpoint" "enable_endpoint is off"; fi
expect "GitHub connection authorised" "AVAILABLE" aws codestar-connections list-connections --query 'Connections[?ConnectionName==`plat-github`]|[0].ConnectionStatus' --output text
expect "pipeline exists"             "plat-api-pipeline" aws codepipeline get-pipeline --name plat-api-pipeline --query pipeline.name --output text
expect "dashboard exists"            "plat-overview" aws cloudwatch get-dashboard --dashboard-name plat-overview --query DashboardName --output text
expect "alarms exist (at least 2)"   "True"    bash -c "aws cloudwatch describe-alarms --alarm-name-prefix plat- --query 'length(MetricAlarms)>=\`2\`' --output text"
expect "budget exists"               "plat-monthly-guard" aws budgets describe-budget --account-id "$ACCOUNT" --budget-name plat-monthly-guard --query Budget.BudgetName --output text

if [[ " $* " == *" --smoke "* ]]; then
  echo "== smoke test: S3 -> SQS -> Lambda -> DynamoDB"
  KEY="raw/verify-$(date +%s).csv"
  printf 'id,value\n1,a\n2,b\n3,c\n' > /tmp/verify.csv
  aws s3 cp /tmp/verify.csv "s3://$DATA/$KEY" --only-show-errors
  for i in $(seq 1 20); do
    ROWS=$(aws dynamodb get-item --table-name plat-jobs --key "{\"job_id\":{\"S\":\"$KEY\"}}" --query 'Item.rows.N' --output text 2>/dev/null)
    [ -n "$ROWS" ] && [ "$ROWS" != "None" ] && break
    sleep 3
  done
  if [ "$ROWS" = "3" ]; then ok "object ingested, 3 rows recorded"; else bad "ingest pipeline" "no item with rows=3 after 60 s"; fi
fi

if [[ " $* " == *" --poison "* ]]; then
  echo "== poison test: a failing message must reach the dead-letter queue"
  printf 'POISON\n' > /tmp/poison.csv
  aws s3 cp /tmp/poison.csv "s3://$DATA/raw/poison-$(date +%s).csv" --only-show-errors
  DLQ=$(aws sqs get-queue-url --queue-name plat-ingest-dlq --query QueueUrl --output text)
  for i in $(seq 1 40); do
    N=$(aws sqs get-queue-attributes --queue-url "$DLQ" --attribute-names ApproximateNumberOfMessages --query 'Attributes.ApproximateNumberOfMessages' --output text)
    [ "$N" -ge 1 ] 2>/dev/null && break
    sleep 10
  done
  if [ "${N:-0}" -ge 1 ] 2>/dev/null; then ok "poison message reached the DLQ (depth $N)"; else bad "dead-letter queue" "still empty after 400 s"; fi
fi

echo
echo "passed $pass, failed $fail, skipped $skip"
[ "$fail" -eq 0 ]
```

`verify.sh` asks **AWS** whether things are true, using the CLI and no Terraform at all. That independence is the point: a plan tells you the code matches state, and this tells you the platform works. Four design choices make it usable:

* **It skips what is off.** A component that is switched off prints `SKIP`, not `FAIL`, so one script serves every configuration.
* **`expect` compares an exact output** to an expected value and records the difference.
* **`--smoke`** runs the real data path: it uploads a three-row CSV and waits up to 60 seconds for the ingest function to record `rows = 3`.
* **`--poison`** uploads a file containing `POISON` and waits for the dead-letter queue to receive it, a test that **a failure is handled**, which is the part that normally goes untested.

The script exits non-zero if any check fails, so it can run in CI after an apply.

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "`terraform apply` succeeding means the platform works." | It means the **API calls succeeded**. Only a check from outside, like `verify.sh`, shows the data path and the alarms work. |
| "`make up` brings everything on." | It applies the **defaults**, which keep costly pieces off. `make full` turns them on. |
| "`make down` is all I need." | It destroys the 12 stacks. The state bucket and CI roles survive, by design, and a few objects (an RDS snapshot) outlive their stack. |
| "Destroy order doesn't matter, Terraform sorts it out." | It sorts out dependencies **within** a state, not across stacks. Reverse order is what keeps `52-ecs` from disappearing while `80-delivery` still points at it. |
| "The SageMaker domain deletes like everything else." | Not while apps exist. Delete them first. |
| "Deleting the EKS cluster removes the load balancer." | Delete the Kubernetes Service first, or the AWS load balancer stays and blocks the VPC. |
| "The KMS key is gone after destroy." | It is **scheduled** for deletion (7 days here). The alias is removed at once, so a rebuild can reuse the name. |
| "A drill breaks the platform for good." | Each is repaired by the plan, because the broken thing is in the code or in a managed attribute. |
| "`verify.sh` replaces monitoring." | It runs when you run it. The alarms from Post 14 watch continuously. |
| "If the console is empty, the cost is zero." | Check snapshots, log groups and buckets, and look at the bill a day later. |
| "I can destroy the state bucket with `terraform destroy`." | It is protected by `prevent_destroy`, holds bootstrap's own state, and is versioned. `scripts/destroy-bootstrap.sh` does the required steps in order. |
| "Cost allocation tags are removed with the stack." | Destroying the resource makes them `Inactive`. The tags stay on resources until those are deleted. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| Every stack and its switches | Posts 03 to 15 |
| State operations for repair | Post 16 |
| Tests and checks | Post 17 |
| The pipeline | Post 18 |

| You get from this post | Used by |
|---|---|
| `make full`, `make pause`, `make verify`, `make smoke` | Your day-to-day work |
| `scripts/destroy-bootstrap.sh` | The very end |

### Console clicks you no longer make

The AWS series' capstone was a checklist of console pages. Here is what became of each:

| AWS capstone part | Here |
|---|---|
| **A. The end-to-end run**, nine checks by hand | `make smoke` and `make verify` |
| **B. The failure drill**, four experiments | The four drills below, each repaired by a plan |
| **C. Tear it down**, fourteen manual steps | `make down`, then `make destroy-bootstrap` |
| **D. Rebuild it as code**, seven stages | The whole series. Stages map to Posts 04 to 15 |

---

## Lab: Run It, Break It, Fix It, Remove It 🛠️

### A. Bring it up

Make sure the one-time manual steps are done: Identity Center is enabled (Post 03), bootstrap is applied (Post 01), and you can sign in as an admin.

```bash
export AWS_PROFILE=plat-admin AWS_REGION=us-east-1
make full ALERT_EMAIL=you@example.com
```

Each stack prints its own plan and apply. The whole run takes roughly 25 to 40 minutes, mostly RDS (about ten) and the service (about three). It ends:

```
== apply 95-cost
Apply complete! Resources: 2 added, 0 changed, 0 destroyed.
```

Two things need you:

1. **Click the confirmation link** in the SNS email (Post 11).
2. **Authorise the GitHub connection** (Post 12), unless you already did.

### B. Check it

```bash
make verify
```

```
== account 123456789012, region us-east-1
== foundations
PASS  state bucket versioned
PASS  VPC exists
PASS  4 subnets
INFO  NAT gateways running: 1
PASS  KMS key rotation on
PASS  secret encrypted with plat-data
PASS  demo reader role
== data
PASS  data bucket uses KMS
PASS  jobs table active
PASS  jobs TTL on
PASS  EFS available
PASS  RDS available
== compute
PASS  plat-ec2 running (i-0a1b2c3d4e5f67890)
PASS  plat-ec2 reachable by Session Manager
PASS  ECR repo
PASS  ECS cluster
PASS  API tasks running
PASS  ALB answers (HTTP status)
SKIP  EKS plat-eks (enable_eks is off)
== events
PASS  ingest Lambda
PASS  report Lambda
PASS  nightly rule enabled
PASS  ec2 state rule enabled
PASS  ingest queue has a DLQ
== ml, delivery, observability, cost
PASS  SageMaker domain plat-studio
SKIP  plat-churn endpoint (enable_endpoint is off)
PASS  GitHub connection authorised
PASS  pipeline exists
PASS  dashboard exists
PASS  alarms exist (at least 2)
PASS  budget exists

passed 28, failed 0, skipped 2
```

(`plat-ec2 reachable by Session Manager` needs the NAT or the SSM endpoints, and passes here because `full` turned the NAT on.) Now the data path and the failure path:

```bash
make smoke
```

```
== smoke test: S3 -> SQS -> Lambda -> DynamoDB
PASS  object ingested, 3 rows recorded
== poison test: a failing message must reach the dead-letter queue
PASS  poison message reached the DLQ (depth 1)
```

The poison test takes three to four minutes: that is the SQS redrive behaviour from Post 11, measured. Clean up its leftovers: `aws sqs purge-queue --queue-url $(terraform -chdir=stacks/60-events output -raw dlq_url)`.

### C. The failure drills

For each drill, **predict first**, then run it, then repair it through Terraform.

#### Drill 1: remove a KMS permission

In `stacks/60-events/main.tf`, delete the `UseDataKey` statement from `data.aws_iam_policy_document.ingest_access`.

**Predict:** uploads are received, the function fails on the S3 read, the message returns to the queue, and after three tries it lands in the DLQ. The DLQ alarm fires.

```bash
scripts/tf.sh 60-events apply -var alert_email=you@example.com
B=$(terraform -chdir=stacks/40-data output -raw data_bucket)
aws s3 cp /tmp/sample.csv s3://$B/raw/drill1.csv
aws logs tail /aws/lambda/plat-ingest --since 2m | grep -i "denied" | head -2
```

```
failed 7d3e...: An error occurred (AccessDenied) when calling the GetObject operation: User: arn:aws:sts::123456789012:assumed-role/plat-ingest-role/plat-ingest is not authorized to perform: kms:Decrypt on the resource associated with this ARN because no identity-based policy allows the kms:Decrypt action
```

The message names the principal, the action and the reason. After about four minutes, `plat-dlq-not-empty` goes to `ALARM` and the email arrives. **Repair:** put the statement back (`git checkout stacks/60-events/main.tf`), apply, and redrive the DLQ message (Post 11). The plan was the repair.

#### Drill 2: remove a network rule

Delete `aws_vpc_security_group_ingress_rule.api_from_alb` in `stacks/52-ecs/main.tf` and apply with `-var enable_service=true`.

**Predict:** not an access error but a **hang**: the load balancer can no longer reach the tasks, health checks time out, and requests return `504` after a delay. IAM was fine the whole time.

```bash
time curl -s -o /dev/null -w '%{http_code}\n' http://$ALB/
```

```
504

real    0m60.2s
```

**Repair:** restore the file and apply. The lesson from the AWS series holds: a **timeout** is network; an **AccessDenied** is policy.

#### Drill 3: take the NAT away

```bash
scripts/tf.sh 20-network apply            # defaults: NAT off
aws ecs update-service --cluster plat-cluster --service plat-api-svc --force-new-deployment >/dev/null
sleep 120
aws ecs describe-services --cluster plat-cluster --services plat-api-svc --query 'services[0].events[:2].message' --output text
```

**Predict:** the running task keeps serving; the **new** task cannot pull its image from the public registry, so the deployment stalls.

```
... unable to pull ... CannotPullContainerError ... i/o timeout
```

Circuit breaker and rollback (Post 09) return the service to the last working revision. **Repair:** `scripts/tf.sh 20-network apply -var enable_nat=true`. In a real environment you would use the ECR endpoints instead of a NAT for image pulls; this drill shows why the path out has to be designed.

#### Drill 4: disable the key

```bash
aws kms disable-key --key-id alias/plat-data
sleep 60
aws s3 cp s3://$B/raw/sample.csv - 2>&1 | head -2
```

**Predict:** everything encrypted with the key fails **at once**: S3 reads, the Lambda, DynamoDB, the API's data routes, SageMaker.

```
An error occurred (KMSInvalidStateException) when calling the GetObject operation: arn:aws:kms:us-east-1:123456789012:key/... is disabled.
```

The plan sees it, too:

```bash
scripts/tf.sh 30-security plan
```

```
  # aws_kms_key.data will be updated in-place
  ~ is_enabled = false -> true
Plan: 0 to add, 1 to change, 0 to destroy.
```

**Repair:** `aws kms enable-key --key-id alias/plat-data` or apply the plan. No other change is needed; the platform recovers. This is the most important lesson of the series: **one shared key is a single point of failure**, and Terraform shows you its health.

### D. Pause and resume

```bash
make pause
make verify | tail -1
make full ALERT_EMAIL=you@example.com
```

After `pause`, `verify` prints `SKIP` for what is off, and the observability stack has removed the alarms and widgets for the missing service. After `full` they return. This is the loop you'll use between lab sessions.

### E. Tear it all down

Before Terraform, remove what Terraform doesn't own:

```bash
# 1. Kubernetes objects that created AWS load balancers (only if you used EKS)
kubectl delete -f stacks/55-eks/manifests/plat-api.yaml
# 2. SageMaker apps (Studio won't delete while any exist): list and delete them as in Post 13
D=$(aws sagemaker list-domains --query 'Domains[0].DomainId' --output text)
aws sagemaker list-apps --domain-id $D --query 'Apps[?Status!=`Deleted`].[AppType,AppName,UserProfileName,SpaceName]' --output text
```

Then:

```bash
make down
```

```
== destroy 95-cost
== destroy 90-observe
== destroy 80-delivery
== destroy 70-ml
== destroy 60-events
== destroy 55-eks
== destroy 52-ecs
== destroy 50-ec2
== destroy 40-data
== destroy 30-security
== destroy 20-network
== destroy 10-identity
```

The order is the reverse of the apply order, and each step is there for a reason: the **delivery** stack points at the ECS service, so it goes first; **events** go before the data they read; **data** goes before the network because mount targets and the database subnet group hold network interfaces in the subnets; the **network** goes last.

Look for what Terraform left behind:

```bash
aws rds describe-db-snapshots --query 'DBSnapshots[].DBSnapshotIdentifier' --output text
aws resourcegroupstaggingapi get-resources --tag-filters Key=project,Values=plat --query 'ResourceTagMappingList[].ResourceARN' --output text
```

```
plat-meta-final
arn:aws:kms:us-east-1:123456789012:key/...
```

The final RDS snapshot is the one you asked for; delete it if you don't want it (`aws rds delete-db-snapshot --db-snapshot-identifier plat-meta-final`). The key is pending deletion and disappears after its 7-day window. Anything **else** the tag search returns is something that escaped: investigate it.

Finally, the state bucket and the CI roles, which Terraform deliberately protected:

```bash
make destroy-bootstrap
```

```
This deletes bucket plat-tfstate-123456789012-us-east-1 and the CI roles. Type the account id (123456789012) to continue: 123456789012
== 1. other stacks must be destroyed first
== 2. move bootstrap's state back to a local file
== 3. allow the bucket to be destroyed, then empty it (all versions and delete markers)
== 4. destroy
Destroy complete! Resources: 13 destroyed.
```

The script checks that no other stack still has resources, moves bootstrap's own state out of the bucket it is about to delete, turns `prevent_destroy` off **in your working copy**, empties every version, and destroys. Afterwards `git checkout bootstrap/main.tf` restores the guard. (The number of resources depends on whether bootstrap created the OIDC provider.)

What remains by hand: the **Identity Center instance** you enabled at the start (free, and shared by anything else in the account), any hand-made buckets from Post 16, and the GitHub repository.

### F. Resources you now have 📦

None. That's the point of a clean teardown: the account is as you found it, and the code in the repository can build it again in an afternoon.

---

## Quick Quiz 🧠

**Q1.** `make verify` prints `SKIP  EKS plat-eks (enable_eks is off)`. Is that a failure?

<details>
<summary>Show answer</summary>

No. A disabled component isn't expected to exist, so the script **skips** it. The same script then works for the cheap configuration and the full one, and only a real mismatch fails.

</details>

**Q2.** Drill 2 gives `504` after a minute, not `403`. What does that tell you about the layer?

<details>
<summary>Show answer</summary>

A **timeout** means packets are being dropped: the **network** (a security group or route), not identity. An `AccessDenied` means the request arrived and was refused.

</details>

**Q3.** Why does `make down` destroy `80-delivery` before `52-ecs`?

<details>
<summary>Show answer</summary>

The pipeline reads the cluster, service and repository from the ECS stack's state. Terraform orders resources **within** one state only; across stacks the order is yours, and the reverse of apply order is the safe one.

</details>

**Q4.** After teardown, what does the tag search `project = plat` tell you?

<details>
<summary>Show answer</summary>

Because `default_tags` put `project = plat` on every taggable resource, anything the search still returns is **left over**: either deliberately retained (the RDS snapshot, the key pending deletion) or a leak.

</details>

**Q5.** Why is the state bucket removed by a separate script and not by `make down`?

<details>
<summary>Show answer</summary>

It holds **every stack's state, including bootstrap's own**, is protected with `prevent_destroy`, and is versioned, so it can only be removed by moving bootstrap's state elsewhere and emptying all versions. Keeping it a deliberate, separate act protects against destroying your records by accident.

</details>

---

## The End 🎉

You have the whole AWS platform from the first series as code: identity, network, security, data, compute on instances, containers and Kubernetes, events, machine learning, delivery, observability and cost, with tests that need no account, a pipeline that needs no keys, and a script that tells you it works.

If you'd like to keep going, three directions are worth the time: **a second account** (a separate state bucket and roles per environment, with the same stacks), **policies as code** (Service Control Policies and permission boundaries through Organizations), and **more modules** (the VPC and bucket modules are the pattern; ECS and Lambda are the next obvious candidates).

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
