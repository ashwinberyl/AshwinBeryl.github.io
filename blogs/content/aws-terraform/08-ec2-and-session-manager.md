---
title: "EC2 and Session Manager: A Private Instance, Reached Without SSH"
date: 2026-11-09
tags: [aws, terraform, ec2, ssm, iam, imds, efs, cloudwatch-agent, intermediate]
description: Post 8 of the AWS on Terraform series. An instance with no public address and no inbound rule, an instance profile, IMDSv2 only, a user-data template that mounts EFS and starts the CloudWatch agent, and the endpoint toggle that makes Session Manager work without a NAT gateway.
---

# A Machine Inside the VPC 🖥️

Every earlier stack was configuration: groups, subnets, a key, a table. This is the first stack that **runs** something. The instance is small and its job is to be a test bench: from inside the VPC we can finally prove that EFS mounts, that the database port is reachable only from the right security group, and that the role we write can use the key. It combines AWS series Posts 09 and 10 (EC2, Linux) into `stacks/50-ec2`.

---

## The Pieces 🧱

| Piece | Resource(s) | Always on? |
|---|---|---|
| Newest Amazon Linux 2023 AMI id | `data.aws_ssm_parameter.al2023` | Yes (a read) |
| Role `plat-ec2-role` + instance profile | `aws_iam_role.ec2`, `aws_iam_instance_profile.ec2` | Yes |
| Managed policies for Session Manager and the agent | `aws_iam_role_policy_attachment.ssm`, `.cwagent` | Yes |
| Inline policy for the data bucket and key | `aws_iam_role_policy.ec2_data_access` | Yes |
| Agent configuration in Parameter Store | `aws_ssm_parameter.cwagent` | Yes |
| The instance `plat-ec2` | `aws_instance.this` | **Toggle** `enable_ec2` (default on, about a cent an hour) |
| Three interface endpoints for Session Manager | `aws_vpc_endpoint.ssm` | **Toggle** `enable_ssm_endpoints` (hourly cost each) |

![Session Manager reaching a private instance](content/aws-terraform/images/08-ec2-session-manager.svg)

### What it reads from other stacks

```hcl
# stacks/50-ec2/main.tf
locals {
  private      = data.terraform_remote_state.network.outputs.private_subnet_ids
  vpc_id       = data.terraform_remote_state.network.outputs.vpc_id
  kms_arn      = data.terraform_remote_state.security.outputs.kms_key_arn
  app_sg_id    = data.terraform_remote_state.security.outputs.app_sg_id
  vpce_sg_id   = data.terraform_remote_state.security.outputs.vpce_sg_id
  bucket_arn   = data.terraform_remote_state.data.outputs.data_bucket_arn
  efs_id       = data.terraform_remote_state.data.outputs.efs_id
  efs_ap_id    = data.terraform_remote_state.data.outputs.efs_access_point_id
  cwagent_name = "AmazonCloudWatch-plat"
}
```

The instance lands in the private subnet keyed `a`, in `plat-app-sg` (Post 05). The endpoints reuse `plat-vpce-sg`, which already allows 443 from `plat-app-sg`.

---

## Reading the Stack 📖

### The AMI, looked up instead of pasted

```hcl
# stacks/50-ec2/main.tf
data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}
```

AMI ids differ per region and change every few weeks. AWS publishes the current Amazon Linux 2023 id under a **public parameter**, and this data source reads it at plan time. The attribute is `insecure_value` because the provider marks `value` as sensitive by default, and an AMI id is not a secret.

That raises a problem: a new AMI today would make the plan want to **replace a running instance** tomorrow. The instance block below answers it with `ignore_changes`.

### The role and the profile

```hcl
# stacks/50-ec2/main.tf
data "aws_iam_policy_document" "ec2_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ec2" {
  name               = "plat-ec2-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_trust.json
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "cwagent" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}
```

* An EC2 instance cannot hold a role directly. It holds an **instance profile**, a thin wrapper that contains one role. The console creates the profile silently; in Terraform it is its own resource.
* `AmazonSSMManagedInstanceCore` is what lets the agent on the instance register with Systems Manager. Without it the instance never appears as a managed node.
* `CloudWatchAgentServerPolicy` lets the CloudWatch agent publish metrics and read its configuration from parameters named `AmazonCloudWatch-*`. That is why our parameter is called `AmazonCloudWatch-plat`.

