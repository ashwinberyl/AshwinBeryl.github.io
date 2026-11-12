---
title: "The Terraform Language You Actually Need"
date: 2026-11-08
tags: [aws, terraform, hcl, variables, for-each, count, dynamic-blocks, lifecycle, intermediate]
description: Post 2 of the AWS on Terraform series. Types, variables, locals, expressions, count versus for_each, dynamic blocks, lifecycle rules and moved blocks, taught in a lab that needs no AWS account.
---

# Reading and Writing HCL 📝

Terraform's language (HCL) is small. A handful of block types and about a dozen ideas cover almost everything in this series. The ideas that trip people up are not the syntax: they are **how Terraform decides what exists** (addresses), **in what order** (the dependency graph), and **what happens when the code changes shape** (`count` versus `for_each`).

This post is a tour of those ideas, followed by a lab that uses only Terraform's built-in `terraform_data` resource. **You need no AWS account and nothing is billed.**

---

## The Block Types 🧱

| Block | Purpose | Example in this repo |
|---|---|---|
| `terraform` | Required Terraform and provider versions, backend | `stacks/*/versions.tf` |
| `provider` | Configures a provider (region, `default_tags`) | `providers.tf` |
| `variable` | An input | `enable_nat` in `20-network` |
| `locals` | Named expressions, to avoid repeating yourself | `local.private` in `40-data` |
| `resource` | Something Terraform creates and manages | `aws_vpc.this` |
| `data` | Something Terraform only reads | `aws_caller_identity.current` |
| `module` | A reusable folder of the blocks above | `module "vpc"` in `20-network` |
| `output` | A value to print and to share with other stacks | `vpc_id` |
| `moved`, `import`, `removed` | Change what state tracks without touching infrastructure | later in this post and in Post 16 |

Files are only a convention. Terraform reads **every `.tf` file in a directory** as one configuration, so `main.tf`, `variables.tf` and `outputs.tf` are for humans.

---

## Types and Variables 🔤

| Type | Written as | Notes |
|---|---|---|
| `string`, `number`, `bool` | `"plat"`, `20`, `true` | Terraform converts between them when safe (`"20"` to `20`) |
| `list(T)` | `["a", "b"]` | Ordered, indexed by position |
| `set(T)` | `toset(["a", "b"])` | Unordered, unique, **no index** |
| `map(T)` | `{ a = 1, b = 2 }` | All values the same type |
| `object({...})` | `{ cidr = "x", public = true }` | Fixed keys, each with its own type |
| `any` | | Type decided by the value. Avoid it for inputs |

A variable can carry a **type**, a **default**, a **description**, a **validation** and a **sensitive** flag. The `optional()` modifier makes an object attribute skippable, with a default:

```hcl
# modules/vpc/variables.tf
variable "gateway_endpoints" {
  description = "Free gateway endpoints to attach to the private route table. Supported: s3, dynamodb."
  type        = set(string)
  default     = ["s3", "dynamodb"]

  validation {
    condition     = alltrue([for e in var.gateway_endpoints : contains(["s3", "dynamodb"], e)])
    error_message = "gateway_endpoints may only contain s3 and dynamodb."
  }
}
```

The `validation` block turns a typo like `"s4"` into an error at plan time instead of a confusing provider failure at apply time. Compare with the S3 module's lifecycle-rule input, where most attributes are `optional(...)`:

```hcl
# modules/s3-bucket/variables.tf
variable "lifecycle_rules" {
  description = "Lifecycle rules. Leave a field out to skip it."
  type = list(object({
    id                                 = string
    prefix                             = optional(string, "")
    noncurrent_expiration_days         = optional(number)
    abort_incomplete_multipart_days    = optional(number)
    transition_days                    = optional(number)
    transition_storage_class           = optional(string, "STANDARD_IA")
    expiration_days                    = optional(number)
    expired_object_delete_marker_clean = optional(bool, false)
  }))
  default = []
}
```

**Ways to set a variable**, from lowest to highest precedence: the `default`, then `TF_VAR_name` environment variables, then `terraform.tfvars`, then `*.auto.tfvars`, then `-var` and `-var-file` on the command line (the later one on the line wins). The command line always wins. In this series you will mostly use `-var enable_nat=true`.

---

## Expressions 🧮

### References

