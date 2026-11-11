---
title: "Quality Gates: terraform test, tflint, trivy and check blocks"
date: 2026-11-11
tags: [aws, terraform, testing, tflint, trivy, pre-commit, validation, preconditions, check-blocks, intermediate]
description: Post 17 of the AWS on Terraform series. Seven kinds of check from formatting to post-apply checks, tests that run against a mocked provider with no AWS account, scanners for lint and insecure settings, validation and preconditions that fail at plan time, and pre-commit to run the cheap ones for free.
---

# Keeping the Code Honest ✅

Thirteen stacks, two modules, a lab per post: the Terraform code is now large enough to break in ways nobody notices. A typo in a variable, a security group opened to the world, a module default flipped: each is a small diff and a large problem.

This post is the set of checks the repository already contains, why each exists, and what it can and cannot see. The trick is not to run more checks but to catch each mistake at the **cheapest** one that can.

---

## The Pieces 🧱

| Gate | Tool | Needs AWS? | Catches |
|---|---|---|---|
| Format | `terraform fmt -check` | No | Style drift |
| Validate | `terraform validate` | No | Syntax, wrong types, unknown references |
| Lint | `tflint` | No | Unused declarations, deprecated syntax, missing version constraints, invalid AWS values |
| Security scan | `trivy config` | No | Insecure settings: open ports, unencrypted storage |
| Tests | `terraform test` | **No** (mocked provider) | Module behaviour |
| Input checks | `validation`, `precondition`, `postcondition` | At plan time | Bad inputs, impossible combinations |
| Runtime assertions | `check` blocks | Yes | Things that should be true of the running system |
| Run all the cheap ones | `pre-commit`, GitHub Actions | | |

![Quality gates](content/aws-terraform/images/17-quality-gates.svg)

---

## Reading the Tooling 📖

### Formatting and validation

`terraform fmt` rewrites files into the canonical layout; with `-check` it only reports. `terraform validate` loads the configuration without contacting AWS and checks that everything is well-formed. The CI workflow runs both for **every** directory in a matrix:

```yaml
# .github/workflows/terraform.yml
name: terraform

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  checks:
    name: fmt + validate (${{ matrix.dir }})
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        dir:
          - bootstrap
          - modules/s3-bucket
          - modules/vpc
          - labs/02-language
          - labs/06-modules
          - labs/16-state
          - stacks/10-identity
          - stacks/20-network
          - stacks/30-security
          - stacks/40-data
          - stacks/50-ec2
          - stacks/52-ecs
          - stacks/55-eks
          - stacks/60-events
          - stacks/70-ml
          - stacks/80-delivery
          - stacks/90-observe
          - stacks/95-cost
    steps:
      - uses: actions/checkout@v4

      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: 1.10.5

      - name: fmt
        run: terraform fmt -check -recursive -diff ${{ matrix.dir }}

      - name: init (no backend)
        run: terraform -chdir=${{ matrix.dir }} init -backend=false -input=false

      - name: validate
        run: terraform -chdir=${{ matrix.dir }} validate
```

Two points: `init -backend=false` lets `validate` run with no state and no credentials, and `fail-fast: false` means one broken stack doesn't hide the status of the others.

### tflint

```hcl
# .tflint.hcl
plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

plugin "aws" {
  enabled = true
  version = "0.38.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}

# Every module and stack declares its own provider requirements in versions.tf.
rule "terraform_required_version" {
  enabled = true
}

rule "terraform_required_providers" {
  enabled = true
}
```

The `terraform` plugin with the `recommended` preset catches Terraform-level mistakes: unused variables and locals, deprecated syntax, missing `required_version`. The `aws` plugin knows AWS-specific facts, such as valid instance types, and flags values that would be rejected at apply. The two extra rules are explicit because they are the most valuable: **every directory declares its Terraform and provider versions**, so the same code behaves the same everywhere.

### trivy

```hcl
# .trivyignore
# Every ignore needs a reason and an owner. Review this file when you touch the code it covers.

# bootstrap: the apply role uses AdministratorAccess until the scoped policy is switched on (Post 18).
AWS-0057

# Public load balancer on purpose: plat-alb is the internet entry point of the lab API.
AWS-0053

# The lab allows all outbound traffic from application security groups.
AWS-0104
```

`trivy config` scans the code for insecure settings against a large rule set, without needing AWS. Our run fails on `HIGH` and `CRITICAL`. The three ignores are the interesting part: **each has a reason**. The apply role has broad rights until the scoped policy is switched on (Post 18), the ALB is public on purpose, and the lab allows all outbound traffic. A scanner whose findings are ignored without explanation teaches people to ignore the scanner.