```hcl
# stacks/50-ec2/main.tf
data "aws_iam_policy_document" "ec2_data_access" {
  statement {
    sid       = "ListDataBucket"
    actions   = ["s3:ListBucket"]
    resources = [local.bucket_arn]
  }

  statement {
    sid       = "ReadWriteObjects"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${local.bucket_arn}/*"]
  }

  statement {
    sid       = "UseDataKey"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
    resources = [local.kms_arn]
  }
}

resource "aws_iam_role_policy" "ec2_data_access" {
  name   = "plat-ec2-data-access"
  role   = aws_iam_role.ec2.id
  policy = data.aws_iam_policy_document.ec2_data_access.json
}

resource "aws_iam_instance_profile" "ec2" {
  name = "plat-ec2-role"
  role = aws_iam_role.ec2.name
}
```

Three statements: list the bucket, read and write objects, and use the key. The third is the lesson of Post 07 applied: **an S3 allow without a KMS allow fails**.

### The agent configuration

```hcl
# stacks/50-ec2/main.tf
resource "aws_ssm_parameter" "cwagent" {
  name = local.cwagent_name
  type = "String"

  value = jsonencode({
    agent = { metrics_collection_interval = 60 }
    metrics = {
      append_dimensions      = { InstanceId = "$${aws:InstanceId}" }
      aggregation_dimensions = [["InstanceId", "path"]]
      metrics_collected = {
        disk = {
          measurement              = ["used_percent"]
          resources                = ["/"]
          ignore_file_system_types = ["sysfs", "devtmpfs", "tmpfs"]
        }
        mem = { measurement = ["mem_used_percent"] }
      }
    }
  })
}
```

`jsonencode` builds the agent's JSON from an HCL object, so there are no quoting mistakes. The one subtlety is `"$${aws:InstanceId}"`: in Terraform, `${` starts an interpolation, and `$${` is the escape for a literal `${`. The agent substitutes the instance id itself.

### The instance

```hcl
# stacks/50-ec2/main.tf
resource "aws_instance" "this" {
  count = var.enable_ec2 ? 1 : 0

  ami                    = data.aws_ssm_parameter.al2023.insecure_value
  instance_type          = var.instance_type
  subnet_id              = local.private["a"]
  vpc_security_group_ids = [local.app_sg_id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name

  user_data_replace_on_change = true
  user_data = templatefile("${path.module}/userdata.sh.tftpl", {
    mount_efs       = var.mount_efs
    efs_id          = local.efs_id
    access_point_id = local.efs_ap_id
    cwagent_param   = local.cwagent_name
  })

  # IMDSv2 only: requests to the metadata service must carry a session token.
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 8
    encrypted   = true
  }

  tags = { Name = "plat-ec2" }

  # A newer AMI is published every few weeks. Do not replace a running instance because of it.
  lifecycle {
    ignore_changes = [ami]
  }

  depends_on = [aws_ssm_parameter.cwagent]
}
```

* **`count`** makes the instance optional. Everything that refers to it uses `aws_instance.this[0]` or `one(...)`.
* **`ignore_changes = [ami]`** stops the newest-AMI problem above. Replace the machine deliberately with `-replace` (Post 16).
* **`http_tokens = "required"`** enforces **IMDSv2**: reading the instance metadata service needs a session token obtained with a `PUT`. Plain `GET` requests, which is how most credential-stealing attacks work against server-side request forgery bugs, return 401. A hop limit of 2 lets containers on the instance reach the service too.
* **`user_data_replace_on_change = true`** makes a changed boot script **replace** the instance. User data runs once at first boot, so applying a new script to a running machine would do nothing; replacing is the honest behaviour.
* **No public IP and no key pair.** There is no way in except Session Manager.

### The boot script

```bash
# stacks/50-ec2/userdata.sh.tftpl
#!/bin/bash
# Runs once as root at first boot (cloud-init). Output goes to /var/log/cloud-init-output.log.
set -euxo pipefail

# AL2023 package repositories are served from S3, so the S3 gateway endpoint is enough to install.
dnf install -y amazon-efs-utils amazon-cloudwatch-agent postgresql16 nmap-ncat

%{ if mount_efs ~}
mkdir -p /mnt/ml
echo "${efs_id}:/ /mnt/ml efs _netdev,tls,accesspoint=${access_point_id} 0 0" >> /etc/fstab
mount -a -t efs
%{ endif ~}

# Config lives in SSM Parameter Store (see main.tf); this needs SSM reachability (NAT or endpoints).
amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -s -c ssm:${cwagent_param} || echo "cwagent config not fetched yet"
```

