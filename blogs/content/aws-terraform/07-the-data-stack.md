---
title: "The Data Stack: S3, DynamoDB, RDS and EFS"
date: 2026-11-08
tags: [aws, terraform, s3, dynamodb, rds, efs, kms, snapshots, intermediate]
description: Post 7 of the AWS on Terraform series. The data lake bucket from the module, the jobs table with its index, TTL and point-in-time recovery, a Postgres instance with a managed password and a snapshot-restore path, and a shared file system, in one stack, with the S3-allowed-KMS-denied failure reproduced from code.
---

# Where the Data Lives 🗄️

This is the stack the rest of the platform reads and writes. It combines the AWS series Posts 06, 07 and 08 into `stacks/40-data`, and it is the first stack that uses **everything** before it: the network for subnets, the security stack for the key and the client group, and the S3 module for the bucket.

---

## The Pieces 🧱

| Piece | Resource(s) | Always on? |
|---|---|---|
| Data lake bucket `plat-data-<account>-<region>` | `module "data_bucket"` | Yes |
| Jobs table `plat-jobs` + index `status-created_idx` | `aws_dynamodb_table.jobs` | Yes |
| Postgres `plat-meta` + subnet group + `plat-rds-sg` | `aws_db_instance.meta`, `aws_db_subnet_group.meta`, `aws_security_group.rds` | **Toggle** `enable_rds` (hourly cost) |
| File system `plat-efs`, mount targets, access point `plat-ml-ap`, `plat-efs-sg` | `aws_efs_*` | Yes (free until you store data) |

![The data stack](content/aws-terraform/images/07-data-stack.svg)

### What it reads from other stacks

```hcl
# stacks/40-data/main.tf
locals {
  account_id = data.aws_caller_identity.current.account_id
  vpc_id     = data.terraform_remote_state.network.outputs.vpc_id
  vpc_cidr   = data.terraform_remote_state.network.outputs.vpc_cidr
  private    = data.terraform_remote_state.network.outputs.private_subnet_ids
  kms_arn    = data.terraform_remote_state.security.outputs.kms_key_arn
  app_sg_id  = data.terraform_remote_state.security.outputs.app_sg_id
}
```

Every value is an output of `20-network` or `30-security`. Reading them is two `terraform_remote_state` data sources (Post 05), and the stack has no input variables for ids at all.

---

## Reading the Stack 📖

### The bucket

The call you saw in Post 06 is the whole bucket: name from the account id and region, encrypted with the shared key, the three prefixes, and the two lifecycle rules (`housekeeping`, `raw-to-ia`). `force_destroy_bucket` defaults to `true` so the lab can be torn down; set it to `false` for data you care about.

### The jobs table

```hcl
# stacks/40-data/main.tf
resource "aws_dynamodb_table" "jobs" {
  name         = "plat-jobs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "job_id"

  deletion_protection_enabled = var.jobs_table_deletion_protection

  attribute {
    name = "job_id"
    type = "S"
  }

  attribute {
    name = "status"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "status-created_idx"
    projection_type = "ALL"

    key_schema {
      attribute_name = "status"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "created_at"
      key_type       = "RANGE"
    }
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = local.kms_arn
  }
}
```

Four details that decide behaviour:

* **Only key attributes are declared.** DynamoDB is schemaless; `attribute` blocks exist solely for attributes used in a key or index (`job_id`, `status`, `created_at`). Declaring an unused attribute is an error.
* **The index is part of the table resource.** `global_secondary_index` with its own `key_schema` blocks. Adding or removing an index later is an in-place change; DynamoDB builds it in the background.
* **TTL is a table setting**, not per item. The attribute `expires_at` must hold an epoch-seconds **number** for items to expire.
* **Encryption uses the shared customer managed key**, as in the AWS series. That has a consequence for callers, covered in the nuances.

### The database

```hcl
# stacks/40-data/main.tf
resource "aws_db_instance" "meta" {
  count = var.enable_rds ? 1 : 0

  identifier     = "plat-meta"
  engine         = "postgres"
  engine_version = "16"
  instance_class = "db.t4g.micro"

  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true
  kms_key_id        = local.kms_arn

  db_name  = var.restore_snapshot_identifier == null ? "platmeta" : null
  username = var.restore_snapshot_identifier == null ? "platadmin" : null

  manage_master_user_password   = true
  master_user_secret_kms_key_id = local.kms_arn

  snapshot_identifier = var.restore_snapshot_identifier

  db_subnet_group_name   = aws_db_subnet_group.meta[0].name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false
  multi_az               = false

  backup_retention_period   = 1
  skip_final_snapshot       = var.rds_skip_final_snapshot
  final_snapshot_identifier = var.rds_skip_final_snapshot ? null : "plat-meta-final"
  deletion_protection       = false
  apply_immediately         = true

  tags = { Name = "plat-meta" }
}
```

