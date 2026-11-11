---
title: "The Network as Code: A VPC Module"
date: 2026-11-08
tags: [aws, terraform, vpc, networking, modules, nat-gateway, vpc-endpoints, for-each, intermediate]
description: Post 4 of the AWS on Terraform series. The two-AZ VPC from the AWS series as a reusable module, a NAT gateway behind a switch so a forgotten lab costs nothing, and a lab that reads routes back from AWS and shows why separate route resources have a blind spot.
---

# The Same Network, Written Once 🌐

In the AWS series you spent a whole lab creating one VPC, four subnets, two route tables, an internet gateway, a NAT gateway and two endpoints, by hand, in the right order. This post is the same network as about 150 lines of Terraform, which you can apply in a minute and tear down in another.

It is also where we first meet a **module**: a folder of Terraform that you call with inputs and get outputs back from. Post 06 studies modules properly; here we just use one.

---

## The Design in One Table 📐

Same plan as AWS series Post 04, same names:

| Subnet | AZ | CIDR | Holds |
|---|---|---|---|
| `plat-public-a` | `us-east-1a` | `10.20.0.0/24` | NAT gateway, load balancers |
| `plat-public-b` | `us-east-1b` | `10.20.1.0/24` | Load balancers |
| `plat-private-a` | `us-east-1a` | `10.20.10.0/24` | App workloads, databases |
| `plat-private-b` | `us-east-1b` | `10.20.11.0/24` | App workloads, databases |

If you ran `cidrsubnet("10.20.0.0/16", 8, 10)` in Post 02's console lab you already know where `10.20.10.0/24` comes from: the 11th `/24` inside the `/16`.

What changes when it becomes code:

| Decision | Why |
|---|---|
| **The NAT gateway is a toggle** (`enable_nat`, default `false`) | A NAT gateway bills every hour it exists. Code defaults to the cheap state, and you ask for the expensive one |
| **Subnets are keyed by AZ letter** (`a`, `b`) | `for_each` addresses are `aws_subnet.private["a"]`. Reordering the AZ list can't shuffle them (Post 02) |
| **Routes are separate resources** (`aws_route`), not `route { }` blocks | Lets the NAT route appear and disappear without rewriting the route table |
| **Gateway endpoints are a set** (`s3`, `dynamodb`) | Adding a third is a one-word change |
| **One private route table**, as in the lab | Cheaper and simpler. Production uses one per AZ, each with its own NAT |
| **No `map_public_ip_on_launch`** | Public IPs are assigned deliberately per resource, not by default |

![The network stack and the vpc module](content/aws-terraform/images/04-module-boundary.svg)

---

## Reading the Module 📖

### Inputs

```hcl
# modules/vpc/variables.tf
variable "azs" {
  description = "Availability zones, in order."
  type        = list(string)
}

variable "enable_nat" {
  description = "Create one NAT gateway (in the first AZ) and route private subnets through it. Costs money every hour."
  type        = bool
  default     = false
}

variable "public_subnet_cidrs" {
  description = "One CIDR per AZ, same order as azs."
  type        = list(string)

  validation {
    condition     = length(var.public_subnet_cidrs) == length(var.azs)
    error_message = "public_subnet_cidrs needs exactly one CIDR for each entry in azs."
  }
}
```

The validation on the CIDR lists uses another variable (`azs`) in its condition. That's allowed since Terraform 1.9, and it turns a mismatch into a clear error at the start of the plan.

### Subnets, keyed by AZ letter

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

resource "aws_subnet" "public" {
  for_each = local.public

  vpc_id                  = aws_vpc.this.id
  availability_zone       = each.value.az
  cidr_block              = each.value.cidr
  map_public_ip_on_launch = false

  tags = merge(var.tags, {
    Name                     = "${var.name}-public-${each.key}"
    tier                     = "public"
    "kubernetes.io/role/elb" = "1"
  })
}

resource "aws_subnet" "private" {
  for_each = local.private

  vpc_id            = aws_vpc.this.id
  availability_zone = each.value.az
  cidr_block        = each.value.cidr

  tags = merge(var.tags, {
    Name                              = "${var.name}-private-${each.key}"
    tier                              = "private"
    "kubernetes.io/role/internal-elb" = "1"
  })
}
```

Every `Name` tag follows `plat-<tier>-<letter>`, so the console looks exactly like the one you built by hand. `merge(var.tags, {...})` adds the module's own tags on top of whatever the caller passed; the provider's `default_tags` (`project`, `managed_by`, `stack`) are added to all of them separately.

### Routing and the NAT switch

```hcl
# modules/vpc/main.tf
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name}-private-rt" })
}

