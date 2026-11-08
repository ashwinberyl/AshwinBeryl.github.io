---
title: "Security as Code: KMS, Secrets and Security Groups"
date: 2026-11-08
tags: [aws, terraform, kms, secrets-manager, security-groups, remote-state, vpc-endpoints, intermediate]
description: Post 5 of the AWS on Terraform series. The shared encryption key and its key policy, a secret encrypted with it, security groups built from separate rule resources, an interface endpoint behind a switch, and how one stack reads another's outputs with terraform_remote_state.
---

# The Key, the Secret and the Fences 🔐

Three things in the platform exist only to protect other things: the **KMS key** that encrypts data, the **secret** that stores credentials, and the **security groups** that decide who may connect. This post builds them as `stacks/30-security` and, along the way, shows how one stack **reads another stack's outputs**.

---

## The Pieces 🧱

| Piece | Resource | AWS series |
|---|---|---|
| Customer managed key | `aws_kms_key.data` + `aws_kms_alias.data` (`alias/plat-data`) | Post 05 |
| Practice secret | `aws_secretsmanager_secret.demo` + `..._version.demo` | Post 05 |
| Client security group | `aws_security_group.app` (`plat-app-sg`) | Post 05 |
| Endpoint security group | `aws_security_group.vpce` (`plat-vpce-sg`) | Post 05 |
| Interface endpoint | `aws_vpc_endpoint.secretsmanager` (**toggle**) | Post 05 |
| Switch for the key-permission lab | `aws_iam_role_policy.demo_reader_kms` (**toggle**) | Post 06 |

---

## Reading Other Stacks' Outputs 🔗

`30-security` needs the VPC id from `20-network` and the role name from `10-identity`. It reads them from their **state objects** in the S3 bucket:

```hcl
# stacks/30-security/remote_state.tf
locals {
  state_bucket = "plat-tfstate-${data.aws_caller_identity.current.account_id}-${var.region}"
}

data "terraform_remote_state" "identity" {
  backend = "s3"

  config = {
    bucket = local.state_bucket
    key    = "10-identity/terraform.tfstate"
    region = var.region
  }
}

data "terraform_remote_state" "network" {
  backend = "s3"

  config = {
    bucket = local.state_bucket
    key    = "20-network/terraform.tfstate"
    region = var.region
  }
}
```

![How 30-security reads the other stacks](content/aws-terraform/images/05-remote-state.svg)

The bucket name is computed from the account id and region, exactly as `scripts/tf.sh` does, so there's nothing to configure.

| Fact | Consequence |
|---|---|
| Only **root-module outputs** are readable | A stack decides what it publishes. Everything else stays private |
| The reader needs `s3:GetObject` on the state | Our plan role has it. State holds secrets, so be deliberate about who else does |
| The data source reads state **at plan time** | If the upstream stack is not applied, you get `Unable to find remote state` or an unsupported-attribute error |
| It creates a hard dependency on **apply order** | `10 -> 20 -> 30 -> 40` in the Makefile is not decoration |
| Output **names are an API** | Renaming `vpc_id` in 20-network breaks every consumer at their next plan |

The alternatives are a data source that looks the thing up by name or tag (`data "aws_vpc"` filtered on `Name = plat-vpc`), or publishing values to SSM Parameter Store. Lookups decouple stacks from each other's state but depend on names being unique and correct. We use remote state because it is explicit and teaches the idea; Post 16 revisits the trade-off.

---

## Reading the Stack 📖

### The key and its policy

```hcl
# stacks/30-security/main.tf
data "aws_iam_policy_document" "key" {
  statement {
    sid       = "EnableIamPolicies"
    actions   = ["kms:*"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${local.account_id}:root"]
    }
  }
}

resource "aws_kms_key" "data" {
  description             = "Shared encryption key for the Platform Lab"
  enable_key_rotation     = true
  rotation_period_in_days = 365
  deletion_window_in_days = 7
  policy                  = data.aws_iam_policy_document.key.json
}

resource "aws_kms_alias" "data" {
  name          = "alias/plat-data"
  target_key_id = aws_kms_key.data.key_id
}
```