| You write | It means |
|---|---|
| `var.region` | An input variable |
| `local.account_id` | A local value |
| `aws_vpc.this.id` | An attribute of a resource |
| `data.aws_caller_identity.current.account_id` | An attribute of a data source |
| `module.vpc.vpc_id` | An output of a module |
| `each.key`, `each.value` | The current element inside `for_each` |
| `count.index` | The current position inside `count` |

Every reference is also a **dependency**. When `aws_subnet.public` mentions `aws_vpc.this.id`, Terraform knows to create the VPC first and to destroy it last. You almost never write `depends_on`; you use it only when a dependency is real but invisible in the code (for example, a policy that must exist before something is allowed to use it).

### Conditionals and `for` expressions

```hcl
status = var.versioning ? "Enabled" : "Suspended"          # conditional

[for k, s in var.subnets : s.cidr if s.public]            # list, filtered
{ for k, s in var.subnets : s.cidr => k }                  # map, new keys
```

A `for` expression in `[ ]` builds a list, in `{ }` builds a map. The `if` clause filters. Our VPC module uses one to turn two parallel lists into a map keyed by AZ letter:

```hcl
# modules/vpc/main.tf
locals {
  az_suffix = [for az in var.azs : substr(az, length(az) - 1, 1)]

  public = {
    for i, az in var.azs : local.az_suffix[i] => {
      az   = az
      cidr = var.public_subnet_cidrs[i]
    }
  }

  private = {
    for i, az in var.azs : local.az_suffix[i] => {
      az   = az
      cidr = var.private_subnet_cidrs[i]
    }
  }

  first_az = local.az_suffix[0]

  endpoint_names = {
    s3       = "s3-gw"
    dynamodb = "ddb-gw"
  }
}
```

### The functions you will actually meet

| Function | Use | Example |
|---|---|---|
| `cidrsubnet(prefix, bits, n)` | Carve a subnet from a range | `cidrsubnet("10.20.0.0/16", 8, 10)` is `10.20.10.0/24` |
| `merge(a, b)` | Combine maps. Later wins | tags |
| `lookup`, `try`, `can` | Safe access, fallbacks | `try(var.x.y, "none")` |
| `toset`, `tolist`, `keys`, `values` | Convert and inspect collections | |
| `format`, `join`, `split`, `substr` | Strings | |
| `jsonencode` | Build JSON from an object, so policies are code, not text | |
| `one(list)` | The single element of a 0-or-1 list, else `null` | `one(aws_db_instance.meta[*].endpoint)` |

`one()` pairs with the **splat** `[*]`, which turns a resource with `count` into a list. It is how we write outputs for things that may not exist when a toggle is off.

---

## `count` versus `for_each` ⚖️

Both create several copies of a resource. They differ in how each copy is **addressed**, and the address is what state remembers.

| | `count = 3` | `for_each = toset(["a", "b", "c"])` |
|---|---|---|
| Address | `aws_x.y[0]`, `[1]`, `[2]` | `aws_x.y["a"]`, `["b"]`, `["c"]` |
| Identity of an instance | Its **position** | Its **key** |
| Remove the first element | Every later index **shifts**; Terraform sees them as changed | Only that one key disappears |
| Best for | "0 or 1 of these" toggles (`count = var.enable ? 1 : 0`) | Collections of real things |

![count versus for_each when the first element is removed](content/aws-terraform/images/02-count-vs-for-each.svg)

> **Key insight:** If removing item 1 from a list should not touch items 2 and 3, use `for_each`. Use `count` for on/off switches and for nothing else.

`for_each` needs a **map or a set of strings** whose keys are known at plan time. If the keys come from a value that only exists after apply (a resource ID), you get *"The for_each map includes keys derived from resource attributes that cannot be determined until apply"*. Key by something you control (a name, an AZ letter), not by an ID.

---

## `dynamic` Blocks 🔁

Some resources contain repeated **nested blocks** (an S3 lifecycle `rule`, a DynamoDB `attribute`). When the number of blocks depends on input, a `dynamic` block generates them:

```hcl
# modules/s3-bucket/main.tf
resource "aws_s3_bucket_lifecycle_configuration" "this" {
  count = length(var.lifecycle_rules) > 0 ? 1 : 0

  bucket = aws_s3_bucket.this.id

  dynamic "rule" {
    for_each = var.lifecycle_rules

    content {
      id     = rule.value.id
      status = "Enabled"

      filter {
        prefix = rule.value.prefix
      }

      dynamic "noncurrent_version_expiration" {
        for_each = rule.value.noncurrent_expiration_days == null ? [] : [rule.value.noncurrent_expiration_days]

        content {
          noncurrent_days = noncurrent_version_expiration.value
        }
      }

      dynamic "abort_incomplete_multipart_upload" {
        for_each = rule.value.abort_incomplete_multipart_days == null ? [] : [rule.value.abort_incomplete_multipart_days]

        content {
          days_after_initiation = abort_incomplete_multipart_upload.value
        }
      }

      dynamic "transition" {
        for_each = rule.value.transition_days == null ? [] : [rule.value.transition_days]

        content {
          days          = transition.value
          storage_class = rule.value.transition_storage_class
        }
      }

      dynamic "expiration" {
        for_each = rule.value.expiration_days == null && !rule.value.expired_object_delete_marker_clean ? [] : [1]

        content {
          days                         = rule.value.expiration_days
          expired_object_delete_marker = rule.value.expiration_days == null ? rule.value.expired_object_delete_marker_clean : null
        }
      }
    }
  }

  depends_on = [aws_s3_bucket_versioning.this]
}
```

The pattern `for_each = X == null ? [] : [X]` generates **zero or one** block, which is how an optional setting becomes optional nested syntax. Read it as "if the input is null, make no block". Use `dynamic` sparingly: for a fixed block, plain syntax is easier to read.

---

## `lifecycle`: Rules About Change 🔒

| Setting | What it does | Where we use it |
|---|---|---|
| `prevent_destroy = true` | Any plan that would destroy this fails | State bucket |
| `create_before_destroy = true` | When replacement is needed, build the new one first | Resources that something else points at |
| `ignore_changes = [attr]` | Do not treat this attribute's drift as a change | Attributes something else manages (an autoscaler's `desired_count`) |
| `replace_triggered_by = [...]` | Force replacement when another resource changes | Rare |
| `precondition` / `postcondition` | Fail the plan with your own message if an assumption is wrong | VPC module (one CIDR per AZ) |

---

## Changing What State Tracks 🧭

Renaming a resource in code makes Terraform see *"old address gone, new address wanted"*, so it plans to destroy and recreate. A **`moved` block** tells it they are the same object:

```hcl
moved {
  from = aws_subnet.private_a
  to   = aws_subnet.private["a"]
}
```

`moved` is evaluated in the plan and changes nothing in AWS. You will use it whenever you refactor, including when we pull code into a module (Post 06). `import` is the mirror image: it brings an **existing** AWS object under management (Post 16).

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "Order of blocks in the file matters." | It doesn't. Terraform builds a graph from references and runs it in dependency order, in parallel where it can. |
| "`count` and `for_each` are interchangeable." | They create different **addresses**. Switching one for the other without `moved` blocks destroys and recreates everything. |
| "`for_each` accepts a list." | Only a **map or a set of strings**. Convert with `toset(list)`, which also removes duplicates. |
| "A `set` of numbers can be used for `for_each`." | Keys must be strings. Use `toset([for n in list : tostring(n)])`. |
| "`terraform.tfvars` is loaded by every command." | It is loaded automatically if it is named exactly that (or `*.auto.tfvars`). Any other name needs `-var-file`. |
| "A variable default is a constraint." | It's only a default. The **type** and **validation** are the constraints. |
| "Locals are variables." | They can't be set from outside. They are named expressions, evaluated each run. |
| "`depends_on` makes things safer." | It adds ordering and can make a plan unknown until apply. Prefer a real reference. |
| "Comments and formatting don't matter." | `terraform fmt -check` fails CI on unformatted files, so run `terraform fmt -recursive` before you commit. |
| "A `sensitive` variable can't leak." | It's redacted in output but is still in state, and a value used in a resource **name** or tag is visible in AWS. |
| "`try()` hides errors safely." | It hides *all* errors in the expression, including real typos. Use it for optional data, not to silence failures. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| A working `terraform` binary and the cloned repo | Post 01 |

| You learn here | Used by |
|---|---|
| Types, `optional()`, `validation` | Every module interface (Posts 04 and 06) |
| `for` expressions | Subnet maps, identity memberships (Posts 03 and 04) |
| `count` toggles with `one()` | `enable_nat`, `enable_rds`, `enable_secretsmanager_endpoint` |
| `for_each` | Subnets, mount targets, identity groups |
| `dynamic` | S3 lifecycle rules (Post 06) |
| `moved` | Refactors in Posts 06 and 16 |