resource "aws_nat_gateway" "this" {
  count = var.enable_nat ? 1 : 0

  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.public[local.first_az].id

  tags = merge(var.tags, { Name = "${var.name}-nat-${local.first_az}" })

  depends_on = [aws_internet_gateway.this]
}

resource "aws_route" "private_nat" {
  count = var.enable_nat ? 1 : 0

  route_table_id         = aws_route_table.private.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this[0].id
}
```

With `enable_nat = false` the three NAT resources have `count = 0`, so they don't exist, and the private route table has no `0.0.0.0/0` route. Private subnets then reach AWS only through the gateway endpoints and anything else times out. That's the correct, free default.

### Gateway endpoints

```hcl
# modules/vpc/main.tf
resource "aws_vpc_endpoint" "gateway" {
  for_each = var.gateway_endpoints

  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${data.aws_region.current.region}.${each.key}"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  tags = merge(var.tags, { Name = "${var.name}-${local.endpoint_names[each.key]}" })
}
```

A gateway endpoint isn't a network interface. It adds a route to the route table (a **prefix list** for the service) that sends S3 or DynamoDB traffic straight to the service over AWS's network. They're free, which is why we always create them.

### How the stack calls it

```hcl
# stacks/20-network/main.tf
module "vpc" {
  source = "../../modules/vpc"

  name                 = "plat"
  cidr_block           = var.vpc_cidr
  azs                  = var.azs
  public_subnet_cidrs  = var.public_subnet_cidrs
  private_subnet_cidrs = var.private_subnet_cidrs
  enable_nat           = var.enable_nat
}
```

That's the whole stack: one module call. The outputs of the module are re-exported so later stacks can read them:

```hcl
# stacks/20-network/outputs.tf
output "private_subnet_ids" {
  value = module.vpc.private_subnet_ids
}
```

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "Setting `enable_nat = true` on the command line keeps it on." | A `-var` lasts for that one command. The next plain `apply` sees the default (`false`) and **plans to destroy the NAT**. Put long-lived choices in a `terraform.tfvars` file. |
| "Terraform will remove a route someone added by hand." | Only if the route table uses inline `route { }` blocks. With separate `aws_route` resources, Terraform manages **only the routes it declares** and ignores the rest. See the lab. |
| "Changing `vpc_cidr` updates the VPC." | The primary CIDR can't be changed. Terraform plans to **replace the VPC**, and every subnet, endpoint and attached resource with it. Plan generously, as in the AWS series. |
| "Destroying the NAT gateway releases its Elastic IP automatically." | Terraform destroys the NAT, then the EIP, in dependency order. A NAT deleted by hand leaves the EIP allocated and **billed** until released. |
| "`terraform destroy` on the network will always work." | A VPC can't be deleted while network interfaces remain in it (an interface endpoint, a load balancer, a Lambda ENI created by another stack). Destroy the stacks that use it first. That is why `make down` runs in reverse order. |
| "Public subnets are public because of their name." | Only because of the **route** `0.0.0.0/0 -> igw`. Name and tag are labels. |
| "Hard-coding `us-east-1a` is portable." | AZ **names** map to different physical zones per account, and not every region has every letter. If you change region, change `azs` as well. |
| "A module's resources show up under one name in state." | They appear with a path: `module.vpc.aws_subnet.private["a"]`. Moving code into or out of a module changes addresses, so use `moved` blocks. |
| "`default_tags` and a resource's own `tags` conflict." | They merge. A tag set on the resource wins for that key. The combined result is the read-only attribute `tags_all`. |
| "Interface endpoints are included here." | They aren't. They need a security group, so the Secrets Manager endpoint lives in `30-security` (Post 05). |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| The state bucket, `scripts/tf.sh` | Post 01 |
| `for_each`, `count` toggles, `merge`, validation | Post 02 |
| The `PlatformAdmin` session | Post 03 |

| You create here | Used by |
|---|---|
| `plat-vpc` and four subnets | **Everything**: data (07), compute (08 to 10), events, ML |
| `plat-private-rt` and its NAT toggle | Image pulls, package installs, the SSM agent |
| S3 and DynamoDB gateway endpoints | Lambda and ECS reaching data without NAT |
| Outputs `vpc_id`, `private_subnet_ids`, `public_subnet_ids` | Every later stack through `terraform_remote_state` |

### Console clicks you no longer make

| In the AWS series you... | Here it is |
|---|---|
| **Create VPC**, name, CIDR | `aws_vpc.this` |
| Created four subnets, one at a time | `aws_subnet.public`, `aws_subnet.private` (`for_each`) |
| **Create internet gateway**, **Attach** | `aws_internet_gateway.this` (attached by `vpc_id`) |
| Created two route tables, **Edit routes**, **Subnet associations** | `aws_route_table.*`, `aws_route.*`, `aws_route_table_association.*` |
| Allocated an Elastic IP, **Create NAT gateway** | `aws_eip.nat`, `aws_nat_gateway.this` |
| **Create endpoint**, Gateway type, tick the route table | `aws_vpc_endpoint.gateway` |

---

## Lab: Apply the Network 🛠️

### 1. Plan

```bash
export AWS_PROFILE=plat-admin AWS_REGION=us-east-1
aws sso login --profile plat-admin
scripts/tf.sh 20-network plan
```

```
Plan: 15 to add, 0 to change, 0 to destroy.
```

Count: 1 VPC, 1 internet gateway, 2 public and 2 private subnets, 2 route tables, 1 internet route, 4 subnet associations, 2 endpoints. No NAT.

```bash
scripts/tf.sh 20-network apply
```

### 2. Verify with the CLI

```bash
VPC=$(terraform -chdir=stacks/20-network output -raw vpc_id)
aws ec2 describe-vpcs --vpc-ids $VPC --query 'Vpcs[0].[VpcId,CidrBlock]' --output text
aws ec2 describe-vpc-attribute --vpc-id $VPC --attribute enableDnsHostnames \
  --query EnableDnsHostnames.Value --output text
