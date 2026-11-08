---
title: "Identity Center, SAML, OAuth and OIDC"
date: 2026-11-08
tags: [aws, iam-identity-center, sso, saml, oauth, oidc, federation, intermediate]
description: Post 3 of the AWS series. Replace the temporary admin with real single sign-on using IAM Identity Center, learn what SAML, OAuth 2.0 and OpenID Connect actually do and why people confuse them, and set up SSO-backed CLI profiles for Jim and Dave.
---

# Nobody Should Have a Password Per Account 🪪

In Post 01 we made `plat-bootstrap`, an IAM user with a static password and admin rights, and promised to delete it. Let's keep that promise.

Think about what's wrong with it. It's a long-lived credential tied to one account. When Jim leaves, someone must remember to delete it. When Dave joins, someone must create *another* one. With ten accounts and fifty people, that's five hundred identities nobody is watching.

The fix is **federation**: people prove who they are *once*, in one place, and receive **short-lived roles** in whichever accounts they're allowed to use. AWS's service for that is **IAM Identity Center**.

---

## What Identity Center Actually Does 🧭

Identity Center sits in front of your accounts and manages four things:

| Concept | What it is | In the Platform Lab |
|---|---|---|
| **Identity source** | Where users and groups come from: Identity Center's own directory, Active Directory, or an external IdP (Okta, Entra ID) | The built-in directory |
| **Users and groups** | The people | `jim`, `dave`; groups `platform-admins`, `data-scientists` |
| **Permission set** | A **template** for permissions (managed policies, inline policy, session length) | `PlatformAdmin`, `DataScientist` |
| **Assignment** | "This group gets this permission set in this account" | `platform-admins` → `PlatformAdmin` in our account |

Here is the part people miss. **A permission set is not a role.** When you assign one to an account, Identity Center **creates an IAM role in that account** named `AWSReservedSSO_<PermissionSetName>_<hash>`, and Jim's session is just him assuming it. Everything you learned in Post 02 still applies.

![How a sign-in becomes a role session](content/aws/images/03-sso-flow.svg)

---

## SAML, OAuth and OIDC: Three Protocols, Three Jobs 🔑

These get mixed up constantly. They solve different problems.

| | **SAML 2.0** | **OAuth 2.0** | **OpenID Connect (OIDC)** |
|---|---|---|---|
| **Main job** | Sign a person into an app (**authentication**) | Let an app act on your behalf (**authorization**) | Sign a person in, built **on top of OAuth** |
| **Token format** | XML **assertion** | An **access token** (opaque, or a JWT) | An **ID token** (always a JWT) plus OAuth tokens |
| **Typical use** | Enterprise SSO to web apps and the AWS console | "Allow this app to read my calendar" | Modern apps, mobile, **machines proving identity** |
| **Born** | 2005 | 2012 | 2014 |
| **Where you'll see it** | Okta to AWS, Entra ID to AWS | `aws sso login` in your terminal | GitHub Actions assuming an AWS role |

### SAML in one flow

SAML involves two parties: the **identity provider (IdP)**, which knows who you are, and the **service provider (SP)**, which wants proof.

1. You open the app (SP-initiated) or click its tile in the IdP portal (IdP-initiated).
2. The IdP authenticates you and builds a **signed XML assertion**: who you are, which groups you're in, valid from and to.
3. Your **browser** carries that assertion to the SP's **Assertion Consumer Service (ACS) URL**.
4. The SP verifies the signature against the IdP's certificate (exchanged earlier as **metadata XML**) and creates your session.

Everything depends on matching a few strings exactly: the **entity ID**, the **ACS URL** and the **certificate**. Most SAML outages are one of those three, or clock skew between the two sides.

### OAuth 2.0: delegating, not logging in

OAuth involves four roles: the **resource owner** (you), the **client** (an app), the **authorization server** (issues tokens) and the **resource server** (the API). The client never sees your password. It gets a **token with scopes**.

| Flow | Used when |
|---|---|
| **Authorization code + PKCE** | A user is present at a browser. The standard, secure choice |
| **Device code** | A device has no browser (a CLI over SSH) |
| **Client credentials** | No user at all. Machine to machine |
| Implicit, password grant | **Deprecated.** Don't build new things on these |

### OIDC: identity on top of OAuth

OIDC adds one thing to OAuth: an **ID token**, a signed **JWT** that says who the user is. A JWT has three dot-separated parts (header, payload, signature) and the payload carries **claims**:

| Claim | Meaning | Check it for |
|---|---|---|
| `iss` | Issuer | It's the IdP you trust |
| `aud` | Audience | It was issued **for your app** |
| `sub` | Subject | A stable user or workload ID |
| `exp` | Expiry | It hasn't expired |

You validate a JWT by fetching the issuer's public keys (from its `/.well-known/openid-configuration` discovery document), checking the **signature**, and then checking `iss`, `aud` and `exp`. Skipping the audience check is the classic bug.

> **Key insight:** "OAuth login" doesn't exist. OAuth proves an app may call an API. OIDC is what proves a person (or a workload) is who they say. When someone says "log in with OAuth", they almost always mean OIDC.

