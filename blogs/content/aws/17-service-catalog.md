---
title: "Service Catalog"
date: 2026-11-08
tags: [aws, service-catalog, governance, launch-constraint, portfolio, cloudformation, least-privilege, intermediate]
description: Post 17 of the AWS series. How Service Catalog lets people create approved infrastructure without holding the permissions to build it, the launch role that makes this possible, and a lab where Dave launches a governed project bucket and fails at everything he shouldn't be able to do.
---

# Self-Service Without Handing Out the Keys 🗂️

Dave is a data scientist. He needs a bucket for each new project, with encryption, versioning and the TLS policy. He should not be able to create *any* resource he likes, and he should not need to learn CloudFormation. Jim doesn't want to be the person who creates a bucket every time someone asks.

There are two bad answers. Give Dave broad S3 permissions (he'll create unencrypted, public buckets by accident). Or make Jim a ticket queue. **Service Catalog** is the third answer: Jim publishes a **template** as a **product**, and Dave launches it. The template runs with a **launch role** that Dave doesn't have.

![Who holds which permission when Dave launches a product](content/aws/images/17-service-catalog.svg)

---

## The Moving Parts 🧱

| Concept | What it is |
|---|---|
| **Product** | A CloudFormation template with a name, owner and one or more **versions** |
| **Portfolio** | A group of products plus the rules and access that apply to them |
| **Access** | Which IAM users, groups or roles may see a portfolio's products |
| **Provisioned product** | One launched instance of a product. Behind it sits a CloudFormation stack |
| **Launch constraint** | The **IAM role** Service Catalog uses to create the stack on the user's behalf |
| **Template constraint** | Rules on the parameters the user may choose (for example "only `dev`") |
| **TagOptions** | Managed lists of allowed tag values, applied to provisioned resources |
| **Sharing** | A portfolio can be shared with other accounts or an organization |

### Who needs which permission?

| Actor | Needs |
|---|---|
| **Administrator** (Jim) | Service Catalog admin permissions, and the right to pass the launch role |
| **End user** (Dave) | The **end-user** Service Catalog permissions, **access to the portfolio**, and **nothing for the underlying resources** |
| **Launch role** | Permission to **create the resources** and to manage the CloudFormation stack |

Without a launch constraint, Service Catalog uses the **end user's own permissions** to create the stack, which would defeat the purpose.

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "Giving a user access to the portfolio lets them launch products." | They also need **IAM permissions** for the Service Catalog end-user API (for example the managed policy `AWSServiceCatalogEndUserFullAccess`). Portfolio access alone is not enough, and IAM alone shows no products. |
| "No launch constraint is fine, the user is trusted." | Then the stack is created with **the user's permissions**. You've given the permissions away and you get no separation. |
| "The launch role is chosen by ARN." | You choose it by **role name**, and the role must exist **with that name** in every account where the product is launched. The role's trust policy must allow `servicecatalog.amazonaws.com`. |
| "Template constraints are validation scripts." | They are **rule statements** over parameters (`Assertions`, `Fn::Contains`, and so on). They can't check, say, a name prefix against an arbitrary pattern. Combine them with a strict launch role. |
| "Editing the template updates provisioned products." | Existing products stay on their **version**. Create a **new version**, then users run **Update**. Old versions can be set to inactive. |
| "Terminating a provisioned product leaves the resources." | It **deletes the stack**, and with it resources whose `DeletionPolicy` is `Delete`. A non-empty bucket makes the termination **fail**. |
| "The user sees the CloudFormation stack." | The stack is named `SC-<account>-pp-<id>`. Whether a user can inspect it depends on their other permissions. |
| "A product can be shared by sending the template." | Share the **portfolio** with accounts. The launch role must exist in each recipient account. |
| "IAM Identity Center users appear as users in the Access tab." | They appear as the **`AWSReservedSSO_<PermissionSet>_<id>` role** created in the account (Post 03). Grant access to that role. |
| "Changing a permission set updates the role instantly." | The role changes only after the permission set is **provisioned** to the account. Re-provision if a change doesn't take effect. |
| "Service Catalog costs money per product." | The service itself has no separate charge in typical use; the **resources it launches** cost what they cost. Check current pricing. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| `infra/cloudformation/bucket.yaml` | Post 16 |
| Dave's permission set `DataScientist` and the `AWSReservedSSO_...` role | Post 03 |
| The KMS key `alias/plat-data` | Post 05 |
| Least-privilege roles with a trust policy for a service | Posts 10 to 14 |

| You create here | Used by |
|---|---|
| Portfolio **`plat-self-service`** with product **Project data bucket** | Dave, whenever a project starts |
| Role **`plat-sc-launch-role`** | Service Catalog only |
| Dave's end-user permission | Post 19 (his Studio work needs project buckets) |

---

## Lab: Publish a Product and Launch It as Dave 🛠️

Part A is Jim (PlatformAdmin). Part B is Dave. Replace `123456789012` and the key ID with yours.

### Part A: Jim publishes

#### 1. Create the launch role

**IAM, Roles, Create role**: trusted entity **Custom trust policy**:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "servicecatalog.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

Name it **`plat-sc-launch-role`** and add this inline policy, **`launch-project-buckets`**:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ManageProjectBucketsOnly",
      "Effect": "Allow",
      "Action": [
        "s3:CreateBucket", "s3:DeleteBucket", "s3:DeleteBucketPolicy",
        "s3:PutBucketPolicy", "s3:GetBucketPolicy",
        "s3:PutBucketVersioning", "s3:GetBucketVersioning",
        "s3:PutEncryptionConfiguration", "s3:GetEncryptionConfiguration",
        "s3:PutBucketPublicAccessBlock", "s3:GetBucketPublicAccessBlock",
        "s3:PutBucketTagging", "s3:GetBucketTagging",
        "s3:GetBucketLocation", "s3:ListBucket"
      ],
      "Resource": "arn:aws:s3:::plat-proj-*"
    },
    {
      "Sid": "CheckTheKey",
      "Effect": "Allow",
      "Action": "kms:DescribeKey",
      "Resource": "arn:aws:kms:us-east-1:123456789012:key/<your-key-id>"
    },
    {
      "Sid": "ManageTheStack",
      "Effect": "Allow",
      "Action": [
        "cloudformation:CreateStack", "cloudformation:DeleteStack",
        "cloudformation:UpdateStack", "cloudformation:DescribeStacks",
        "cloudformation:DescribeStackEvents", "cloudformation:GetTemplateSummary",
        "cloudformation:SetStackPolicy", "cloudformation:ValidateTemplate",
        "cloudformation:CreateChangeSet", "cloudformation:DescribeChangeSet",
        "cloudformation:ExecuteChangeSet", "cloudformation:DeleteChangeSet",
        "servicecatalog:GetApplicationsForResource", "tag:GetResources",
        "tag:TagResources", "tag:UntagResources"
      ],
      "Resource": "*"
    }
  ]
}
```

The role can only create buckets named `plat-proj-*`. That is the *real* boundary: whatever Dave types for the project name, nothing else can be created.

> **Note:** If a launch later fails with an access error mentioning an action not in this list, add that action. Service Catalog's own documentation lists the minimum set, and CloudFormation will tell you the missing action in the stack event.

#### 2. Create the product

**Service Catalog, Provisioning, Products, Create product**:

| Field | Value |
|---|---|
| Product name | `Project data bucket` |
| Description | `Private, versioned, KMS-encrypted bucket. Use KmsKeyArn: arn:aws:kms:us-east-1:123456789012:key/<id>. ProjectName must start with plat-proj-.` |
| Owner | `Platform team` |
| Version details | **Upload a template file**, choose `bucket.yaml` |
| Version title | `v1` |
| Support email | your address |

Create it.

#### 3. Create the portfolio and add the product

**Portfolios, Create portfolio**: name **`plat-self-service`**, owner `Platform team`. Open it, **Products, Add product to portfolio**, select `Project data bucket`.

#### 4. Add the constraints

In the portfolio, **Constraints, Create constraint**:

1. **Product:** Project data bucket. **Constraint type: Launch**. Method **Enter role name**: `plat-sc-launch-role`.
2. **Product:** Project data bucket. **Constraint type: Template**. Description `Dev only`. Paste:

```json
{
  "Rules": {
    "DevOnly": {
      "Assertions": [
        {
          "Assert": { "Fn::Contains": [["dev"], { "Ref": "Environment" }] },
          "AssertDescription": "Only the dev environment is allowed"
        }
      ]
    }
  }
}
```

#### 5. Give Dave what he needs

**In Identity Center:** open **Permission sets, DataScientist, Permissions, Attach managed policies**, and add **`AWSServiceCatalogEndUserFullAccess`**. If the console asks you to provision, **re-provision** the permission set to your account. Dave still has `ViewOnlyAccess` and **no S3 write permissions**.

**In Service Catalog:** portfolio `plat-self-service`, **Access, Grant access, Roles**. Search for `AWSReservedSSO_DataScientist` and select it. Grant.

### Part B: Dave launches

Sign in as **dave** through the Identity Center portal, account, **DataScientist** (his session is one hour, as designed in Post 03). Open **CloudShell** or use the console.

#### 6. Prove Dave can't do it directly

```bash
aws s3api create-bucket --bucket plat-proj-direct-123456789012-us-east-1
```

```text
An error occurred (AccessDenied) when calling the CreateBucket operation: ...
User: arn:aws:sts::123456789012:assumed-role/AWSReservedSSO_DataScientist_.../dave
is not authorized to perform: s3:CreateBucket ...
```

Good. Dave has no way to create buckets on his own.

#### 7. Launch the product

**Service Catalog, Products** (end-user view). `Project data bucket` is listed. **Launch product**:

| Field | Value |
|---|---|
| Provisioned product name | `churn-bucket` |
| Version | `v1` |
| ProjectName | `plat-proj-churn` |
| Environment | `dev` |
| KmsKeyArn | the ARN from the product description |

Launch. The status goes **Under change**, then **Available**. Open the provisioned product's **Outputs**: `BucketName` and `BucketArn` are there. Dave now has a bucket he could not have created himself. To confirm its settings, switch to Jim's session (or ask Jim) and run:

```bash
aws s3api get-bucket-versioning --bucket plat-proj-churn-dev-123456789012-us-east-1
```

```text
{ "Status": "Enabled" }
```

(Whether Dave can also read bucket settings depends on what his `ViewOnlyAccess` set includes, so don't rely on it.)

#### 8. Try to cheat

**a. Choose `prod`.** Launch another product with `Environment = prod`. The launch is **rejected before anything is created**: *Only the dev environment is allowed*. That's the template constraint.

**b. Use a name outside the allowed prefix.** Launch with `ProjectName = sneaky` and `Environment = dev`. The provisioned product ends in **Error**. Open it, **Events**, and you'll see the CloudFormation failure: **AccessDenied** for `s3:CreateBucket` on `arn:aws:s3:::sneaky-dev-...`. The launch role refused. Terminate the failed product.

Both rules did their work at different layers: the parameter rule stopped a bad value early, and the launch role stopped what a rule can't express.

#### 9. Terminate

Dave terminates `churn-bucket` (**Actions, Terminate**). The stack and the empty bucket are deleted. If he had put an object in the bucket first, the termination would fail on `BucketNotEmpty`, because the bucket's `DeletionPolicy` is `Delete` and S3 refuses to delete a non-empty bucket.

### 10. Resources you now have 📦

| Resource | Name |
|---|---|
| Role | `plat-sc-launch-role` |
| Product, portfolio | `Project data bucket` (v1), `plat-self-service` |
| Constraints | Launch (`plat-sc-launch-role`), Template (dev only) |
| Access | Role `AWSReservedSSO_DataScientist_...` |
| Permission set change | `AWSServiceCatalogEndUserFullAccess` added to DataScientist |

### Cleanup 🧹

Nothing here costs money. Keep it all. In Post 19 Dave launches a bucket for his ML work with this product.

---

## Quick Quiz 🧠

**Q1.** Dave can see the portfolio's products but launching fails immediately with an authorization error on the Service Catalog API. What is missing?

<details>
<summary>Show answer</summary>

The IAM **end-user permissions** for Service Catalog on his role (for example `AWSServiceCatalogEndUserFullAccess`). Portfolio access and IAM permissions are two separate requirements.

</details>

**Q2.** What happens if you forget the launch constraint?

<details>
<summary>Show answer</summary>

Service Catalog creates the stack using the **end user's own permissions**. Dave would need S3 permissions to succeed (and would then hold them directly), and the governance goal is lost.

</details>

**Q3.** Why did `ProjectName = sneaky` fail even though the template accepts it?

<details>
<summary>Show answer</summary>

The template's `AllowedPattern` is only a format check. The **launch role** may only act on `arn:aws:s3:::plat-proj-*`, so CloudFormation's call to create `sneaky-dev-...` was denied.

</details>

**Q4.** How do you roll out an improved template to existing provisioned products?

<details>
<summary>Show answer</summary>

Add a **new product version**, then have users **Update** their provisioned products to it. Existing products don't change when a template is edited.

</details>

**Q5.** Why does terminating a provisioned product sometimes fail?

<details>
<summary>Show answer</summary>

Termination deletes the CloudFormation stack. If a resource can't be deleted (for example a **non-empty S3 bucket**), the stack delete fails and the product stays in an error state until the cause is fixed.

</details>

---

## What's Next? 🚀

You have source in Git, infrastructure in templates and a governed way to request resources. Now the link in the middle: a push should **build** the container image and **deploy** it, with no one running `docker push` from a laptop.

👉 **[Post 18: CodeBuild and CodePipeline](content/aws/18-codebuild-and-codepipeline.md)**: a `buildspec.yml` that builds and pushes `plat-api` to ECR, and a pipeline that connects GitHub to CodeBuild to ECS, with an approval step and an alert on failure.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
