---
title: "IAM in Depth"
date: 2026-11-08
tags: [aws, iam, policies, roles, sts, least-privilege, intermediate]
description: Post 2 of the AWS series. How AWS decides every allow and deny, the difference between identity, resource, trust and boundary policies, why roles beat users, and a lab where you assume a role, hit an explicit deny and use the policy simulator to explain it.
---

# Every AccessDenied Has a Reason 🔐

You have an administrator, and `AdministratorAccess` is a one-line policy that says "everything". That's fine for Jim on day one. It's a disaster once Dave, a Lambda function and a pipeline all need access to *parts* of the platform.

IAM is the system that answers one question, billions of times a day: **"is this principal allowed to do this action on this resource, right now?"** If you can run that decision in your head, you can fix most AWS problems without guessing.

---

## The Building Blocks 🧱

| Term | What it is | Example in the Platform Lab |
|---|---|---|
| **Principal** | Who is making the request | Jim, a Lambda function, an ECS task |
| **Action** | What they want to do | `s3:GetObject`, `dynamodb:PutItem` |
| **Resource** | What they want to do it to | `arn:aws:s3:::plat-data-.../raw/*` |
| **Condition** | Extra rules that must be true | Request came over TLS, caller used MFA |
| **Policy** | A JSON document that lists allow/deny statements | `plat-s3-read-demo` |
| **User** | A long-lived identity with credentials | `plat-bootstrap` (temporary) |
| **Role** | An identity with **no credentials of its own** that anyone permitted can *assume* for a short time | `plat-demo-reader` |

