---
title: "SageMaker as Code: Studio, Models and an Endpoint on a Switch"
date: 2026-11-11
tags: [aws, terraform, sagemaker, studio, endpoint, machine-learning, cost, intermediate]
description: Post 13 of the AWS on Terraform series. A Studio domain with user profiles built from a set, one execution role, the security group that talks only to itself, and a real-time endpoint behind a double condition, with create_before_destroy and unique names so models can be replaced without downtime.
---

# Machine Learning Without the Clicks 🤖

`stacks/70-ml` covers the SageMaker half of the AWS series (Posts 19 and 20). It has two parts with opposite cost profiles:

* **Studio** (a domain and user profiles) costs **nothing until someone opens an app**. It is safe to leave on.
* An **endpoint** bills every hour, whether or not anyone calls it. It sits behind a switch and a second condition.

Training itself stays outside Terraform. A training job is an event, not a resource: it runs once and produces a file. Terraform's job is the infrastructure around it and the serving side after it.

---

## The Pieces 🧱

| Piece | Resource(s) | Always on? |
|---|---|---|
| Execution role `plat-sm-role` | `aws_iam_role.sagemaker`, attachment, inline policy | Yes |
| Studio security group and two rules | `aws_security_group.studio`, `..._ingress_rule.studio_self`, `..._egress_rule.studio_all` | **Toggle** `enable_studio` (default on) |
| Domain `plat-studio` | `aws_sagemaker_domain.studio` | Toggle |
| One profile per name | `aws_sagemaker_user_profile.this` | Toggle |
| Model, endpoint configuration, endpoint | `aws_sagemaker_model.churn`, `..._endpoint_configuration.churn`, `..._endpoint.churn` | **Toggle** `enable_endpoint` **and** `model_data_url` set |

![SageMaker stack](content/aws-terraform/images/13-sagemaker.svg)

```hcl
# stacks/70-ml/main.tf
locals {
  vpc_id     = data.terraform_remote_state.network.outputs.vpc_id
  private    = values(data.terraform_remote_state.network.outputs.private_subnet_ids)
  kms_arn    = data.terraform_remote_state.security.outputs.kms_key_arn
  bucket_arn = data.terraform_remote_state.data.outputs.data_bucket_arn

  studio   = var.enable_studio ? 1 : 0
  endpoint = var.enable_endpoint && var.model_data_url != null ? 1 : 0
}
```

`local.endpoint` is the double condition: the flag must be on **and** a model artifact must be provided. Without a model there is nothing to serve, and the endpoint would fail after a ten-minute wait. Putting both in the local makes every `count` below it a plain `local.endpoint`.

---

## Reading the Stack 📖

### The execution role

```hcl
# stacks/70-ml/main.tf
data "aws_iam_policy_document" "sagemaker_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["sagemaker.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sagemaker" {
  name               = "plat-sm-role"
  assume_role_policy = data.aws_iam_policy_document.sagemaker_trust.json
}

resource "aws_iam_role_policy_attachment" "sagemaker_full" {
  role       = aws_iam_role.sagemaker.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"
}
```

One role serves Studio users, training jobs and the hosted model. `AmazonSageMakerFullAccess` covers SageMaker itself and the buckets whose names contain `sagemaker`. Our bucket is not named that way, so the inline policy adds ours:

```hcl
# stacks/70-ml/main.tf
data "aws_iam_policy_document" "sm_data_access" {
  statement {
    sid       = "ListDataBucket"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [local.bucket_arn]
  }

  statement {
    sid       = "ReadWriteMlPrefixes"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${local.bucket_arn}/raw/*", "${local.bucket_arn}/processed/*", "${local.bucket_arn}/models/*"]
  }

  statement {
    sid       = "UseDataKey"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey", "kms:CreateGrant"]
    resources = [local.kms_arn]
  }
}

resource "aws_iam_role_policy" "sm_data_access" {
  name   = "plat-sm-data-access"
  role   = aws_iam_role.sagemaker.id
  policy = data.aws_iam_policy_document.sm_data_access.json
}
```