The single policy statement says "the account's root may do anything with this key". It looks like it hands everything to the root user, but its real effect is the opposite of that: it **delegates control to IAM**. Without it, a key policy that names only specific principals would make IAM policies powerless (AWS series Post 05). With it, `kms:Decrypt` can be granted or withheld by ordinary IAM policies, as we do for `plat-demo-reader` below.

`enable_key_rotation` with a 365-day period replaces the "Key rotation" tab click. `deletion_window_in_days = 7` is the **minimum**; a key is never deleted instantly, only scheduled for deletion.

### The secret

```hcl
# stacks/30-security/main.tf
resource "aws_secretsmanager_secret" "demo" {
  name                    = "plat/demo/api-key"
  description             = "Practice secret"
  kms_key_id              = aws_kms_key.data.arn
  recovery_window_in_days = var.secret_recovery_window_days
}

resource "aws_secretsmanager_secret_version" "demo" {
  secret_id     = aws_secretsmanager_secret.demo.id
  secret_string = jsonencode({ api_key = "demo-12345" })
}
```

`recovery_window_in_days = 0` deletes the secret immediately on destroy. For a lab that's convenient; with the default of 30 a destroyed secret is only *scheduled* for deletion and **its name stays reserved**, so recreating it fails. Keep a real recovery window for real secrets.

### Security groups as separate rules

```hcl
# stacks/30-security/main.tf
resource "aws_security_group" "app" {
  name        = "plat-app-sg"
  description = "Clients: shells, EC2, Lambda, tasks"
  vpc_id      = local.vpc_id

  tags = { Name = "plat-app-sg" }
}

resource "aws_security_group" "vpce" {
  name        = "plat-vpce-sg"
  description = "Interface endpoint access"
  vpc_id      = local.vpc_id

  tags = { Name = "plat-vpce-sg" }
}

resource "aws_vpc_security_group_ingress_rule" "vpce_from_app" {
  security_group_id            = aws_security_group.vpce.id
  referenced_security_group_id = aws_security_group.app.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
  description                  = "HTTPS from clients"
}

resource "aws_vpc_security_group_egress_rule" "app_all" {
  security_group_id = aws_security_group.app.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "All outbound"
}
```

Three choices here are worth knowing:

1. **Rules are separate resources.** The older style puts `ingress { }` blocks inside the group. That makes two groups that reference each other a *dependency cycle* (A needs B's id and B needs A's), and it makes the group authoritative over every rule. Separate `aws_vpc_security_group_*_rule` resources avoid both.
2. **The source is a security group, not a CIDR.** `referenced_security_group_id` is the rule from the AWS series, "allow members of `plat-app-sg`".
3. **The explicit egress rule matters.** The console adds an allow-all outbound rule to every new group. **Terraform removes it** and creates the group with *no* egress. A client group with no egress rule can't reach anything, so we declare it.

### The interface endpoint and the lab switches

```hcl
# stacks/30-security/main.tf
resource "aws_vpc_endpoint" "secretsmanager" {
  count = var.enable_secretsmanager_endpoint ? 1 : 0

  vpc_id              = local.vpc_id
  service_name        = "com.amazonaws.${var.region}.secretsmanager"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = [data.terraform_remote_state.network.outputs.private_subnet_ids["a"]]
  security_group_ids  = [aws_security_group.vpce.id]

  tags = { Name = "plat-secretsmanager-vpce" }
}

resource "aws_iam_role_policy" "demo_reader_kms" {
  count = var.grant_demo_reader_decrypt ? 1 : 0

  name   = "plat-kms-decrypt-demo"
  role   = data.terraform_remote_state.identity.outputs.demo_reader_role_name
  policy = data.aws_iam_policy_document.demo_reader_kms.json
}
```

The endpoint is in **one** subnet (`private["a"]`) to halve the cost, as in the AWS series, and `private_dns_enabled = true` is the setting that makes the normal service hostname resolve to a private address.