### Tests that need no AWS account

```hcl
# modules/s3-bucket/tests/defaults.tftest.hcl
# terraform -chdir=modules/s3-bucket test
# Mock provider: no AWS account, no credentials, no cost. Only plans are checked.
mock_provider "aws" {}

variables {
  name = "plat-test-bucket"
}

run "secure_defaults" {
  command = plan

  assert {
    condition     = aws_s3_bucket.this.bucket == "plat-test-bucket"
    error_message = "The bucket must use the name that was passed in."
  }

  assert {
    condition     = length(aws_s3_bucket_versioning.this) == 1
    error_message = "Versioning must be on by default."
  }

  assert {
    condition     = length(aws_s3_bucket_lifecycle_configuration.this) == 0
    error_message = "No lifecycle configuration unless rules are given."
  }

  assert {
    condition     = aws_s3_bucket_public_access_block.this.block_public_acls && aws_s3_bucket_public_access_block.this.block_public_policy && aws_s3_bucket_public_access_block.this.ignore_public_acls && aws_s3_bucket_public_access_block.this.restrict_public_buckets
    error_message = "All four public access block settings must be on."
  }

  assert {
    condition     = !aws_s3_bucket.this.force_destroy
    error_message = "force_destroy must default to false."
  }
}

run "versioning_can_be_turned_off" {
  command = plan

  variables {
    versioning = false
  }

  assert {
    condition     = length(aws_s3_bucket_versioning.this) == 0
    error_message = "versioning = false must not create a versioning resource."
  }
}

run "lifecycle_and_prefixes" {
  command = plan

  variables {
    prefixes = ["raw/", "processed/"]
    lifecycle_rules = [
      { id = "a", noncurrent_expiration_days = 30 },
      { id = "b", prefix = "raw/", transition_days = 30 },
    ]
  }

  assert {
    condition     = length(aws_s3_bucket_lifecycle_configuration.this) == 1
    error_message = "Rules must create exactly one lifecycle configuration."
  }

  assert {
    condition     = length(aws_s3_object.prefix) == 2
    error_message = "One marker object per prefix."
  }
}
```

* **`mock_provider "aws" {}`** replaces the real provider with a fake that returns generated values. Nothing touches AWS, so the test needs no credentials and costs nothing.
* **`command = plan`** evaluates the configuration without creating anything; the assertions inspect what the plan would create.
* Each `run` block has its own variables, so one file checks the secure defaults, the off-switch for versioning, and the lifecycle and prefix behaviour.

The VPC module's test adds two kinds of case:

```hcl
# modules/vpc/tests/network.tftest.hcl
# terraform -chdir=modules/vpc test
mock_provider "aws" {}

variables {
  azs                  = ["us-east-1a", "us-east-1b"]
  public_subnet_cidrs  = ["10.20.0.0/24", "10.20.1.0/24"]
  private_subnet_cidrs = ["10.20.10.0/24", "10.20.11.0/24"]
}

run "no_nat_by_default" {
  command = plan

  assert {
    condition     = length(aws_nat_gateway.this) == 0 && length(aws_eip.nat) == 0 && length(aws_route.private_nat) == 0
    error_message = "The NAT gateway, its address and its route must not exist unless enable_nat is true."
  }

  assert {
    condition     = length(aws_subnet.public) == 2 && length(aws_subnet.private) == 2
    error_message = "Two public and two private subnets."
  }

  assert {
    condition     = contains(keys(aws_subnet.private), "a") && contains(keys(aws_subnet.private), "b")
    error_message = "Subnets must be keyed by AZ letter."
  }

  assert {
    condition     = length(aws_vpc_endpoint.gateway) == 2
    error_message = "S3 and DynamoDB gateway endpoints by default."
  }
}

run "nat_on" {
  command = plan

  variables {
    enable_nat = true
  }

  assert {
    condition     = length(aws_nat_gateway.this) == 1 && length(aws_eip.nat) == 1 && length(aws_route.private_nat) == 1
    error_message = "enable_nat = true creates one NAT gateway, one address and one route."
  }
}

run "cidr_count_must_match_azs" {
  command = plan

  variables {
    public_subnet_cidrs = ["10.20.0.0/24"]
  }

  expect_failures = [var.public_subnet_cidrs]
}

run "unsupported_endpoint_rejected" {
  command = plan

  variables {
    gateway_endpoints = ["s3", "kinesis"]
  }

  expect_failures = [var.gateway_endpoints]
}
```

