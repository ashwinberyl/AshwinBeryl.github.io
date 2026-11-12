---
title: "Modules: One Bucket Definition, Many Buckets"
date: 2026-11-08
tags: [aws, terraform, modules, s3, dynamic-blocks, moved-blocks, refactoring, intermediate]
description: Post 6 of the AWS on Terraform series. How to design a module's interface, what belongs inside it, how to call it with for_each, how to refactor existing resources into it without recreating them, and a lab that builds three buckets from one definition.
---

# Write It Once, Mean It Everywhere 📦

A secure S3 bucket takes **seven** resources in Terraform: the bucket, its public access block, ownership controls, versioning, default encryption, a bucket policy and (often) a lifecycle configuration. In the AWS series you ticked all of that in the console, once per bucket. Copy those seven blocks into every stack and sooner or later one copy loses its TLS rule or its public access block.

A **module** is a directory of `.tf` files that you call with inputs. `modules/s3-bucket` is that bucket, written once. Anything that creates a bucket in this series calls it.

---

## What a Module Is 🧱

| Part | File | Role |
|---|---|---|
| **Interface in** | `variables.tf` | The inputs, with types, defaults and validation |
| **Implementation** | `main.tf` | Resources and data sources |
| **Interface out** | `outputs.tf` | What callers may read |
| **Requirements** | `versions.tf` | Terraform and provider *version constraints* |

Calling a module is a block with a `source` and the inputs:

```hcl
# stacks/40-data/main.tf
module "data_bucket" {
  source = "../../modules/s3-bucket"

  name          = "plat-data-${local.account_id}-${var.region}"
  kms_key_arn   = local.kms_arn
  force_destroy = var.force_destroy_bucket
  prefixes      = ["raw/", "processed/", "models/"]

  lifecycle_rules = [
    {
      id                              = "housekeeping"
      noncurrent_expiration_days      = 30
      abort_incomplete_multipart_days = 7
    },
    {
      id                       = "raw-to-ia"
      prefix                   = "raw/"
      transition_days          = 30
      transition_storage_class = "STANDARD_IA"
    },
  ]
}
```

![One module, many callers](content/aws-terraform/images/06-one-module-many-callers.svg)

---

## Designing the Interface 🎛️

The interface is the part you can't easily change later, because every caller depends on it.

| Principle | Example in `s3-bucket` |
|---|---|
| **Secure by default, no way to turn off the essentials** | Public access block, `BucketOwnerEnforced` and the TLS-deny policy have *no* variable. A caller can't forget them, and can't disable them |
| **Few inputs, each meaningful** | `name`, `kms_key_arn`, `versioning`, `force_destroy`, `prefixes`, `lifecycle_rules` |
| **Sensible defaults** | `versioning = true`; `kms_key_arn = null` means SSE-S3 |
| **Optional features are `null`, empty, or a list** | No lifecycle rules means no lifecycle resource at all |
| **Structured input over many flat variables** | One `lifecycle_rules` list of objects with `optional()` fields, not twelve variables |
| **Outputs expose identifiers, not internals** | `id` and `arn`. Callers never write `module.x.aws_s3_bucket.this`, which they can't anyway |
| **No `provider` blocks inside** | The module uses whatever provider configuration the caller has, so the caller controls region, tags and credentials |

> **Key insight:** A module is a promise. Callers rely on what it does *and doesn't* let them do. Adding an optional input is safe. Renaming or removing one breaks every caller.

---

## Reading the Module 📖

### Defaults that every bucket gets

```hcl
# modules/s3-bucket/main.tf
resource "aws_s3_bucket_public_access_block" "this" {
  bucket = aws_s3_bucket.this.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    bucket_key_enabled = var.kms_key_arn != null

    apply_server_side_encryption_by_default {
      sse_algorithm     = var.kms_key_arn != null ? "aws:kms" : "AES256"
      kms_master_key_id = var.kms_key_arn
    }
  }
}
```

`bucket_key_enabled` is turned on exactly when a KMS key is used. A **bucket key** lets S3 reuse one data key for many objects instead of calling KMS per object, which cuts KMS request cost sharply (AWS series Post 06). With SSE-S3 there are no KMS calls to save, so it is off.

### Optional versioning

```hcl
# modules/s3-bucket/main.tf
resource "aws_s3_bucket_versioning" "this" {
  count = var.versioning ? 1 : 0

  bucket = aws_s3_bucket.this.id

  versioning_configuration {
    status = "Enabled"
  }
}
```

The resource exists only when `versioning` is true (`count`). A bucket that was never versioned has *no* versioning configuration, and Terraform shouldn't invent one.