```

```
vpc-0a1b2c3d4e5f67890   10.20.0.0/16
True
```

```bash
aws ec2 describe-subnets --filters Name=tag:project,Values=plat \
  --query 'Subnets[].[Tags[?Key==`Name`]|[0].Value,AvailabilityZone,CidrBlock]' --output text | sort
```

```
plat-private-a  us-east-1a  10.20.10.0/24
plat-private-b  us-east-1b  10.20.11.0/24
plat-public-a   us-east-1a  10.20.0.0/24
plat-public-b   us-east-1b  10.20.1.0/24
```

Now the routing. This is the output that proves "private" without trusting a name:

```bash
for rt in plat-public-rt plat-private-rt; do
  echo "== $rt"
  aws ec2 describe-route-tables --filters Name=tag:Name,Values=$rt \
    --query 'RouteTables[0].Routes[].[DestinationCidrBlock||DestinationPrefixListId, GatewayId||NatGatewayId]' --output text
done
```

```
== plat-public-rt
10.20.0.0/16    local
0.0.0.0/0       igw-0a1b2c3d4e5f67890
== plat-private-rt
10.20.0.0/16    local
pl-63a5400a     vpce-0123456789abcdef0
pl-02cd2c6b     vpce-0fedcba9876543210
```

The private table has **no** `0.0.0.0/0` entry. The two `pl-` entries are the S3 and DynamoDB prefix lists, pointing at the gateway endpoints.

### 3. Turn the NAT gateway on

```bash
scripts/tf.sh 20-network plan -var enable_nat=true
```

```
Plan: 3 to add, 0 to change, 0 to destroy.
```

The Elastic IP, the NAT gateway and the route. Apply it (`apply -var enable_nat=true`, then `yes`) and rerun the private route table query: a new line `0.0.0.0/0  nat-0abc...` appears. The NAT takes a minute or two to become available.

> **From this moment the NAT gateway bills by the hour.** Do the next step before you leave.

### 4. Turn it off again

A plain apply is enough, because the code's default is `false`:

```bash
scripts/tf.sh 20-network apply
```

```
Plan: 0 to add, 0 to change, 3 to destroy.
```

Terraform destroys the route first, then the NAT gateway, then the Elastic IP, the reverse of creation. This is exactly what `make pause` does for the whole lab. Verify with `aws ec2 describe-nat-gateways --filter Name=state,Values=available,pending` and expect an empty list.

### 5. Drift: a missing tag

`default_tags` means Terraform expects `project = plat` on every resource. Remove it by hand:

```bash
aws ec2 delete-tags --resources $VPC --tags Key=project
scripts/tf.sh 20-network plan
```

```
  # module.vpc.aws_vpc.this will be updated in-place
  ~ resource "aws_vpc" "this" {
      ~ tags_all = {
          + "project" = "plat"
            # (3 unchanged elements hidden)
        }
    }

