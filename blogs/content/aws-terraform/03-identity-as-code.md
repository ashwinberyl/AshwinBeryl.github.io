---
title: "Identity as Code: IAM and Identity Center"
date: 2026-11-08
tags: [aws, terraform, iam, identity-center, sso, permission-sets, iam-policy-document, intermediate]
description: Post 3 of the AWS on Terraform series. Groups, users, permission sets and assignments in Terraform, trust policies written as data instead of JSON strings, and a lab that applies the 10-identity stack and proves the result from the CLI.
---

# Who May Do What, in Version Control 🪪

Identity is the first stack because everything after it is gated by it: the roles people sign in with, and the practice role used in the key-policy and bucket-policy labs.

This post turns Posts 02 and 03 of the AWS series into `stacks/10-identity`.

---

## What Terraform Can and Cannot Do Here ⚖️

| Task | Terraform? | Notes |
|---|---|---|
| Enable IAM Identity Center | **No** | Done once by hand (AWS series Post 03, step 1). Terraform **reads** the instance with a data source |
| Require MFA at sign-in | **No** | A console-only setting for the built-in directory |
| Create groups and users | Yes | `aws_identitystore_group`, `aws_identitystore_user` |
| Put users in groups | Yes | `aws_identitystore_group_membership` |
| Define permission sets | Yes | `aws_ssoadmin_permission_set` + policy attachments |
| Assign a group to an account | Yes | `aws_ssoadmin_account_assignment` |
| Set a user's password | **No** | You send the "set your password" email from the console |
| Create the `AWSReservedSSO_*` role | **Not directly** | Identity Center creates it when an assignment exists |
| IAM roles, policies, trust relationships | Yes | `aws_iam_role`, `aws_iam_role_policy` |

![Identity Center resources and the role AWS creates](content/aws-terraform/images/03-identity-resources.svg)

> **Key insight:** The same rule from the AWS series holds: *a permission set is not a role*. In code it is even clearer, because there is **no resource that creates the role**. You declare the assignment, and Identity Center builds the role in the account as a side effect.

---

## Reading the Stack 📖

### Finding the Identity Center instance

```hcl
# stacks/10-identity/main.tf
data "aws_ssoadmin_instances" "this" {}

locals {
  instance_arn      = tolist(data.aws_ssoadmin_instances.this.arns)[0]
  identity_store_id = tolist(data.aws_ssoadmin_instances.this.identity_store_ids)[0]
  account_id        = data.aws_caller_identity.current.account_id

  groups = toset(["platform-admins", "data-scientists"])

  # group name -> permission set name
  assignments = {
    "platform-admins" = "PlatformAdmin"
    "data-scientists" = "DataScientist"
  }

  # one entry per (user, group) pair
  memberships = merge([
    for username, u in var.users : {
      for g in u.groups : "${username}/${g}" => { user = username, group = g }
    }
  ]...)
}
```

`aws_ssoadmin_instances` returns *lists* (an account can have an organization instance and account instances), so we take the first. The `groups`, `assignments` and `memberships` locals are the part to study:

* `groups` is a **set of names**, so groups are created with `for_each`.
* `assignments` maps a group name to a permission-set name, so adding a team is one line.
* `memberships` flattens "each user has a list of groups" into one entry per **(user, group)** pair, keyed `"jim/platform-admins"`. A nested `for`, wrapped in `merge(...)` with the `...` expansion, builds it. With no users, `merge()` of nothing is an empty map, which is why the stack applies cleanly before you add anyone.

### Groups, users, memberships