### The lifecycle rule list

You saw the `dynamic` machinery in Post 02. The caller's side is just data:

```hcl
lifecycle_rules = [
  {
    id                              = "housekeeping"
    noncurrent_expiration_days      = 30
    abort_incomplete_multipart_days = 7
  },
  {
    id                       = "raw-to-ia"
    prefix                   = "raw/"
    transition_days          = 30
    transition_storage_class = "STANDARD_IA"
  },
]
```

Those are the two rules from AWS series Post 06, as four lines each instead of a page of console clicks. A rule can leave any field out, because every field except `id` is `optional(...)`.

### Prefixes

```hcl
# modules/s3-bucket/main.tf
resource "aws_s3_object" "prefix" {
  for_each = toset(var.prefixes)

  bucket  = aws_s3_bucket.this.id
  key     = each.value
  content = ""

  depends_on = [aws_s3_bucket_policy.this]
}
```

S3 has no folders (AWS series Post 06). A "folder" in the console is a zero-byte object whose key ends in `/`. Creating them gives the bucket the same `raw/`, `processed/` and `models/` layout in the console that we built by hand. They aren't required by anything.

---

## Calling Patterns 🔁

| Pattern | Use it when |
|---|---|
| `module "x" { source = "./m" }` | One instance |
| `for_each = toset([...])` or a map | Several, each with its own key: `module.scratch["one"]` |
| `count = var.enable ? 1 : 0` | An optional instance. Outputs then need `one(module.x[*].out)` |
| `providers = { aws = aws.other }` | The same module in a different region or account |

### Where a module comes from

| `source` | Example | Notes |
|---|---|---|
| Local path | `"../../modules/s3-bucket"` | What we use. Always the same commit as the caller |
| Git | `"git::https://github.com/org/repo.git//modules/s3-bucket?ref=v1.2.0"` | **Pin a tag**, never a branch |
| Registry | `"terraform-aws-modules/vpc/aws"` with `version = "~> 5.0"` | Convenient; read what you are running |

---

## Refactoring Into a Module 🔧

Suppose a stack already has `aws_s3_bucket.data`, applied and holding objects. You want it to use the module. If you simply delete the resources and add the module call, Terraform plans to **destroy the bucket** and create a new one. Tell it the objects are the same with `moved`:

```hcl
moved {
  from = aws_s3_bucket.data
  to   = module.data_bucket.aws_s3_bucket.this
}

moved {
  from = aws_s3_bucket_versioning.data
  to   = module.data_bucket.aws_s3_bucket_versioning.this[0]
}
# ...one block per resource that moves
```

`terraform plan` should then report `has moved to` lines and **no** creates or destroys. If a resource shows as destroy-and-create, a `moved` block is missing for it.

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "Modules are for sharing between teams." | They're for **consistency within one codebase** first. This repo uses local modules only. |
| "More inputs make a module more reusable." | They make it harder to use and to change. Expose what callers genuinely vary. |
| "I can read `module.x.aws_s3_bucket.this.arn`." | Only outputs are visible. If a caller needs an attribute, add an output. |
| "Provider settings go in the module." | They belong to the **caller**. A module with its own `provider` block can't be used with `count` or `for_each`. |
| "`for_each` on a module keys by the bucket's name." | It keys by whatever you iterate over, and that key appears in every address. Pick keys you'll never rename. |
| "Turning versioning off disables it." | Removing the resource **suspends** versioning. S3 never goes back to unversioned, and every existing version stays (and is billed). |
| "`force_destroy = true` is harmless." | It lets `destroy` delete a bucket **with objects and every version**. Fine for labs, dangerous for data. The default is `false`. |
| "Unpinned git modules are fine." | A moving branch changes your infrastructure when someone pushes. Pin a tag or commit. |
| "`terraform init` is only for providers." | It also downloads or links **modules**. Adding or changing a `source` requires `init -upgrade` or at least `init`. |
| "A module can depend on a resource through `depends_on`." | It can, since Terraform 0.13, but it makes everything inside unknown until the dependency is applied. Prefer passing a value that depends on it. |
| "Moving code into a module is free." | It changes every address. Without `moved` blocks it's a full recreate. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| `dynamic`, `optional()`, `count` toggles | Post 02 |
| `plat-data` KMS key (as `kms_key_arn`) | Post 05 |

| You create here | Used by |
|---|---|
| `modules/s3-bucket` | `stacks/40-data` (Post 07), then logs, artifacts and model buckets in later stacks |
| The `moved` pattern | Refactors and state surgery (Post 16) |

