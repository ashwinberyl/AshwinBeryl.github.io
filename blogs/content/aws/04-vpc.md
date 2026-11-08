---
title: "VPC: Subnets, NAT and Endpoints"
date: 2026-11-08
tags: [aws, vpc, networking, subnets, nat-gateway, vpc-endpoints, route-tables, intermediate]
description: Post 4 of the AWS series. What actually makes a subnet public or private, how route tables decide where packets go, when a NAT gateway or a VPC endpoint is the right exit, and a lab that builds the two-AZ network every later post sits inside.
---

# Where Do the Packets Go? 🌐

Every service in this series runs *somewhere*. A Lambda function, an ECS task, an RDS database and a SageMaker job all get a network interface with an IP address inside a **VPC**.

And networking is where most "it just hangs" problems live. Not `AccessDenied`. Not an error at all. Just a timeout, because a packet had nowhere to go.

This post builds the network, and, more importantly, makes the rules for **why packets reach a destination or don't** completely mechanical.

---

## The Pieces 🧱

| Piece | What it is |
|---|---|
| **VPC** | A private, isolated network in one region, defined by an IP range (CIDR) |
| **Subnet** | A slice of the VPC's range that lives in **exactly one Availability Zone** |
| **Route table** | A list of "destination range → target" rules attached to subnets |
| **Internet gateway (IGW)** | The door between the VPC and the public internet |
| **NAT gateway** | Lets private resources start outbound connections without being reachable inbound |
| **VPC endpoint** | A private path from your VPC to an AWS service, without using the internet |
| **Security group** | A stateful firewall on a network interface (Post 07) |
| **Network ACL** | A stateless firewall on a subnet |

### What makes a subnet "public"?

Not a checkbox, and not a name. A subnet is public **only if its route table has a route to an internet gateway**.

| Subnet type | Route to `0.0.0.0/0` | Can be reached from the internet? | Can reach the internet? |
|---|---|---|---|
| **Public** | Internet gateway | Yes, if the resource also has a public IPv4 and the security group allows it | Yes |
| **Private (with egress)** | NAT gateway | **No** | Yes, outbound only |
| **Isolated** | None | No | No |

Every route table contains an unremovable **`local`** route for the VPC's own range, so anything inside a VPC can reach anything else inside it (subject to security groups).

### How a route is chosen

AWS picks the **most specific matching route** (longest prefix). A request to `10.20.10.5` matches `local` (`10.20.0.0/16`) before `0.0.0.0/0`, so internal traffic never goes out of the door.

---

## Our Network Plan 📐

Two AZs, so a single AZ failure doesn't take the platform down. Each AZ gets a public and a private subnet.

| Subnet | AZ | CIDR | Holds |
|---|---|---|---|
| `plat-public-a` | `us-east-1a` | `10.20.0.0/24` | NAT gateway, load balancers |
| `plat-public-b` | `us-east-1b` | `10.20.1.0/24` | Load balancers |
| `plat-private-a` | `us-east-1a` | `10.20.10.0/24` | App workloads, databases |
| `plat-private-b` | `us-east-1b` | `10.20.11.0/24` | App workloads, databases |

The VPC range is `10.20.0.0/16`, which is 65,536 addresses. Each `/24` is 256, but **AWS reserves five in every subnet**, so each holds 251 usable addresses:

| Address | Reserved for |
|---|---|
| `.0` | Network address |
| `.1` | VPC router |
| `.2` | DNS (Route 53 Resolver) |
| `.3` | Reserved for future use |
| `.255` | Broadcast (not supported, but reserved) |

Later posts use `10.30.0.0/16` and `10.40.0.0/16` for the CloudFormation and Terraform labs. Picking **non-overlapping ranges now** means you can peer or connect VPCs later. Overlapping ranges can't be joined, and a VPC's primary CIDR can't be resized.

![The Platform Lab VPC](content/aws/images/04-vpc.svg)

---

## Two Ways Out: NAT vs Endpoints 🚪

Private resources often need to reach **AWS services** (S3, DynamoDB, Secrets Manager, ECR) or the **internet** (package repositories). There are two mechanisms, and they work very differently.

### NAT gateway

A managed device in a **public** subnet that rewrites outbound traffic from private subnets so it appears to come from its Elastic IP. Replies come back, but nothing can start a connection *in*.

It bills **per hour** and **per GB processed**, plus the public IPv4 address, which is why NAT is the usual cause of a surprise bill.

