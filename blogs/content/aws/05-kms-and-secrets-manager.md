---
title: "KMS and Secrets Manager"
date: 2026-11-08
tags: [aws, kms, secrets-manager, encryption, envelope-encryption, vpc-endpoints, cloudshell, intermediate]
description: Post 5 of the AWS series. How KMS keys, key policies and envelope encryption actually work, why decrypt permission is separate from data permission, how Secrets Manager stores and versions secrets, and a lab that reads a secret from a private subnet through an interface endpoint.
---

# Encrypted Doesn't Mean Protected 🗝️

"Everything is encrypted" is the sentence that ends security reviews, and it's almost meaningless. Encrypted *by whom*? With *which key*? And who is allowed to ask that key to decrypt?

On AWS, encryption is nearly free to turn on. The real security question is the second one: **who can use the key.** That's what makes KMS important, and it's why this post comes before S3, RDS or anything else that stores data.

We'll also solve a companion problem: where does a database password live so that it never appears in code, a Dockerfile or a screenshot?

---

## KMS: What It Actually Does 🔑

**AWS Key Management Service (KMS)** holds encryption keys inside hardware security modules and **never lets the key material leave**. You don't download a key and encrypt things locally. You send data to KMS and ask it to encrypt or decrypt.

### Three kinds of keys

| Key type | Who manages it | Key policy editable? | Cost | Typical use |
|---|---|---|---|---|
| **AWS owned** | AWS, invisibly | No | Free | Default for some services (e.g. DynamoDB) |
| **AWS managed** (`aws/s3`, `aws/rds`...) | AWS, in your account | **No** | Free | "Encrypt with the default key" |
| **Customer managed** (CMK) | You | **Yes** | ~$1/month per key, plus about $0.03 per 10,000 requests | Anything shared, audited or cross-account |

We use **one customer managed key, `alias/plat-data`**, for the whole platform. An **alias** is a friendly name that points at a key ID, and you can re-point it later without changing any code that uses the alias.

### Envelope encryption

KMS can directly encrypt only **4 KB** of data. For anything bigger (an S3 object, a database volume), services use **envelope encryption**:

1. The service asks KMS for a **data key** (`GenerateDataKey`). KMS returns it twice: **plaintext** and **encrypted under your CMK**.
2. The service encrypts your data locally with the plaintext data key, then **throws the plaintext key away**.
3. It stores the **encrypted** data key right next to the encrypted data.
4. To read: the service sends the encrypted data key to KMS (`Decrypt`), gets the plaintext key back, and decrypts the data.

![Envelope encryption, and a secret read through a private endpoint](content/aws/images/05-kms-secrets.svg)

So *every* read of an encrypted object requires a **KMS permission check**. That's the connection most people miss, and we'll trip over it deliberately in Post 06.

### Who can use a key: the key policy

Every KMS key has a **key policy**, and it's the **only** policy that is mandatory. Other services let IAM alone decide. KMS doesn't.

The default policy that the console creates includes a statement allowing the account's **root principal**. That statement doesn't mean "root can use it". It means "**IAM policies in this account are allowed to grant access to this key**". Remove it, and IAM can no longer help you.

| Role on a key | Can do | Can't do |
|---|---|---|
| **Key administrator** | Manage the key: edit policy, rotate, disable, delete | **Use** it to encrypt or decrypt (unless IAM or the key policy also allows it) |
| **Key user** | Encrypt, decrypt, generate data keys | Change the key |

---

## Secrets Manager: Secrets That Know How to Rotate 🔒

**AWS Secrets Manager** stores values like database passwords and API keys, encrypted with a KMS key, and gives you:

| Feature | What it means |
|---|---|
| **Versions and staging labels** | Each change creates a new version. `AWSCURRENT` marks the live one, `AWSPREVIOUS` the last. `AWSPENDING` is used during rotation |
| **Rotation** | A Lambda function can change the password in the database *and* the secret together on a schedule. RDS can manage this for you (Post 08) |
| **Resource policy** | Lets you share a secret across accounts |
| **Audit** | Every read is a CloudTrail event |
| **Cost** | About $0.40 per secret per month, plus about $0.05 per 10,000 API calls |

### Secrets Manager or Parameter Store?