`templatefile` fills in `${...}` and the `%{ if }` directive from the values in the call above. The package repository for Amazon Linux 2023 is served from S3, so the **S3 gateway endpoint** from Post 04 is enough for `dnf` to install packages even without a NAT. The agent configuration fetch is different: it needs to reach Systems Manager.

### Session Manager without a NAT

```hcl
# stacks/50-ec2/main.tf
resource "aws_vpc_endpoint" "ssm" {
  for_each = var.enable_ssm_endpoints ? toset(["ssm", "ssmmessages", "ec2messages"]) : toset([])

  vpc_id              = local.vpc_id
  service_name        = "com.amazonaws.${var.region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = [local.private["a"]]
  security_group_ids  = [local.vpce_sg_id]

  tags = { Name = "plat-${each.key}-vpce" }
}
```

The agent talks to three services: `ssm`, `ssmmessages` (the session channel) and `ec2messages`. A private subnet reaches them either through a NAT gateway or through these three interface endpoints, never both at once. Choose by cost: three endpoints in one AZ bill per hour like a NAT, but carry no per-gigabyte charge for this traffic. `private_dns_enabled` is what makes `ssm.us-east-1.amazonaws.com` resolve to the endpoint's private address.

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "Session Manager needs port 22 or a bastion." | It needs **no inbound rule at all**. The agent makes an outbound HTTPS connection and the session is carried over it. |
| "Private subnet plus the SSM policy is enough." | The agent also needs a **path** to Systems Manager: a NAT, or the three endpoints. Without one the instance never registers. |
| "Instance profile and role are the same thing." | The role holds permissions; the profile attaches a role to an instance. Same name here by convention, two resources. |
| "I'll use `value` from the AMI parameter." | The provider marks it sensitive; the data source exposes `insecure_value` for non-secret values. |
| "Using the latest AMI is always safe." | Only with `ignore_changes = [ami]`. Without it, every new AMI plans a replacement of the running instance. |
| "Changing the user data updates the running instance." | It runs **once**, at first boot. Hence `user_data_replace_on_change`. |
| "IMDSv2 breaks my containers." | A hop limit of 1 does. Containers add a network hop, so the stack uses 2. |
| "The instance role can use the bucket because of the S3 statement." | Only with the KMS statement as well. The bucket is encrypted with `plat-data`. |
| "`$${aws:InstanceId}` is a typo." | It is the escape for a literal `${` in a Terraform string. The agent fills it in. |
| "Interface endpoints are free because the traffic stays in AWS." | They bill per hour per AZ and per gigabyte. Three of them are about the price of a NAT gateway. |
| "`mount -a` fails silently when EFS is unreachable." | It fails loudly, and under `set -e` the whole script stops. Check `/var/log/cloud-init-output.log`. |
| "Metrics from the agent appear in the EC2 namespace." | They appear in **`CWAgent`**, with dimensions from the config (`InstanceId`, `path`). Alarms in Post 14 use that namespace. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| `private_subnet_ids`, `vpc_id` | `20-network` |
| `kms_key_arn`, `app_sg_id`, `vpce_sg_id` | `30-security` |
| `data_bucket_arn`, `efs_id`, `efs_access_point_id` | `40-data` |

| You create here | Used by |
|---|---|
| Instance `plat-ec2` | Test bench for every later stack; target of the EC2 state-change rule in Post 11 |
| Role `plat-ec2-role` | Alarms and dashboards in Post 14 read the instance's metrics |
| Parameter `AmazonCloudWatch-plat` | The agent on the instance |
| Outputs: `instance_id`, `role_name`, `role_arn` | Verification script, observability |

### Console clicks you no longer make