Plan: 0 to add, 1 to change, 0 to destroy.
```

Apply to repair it. Cost allocation tags in Post 15 depend on this being true everywhere, and now a single plan can prove it.

### 6. The blind spot: a route Terraform doesn't know about

```bash
RT=$(aws ec2 describe-route-tables --filters Name=tag:Name,Values=plat-private-rt \
  --query 'RouteTables[0].RouteTableId' --output text)
IGW=$(aws ec2 describe-internet-gateways --filters Name=attachment.vpc-id,Values=$VPC \
  --query 'InternetGateways[0].InternetGatewayId' --output text)
aws ec2 create-route --route-table-id $RT --destination-cidr-block 192.0.2.0/24 --gateway-id $IGW
scripts/tf.sh 20-network plan
```

```
No changes. Your infrastructure matches the configuration.
```

Terraform manages each `aws_route` it declares and nothing else. Someone just sent a range to the internet gateway from a private table, and the plan is clean. If the table used inline `route { }` blocks, Terraform would own the *whole list* and show this route for removal. Both styles are valid; the trade-off is flexibility versus detection. Remove the route:

```bash
aws ec2 delete-route --route-table-id $RT --destination-cidr-block 192.0.2.0/24
```

### 7. Trip the validation

```bash
scripts/tf.sh 20-network plan -var 'public_subnet_cidrs=["10.20.0.0/24"]'
```

```
Error: Invalid value for variable

  public_subnet_cidrs needs exactly one CIDR for each entry in azs.
```

The mistake is caught before a single API call.

### 8. Resources you now have 📦

| Resource | Name | Notes |
|---|---|---|
| VPC | `plat-vpc` (`10.20.0.0/16`) | DNS support and hostnames on |
| Subnets | `plat-public-a/b`, `plat-private-a/b` | |
| Internet gateway | `plat-igw` | |
| Route tables | `plat-public-rt`, `plat-private-rt` | |
| Gateway endpoints | `plat-s3-gw`, `plat-ddb-gw` | Free |
| NAT gateway | `plat-nat-a` | **Only while `enable_nat = true`. Hourly cost** |

### Cleanup 🧹

Make sure the NAT is off (step 4). Everything else here is free, so leave the network in place for the next posts.

---

## Quick Quiz 🧠

**Q1.** You run `apply -var enable_nat=true`, then tomorrow a teammate runs a plain `apply`. What happens to the NAT gateway?

<details>
<summary>Show answer</summary>

It's destroyed. `-var` isn't persisted anywhere, so the teammate's run sees the default `false` and plans to remove the NAT, its route and its Elastic IP. If you want it to stay on, set `enable_nat = true` in a `terraform.tfvars` that is committed or shared, so everyone plans against the same intent.

</details>

**Q2.** Why are the subnets keyed `a` and `b` rather than created with `count`?

<details>
<summary>Show answer</summary>

`count` addresses by position. Inserting or reordering an AZ would shift indexes and make Terraform replace subnets that didn't change. Keys are stable identities: `aws_subnet.private["a"]` is always the subnet in the `a` zone.

</details>

**Q3.** Someone adds a route to `plat-private-rt` in the console. `terraform plan` shows no changes. Is something wrong with Terraform?

<details>
<summary>Show answer</summary>

No, it's how standalone `aws_route` resources work: each manages one route, and routes it doesn't declare are ignored. Inline `route { }` blocks make the route table authoritative for the whole list instead. Neither is wrong, but you need to know which one you chose.

</details>

**Q4.** After `enable_nat` goes from `true` to `false`, in what order are resources destroyed, and why?

<details>
<summary>Show answer</summary>

Route, then NAT gateway, then Elastic IP. Terraform destroys in reverse dependency order: the route references the NAT, the NAT references the EIP. Deleting the NAT first would leave a route pointing at a missing target, and releasing the EIP first would fail because it's still in use.

</details>

**Q5.** The module creates gateway endpoints but not an interface endpoint for Secrets Manager. Why leave that out?

<details>
<summary>Show answer</summary>

An interface endpoint needs a **security group** to allow traffic in on 443, and security groups belong to the security stack, which depends on the VPC id. Putting the endpoint in `30-security` keeps the dependency pointing one way (security reads network) rather than creating a circle.

</details>

---

## What's Next? 🚀

The network exists and nothing in it is encrypted or fenced yet. Next come the key every service will use, the secret we read through a private endpoint, and the security groups, along with our first look at **how one stack reads another's outputs**.

👉 **[Post 05: Security as Code](content/aws-terraform/05-security-as-code.md)**: KMS, Secrets Manager, security groups as separate rules, and `terraform_remote_state`.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