---

## Lab: Experiment With the Language 🛠️

Everything here runs in `labs/02-language`. It uses `terraform_data`, a resource built into Terraform that stores a value in state and calls no API. There is nothing to bill and nothing to clean up in AWS.

```hcl
# labs/02-language/main.tf
# Post 02 lab. Uses only the built-in terraform_data resource, so it needs no AWS account.
terraform {
  required_version = ">= 1.10"
}

variable "names" {
  type    = list(string)
  default = ["alpha", "bravo", "charlie"]
}

variable "subnets" {
  type = map(object({
    cidr   = string
    public = optional(bool, false)
  }))
  default = {
    a = { cidr = "10.0.0.0/24", public = true }
    b = { cidr = "10.0.1.0/24" }
    c = { cidr = "10.0.2.0/24" }
  }
}

locals {
  public_cidrs  = [for k, s in var.subnets : s.cidr if s.public]
  by_cidr       = { for k, s in var.subnets : s.cidr => k }
  subnet_names  = [for k in sort(keys(var.subnets)) : "plat-${k}"]
  private_count = length([for s in var.subnets : s if !s.public])
  tags          = merge({ project = "plat" }, { env = "dev" })
}

# Same list, two ways of addressing it.
resource "terraform_data" "by_count" {
  count = length(var.names)

  triggers_replace = var.names[count.index]
}

resource "terraform_data" "by_key" {
  for_each = toset(var.names)

  triggers_replace = each.key
}

output "by_count_addresses" {
  value = [for i, r in terraform_data.by_count : "terraform_data.by_count[${i}]"]
}

output "by_key_addresses" {
  value = [for k, r in terraform_data.by_key : "terraform_data.by_key[\"${k}\"]"]
}

output "locals_preview" {
  description = "Everything the locals compute, so `terraform plan` shows it and tflint sees them used."
  value       = {
    public_cidrs  = local.public_cidrs
    by_cidr       = local.by_cidr
    subnet_names  = local.subnet_names
    private_count = local.private_count
    tags          = local.tags
  }
}
```

### 1. Initialise

```bash
cd labs/02-language
terraform init
```

```
Terraform has been successfully initialized!
```

No provider is downloaded, because `terraform_data` is part of Terraform itself.

### 2. Explore expressions in the console

`terraform console` loads the configuration and lets you evaluate expressions.

```bash
terraform console
```

```
> join(",", local.public_cidrs)
"10.0.0.0/24"
> join(",", [for k, v in local.by_cidr : "${k}=${v}"])
"10.0.0.0/24=a,10.0.1.0/24=b,10.0.2.0/24=c"
> join(",", local.subnet_names)
"plat-a,plat-b,plat-c"
> local.private_count
2
> jsonencode(local.tags)
"{\"env\":\"dev\",\"project\":\"plat\"}"
> cidrsubnet("10.20.0.0/16", 8, 10)
"10.20.10.0/24"
> cidrsubnet("10.20.0.0/16", 8, 11)
"10.20.11.0/24"
> substr("us-east-1a", length("us-east-1a") - 1, 1)
"a"
> try(var.subnets["z"].cidr, "no such subnet")
"no such subnet"
> format("%s-%03d", "plat", 7)
"plat-007"
> length(toset(["a", "b", "a"]))
2
```

Notice the `cidrsubnet` results. They are exactly the private subnets `10.20.10.0/24` and `10.20.11.0/24` from the VPC in the AWS series, and you will see the same function again in Post 04. `public` was `optional(bool, false)` in the variable, so `b` and `c` have `public = false` without being written. Press **Ctrl-D** to leave the console.

### 3. Create six instances

```bash
terraform plan
```

```
Plan: 6 to add, 0 to change, 0 to destroy.
```

Three from `by_count`, three from `by_key`.

```bash
terraform apply -auto-approve
terraform state list
```

```
terraform_data.by_count[0]
terraform_data.by_count[1]
terraform_data.by_count[2]
terraform_data.by_key["alpha"]
terraform_data.by_key["bravo"]
terraform_data.by_key["charlie"]
```

That list *is* the set of addresses state remembers. Notice that `[0]` is "whichever name is first", but `["alpha"]` is always alpha.

