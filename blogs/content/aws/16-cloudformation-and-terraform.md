---
title: "CloudFormation and Terraform"
date: 2026-11-08
tags: [aws, cloudformation, terraform, iac, change-sets, drift, state, intermediate]
description: Post 16 of the AWS series. The same secure S3 bucket defined in CloudFormation and in Terraform, with change sets, replacement, drift, state and locking, and a lab that deploys both and shows where each tool surprises you.
---

# Infrastructure You Can Review, Repeat and Delete 📐

Fifteen posts of console clicking taught you what every setting *means*. Clicking has two weaknesses: nobody can review it in a pull request, and nobody can repeat it exactly. **Infrastructure as Code (IaC)** fixes both by describing resources in files.

We will define one small, reusable thing in **both** major tools: a **private, versioned, KMS-encrypted S3 bucket with a TLS-only policy**. It is the project bucket Dave will request through Service Catalog in Post 17, so what you write here is reused.

![One definition, two engines](content/aws/images/16-iac.svg)

---

## Two Tools, Two Models 🧰

| | **CloudFormation** | **Terraform** |
|---|---|---|
| Owner | AWS | HashiCorp (open source core, plus the OpenTofu fork) |
| Format | YAML or JSON **templates** | **HCL** configuration files |
| Unit | A **stack** | A **configuration** plus its **state** |
| Where "what exists" is remembered | **Inside AWS**, by the stack | In a **state file** that you must store and protect |
| Preview | **Change sets** | `terraform plan` |
| Scope | AWS only | Many providers (AWS, GitHub, Kubernetes, ...) |
| Rollback | **Automatic** when a stack operation fails | None: a failed apply leaves a partial result you fix and re-apply |
| New AWS features | Sometimes land later | Provider releases, usually fast but not instant |

Both are **declarative**: you describe the end state, and the tool works out the steps.

### Terraform state

State maps your configuration to real resource IDs. Lose it and Terraform forgets that it created anything. Put it in a **remote backend**. For S3, the modern setting is **`use_lockfile = true`**, which holds a lock as a small object next to the state file. (The older approach used a separate DynamoDB table for locking and is deprecated.)

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "Updating a CloudFormation stack just changes the resource." | Some property changes need **replacement**: a new resource is created and the old one deleted. Changing a **bucket name** replaces the bucket. Always read the change set's **Replacement** column. |
| "A failed stack update leaves a mess." | Failed **updates** roll back to the last good state. But a failed **create** ends in `ROLLBACK_COMPLETE`, which you **cannot update**: delete the stack and start again. |
| "Deleting a stack deletes my data." | Only if the resource's **DeletionPolicy** is `Delete` (the default). A non-empty S3 bucket also **blocks** the delete. Use `Retain` for anything you can't recreate. |
| "If someone changes a resource in the console, CloudFormation updates itself." | It doesn't know. That is **drift**. You must run **drift detection**, and the next update may overwrite or ignore the manual change. |
| "A Terraform `plan` that shows no changes means nothing is wrong." | It only compares your files, the state, and what the provider reads. A resource Terraform doesn't manage is invisible to it. |
| "State is just a cache." | It is the **source of truth** for what Terraform manages. Editing or deleting it by hand is how resources get orphaned or duplicated. |
| "State is safe to commit to Git." | State holds **plaintext values**, including secrets and generated passwords. Never commit it. Store it encrypted, with restricted access. |
| "Two people can run `apply` at once." | Without **locking**, they corrupt state. Remote state with locking makes the second run fail fast. |
| "Manage the same resource in both tools." | Two tools fighting over one resource guarantee surprises. **One owner per resource.** |
| "The state bucket can be created by the same Terraform." | A chicken-and-egg problem: the backend must exist **before** `init`. Create it once by hand (or a tiny separate stack). |
| "`terraform apply -auto-approve` is fine in a pipeline." | Only after a **reviewed plan** has been saved and the same plan is applied. Auto-approving a fresh plan skips the review. |
| "Parameters are secret." | CloudFormation parameters show in the console and in the API unless you use `NoEcho` (which hides the value from describe calls only). Prefer **dynamic references** to Secrets Manager or SSM. |
| "I can use `!Ref` for any resource attribute." | `!Ref` returns one default value (often the name or ID). Use **`!GetAtt`** for ARNs and other attributes, and **`!Sub`** to assemble strings. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| The secure bucket settings: BPA, SSE-KMS with Bucket Key, versioning, TLS-deny policy | Post 06 |
| The KMS key `alias/plat-data` | Post 05 |
| The `plat-platform` repository and `.gitignore` for state files | Post 15 |
| CloudShell with the PlatformAdmin identity | Posts 01, 03 |

