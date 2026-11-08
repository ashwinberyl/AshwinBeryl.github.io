---
title: "RDS and DynamoDB"
date: 2026-11-08
tags: [aws, rds, postgresql, dynamodb, databases, secrets-manager, kms, gsi, intermediate]
description: Post 8 of the AWS series. When to choose a relational database and when a key-value table, how Multi-AZ, backups and managed credentials really work in RDS, how DynamoDB keys, indexes and capacity decide your fate, and a lab that builds a private Postgres instance and the platform's jobs table.
---

# Two Databases, Two Different Questions 🗄️

The platform has two kinds of state, and they want different homes.

**Metadata about datasets** (names, where they live, row counts) is small, relational and queried in flexible ways. That wants **RDS**. **Job status** (is job 42 done?) is looked up by ID, written constantly and needs to stay fast no matter how many jobs exist. That wants **DynamoDB**.

Choosing between them isn't about fashion. It's about the questions you'll ask, and in this post we build both and see what each does well.

---

## Choosing: The Questions You'll Ask ❓

| | **RDS (PostgreSQL)** | **DynamoDB** |
|---|---|---|
| **Model** | Tables, joins, SQL | Items in a table, found by key |
| **Queries** | Anything you can write in SQL | Only by **primary key or index**. You design for the access pattern *in advance* |
| **Scaling** | Bigger instance, plus read replicas | Automatic and **horizontal**. No instance to size |
| **Billing** | Per instance-hour plus storage, **even when idle** | **Per request** (on-demand) or per provisioned capacity |
| **Network** | **Inside your VPC**, with an ENI and a security group | A **public regional service**. Reached privately via the gateway endpoint (Post 04) |
| **Good for** | Reporting, flexible queries, relational integrity | Key lookups, sessions, job state, huge scale with predictable access |

If you don't yet know how you'll query the data, start with RDS. If you know exactly how it'll be read and need it to scale without tuning, DynamoDB is ideal.

---

## RDS in Five Ideas 🐘

**1. It's a managed instance, not a managed schema.** AWS patches, backs up and fails over the database server. *You* still own schemas, indexes and queries.

**2. Multi-AZ is about availability, not reads.**

| Option | What it is | Standby readable? |
|---|---|---|
| **Single-AZ** | One instance | n/a |
| **Multi-AZ instance** | A **synchronous standby** in another AZ, automatic failover | **No** |
| **Multi-AZ DB cluster** | One writer plus two **readable** standbys (PostgreSQL, MySQL) | **Yes** |
| **Read replica** | An **asynchronous** copy for scaling reads (also usable cross-region) | Yes |

**3. Backups are two different things.**

| | **Automated backups** | **Manual snapshots** |
|---|---|---|
| Created | Daily plus transaction logs | When you ask |
| Retention | **0 to 35 days** | **Until you delete them** |
| Point-in-time restore | **Yes** | No |
| On instance deletion | Removed (unless you choose to retain) | **Kept** |

**4. Configuration lives in parameter groups.** Dynamic parameters apply at once. **Static** ones show `pending-reboot` until you restart the instance.

**5. Credentials can be managed for you.** RDS can create the master password **in Secrets Manager**, encrypted with your KMS key, and **rotate it automatically** (every seven days by default). Applications fetch it at runtime and never see a stale password.

---

## DynamoDB in Five Ideas ⚡

**1. The primary key decides everything.** A table needs a **partition key** and optionally a **sort key**. DynamoDB hashes the partition key to pick a physical partition. A *good* key has **many distinct values** and spreads traffic evenly.

**2. Query is cheap. Scan is not.**

| Operation | What it does | Cost |
|---|---|---|
| **GetItem** | One item by full key | Tiny |
| **Query** | Items with one partition key value, optionally a sort key range | Proportional to what it **returns** |
| **Scan** | Reads **every item** in the table | Proportional to the **whole table**, even if a filter hides most results |

**3. Indexes give you more access patterns.** A **global secondary index (GSI)** is a second copy of the data under a different key. A **local secondary index (LSI)** shares the partition key and can **only be created with the table**.

**4. Capacity modes.** **On-demand** charges per request and scales automatically. **Provisioned** (with auto scaling) is cheaper at steady, predictable load.