### Where each one shows up in this series

| Protocol | Place |
|---|---|
| **SAML** | Optional: connecting an external IdP to Identity Center (SCIM keeps users in sync) |
| **OAuth 2.0** | `aws sso login` runs an OAuth flow in your browser, and the CLI stores the resulting token under `~/.aws/sso/cache` |
| **OIDC** | Post 18 and the nuance below: CI systems prove who they are with OIDC tokens and call `sts:AssumeRoleWithWebIdentity`, so there are **no stored AWS keys** |

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "SSO means one login that works everywhere." | SSO gets you **into AWS**. Inside each account you get a **role** with its own limits. You can be an admin in one account and read-only in another. |
| "Identity Center users appear under IAM, Users." | They don't. They're not IAM users at all. You'll only see the **roles** created from their permission sets. |
| "Changing a permission set updates every account instantly." | Mostly, but not always. If assignments show **"Reprovision needed"**, choose it. Until then the role in the account may be stale. |
| "Identity Center works across regions." | It lives in **one home region**, and you pick it when you enable it. It can't be moved in place. Choose it deliberately (we use `us-east-1`). |
| "OAuth and SAML are two flavours of the same thing." | SAML is XML assertions for **sign-in**. OAuth is token delegation for **API access**. Different shapes, different purposes. |
| "A JWT is encrypted, so it's private." | A normal JWT is only **signed**, not encrypted. Anyone can base64-decode the payload. Never put secrets in claims. |
| "Deleting a user ends their sessions." | Existing role sessions keep working **until they expire**. Short session durations are your real safety net. |
| "I can delete the old IAM user and everything keeps working." | Any trust policy that named that user now shows a **raw unique ID** (`AIDA...`) instead of an ARN, and no longer matches anybody. You'll fix one in the lab. |
| "The portal's *Access keys* page is the proper CLI setup." | Those are **temporary copy-paste keys** that expire. A proper SSO profile (`aws configure sso`) refreshes the session for you. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| `plat-bootstrap` to sign in and set things up | Post 01 |
| The role, trust and evaluation model | Post 02 |
| Role `plat-demo-reader` (whose trust we repair) | Post 02 |

| You create here | Used by |
|---|---|
| Users `jim` and `dave`, groups `platform-admins` and `data-scientists` | Every later post |
| Permission set `PlatformAdmin` | Everything Jim builds |
| Permission set `DataScientist` | Extended in Posts 17, 19 and 20 |
| The `plat-admin` CLI profile | Every lab from here on, including the local Docker work in Post 09 |

---

## Lab: Real Single Sign-On 🛠️

You'll need two email addresses you can read. If you use Gmail, `you+jim@gmail.com` and `you+dave@gmail.com` both land in your own inbox.

Sign in as `plat-bootstrap` in `us-east-1`.

### 1. Enable Identity Center