| | **Secrets Manager** | **SSM Parameter Store** |
|---|---|---|
| Built-in rotation | **Yes** | No |
| Cost | ~$0.40 per secret per month | Standard parameters free; advanced parameters cost a little |
| Size | Up to 64 KB | 4 KB standard |
| Cross-account sharing | Yes (resource policy and CMK) | Limited |
| Best for | Credentials that rotate | Plain config and simple secrets |

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "If the bucket is encrypted, the data is safe." | Only as safe as **who can call `kms:Decrypt`** on its key. A role with S3 read access but no KMS access is denied, and a role with both reads everything. |
| "IAM permissions are enough to use a KMS key." | Only if the **key policy allows IAM to delegate** (the default root statement). Delete that statement and IAM policies become useless for that key. |
| "A key administrator can read the data." | **No.** Administering and using are separate. An admin can't decrypt unless something also grants `kms:Decrypt`. (With the default policy and `AdministratorAccess`, Jim can do both, so don't be surprised when it works.) |
| "KMS encrypts my 2 GB file." | KMS only encrypts up to **4 KB**. Bigger data uses **envelope encryption**: KMS protects the data key, and the service protects the data. |
| "Rotating a key re-encrypts everything." | Rotation creates **new backing key material** for future encryptions. Old data is **not** re-encrypted, and old material is kept so it still decrypts. The key ID and ARN **don't change**. |
| "Automatic rotation is on by default." | For **customer managed** keys it's **off**. You enable it, and the default period is one year. AWS managed keys rotate for you. |
| "I can delete a key and change my mind." | Deletion has a **7 to 30 day waiting period**. After it, **everything encrypted under that key is permanently unreadable**. Disable a key first, delete only when you're sure. |
| "Secret ARNs are predictable." | A secret ARN ends with a **random six-character suffix**. In IAM policies, write `...:secret:plat/demo/api-key-*` or you'll be denied. |
| "Putting a secret in an environment variable is fine." | Environment variables show up in the console, in `describe` calls and in crash dumps. Read the secret **at runtime**, from Secrets Manager, with an IAM role. |
| "Secrets Manager is the same as an encrypted S3 file." | It adds **versioning**, **rotation**, **audit** and **fine-grained access**. A file in S3 has none of those. |
| "An interface endpoint makes traffic private automatically." | Only if **Private DNS** is on and the VPC has **DNS hostnames enabled**. Otherwise the service name still resolves to a **public** IP. |
| "Cross-account secret sharing works with the default key." | The default `aws/secretsmanager` key **can't be shared**. Use a customer managed key and add the other account to its key policy. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| `plat-vpc`, private subnets and DNS settings | Post 04 |
| The `PlatformAdmin` role and the `plat-admin` profile | Post 03 |
| Role `plat-demo-reader` | Post 02 |

| You create here | Used by |
|---|---|
| **KMS key `alias/plat-data`** | **S3 (06), EFS (07), RDS and DynamoDB (08), SNS, SageMaker (19, 20)**: the shared encryption key |
| Secret `plat/demo/api-key` | A harmless practice secret for the lab |
| `plat-app-sg` and `plat-vpce-sg` security groups | RDS and EFS rules in Posts 07 and 08, and the endpoints in Post 10 |
| Interface endpoint pattern | Reused for SSM (Post 10), ECR (11) and CloudWatch Logs (21) |
| A **VPC-attached CloudShell** | Posts 07 and 08, to reach EFS and RDS from inside the network |

---

## Lab: The Platform Key and a Private Secret 🛠️

Sign in as Jim, region **N. Virginia**, and run CLI commands with `AWS_PROFILE=plat-admin` on your laptop.

### 1. Create the customer managed key

1. Open **Key Management Service**, then **Customer managed keys**, then **Create key**.
2. Key type **Symmetric**, key usage **Encrypt and decrypt**, advanced options left as **KMS** and **Single-Region**. Choose **Next**.
3. Alias: **`plat-data`**. Description: `Shared encryption key for the Platform Lab`. Add the tag `project = plat`.
4. **Key administrators:** search for `AWSReservedSSO_PlatformAdmin` and tick it.
5. **Key users:** leave empty for now.
6. Review the generated key policy. Find the statement with `"Principal": {"AWS": "arn:aws:iam::<account>:root"}`. That's the "let IAM decide" statement. Create the key.