Read the interesting lines:

* `count = var.enable_rds ? 1 : 0`. Off by default, because an idle `db.t4g.micro` still bills.
* `manage_master_user_password = true` with `master_user_secret_kms_key_id`. **Terraform never sees the password.** RDS generates it, stores it in Secrets Manager encrypted with our key, and rotates it. Applications fetch it at runtime. This is the answer to "secrets in state" from Posts 01 and 05.
* `snapshot_identifier` plus `db_name`/`username` set to `null` when restoring. When you restore from a snapshot, the database name and user come **from the snapshot**; supplying them is an error.
* `skip_final_snapshot = false` with `final_snapshot_identifier = "plat-meta-final"`. Destroying the instance leaves a snapshot behind, exactly the delete flow in the AWS series.

### The file system

```hcl
# stacks/40-data/main.tf
resource "aws_efs_file_system" "this" {
  creation_token   = "plat-efs"
  encrypted        = true
  kms_key_id       = local.kms_arn
  performance_mode = "generalPurpose"
  throughput_mode  = "elastic"

  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }

  tags = { Name = "plat-efs" }
}

resource "aws_efs_mount_target" "this" {
  for_each = local.private

  file_system_id  = aws_efs_file_system.this.id
  subnet_id       = each.value
  security_groups = [aws_security_group.efs.id]
}

resource "aws_efs_access_point" "ml" {
  file_system_id = aws_efs_file_system.this.id

  posix_user {
    uid = 1000
    gid = 1000
  }

  root_directory {
    path = "/ml"

    creation_info {
      owner_uid   = 1000
      owner_gid   = 1000
      permissions = "0755"
    }
  }

  tags = { Name = "plat-ml-ap" }
}
```

`for_each = local.private` creates one mount target per private subnet, keyed `a` and `b`. The access point makes everyone who mounts through it appear as user **1000** inside `/ml`, whatever their real user id (AWS series Post 07).

The file system policy enforces TLS:

```hcl
# stacks/40-data/main.tf
data "aws_iam_policy_document" "efs" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["*"]
    resources = [aws_efs_file_system.this.arn]

    principals {
      type        = "AWS"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  # With no policy EFS lets any client with network access in; keep that, add only the TLS rule.
  statement {
    sid       = "AllowNetworkClients"
    actions   = ["elasticfilesystem:ClientMount", "elasticfilesystem:ClientWrite"]
    resources = [aws_efs_file_system.this.arn]

    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
  }
}
```

With no policy, EFS lets in any client that has network access and the right security group. We keep exactly that, in the `Allow` statement, and add one `Deny` for connections without TLS.

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "The role can read the bucket, so it can read the objects." | Not with a customer managed key. **S3 allows, then KMS denies**: `GetObject` also needs `kms:Decrypt` on the key. The lab below reproduces it. |
| "DynamoDB with a customer managed key is transparent to callers." | The principals that read and write the table need permission to use the key too (through IAM or the key policy). Later stacks grant it explicitly to every task and function role. |
| "`terraform destroy` keeps my RDS data." | It keeps a **final snapshot** only if `skip_final_snapshot` is false, and the **second** destroy fails with `DBSnapshotAlreadyExists` unless you delete or rename the old snapshot first. |
| "I'll set `db_name` when restoring, to be safe." | For a snapshot restore the name and master user come from the snapshot. Setting them is an error, so the code passes `null`. |
| "`engine_version = \"16\"` pins version 16.0." | It selects the **major** version; RDS picks the latest minor and may upgrade it later. Terraform tolerates that for a major-only value. |
| "Terraform can read the database password from state." | With `manage_master_user_password` there is no password in state. Only the ARN of the secret is. |
| "A TTL deletes items at the exact second." | Typically within a couple of days. Filter on `expires_at` in queries if it matters (AWS series Post 08). |
| "`aws_dynamodb_table` can change its key later." | The primary key is immutable. Changing `hash_key` replaces the table, and its data. |
| "Deleting the table is blocked by default." | It isn't. Set `deletion_protection_enabled` (the `jobs_table_deletion_protection` variable) for anything real. |
| "EFS mount targets are in my security group automatically." | Each one has its **own** security group list. That's why the `aws_efs_mount_target` sets `security_groups`. |
| "`force_destroy` on a bucket is harmless." | It deletes every object and version on destroy. The right default for a lab, the wrong one for production. |
| "I can bring up RDS and use it immediately." | Create takes 5 to 10 minutes. Terraform waits, so `apply` appears to hang. It isn't. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| `vpc_id`, `vpc_cidr`, `private_subnet_ids` | `20-network` (Post 04) |
| `kms_key_arn`, `app_sg_id` | `30-security` (Post 05) |
| The `s3-bucket` module | Post 06 |
| Role `plat-demo-reader` | `10-identity` (Post 03) |