### VPC endpoints

An endpoint lets a private resource talk to an AWS service **without leaving the AWS network** and without NAT. There are two kinds:

| | **Gateway endpoint** | **Interface endpoint** (PrivateLink) |
|---|---|---|
| **Services** | **S3 and DynamoDB only** | Most other services (Secrets Manager, ECR, SSM, CloudWatch Logs, SQS ...) |
| **How it works** | A **route** in your route table pointing a service prefix list at the endpoint | An **ENI** with a private IP in each chosen subnet, reached via **private DNS** |
| **Cost** | **Free** | Hourly per AZ, plus data processed |
| **Security** | Endpoint policy | Endpoint policy **and** a security group |
| **Reachable from outside the VPC?** | No (on-prem and peered VPCs can't use it) | Yes (over VPN or Direct Connect) |

A rule of thumb: **always create the S3 and DynamoDB gateway endpoints**, because they're free and they keep that traffic off the NAT. Add interface endpoints when NAT cost or a "no internet at all" requirement justifies them.

> **Key insight:** A route table answers "where does this packet go?", and a security group answers "may it pass?". When something hangs, check the route first. When something is refused, check the security group.

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "A public subnet gives my instances public IPs." | It only gives them a **route** to the internet. The instance also needs a **public IPv4 or Elastic IP**, and a security group that allows the traffic. |
| "Private subnets have no internet." | They have **outbound** internet if a route points at a NAT gateway. "Private" means *nothing on the internet can start a connection in*. |
| "One NAT gateway is highly available." | A NAT gateway lives in **one AZ**. If that AZ fails, private subnets in the other AZ lose their route to the internet. Production uses **one NAT per AZ**, and each private route table points at its own. We use one to save money. |
| "NAT is cheap, it's just a gateway." | You pay an **hourly charge**, a **per-GB charge** and the Elastic IP. Pulling large container images or datasets through NAT adds up fast. |
| "Gateway and interface endpoints are the same thing." | Different mechanics, price and reach. Gateway endpoints are **route table entries** and only work from inside the VPC. Interface endpoints are **ENIs** with DNS. |
| "An S3 endpoint makes my bucket private." | The bucket's public endpoint still exists. To *force* VPC-only access, add a bucket policy condition on `aws:SourceVpce`. (Post 06) |
| "Interface endpoints work out of the box." | They need **DNS support and DNS hostnames** enabled on the VPC and **Private DNS** enabled on the endpoint, or the service name still resolves to the **public** address. |
| "I can resize the VPC later." | You can **add** secondary CIDR blocks, but you can't change or shrink the primary one, and you can't resize a subnet. Plan generously. |
| "VPC peering is transitive." | If A peers with B and B peers with C, A **cannot** reach C. You need explicit peering or a **transit gateway**. |
| "Security groups and network ACLs do the same job." | Security groups are **stateful** and attach to **ENIs**. NACLs are **stateless** (you must allow replies explicitly) and attach to **subnets**. Most platforms use security groups and leave NACLs at default. |
| "Anything in the default VPC is fine for a lab." | Every region has a **default VPC** with public subnets. It's convenient, and it's not a platform. We build our own. |
| "Each AZ has the same name for everyone." | AZ **names are per-account**. Use AZ IDs when coordinating (Post 01). |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| The `PlatformAdmin` role and the `plat-admin` CLI profile | Post 03 |
| The naming convention and the `project = plat` tag | Post 01 |

| You create here | Used by |
|---|---|
| `plat-vpc` and the four subnets | **Every later post**: EC2, RDS, ECS, EKS, Lambda in a VPC, SageMaker VPC-only mode |
| `plat-private-rt` with a NAT route | ECR image pulls (Post 11), pip installs, the SSM agent (Post 10) |
| S3 and DynamoDB gateway endpoints | Lambda (Post 13) and ECS tasks (Post 11) reaching data without NAT |
| DNS support and hostnames enabled | Interface endpoints in Posts 05 and 10 |

---

## Lab: Build the Platform Network 🛠️

Sign in as Jim (access portal), open the console in **N. Virginia**, and go to **VPC**.

> **Tip:** The console's **"VPC and more"** wizard can build all of this in one click. We create each piece by hand, because a wizard hides precisely the connections this post is about.

### 1. Create the VPC

1. **Your VPCs**, then **Create VPC**, then choose **VPC only**.
2. Name tag: `plat-vpc`. IPv4 CIDR block: **IPv4 CIDR manual input**, `10.20.0.0/16`. No IPv6. Tenancy: **Default**.
3. Add the tag `project = plat`, and create it.
4. Select the VPC, then **Actions**, then **Edit VPC settings**, and tick **Enable DNS hostnames**. (DNS resolution is already on.) Save.

### 2. Create the four subnets

**Subnets**, then **Create subnet**, choose `plat-vpc`, and add four subnets in one go:

| Name | Availability Zone | IPv4 CIDR |
|---|---|---|
| `plat-public-a` | `us-east-1a` | `10.20.0.0/24` |
| `plat-public-b` | `us-east-1b` | `10.20.1.0/24` |
| `plat-private-a` | `us-east-1a` | `10.20.10.0/24` |
| `plat-private-b` | `us-east-1b` | `10.20.11.0/24` |

Add `project = plat` to each. Notice that right now **none of them is public or private**. They're just ranges. The route tables will decide.

### 3. Create and attach the internet gateway

1. **Internet gateways**, then **Create internet gateway**, name `plat-igw`.
2. **Actions**, then **Attach to VPC**, and choose `plat-vpc`.

### 4. Create the route tables

1. **Route tables**, then **Create route table**: name `plat-public-rt`, VPC `plat-vpc`.
2. Open it, choose **Routes**, then **Edit routes**, then **Add route**: destination `0.0.0.0/0`, target **Internet Gateway**, `plat-igw`. Save.
3. **Subnet associations**, then **Edit subnet associations**, and tick `plat-public-a` and `plat-public-b`. Save.
4. Create a second route table: `plat-private-rt`, VPC `plat-vpc`. It starts with only the `local` route.
5. Associate it with `plat-private-a` and `plat-private-b`.

The two public subnets are now genuinely public. Leave the VPC's **main route table** alone. Any subnet you forget to associate falls back to it, so it should never hold an internet route.

### 5. Create the NAT gateway

1. **NAT gateways**, then **Create NAT gateway**.
2. Name `plat-nat-a`, subnet **`plat-public-a`** (it must be a *public* subnet), connectivity **Public**.
3. Choose **Allocate Elastic IP**, add the tag `project = plat`, and create it.
4. Wait for the state to become **Available** (a minute or two).
5. Back in **Route tables**, open `plat-private-rt`, **Edit routes**, **Add route**: `0.0.0.0/0`, target **NAT Gateway**, `plat-nat-a`. Save.

This is the moment the meter starts running. We'll delete this at the end of the session.

### 6. Create the gateway endpoints

1. **Endpoints**, then **Create endpoint**.
2. Name `plat-s3-gw`. Service category **AWS services**. Search for `s3` and choose **`com.amazonaws.us-east-1.s3`** with type **Gateway**.
3. VPC `plat-vpc`. Route tables: tick **`plat-private-rt`** (and `plat-public-rt` if you like). Policy: **Full access**. Create it.
4. Repeat for DynamoDB: name `plat-ddb-gw`, service **`com.amazonaws.us-east-1.dynamodb`**, type **Gateway**, same route tables.

Open `plat-private-rt` again. You'll see two **new routes** whose destinations are prefix lists (`pl-xxxxxxxx`) and whose targets are `vpce-...`. That's all a gateway endpoint is.

### 7. Verify from the CLI

On your laptop, with `AWS_PROFILE=plat-admin` (run `aws sso login --profile plat-admin` if the session expired):

```bash
aws ec2 describe-subnets \
  --filters "Name=tag:Name,Values=plat-*" \
  --query 'Subnets[].[Tags[?Key==`Name`]|[0].Value,AvailabilityZone,CidrBlock,AvailableIpAddressCount]' \
  --output table
```

```text
------------------------------------------------------------
|                      DescribeSubnets                     |
+----------------+-------------+----------------+----------+
|  plat-public-a |  us-east-1a |  10.20.0.0/24  |  250     |
|  plat-public-b |  us-east-1b |  10.20.1.0/24  |  251     |
|  plat-private-a|  us-east-1a |  10.20.10.0/24 |  251     |
|  plat-private-b|  us-east-1b |  10.20.11.0/24 |  251     |
+----------------+-------------+----------------+----------+
```

`plat-public-a` shows 250: the NAT gateway's network interface took one address. Now the private route table:

```bash
aws ec2 describe-route-tables \
  --filters "Name=tag:Name,Values=plat-private-rt" \
  --query 'RouteTables[0].Routes[].[DestinationCidrBlock,DestinationPrefixListId,GatewayId,NatGatewayId]' \
  --output table
```

You should see `10.20.0.0/16 → local`, `0.0.0.0/0 → nat-...`, and two prefix-list rows pointing at `vpce-...`. And the NAT state:

```bash
aws ec2 describe-nat-gateways --filter "Name=tag:Name,Values=plat-nat-a" \
  --query 'NatGateways[].[NatGatewayId,State,SubnetId]' --output table
```

The state should read `available`.

A real end-to-end packet test arrives in Post 05, when we launch a CloudShell inside this VPC and prove DNS and routing from the inside.

### 8. Resources you now have 📦

| Resource | Name | Notes |
|---|---|---|
| VPC | `plat-vpc` `10.20.0.0/16` | DNS support and hostnames on |
| Subnets | `plat-public-a/b`, `plat-private-a/b` | One public and one private per AZ |
| Internet gateway | `plat-igw` | Attached |
| Route tables | `plat-public-rt`, `plat-private-rt` | Private has a NAT default route |
| NAT gateway | `plat-nat-a` | **Costs money.** Delete after each session |
| Gateway endpoints | `plat-s3-gw`, `plat-ddb-gw` | Free |

### Cleanup 🧹

| Keep (free) | Delete at the end of each session |
|---|---|
| VPC, subnets, route tables, IGW, gateway endpoints | **NAT gateway** `plat-nat-a`, and **release its Elastic IP** |

To pause: **NAT gateways**, select `plat-nat-a`, **Actions, Delete NAT gateway**. Once it shows *Deleted*, go to **Elastic IPs** and **Release** the address (an unattached Elastic IP is billed too). The route in `plat-private-rt` will show as a **blackhole**.

To resume: create a new NAT gateway in `plat-public-a`, allocate a new Elastic IP, and **Edit routes** on `plat-private-rt` to point `0.0.0.0/0` at the new NAT ID.

---

## Quick Quiz 🧠

**Q1.** You create a subnet and launch an instance with a public IP in it. It can't reach the internet. What's the most likely missing piece?

<details>
<summary>Show answer</summary>

A **route** to an internet gateway in the subnet's route table. A public IP and a security group aren't enough. The packet needs a route `0.0.0.0/0 → igw-...` to leave the VPC. (Also check that the IGW is *attached* to the VPC.)

</details>

**Q2.** A NAT gateway is created in a *private* subnet. Does it work?

<details>
<summary>Show answer</summary>

**No.** A NAT gateway needs to sit in a **public subnet** (one with a route to an IGW) and have an Elastic IP, because it forwards traffic out through the internet gateway. A NAT in a private subnet has no path out.

</details>

**Q3.** Why create the S3 and DynamoDB gateway endpoints even if the NAT gateway already gives private subnets access to them?

<details>
<summary>Show answer</summary>

They're **free** and they keep that traffic off the NAT gateway, which charges per GB processed. They also keep the traffic on the AWS network, and they let you write policies that require requests to arrive through a specific endpoint.

</details>

**Q4.** Subnets `10.20.0.0/24` in `us-east-1a` and a second one at `10.20.0.128/25` in `us-east-1b`. Will AWS create the second?

<details>
<summary>Show answer</summary>

**No.** Subnet ranges within a VPC can't overlap, and `10.20.0.128/25` falls inside `10.20.0.0/24`. Each subnet needs a unique, non-overlapping slice of the VPC's range.

</details>

**Q5.** Why does `plat-public-a` show 250 free addresses while the others show 251?

<details>
<summary>Show answer</summary>

A `/24` has 256 addresses, AWS reserves 5, leaving **251**. The NAT gateway created its own **network interface** in `plat-public-a`, which consumed one more, leaving 250. Interface endpoints, load balancers and Lambda/ECS ENIs consume addresses the same way.

</details>

---

## What's Next? 🚀

We have a network, but everything we put in it will carry data and secrets. Who holds the keys that encrypt them? And where do passwords and API keys live so they never land in code or environment dumps?

👉 **[Post 05: KMS and Secrets Manager](content/aws/05-kms-and-secrets-manager.md)**: create the encryption key the whole platform shares, store your first secret, and read it from inside the VPC through a private endpoint.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