```hcl
# stacks/10-identity/main.tf
resource "aws_identitystore_group" "this" {
  for_each = local.groups

  identity_store_id = local.identity_store_id
  display_name      = each.key
  description       = "Managed by Terraform"
}

resource "aws_identitystore_user" "this" {
  for_each = var.users

  identity_store_id = local.identity_store_id
  user_name         = each.key
  display_name      = "${each.value.given_name} ${each.value.family_name}"

  name {
    given_name  = each.value.given_name
    family_name = each.value.family_name
  }

  emails {
    value   = each.value.email
    primary = true
  }
}

resource "aws_identitystore_group_membership" "this" {
  for_each = local.memberships

  identity_store_id = local.identity_store_id
  group_id          = aws_identitystore_group.this[each.value.group].group_id
  member_id         = aws_identitystore_user.this[each.value.user].user_id
}
```

The users come from a **variable** with a precise type, so a typo in a field name fails at plan time:

```hcl
# stacks/10-identity/variables.tf
variable "users" {
  description = "Identity Center users. Put real values in terraform.tfvars (git-ignored); see terraform.tfvars.example."
  type = map(object({
    given_name  = string
    family_name = string
    email       = string
    groups      = list(string)
  }))
  default = {}
}
```

Real email addresses do not belong in git, so the values live in `terraform.tfvars`, which `.gitignore` excludes. The repo ships `terraform.tfvars.example`.

### Permission sets and assignments

```hcl
# stacks/10-identity/main.tf
resource "aws_ssoadmin_permission_set" "platform_admin" {
  name             = "PlatformAdmin"
  description      = "Full administration for the platform team"
  instance_arn     = local.instance_arn
  session_duration = var.admin_session_duration
}

resource "aws_ssoadmin_managed_policy_attachment" "platform_admin" {
  instance_arn       = local.instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.platform_admin.arn
  managed_policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

resource "aws_ssoadmin_account_assignment" "this" {
  for_each = local.assignments

  instance_arn       = local.instance_arn
  permission_set_arn = local.permission_set_arns[each.value]

  principal_id   = aws_identitystore_group.this[each.key].group_id
  principal_type = "GROUP"

  target_id   = local.account_id
  target_type = "AWS_ACCOUNT"

  depends_on = [
    aws_ssoadmin_managed_policy_attachment.platform_admin,
    aws_ssoadmin_managed_policy_attachment.data_scientist,
  ]
}
```

A permission set is two resources: the set itself (name, session length) and one **attachment per managed policy**. The assignment carries `depends_on` for both attachments so that the role in the account is provisioned **after** its policies exist.

`session_duration` is an ISO 8601 duration: `PT4H` is four hours, `PT1H` is one.

### Policies as data, not JSON strings

A trust policy is JSON. You can paste a heredoc, but one missing quote becomes a runtime error. `aws_iam_policy_document` is a **data source** that builds the JSON from blocks Terraform can check:

```hcl
# stacks/10-identity/main.tf
data "aws_iam_policy_document" "demo_reader_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${local.account_id}:root"]
    }
  }
}

resource "aws_iam_role" "demo_reader" {
  name                 = "plat-demo-reader"
  description          = "Practice role for IAM, key policy and bucket policy labs"
  assume_role_policy   = data.aws_iam_policy_document.demo_reader_trust.json
  max_session_duration = 3600
}
```

The principal `arn:aws:iam::<account>:root` means "this account" as a *trust boundary*: any identity in the account whose **own** policy allows `sts:AssumeRole` on this role can use it. That's the repair we made in the AWS series after deleting `plat-bootstrap`; here it's correct from the start. The role's permissions are a separate inline policy:

```hcl
# stacks/10-identity/main.tf
data "aws_iam_policy_document" "demo_reader_s3" {
  statement {
    sid       = "ListDataBucket"
    actions   = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::plat-data-${local.account_id}-${var.region}"]
  }

  statement {
    sid       = "ReadDataObjects"
    actions   = ["s3:GetObject"]
    resources = ["arn:aws:s3:::plat-data-${local.account_id}-${var.region}/*"]
  }
}

resource "aws_iam_role_policy" "demo_reader_s3" {
  name   = "plat-s3-read-demo"
  role   = aws_iam_role.demo_reader.id
  policy = data.aws_iam_policy_document.demo_reader_s3.json
}
```