| You create here | Used by |
|---|---|
| **`infra/cloudformation/bucket.yaml`** | The Service Catalog product (17) and a pipeline stage (18) |
| **`infra/terraform/bucket/`** | The Terraform way to repeat the same thing |
| State bucket `plat-tfstate-<acct>-us-east-1` | All future Terraform |

---

## Lab: One Bucket, Twice 🛠️

Work as Jim, in **N. Virginia**, in **CloudShell**. Replace `123456789012` with your account ID.

### 1. Write the CloudFormation template

Create the folder in your local clone of `plat-platform` (and, for the lab, paste the same file into CloudShell):

**`infra/cloudformation/bucket.yaml`**

```yaml
AWSTemplateFormatVersion: "2010-09-09"
Description: Private, versioned, KMS-encrypted S3 bucket for a platform project

Parameters:
  ProjectName:
    Type: String
    Description: Lowercase project name, used in the bucket name
    AllowedPattern: "^[a-z0-9-]{3,30}$"
    ConstraintDescription: 3 to 30 characters, lowercase letters, digits and hyphens
  Environment:
    Type: String
    Default: dev
    AllowedValues: [dev, prod]
  KmsKeyArn:
    Type: String
    Description: ARN of the KMS key used for default encryption
    AllowedPattern: "^arn:aws:kms:[a-z0-9-]+:[0-9]{12}:key/[0-9a-f-]{36}$"

Resources:
  Bucket:
    Type: AWS::S3::Bucket
    DeletionPolicy: Delete
    UpdateReplacePolicy: Retain
    Properties:
      BucketName: !Sub "${ProjectName}-${Environment}-${AWS::AccountId}-${AWS::Region}"
      VersioningConfiguration:
        Status: Enabled
      BucketEncryption:
        ServerSideEncryptionConfiguration:
          - BucketKeyEnabled: true
            ServerSideEncryptionByDefault:
              SSEAlgorithm: aws:kms
              KMSMasterKeyID: !Ref KmsKeyArn
      PublicAccessBlockConfiguration:
        BlockPublicAcls: true
        BlockPublicPolicy: true
        IgnorePublicAcls: true
        RestrictPublicBuckets: true
      Tags:
        - Key: project
          Value: !Ref ProjectName
        - Key: environment
          Value: !Ref Environment

  BucketPolicy:
    Type: AWS::S3::BucketPolicy
    Properties:
      Bucket: !Ref Bucket
      PolicyDocument:
        Version: "2012-10-17"
        Statement:
          - Sid: DenyInsecureTransport
            Effect: Deny
            Principal: "*"
            Action: "s3:*"
            Resource:
              - !GetAtt Bucket.Arn
              - !Sub "${Bucket.Arn}/*"
            Condition:
              Bool:
                aws:SecureTransport: "false"

Outputs:
  BucketName:
    Description: Name of the bucket
    Value: !Ref Bucket
  BucketArn:
    Description: ARN of the bucket
    Value: !GetAtt Bucket.Arn
```

`UpdateReplacePolicy: Retain` means that if a change forces replacement, the **old bucket is kept**, not deleted with its data. Get your key ARN:

```bash
KEY_ARN=$(aws kms describe-key --key-id alias/plat-data --query KeyMetadata.Arn --output text)
echo $KEY_ARN
aws cloudformation validate-template --template-body file://bucket.yaml --query Parameters[].ParameterKey
```