### 4. Remove the first name

```bash
terraform plan -var 'names=["bravo","charlie"]'
```

```
  # terraform_data.by_count[0] must be replaced
  # terraform_data.by_count[1] must be replaced
  # terraform_data.by_count[2] will be destroyed
  # terraform_data.by_key["alpha"] will be destroyed

Plan: 2 to add, 0 to change, 4 to destroy.
```

Same input, same intent, but `count` replaced two instances it had no reason to touch, while `for_each` removed only `alpha`. With real resources, "replaced" means a database or a bucket recreated. This is the lesson of the whole post, and you just watched it happen. **Do not apply this change.**

### 5. Rename a resource, with and without `moved`

Rename the `by_key` resource to `keyed`. These two edits change the declaration and the reference in the output:

```bash
sed -i 's/resource "terraform_data" "by_key"/resource "terraform_data" "keyed"/; s/ in terraform_data.by_key / in terraform_data.keyed /' main.tf
terraform plan
```

```
Plan: 3 to add, 0 to change, 3 to destroy.
```

A pure rename is a destroy-and-create of all three. Now tell Terraform it is the same object by appending:

```hcl
moved {
  from = terraform_data.by_key
  to   = terraform_data.keyed
}
```

```bash
terraform plan
```

```
  # terraform_data.by_key["alpha"] has moved to terraform_data.keyed["alpha"]
  # terraform_data.by_key["bravo"] has moved to terraform_data.keyed["bravo"]
  # terraform_data.by_key["charlie"] has moved to terraform_data.keyed["charlie"]

Plan: 0 to add, 0 to change, 0 to destroy.
```

Apply it if you like (`terraform apply -auto-approve`). State is rewritten and nothing else happens. Real refactors in the next posts use exactly this.

### 6. Clean up

```bash
terraform destroy -auto-approve
git checkout -- main.tf
rm -f terraform.tfstate terraform.tfstate.backup
```

### Resources you now have 📦

None. The lab used only local state, which you just removed.

---

## Quick Quiz 🧠

**Q1.** You have `count = length(var.az_names)` creating subnets, and you delete the first AZ from the list. What does the plan do to the other subnets, and how should the code be written instead?

<details>
<summary>Show answer</summary>

Indexes shift, so subnet `[1]` becomes `[0]` and so on. Terraform sees the later subnets as changed (here, a different AZ or CIDR, which forces **replacement**), plus one destroyed. Use `for_each` keyed by something stable such as the AZ letter, so each subnet keeps its own address. Our VPC module keys by `a` and `b`.

</details>

**Q2.** `for_each = aws_subnet.private[*].id` fails with an error about keys that cannot be determined until apply. Why, and what is the fix?

<details>
<summary>Show answer</summary>

IDs don't exist until the subnets are created, but `for_each` must know its keys during **plan**. Iterate over something known in advance, such as the map you built the subnets from (`for_each = local.private`) or `for_each = aws_subnet.private` (keyed by the AZ letter), and read `.id` from `each.value`.

</details>

**Q3.** What does `moved { from = a.x  to = a.y }` change in AWS?

<details>
<summary>Show answer</summary>

**Nothing.** It only edits the address in state during the next apply. Without it, a rename is "destroy x, create y".

</details>

**Q4.** `terraform.tfvars` is ignored when you run `terraform plan`. The file is called `prod.tfvars`. Why?

<details>
<summary>Show answer</summary>

Only `terraform.tfvars`, `terraform.tfvars.json` and files ending in `.auto.tfvars` are loaded automatically. Any other name must be passed with `-var-file=prod.tfvars`.

</details>

**Q5.** An output uses `one(aws_db_instance.meta[*].endpoint)`. When `enable_rds` is false, what does it return, and why not `aws_db_instance.meta[0].endpoint`?

<details>
<summary>Show answer</summary>

It returns `null`. With `count = 0` the resource has no instances, so `[*]` is an empty list and `one([])` is `null`. Writing `[0]` would be an *Invalid index* error whenever the toggle is off.

</details>

---

## What's Next? 🚀

You can read the language. Now we build the first real stack, and it is the one that makes everything else safe to run: who is allowed to do what.

👉 **[Post 03: Identity as Code](content/aws-terraform/03-identity-as-code.md)**: Identity Center groups, users and permission sets, plus the practice role from the IAM post, all in Terraform.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