The bucket it points at, `plat-data-<account>-<region>`, **does not exist yet**. IAM policies don't check that a resource exists, so this is fine. Post 07 creates the bucket, and Post 05 adds the key permission whose absence we use for the "S3 allowed, KMS denied" lab.

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "Terraform can bring up Identity Center in a new account." | It can't enable the service. It can only manage objects **inside** an enabled instance. Without it, `aws_ssoadmin_instances` returns an empty list and the plan fails on `[0]`. |
| "A user created in Terraform can sign in." | The user exists but has **no password and no MFA device**. In Identity Center, open the user and use **Reset password**, then **Send an email with instructions**. |
| "I'll delete the permission set and recreate it; same thing." | Existing sessions keep working until they expire, and the new set has a new ARN. More importantly, **if you destroy the assignment you are signed in with, you lock yourself out**. Keep one admin path (break-glass) outside this stack. |
| "`aws_iam_role_policy` makes the role's policies match my code." | It manages only the **policy it names**. A second inline policy added by hand is **invisible** to Terraform and survives every apply. The exclusive resources (`aws_iam_role_policies_exclusive`) change that behaviour. |
| "Changing `session_duration` is instant." | The provider re-provisions the permission set, but **existing sessions keep the old length** until they end. |
| "`for_each` over `var.users` is fine if I rename a user." | The map key is the identity of the instance. Renaming `jim` to `jimmy` **destroys and recreates** the user, with a new user id and lost memberships. Change `given_name` instead. |
| "A permission set for `ViewOnlyAccess` can read S3 objects." | `ViewOnlyAccess` is about *metadata* (list, describe). Reading data (`GetObject`) is not in it. We extend `DataScientist` in later posts. |
| "A trust policy with `root` lets everyone in the account assume the role." | It lets everyone in the account **who is also granted `sts:AssumeRole` by their own policy**. The administrator role has that; most identities don't. |
| "`data.aws_iam_policy_document.json` is deployed." | It's only text. Nothing exists until a resource (`aws_iam_role`, `aws_iam_role_policy`) uses it. |
| "The `AWSReservedSSO_` role name is stable." | It contains a hash suffix. Never hard-code it. Use the permission-set name and look the role up. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| Identity Center enabled with the organization instance | AWS series Post 03 (steps 1 and 2) |
| The state bucket and `scripts/tf.sh` | Post 01 |
| `for_each`, `merge`, `optional` | Post 02 |

| You create here | Used by |
|---|---|
| Groups `platform-admins`, `data-scientists` | Everyone's day-to-day sign-in |
| Permission sets `PlatformAdmin`, `DataScientist` | The `plat-admin` CLI profile, later extended for SageMaker |
| Role `plat-demo-reader` and policy `plat-s3-read-demo` | Post 05 (key access) and Post 07 (the bucket labs) |
| Outputs `demo_reader_role_name`, `sso_instance_arn` | `30-security`, through remote state |

### Console clicks you no longer make

| In the AWS series you... | Here it is |
|---|---|
| **Groups, Create group** | `aws_identitystore_group.this["platform-admins"]` |
| **Users, Add user**, then added to a group | `aws_identitystore_user` + `aws_identitystore_group_membership` |
| **Permission sets, Predefined, AdministratorAccess**, name, 4 hours | `aws_ssoadmin_permission_set` + `aws_ssoadmin_managed_policy_attachment` |
| **AWS accounts, Assign users or groups** | `aws_ssoadmin_account_assignment.this` |
| **IAM, Roles, Create role** with a trust policy, plus an inline policy | `aws_iam_role` + `aws_iam_role_policy` |

---

## Lab: Apply the Identity Stack 🛠️

> **Starting point.** Identity Center is enabled (organization instance) and you can sign in as an admin. If you still have the **hand-built** groups, users and permission sets from the AWS series, creating the same names fails with `ConflictException`. In a lab account, remove them by hand first, **using a different admin path** (not the `PlatformAdmin` session you are about to delete). To keep them instead, bring them under Terraform with `import` (Post 16 shows the workflow). Also delete the hand-built IAM role `plat-demo-reader`.