```text
arn:aws:kms:us-east-1:123456789012:key/2c8e9f10-aaaa-bbbb-cccc-0123456789ab
[
    "ProjectName",
    "Environment",
    "KmsKeyArn"
]
```

`validate-template` only checks syntax. It will not catch a wrong property value.

### 2. Create the stack

**CloudFormation, Create stack, With new resources**:

1. **Upload a template file**: `bucket.yaml`.
2. Stack name **`plat-bucket-demo`**. Parameters: `ProjectName = plat-demo`, `Environment = dev`, `KmsKeyArn =` your key ARN.
3. Tags: `project = plat`. Permissions: leave as your current role. Failure options: **Roll back all stack resources**. Submit.

Watch the **Events** tab:

```text
CREATE_IN_PROGRESS   Bucket
CREATE_COMPLETE      Bucket
CREATE_IN_PROGRESS   BucketPolicy
CREATE_COMPLETE      BucketPolicy
CREATE_COMPLETE      plat-bucket-demo
```

CloudFormation worked out the order itself: the policy needs the bucket, because it references `Bucket`. Open **Outputs** and **Resources**, then verify in S3 that the bucket `plat-demo-dev-<acct>-us-east-1` has versioning on, default encryption with your key, and all four Block Public Access settings on.

### 3. A safe update, and a dangerous one

**Change sets** show the effect before anything happens.

**Update a tag.** Edit `bucket.yaml` and add a third tag (`owner` = `jim`). Instead of updating directly, choose **Stack actions, Create change set for current stack**, upload the changed file, keep the parameters, and name it `add-owner-tag`. Open the change set:

```text
Action   Logical ID   Resource type       Replacement
Modify   Bucket       AWS::S3::Bucket     False
```

**Replacement False.** Execute it.

**Change the environment.** Create another change set from the same template, but set `Environment = prod`, name `go-prod`:

```text
Action   Logical ID     Resource type          Replacement
Modify   Bucket         AWS::S3::Bucket        True
Modify   BucketPolicy   AWS::S3::BucketPolicy  True
```

**Replacement True**: the bucket name contains the environment, so CloudFormation would create a *new* bucket and (with `UpdateReplacePolicy: Retain`) leave the old one behind. **Do not execute it.** Delete the change set. This is the habit to build: read the Replacement column every time.

### 4. See drift

In the S3 console open `plat-demo-dev-...`, **Properties, Bucket Versioning, Edit, Suspend**. Back in CloudFormation: **Stack actions, Detect drift**, then **View drift results**:

```text
Bucket   AWS::S3::Bucket   MODIFIED
  Property: /VersioningConfiguration/Status   Expected: Enabled   Actual: Suspended
```

CloudFormation did not notice by itself. Fix it by running an **update stack** with the unchanged template (or re-enable versioning in the console). Note that CloudFormation updates only what **it** thinks changed, so a manual change is not always reverted; resolve drift deliberately.

### 5. A failed create, and what it leaves behind

Create a second stack `plat-bucket-bad` with the same template, `ProjectName = plat-bad`, and a **well-formed key ARN of a key that doesn't exist** (change a few characters of the UUID in your key ARN). The create fails and the stack ends in **`ROLLBACK_COMPLETE`**. Read the **Events** tab for the reason (the exact message varies). Try **Update stack**: the option is unavailable. **Delete** it. A failed create can only be deleted and recreated.

### 6. Terraform: bootstrap the state bucket

Terraform needs somewhere to keep state before it can create anything. Create it by hand once. **S3, Create bucket**: `plat-tfstate-123456789012-us-east-1`, Block all public access on, **Bucket Versioning enabled**, default encryption **SSE-S3**. Tag `project = plat`.

> This is the one resource Terraform cannot create for itself, so we create it outside Terraform.

### 7. Install Terraform in CloudShell

CloudShell does not ship with Terraform. Download a recent 1.x release from HashiCorp's release site (the backend setting we use needs 1.10 or newer; check the releases page for the latest version):