### Console clicks you no longer make

| In the AWS series you... | Here it is |
|---|---|
| **Create bucket**, Block Public Access, Bucket Versioning, Default encryption (SSE-KMS, Bucket Key) | One `module "..."` call |
| **Management, Lifecycle rules, Create lifecycle rule** (twice) | `lifecycle_rules = [ ... ]` |
| **Create folder** `raw/`, `processed/`, `models/` | `prefixes = [...]` |
| Pasted a TLS-only bucket policy | Built into the module, not optional |

---

## Lab: Three Buckets From One Definition 🛠️

This lab runs in `labs/06-modules` with **local state** and creates throwaway buckets with a `plat-lab-` prefix. They cost nothing while empty. Nothing here touches the real `plat-data` bucket, which arrives in Post 07.

```hcl
# labs/06-modules/main.tf
# Post 06 lab. Calls the s3-bucket module three times. Local state, destroyed at the end of the lab.
terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

variable "region" {
  type    = string
  default = "us-east-1"
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project    = "plat"
      managed_by = "terraform"
      stack      = "lab-06-modules"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  suffix = "${data.aws_caller_identity.current.account_id}-${var.region}"
}

# One call, every feature on.
module "logs" {
  source = "../../modules/s3-bucket"

  name          = "plat-lab-logs-${local.suffix}"
  force_destroy = true
  prefixes      = ["app/", "alb/"]

  lifecycle_rules = [
    {
      id                              = "expire-logs"
      expiration_days                 = 30
      noncurrent_expiration_days      = 7
      abort_incomplete_multipart_days = 7
    },
  ]
}

# One call, two buckets: for_each on a module.
module "scratch" {
  source   = "../../modules/s3-bucket"
  for_each = toset(["one", "two"])

  name          = "plat-lab-scratch-${each.key}-${local.suffix}"
  versioning    = false
  force_destroy = true
}

output "buckets" {
  value = merge(
    { logs = module.logs.id },
    { for k, m in module.scratch : "scratch-${k}" => m.id },
  )
}
```

### 1. Initialise and plan

```bash
cd labs/06-modules
terraform init
terraform plan
```

```
Plan: 19 to add, 0 to change, 0 to destroy.
```

`logs` has nine (bucket, access block, ownership, versioning, encryption, policy, lifecycle, two prefix objects). Each `scratch` bucket has five, because versioning is off and there are no lifecycle rules or prefixes: 9 + 5 + 5 = 19.

```bash
terraform apply
terraform state list | head -12
```

```
data.aws_caller_identity.current
module.logs.aws_s3_bucket.this
module.logs.aws_s3_bucket_lifecycle_configuration.this[0]
module.logs.aws_s3_bucket_ownership_controls.this
module.logs.aws_s3_bucket_policy.this
module.logs.aws_s3_bucket_public_access_block.this
module.logs.aws_s3_bucket_server_side_encryption_configuration.this
module.logs.aws_s3_bucket_versioning.this[0]
module.logs.aws_s3_object.prefix["alb/"]
module.logs.aws_s3_object.prefix["app/"]
module.scratch["one"].aws_s3_bucket.this
...
```

Notice the **addresses**: `module.logs...`, `module.scratch["one"]...`, and the `[0]` on resources created with `count`. A `moved` block must spell them exactly like this.

### 2. Verify with the CLI

```bash
terraform output buckets
LOGS=$(terraform output -json buckets | python3 -c 'import json,sys; print(json.load(sys.stdin)["logs"])')
SCRATCH=$(terraform output -json buckets | python3 -c 'import json,sys; print(json.load(sys.stdin)["scratch-one"])')

aws s3api get-bucket-versioning --bucket $LOGS
aws s3api get-bucket-versioning --bucket $SCRATCH
aws s3api get-bucket-encryption --bucket $LOGS \
  --query 'ServerSideEncryptionConfiguration.Rules[0].[ApplyServerSideEncryptionByDefault.SSEAlgorithm,BucketKeyEnabled]' --output text
aws s3api get-bucket-lifecycle-configuration --bucket $LOGS \
  --query 'Rules[].[ID,Status,Expiration.Days,NoncurrentVersionExpiration.NoncurrentDays,AbortIncompleteMultipartUpload.DaysAfterInitiation]' --output text
aws s3api list-objects-v2 --bucket $LOGS --query 'Contents[].Key' --output text
```

```
{ "Status": "Enabled" }
(no output: this bucket was never versioned)
AES256  False
expire-logs  Enabled  30  7  7
alb/    app/
```