### 1. Provide your users

```bash
cd stacks/10-identity
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` and put **real email addresses you can read** (a `+jim` alias on one mailbox works). Then go back to the repo root:

```bash
cd ../..
```

### 2. Plan

```bash
scripts/tf.sh 10-identity plan
```

```
Plan: 14 to add, 0 to change, 0 to destroy.
```

Count them: 2 groups, 2 users, 2 memberships, 2 permission sets, 2 policy attachments, 2 account assignments, 1 role, 1 role policy. With no users in `terraform.tfvars` it is **10**.

### 3. Apply

```bash
scripts/tf.sh 10-identity apply
```

Type `yes`. Group and user creation is quick; assignments take a few seconds longer because Identity Center creates the roles in your account.

### 4. Set passwords (the part code can't do)

In the console open **IAM Identity Center, Users, `jim`, Reset password**, choose **Send an email with instructions for resetting the password**. Repeat for `dave`. Sign in as Jim, set a password and register MFA, exactly as in the AWS series.

### 5. Verify with the CLI

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
INSTANCE=$(terraform -chdir=stacks/10-identity output -raw sso_instance_arn)
STORE=$(terraform -chdir=stacks/10-identity output -raw identity_store_id)

aws identitystore list-groups --identity-store-id $STORE --query 'Groups[].DisplayName'
aws identitystore list-users  --identity-store-id $STORE --query 'Users[].UserName'
aws sso-admin list-permission-sets --instance-arn $INSTANCE
```

You should see both group names, both users, and two permission set ARNs. Check the session lengths survived:

```bash
for ps in $(aws sso-admin list-permission-sets --instance-arn $INSTANCE --query 'PermissionSets[]' --output text); do
  aws sso-admin describe-permission-set --instance-arn $INSTANCE --permission-set-arn $ps \
    --query 'PermissionSet.[Name,SessionDuration]' --output text
done
```

```
PlatformAdmin   PT4H
DataScientist   PT1H
```

And the proof that a permission set becomes a role:

```bash
aws iam list-roles --query "Roles[?starts_with(RoleName,'AWSReservedSSO')].RoleName" --output text
```

```
AWSReservedSSO_DataScientist_1a2b3c4d5e6f7a8b   AWSReservedSSO_PlatformAdmin_9f8e7d6c5b4a3210
```

Terraform never mentioned those names.

### 6. Sign in with the CLI

```bash
aws configure sso --profile plat-admin
export AWS_PROFILE=plat-admin
aws sts get-caller-identity --query Arn --output text
```

Answer the prompts as in the AWS series (start URL from **Settings** in Identity Center, region `us-east-1`, role `PlatformAdmin`). You should see `arn:aws:sts::<account>:assumed-role/AWSReservedSSO_PlatformAdmin_.../jim`.

### 7. Use the practice role

```bash
aws sts assume-role \
  --role-arn arn:aws:iam::$ACCOUNT:role/plat-demo-reader \
  --role-session-name tf-check --query AssumedRoleUser.Arn --output text
```

```
arn:aws:sts::123456789012:assumed-role/plat-demo-reader/tf-check
```

Ask IAM what the role may do, without touching any data:

```bash
ROLE=arn:aws:iam::$ACCOUNT:role/plat-demo-reader
OBJ=arn:aws:s3:::plat-data-$ACCOUNT-us-east-1/raw/events.csv
for a in s3:GetObject s3:PutObject; do
  echo -n "$a: "
  aws iam simulate-principal-policy --policy-source-arn $ROLE \
    --action-names $a --resource-arns $OBJ --query 'EvaluationResults[0].EvalDecision' --output text