`nat_on` checks the **count toggle** from Post 04: switching `enable_nat` on creates exactly one gateway, one address and one route. The last two runs use **`expect_failures`**: they pass **only when the named variable's validation fails**. A test that proves the guard rail works is a stronger statement than a test that proves the happy path works.

What tests **cannot** see: whether AWS accepts the values. A mock returns whatever you ask. Tests cover logic, not integration.

### Validation, preconditions and postconditions

These live in the code itself and run on every plan, for everyone:

```hcl
# modules/vpc/variables.tf
variable "public_subnet_cidrs" {
  description = "One CIDR per AZ, same order as azs."
  type        = list(string)

  validation {
    condition     = length(var.public_subnet_cidrs) == length(var.azs)
    error_message = "public_subnet_cidrs needs exactly one CIDR for each entry in azs."
  }
}

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

A `validation` block checks a **variable** before anything else happens. A `precondition` (inside a resource's `lifecycle`) checks a **relationship** between values:

```hcl
# modules/vpc/main.tf
resource "aws_vpc" "this" {
  cidr_block           = var.cidr_block
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = merge(var.tags, { Name = "${var.name}-vpc" })

  lifecycle {
    precondition {
      condition     = length(var.azs) == length(var.public_subnet_cidrs) && length(var.azs) == length(var.private_subnet_cidrs)
      error_message = "Give exactly one public and one private CIDR per AZ."
    }
  }
}
```

And Post 12 used one to catch a cross-stack impossibility: `enable_deploy_stage = true` while the ECS service doesn't exist. A **postcondition** is the mirror image: it asserts something about a resource **after** it is created, such as that an allocated address isn't empty, and fails the apply if not.

### check blocks: assertions about the running system

```hcl
# stacks/20-network/main.tf
check "vpc_dns_hostnames" {
  data "aws_vpc" "this" {
    id = module.vpc.vpc_id
  }

  assert {
    condition     = data.aws_vpc.this.enable_dns_hostnames
    error_message = "DNS hostnames are off in the VPC. Interface endpoints with private DNS will not resolve."
  }
}
```

A `check` block with a scoped data source reads the **real** VPC and asserts a property. It runs at the end of every plan and apply, and its failure is a **warning**, not an error: it doesn't stop anything, but it appears in the output every time. That makes it right for conditions that depend on the world rather than on your code: "DNS hostnames are on", "the certificate isn't about to expire", "the endpoint answers". Interface endpoints with private DNS (Post 05) silently misbehave without that setting, and the setting can be changed by hand, so the check watches for it.

### Running them without thinking: pre-commit and CI

```yaml
# .pre-commit-config.yaml
# pip install pre-commit && pre-commit install
repos:
  - repo: https://github.com/antonbabenko/pre-commit-terraform
    rev: v1.96.2
    hooks:
      - id: terraform_fmt
      - id: terraform_validate
      - id: terraform_tflint
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: end-of-file-fixer
      - id: trailing-whitespace
      - id: check-added-large-files
```

`pre-commit` runs format, validate and tflint on every commit, on your computer, before the code leaves it. The GitHub Actions workflows then run the same tools again on every pull request, because a local hook can be skipped and the pipeline can't.

```yaml
# .github/workflows/quality.yml
name: quality

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  tflint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: terraform-linters/setup-tflint@v4
        with:
          tflint_version: v0.53.0
      - run: tflint --init
        env:
          GITHUB_TOKEN: ${{ github.token }}
      - run: tflint --recursive --format compact
        env:
          GITHUB_TOKEN: ${{ github.token }}

  security-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: aquasecurity/trivy-action@0.28.0
        with:
          scan-type: config
          scan-ref: .
          severity: HIGH,CRITICAL
          exit-code: "1"
          trivyignores: .trivyignore

  module-tests:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        module: [modules/s3-bucket, modules/vpc]
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: 1.10.5
      - run: terraform -chdir=${{ matrix.module }} init -backend=false -input=false
      - run: terraform -chdir=${{ matrix.module }} test