### 2. Encrypt and decrypt a small message

```bash
echo -n "hello platform" > msg.txt

aws kms encrypt --key-id alias/plat-data --plaintext fileb://msg.txt \
  --query CiphertextBlob --output text | base64 --decode > msg.enc

aws kms decrypt --ciphertext-blob fileb://msg.enc \
  --query Plaintext --output text | base64 --decode
```

```text
hello platform
```

Notice that `decrypt` didn't name a key. For symmetric keys, **the ciphertext carries its key ID**, so KMS knows which key to use. That's also why you can't decrypt something if you lose access to that key.

### 3. See envelope encryption's raw ingredient

```bash
aws kms generate-data-key --key-id alias/plat-data --key-spec AES_256 \
  --query '[KeyId,length(Plaintext),length(CiphertextBlob)]' --output text
```

You'll get the key ARN and two base64 lengths: a 32-byte data key in plaintext (44 characters encoded) and a longer encrypted copy. That pair is what S3, RDS and EBS use behind the scenes. Don't keep it.

### 4. Turn on rotation

1. Open the key, **Key rotation** tab, **Edit**, tick **Enable automatic key rotation**, keep **365 days**, and save.

```bash
aws kms get-key-rotation-status --key-id alias/plat-data
```

```json
{
    "KeyRotationEnabled": true,
    "RotationPeriodInDays": 365
}
```

### 5. Create the security groups

We need two firewalls now, and Post 07 covers them in depth.

1. **VPC, Security groups, Create security group.**
2. Name **`plat-app-sg`**, description `Workloads that call AWS services`, VPC `plat-vpc`. Leave **Inbound** empty. Leave default **Outbound** (all traffic). Add `project = plat` and create.
3. Create a second group: **`plat-vpce-sg`**, description `Interface endpoint access`, VPC `plat-vpc`.
4. Add an **Inbound rule**: type **HTTPS**, port 443, **Source** = the security group `plat-app-sg`. Create it.

That source is a **security group**, not an IP range. It means "any network interface that carries `plat-app-sg`". It's the pattern we'll use for almost every connection from now on.

### 6. Store a secret

1. Open **Secrets Manager**, then **Store a new secret**.
2. Type **Other type of secret**. Add a key/value pair: key `api_key`, value `demo-12345`.
3. **Encryption key:** choose **`plat-data`** (not the default).
4. Name **`plat/demo/api-key`**. Description `Practice secret`. Add `project = plat`.
5. Leave rotation off and store it.

```bash
aws secretsmanager get-secret-value --secret-id plat/demo/api-key \
  --query '[Name,VersionStages,SecretString]' --output json
```

```json
[
    "plat/demo/api-key",
    ["AWSCURRENT"],
    "{\"api_key\":\"demo-12345\"}"
]
```

This worked from your laptop through the **public** Secrets Manager endpoint. Next we make a *private* path.

### 7. Create the interface endpoint

1. **VPC, Endpoints, Create endpoint.**
2. Name `plat-secretsmanager-vpce`. Service category **AWS services**. Choose **`com.amazonaws.us-east-1.secretsmanager`** (type **Interface**).
3. VPC `plat-vpc`. Tick **Enable DNS name** (private DNS). Subnets: **`us-east-1a`, `plat-private-a`** (one AZ to save money; production uses both). Security group **`plat-vpce-sg`**. Policy **Full access**.
4. Create and wait for **Available**.

### 8. Read the secret from inside the VPC

1. Open **CloudShell**. Choose **Actions, Create VPC environment**.
2. Name `plat-shell`, VPC `plat-vpc`, subnet **`plat-private-a`**, security group **`plat-app-sg`**. Create and wait for it to start.
3. A VPC CloudShell has **no internet access of its own**: it reaches AWS APIs and installs packages through the **NAT gateway** (or endpoints). Keep the NAT gateway from Post 04 running whenever you use `plat-shell`.

Now prove the path:

```bash
getent hosts secretsmanager.us-east-1.amazonaws.com
aws secretsmanager get-secret-value --secret-id plat/demo/api-key \
  --query SecretString --output text
```