| You create here | Used by |
|---|---|
| Bucket `plat-data-...` | Lambda ingest, ECS and EKS apps, SageMaker (later posts) |
| Table `plat-jobs` | The API's `/jobs` route, the ingester, the nightly report |
| RDS `plat-meta` + secret | The API's `/datasets` route |
| EFS + `plat-ml-ap` | SageMaker Studio and EC2 clients |
| Outputs: bucket, table ARN, `rds_sg_id`, `efs_sg_id`, access point ARN | Compute and ML stacks |

### Console clicks you no longer make

| In the AWS series you... | Here it is |
|---|---|
| **S3, Create bucket**, versioning, encryption with `plat-data`, Bucket Key, folders, two lifecycle rules | `module "data_bucket"` |
| **DynamoDB, Create table**, partition key, global index, TTL, PITR, encryption | `aws_dynamodb_table.jobs` |
| **RDS, Create database** (about 15 settings), subnet group, security group | `aws_db_instance.meta` + `aws_db_subnet_group` + `aws_security_group.rds` |
| **EFS, Create file system, Customize**, mount targets, **Access points**, policy | `aws_efs_*` |

---

## Lab: Apply the Data Stack 🛠️

### 1. Plan and apply

```bash
export AWS_PROFILE=plat-admin AWS_REGION=us-east-1
scripts/tf.sh 40-data plan
```

```
Plan: 20 to add, 0 to change, 0 to destroy.
```

Ten for the bucket module (seven settings, three prefix objects), one DynamoDB table, two for the RDS security group and its rule, two for the EFS ones, then the file system, two mount targets, the access point and the policy. The database and its subnet group are not in this number because `enable_rds` is off.

```bash
scripts/tf.sh 40-data apply
```

Mount targets take a minute or two to become available.

### 2. Verify the bucket

```bash
B=$(terraform -chdir=stacks/40-data output -raw data_bucket)
aws s3api get-bucket-encryption --bucket $B \
  --query 'ServerSideEncryptionConfiguration.Rules[0].[ApplyServerSideEncryptionByDefault.SSEAlgorithm,BucketKeyEnabled]' --output text
aws s3api get-bucket-lifecycle-configuration --bucket $B --query 'Rules[].ID' --output text
aws s3api list-objects-v2 --bucket $B --query 'Contents[].Key' --output text
```

```
aws:kms  True
housekeeping  raw-to-ia
models/  processed/  raw/
```

### 3. Reproduce "S3 allowed, KMS denied"

Put an object in the bucket as the administrator. The default encryption encrypts it with `plat-data`:

```bash
echo "id,ts" > /tmp/events.csv
aws s3 cp /tmp/events.csv s3://$B/raw/events.csv
```

