---
title: "How Terraform Works, and the Bootstrap"
date: 2026-11-08
tags: [aws, terraform, iac, state, s3-backend, oidc, github-actions, intermediate]
description: Post 1 of the AWS on Terraform series. What a plan really compares, why state is the most sensitive file you own, how S3 native locking works, and a lab that builds the state bucket and GitHub OIDC roles that every other stack depends on.
---

# From Console Clicks to Code 🧱

In the AWS series we built the Platform Lab by hand, one console click at a time. That was the right way to learn what each service does. It is the wrong way to *keep* it: nobody can review a click, nobody can repeat it exactly, and nobody remembers which of the forty clicks mattered.

This series rebuilds the **same platform** (same names, same settings, same wiring) as Terraform code. Every post maps the clicks you already know onto resources, then has you plan, apply, verify with the CLI, break something on purpose, and watch Terraform notice.

The code lives in one repository, [`plat-platform-terraform`](https://github.com/ashwinberyl/plat-platform-terraform). The posts quote it directly, so what you read is what you run.

> **Ground rule:** this series assumes you have read the AWS series, or at least know what the services do. Here we spend the words on *how Terraform expresses them*.

---

## The Pieces 🧩

| Piece | What it is |
|---|---|
| **Configuration** | `.tf` files that describe the infrastructure you want |
| **Provider** | A plugin that talks to one API. `hashicorp/aws` turns resources into AWS API calls |
| **Resource** | One thing Terraform manages, for example `aws_s3_bucket.state`. The address is `type.name` |
| **Data source** | A read-only lookup, for example "who am I?" (`aws_caller_identity`) |
| **State** | Terraform's record of which real object each resource address maps to, with all its attributes |
| **Backend** | Where state is stored and how it is locked. We use S3 |
| **Plan** | The difference between configuration and reality, as a list of actions |
| **Apply** | Carrying out a plan, then recording the result in state |

### What a plan compares

![The three inputs of a plan](content/aws-terraform/images/01-plan-inputs.svg)

Terraform never "looks at your code and fixes the account". A plan has **three inputs**:

1. **Configuration**: what you want.
2. **State**: what Terraform believes it created last time.
3. **Real infrastructure**: what the provider reads back from AWS right now (the *refresh*).

It reconciles the three into actions: create what is in configuration but not in state, change what differs, destroy what is in state but no longer in configuration. This is why a change you make in the console shows up in the next plan as **drift**: reality no longer matches what state recorded.

> **Key insight:** State is how Terraform knows that `aws_s3_bucket.state` *is* the bucket `plat-tfstate-123456789012-us-east-1`. Lose the state and Terraform has no memory: it will try to create everything again and fail on the name clashes.

### The three commands you run most

| Command | What it does | Changes AWS? |
|---|---|---|
| `terraform init` | Downloads providers and modules, configures the backend | No |
| `terraform plan` | Refreshes, compares, prints the actions | No |
| `terraform apply` | Shows the plan, asks for `yes`, executes, updates state | **Yes** |

`terraform validate` checks syntax and internal consistency without calling AWS. `terraform fmt` rewrites files into the canonical layout. Both are fast enough to run on every pull request, which is exactly what our CI workflow does.

---

## State: The File You Must Protect 🔐

State is JSON. For every resource it stores **every attribute the provider returned**, including values you marked as sensitive, and including generated passwords. Terraform hides them in plan output, but they sit in the state file in plain text.

So the state bucket must be:

| Requirement | How we meet it |
|---|---|
| **Not public** | All four public-access-block settings on, bucket-owner-enforced ownership |
| **Encrypted at rest** | SSE-S3 (`AES256`). We cannot use our KMS key here, because the key itself is created by a stack that stores its state in this bucket |
| **Encrypted in transit** | A bucket policy that denies any request where `aws:SecureTransport` is `false` |
| **Recoverable** | **Versioning**, so a bad write can be rolled back to the previous version of the file |
| **Protected from deletion** | `prevent_destroy` in the resource, so a stray `destroy` fails |
| **Locked while in use** | S3 native locking, described next |

### Locking without DynamoDB

Older guides pair the S3 backend with a DynamoDB table for locking. Since **Terraform 1.10** the S3 backend can lock by itself: set `use_lockfile = true` and Terraform writes a second object, `<key>.tflock`, using an S3 **conditional write** (`If-None-Match`). If the object already exists the write is rejected and the second run stops with *Error acquiring the state lock*. When the first run finishes it deletes the lock object.

That means two extra permissions matter: the identity running Terraform needs `s3:PutObject` and `s3:DeleteObject` on the state bucket, **even for a read-only `plan`**, because planning takes the lock too. Our plan role has exactly that and nothing else on the bucket.

---

## The Chicken-and-Egg Problem 🐔

Every stack stores its state in S3. But the S3 bucket has to be created by *something*.

The answer is a tiny stack, **`bootstrap/`**, that is applied **once** with **local state**, and then moves its own state into the bucket it just created. After that, even bootstrap is stored remotely like everything else.

```
1. terraform apply          state is a local file, bucket gets created
2. add backend "s3" {}      tell Terraform the bucket exists now
3. init -migrate-state      copy the local state into the bucket
```

Bootstrap also creates the **GitHub OIDC trust** used by CI. Instead of storing AWS keys in GitHub, a workflow presents a short-lived token signed by GitHub, and AWS exchanges it for temporary role credentials. The role's trust policy checks the token's `sub` claim, which says *which repository and which ref* is asking:

| Role | Trust condition (`sub`) | Permissions |
|---|---|---|
| `plat-tf-plan` | `repo:ashwinberyl/plat-platform-terraform:pull_request` or `...:ref:refs/heads/main` (the nightly drift check) | `ReadOnlyAccess` plus the state-bucket rights above |
| `plat-tf-apply` | `repo:ashwinberyl/plat-platform-terraform:environment:production` | `AdministratorAccess` (narrowed in Post 18) |

A pull request from anyone can only ever get the read-only role. Only code that has been merged to `main` can get the powerful one.

---

## The Repository Map 🗺️

| Directory | Contents | Posts |
|---|---|---|
| `bootstrap/` | State bucket, OIDC provider, CI roles | **01** |
| `modules/` | `s3-bucket`, `vpc`, and more as we go | 04, 06 |
| `stacks/10-identity` | Identity Center, `plat-demo-reader` | 03 |
| `stacks/20-network` | VPC, subnets, NAT, endpoints | 04 |
| `stacks/30-security` | KMS, secrets, security groups | 05 |
| `stacks/40-data` | S3 data lake, DynamoDB, RDS, EFS | 07 |
| `stacks/50` to `90` | Compute, events, ML, delivery, observability | later posts |
| `scripts/tf.sh` | Runs Terraform in a stack with the right backend settings | all |

**Why many small stacks instead of one big one?** Each stack has its own state file. A mistake or a slow plan in one cannot touch the others, and `destroy` of the compute stack cannot delete your database. The cost is that stacks must pass values to each other, which we do with outputs and `terraform_remote_state` (Post 05).

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "Terraform reads my `.tf` files and makes AWS match." | It compares config to **state**, and refreshes state from AWS. A resource that exists in AWS but **not in state** is invisible to it. |
| "State is just a cache; I can delete it." | Deleting it makes Terraform forget what it manages. The next apply tries to create everything again and hits `already exists` errors. Recover with `import`, not by hoping. |
| "Sensitive variables are not stored in state." | `sensitive = true` hides the value in **output**. The value is still in the state file in plain text. Treat state like a credential. |
| "I need a DynamoDB table for S3 locking." | Not since 1.10: `use_lockfile = true`. Old guides are out of date, and `dynamodb_table` is deprecated. |
| "`plan` is read-only so it needs no write access." | With lockfile locking it writes (and deletes) the `.tflock` object. A role that cannot write there fails at plan. |
| "I can put the bucket name in a variable inside the `backend` block." | **Backend blocks cannot use variables or locals.** They are read before anything is evaluated. That is why ours is empty (`backend "s3" {}`) and `scripts/tf.sh` supplies the values with `-backend-config`. |
| "`terraform apply` saves a plan, so what I review is what runs." | Only if you run `plan -out=tfplan` and then `apply tfplan`. A bare `apply` re-plans first, and the world may have changed since you looked. CI applies only after a reviewed plan and an approval (Post 18). |
| "One OIDC provider per repo." | One per **URL per account**. `token.actions.githubusercontent.com` exists once, and every repository shares it. If another project already created it, creating it again fails, which is why `create_oidc_provider` is a variable. |
| "The `aud` check is enough to secure the role." | Without a `sub` condition **any GitHub repository** can assume the role. Always pin `sub`. |
| "`prevent_destroy` makes the bucket undeletable." | It only blocks plans that would destroy it. Remove the line and the bucket can go. It protects against accidents, not against intent. |
| "Providers are pinned by the version in `required_providers`." | That sets a **range** (`~> 6.0` means `>= 6.0, < 7.0`). The exact version is pinned in `.terraform.lock.hcl`, which you should commit. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| An AWS account and the `plat-admin` SSO profile | AWS series, Posts 01 and 03 |
| The naming convention and the `project = plat` tag | AWS series, Post 01 (now applied automatically with `default_tags`) |
| What an S3 bucket's protections are (public access block, versioning, policy) | AWS series, Post 06 |

| You create here | Used by |
|---|---|
| Bucket `plat-tfstate-<account>-<region>` | **Every stack** in this series, as its backend |
| GitHub OIDC provider and roles `plat-tf-plan`, `plat-tf-apply` | The pull-request workflow (Post 18) and the capstone (Post 19) |
| `scripts/tf.sh` | Every lab from here on |

### Console clicks you no longer make

| In the AWS series you... | Here it is |
|---|---|
| Created a bucket, ticked *Block all public access* (Post 06, steps 1 to 2) | `aws_s3_bucket` + `aws_s3_bucket_public_access_block` + `aws_s3_bucket_ownership_controls` |
| Turned on *Bucket Versioning* | `aws_s3_bucket_versioning` |
| Chose a default encryption type | `aws_s3_bucket_server_side_encryption_configuration` |
| Pasted a bucket policy JSON | `data "aws_iam_policy_document"` + `aws_s3_bucket_policy` |
| Created an IAM role with a trust policy (Post 02) | `aws_iam_role` with `assume_role_policy` |

---

## Lab: Build the Bootstrap 🛠️

> **Before you start.** Use a fresh account or **delete the hand-built lab first**. Later stacks create resources with the same names the AWS series used (IAM role `plat-demo-reader`, KMS alias `alias/plat-data`, bucket `plat-data-<account>-<region>`, table `plat-jobs`, security groups, secret `plat/demo/api-key`). The bootstrap itself only creates new names, so it is safe either way.

### 1. Check your tools

```bash
terraform version
aws --version
export AWS_PROFILE=plat-admin AWS_REGION=us-east-1
aws sso login --profile plat-admin
aws sts get-caller-identity --query Arn --output text
```

You need **Terraform 1.10 or newer**. The identity should be an `AWSReservedSSO_PlatformAdmin_...` assumed role. If you are on the older `plat-bootstrap` user, that works too for this one post.

Clone the repository:

```bash
git clone https://github.com/ashwinberyl/plat-platform-terraform.git
cd plat-platform-terraform
```

### 2. Read the bootstrap stack

Open `bootstrap/`. It is four files: `versions.tf` (Terraform and provider versions), `variables.tf`, `main.tf` and `outputs.tf`. First the provider, with the tags every resource inherits:

```hcl
# bootstrap/main.tf
provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project    = "plat"
      managed_by = "terraform"
      stack      = "bootstrap"
    }
  }
}
```

`default_tags` is how the `project = plat` rule from the AWS series now applies to **every** resource without anyone remembering. The bucket itself, and the guard on it:

```hcl
# bootstrap/main.tf
resource "aws_s3_bucket" "state" {
  bucket = local.bucket_name

  lifecycle {
    prevent_destroy = true
  }
}
```

The OIDC pieces. Note that the provider is optional (`count`) and has a data-source fallback for accounts that already have one:

```hcl
# bootstrap/main.tf
resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_oidc_provider && var.enable_ci_roles ? 1 : 0

  url            = local.github_oidc_url
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_openid_connect_provider" "github" {
  count = !var.create_oidc_provider && var.enable_ci_roles ? 1 : 0

  url = local.github_oidc_url
}
```

The apply role's trust policy, where the `sub` condition does the real work:

```hcl
# bootstrap/main.tf
data "aws_iam_policy_document" "apply_trust" {
  count = var.enable_ci_roles ? 1 : 0

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${local.github_sub_prefix}:environment:production"]
    }
  }
}
```

### 3. Initialise, plan, apply

```bash
terraform -chdir=bootstrap init
terraform -chdir=bootstrap plan
```

`init` downloads the AWS provider and writes `.terraform.lock.hcl`. The plan ends with:

```
Plan: 13 to add, 0 to change, 0 to destroy.

Changes to Outputs:
  + account_id     = "123456789012"
  + apply_role_arn = (known after apply)
  + plan_role_arn  = (known after apply)
  + state_bucket   = "plat-tfstate-123456789012-us-east-1"
```

Thirteen: seven for the bucket and its settings, one OIDC provider, five for the two roles and their policies. If your account already has the GitHub OIDC provider, apply fails on it; rerun the plan with `-var create_oidc_provider=false` and you will see `12 to add`.

```bash
terraform -chdir=bootstrap apply
```

Read the plan, type `yes`.

### 4. Verify with the CLI

Terraform says it succeeded. Check AWS agrees:

```bash
BUCKET=$(terraform -chdir=bootstrap output -raw state_bucket)
aws s3api get-bucket-versioning --bucket $BUCKET
aws s3api get-public-access-block --bucket $BUCKET --query PublicAccessBlockConfiguration
aws s3api get-bucket-encryption --bucket $BUCKET \
  --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault'
aws iam list-open-id-connect-providers
aws iam get-role --role-name plat-tf-apply --query Role.AssumeRolePolicyDocument.Statement[0].Condition
```

You should see `"Status": "Enabled"`, all four public-access settings `true`, `"SSEAlgorithm": "AES256"`, the GitHub provider ARN, and a `StringEquals` condition whose `sub` is `repo:ashwinberyl/plat-platform-terraform:environment:production`.

### 5. Move bootstrap's state into the bucket

Right now the state is a local file, `bootstrap/terraform.tfstate`. Move it:

```bash
cp bootstrap/backend.tf.example bootstrap/backend.tf
scripts/tf.sh bootstrap migrate
```

`scripts/tf.sh` computes the bucket name from your account id and passes it as `-backend-config`:

```bash
# scripts/tf.sh
#!/usr/bin/env bash
# Usage: scripts/tf.sh <stack> <terraform-command> [args...]
#   scripts/tf.sh 20-network plan
#   scripts/tf.sh 20-network apply -var enable_nat=true
#   scripts/tf.sh bootstrap migrate        # one-time: move local state into S3
# <stack> is "bootstrap", a directory name under stacks/, or labs/<name> for a lab that uses remote state.
set -euo pipefail

STACK="${1:?usage: tf.sh <stack> <command> [args...]}"
CMD="${2:?usage: tf.sh <stack> <command> [args...]}"
shift 2

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="${TF_STATE_BUCKET:-plat-tfstate-${ACCOUNT}-${REGION}}"

if [ "$STACK" = "bootstrap" ]; then
  DIR="$ROOT/bootstrap"
elif [[ "$STACK" == labs/* ]]; then
  DIR="$ROOT/$STACK"
else
  DIR="$ROOT/stacks/$STACK"
fi
[ -d "$DIR" ] || { echo "no such stack: $STACK" >&2; exit 1; }

BACKEND=(
  -backend-config="bucket=${BUCKET}"
  -backend-config="key=${STACK}/terraform.tfstate"
  -backend-config="region=${REGION}"
  -backend-config="use_lockfile=true"
  -backend-config="encrypt=true"
)

case "$CMD" in
  migrate)
    terraform -chdir="$DIR" init -migrate-state -force-copy -input=false "${BACKEND[@]}"
    ;;
  init)
    terraform -chdir="$DIR" init -input=false -reconfigure "${BACKEND[@]}" "$@"
    ;;
  *)
    terraform -chdir="$DIR" init -input=false -reconfigure "${BACKEND[@]}" > /dev/null
    terraform -chdir="$DIR" "$CMD" "$@"
    ;;
esac
```

Look for `Successfully configured the backend "s3"!`. Confirm the state is now remote and run a plan to prove nothing changed:

```bash
aws s3 ls s3://$BUCKET/bootstrap/
scripts/tf.sh bootstrap plan
```

```
2026-11-08 10:15:02      18934 terraform.tfstate

No changes. Your infrastructure matches the configuration.
```

The local `terraform.tfstate` is now an empty leftover (and is git-ignored). You can delete it, and the `.backup` file.

### 6. Watch the lock work

Open two terminals.

**Terminal 1** (leave it waiting at the prompt):

```bash
scripts/tf.sh bootstrap apply -var enable_ci_roles=true
# Do you want to perform these actions?   <-- do NOT answer yet
```

**Terminal 2:**

```bash
scripts/tf.sh bootstrap plan
```

```
Error: Error acquiring the state lock

Error message: operation error S3: PutObject, https response error, StatusCode: 412 ... PreconditionFailed
Lock Info:
  ID:        3f6b9c1e-...
  Path:      plat-tfstate-123456789012-us-east-1/bootstrap/terraform.tfstate
  Operation: OperationTypeApply
  Who:       you@your-laptop
```

HTTP **412 Precondition Failed** is the conditional write being refused. Answer `no` in terminal 1, and the lock object disappears. If a run is killed mid-way and leaves a stale lock, `terraform force-unlock <ID>` removes it. Use it only after confirming no run is active.

### 7. Cause drift on purpose

Change the bucket behind Terraform's back:

```bash
aws s3api put-bucket-versioning --bucket $BUCKET \
  --versioning-configuration Status=Suspended
scripts/tf.sh bootstrap plan
```

```
  # aws_s3_bucket_versioning.state will be updated in-place
  ~ resource "aws_s3_bucket_versioning" "state" {
      ~ versioning_configuration {
          ~ status = "Suspended" -> "Enabled"
        }
    }

Plan: 0 to add, 1 to change, 0 to destroy.
```

Terraform noticed because the refresh read the real value and compared it to the configuration. Apply to put it back:

```bash
scripts/tf.sh bootstrap apply
```

### 8. Try to destroy the state bucket

```bash
scripts/tf.sh bootstrap destroy
```

```
Error: Instance cannot be destroyed

  Resource aws_s3_bucket.state has lifecycle.prevent_destroy set, but the plan calls for it to be destroyed.
```

Good. That is the guard doing its job. (To remove the bucket for real you would delete the `prevent_destroy` line, empty every object **and every version**, and destroy. That is deliberately inconvenient.)

### 9. Commit the lock file

```bash
git add bootstrap/.terraform.lock.hcl
```

Committing `.terraform.lock.hcl` pins the exact provider build, so CI and your laptop use identical providers.

### 10. Resources you now have 📦

| Resource | Name | Notes |
|---|---|---|
| S3 bucket | `plat-tfstate-<account>-<region>` | Versioned, encrypted, private, `prevent_destroy` |
| OIDC provider | `token.actions.githubusercontent.com` | One per account |
| IAM role | `plat-tf-plan` | Pull requests, read-only |
| IAM role | `plat-tf-apply` | `production` environment only (limited to `main`) |
| State objects | `bootstrap/terraform.tfstate` | Moved here in step 5 |

### Cleanup 🧹

Nothing to clean up: this stack is free to keep, and every later stack needs it. **Do not destroy it** until the very end of the series (Post 19).

---

## Quick Quiz 🧠

**Q1.** Why can't you write `bucket = var.state_bucket` inside the `backend "s3"` block?

<details>
<summary>Show answer</summary>

The backend is configured during `terraform init`, **before** variables and locals are evaluated, because Terraform needs the backend to load state before it can do anything else. So the block must contain literals, or be left empty and supplied through `-backend-config` (our approach) or a `.hcl` file.

</details>

**Q2.** A teammate says "the database password is marked `sensitive`, so it isn't in our state file." Are they right?

<details>
<summary>Show answer</summary>

**No.** `sensitive` only redacts the value in CLI output. The state stores the full attribute values in plain text. That is why the state bucket is private, encrypted, versioned and limited to the identities that run Terraform. (Later we also avoid creating passwords in Terraform at all, and let RDS manage the master password.)

</details>

**Q3.** Two engineers run `apply` on the same stack at the same moment. With `use_lockfile = true`, what happens to the second one?

<details>
<summary>Show answer</summary>

The first run writes `terraform.tfstate.tflock` with a conditional write (`If-None-Match: *`). The second run's identical write fails with `412 PreconditionFailed`, and Terraform reports *Error acquiring the state lock* along with who holds it. The second run changes nothing. It can wait with `-lock-timeout=5m` instead of failing immediately.

</details>

**Q4.** Why does the OIDC role for pull requests have a different trust condition from the one for `main`?

<details>
<summary>Show answer</summary>

The `sub` claim identifies *which workflow context* is asking. A pull request, which can be opened from a branch with unreviewed code, may only assume the **read-only** plan role. Only a job that runs in the **`production` environment** can assume the **apply** role, and that environment (Post 18) is limited to `main` and requires a reviewer's approval. When a job declares an environment, GitHub puts the environment name in `sub` instead of the branch, which is why the trust names `environment:production` and not `refs/heads/main`. Without the `sub` condition, any repository on GitHub could assume either role.

</details>

**Q5.** Someone suspends bucket versioning in the console. `terraform plan` reports one change. Which three things did it compare?

<details>
<summary>Show answer</summary>

The **configuration** (`status = "Enabled"`), the **state** (the last recorded value), and the **real bucket** (read during refresh, now `Suspended`). The real value differs from the configuration, so the plan proposes updating it in place.

</details>

---

## What's Next? 🚀

You can create infrastructure, and you know where its memory lives. But so far we have only read other people's HCL. Variables, locals, `for_each`, `dynamic` blocks and the rest of the language decide whether your code stays readable or turns into a copy-paste swamp.

👉 **[Post 02: The Terraform Language You Actually Need](content/aws-terraform/02-the-terraform-language.md)**: a small lab that needs no AWS account and shows, with real plans, why `for_each` beats `count`.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
