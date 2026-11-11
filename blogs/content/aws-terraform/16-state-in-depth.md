---
title: "State in Depth: import, moved, removed and Recovery"
date: 2026-11-11
tags: [aws, terraform, state, import, moved, removed, s3, locking, terraform-remote-state, intermediate]
description: Post 16 of the AWS on Terraform series. Adopting a hand-made bucket with an import block and generated configuration, renaming without destroying, forgetting without deleting, forcing replacement, recovering state from S3 versions, clearing a stuck lock, and the three ways one stack can read another.
---

# Operating the State 🗃️

Everything so far assumed a clean start: Terraform creates a thing, remembers it, and later changes or destroys it. Real work isn't like that. Someone builds a bucket by hand. A resource needs a better name. A stack must stop managing something without deleting it. A state file is overwritten by mistake. This post is about those moments.

It uses a small throw-away lab, `labs/16-state`, with its own state file in the bucket from Post 01. Nothing in the platform stacks is touched.

---

## The Pieces 🧱

| Piece | What it is |
|---|---|
| `import` block | Adopts an existing real object into state, with an address you choose |
| `-generate-config-out` | Writes the configuration for that object, so you don't type it |
| `moved` block | Tells Terraform that an address changed, **not** the object |
| `removed` block | Forgets a resource without destroying it |
| `-replace=ADDRESS` | Destroys and recreates one resource on the next apply |
| `state` commands | The imperative toolbox: `list`, `show`, `mv`, `rm`, `pull`, `push` |
| `-refresh-only` | Updates state from reality without changing anything real |
| Bucket versions and lock file | Recovery and concurrency, from Post 01 |

![State operations](content/aws-terraform/images/16-state-operations.svg)

---

## Reading the Lab 📖

The lab directory starts almost empty:

```hcl
# labs/16-state/main.tf
# Post 16 lab: bring a bucket someone created by hand under Terraform, then practise state surgery.
variable "region" {
  type    = string
  default = "us-east-1"
}

variable "bucket_name" {
  description = "Name of the hand-made bucket (see the lab for the command that creates it)."
  type        = string
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project    = "plat"
      managed_by = "terraform"
      stack      = "lab-16-state"
    }
  }
}
```

A variable for the bucket's name, and a provider with the same `default_tags` as every stack (this will matter when we import). The backend is declared empty in `versions.tf` and filled in by `scripts/tf.sh`, exactly as in the real stacks:

```hcl
# labs/16-state/versions.tf
terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Run with: scripts/tf.sh labs/16-state <command>
  backend "s3" {}
}
```

Run it with `scripts/tf.sh labs/16-state <command>`. Its state key is `labs/16-state/terraform.tfstate` in the shared state bucket.

### The import block

```hcl
# labs/16-state/import.tf.example
# Copy to import.tf. The id of an S3 bucket is its name.
import {
  to = aws_s3_bucket.imported
  id = var.bucket_name
}
```

An `import` block says: the object with this **id** should live at this **address**. The id format is per resource type and is listed on each resource's documentation page; for a bucket it is the name. Two things make this better than the older `terraform import` command: it appears in a **plan**, so it can be reviewed and approved like any other change, and it can be committed so that every environment performs the same adoption.

### Generating the configuration

Writing resource blocks for an existing object by hand is error-prone. Terraform can write them:

```bash
scripts/tf.sh labs/16-state plan -generate-config-out=generated.tf -var bucket_name=<name>
```

It reads the real object through the provider and writes a `generated.tf` file with a resource block containing every attribute it found. Treat the file as a **draft**: remove computed attributes that conflict with each other, delete defaults you don't care about, and extract values into variables where they should vary. It is a starting point, and the provider version determines exactly what appears.

### moved: a rename is not a replacement

Terraform identifies a resource by its **address** (`aws_s3_bucket.imported`). If you rename the block, the old address has no configuration and the new address has no state, so Terraform plans to **destroy one and create the other**. For a bucket with objects, or a database, that is a catastrophe from a harmless edit. The `moved` block gives the answer:

```hcl
moved {
  from = aws_s3_bucket.imported
  to   = aws_s3_bucket.lab
}
```

Terraform renames the entry in state and changes nothing real. The block can stay in the code for as long as anyone might still have the old address in their state, and can be removed afterwards. The same block handles moving a resource **into or out of a module**, which is why modules (Post 06) are safe to refactor.

### removed: stop managing, keep the object

```hcl
removed {
  from = aws_s3_bucket.lab

  lifecycle {
    destroy = false
  }
}
```