The last resource is a deliberate switch. It exists only when `grant_demo_reader_decrypt = true` and gives `plat-demo-reader` permission to use the key. Leaving it off is how Post 07 reproduces *"S3 allowed, KMS denied"*; flipping it is the fix.

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "A root principal in the key policy means only root can use the key." | It means "this account", and it enables IAM policies to grant access. Without that statement, IAM alone can't. |
| "Destroying the stack deletes the key." | It **schedules** deletion (7 days minimum). The alias is removed at once, and data encrypted under that key becomes unreadable when the key is finally deleted. Never destroy a key that still protects data you need. |
| "I can recreate the stack and get my data back." | A recreated key has a **new key id**. Objects and secrets encrypted with the old one cannot be decrypted by it. |
| "Marking the secret value `sensitive` keeps it out of state." | The secret string is in state in plain text. For real credentials let the service generate them (RDS does, Post 07) so Terraform never sees them. |
| "Security group changes need a replace." | Rule changes are in-place and instant. Changing the group's `name` or `vpc_id` forces replacement, which fails while anything uses it. |
| "An empty `egress` means default allow-all." | In the console, yes. In Terraform, it means **no outbound traffic at all**. |
| "`terraform_remote_state` is secure because it's an internal data source." | It reads the **entire state file**, and Terraform exposes only the outputs, but the reader's IAM identity can read all of it. Limit who gets `s3:GetObject`. |
| "The endpoint works as soon as it exists." | It needs the endpoint SG to allow 443 from the client, **private DNS** on, and DNS hostnames on in the VPC (the VPC module sets that). Otherwise the name still resolves to a public address. |
| "A single-subnet endpoint is highly available." | It's a single point of failure for that AZ. It matches the lab's cost goal, not production. |
| "Recreating a secret with the same name is instant." | Only with `recovery_window_in_days = 0`. Otherwise the name is blocked until the window passes, or until you run `aws secretsmanager delete-secret --force-delete-without-recovery`. |
| "KMS key rotation changes the key id." | It doesn't. Rotation creates new **backing key material**; the key id, ARN and alias stay the same, and old ciphertext still decrypts. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| `vpc_id`, `private_subnet_ids` | `20-network` (Post 04) |
| `demo_reader_role_name` | `10-identity` (Post 03) |
| The state bucket naming rule | `bootstrap` (Post 01) |

| You create here | Used by |
|---|---|
| Key `alias/plat-data` | S3, DynamoDB, RDS, EFS in `40-data` (Post 07); later SNS, ECS, SageMaker |
| `plat-app-sg` | Every client: RDS and EFS rules (Post 07), EC2, tasks, Lambda |
| `plat-vpce-sg` | This endpoint now, and the SSM / ECR / Logs endpoints later |
| Secret `plat/demo/api-key` | A practice target for IAM and key-policy experiments |
| Outputs `kms_key_arn`, `app_sg_id` | `40-data`, through remote state |

### Console clicks you no longer make

| In the AWS series you... | Here it is |
|---|---|
| **KMS, Create key**, alias `plat-data`, **Key rotation, Enable** | `aws_kms_key.data` + `aws_kms_alias.data` |
| **Secrets Manager, Store a new secret**, choosing the `plat-data` key | `aws_secretsmanager_secret` + `..._version` with `kms_key_id` |
| **EC2, Security Groups, Create**, **Add rule, source = security group** | `aws_security_group` + `aws_vpc_security_group_ingress_rule` |
| **VPC, Endpoints, Create endpoint**, Interface, **Enable DNS name** | `aws_vpc_endpoint.secretsmanager` |

---

## Lab: Apply the Security Stack 🛠️

### 1. Plan and apply

```bash
export AWS_PROFILE=plat-admin AWS_REGION=us-east-1
scripts/tf.sh 30-security plan
```

```
Plan: 8 to add, 0 to change, 0 to destroy.
```

The key, its alias, the secret and its version, two security groups, one ingress rule and one egress rule. The two switches are off.

```bash
scripts/tf.sh 30-security apply
```

If you see `Unable to find remote state`, apply `10-identity` and `20-network` first.

### 2. Verify the key