```bash
uname -m            # x86_64 expected
TF_VER=1.13.0     # or newer: check the releases page
mkdir -p ~/bin && cd ~/bin
curl -sSLO https://releases.hashicorp.com/terraform/${TF_VER}/terraform_${TF_VER}_linux_amd64.zip
unzip -o terraform_${TF_VER}_linux_amd64.zip && rm terraform_${TF_VER}_linux_amd64.zip
export PATH=$HOME/bin:$PATH
terraform version
```

If `uname -m` shows `aarch64`, use the `linux_arm64` zip. Anything in your CloudShell home directory persists between sessions (up to its quota).

### 8. Write the Terraform

```bash
mkdir -p ~/bucket && cd ~/bucket
```

**`main.tf`**

```hcl
terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0, < 7.0"
    }
  }

  backend "s3" {
    bucket       = "plat-tfstate-123456789012-us-east-1"
    key          = "bucket-demo/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = "us-east-1"

  default_tags {
    tags = {
      project = "plat"
    }
  }
}

variable "project_name" {
  type    = string
  default = "plat-tf"
}

variable "environment" {
  type    = string
  default = "dev"

  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "environment must be dev or prod."
  }
}

variable "kms_key_arn" {
  type = string
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  bucket_name = "${var.project_name}-${var.environment}-${data.aws_caller_identity.current.account_id}-${data.aws_region.current.name}"
}

resource "aws_s3_bucket" "this" {
  bucket = local.bucket_name
}

resource "aws_s3_bucket_versioning" "this" {
  bucket = aws_s3_bucket.this.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    bucket_key_enabled = true

    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  bucket                  = aws_s3_bucket.this.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_iam_policy_document" "tls_only" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.this.arn, "${aws_s3_bucket.this.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "this" {
  bucket = aws_s3_bucket.this.id
  policy = data.aws_iam_policy_document.tls_only.json

  depends_on = [aws_s3_bucket_public_access_block.this]
}

output "bucket_name" {
  value = aws_s3_bucket.this.bucket
}
```

Replace the state bucket name. (Newer AWS provider versions may print a deprecation warning for `data.aws_region.current.name`; it still works.) Pass the key ARN with an environment variable so you don't hard-code it:

```bash
export TF_VAR_kms_key_arn=$(aws kms describe-key --key-id alias/plat-data --query KeyMetadata.Arn --output text)
terraform init
terraform fmt
terraform validate
```

```text
Terraform has been successfully initialized!
Success! The configuration is valid.
```

### 9. Plan, apply, inspect

```bash
terraform plan -out=tfplan
```

```text
Plan: 5 to add, 0 to change, 0 to destroy.
```

Read the plan before applying: bucket, versioning, encryption, public access block, policy. Apply **exactly that plan**:

```bash
terraform apply tfplan
terraform state list
aws s3 ls s3://plat-tfstate-123456789012-us-east-1/ --recursive
```

```text
aws_s3_bucket.this
aws_s3_bucket_policy.this
aws_s3_bucket_public_access_block.this
aws_s3_bucket_server_side_encryption_configuration.this
aws_s3_bucket_versioning.this
...
2026-11-08 12:01:14       4172 bucket-demo/terraform.tfstate
```

That `terraform.tfstate` object is the memory of what Terraform created. Peek at it, and notice it holds real attribute values in plain text:

```bash
terraform state show aws_s3_bucket.this | head -8
```

### 10. Drift and locking, the Terraform way

Suspend versioning on `plat-tf-dev-...` in the S3 console, then:

```bash
terraform plan
```

```text
  # aws_s3_bucket_versioning.this will be updated in-place
  ~ versioning_configuration {
      ~ status = "Suspended" -> "Enabled"
```

Terraform refreshed from AWS, compared with your files, and proposes to fix it. Apply it (`terraform apply`, type `yes`). While an apply is running, a lock object `bucket-demo/terraform.tfstate.tflock` exists next to the state file. A second `terraform apply` started from another CloudShell tab fails with *Error acquiring the state lock*, which is the protection working.