Notes: reads and writes are limited to **three prefixes** (`raw/`, `processed/`, `models/`), not the whole bucket. And the key statement has an extra action, **`kms:CreateGrant`**: SageMaker passes the key to other services (the training instance's volume, the endpoint) by creating grants. Without it, the job fails with a KMS error although `Decrypt` is allowed.

### Studio networking

```hcl
# stacks/70-ml/main.tf
resource "aws_security_group" "studio" {
  count = local.studio

  name        = "plat-studio-sg"
  description = "SageMaker Studio apps"
  vpc_id      = local.vpc_id

  tags = { Name = "plat-studio-sg" }
}

resource "aws_vpc_security_group_ingress_rule" "studio_self" {
  count = local.studio

  security_group_id            = aws_security_group.studio[0].id
  referenced_security_group_id = aws_security_group.studio[0].id
  ip_protocol                  = "-1"
  description                  = "Members of the group talk to each other"
}

resource "aws_vpc_security_group_egress_rule" "studio_all" {
  count = local.studio

  security_group_id = aws_security_group.studio[0].id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "All outbound (needs the NAT gateway or VPC endpoints to leave the VPC)"
}
```

Studio runs several apps (a JupyterServer, kernel gateways) plus an EFS home directory, and they talk to each other on many ports. The rule allows **any traffic from members of the same group**, a pattern for "these components are one system". Nothing outside the group can reach in. Egress is open because the apps need to call SageMaker and S3 APIs, and that is possible only if the subnets have a NAT or the right endpoints.

### The domain and its users

```hcl
# stacks/70-ml/main.tf
resource "aws_sagemaker_domain" "studio" {
  count = local.studio

  domain_name             = "plat-studio"
  auth_mode               = "IAM"
  vpc_id                  = local.vpc_id
  subnet_ids              = local.private
  app_network_access_type = "VpcOnly"

  default_user_settings {
    execution_role  = aws_iam_role.sagemaker.arn
    security_groups = [aws_security_group.studio[0].id]
  }

  default_space_settings {
    execution_role  = aws_iam_role.sagemaker.arn
    security_groups = [aws_security_group.studio[0].id]
  }

  # Destroy the domain's EFS home directories with it. Without this they are orphaned and keep billing.
  retention_policy {
    home_efs_file_system = "Delete"
  }
}

resource "aws_sagemaker_user_profile" "this" {
  for_each = var.enable_studio ? var.studio_users : toset([])

  domain_id         = aws_sagemaker_domain.studio[0].id
  user_profile_name = each.key
}
```

* **`app_network_access_type = "VpcOnly"`** puts Studio's traffic through your subnets and security group, so your network controls decide what notebooks can reach. The alternative sends it through an AWS-managed network.
* `retention_policy` set to `Delete` removes the home-directory file system when the domain is destroyed. The default `Retain` leaves an EFS file system with no owner that quietly keeps billing.
* Profiles come from **`for_each` over a set** of names. Add a name and a profile appears; remove one and only that profile is destroyed, which is why a set is better than a list here.
* Creating the domain takes about five to ten minutes.

### The endpoint

```hcl
# stacks/70-ml/main.tf
resource "aws_sagemaker_model" "churn" {
  count = local.endpoint

  # aws_sagemaker_model has no name_prefix; a hash of the inputs gives a new name per version.
  name               = "plat-churn-${substr(md5("${var.inference_image}${var.model_data_url}"), 0, 8)}"
  execution_role_arn = aws_iam_role.sagemaker.arn

  primary_container {
    image          = var.inference_image
    model_data_url = var.model_data_url
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_sagemaker_endpoint_configuration" "churn" {
  count = local.endpoint

  name_prefix = "plat-churn-"

  production_variants {
    variant_name           = "AllTraffic"
    model_name             = aws_sagemaker_model.churn[0].name
    initial_instance_count = 1
    instance_type          = var.endpoint_instance_type
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_sagemaker_endpoint" "churn" {
  count = local.endpoint

  name                 = "plat-churn"
  endpoint_config_name = aws_sagemaker_endpoint_configuration.churn[0].name
}
```

Three resources with a chain of references: the model points at an artifact, the configuration at the model, the endpoint at the configuration. The endpoint resource is stable (`name = "plat-churn"`), while the configuration uses **`name_prefix`** for a generated name. The model resource has no `name_prefix` argument, so its name carries a short hash of the image and artifact URL: a new artifact means a new name.

That choice and `create_before_destroy` work together. When `model_data_url` changes, Terraform must replace the model. SageMaker names are immutable and unique, so a replacement can't reuse the old name. With a prefix it creates a new model and a new configuration **first**, points the endpoint at the new configuration (an in-place update that SageMaker performs without downtime), and only then deletes the old ones.

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "A Studio domain bills by the hour." | The domain and profiles are free. Apps (notebooks, kernels) bill while they run, and the EFS home directory bills for what it stores. |
| "I can destroy the domain right away." | It fails while any user has a running **app** (and so does a profile with apps). Delete the apps first. |
| "The domain's EFS is deleted with it." | Only with `home_efs_file_system = "Delete"`. The default retains it. |
| "VpcOnly Studio just works in a private subnet." | It needs a NAT, or endpoints for SageMaker API, runtime, S3 and more. |
| "`AmazonSageMakerFullAccess` can read any bucket." | Only buckets whose name contains `sagemaker`. Ours needs the inline policy. |
| "A model is a running thing." | It's a **definition**: image plus artifact. The endpoint is the running part and the only part that bills. |
| "Changing `model_data_url` updates the endpoint in place." | It replaces model and config; the endpoint is then updated to the new config. Names must be new, hence the hash in the model name and `name_prefix` on the configuration. |
| "An endpoint that fails to start shows an error immediately." | Terraform waits about ten minutes first, then reports the failure reason. |
| "Training should be a Terraform resource." | A training job is one-shot and has no lifecycle to manage. Pipelines or the CLI run it. |
| "A deleted endpoint leaves nothing behind." | The model and configuration remain until deleted separately. Terraform removes them here. |
| "`ml.t2.medium` is available everywhere." | Instance-type availability and **service quotas** vary by account and region. A quota of zero returns `ResourceLimitExceeded`. |
| "Users can't see each other's work." | They share the execution role. Separate profiles are not separate permissions unless you give each its own role. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| `vpc_id`, `private_subnet_ids` | `20-network` |
| `kms_key_arn` | `30-security` |
| `data_bucket_arn` | `40-data` |
| Network path out | NAT in `20-network`, or endpoints |

| You create here | Used by |
|---|---|
| `plat-sm-role` | Studio, training jobs, the hosted model |
| Endpoint `plat-churn` | Alarms and dashboard (Post 14), `verify.sh` |

### Console clicks you no longer make

| In the AWS series you... | Here it is |
|---|---|
| **SageMaker, Domains, Create**: IAM, VPC, subnets, security group | `aws_sagemaker_domain.studio` + `aws_security_group.studio` |
| **Add user** twice | `aws_sagemaker_user_profile.this` (`for_each`) |
| **IAM, Create role** for SageMaker, add the data policy | `aws_iam_role.sagemaker` + attachment + inline policy |
| **Inference, Models, Create model**, endpoint configuration, **Create endpoint** | the three `aws_sagemaker_*` resources |

---

## Lab: Train by Hand, Serve From Code 🛠️

### 1. Studio

```bash
export AWS_PROFILE=plat-admin AWS_REGION=us-east-1
scripts/tf.sh 70-ml plan
```

```
Plan: 9 to add, 0 to change, 0 to destroy.
```

The role with its attachment and policy (3), the security group with two rules (3), the domain (1), two profiles (2).

```bash
scripts/tf.sh 70-ml apply
aws sagemaker list-domains --query 'Domains[].[DomainName,Status]' --output text
aws sagemaker list-user-profiles --query 'UserProfiles[].UserProfileName' --output text
```

```
plat-studio  InService
jim  dave
```

The NAT from Post 09 gives Studio the route it needs. Open Studio for one profile in the console if you want to see it. Opening it starts an app, which bills until you stop it.

### 2. Make training data and train a model

A synthetic data set with the label in the first column (the XGBoost container's CSV convention, no header):

```bash
python3 - <<'PY'
import random
random.seed(7)
rows = []
for _ in range(400):
    tenure, calls, spend = random.randint(1, 60), random.randint(0, 10), random.randint(10, 120)
    churn = 1 if (calls > 5 and tenure < 24) or random.random() < 0.05 else 0
    rows.append(f"{churn},{tenure},{calls},{spend}")
open("/tmp/train.csv", "w").write("\n".join(rows) + "\n")
PY
B=$(terraform -chdir=stacks/40-data output -raw data_bucket)
aws s3 cp /tmp/train.csv s3://$B/processed/train.csv
```

Run one training job with the built-in XGBoost image, as the role from this stack:

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
IMG=683313688378.dkr.ecr.us-east-1.amazonaws.com/sagemaker-xgboost:1.7-1
aws sagemaker create-training-job --training-job-name plat-churn-$(date +%s) \
  --role-arn arn:aws:iam::$ACCOUNT:role/plat-sm-role \
  --algorithm-specification TrainingImage=$IMG,TrainingInputMode=File \
  --hyper-parameters objective=binary:logistic,num_round=20 \
  --input-data-config "[{\"ChannelName\":\"train\",\"ContentType\":\"text/csv\",\"DataSource\":{\"S3DataSource\":{\"S3DataType\":\"S3Prefix\",\"S3Uri\":\"s3://$B/processed/train.csv\",\"S3DataDistributionType\":\"FullyReplicated\"}}}]" \
  --output-data-config S3OutputPath=s3://$B/models/ \
  --resource-config InstanceType=ml.m5.large,InstanceCount=1,VolumeSizeInGB=5 \
  --stopping-condition MaxRuntimeInSeconds=600
```

If you get `ResourceLimitExceeded`, your account has no quota for `ml.m5.large` training instances: request one in **Service Quotas**, or try another type. Poll until it completes (3 to 5 minutes):

```bash
J=$(aws sagemaker list-training-jobs --sort-by CreationTime --max-results 1 --query 'TrainingJobSummaries[0].TrainingJobName' --output text)
aws sagemaker describe-training-job --training-job-name $J --query '[TrainingJobStatus,ModelArtifacts.S3ModelArtifacts]' --output text
```

```
Completed  s3://plat-data-123456789012-us-east-1/models/plat-churn-1789000000/output/model.tar.gz
```

The artifact was written with the bucket's KMS encryption, and the role could do it only because of `kms:GenerateDataKey` and `CreateGrant`. Copy that URL.

### 3. Turn on the endpoint

```bash
URL=s3://$B/models/<job-name>/output/model.tar.gz
scripts/tf.sh 70-ml plan -var enable_endpoint=true -var model_data_url=$URL
```

```
Plan: 3 to add, 0 to change, 0 to destroy.
```

Model, configuration, endpoint. Apply, and wait about five to ten minutes:

```bash
scripts/tf.sh 70-ml apply -var enable_endpoint=true -var model_data_url=$URL
aws sagemaker describe-endpoint --endpoint-name plat-churn --query EndpointStatus --output text
```

```
InService
```

### 4. Call it

```bash
aws sagemaker-runtime invoke-endpoint --endpoint-name plat-churn --content-type text/csv \
  --cli-binary-format raw-in-base64-out --body '12,8,95' /tmp/pred.json >/dev/null && cat /tmp/pred.json; echo
aws sagemaker-runtime invoke-endpoint --endpoint-name plat-churn --content-type text/csv \
  --cli-binary-format raw-in-base64-out --body '50,1,40' /tmp/pred.json >/dev/null && cat /tmp/pred.json; echo
```

```
0.8423
0.0451
```

A short tenure with many calls scores high; a long tenure with few calls scores low. Exact numbers differ per training run.

### 5. Replace the model without downtime

Run the training job again (the same command produces a second artifact), then point the stack at it:

```bash
scripts/tf.sh 70-ml plan -var enable_endpoint=true -var model_data_url=<new-url>
```

```
  # aws_sagemaker_model.churn[0] must be replaced
  # aws_sagemaker_endpoint_configuration.churn[0] must be replaced
  # aws_sagemaker_endpoint.churn[0] will be updated in-place
Plan: 2 to add, 1 to change, 2 to destroy.
```

Read the order in the apply output: new model, new configuration, **update the endpoint**, then destroy the old pair. During the update the endpoint stays `InService` on the old configuration until the new one is ready, and your `invoke-endpoint` loop doesn't fail.

### 6. See what Terraform doesn't see

```bash
D=$(aws sagemaker list-domains --query 'Domains[0].DomainId' --output text)
aws sagemaker create-user-profile --domain-id $D --user-profile-name rogue
scripts/tf.sh 70-ml plan -var enable_endpoint=true -var model_data_url=$URL
```

```
No changes. Your infrastructure matches the configuration.
```

Terraform reports only on what it manages. A profile created by hand is invisible to it, which is a limit of drift detection worth remembering: **drift is a difference in something in state, not a count of what exists**. To bring it under management you would write an `import` block (Post 16); here remove it with `aws sagemaker delete-user-profile --domain-id $D --user-profile-name rogue`.

### 7. Break it: a model that doesn't exist

```bash
scripts/tf.sh 70-ml apply -var enable_endpoint=true -var model_data_url=s3://$B/models/nothing/model.tar.gz
```

The first resources are created; then the endpoint is replaced and, after several minutes of waiting, apply fails:

```
Error: waiting for SageMaker AI Endpoint (plat-churn) update: unexpected state 'Failed', wanted target 'InService'. last error: Unable to locate model artifact...
```

Terraform stops, the old pair is still in place, and the next `plan` shows what it intends to do. Reapply with the correct URL to recover. A failed **update** leaves the endpoint serving the previous configuration, which is the advantage of changing endpoints in place.

### 8. Resources you now have 📦

| Resource | Name | Notes |
|---|---|---|
| Role | `plat-sm-role` | |
| Domain | `plat-studio` | Free until an app runs |
| User profiles | `jim`, `dave` | |
| Security group | `plat-studio-sg` | |
| Model, config | `plat-churn-<generated>` | Only with `enable_endpoint` |
| Endpoint | `plat-churn` | **Hourly cost** |

### Cleanup 🧹

The endpoint first, always:

```bash
scripts/tf.sh 70-ml apply                  # endpoint off: 3 to destroy
```

To remove Studio too, **stop every app**; Terraform cannot delete a domain or profile that has running apps:

```bash
D=$(aws sagemaker list-domains --query 'Domains[0].DomainId' --output text)
aws sagemaker list-apps --domain-id $D --query 'Apps[?Status!=`Deleted`].[AppType,AppName,UserProfileName,SpaceName]' --output text
```

Delete each listed app with `aws sagemaker delete-app --domain-id $D --app-type <type> --app-name <name> --user-profile-name <profile>` (add `--space-name` for apps that belong to a space), wait for them to read `Deleted`, then `scripts/tf.sh 70-ml apply -var enable_studio=false`.

---

## Quick Quiz 🧠

**Q1.** Why does the endpoint need both `enable_endpoint` and `model_data_url`?

<details>
<summary>Show answer</summary>

A switch alone could create an endpoint with no model, which fails after a long wait. The double condition in `local.endpoint` makes "no model" mean "no endpoint" and keeps the plan honest.

</details>

**Q2.** Training succeeds with `Decrypt` allowed but fails on the encrypted bucket. What is likely missing?

<details>
<summary>Show answer</summary>

`kms:CreateGrant` (and possibly `GenerateDataKey`). SageMaker grants the key to the training instance's volume and to other components; without the permission to create grants the job fails with a KMS error.

</details>

**Q3.** Why do the model and configuration get generated names (a hash and `name_prefix`) and `create_before_destroy`?

<details>
<summary>Show answer</summary>

SageMaker resource names are unique and immutable. A replacement therefore needs a **new** name, which a prefix or an input hash generates, and it must exist **before** the old one is removed so the endpoint always has something to point at.

</details>

**Q4.** `terraform apply` to destroy Studio fails. What do you check first?

<details>
<summary>Show answer</summary>

Running or stopped-but-not-deleted **apps** in the domain. A domain or profile can't be deleted while it has apps; list them with `list-apps` and delete them first.

</details>

**Q5.** You created a user profile by hand and the plan says "No changes". Is that a bug?

<details>
<summary>Show answer</summary>

No. Terraform compares the resources in its **state and configuration**; the extra profile is in neither. Detecting unmanaged additions needs a different tool, or an `import` followed by a decision about whether to manage it.

</details>

---

## What's Next? 🚀

Everything now exists, and nothing watches it. Next: a dashboard, alarms with the right dimensions, and the log metric filters that turn text into numbers.

👉 [Post 14: Observability as Code: Dashboards, Alarms and Log Metrics](content/aws-terraform/14-observability-as-code.md)

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
