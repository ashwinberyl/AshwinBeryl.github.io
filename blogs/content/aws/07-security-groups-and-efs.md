---
title: "Security Groups and EFS"
date: 2026-11-08
tags: [aws, security-groups, nacl, efs, nfs, networking, kms, intermediate]
description: Post 7 of the AWS series. How security groups really evaluate traffic, why referencing a group beats listing IPs, how they differ from network ACLs, how EFS file systems, mount targets and access points fit together, and a lab that tests a rule from inside the VPC by watching a port open and close.
---

# The Firewall on Every Network Interface 🧱

In Post 05 you made a secret unreachable by deleting one rule, and the symptom was a **hang**, not an error. That was a security group at work.

Security groups are the firewall you will touch on almost every resource in this series: load balancers, containers, databases, endpoints and file systems. Get the mental model right once and a whole class of "it just times out" problems stops being mysterious.

Then we use them to protect something new: a **shared file system** (EFS) that several machines mount at once, which S3 can't be.

---

## Security Groups: The Model 🛡️

A **security group (SG)** is a set of rules attached to a **network interface** (ENI), not to a subnet and not to a VM. Anything that has an ENI in a VPC (an EC2 instance, an RDS database, a Lambda in a VPC, a Fargate task) carries one or more security groups.

| Property | What it means |
|---|---|
| **Stateful** | If a request is allowed in, the reply is allowed out automatically (and vice versa) |
| **Allow rules only** | There is **no deny rule**. Anything not allowed is dropped |
| **Default** | **No inbound** allowed, **all outbound** allowed |
| **No ordering** | All rules are evaluated together. A match on any rule allows the traffic |
| **Per-VPC** | A group belongs to one VPC |
| **Multiple per ENI** | An ENI can carry several groups. Their rules are combined |

### Referencing groups instead of IPs

A rule's **source** can be an IP range, a prefix list, or **another security group**.

| Source | Meaning | Good for |
|---|---|---|
| `0.0.0.0/0` | Anyone on the internet | Public load balancers only |
| `10.20.0.0/16` | Anything in the VPC | Broad internal access |
| **`sg-abc` (another group)** | **Any ENI that carries `sg-abc`** | **App-to-database, app-to-file-system** |

Referencing a group means you never edit IP lists as instances come and go. A new task that carries `plat-app-sg` is automatically allowed to reach the database, and a task that doesn't carry it is not.

### Our firewall design

Each tier only accepts traffic from the tier in front of it.

| Security group | Inbound rule | Used by | Post |
|---|---|---|---|
| `plat-vpce-sg` | 443 from `plat-app-sg` | Interface endpoints | 05 |
| `plat-app-sg` | none | Anything that is a *client*: shells, EC2, Lambda | 05 |
| `plat-efs-sg` | 2049 from `plat-app-sg` | EFS mount targets | **this post** |
| `plat-rds-sg` | 5432 from `plat-app-sg` | RDS database | 08 |
| `plat-alb-sg` | 80 from `0.0.0.0/0` | The public load balancer | 11 |
| `plat-api-sg` | 8080 from `plat-alb-sg` | ECS tasks | 11 |

![The chain of security groups](content/aws/images/07-sg-chain.svg)

### Security groups vs network ACLs

| | **Security group** | **Network ACL (NACL)** |
|---|---|---|
| Attached to | An ENI (resource) | A **subnet** |
| State | **Stateful** | **Stateless**: you must allow the reply traffic yourself |
| Rule types | Allow only | **Allow and deny** |
| Evaluation | All rules together | **In number order**, first match wins |
| Typical use | The everyday firewall | A coarse backstop, or blocking a specific IP range |

Most platforms leave NACLs at their permissive default and do the real work with security groups.

---

## EFS: A Shared File System 📁

**Amazon EFS** is a managed **NFS** file system. Many Linux machines, even across AZs, can mount the **same** directory tree at the same time.

| | **S3** | **EBS** | **EFS** |
|---|---|---|---|
| Type | Object store (HTTP API) | Block device | **Network file system (NFS)** |
| Shared by many machines at once | Yes (via API) | One instance (mostly) | **Yes (as a mount)** |
| Scope | Region | **One AZ** | **Region (multi-AZ)** |
| Capacity | Unlimited | Fixed size you provision | **Grows and shrinks automatically** |
| Rough cost | Lowest | Low | **About ten times S3 per GB** |

Use EFS when software needs a **POSIX file system shared between machines** (shared model files, user home directories, CMS content). Don't use it for bulk storage that S3 can serve.

### The pieces

| Piece | What it is |
|---|---|
| **File system** | The storage itself. Encrypted at rest with a KMS key you choose **at creation** |
| **Mount target** | An ENI in a subnet that clients connect to. **Create one per AZ** where you have clients |
| **Security group** | Attached to the mount target. It must allow **TCP 2049** (NFS) from clients |
| **Access point** | An entry point that **forces a POSIX user and root directory** for whoever uses it |
| **File system policy** | An IAM-style resource policy, for example "require TLS" |