### 11. Compare the two replacement behaviors

Run `terraform plan -var environment=prod`:

```text
  # aws_s3_bucket.this must be replaced
-/+ resource "aws_s3_bucket" "this" { ... bucket = "plat-tf-dev-..." -> "plat-tf-prod-..." # forces replacement
Plan: 5 to add, 0 to change, 5 to destroy.
```

Same lesson as the change set, with different notation (`-/+` and `# forces replacement`). **Do not apply it.**

### 12. Commit the files

```bash
cd plat-platform
mkdir -p infra/cloudformation infra/terraform/bucket
# copy bucket.yaml and main.tf into those folders, then:
git switch -c iac/bucket
git add infra
git commit -m "Add secure project bucket in CloudFormation and Terraform"
git push -u origin iac/bucket
# open a pull request and merge
```

`.gitignore` already excludes `.terraform/`, `*.tfstate` and `*.tfstate.*`. Check with `git status` that no state or provider binaries were staged. Commit **`.terraform.lock.hcl`** (it pins provider versions). Your webhook from Post 15 logs the push.

### 13. Resources you now have 📦

| Resource | Name | Managed by |
|---|---|---|
| Stack and bucket | `plat-bucket-demo` / `plat-demo-dev-<acct>-us-east-1` | CloudFormation |
| Bucket and policy | `plat-tf-dev-<acct>-us-east-1` | Terraform |
| State bucket | `plat-tfstate-<acct>-us-east-1` | By hand |
| Files in Git | `infra/cloudformation/bucket.yaml`, `infra/terraform/bucket/main.tf` | |

### Cleanup 🧹

Delete both demo buckets, **each through the tool that created it**:

```bash
terraform destroy         # type yes
```

CloudFormation: **Delete stack** `plat-bucket-demo` (the bucket is empty, so it succeeds). Keep `plat-tfstate-...` (empty buckets cost nothing). Keep the template file: Post 17 needs it.

---

## Quick Quiz 🧠

**Q1.** A change set shows `Replacement: True` for your production data bucket. What do you do?

<details>
<summary>Show answer</summary>

**Do not execute it.** Find the property that forces replacement (here a name that includes a changed parameter), change the design so the name stays stable, or plan a deliberate migration. Use `DeletionPolicy` and `UpdateReplacePolicy: Retain` so a mistake doesn't delete data.

</details>

**Q2.** Your first stack creation fails. You fix the template and click Update, but the option is greyed out. Why?

<details>
<summary>Show answer</summary>

The failed create left the stack in **`ROLLBACK_COMPLETE`**, which cannot be updated. Delete the stack and create it again.

</details>

**Q3.** A colleague "fixes" a Terraform-managed bucket setting in the console. What does the next `terraform plan` show and why?

<details>
<summary>Show answer</summary>

A proposed **in-place update** that reverts the setting. Terraform **refreshes** real values from AWS, compares them with your configuration, and shows the difference.

</details>

**Q4.** Why must the Terraform state bucket be created outside the configuration that uses it?

<details>
<summary>Show answer</summary>

`terraform init` configures the backend **before** anything is created, so the bucket has to exist already. Bootstrap it by hand or with a separate, small configuration.

</details>

**Q5.** Give two reasons never to commit `terraform.tfstate`.

<details>
<summary>Show answer</summary>

It holds **plaintext resource attributes, including secrets**, and committing it creates a **second copy that drifts** from the remote state, which can be applied by mistake.

</details>

---

## What's Next? 🚀

Writing a template is the platform engineer's job. But Dave, the data scientist, should be able to ask for "a project bucket" without learning CloudFormation, and without permission to create anything else. That is a governance problem, and AWS has a service built for it.

👉 **[Post 17: Service Catalog](content/aws/17-service-catalog.md)**: publish `bucket.yaml` as a product, grant Dave access to the portfolio only, and watch him launch it with a launch role he could never assume himself.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