```bash
aws kms describe-key --key-id alias/plat-data \
  --query 'KeyMetadata.[KeyId,KeyState,KeyManager,KeyUsage]' --output text
aws kms get-key-rotation-status --key-id alias/plat-data
```

```
b1c2d3e4-...   Enabled   CUSTOMER   ENCRYPT_DECRYPT
{
    "KeyRotationEnabled": true,
    "RotationPeriodInDays": 365,
    ...
}
```

Read the policy back and find the single statement:

```bash
aws kms get-key-policy --key-id alias/plat-data --policy-name default --query Policy --output text
```

### 3. Verify the secret

```bash
aws secretsmanager get-secret-value --secret-id plat/demo/api-key --query SecretString --output text
aws secretsmanager describe-secret --secret-id plat/demo/api-key --query KmsKeyId --output text
```

```
{"api_key":"demo-12345"}
arn:aws:kms:us-east-1:123456789012:key/b1c2d3e4-...
```

The second line is the proof that the secret is encrypted with **our** key, not the default `aws/secretsmanager`.

### 4. Verify the security groups

```bash
SG=$(terraform -chdir=stacks/30-security output -raw vpce_sg_id)
aws ec2 describe-security-group-rules --filters Name=group-id,Values=$SG \
  --query 'SecurityGroupRules[].[IsEgress,IpProtocol,FromPort,ReferencedGroupInfo.GroupId]' --output text
```

```
False   tcp   443   sg-0a1b2c3d4e5f67890
```

One inbound rule, and it references the app group's id rather than an address. There is **no outbound rule at all**: Terraform removed the allow-all rule that AWS adds to every new group. The endpoint doesn't need one, because security groups are stateful and replies to a connection a client opened are allowed automatically. The client group is different. It *starts* connections, so we declared its egress:

```bash
APP=$(terraform -chdir=stacks/30-security output -raw app_sg_id)
aws ec2 describe-security-group-rules --filters Name=group-id,Values=$APP \
  --query 'SecurityGroupRules[].[IsEgress,IpProtocol,CidrIpv4]' --output text
```

```
True    -1    0.0.0.0/0
```

That's the rule we declared as `aws_vpc_security_group_egress_rule.app_all`.

### 5. Read another stack's outputs yourself

This is exactly what `terraform_remote_state` does:

```bash
BUCKET=plat-tfstate-$(aws sts get-caller-identity --query Account --output text)-us-east-1
aws s3 cp s3://$BUCKET/20-network/terraform.tfstate - | jq -r '.outputs | keys[]'
```

```
nat_enabled
private_route_table_id
private_subnet_ids
public_subnet_ids
vpc_cidr
vpc_id
```