Deleting a resource block from the code **destroys** the real object. `removed` with `destroy = false` is the alternative: forget it, leave it. Use it when ownership moves to another stack or team.

### Replace, and its imperative cousins

`terraform apply -replace='aws_s3_object.note'` forces one resource to be destroyed and recreated, with a plan that shows exactly that. It supersedes the old `terraform taint`, which changed state **before** review. `terraform state mv` and `terraform state rm` do what `moved` and `removed` do, but immediately, on state itself, with no plan and no review. They remain useful for emergencies; in normal work, prefer the blocks.

### Three ways to read another stack

The platform's stacks read each other through `terraform_remote_state`. It's worth knowing the alternatives and what each costs.

| Approach | How | Good | Costs |
|---|---|---|---|
| `terraform_remote_state` (what we use) | Read the other stack's **outputs** from its state file | Exact values, typed, no lookup ambiguity, fails loudly if an output is missing | The reader needs `s3:GetObject` on the **whole state file**, which may contain secrets. Couples stacks by output name. Needs the same backend. |
| Data sources by name or tag | `data "aws_vpc"` with a filter | No coupling to another stack's state; works with objects not created by Terraform | Lookups can match zero or several objects. Silent dependency on tags and names. Needs describe permissions. |
| Published parameters | One stack writes values to SSM Parameter Store, others read them | An explicit **contract** between stacks; cross-tool; fine-grained permissions | An extra resource per value, a second place to keep correct. |

Our case is a single repository, one backend and one team, so the first option is the clearest. In a larger organisation with separate teams and accounts, the third is worth its overhead.

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "`import` creates the configuration." | The classic command only fills state. The block with `-generate-config-out` drafts the configuration; you still own and edit it. |
| "After importing, the plan will be empty." | Often not: tags (from `default_tags`), settings the provider defaults and settings the hand-made object lacks all show as differences. Read them. |
| "Renaming a resource block is a cosmetic change." | It plans a destroy and a create unless a `moved` block is present. |
| "Removing a resource block keeps the object." | It **destroys** it. Use `removed` with `destroy = false`. |
| "`terraform state rm` deletes the real resource." | It only removes the state entry. The next plan wants to **create** a duplicate. |
| "State is a cache I can regenerate." | It is the only record of which real object each address means. Rebuilding it is manual (imports, one resource at a time). |
| "State is safe to commit if the repo is private." | It can hold secrets and ids. Keep it in an encrypted, versioned, access-controlled bucket. |
| "A stuck lock means the state is corrupt." | Usually a crashed run left a lock object. `terraform force-unlock <ID>` clears it, once you are sure no run is active. |
| "Moving between modules needs state surgery." | A `moved` block does it, and shows it in the plan. |
| "`-replace` is the same as `taint`." | `-replace` is part of the plan, so it can be reviewed; `taint` edited state immediately. |
| "`terraform_remote_state` only reads outputs, so it is harmless." | The **permission** is on the whole state file. Anyone who can run it can read everything in that file. |
| "I can `import` into any address." | The resource must exist in the configuration at that address, and the object can be in **one** state only. Importing it into two is a future conflict. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| The versioned, encrypted state bucket and lock file | Post 01 |
| `default_tags`, `moved`, modules | Posts 02 and 06 |
| `terraform_remote_state` | Post 05 and every later stack |

| You learn here | Used by |
|---|---|
| Adopting existing resources | The migration path from the AWS series' hand-made lab (README) |
| Safe renames | Refactoring any stack |
| Recovery | Post 19's teardown and rebuild |

### Console clicks you no longer make

There is no console equivalent for state. The closest is the question "what do I actually have?", which these commands answer.

| Console habit | Terraform operation |
|---|---|
| Open the resource and read its settings to write them down | `-generate-config-out` |
| Rename a resource by creating a new one and deleting the old | `moved` |
| Walk away from a resource and leave it running | `removed` with `destroy = false` |
| Delete and recreate a resource to "reset" it | `-replace` |

---

## Lab: Adopt, Rename, Forget, Recover 🛠️

### 1. Create something by hand

```bash
export AWS_PROFILE=plat-admin AWS_REGION=us-east-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
NAME=plat-lab-import-$ACCOUNT
aws s3api create-bucket --bucket $NAME
echo "left over from before Terraform" > /tmp/old.txt && aws s3 cp /tmp/old.txt s3://$NAME/old.txt
```

### 2. Write the import block and generate the code

```bash
cp labs/16-state/import.tf.example labs/16-state/import.tf
scripts/tf.sh labs/16-state plan -generate-config-out=generated.tf -var bucket_name=$NAME
```