The scratch bucket printing nothing is the point: it genuinely has no versioning configuration.

### 3. Prove the TLS rule is in the module

```bash
aws s3 ls s3://$LOGS --endpoint-url http://s3.us-east-1.amazonaws.com
```

```
An error occurred (AccessDenied) when calling the ListObjectsV2 operation: User: ... is not authorized to perform: s3:ListBucket on resource: ... with an explicit deny in a resource-based policy
```

A signed request over plain HTTP is refused by the `DenyInsecureTransport` statement. Every bucket from this module has it, and no caller had to remember.

### 4. Change one caller, not the module

Edit `labs/06-modules/main.tf`: change `for_each = toset(["one", "two"])` to `toset(["two", "three"])`, then:

```bash
terraform plan
```

```
Plan: 5 to add, 0 to change, 5 to destroy.
```

Only `module.scratch["one"]` is destroyed and only `module.scratch["three"]` is created. `["two"]` is untouched, because for_each keys are identities (the Post 02 lesson, now on a whole module). Apply it.

### 5. Watch "turn versioning off" actually suspend it

Versioning is on by default, so add `versioning = false` to the `logs` module call and plan:

```
  # module.logs.aws_s3_bucket_versioning.this[0] will be destroyed
Plan: 0 to add, 0 to change, 1 to destroy.
```

Apply, then read it back:

```bash
aws s3api get-bucket-versioning --bucket $LOGS
```

```
{ "Status": "Suspended" }
```

The resource is gone from state, but the bucket cannot return to "never versioned". It is **suspended**: no new versions are created, existing versions remain. Remove the `versioning = false` line and apply again to switch it back to Enabled.

### 6. Resources you now have 📦

| Resource | Name | Notes |
|---|---|---|
| Buckets | `plat-lab-logs-<account>-<region>`, `plat-lab-scratch-two-...`, `plat-lab-scratch-three-...` | Empty, free |

### Cleanup 🧹

```bash
terraform destroy
rm -f terraform.tfstate terraform.tfstate.backup
```

`force_destroy = true` in the lab lets the destroy remove the two prefix objects first. Nothing from this lab is used later.

---

## Quick Quiz 🧠

**Q1.** Why does the module have no variable to switch off the TLS-deny policy?

<details>
<summary>Show answer</summary>

Because it's a guarantee, not a preference. Anything a caller *can* disable will eventually be disabled by someone in a hurry. Leaving essentials out of the interface means every bucket in the platform is guaranteed to have them, and a reviewer doesn't need to check each call.

</details>

**Q2.** You move `aws_s3_bucket.data` into `module.data_bucket` and forget the `moved` block. What does `terraform plan` show?

<details>
<summary>Show answer</summary>

It plans to **destroy** `aws_s3_bucket.data` (no longer in the configuration) and **create** `module.data_bucket.aws_s3_bucket.this`. For a bucket holding data, that is data loss. With the `moved` block it reports `has moved to` and 0 to add, 0 to destroy.

</details>

**Q3.** Why does a module that creates `aws_s3_bucket_versioning` with `count` need `[0]` in the `moved` target?

<details>
<summary>Show answer</summary>

A resource with `count` has instances addressed by index, even when there is only one. The state address is `...versioning.this[0]`, and a `moved` block must name the instance exactly.

</details>

**Q4.** A teammate wants to add `provider "aws" { region = "eu-west-1" }` inside the module "so it's self-contained". What's the problem?

<details>
<summary>Show answer</summary>

A module with its own provider configuration can't be used with `count`, `for_each` or `depends_on` at the call site, and it hides where resources are created. Providers belong to the root configuration, and a module that needs another region receives it through the `providers = { aws = aws.other }` argument.

</details>

**Q5.** After setting `versioning = false` on an existing versioned bucket, `get-bucket-versioning` returns `Suspended`, not nothing. Why?

<details>
<summary>Show answer</summary>

S3 has no way to remove versioning from a bucket once it was enabled. The provider's "delete" for the versioning resource sets the status to `Suspended`. New writes stop creating versions, but existing versions are kept, and you still pay for them until a lifecycle rule expires them.

</details>

---

## What's Next? 🚀

We have the pieces: network, identity, key, a bucket module. Now we use all of them at once to build the stack that holds the platform's data: the S3 data lake, the DynamoDB jobs table, the Postgres database and the shared file system.

👉 **[Post 07: The Data Stack](content/aws-terraform/07-the-data-stack.md)**: S3, DynamoDB, RDS with a managed password and a snapshot-restore path, and EFS, in one stack.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