Clients use the **EFS mount helper** (`amazon-efs-utils`) with `-o tls` to encrypt traffic in transit. The DNS name `fs-xxxx.efs.us-east-1.amazonaws.com` resolves to the mount target **in the client's own AZ**.

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "I'll add a deny rule to block that IP." | Security groups have **no deny rules**. Remove the allow, or use a **NACL** to block an address. |
| "Rule order matters, like a router ACL." | There's **no order**. The union of all allows applies. (NACLs *are* ordered.) |
| "The default outbound rule is a risk, outbound should be blocked." | All outbound is allowed by default and is usually fine. Tighten it for high-security tiers. Return traffic is **automatically allowed** because the group is stateful. |
| "Security groups attach to subnets." | They attach to **ENIs**. A subnet has a NACL. |
| "Referencing a security group is the same as allowing its IPs." | It's based on **membership**, not IPs, and it matches the **private** address of the source. Traffic arriving via a public IP won't match a SG-reference rule. |
| "The default security group is safe." | It allows **all traffic between its own members**, and anything launched without choosing a group gets it. Don't use it for anything. |
| "Changing a rule kills existing connections instantly." | New connections follow the new rule straight away, but connections AWS is **already tracking** can keep flowing until they close. Test with a *fresh* connection. |
| "A timeout means the app is down." | A **timeout** usually means a **firewall or route block**. **`Connection refused`** means the packet *arrived* but nothing was listening, so the network is fine and the app isn't. |
| "I can add unlimited rules." | Default quotas are about **60 inbound and 60 outbound rules per group** and **5 groups per interface**. Quotas can be raised, but needing to is a design smell. |
| "Opening SSH to the world for five minutes is harmless." | Scanners find open port 22 within minutes. Use **SSM Session Manager** (Post 10) and open no inbound port at all. |
| "EFS encryption can be switched on later." | Encryption at rest is set **when the file system is created**. You can't convert one in place. |
| "A mount failure means a permissions problem." | It's usually **network**: the SG doesn't allow 2049, there's no mount target in that AZ, DNS hostnames are off, or `amazon-efs-utils` isn't installed. |
| "EFS is just cheap network storage." | It costs roughly **ten times S3** per GB, and with *Elastic* throughput you also pay per GB read and written. |
| "An access point is a firewall." | It maps every user to a **fixed POSIX identity and root directory**. It doesn't filter network traffic. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| `plat-vpc`, private subnets, DNS hostnames on | Post 04 |
| `plat-app-sg` and the CloudShell VPC environment `plat-shell` | Post 05 |
| KMS key `alias/plat-data` | Post 05 |

| You create here | Used by |
|---|---|
| `plat-efs-sg` | The same pattern as `plat-rds-sg` (08), `plat-api-sg` (11) and `plat-sm-sg` (19) |
| EFS file system `plat-efs` and access point `plat-ml-ap` | Mounted on EC2 in Post 10. EKS can use it through a CSI driver (12). SageMaker Studio uses its own EFS for home directories (19) |
| The **hang vs refused** diagnostic habit | Every troubleshooting section from here on, and the capstone |

---

## Lab: Firewall Rules You Can Watch 🛠️

Sign in as Jim in **N. Virginia**. Open the **CloudShell VPC environment** `plat-shell` from Post 05. It lives in `plat-private-a` and carries `plat-app-sg`.

> The NAT gateway from Post 04 must be running for the VPC CloudShell to start. If you deleted it, recreate it (Post 04 Cleanup, "To resume").

### 1. Create the EFS security group

1. **VPC, Security groups, Create security group.**
2. Name **`plat-efs-sg`**, description `NFS access to EFS`, VPC `plat-vpc`.
3. **Inbound rule:** type **NFS** (TCP 2049), **Source:** the security group **`plat-app-sg`**.
4. Tag `project = plat` and create it.

### 2. Create the file system

1. Open **EFS**, then **Create file system**, then **Customize**.
2. **Name:** `plat-efs`. **File system type:** **Regional**. Keep automatic backups on.
3. **Lifecycle management:** transition into Infrequent Access after **30 days**. Leave Archive off.
4. **Encryption:** enabled, with the KMS key **`plat-data`** (choose it from your keys).
5. **Throughput mode:** **Elastic**. **Performance mode:** **General Purpose**.
6. Tag `project = plat`. Choose **Next**.
7. **Network:** VPC `plat-vpc`. For each of `us-east-1a` and `us-east-1b`, choose the private subnet (`plat-private-a`, `plat-private-b`) and **replace the default security group with `plat-efs-sg`** (remove the default one).
8. **File system policy:** tick **Enforce in-transit encryption for all clients**. Create the file system.

### 3. Create an access point

1. Open the file system, **Access points**, **Create access point**.
2. Name **`plat-ml-ap`**. **Root directory path:** `/ml`.
3. **POSIX user:** user ID `1000`, group ID `1000`.
4. **Root directory creation permissions:** owner user ID `1000`, owner group ID `1000`, permissions `0755`.
5. Create it.

From now on, anyone who mounts through this access point lands in `/ml` and **appears to be user 1000**, regardless of who they really are.

### 4. Verify from the CLI