```
aws_s3_bucket.imported: Preparing import... [id=plat-lab-import-123456789012]
aws_s3_bucket.imported: Refreshing state... [id=plat-lab-import-123456789012]

Terraform will perform the following actions:

  # aws_s3_bucket.imported will be imported
  # (config will be generated)
    resource "aws_s3_bucket" "imported" {
        ...
    }

Plan: 1 to import, 0 to add, 0 to change, 0 to destroy.

Terraform has generated configuration and written it to generated.tf. Please review the configuration and edit it as necessary.
```

Open `labs/16-state/generated.tf`. Trim it to what you care about, which for this lab is `bucket` (use `var.bucket_name`) and `force_destroy = true` so the lab bucket can be removed later. Then plan again:

```bash
scripts/tf.sh labs/16-state plan -var bucket_name=$NAME
```

```
  # aws_s3_bucket.imported will be updated in-place
  # (imported from "plat-lab-import-123456789012")
  ~ resource "aws_s3_bucket" "imported" {
      ~ tags_all = {
          + "managed_by" = "terraform"
          + "project"    = "plat"
          + "stack"      = "lab-16-state"
        }
    }

Plan: 1 to import, 0 to add, 1 to change, 0 to destroy.
```

That is the honest picture: **adopted, and about to be tagged**, because the hand-made bucket had none of our tags. Apply:

```bash
scripts/tf.sh labs/16-state apply -var bucket_name=$NAME
scripts/tf.sh labs/16-state state list
```

```
aws_s3_bucket.imported
```

The `import` block has done its job; delete `import.tf` (leaving it is harmless, since the object is already in state). Check the bucket still has the old file: `aws s3 ls s3://$NAME/`.

### 3. Rename it, wrongly then rightly

Change the block's address in `generated.tf` from `imported` to `lab`, nothing else:

```bash
scripts/tf.sh labs/16-state plan -var bucket_name=$NAME
```

```
  # aws_s3_bucket.imported will be destroyed
  # (because aws_s3_bucket.imported is not in configuration)
  # aws_s3_bucket.lab will be created
Plan: 1 to add, 0 to change, 1 to destroy.
```

**Do not apply this.** It would destroy the bucket (including `old.txt`, with `force_destroy`) and create an empty one. Add the `moved` block from above to `generated.tf` and plan again:

```
  # aws_s3_bucket.imported has moved to aws_s3_bucket.lab
Plan: 0 to add, 0 to change, 0 to destroy.
```

Apply to record the new address. `state list` now shows `aws_s3_bucket.lab`, and `old.txt` is untouched. The imperative equivalent, for reference, would have been `scripts/tf.sh labs/16-state state mv aws_s3_bucket.imported aws_s3_bucket.lab` before editing the code, with no plan to review.

### 4. Add an object and force it to be replaced

Append to `main.tf` (or a new file):

```hcl
resource "aws_s3_object" "note" {
  bucket  = aws_s3_bucket.lab.id
  key     = "notes.txt"
  content = "managed by terraform"
}
```

Apply it, then:

```bash
scripts/tf.sh labs/16-state apply -var bucket_name=$NAME -replace=aws_s3_object.note
```

```
  # aws_s3_object.note will be replaced, as requested
Plan: 1 to add, 0 to change, 1 to destroy.
```

Reviewable, exactly one resource, and the reason is stated in the plan.

### 5. Break it: lose the state entry, then recover

Simulate a mistake:

```bash
scripts/tf.sh labs/16-state state rm aws_s3_object.note
scripts/tf.sh labs/16-state plan -var bucket_name=$NAME
```

```
  # aws_s3_object.note will be created
Plan: 1 to add, 0 to change, 0 to destroy.
```

The object exists but Terraform has forgotten it. Recover from the bucket's **version history**:

```bash
S=plat-tfstate-$ACCOUNT-$AWS_REGION
K=labs/16-state/terraform.tfstate
aws s3api list-object-versions --bucket $S --prefix $K --query 'Versions[].[VersionId,LastModified,IsLatest]' --output text | head -4
```

```
nQ1x...  2026-11-12T09:41:07+00:00  True
Gh7r...  2026-11-12T09:40:12+00:00  False
...
```

The second line is the state **before** the `state rm`. Restore it by copying that version over the key; this creates a new latest version with the old content:

```bash
OLD=<the VersionId from the second line>
aws s3api copy-object --bucket $S --key $K --copy-source "$S/$K?versionId=$OLD"
scripts/tf.sh labs/16-state plan -var bucket_name=$NAME
```