### Anatomy of a policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadRawData",
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": "arn:aws:s3:::plat-data-123456789012-us-east-1/raw/*",
      "Condition": {
        "Bool": { "aws:SecureTransport": "true" }
      }
    }
  ]
}
```

`Version` is always `2012-10-17` (it's the policy language version, not a date you update). Each statement is **Effect + Action + Resource + optional Condition**. Resource-based policies add one more field: **`Principal`**, because the policy lives on the resource and has to say *who* it applies to.

---

## Six Kinds of Policy 📚

IAM isn't one policy. A single request can be checked against up to six layers, and **all of them must agree**.

| Policy type | Attached to | What it does |
|---|---|---|
| **Identity-based** | A user, group or role | Grants permissions to that identity |
| **Resource-based** | A resource (S3 bucket, KMS key, SQS queue) | Grants permissions to named principals, even in other accounts |
| **Trust policy** | A role (it's a resource-based policy for the role) | Says **who may assume** the role |
| **Permissions boundary** | A user or role | Sets the **maximum** permissions that identity can ever have |
| **Service control policy (SCP)** | An AWS Organizations account or OU | Sets the maximum for every principal in the account |
| **Session policy** | Passed when assuming a role | Narrows one particular session |

Two more you'll meet later: **VPC endpoint policies** (Post 04) and **resource control policies** in Organizations.

> **Key insight:** Only identity-based and resource-based policies can **grant** access. Boundaries, SCPs and session policies can only **limit** it. A boundary never gives anyone a permission by itself.

---

## How AWS Decides ⚖️

The evaluation logic fits on one page, and it's worth memorising.

1. **Everything starts as denied.** If no policy mentions it, it's an *implicit deny*.
2. **An explicit `Deny` anywhere wins.** Always. No other policy can override it.
3. Organization guardrails (SCPs) must allow it.
4. Permissions boundaries and session policies, if present, must allow it.
5. Some **Allow** must exist: an identity-based policy *or* (within the same account) a resource-based policy.

![How AWS evaluates a request](content/aws/images/02-iam-evaluation.svg)

Two special cases decide a lot of real-world confusion:

| Situation | Rule |
|---|---|
| **Same account** | An allow in the identity policy **or** the resource policy is enough |
| **Cross-account** | **Both** sides must allow: the caller's identity policy **and** the target's resource policy |

---

## Roles, Trust and Temporary Credentials 🎭

A role has two completely separate policy sets, and mixing them up causes endless confusion:

| | Answers | Lives where |
|---|---|---|
| **Trust policy** | *Who* can become this role? | On the role, as `AssumeRolePolicyDocument` |
| **Permission policies** | *What* can the role do once assumed? | Attached to the role |

When a principal calls `sts:AssumeRole`, AWS checks the trust policy, and if it passes, hands back **temporary credentials**: an access key, a secret key and a **session token**. They expire (default one hour). That is why roles beat users: there's nothing permanent to steal.

Here's a trust policy that lets one specific user become the role:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "AWS": "arn:aws:iam::123456789012:user/plat-bootstrap" },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

And one that lets a **service** use the role (this is how Lambda, ECS and EC2 get their identity):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "lambda.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

### Conditions you'll use constantly

| Condition key | Use |
|---|---|
| `aws:SecureTransport` | Require HTTPS |
| `aws:MultiFactorAuthPresent` | Require MFA for sensitive actions |
| `aws:SourceIp` / `aws:SourceVpce` | Limit to an office range or a VPC endpoint |
| `aws:PrincipalOrgID` | Allow anyone in your AWS Organization |
| `aws:SourceArn` / `aws:SourceAccount` | Stop the "confused deputy" problem when a service acts for you |
| `aws:RequestedRegion` | Block activity outside approved regions |
| `sts:ExternalId` | Protect cross-account roles assumed by third parties |

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "If one policy denies and another allows, it depends on which is stronger." | There is no "stronger". An **explicit deny always wins**. |
| "Attaching a permission policy to a role lets people use it." | Not until the **trust policy** lets them assume it. Both halves are required. |
| "A permissions boundary gives a role its permissions." | It only **caps** them. With no identity policy, a boundary grants nothing. |
| "`Action: s3:*` on `Resource: *` is fine because it's just S3." | That includes deleting every bucket and objects, and it can read any data your KMS permissions allow. Scope the resource ARN. |
| "`NotAction` with `Allow` means 'allow only these'." | It means **allow everything except** these. It's a footgun. |
| "A trust policy naming a user is the same as naming the account root." | Naming the **exact user or role** works on its own. Naming `:root` just delegates, so each identity then also needs an identity policy that allows `sts:AssumeRole`. |
| "IAM changes apply instantly." | IAM is **eventually consistent**. After creating a role or policy, wait a few seconds before testing, or you'll chase a phantom error. |
| "Role chaining can give me a 12-hour session." | A role assumed **from another role** is capped at **one hour**, whatever the role's maximum session says. |
| "Groups can be principals in a policy." | A group is only a way to attach policies to users. You **can't** name a group as a `Principal`. |
| "Wildcards in `Resource` work for every action." | Some actions don't support resource-level permissions and need `Resource: "*"`. `s3:ListAllMyBuckets` is one. |

---

## The Least-Privilege Loop 🔁

You won't write perfect policies on the first try. You tighten them with tools:

1. **Start from an AWS managed policy** if it fits, or a broad one you plan to shrink.
2. **IAM Access Advisor** (on the role or user, tab *Last accessed*) shows which services were actually used, and when.
3. **IAM Access Analyzer** can generate a policy from CloudTrail activity and flags findings like public or cross-account access.
4. **The policy simulator** answers "would this be allowed?" without making the real call.

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| The `plat-bootstrap` admin and CloudShell | Post 01 |

| You create here | Used by |
|---|---|
| Customer managed policy `plat-s3-read-demo` | Post 06, where it meets a KMS key and fails |
| Role `plat-demo-reader` | Posts 05 and 06, as the guinea pig for key and bucket policies |
| The evaluation model | **Every later post.** Every `AccessDenied` is one of the five steps above |

---

## Lab: Assume a Role, Break It, Explain It 🛠️

You'll create a read-only role, assume it from CloudShell, hit an implicit deny, then an explicit one, and finally ask the simulator to explain both.

Sign in as `plat-bootstrap` and open **CloudShell** in `us-east-1`.

### 1. Create the permission policy

1. Open **IAM**, then **Policies**, then **Create policy**.
2. Switch to the **JSON** tab and paste:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListAllBuckets",
      "Effect": "Allow",
      "Action": "s3:ListAllMyBuckets",
      "Resource": "*"
    },
    {
      "Sid": "ReadPlatBuckets",
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetObject"],
      "Resource": ["arn:aws:s3:::plat-*", "arn:aws:s3:::plat-*/*"]
    }
  ]
}
```

3. Name it `plat-s3-read-demo`, add the tag `project = plat`, and create it.

Notice the two separate resource patterns. `s3:ListBucket` applies to the **bucket** ARN, and `s3:GetObject` applies to **objects inside it** (`/*`). Forgetting one of the two is the most common S3 policy bug.

### 2. Create the role

1. **IAM**, then **Roles**, then **Create role**.
2. Trusted entity type: **Custom trust policy**. Paste (replace the account ID with yours):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "AWS": "arn:aws:iam::123456789012:user/plat-bootstrap" },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

3. Attach **`plat-s3-read-demo`**.
4. Name the role `plat-demo-reader`, add the tag `project = plat`, and create it.

### 3. Assume it from CloudShell

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)

read AK SK ST <<< $(aws sts assume-role \
  --role-arn arn:aws:iam::$ACCOUNT:role/plat-demo-reader \
  --role-session-name jim-demo \
  --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' \
  --output text)

export AWS_ACCESS_KEY_ID=$AK AWS_SECRET_ACCESS_KEY=$SK AWS_SESSION_TOKEN=$ST
aws sts get-caller-identity
```

Expected output:

```json
{
    "UserId": "AROAEXAMPLEEXAMPLE:jim-demo",
    "Account": "123456789012",
    "Arn": "arn:aws:sts::123456789012:assumed-role/plat-demo-reader/jim-demo"
}
```

You're no longer a user. You're an `assumed-role` with a session name. The environment variables you just exported override CloudShell's own credentials until you unset them.

### 4. Hit an implicit deny

```bash
aws s3 ls
aws iam list-users
```

`aws s3 ls` works (the list is empty, because we have no buckets yet). `aws iam list-users` fails:

```text
An error occurred (AccessDenied) when calling the ListUsers operation: User:
arn:aws:sts::123456789012:assumed-role/plat-demo-reader/jim-demo is not authorized
to perform: iam:ListUsers because no identity-based policy allows the iam:ListUsers action
```

Read the error word by word. It tells you the **principal**, the **action**, and the **reason**: *no identity-based policy allows it* is an **implicit deny**.

### 5. Add an explicit deny

Switch back to your own identity first:

```bash
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
```

Now in the console, open the role `plat-demo-reader`, choose **Add permissions**, then **Create inline policy**, and paste:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyListBuckets",
      "Effect": "Deny",
      "Action": "s3:ListAllMyBuckets",
      "Resource": "*"
    }
  ]
}
```

Name it `deny-demo`. Wait about ten seconds (eventual consistency), then repeat the assume-role commands from step 3 and run:

```bash
aws s3 ls
```

```text
An error occurred (AccessDenied) when calling the ListBuckets operation: User:
arn:aws:sts::123456789012:assumed-role/plat-demo-reader/jim-demo is not authorized
to perform: s3:ListAllMyBuckets with an explicit deny in an identity-based policy
```

Same action as before, but now it's blocked by an **explicit deny in an identity-based policy**, even though `plat-s3-read-demo` *allows* it. The wording of the error is your diagnosis.

### 6. Ask the simulator

Clear the session credentials again (`unset ...`) and run:

```bash
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::$ACCOUNT:role/plat-demo-reader \
  --action-names s3:ListAllMyBuckets iam:ListUsers \
  --resource-arns "*" \
  --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output table
```

Expected:

```text
-----------------------------------------
|        SimulatePrincipalPolicy        |
+---------------------+-----------------+
|  s3:ListAllMyBuckets|  explicitDeny   |
|  iam:ListUsers      |  implicitDeny   |
+---------------------+-----------------+
```

Now ask about an object read, using a resource ARN that matches the policy's `plat-*` pattern:

```bash
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::$ACCOUNT:role/plat-demo-reader \
  --action-names s3:GetObject \
  --resource-arns arn:aws:s3:::plat-data-test/raw/file.csv \
  --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output table
```

```text
-------------------------------
|   SimulatePrincipalPolicy   |
+----------------+------------+
|  s3:GetObject  |  allowed   |
+----------------+------------+
```

The three decisions (`allowed`, `explicitDeny`, `implicitDeny`) are exactly the outcomes from the evaluation diagram. The resource ARN matters: the same action against a resource the policy doesn't cover would come back `implicitDeny`.

You can do the same visually: **IAM, then Roles, `plat-demo-reader`, then the *Simulate* link** in the console.

### 7. Remove the explicit deny

Delete the `deny-demo` inline policy so later posts start clean. Keep the role and the managed policy.

### 8. Resources you now have 📦

| Resource | Name | Notes |
|---|---|---|
| Managed policy | `plat-s3-read-demo` | Read-only on `plat-*` buckets |
| Role | `plat-demo-reader` | Trusts `plat-bootstrap` only |

### Cleanup 🧹

Nothing to delete. IAM is free. Make sure you ran `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN` so your next CloudShell command runs as yourself again.

---

## Quick Quiz 🧠

**Q1.** A role has `s3:GetObject` allowed in its identity policy, but a bucket policy has an explicit `Deny` for that role. Can it read the object?

<details>
<summary>Show answer</summary>

**No.** An explicit deny in *any* applicable policy overrides every allow, wherever the allow comes from.

</details>

**Q2.** Jim attaches a perfect permission policy to a role but nobody can assume it. What did he forget?

<details>
<summary>Show answer</summary>

The **trust policy**. Permission policies say what the role can do. The trust policy says who may *become* it. Without a matching `Principal` (and `sts:AssumeRole`), the role can't be assumed.

</details>

**Q3.** An account A role needs to read an S3 bucket in account B. The bucket policy in B allows it, but the role in A has no S3 permissions. Result?

<details>
<summary>Show answer</summary>

**Denied.** Cross-account access needs **both** sides to allow: the caller's identity policy in A and the resource policy in B. (Same-account access needs only one of them.)

</details>

**Q4.** Dave's role has a permissions boundary that allows only S3 and SQS. His identity policy allows `s3:*` and `dynamodb:*`. What can he do?

<details>
<summary>Show answer</summary>

**S3 only.** The effective permissions are the **intersection** of the identity policy and the boundary. `dynamodb:*` is allowed by the policy but not by the boundary, so it's denied.

</details>

**Q5.** The error says "no identity-based policy allows the action". Is that an explicit or an implicit deny, and where would you look next?

<details>
<summary>Show answer</summary>

An **implicit deny**. Nothing granted it. Look at the identity's attached policies, then any resource policy, then any boundary or SCP that might be capping it. An *explicit* deny says so in the message.

</details>

---

## What's Next? 🚀

We now understand how decisions get made. But `plat-bootstrap` is still a human with a password, and the next ten engineers shouldn't each get one. How do people sign in once, get short-lived roles in the right accounts, and prove who they are using protocols like SAML and OAuth?

👉 **[Post 03: Identity Center, SAML, OAuth and OIDC](content/aws/03-identity-center-and-auth-protocols.md)**: replace the temporary admin with real single sign-on, and finally understand what "federation" means.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