```bash
aws efs describe-file-systems --query \
  'FileSystems[].[Name,LifeCycleState,Encrypted,ThroughputMode,PerformanceMode]' --output table

FS=$(aws efs describe-file-systems --query 'FileSystems[0].FileSystemId' --output text)
aws efs describe-mount-targets --file-system-id $FS \
  --query 'MountTargets[].[AvailabilityZoneName,SubnetId,IpAddress,LifeCycleState]' --output table
```

```text
-----------------------------------------------------------------
|                      DescribeMountTargets                     |
+-------------+------------------------+--------------+---------+
|  us-east-1a |  subnet-0aaa...        |  10.20.10.84 |  available |
|  us-east-1b |  subnet-0bbb...        |  10.20.11.37 |  available |
+-------------+------------------------+--------------+---------+
```

Note the IP addresses. They're **inside the private subnets**, and there's one mount target per AZ.

### 5. Watch a firewall rule open and close

Mounting needs a Linux client with the EFS helper, which we launch in Post 10. But we can test the **network path** now with plain bash. In **`plat-shell`**:

```bash
EFS_IP=10.20.10.84          # use YOUR us-east-1a mount target IP from step 4

timeout 5 bash -c "</dev/tcp/$EFS_IP/2049" && echo "port 2049: OPEN" || echo "port 2049: BLOCKED"
```

```text
port 2049: OPEN
```

The shell carries `plat-app-sg`, which `plat-efs-sg` allows. Now break it:

1. Open **`plat-efs-sg`**, **Inbound rules, Edit inbound rules**, and **delete** the NFS rule. Save.
2. Wait a few seconds and run the same command again.

```text
port 2049: BLOCKED
```

The command waits five seconds and then gives up. **No error, just silence.** Restore the rule (type NFS, source `plat-app-sg`) and run it once more to see `OPEN`.

Now try a different client. Open a **regular CloudShell** (not the VPC one) and repeat the test against the same IP. It's also `BLOCKED`, but for a different reason: that shell isn't inside the VPC at all, so there is **no route** to `10.20.10.84`. A security group isn't even in play. The symptom is identical, which is exactly why "it hangs" needs two checks: **route first, firewall second**.

### 6. Resources you now have 📦

| Resource | Name | Notes |
|---|---|---|
| Security group | `plat-efs-sg` | 2049 from `plat-app-sg` |
| EFS file system | `plat-efs` | Encrypted with `plat-data`, Elastic throughput, TLS enforced |
| Mount targets | `us-east-1a`, `us-east-1b` | In the private subnets |
| Access point | `plat-ml-ap` | `/ml`, uid/gid 1000 |

### Cleanup 🧹

| Keep | Notes |
|---|---|
| Everything | An empty EFS file system costs nothing. You pay for stored data and, with Elastic throughput, for data transferred. We'll mount it in Post 10 and store only a few bytes |

---

## Quick Quiz 🧠

**Q1.** A connection to a database port hangs for 30 seconds, then times out. Another attempt to a different host immediately says "Connection refused". What does each tell you?

<details>
<summary>Show answer</summary>

The **hang** means packets are being **dropped**: a security group, NACL or missing route is blocking them. **Connection refused** means the packet **reached the host** and nothing was listening on that port, so the network path is fine and the application (or its port) is the problem.

</details>

**Q2.** Why is `plat-efs-sg` allowing `plat-app-sg` better than allowing `10.20.0.0/16`?

<details>
<summary>Show answer</summary>

It limits access to **resources that carry `plat-app-sg`** rather than everything in the VPC, and it keeps working as addresses change. A compromised or unrelated resource in the same VPC that doesn't carry the group still can't reach the file system.

</details>

**Q3.** You need to block one hostile IP address from reaching an internet-facing instance. Which tool, and why not a security group?

<details>
<summary>Show answer</summary>

A **network ACL**. Security groups have **only allow rules**, so you can't express "deny this address" there. NACLs support explicit deny rules, evaluated in number order.

</details>

**Q4.** A teammate wants to turn on encryption for the existing unencrypted `plat-efs`. What are the options?

<details>
<summary>Show answer</summary>

Encryption at rest can only be chosen **at creation**. The path is to create a **new encrypted file system** and copy the data across (for example with AWS DataSync or `rsync`), then switch clients to the new one.

</details>

**Q5.** A mount command from an EC2 instance in `us-east-1c` fails to resolve the file system DNS name, but works from `us-east-1a`. Why?

<details>
<summary>Show answer</summary>

The DNS name resolves to the **mount target in the client's own AZ**. There's no mount target in `us-east-1c`, so there's nothing to resolve to. Create a mount target in that AZ (or mount by IP, accepting cross-AZ traffic and cost).

</details>

---

## What's Next? 🚀

We have encrypted object storage and a shared file system. Next, the structured stores. When should the platform use a relational database and when a key-value table? How do you keep a database in private subnets, with its password managed for you, and how do you design a DynamoDB key so one partition doesn't melt?

👉 **[Post 08: RDS and DynamoDB](content/aws/08-rds-and-dynamodb.md)**: a private Postgres instance with a managed secret, a jobs table with an index, and the nuances that cause most production surprises.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