**5. Consistency is a choice.** Reads are **eventually consistent** by default. Pass `ConsistentRead` for a strongly consistent read (twice the read cost, and **not available on GSIs**).

![The Platform Lab's two databases](content/aws/images/08-databases.svg)

---

## Nuances & Misconceptions 🧩

### RDS

| What people assume | What's actually true |
|---|---|
| "Multi-AZ gives me a read replica." | The **standby in a Multi-AZ instance can't serve reads**. It only takes over on failure. Use a read replica or a Multi-AZ DB cluster to read from a second node. |
| "Read replicas are always up to date." | They're **asynchronous**, so reads can lag the primary. Don't read-your-own-writes from a replica. |
| "`Publicly accessible = No` is all the security I need." | That only stops a **public IP** being assigned. You still need a **security group** that allows only the callers you intend, and the instance should be in **private subnets**. |
| "A stopped RDS instance stays stopped." | AWS **starts it again after 7 days**. Delete it if you won't use it. |
| "Storage can shrink if I delete data." | Allocated storage **can only grow**. Shrinking means restoring into a smaller new instance. |
| "Deleting the instance keeps my backups." | **Automated backups are deleted with the instance** unless you choose to retain them. Take a **final snapshot** to keep your data. |
| "I'm the superuser." | RDS gives you **`rds_superuser`**, a powerful role that is **not** true superuser. Some extensions and settings are managed by AWS. |
| "The instance has a stable IP." | Use the **endpoint DNS name**. The IP changes on failover and maintenance. |
| "The managed master secret works like a normal secret." | RDS **owns** it and rotates it. Apps must **fetch it at runtime**, never copy the password into code, and you can't casually edit its value. |
| "Encryption can be enabled later." | **Storage encryption is chosen at creation.** To encrypt an unencrypted instance, copy a snapshot with encryption on and restore from it. |
| "`db.t4g.micro` is fine for production." | **Burstable** instances run on CPU credits. A sustained load drains them and throttles the database. |

### DynamoDB

| What people assume | What's actually true |
|---|---|
| "On-demand means unlimited instant scale." | It adapts quickly, but a sudden jump far above recent peaks can still **throttle**. It isn't a substitute for a good key design. |
| "A Scan with a filter is cheap because few items match." | The filter runs **after** the read. You pay for **everything scanned**, and `ScannedCount` shows it. |
| "I can query by any attribute." | Only by the **table key or an index**. Anything else is a Scan. Design access patterns first. |
| "`status` is a fine attribute name." | `status`, `name`, `date` and many others are **reserved words**. You must alias them with `ExpressionAttributeNames` (`#s`) in expressions. |
| "Reads are always up to date." | Default reads are **eventually consistent**. Use `ConsistentRead=true` on the table (not on a GSI) when you need the latest value. |
| "TTL deletes items at the exact time." | Expired items are removed **typically within a few days** (often within 48 hours) and may still appear in reads until then. Filter on the expiry time in queries if it matters. |
| "A hot key is fine because DynamoDB scales." | A single partition key value has a **per-partition throughput ceiling**. One very popular key (`status = DONE` on a huge table) concentrates load. |
| "GSIs are free copies." | Each GSI **stores a copy and charges for its writes**. A throttled GSI can also **slow writes to the base table**. |
| "Items can be any size." | **400 KB** per item, including attribute names. Large payloads belong in S3, with a pointer in the item. |
| "Numbers are numbers." | The API sends numbers as **strings** (`{"N": "5050"}`), and SDKs may return `Decimal` types. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| `plat-vpc`, private subnets, the **DynamoDB gateway endpoint** | Post 04 |
| `plat-app-sg` and the VPC CloudShell `plat-shell` | Post 05 |
| KMS key `alias/plat-data` | Post 05 |
| The security group pattern | Post 07 |

| You create here | Used by |
|---|---|
| **RDS `plat-meta`**, its managed secret and `plat-rds-sg` | The API's `/datasets` route on ECS (Post 11) |
| **DynamoDB `plat-jobs`** and its GSI `status-created_idx` | The Lambda ingester (13), the nightly report (14), the API's `/jobs` route (11, 12) |
| The conditional-write idempotency pattern | Posts 13 and 14, because SQS delivers **at least once** |

---

## Lab: A Private Postgres and a Jobs Table 🛠️

Sign in as Jim in **N. Virginia**. The NAT gateway from Post 04 must be running.

### Part A: RDS

#### 1. Create the security group

1. **VPC, Security groups, Create security group.**
2. Name **`plat-rds-sg`**, description `PostgreSQL access`, VPC `plat-vpc`.
3. **Inbound rule:** type **PostgreSQL** (TCP 5432), **Source:** security group **`plat-app-sg`**.
4. Tag `project = plat` and create it.

#### 2. Create a DB subnet group

1. Open **RDS**, **Subnet groups**, **Create DB subnet group**.
2. Name **`plat-db-subnets`**, description `Private subnets`, VPC `plat-vpc`.
3. Availability Zones: **us-east-1a** and **us-east-1b**. Subnets: **`plat-private-a`** (10.20.10.0/24) and **`plat-private-b`** (10.20.11.0/24).
4. Create it.

A subnet group tells RDS *which* subnets it may place instances in. It must cover **at least two AZs**, even for a single-AZ instance.

#### 3. Create the database

**Databases, Create database**, then **Standard create**:

| Setting | Value |
|---|---|
| Engine | **PostgreSQL** (the default recent version offered) |
| Template | **Dev/Test** (or the Free tier or Sandbox template if the console offers one) |
| Availability | **Single-AZ / Single DB instance** |
| DB instance identifier | `plat-meta` |
| Master username | `platadmin` |
| Credentials management | **Managed in AWS Secrets Manager**, encryption key **`plat-data`** |
| Instance class | **Burstable, `db.t4g.micro`** |
| Storage | **gp3**, **20 GiB**. Turn **storage autoscaling** off |
| Compute resource | **Don't connect to an EC2 compute resource** |
| VPC | `plat-vpc`, DB subnet group **`plat-db-subnets`** |
| Public access | **No** |
| VPC security group | **Choose existing: `plat-rds-sg`**, and remove `default` |
| Initial database name | `platmeta` |
| Backup retention | **1 day** |
| Encryption | Enabled, KMS key **`plat-data`** |
| Performance Insights | Off for the lab |
| Deletion protection | Off for the lab |
| Tags | `project = plat` |

Create the database. It takes **five to ten minutes** to become *Available*.

#### 4. Read the managed secret

```bash
aws rds describe-db-instances --db-instance-identifier plat-meta \
  --query 'DBInstances[0].[Endpoint.Address,MasterUserSecret.SecretArn,MasterUserSecret.SecretStatus]' \
  --output text
```

```text
plat-meta.cabc1234xyz.us-east-1.rds.amazonaws.com   arn:aws:secretsmanager:us-east-1:123456789012:secret:rds!db-1234abcd-...   active
```

Note the endpoint and the **secret ARN**. The secret name starts with `rds!`. That prefix marks a secret **managed by RDS**.

#### 5. Connect from inside the VPC

Open the **`plat-shell`** CloudShell (the VPC one) and install a client:

```bash
sudo dnf install -y postgresql16        # if not found, run: dnf search postgresql
```

Set variables (replace both with your own values from step 4):

```bash
ENDPOINT=plat-meta.cabc1234xyz.us-east-1.rds.amazonaws.com
SECRET_ARN=arn:aws:secretsmanager:us-east-1:123456789012:secret:rds!db-1234abcd-...

export PGPASSWORD=$(aws secretsmanager get-secret-value --secret-id "$SECRET_ARN" \
  --query SecretString --output text \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['password'])")

psql "host=$ENDPOINT port=5432 dbname=platmeta user=platadmin sslmode=require"
```

At the `platmeta=>` prompt:

```sql
CREATE TABLE datasets (
  id         serial PRIMARY KEY,
  name       text NOT NULL,
  s3_key     text NOT NULL,
  row_count  integer,
  created_at timestamptz DEFAULT now()
);

INSERT INTO datasets (name, s3_key, row_count)
VALUES ('events', 'raw/events.csv', 5050);

SELECT id, name, s3_key, row_count FROM datasets;
\q
```

```text
 id |  name  |     s3_key     | row_count
----+--------+----------------+-----------
  1 | events | raw/events.csv |      5050
```

Three connections made this work: a **route** (same VPC), a **security group** (`plat-app-sg` to `plat-rds-sg` on 5432) and **credentials** (the secret, decrypted through KMS). If it had failed, you'd know which three things to check, and in that order.

#### 6. Prove the isolation

From a **regular** CloudShell (outside the VPC), try to reach the endpoint:

```bash
timeout 5 bash -c "</dev/tcp/$ENDPOINT/5432" && echo OPEN || echo BLOCKED
```

It resolves to a **private** IP and gives `BLOCKED`. The database has no public address, and nothing outside the VPC has a route to it.

### Part B: DynamoDB

#### 7. Create the table

1. Open **DynamoDB**, **Create table**.
2. Table name **`plat-jobs`**. Partition key **`job_id`** (String). No sort key.
3. **Table settings: Customize settings.**
4. **Read/write capacity settings: On-demand.**
5. **Secondary indexes, Create global index:** partition key **`status`** (String), sort key **`created_at`** (String), index name **`status-created_idx`**, projection **All**.
6. **Encryption at rest:** **Stored in your account, owned by you** (customer managed key), select **`plat-data`**.
7. Tag `project = plat` and create the table.

When it's *Active*, open **Additional settings**:

- **Time to Live (TTL):** turn on, attribute name **`expires_at`**.
- **Backups, Point-in-time recovery:** turn on.

#### 8. Put, get and query

```bash
for item in \
 '{"job_id":{"S":"job-001"},"status":{"S":"DONE"},"created_at":{"S":"2026-11-08T09:00:00Z"},"rows":{"N":"5050"}}' \
 '{"job_id":{"S":"job-002"},"status":{"S":"RUNNING"},"created_at":{"S":"2026-11-08T09:05:00Z"}}' \
 '{"job_id":{"S":"job-003"},"status":{"S":"DONE"},"created_at":{"S":"2026-11-08T09:10:00Z"},"rows":{"N":"120"}}' \
 '{"job_id":{"S":"job-004"},"status":{"S":"FAILED"},"created_at":{"S":"2026-11-08T09:15:00Z"}}'
do
  aws dynamodb put-item --table-name plat-jobs --item "$item"
done

aws dynamodb get-item --table-name plat-jobs --key '{"job_id":{"S":"job-001"}}'
```

Now the indexed query. `status` is a reserved word, so it needs an alias:

```bash
aws dynamodb query --table-name plat-jobs --index-name status-created_idx \
  --key-condition-expression "#s = :s" \
  --expression-attribute-names '{"#s":"status"}' \
  --expression-attribute-values '{":s":{"S":"DONE"}}' \
  --return-consumed-capacity TOTAL \
  --query '{Count:Count,ScannedCount:ScannedCount,Capacity:ConsumedCapacity.CapacityUnits}'
```

```json
{
    "Count": 2,
    "ScannedCount": 2,
    "Capacity": 0.5
}
```

Compare it with a Scan that does the same filtering:

```bash
aws dynamodb scan --table-name plat-jobs \
  --filter-expression "#s = :s" \
  --expression-attribute-names '{"#s":"status"}' \
  --expression-attribute-values '{":s":{"S":"DONE"}}' \
  --return-consumed-capacity TOTAL \
  --query '{Count:Count,ScannedCount:ScannedCount,Capacity:ConsumedCapacity.CapacityUnits}'
```

```json
{
    "Count": 2,
    "ScannedCount": 4,
    "Capacity": 0.5
}
```

Same answer, but `ScannedCount` is **4**: the Scan read every item and then discarded two. With four rows it costs the same. With forty million, the Query still touches only matching entries while the Scan reads the whole table.

#### 9. Make a write idempotent

SQS delivers messages at least once, so a handler may process the same job twice. DynamoDB can refuse the duplicate:

```bash
aws dynamodb put-item --table-name plat-jobs \
  --item '{"job_id":{"S":"job-001"},"status":{"S":"QUEUED"}}' \
  --condition-expression "attribute_not_exists(job_id)"
```

```text
An error occurred (ConditionalCheckFailedException) when calling the PutItem operation:
The conditional request failed
```

The write was **rejected**, and `job-001` still says `DONE`. We'll rely on this pattern in Posts 13 and 14.

#### 10. Confirm encryption

```bash
aws dynamodb describe-table --table-name plat-jobs \
  --query 'Table.SSEDescription.[Status,SSEType,KMSMasterKeyArn]' --output text
```

```text
ENABLED   KMS   arn:aws:kms:us-east-1:123456789012:key/1234abcd-...
```

### 11. Resources you now have 📦

| Resource | Name | Notes |
|---|---|---|
| Security group | `plat-rds-sg` | 5432 from `plat-app-sg` |
| DB subnet group | `plat-db-subnets` | Private subnets, two AZs |
| RDS instance | `plat-meta` (PostgreSQL, `db.t4g.micro`) | Private, encrypted, managed secret. **Hourly cost** |
| Secret | `rds!db-...` | Owned by RDS, rotates every 7 days |
| Table | `datasets` (in `platmeta`) | One row |
| DynamoDB table | `plat-jobs` + GSI `status-created_idx` | On-demand, KMS, TTL on `expires_at`, PITR on |

### Cleanup 🧹

| Keep | Pause or delete |
|---|---|
| DynamoDB table (on-demand costs nothing when idle, apart from a few cents of storage), subnet group, security group | **RDS instance:** a *stopped* instance restarts itself after 7 days and still bills for storage. For anything longer than a day, **take a manual snapshot, then delete the instance**. You'll restore from that snapshot when you need it again (Post 11) |

To delete: **RDS, Databases, `plat-meta`, Actions, Delete**. Choose **Create final snapshot** (name it `plat-meta-final`) and untick **Retain automated backups**. To restore later: **Snapshots, `plat-meta-final`, Actions, Restore snapshot**, then set the same subnet group and security group.

---

## Quick Quiz 🧠

**Q1.** Your Multi-AZ RDS instance is slow under read load. A colleague says "just read from the standby". Why won't that work?

<details>
<summary>Show answer</summary>

In a **Multi-AZ instance deployment**, the standby is only for **failover**. It's not readable. To offload reads you need a **read replica** or a **Multi-AZ DB cluster**, whose standbys are readable (with the usual asynchronous replica lag for replicas).

</details>

**Q2.** You delete an RDS instance with automated backups and no final snapshot. Can you restore it?

<details>
<summary>Show answer</summary>

**No**, unless you chose to retain automated backups. Automated backups are deleted with the instance by default, and manual snapshots are the only kind that survive deletion. Always take a final snapshot of data you care about.

</details>

**Q3.** A Query on a GSI returns `Count: 2, ScannedCount: 2`. A Scan with a filter returns `Count: 2, ScannedCount: 4`. Which one scales with table size, and why?

<details>
<summary>Show answer</summary>

The **Scan**. It reads every item and applies the filter afterwards, so cost and time grow with the whole table even when few items match. A Query uses the key (or index key) to touch only the matching items.

</details>

**Q4.** Your `UpdateItem` fails with a validation error about `status`. What's the fix?

<details>
<summary>Show answer</summary>

`status` is a **DynamoDB reserved word**. Alias it in the expression: use `#s` and supply `ExpressionAttributeNames: {"#s": "status"}`.

</details>

**Q5.** A job message is delivered twice. How does `attribute_not_exists(job_id)` make the second write safe?

<details>
<summary>Show answer</summary>

It makes `PutItem` succeed **only if no item with that key exists**. The second attempt fails with `ConditionalCheckFailedException`, leaving the original untouched, so the duplicate delivery is harmless. That's an **idempotent write**.

</details>

---

## What's Next? 🚀

We now have the network, the keys, the data stores and the firewalls. Time for something to *run*. Before we launch a server or a container, we need two foundations that every compute service assumes: how to work comfortably on Linux, and how to build and run a container image locally.

👉 **[Post 09: Linux and Docker Fundamentals](content/aws/09-linux-and-docker.md)**: the commands you'll use on every instance, and the `plat-api` container image the rest of the series deploys.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