| In the AWS series you... | Here it is |
|---|---|
| **EC2, Launch instance**: name, AMI, type, network, security group, advanced details | `aws_instance.this` |
| **IAM, Create role** for EC2, attach two managed policies, add inline policy | `aws_iam_role.ec2` + attachments + `aws_iam_role_policy` |
| **Systems Manager, Parameter Store, Create parameter** for the agent | `aws_ssm_parameter.cwagent` |
| Paste the boot commands into **User data** | `templatefile(...)` |
| **VPC, Endpoints, Create endpoint** three times | `aws_vpc_endpoint.ssm` with `for_each` |

---

## Lab: Test Everything From Inside 🛠️

You need the Session Manager plugin for the AWS CLI on your computer (`session-manager-plugin --version`).

### 1. Plan and apply, with the endpoints

```bash
export AWS_PROFILE=plat-admin AWS_REGION=us-east-1
scripts/tf.sh 50-ec2 plan -var enable_ssm_endpoints=true
```

```
Plan: 10 to add, 0 to change, 0 to destroy.
```

Seven are the stack itself (role, two attachments, inline policy, profile, parameter, instance) and three are the endpoints. Apply:

```bash
scripts/tf.sh 50-ec2 apply -var enable_ssm_endpoints=true
```

### 2. Wait for the instance to register

```bash
IID=$(terraform -chdir=stacks/50-ec2 output -raw instance_id)
aws ssm describe-instance-information --filters Key=InstanceIds,Values=$IID \
  --query 'InstanceInformationList[0].[PingStatus,PlatformName,AgentVersion]' --output text
```

For the first minute or two this prints `None`. Then:

```
Online  Amazon Linux  3.3.2299.0
```

### 3. Open a session

```bash
aws ssm start-session --target $IID
```

Inside the session:

```bash
# IMDSv2 is enforced: no token, no answer
curl -s -o /dev/null -w '%{http_code}\n' http://169.254.169.254/latest/meta-data/instance-id
TOKEN=$(curl -s -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 60')
curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/instance-id; echo
```

```
401
i-0a1b2c3d4e5f67890
```

### 4. Prove EFS from inside

```bash
df -h /mnt/ml | tail -1
sudo -u ssm-user sh -c 'echo hello > /mnt/ml/from-ec2.txt' ; ls -ln /mnt/ml
```

```
127.0.0.1:/     8.0E     0  8.0E   0% /mnt/ml
-rw-r--r--. 1 1000 1000 6 Nov  9 09:14 from-ec2.txt
```

The file is owned by **1000:1000** although the command ran as a different user: that is the access point's `PosixUser` from Post 07. Two security groups and a policy were involved in getting this to work, and you have just exercised both of them.

### 5. Prove the role, with and without the key

Get the bucket name on your computer with `terraform -chdir=stacks/40-data output -raw data_bucket`, then in the session set `B` to it:

```bash
echo "from ec2" > /tmp/e.txt
aws s3 cp /tmp/e.txt s3://$B/raw/from-ec2.txt
aws s3 cp s3://$B/raw/from-ec2.txt - 
```

```
upload: ../../tmp/e.txt to s3://plat-data-123456789012-us-east-1/raw/from-ec2.txt
from ec2
```

The instance used its role's credentials, delivered through the metadata service, and the `UseDataKey` statement made the object readable.

### 6. Prove the database port, if RDS is on

If you switched `enable_rds` on in Post 07:

```bash
H=$(aws rds describe-db-instances --db-instance-identifier plat-meta --query 'DBInstances[0].Endpoint.Address' --output text)
nc -zv -w 3 $H 5432
```

```
Ncat: Connected to 10.20.11.52:5432.
```

The instance is in `plat-app-sg`, the only source `plat-rds-sg` allows. A machine in any other group gets a timeout, not a refusal: security groups drop silently.

Leave the session with `exit`.

### 7. See the agent's metrics

After about five minutes:

```bash
aws cloudwatch list-metrics --namespace CWAgent --query 'Metrics[].MetricName' --output text | tr '\t' '\n' | sort -u
```

```
disk_used_percent
mem_used_percent
```

### 8. Break it: take the path away

```bash
scripts/tf.sh 50-ec2 plan
```

```
  # aws_vpc_endpoint.ssm["ec2messages"] will be destroyed
  # aws_vpc_endpoint.ssm["ssm"] will be destroyed
  # aws_vpc_endpoint.ssm["ssmmessages"] will be destroyed
Plan: 0 to add, 0 to change, 3 to destroy.
```