Now become `plat-demo-reader`, the role from Post 03 whose inline policy allows `s3:ListBucket` and `s3:GetObject` on this bucket:

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
read AK SK TOK < <(aws sts assume-role --role-arn arn:aws:iam::$ACCOUNT:role/plat-demo-reader \
  --role-session-name kms-lab --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' --output text)
as_reader() { env -u AWS_PROFILE AWS_ACCESS_KEY_ID=$AK AWS_SECRET_ACCESS_KEY=$SK AWS_SESSION_TOKEN=$TOK "$@"; }

as_reader aws s3 ls s3://$B/raw/
as_reader aws s3 cp s3://$B/raw/events.csv -
```

```
2026-11-08 10:20:11          6 events.csv

An error occurred (AccessDenied) when calling the GetObject operation: User: arn:aws:sts::123456789012:assumed-role/plat-demo-reader/kms-lab is not authorized to perform: kms:Decrypt on the resource associated with this ARN because no identity-based policy allows the kms:Decrypt action
```

**Listing worked and reading failed.** The S3 policy allowed it, and KMS said no. This is the situation the AWS series built by hand.

Fix it with the switch in `30-security`:

```bash
scripts/tf.sh 30-security plan -var grant_demo_reader_decrypt=true
```

```
Plan: 1 to add, 0 to change, 0 to destroy.
```

```bash
scripts/tf.sh 30-security apply -var grant_demo_reader_decrypt=true
sleep 15
as_reader aws s3 cp s3://$B/raw/events.csv -
```

```
id,ts
```

Wait the few seconds for IAM changes to propagate. That `-var` is not persisted: the next plain apply of `30-security` removes the permission again, which is a handy way to reset the experiment.

### 4. Verify the DynamoDB table

```bash
aws dynamodb describe-table --table-name plat-jobs \
  --query 'Table.[BillingModeSummary.BillingMode,SSEDescription.SSEType,GlobalSecondaryIndexes[0].IndexName]' --output text
aws dynamodb describe-time-to-live --table-name plat-jobs --query TimeToLiveDescription.[TimeToLiveStatus,AttributeName] --output text
aws dynamodb describe-continuous-backups --table-name plat-jobs \
  --query 'ContinuousBackupsDescription.PointInTimeRecoveryDescription.PointInTimeRecoveryStatus' --output text
```

```
PAY_PER_REQUEST  KMS  status-created_idx
ENABLED  expires_at
ENABLED
```

Write two items and query the index:

```bash
aws dynamodb put-item --table-name plat-jobs --item \
  '{"job_id":{"S":"job-001"},"status":{"S":"DONE"},"created_at":{"S":"2026-11-08T10:00:00Z"}}'
aws dynamodb put-item --table-name plat-jobs --item \
  '{"job_id":{"S":"job-002"},"status":{"S":"RUNNING"},"created_at":{"S":"2026-11-08T10:05:00Z"}}'

aws dynamodb query --table-name plat-jobs --index-name status-created_idx \
  --key-condition-expression '#s = :s' --expression-attribute-names '{"#s":"status"}' \
  --expression-attribute-values '{":s":{"S":"DONE"}}' --query 'Items[].job_id.S' --output text
```

```
job-001
```

### 5. Cause drift on the table

Turn point-in-time recovery off behind Terraform's back:

```bash
aws dynamodb update-continuous-backups --table-name plat-jobs \
  --point-in-time-recovery-specification PointInTimeRecoveryEnabled=false
scripts/tf.sh 40-data plan
```

```
  # aws_dynamodb_table.jobs will be updated in-place
  ~ resource "aws_dynamodb_table" "jobs" {
      ~ point_in_time_recovery {
          ~ enabled = false -> true
        }
    }

Plan: 0 to add, 1 to change, 0 to destroy.
```

Apply to turn it back on. This is how you would find out a colleague "temporarily" changed a safety setting: not by asking, but by planning.

### 6. Verify EFS

```bash
aws efs describe-file-systems --query 'FileSystems[].[Name,LifeCycleState,Encrypted,ThroughputMode,PerformanceMode]' --output text
FS=$(terraform -chdir=stacks/40-data output -raw efs_id)
aws efs describe-mount-targets --file-system-id $FS \
  --query 'MountTargets[].[AvailabilityZoneName,IpAddress,LifeCycleState]' --output text
aws efs describe-access-points --file-system-id $FS \
  --query 'AccessPoints[].[Name,RootDirectory.Path,PosixUser.Uid,PosixUser.Gid]' --output text
```

```
plat-efs  available  True  elastic  generalPurpose
us-east-1a  10.20.10.84  available
us-east-1b  10.20.11.37  available
plat-ml-ap  /ml  1000  1000
```

The mount-target addresses sit inside the private subnets, one per AZ. To prove the network path (port 2049 open for `plat-app-sg`, blocked for everything else) we need a client in the VPC, and that arrives with EC2 in Post 08.

### 7. Optional: switch the database on

This step bills by the hour and takes about ten minutes.

```bash
scripts/tf.sh 40-data plan -var enable_rds=true
```

```
Plan: 2 to add, 0 to change, 0 to destroy.
```

The subnet group and the instance.

```bash
scripts/tf.sh 40-data apply -var enable_rds=true
aws rds describe-db-instances --db-instance-identifier plat-meta \
  --query 'DBInstances[0].[DBInstanceStatus,Engine,PubliclyAccessible,StorageEncrypted,MasterUserSecret.SecretArn]' --output text
```

```
available  postgres  False  True  arn:aws:secretsmanager:us-east-1:123456789012:secret:rds!db-1234abcd-...
```

Terraform waited for `available`, and never saw the password. Check that it's **not** in state:

```bash
scripts/tf.sh 40-data state pull | grep -c '"password"'
```

The count is `0`.

### 8. Optional: the snapshot round trip

Switch the database off with a plain apply (the default is `enable_rds = false`):

```bash
scripts/tf.sh 40-data apply
```

```
Plan: 0 to add, 0 to change, 2 to destroy.
```

It creates `plat-meta-final` before deleting the instance, which takes several minutes. Bring it back from the snapshot:

```bash
scripts/tf.sh 40-data apply -var enable_rds=true -var restore_snapshot_identifier=plat-meta-final
```

Data survives. Before the **next** time you switch the database off, delete the old snapshot, or the final snapshot will clash with it:

```bash
aws rds delete-db-snapshot --db-snapshot-identifier plat-meta-final
```

### 9. Resources you now have 📦

| Resource | Name | Notes |
|---|---|---|
| S3 bucket | `plat-data-<account>-<region>` | KMS, versioned, 2 lifecycle rules |
| DynamoDB table | `plat-jobs` | On-demand, KMS, TTL, PITR |
| EFS | `plat-efs`, access point `plat-ml-ap` | Encrypted, elastic |
| Security groups | `plat-rds-sg`, `plat-efs-sg` | |
| RDS instance | `plat-meta` | **Only with `enable_rds`. Hourly cost** |

### Cleanup 🧹

`make pause` switches off every hourly-billed piece (NAT, the endpoint, RDS) and keeps the rest. Everything else in this stack costs cents while empty. Leave it for the next posts.

---

## Quick Quiz 🧠

**Q1.** `plat-demo-reader` can `ListBucket` but `GetObject` fails with a `kms:Decrypt` denial. Which policy needs the change, and why isn't the bucket policy at fault?

<details>
<summary>Show answer</summary>

The role's **IAM policy** (or the key policy) needs to allow `kms:Decrypt` on the `plat-data` key. S3 evaluated and allowed the read; the object's data key is wrapped by KMS, and **KMS evaluates its own permissions separately**. Decrypt permission is deliberately independent of data permission.

</details>

**Q2.** Why does the restore path set `db_name` and `username` to `null`?

<details>
<summary>Show answer</summary>

When an instance is restored from a snapshot, its databases and master user already exist in the snapshot. RDS rejects an attempt to set an initial database name or user at restore time, so the code passes `null` for those attributes when `restore_snapshot_identifier` is set.

</details>

**Q3.** You turn `enable_rds` off, then on again, then off again, with no other changes. The third apply fails. Why?

<details>
<summary>Show answer</summary>

The first destroy created a final snapshot named `plat-meta-final`. The second destroy tries to create a snapshot with the **same name**, and RDS refuses (`DBSnapshotAlreadyExists`). Delete the old snapshot, or give each destroy a unique `final_snapshot_identifier`.

</details>

**Q4.** The RDS master password is "managed". Where does it live, and could someone with only read access to the Terraform state obtain it?

<details>
<summary>Show answer</summary>

It lives in **Secrets Manager**, encrypted with the `plat-data` key, created and rotated by RDS. State contains only the secret's ARN. Reading it requires `secretsmanager:GetSecretValue` on the secret **and** `kms:Decrypt` on the key, so state access alone isn't enough.

</details>

**Q5.** Why does the jobs table declare an attribute block for `created_at` when no item is required to have it?

<details>
<summary>Show answer</summary>

`created_at` is the **sort key of the global secondary index**. DynamoDB needs a type for every attribute used in any key schema (table or index), and nothing else. Other attributes are free-form and must not be declared.

</details>

---

## What's Next? 🚀

The foundation is done: identity, network, security and data, all as code. From here the platform runs things, and the first thing we need is a machine inside the VPC to test it all from.

👉 [Post 08: EC2 and Session Manager: A Private Instance, Reached Without SSH](content/aws-terraform/08-ec2-and-session-manager.md): an instance you reach with no SSH and no open port, which finally lets us test EFS, RDS and the endpoints from inside the VPC.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