```

Three independent jobs: lint, security scan, and module tests (a matrix over the two modules). Independent means that a failing scan doesn't prevent you from seeing that the tests passed.

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "`validate` proves the configuration works." | It proves it is **well-formed**. AWS can still reject every value in it. |
| "A passing test means the module works in AWS." | With a mock provider it means the **logic** is right. Integration is only proven by an apply. |
| "`terraform test` creates real resources." | Only with `command = apply` and a real provider. Plan-mode tests with a mock create nothing. |
| "Scanner findings are bugs to fix." | Some are intentional (a public load balancer). Record them with a reason, never silently. |
| "tflint and `validate` find the same things." | `validate` knows Terraform's rules; tflint knows style and provider-specific values. |
| "A failed `check` stops the apply." | It is a warning. Use a `precondition` or `postcondition` to block. |
| "A `validation` can only look at its own variable." | Before Terraform 1.9 that was true. Now it can reference others: the VPC module compares `public_subnet_cidrs` with `var.azs`. Relationships between resources still need a `precondition`. |
| "`expect_failures` hides errors." | It **requires** the failure. If validation stops failing, the test fails. |
| "Pre-commit replaces CI." | It runs on one computer, and can be bypassed with `--no-verify`. CI is the enforced copy. |
| "I need every check on every commit." | Put the cheap, local ones in pre-commit and the credentialed ones in CI. |
| "Unused variables are harmless." | They mislead readers about what the module accepts. tflint flags them. |
| "`.trivyignore` is a place to silence noise." | It's a ledger of accepted risk, and each entry must say who accepted what and why. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| Module validations and the `enable_nat` toggle | Posts 04 and 06 |
| The `check` block | `20-network` (Post 04) |
| The precondition in the pipeline | `80-delivery` (Post 12) |

| You create here | Used by |
|---|---|
| `quality.yml`, `terraform.yml` | Every pull request, and the plan workflow in Post 18 |
| `.trivyignore` | The scan; reviewed whenever the code it covers changes |

### Console clicks you no longer make

There is no console version of a test. The nearest habit is **looking at what you made and hoping**; these checks replace it with something repeatable.

| Habit | Replaced by |
|---|---|
| Click through the console to see if it looks right | `terraform test`, `check` blocks, `scripts/verify.sh` |
| Ask a colleague to look for a mistake in the diff | `tflint`, `trivy`, `plan` in CI |
| Read the security group page for open ports | `trivy config` |

---

## Lab: Break Each Gate on Purpose 🛠️

You need `tflint` and `trivy` installed (`tflint --version`, `trivy --version`). Everything else is already there.

### 1. The tests

```bash
make test
```

```
modules/s3-bucket/tests/defaults.tftest.hcl... in progress
  run "secure_defaults"... pass
  run "versioning_can_be_turned_off"... pass
  run "lifecycle_and_prefixes"... pass
modules/s3-bucket/tests/defaults.tftest.hcl... tearing down
modules/s3-bucket/tests/defaults.tftest.hcl... pass

Success! 3 passed, 0 failed.
modules/vpc/tests/network.tftest.hcl... in progress
  run "no_nat_by_default"... pass
  run "nat_on"... pass
  run "cidr_count_must_match_azs"... pass
  run "unsupported_endpoint_rejected"... pass
modules/vpc/tests/network.tftest.hcl... tearing down
modules/vpc/tests/network.tftest.hcl... pass

Success! 4 passed, 0 failed.
```

No AWS credentials were used. You can run this on a plane.

### 2. Break a module default and watch the test catch it

In `modules/s3-bucket/variables.tf`, change the default of `versioning` from `true` to `false`:

```bash
make test
```

```
  run "secure_defaults"... fail
╷
│ Error: Test assertion failed
│
│   on modules/s3-bucket/tests/defaults.tftest.hcl line 20, in run "secure_defaults":
│   20:     condition     = length(aws_s3_bucket_versioning.this) == 1
│     ├────────────────
│     │ aws_s3_bucket_versioning.this is empty tuple
│
│ Versioning must be on by default.
╵
```

Someone "tidying" a default would have silently turned off versioning in every caller (the state bucket protections included). The test name and message tell you what rule was broken. Revert the change.

### 3. An unused variable and tflint

Add to `stacks/50-ec2/variables.tf`:

```hcl
variable "unused_demo" {
  type    = string
  default = "x"
}
```

```bash
tflint --init
tflint --chdir=stacks/50-ec2
```

```
1 issue(s) found:

Warning: variable "unused_demo" is declared but not used (terraform_unused_declarations)

  on variables.tf line 31:
  31: variable "unused_demo" {
```

Remove it.

### 4. An insecure setting and trivy

Create `stacks/50-ec2/scan_demo.tf`:

```hcl
resource "aws_security_group" "scan_demo" {
  name   = "scan-demo"
  vpc_id = local.vpc_id

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
```

```bash
trivy config --severity HIGH,CRITICAL --ignorefile .trivyignore stacks/50-ec2
```

```
scan_demo.tf (terraform)
========================
Tests: 1 (SUCCESSES: 0, FAILURES: 1)
Failures: 1 (HIGH: 0, CRITICAL: 1)

CRITICAL: Security group rule allows unrestricted ingress from any IP address.
  AVD-AWS-0107
```

The exact rule text depends on the trivy version. Delete the file. Notice what you did **not** need: an AWS account, a plan, an apply.

### 5. A validation failure at plan time

```bash
scripts/tf.sh 20-network plan -var 'public_subnet_cidrs=["10.20.0.0/24"]'
```

```
Error: Invalid value for variable

  on ../../modules/vpc/variables.tf line 21, in variable "public_subnet_cidrs":
  public_subnet_cidrs needs exactly one CIDR for each entry in azs.

This was checked by the validation rule at ../../modules/vpc/variables.tf:21,3-13.
```

The guard rail lives in the **module**, so every caller gets it, and the message says what to fix. It fires before any provider call; the module's `cidr_count_must_match_azs` test from step 1 asserts the same thing without AWS.

### 6. A check block that sees something the code doesn't

Turn off DNS hostnames in the VPC by hand:

```bash
VPC=$(terraform -chdir=stacks/20-network output -raw vpc_id)
aws ec2 modify-vpc-attribute --vpc-id $VPC --no-enable-dns-hostnames
scripts/tf.sh 20-network plan
```

```
  # module.vpc.aws_vpc.this will be updated in-place
  ~ enable_dns_hostnames = false -> true

Warning: Check block assertion failed

  on main.tf line 19, in check "vpc_dns_hostnames":
  DNS hostnames are off in the VPC. Interface endpoints with private DNS will not resolve.
```

Two signals for one change: the **plan** shows the drift, and the **check** states why it matters. Apply to restore it. Even on a stack where drift detection was disabled, the check would still warn.

### 7. Run it all the way a teammate would

```bash
pip install pre-commit && pre-commit install
git commit --allow-empty -m "try the hooks"
```

```
Terraform fmt............................................................Passed
Terraform validate.......................................................Passed
Terraform validate with tflint...........................................Passed
Fix End of Files.........................................................Passed
Trim Trailing Whitespace.................................................Passed
Check for added large files..............................................Passed
```

### 8. Resources you now have 📦

Nothing in AWS: this post created checks, not infrastructure.

| Artifact | Where | Notes |
|---|---|---|
| Tests | `modules/*/tests/` | Run with `make test` |
| Lint config | `.tflint.hcl` | |
| Scan ledger | `.trivyignore` | Every entry has a reason |
| Hooks | `.pre-commit-config.yaml` | |
| Workflows | `.github/workflows/terraform.yml`, `quality.yml` | |

### Cleanup 🧹

Revert any edits from the steps above (`git checkout -- .` and delete `stacks/50-ec2/scan_demo.tf` if it still exists).

---

## Quick Quiz 🧠

**Q1.** Your test passes with a mock provider, but `apply` fails because the instance type doesn't exist in the region. Which gate could have caught it earlier?

<details>
<summary>Show answer</summary>

**tflint's AWS plugin**, which knows valid instance types, or a variable `validation`. A mock accepts any value, so tests can't know AWS's rules.

</details>

**Q2.** What does `expect_failures = [var.gateway_endpoints]` assert?

<details>
<summary>Show answer</summary>

That the run **fails because of that variable's validation**. If the validation stops rejecting bad input, the test fails, so the test protects the guard rail itself.

</details>

**Q3.** When would you use a `check` block instead of a `precondition`?

<details>
<summary>Show answer</summary>

For conditions about the **running world** that shouldn't block a change, such as "DNS hostnames are on". A failed check warns; a failed precondition stops the plan.

</details>

**Q4.** Why is every `.trivyignore` entry accompanied by a comment?

<details>
<summary>Show answer</summary>

An ignore is **accepted risk**. Without a reason and an owner the next person can't tell a deliberate decision from a silenced problem, and the scanner loses its value.

</details>

**Q5.** Pre-commit already runs fmt and validate. Why run them in CI too?

<details>
<summary>Show answer</summary>

Local hooks can be skipped (`--no-verify`) or never installed. CI is the **enforced** copy that every change must pass.

</details>

---

## What's Next? 🚀

Checks run on your computer and on a pull request. The last piece is to let a pipeline do the planning and applying, with no long-lived keys, two roles and a human approval.

👉 [Post 18: The Terraform Pipeline: Plan on Pull Request, Apply on Merge](content/aws-terraform/18-terraform-pipeline.md)

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