done
```

```
s3:GetObject: allowed
s3:PutObject: implicitDeny
```

### 8. Cause drift, then a blind spot

**Drift in a managed policy.** In the console open **IAM, Roles, `plat-demo-reader`, `plat-s3-read-demo`, Edit**, and add `"s3:PutObject"` to the `ReadDataObjects` actions. Save, then:

```bash
scripts/tf.sh 10-identity plan
```

```
  # aws_iam_role_policy.demo_reader_s3 will be updated in-place
  ~ resource "aws_iam_role_policy" "demo_reader_s3" {
      ~ policy = jsonencode(...)
    }

Plan: 0 to add, 1 to change, 0 to destroy.
```

Apply to revert it. **Now the blind spot:** add a *second* inline policy by hand (any name, for example `sneaky`) allowing `s3:*`. Run the plan again: `No changes.` Terraform manages the policy it names and ignores the rest. Delete `sneaky` by hand. Exclusive-attachment resources exist for the cases where you want Terraform to be the only source of truth.

### 9. Resources you now have 📦

| Resource | Name | Notes |
|---|---|---|
| Identity Center groups | `platform-admins`, `data-scientists` | |
| Identity Center users | `jim`, `dave` | No password until you send the reset email |
| Permission sets | `PlatformAdmin` (4 h), `DataScientist` (1 h) | |
| Account assignments | 2 | Create the `AWSReservedSSO_*` roles |
| IAM role | `plat-demo-reader` | Trusts the account |
| IAM inline policy | `plat-s3-read-demo` | List and Get on the data bucket |

### Cleanup 🧹

**Do not destroy this stack yet.** Everything from here on is run through the `PlatformAdmin` session this stack creates. Destroying it would also delete the access you are using. It is the **last** stack removed in `make down`.

---

## Quick Quiz 🧠

**Q1.** `terraform plan` on a brand-new account fails with `Invalid index` on `data.aws_ssoadmin_instances.this.arns`. What happened?

<details>
<summary>Show answer</summary>

Identity Center hasn't been enabled, so the data source returns an empty list and `[0]` doesn't exist. Terraform can't enable the service. Enable it once in the console (organization instance), then plan again.

</details>

**Q2.** Why is `memberships` built with a nested `for` and `merge(...)` instead of just `for_each = var.users`?

<details>
<summary>Show answer</summary>

A membership is a **(user, group)** pair, and one user can be in several groups. `for_each = var.users` would give one instance per user. The nested `for` produces one entry per pair, keyed `"jim/platform-admins"`, so adding or removing one group affects only that membership.

</details>

**Q3.** You hand-add an inline policy `extra` to `plat-demo-reader` in the console. `terraform plan` says no changes. Why, and how would you make Terraform notice?

<details>
<summary>Show answer</summary>

`aws_iam_role_policy` manages only the policy named in its `name` argument. Others are unknown to it. To make Terraform the single source of truth, use the exclusive resource `aws_iam_role_policies_exclusive`, which lists every inline policy that should exist and removes the rest.

</details>

**Q4.** You remove `dave` from `var.users` and apply. What is deleted, and what happens if Dave has a live session?

<details>
<summary>Show answer</summary>

His user and his group membership are destroyed. A live session is **not** ended: it keeps its role credentials until they expire, which is why the short `DataScientist` session length (one hour) is the real safety net. Revoke active sessions in Identity Center if you need it sooner.

</details>

**Q5.** Why does the assignment `depends_on` the managed policy attachments, when it never references them?

<details>
<summary>Show answer</summary>

Terraform orders resources only by **references**. The assignment refers to the permission set but not to its attachments, so without `depends_on` it could be created first, and Identity Center would provision a role whose policies arrive later. The explicit dependency ensures the role is provisioned with the policies already in place.

</details>

---

## What's Next? 🚀

People can sign in. Now they need somewhere to run things: a network. It's also where we meet our first **module**, a folder we call instead of copying.

👉 **[Post 04: The Network as Code](content/aws-terraform/04-the-network-as-code.md)**: the two-AZ VPC from the AWS series with a NAT gateway you can switch off, so a forgotten lab costs nothing.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