1. Open **IAM Identity Center** in the console and confirm the region selector says **N. Virginia**.
2. Choose **Enable**. If asked, choose the **organization instance** option, which sets up AWS Organizations for you. (An *account instance* is a limited alternative and isn't what we want.)
3. Wait for the success banner and note the **AWS access portal URL**, which looks like `https://d-xxxxxxxxxx.awsapps.com/start`.

### 2. Require MFA at sign-in

1. In Identity Center, choose **Settings**, then **Authentication**, then **Multi-factor authentication**, and choose **Configure**.
2. Set **Prompt users for MFA** to **Every time they sign in**, tick **Authenticator apps** and **Security keys and built-in authenticators**, and choose **Require them to register an MFA device at sign-in**.
3. Save.

### 3. Create groups and users

1. **Groups**, then **Create group**: `platform-admins`. Repeat for `data-scientists`.
2. **Users**, then **Add user**: username `jim`, your first `+jim` email address, first and last name. Choose **Send an email to this user with password setup instructions**. On the next page, add `jim` to `platform-admins`.
3. Repeat for `dave`, with his email, in `data-scientists`.

### 4. Create the permission sets

1. **Permission sets**, then **Create permission set**, then **Predefined permission set**.
2. Choose **AdministratorAccess**. Name it `PlatformAdmin`. Set **Session duration** to **4 hours**.
3. Create another predefined set from **ViewOnlyAccess**. Name it `DataScientist`, and keep **1 hour**. (We'll extend it in later posts.)

### 5. Assign groups to the account

1. **AWS accounts**, tick your account, then **Assign users or groups**.
2. On **Groups**, choose `platform-admins`, then **Next**, pick `PlatformAdmin`, and submit.
3. Repeat with `data-scientists` and `DataScientist`.

Open **IAM, then Roles** and search for `AWSReservedSSO`. You'll see two new roles. That's the proof that a permission set becomes a role.

### 6. Sign in as Jim

1. Open Jim's invitation email, choose **Accept invitation**, and set a password.
2. Register an MFA device when prompted.
3. At the portal, you'll see your account with **PlatformAdmin**. Choose **Management console**.

Check the top right of the console. It now shows `PlatformAdmin/jim`, not an IAM user name.

### 7. Set up an SSO-backed CLI profile

Install the **AWS CLI v2** on your computer if you haven't (use the official install guide for your OS), then run:

```bash
aws configure sso
```

Answer the prompts:

| Prompt | Value |
|---|---|
| SSO session name | `plat` |
| SSO start URL | your portal URL |
| SSO region | `us-east-1` |
| SSO registration scopes | `sso:account:access` |

Your browser opens, so approve the request. Back in the terminal, pick your account and the `PlatformAdmin` role, then set the default region to `us-east-1`, the output to `json` and the profile name to `plat-admin`.

```bash
export AWS_PROFILE=plat-admin
aws sts get-caller-identity
```

Expected:

```json
{
    "UserId": "AROAEXAMPLEEXAMPLE:jim",
    "Account": "123456789012",
    "Arn": "arn:aws:sts::123456789012:assumed-role/AWSReservedSSO_PlatformAdmin_abc123def456/jim"
}
```

That `AWSReservedSSO_...` ARN is your identity for the rest of the series. When the session expires, run `aws sso login --profile plat-admin` and it refreshes.

### 8. Retire the temporary admin

First, fix the thing that will break. As Jim, open **IAM, Roles, `plat-demo-reader`, Trust relationships, Edit trust policy**, and change the principal so it trusts the account instead of the old user:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "AWS": "arn:aws:iam::123456789012:root" },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

Trusting `:root` means "any identity in this account **that its own IAM policy allows to call `sts:AssumeRole`**". `PlatformAdmin` has admin rights, so Jim qualifies. Dave doesn't, which is the point.

Now delete the bootstrap user: **IAM, Users, `plat-bootstrap`, Delete**. Confirm by typing the name.

### 9. Prove it works

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
aws sts assume-role \
  --role-arn arn:aws:iam::$ACCOUNT:role/plat-demo-reader \
  --role-session-name jim-check \
  --query 'AssumedRoleUser.Arn' --output text
```

```text
arn:aws:sts::123456789012:assumed-role/plat-demo-reader/jim-check
```

Finally, sign in as **Dave** in a private browser window and try to open **IAM, Roles**. He can *view* it (ViewOnlyAccess) but cannot change anything. That's the first guardrail of the platform.

### 10. Resources you now have 📦

| Resource | Name | Notes |
|---|---|---|
| Identity Center instance | home region `us-east-1` | Can't move later |
| Users | `jim`, `dave` | MFA required |
| Groups | `platform-admins`, `data-scientists` | |
| Permission sets | `PlatformAdmin` (4h), `DataScientist` (1h) | Generate `AWSReservedSSO_*` roles |
| CLI profile | `plat-admin` | Use `export AWS_PROFILE=plat-admin` |
| **Deleted** | `plat-bootstrap` | No static admin credentials remain |

### Cleanup 🧹

Nothing to delete. Identity Center is free. Remember that from now on, **"sign in" means the access portal**, not the IAM sign-in URL.

---

## Quick Quiz 🧠

**Q1.** What's the difference between a permission set and a role?

<details>
<summary>Show answer</summary>

A **permission set** is a template managed in Identity Center. When you assign it to an account, Identity Center **creates a role** from it (`AWSReservedSSO_<name>_<hash>`) inside that account. The role is what actually carries the policies and is what people assume.

</details>

**Q2.** A teammate says "we use OAuth to log users into our app". What's the likely mistake?

<details>
<summary>Show answer</summary>

OAuth 2.0 **authorizes access to an API**. It doesn't define who the user is. Logging users in is **OpenID Connect**, which adds an ID token (a JWT) on top of OAuth. They probably *are* using OIDC and calling it OAuth.

</details>

**Q3.** Your app receives a valid-looking JWT. Which three claims must you check after verifying the signature?

<details>
<summary>Show answer</summary>

`iss` (is it from the issuer you trust?), `aud` (was it issued **for this app**?) and `exp` (is it still valid?). A correctly signed token from the right issuer but for a different audience should still be rejected.

</details>

**Q4.** You delete the IAM user named in a role's trust policy. What happens to the trust policy, and how do you fix it?

<details>
<summary>Show answer</summary>

The principal is replaced with the user's **unique ID** (`AIDA...`) because the ARN no longer resolves. That ID matches nobody, so the role can no longer be assumed by that path. Edit the trust policy to name a current principal (a role, or the account root with IAM policies controlling who may assume).

</details>

**Q5.** Dave's permission set is changed to add a new managed policy, but he still can't use it an hour later. First thing to check?

<details>
<summary>Show answer</summary>

Look under **AWS accounts** in Identity Center for a **"Reprovision needed"** indication on the assignment. Choose it to push the updated permission set into the account's role. Also remember Dave's existing session keeps its **old permissions until it expires or he signs in again**.

</details>

---

## What's Next? 🚀

People can now sign in safely, and everything they do is a role session. Next we need somewhere for the platform to *live*. Where do packets go, who can reach the internet, and how does a private server call AWS services without leaving the network?

👉 **[Post 04: VPC: Subnets, NAT and Endpoints](content/aws/04-vpc.md)**: build the private network every later service sits inside.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