Those six names are the entire interface that `20-network` offers to the rest of the platform. (If you don't have `jq`, `terraform -chdir=stacks/20-network output` shows the same.)

### 6. Switch on the interface endpoint

```bash
scripts/tf.sh 30-security plan -var enable_secretsmanager_endpoint=true
```

```
Plan: 1 to add, 0 to change, 0 to destroy.
```

```bash
scripts/tf.sh 30-security apply -var enable_secretsmanager_endpoint=true
aws ec2 describe-vpc-endpoints --filters Name=tag:Name,Values=plat-secretsmanager-vpce \
  --query 'VpcEndpoints[0].[State,PrivateDnsEnabled,VpcEndpointType]' --output text
```

```
available   True   Interface
```

> **The endpoint bills by the hour.** Do step 8 before you move on.

**Optional: read the secret from inside the VPC.** Exactly as in AWS series Post 05, open a **CloudShell VPC environment** in `plat-private-a` with `plat-app-sg` (you'll need the NAT gateway on for CloudShell itself: `scripts/tf.sh 20-network apply -var enable_nat=true`). Then:

```bash
getent hosts secretsmanager.us-east-1.amazonaws.com
aws secretsmanager get-secret-value --secret-id plat/demo/api-key --query SecretString --output text
```

The hostname resolves to a `10.20.10.x` address, and the secret is returned. Turn the NAT off when you're done.

### 7. Drift on a security-group rule

Delete the endpoint's inbound rule by hand: **EC2, Security Groups, `plat-vpce-sg`, Inbound rules, Edit, Delete, Save**. From the CloudShell VPC environment the same `get-secret-value` call now **hangs** until it times out, with no error message. That's the symptom of a security group block, as in the AWS series. Now ask Terraform:

```bash
scripts/tf.sh 30-security plan -var enable_secretsmanager_endpoint=true
```

```
  # aws_vpc_security_group_ingress_rule.vpce_from_app will be created
  + resource "aws_vpc_security_group_ingress_rule" "vpce_from_app" {
      + from_port                    = 443
      + referenced_security_group_id = "sg-0a1b2c3d4e5f67890"
      ...
    }

Plan: 1 to add, 0 to change, 0 to destroy.
```

Because each rule is its own resource, a missing rule is a **missing resource**, and Terraform plans to create it. Apply, and the call works again.

### 8. Switch the endpoint off

```bash
scripts/tf.sh 30-security apply
```

```
Plan: 0 to add, 0 to change, 1 to destroy.
```

### 9. Resources you now have 📦

| Resource | Name | Notes |
|---|---|---|
| KMS key + alias | `alias/plat-data` | Rotation on. About $1 per month |
| Secret | `plat/demo/api-key` | About $0.40 per month |
| Security groups | `plat-app-sg`, `plat-vpce-sg` | Free |
| Interface endpoint | `plat-secretsmanager-vpce` | **Only while the switch is on. Hourly cost** |

### Cleanup 🧹

Make sure the endpoint is gone (step 8) and the NAT is off. The key and the secret are cheap, and **everything in `40-data` depends on the key**, so leave them.

---

## Quick Quiz 🧠

**Q1.** Why does the key policy contain a statement for the account root, if the goal is to let specific roles use the key?

<details>
<summary>Show answer</summary>

That statement is what lets **IAM policies** control the key. A key policy is a resource policy that must itself allow access, or allow IAM to. With it, a role gets `kms:Decrypt` by having an IAM policy that grants it, and loses it when that policy is removed. Without it, only principals named in the key policy could ever use the key.

</details>

**Q2.** You `terraform destroy` the security stack, then apply it again. Your S3 objects, encrypted with the old key, can't be read. Why?

<details>
<summary>Show answer</summary>

The new key has a different **key id** and different key material. The alias `plat-data` now points at it, but the old objects' data keys were wrapped by the old key, which is deleted after its 7-day window. Never destroy a key while data encrypted with it still matters, and consider `prevent_destroy` for real environments.

</details>

**Q3.** A new security group made with Terraform can't reach the internet through the NAT, though the same group made in the console could. What's missing?

<details>
<summary>Show answer</summary>

An **egress rule**. The console adds "allow all outbound" automatically. Terraform removes that default and creates the group with no outbound rule, so you must declare one (`aws_vpc_security_group_egress_rule`).

</details>

**Q4.** Why are the endpoint's rules separate `aws_vpc_security_group_ingress_rule` resources instead of an `ingress` block?

<details>
<summary>Show answer</summary>

Inline rules make the group authoritative for all its rules, and two groups referencing each other create a dependency cycle. With separate rules, each group is created first (no references), and the rules, which reference groups by id, are created after. A deleted rule also shows up as a missing resource instead of silent drift.

</details>

**Q5.** `20-network` renames its output `vpc_id` to `network_id`. What breaks, and when do you find out?

<details>
<summary>Show answer</summary>

Every stack that reads `outputs.vpc_id` through `terraform_remote_state` (30 and 40) fails at its **next plan** with an unsupported-attribute error. Nothing in AWS is affected. That's the cost of remote-state coupling: output names form an interface, so change them like an API (add the new name, migrate consumers, then remove the old).

</details>

---

## What's Next? 🚀

We've now written the same patterns several times: a bucket here, a tag convention there. The next post turns repetition into a **module**, designs its interface properly, and shows the refactor that moves existing resources into it without recreating anything.

👉 **[Post 06: Modules: One Bucket Definition, Many Buckets](content/aws-terraform/06-modules.md)**: the S3 module in depth, called three times in a lab.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