```text
10.20.10.52     secretsmanager.us-east-1.amazonaws.com
{"api_key":"demo-12345"}
```

The service name resolved to a **private `10.20.x.x` address**, an ENI in your subnet. Open a plain CloudShell (the default, non-VPC one) and run `getent hosts` again: you'll see **public** IPs. Same name, two answers, decided by **Private DNS**.

### 9. Now break it on purpose

Remove the ingress rule from `plat-vpce-sg` (Inbound rules, Edit, Delete) and repeat the `get-secret-value` call from `plat-shell`. It **hangs** until the CLI times out. No `AccessDenied`, no message: just silence. That's what a security group block looks like. Restore the rule and it works again.

### 10. Resources you now have 📦

| Resource | Name | Notes |
|---|---|---|
| KMS key | `alias/plat-data` | Rotation on. ~$1/month |
| Security groups | `plat-app-sg`, `plat-vpce-sg` | Used from here on |
| Secret | `plat/demo/api-key` | ~$0.40/month |
| Interface endpoint | `plat-secretsmanager-vpce` | **Hourly cost.** Delete after the session |
| CloudShell VPC environment | `plat-shell` | Free. Reused in Posts 07 and 08 |

### Cleanup 🧹

| Keep | Delete now |
|---|---|
| The KMS key (never delete it casually), the secret, the security groups, the CloudShell VPC environment | **Interface endpoint** `plat-secretsmanager-vpce` (about $0.01 per hour per AZ plus data) |

Also remember the **NAT gateway** from Post 04 if you're finishing for the day.

---

## Quick Quiz 🧠

**Q1.** Dave's role can read an object in a bucket but gets `AccessDenied` mentioning KMS. What's missing and why?

<details>
<summary>Show answer</summary>

Permission to use the **KMS key** that encrypts the object (`kms:Decrypt`, and `kms:GenerateDataKey` for writes). Reading an encrypted object means S3 has to ask KMS to decrypt its data key **on the caller's behalf**, so the caller needs access to the key, allowed by the key policy and (with the default delegation) an IAM policy.

</details>

**Q2.** You enable automatic rotation on `alias/plat-data`. A year later, can you still decrypt data you encrypted today?

<details>
<summary>Show answer</summary>

**Yes.** Rotation adds new key material for future encryptions but **keeps every old version** so existing ciphertext still decrypts. The key ID and ARN stay the same, so nothing that references the key needs to change.

</details>

**Q3.** Why can't KMS directly encrypt a 1 MB file, and what happens instead?

<details>
<summary>Show answer</summary>

KMS's `Encrypt` API accepts at most **4 KB**. For larger data the service uses **envelope encryption**: it asks KMS for a data key, encrypts the file locally with it, stores the **encrypted** data key beside the file, and discards the plaintext key. KMS only ever protects the small data key.

</details>

**Q4.** A Lambda reads `plat/demo/api-key` successfully, but you add `Resource: arn:aws:secretsmanager:us-east-1:123456789012:secret:plat/demo/api-key` to its policy and it's denied. Why?

<details>
<summary>Show answer</summary>

A secret ARN has a **random six-character suffix** (`...api-key-AbCdEf`), so the exact ARN without it doesn't match. Use `secret:plat/demo/api-key-*` (or `secret:plat/*`) in the policy.

</details>

**Q5.** An interface endpoint exists and its security group allows 443, but the secret is still read over the public internet. Name two things to check.

<details>
<summary>Show answer</summary>

(1) **Private DNS** must be enabled on the endpoint, or the service name still resolves to its public address. (2) The VPC must have **DNS support and DNS hostnames** turned on. Resolve the name from inside the VPC (`getent hosts`) and check it returns a private IP.

</details>

---

## What's Next? 🚀

We have a network and a key to encrypt things with. Now for the first place data will *live*. How do you design an S3 bucket that's private, encrypted with our new key, versioned, and cheap over time? And what happens when a role can read the bucket but not the key?

👉 **[Post 06: S3](content/aws/06-s3.md)**: the platform's data lake bucket, a lifecycle policy, a bucket policy, and the "S3 yes, KMS no" failure you'll meet in real life.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