A plain plan removes the endpoints, because the toggle defaults to false and the variable is not stored. Apply it, then check from your computer:

```bash
scripts/tf.sh 50-ec2 apply
sleep 300
aws ssm describe-instance-information --filters Key=InstanceIds,Values=$IID --query 'InstanceInformationList[0].PingStatus' --output text
aws ssm start-session --target $IID
```

```
ConnectionLost
An error occurred (TargetNotConnected) when calling the StartSession operation: i-0a1b2c3d4e5f67890 is not connected.
```

The instance is running and healthy and **unreachable**, because the only route to Systems Manager was deleted. This is the failure people meet when they harden a network without knowing what the agent needs. Restore it with `-var enable_ssm_endpoints=true` (or turn on the NAT in `20-network`), and the status returns to `Online` in a minute or two.

### 9. Cause drift on the instance

```bash
aws ec2 modify-instance-metadata-options --instance-id $IID --http-tokens optional
scripts/tf.sh 50-ec2 plan -var enable_ssm_endpoints=true
```

```
  # aws_instance.this[0] will be updated in-place
  ~ metadata_options {
      ~ http_tokens = "optional" -> "required"
    }

Plan: 0 to add, 1 to change, 0 to destroy.
```

Someone loosened the metadata protection by hand, and the plan found it. Apply to put it back; metadata options change in place, with no reboot.

### 10. Resources you now have 📦

| Resource | Name | Notes |
|---|---|---|
| IAM role + profile | `plat-ec2-role` | SSM, CloudWatch agent, bucket and key access |
| SSM parameter | `AmazonCloudWatch-plat` | Agent configuration |
| EC2 instance | `plat-ec2` | Private subnet a, IMDSv2, encrypted root volume |
| Interface endpoints | `plat-ssm-vpce`, `plat-ssmmessages-vpce`, `plat-ec2messages-vpce` | **Hourly cost.** Only with `enable_ssm_endpoints` |

### Cleanup 🧹

The endpoints are the expensive part. `make pause` switches them off together with the other hourly pieces. To remove the instance too: `scripts/tf.sh 50-ec2 apply -var enable_ec2=false`. The role and parameter are free.

---

## Quick Quiz 🧠

**Q1.** The instance is running, its role is correct, and `describe-instance-information` returns nothing. What are the two possible causes in this network?

<details>
<summary>Show answer</summary>

The agent cannot reach `ssm`, `ssmmessages` and `ec2messages`: there is **no NAT gateway and no interface endpoints** (or the endpoint security group does not allow 443 from the instance). A missing `AmazonSSMManagedInstanceCore` on the role gives the same symptom, so check both the path and the role.

</details>

**Q2.** Why is `ignore_changes = [ami]` set, and how do you deliberately move to a new AMI?

<details>
<summary>Show answer</summary>

The AMI id comes from a parameter AWS updates every few weeks; without `ignore_changes`, each update plans a **replacement of the running instance**. To move on purpose, force it: `terraform apply -replace='aws_instance.this[0]'`.

</details>

**Q3.** What does `http_tokens = "required"` protect against?

<details>
<summary>Show answer</summary>

It forces IMDSv2, where a token obtained with a `PUT` request must accompany each metadata call. A server-side request forgery bug in an application usually can only make `GET` requests, so it can no longer read the role's temporary credentials.

</details>

**Q4.** Why does editing `userdata.sh.tftpl` replace the instance instead of updating it?

<details>
<summary>Show answer</summary>

User data executes once, at first boot. Changing it on a running machine would have no effect, so `user_data_replace_on_change = true` makes Terraform build a new instance that runs the new script.

</details>

**Q5.** Why must the instance policy contain a `kms:*` statement for a bucket it already has `s3:GetObject` on?

<details>
<summary>Show answer</summary>

The bucket's default encryption uses the customer managed key `plat-data`. S3 allows the read, then asks KMS to decrypt the object's data key, and **KMS evaluates permissions separately**. Without `kms:Decrypt` the read fails with AccessDenied.

</details>

---

## What's Next? 🚀

Now that we can test from inside the network, we can put something real in it: a container image, a cluster to run it, and a load balancer in front.

👉 [Post 09: Containers on ECS: ECR, Fargate and an Application Load Balancer](content/aws-terraform/09-ecs-fargate-and-the-alb.md)

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