```
No changes. Your infrastructure matches the configuration.
```

This is why Post 01 insisted on a **versioned** state bucket: the recovery tool is S3's, not Terraform's.

### 6. Break it: a stuck lock

Terraform's native lock is an S3 object next to the state. Create one by hand, as a crashed run would have left:

```bash
cat > /tmp/lock.json <<'JSON'
{"ID":"11111111-2222-3333-4444-555555555555","Operation":"OperationTypeApply","Info":"","Who":"someone@laptop","Version":"1.10.0","Created":"2026-11-12T10:00:00Z","Path":""}
JSON
aws s3api put-object --bucket $S --key $K.tflock --body /tmp/lock.json >/dev/null
scripts/tf.sh labs/16-state plan -var bucket_name=$NAME
```

```
Error: Error acquiring the state lock

Lock Info:
  ID:        11111111-2222-3333-4444-555555555555
  Operation: OperationTypeApply
  Who:       someone@laptop
```

The wording of the error varies slightly by version, but the information is the same. First check that nobody really is running Terraform, then:

```bash
scripts/tf.sh labs/16-state force-unlock -force 11111111-2222-3333-4444-555555555555
scripts/tf.sh labs/16-state plan -var bucket_name=$NAME
```

The plan runs again. Never force-unlock a lock whose owner might still be running: two concurrent applies on one state is the thing the lock exists to prevent.

### 7. Forget without deleting

Remove the `aws_s3_object.note` block and replace the bucket block with:

```hcl
removed {
  from = aws_s3_bucket.lab

  lifecycle {
    destroy = false
  }
}
```

(Delete the object block first, or the object's reference to the bucket will stop the plan.)

```bash
scripts/tf.sh labs/16-state plan -var bucket_name=$NAME
```

```
  # aws_s3_object.note will be destroyed
  # aws_s3_bucket.lab will no longer be managed by Terraform, but will not be destroyed
Plan: 0 to add, 0 to change, 1 to destroy.
```

Apply. Then prove the bucket survived: `aws s3api head-bucket --bucket $NAME` prints nothing and succeeds, `state list` is empty.

### 8. Resources you now have 📦

| Resource | Name | Notes |
|---|---|---|
| S3 bucket (hand-made) | `plat-lab-import-<account>` | Not in any state any more |
| State object | `labs/16-state/terraform.tfstate` | In the shared state bucket |

### Cleanup 🧹

```bash
aws s3 rb s3://$NAME --force
aws s3 rm s3://$S/labs/16-state/terraform.tfstate
```

The second command deletes the lab's current state object; the bucket's versioning keeps a delete marker and the older versions, which is fine.

---

## Quick Quiz 🧠

**Q1.** You rename `aws_db_instance.meta` to `aws_db_instance.main` and the plan shows one destroy and one create. What was missing?

<details>
<summary>Show answer</summary>

A **`moved` block** (`from = aws_db_instance.meta`, `to = aws_db_instance.main`). Without it Terraform sees an unrelated removal and addition. With it the plan shows no change.

</details>

**Q2.** What is the difference between deleting a resource block and using `removed` with `destroy = false`?

<details>
<summary>Show answer</summary>

Deleting the block makes Terraform **destroy** the real object. `removed` with `destroy = false` **forgets** it: the state entry goes, the object stays.

</details>

**Q3.** Why is `-replace` better than `terraform taint`?

<details>
<summary>Show answer</summary>

`-replace` is evaluated as part of the plan, so you see and approve exactly what will be recreated. `taint` modified state immediately, before any review.

</details>

**Q4.** You deleted the wrong state entry with `state rm`. What recovers it, and why does it work?

<details>
<summary>Show answer</summary>

Copy the **previous version** of the state object back over the key in the S3 bucket. It works because the state bucket is versioned, so every write kept the earlier content.

</details>

**Q5.** Why does `terraform_remote_state` access need more thought than it seems?

<details>
<summary>Show answer</summary>

It reads outputs, but the permission it needs is `s3:GetObject` on the **entire state file**, which can contain secrets and ids of everything in the stack. Anyone who can run it can read all of it.

</details>

---

## What's Next? 🚀

You can now adopt, move and recover. The next question is how to keep a codebase of this size correct as it changes: tests that run without AWS, scanners that read the code, and checks that run inside the plan.

👉 [Post 17: Quality Gates: terraform test, tflint, trivy and check blocks](content/aws-terraform/17-quality-gates.md)

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
