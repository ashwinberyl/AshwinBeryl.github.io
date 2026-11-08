---
title: "Git and Webhooks"
date: 2026-11-08
tags: [aws, git, github, gitlab, webhooks, hmac, lambda-function-url, secrets-manager, intermediate]
description: Post 15 of the AWS series. The parts of Git a platform team uses every day, how a webhook turns a push into an HTTP request, why signatures matter, and a lab that puts the platform code in GitHub and receives verified push events in a Lambda function.
---

# A Push Is Just an HTTP Request Waiting to Happen 🔔

Everything we have built by hand has lived only in the AWS console, which means it lives only in your head. From this part on, the platform's code, build instructions and infrastructure definitions go into **Git**, and changes to Git will **start things**: a build, a test, a deployment.

The mechanism behind "a push starts a pipeline" is not magic. It is a **webhook**: when something happens, GitHub or GitLab sends an HTTP `POST` to a URL you chose. In this post you will receive that request yourself, verify it, and read it, before CodePipeline (Post 18) hides the same mechanism behind a connection.

![From git push to a verified event in CloudWatch](content/aws/images/15-webhooks.svg)

---

## The Git You Actually Need 🌿

| Concept | What it is |
|---|---|
| **Commit** | A snapshot plus a message, identified by a hash. Commits form a chain |
| **Branch** | A movable name pointing to a commit. `main` is just a convention |
| **Remote** | A copy of the repository elsewhere, usually called `origin` |
| **Push / pull** | Send your commits to a remote / fetch and integrate theirs |
| **Pull request (merge request on GitLab)** | A proposal to merge one branch into another, with review and checks |
| **Merge vs rebase** | Merge keeps both histories with a merge commit. Rebase replays your commits on top of the target for a linear history |
| **`.gitignore`** | Files Git should never track |

A working routine for a platform repository:

```bash
git switch -c feature/short-name      # 1. branch from an up-to-date main
# edit, test
git add -p                            # 2. stage deliberately, in pieces
git commit -m "Explain why, not what" # 3. small commits with meaning
git push -u origin feature/short-name # 4. publish the branch
# open a pull request, wait for checks, merge
git switch main && git pull           # 5. sync back
```

---

## Webhooks: Mechanics ⚙️

When an event occurs, the provider sends:

- A `POST` with a **JSON body** describing the event.
- **Headers** naming the event type and a unique delivery ID.
- A way to prove the sender is genuine.

| | **GitHub** | **GitLab** |
|---|---|---|
| Event type header | `X-GitHub-Event` (`push`, `pull_request`, `ping`, ...) | `X-Gitlab-Event` |
| Delivery ID | `X-GitHub-Delivery` | `X-Gitlab-Event-UUID` |
| Authenticity | **HMAC-SHA256 of the raw body** with your shared secret, in `X-Hub-Signature-256` | A **secret token** you set, sent as-is in `X-Gitlab-Token` (newer versions also support signing tokens) |
| Delivery history | Repository, Settings, Webhooks, **Recent Deliveries**, with **Redeliver** | Settings, Webhooks, **Recent events**, with resend |
| Timeout | About 10 seconds. Slow handlers are marked failed | Similar |

The right pattern: **verify, record, respond fast**. Do slow work somewhere else (a queue, a pipeline).

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "A webhook URL that nobody knows is safe." | URLs leak. Anyone who finds it can send fake pushes. **Verify the signature** (GitHub) or token (GitLab) before doing anything. |
| "I can verify the signature on the parsed JSON." | The HMAC is computed on the **exact raw bytes**. Re-serializing JSON changes whitespace and key order and breaks the match. Verify before parsing. |
| "Compare signatures with `==`." | Use a **constant-time comparison** (`hmac.compare_digest`) to avoid timing leaks. |
| "A failed delivery will be retried automatically." | GitHub **does not retry automatically**. You can redeliver manually or through the API. Design receivers to handle duplicates. |
| "Webhooks arrive in order." | They don't have to. Use the commit hash and timestamps, not arrival order. |
| "Branch protection stops people pushing." | Only if you **enable it**. By default anyone with write access can push to `main`. Require pull requests and checks on `main`. |
| "Deleting a file from Git removes it from history." | The file stays in **old commits**. A committed secret is a leaked secret: **rotate it**, then clean history if needed. |
| "`git pull` is always safe." | It fetches **and** merges (or rebases). Run `git fetch` and look first if the branch is shared. |
| "`.gitignore` untracks files." | It only affects **untracked** files. A file already committed stays tracked until `git rm --cached`. |
| "GitHub and GitLab webhooks are the same." | The headers, signing method and payload shape differ. A receiver written for one needs changes for the other. |
| "I can use my account password for `git push`." | GitHub no longer accepts account passwords for Git over HTTPS. Use **SSH keys** or a **personal access token**. |
| "Function URLs need IAM auth to be safe." | A URL with auth type `NONE` is public by design. Its protection is the **signature check in your code**. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| Lambda (execution role, environment, logging) | Post 13 |
| Secrets Manager (a secret fetched at runtime, ARN suffix) | Post 05 |
| CloudWatch Logs to read the evidence | Post 13 |
| `app.py`, `Dockerfile`, `requirements.txt`, `make_data.py` | Posts 06, 09 |

| You create here | Used by |
|---|---|
| Repository **`plat-platform`** | CodeBuild and CodePipeline source (18), CloudFormation and Terraform files (16), `buildspec.yml` |
| Secret `plat/github-webhook` | Only this receiver |
| Function `plat-webhook-echo` | A learning tool: you see exactly what a source event contains |

---

## Lab: Put the Platform in GitHub and Verify a Push 🛠️

You need a GitHub account (the steps are equivalent on GitLab, with the header differences above) and `git` on your machine.

### 1. Create the repository and push the code

On GitHub: **New repository**, name **`plat-platform`**, **Private**, no README, no template.

On your machine, in the folder where you built the API in Post 09:

```bash
mkdir -p plat-platform/app plat-platform/data
cd plat-platform
git init -b main

cp ../app.py ../requirements.txt ../Dockerfile ../.dockerignore app/
cp ../make_data.py data/

cat > .gitignore <<'EOF'
__pycache__/
*.pyc
.venv/
.env
*.csv
.terraform/
*.tfstate
*.tfstate.*
EOF

git add .
git commit -m "Add plat-api application and dataset generator"
git remote add origin git@github.com:<your-user>/plat-platform.git
git push -u origin main
```

Adjust the `cp` paths to where your Post 09 files actually are. `.gitignore` already excludes CSVs and Terraform state, which you will meet later: **state files contain secrets and never belong in Git**. If SSH is not set up, use the HTTPS URL and a fine-grained personal access token with *Contents: Read and write* on this repository.

```bash
git log --oneline
git status
```

```text
3b9f1c2 Add plat-api application and dataset generator
On branch main
nothing to commit, working tree clean
```

### 2. Store the webhook secret

In CloudShell, create a random shared secret and store it. Print it once so you can paste it into GitHub:

```bash
S=$(openssl rand -hex 32)
aws secretsmanager create-secret --name plat/github-webhook --secret-string "$S" \
  --tags Key=project,Value=plat --query ARN --output text
echo "$S"
```

```text
arn:aws:secretsmanager:us-east-1:123456789012:secret:plat/github-webhook-Ab12Cd
9f2e1d0c7a6b5e4d3c2b1a0f9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2f1e0d
```

Copy the second line (the secret). This secret uses the default `aws/secretsmanager` key, so the function won't need KMS permissions.

### 3. The receiver function

**IAM, Roles, Create role**: Lambda use case, `AWSLambdaBasicExecutionRole`, name **`plat-webhook-role`**. Add an inline policy `read-webhook-secret`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "arn:aws:secretsmanager:us-east-1:123456789012:secret:plat/github-webhook-*"
    }
  ]
}
```

The trailing `-*` matches the random six-character suffix in the ARN.

**Lambda, Create function** `plat-webhook-echo`, Python 3.12, role `plat-webhook-role`. Environment variable `SECRET_ID` = `plat/github-webhook`. Timeout 10 seconds. Replace the code and **Deploy**:

**`webhook.py`** (paste into `lambda_function.py`)

```python
import base64
import hashlib
import hmac
import json
import logging
import os

import boto3

log = logging.getLogger()
log.setLevel(logging.INFO)

sm = boto3.client("secretsmanager")
_secret = None


def secret():
    global _secret
    if _secret is None:
        _secret = sm.get_secret_value(SecretId=os.environ["SECRET_ID"])["SecretString"].encode()
    return _secret


def handler(event, context):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    raw = event.get("body") or ""
    body = base64.b64decode(raw) if event.get("isBase64Encoded") else raw.encode()

    sent = headers.get("x-hub-signature-256", "")
    expected = "sha256=" + hmac.new(secret(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sent, expected):
        log.warning("rejected delivery=%s", headers.get("x-github-delivery"))
        return {"statusCode": 401, "body": "invalid signature"}

    kind = headers.get("x-github-event", "unknown")
    delivery = headers.get("x-github-delivery")
    if kind == "ping":
        log.info(json.dumps({"event": "ping", "delivery": delivery}))
        return {"statusCode": 200, "body": "pong"}

    payload = json.loads(body)
    if kind == "push":
        log.info(json.dumps({
            "event": "push",
            "delivery": delivery,
            "repo": payload["repository"]["full_name"],
            "ref": payload["ref"],
            "head": payload["after"][:7],
            "commits": len(payload.get("commits", [])),
            "pusher": payload["pusher"]["name"],
        }))
    else:
        log.info(json.dumps({"event": kind, "delivery": delivery, "action": payload.get("action")}))
    return {"statusCode": 202, "body": "accepted"}
```

### 4. Give it a URL

On the function: **Configuration, Function URL, Create function URL**, auth type **NONE**, save. Copy the URL (it looks like `https://abc123xyz.lambda-url.us-east-1.on.aws/`). The console adds the resource-based permission that makes it publicly callable. Test the guard immediately:

```bash
URL=https://abc123xyz.lambda-url.us-east-1.on.aws/
curl -s -i -X POST $URL -d '{"hello":"world"}' | head -1
```

```text
HTTP/1.1 401 Unauthorized
```

An unsigned request gets `401`. The public URL is reachable but useless to anyone without the secret.

### 5. Register the webhook

In GitHub: repository **Settings, Webhooks, Add webhook**:

| Field | Value |
|---|---|
| Payload URL | the function URL |
| Content type | **application/json** |
| Secret | the string you printed in step 2 |
| SSL verification | Enable |
| Events | **Just the push event** |
| Active | Yes |

Save. GitHub sends a **ping** immediately. Open the webhook, **Recent Deliveries**: the ping shows a green tick and response `pong`.

### 6. Push and read the evidence

```bash
git switch -c feature/version-label
sed -i 's/"APP_VERSION", "1.0.0"/"APP_VERSION", "1.0.2"/' app/app.py
git add -p            # review the one-line change, press y
git commit -m "Default app version to 1.0.2"
git push -u origin feature/version-label
```

Check the function's logs in CloudShell:

```bash
aws logs tail /aws/lambda/plat-webhook-echo --since 5m --format short | grep '"event"'
```

```text
[INFO] {"event": "push", "delivery": "5a1b...", "repo": "<you>/plat-platform", "ref": "refs/heads/feature/version-label", "head": "c41d9ee", "commits": 1, "pusher": "<you>"}
```

(If the `sed` pattern doesn't match your file, make any one-line edit.) The `ref` tells a pipeline *which branch* and `head` tells it *which commit* to build. This is the entire contract a CI system needs.

On GitHub open a **pull request** from the branch to `main` and **merge** it. A merge to `main` is also a push: a second event with `"ref": "refs/heads/main"`.

### 7. Prove the signature check

1. In GitHub, edit the webhook and change the **Secret** to something else. Save.
2. Push another commit (or **Redeliver** an old delivery).
3. **Recent Deliveries** now shows a failed delivery: response `401`, body `invalid signature`. The log shows `rejected delivery=...`.
4. Set the secret back to the real value, open the failed delivery, and click **Redeliver**. It succeeds.

Redelivery is the manual retry GitHub offers. It also shows why receivers must tolerate seeing the same delivery twice.

### 8. Protect `main`

GitHub: **Settings, Branches** (or **Rules, Rulesets**), add a rule for `main`: **Require a pull request before merging**. From now on a direct push to `main` is refused. That is the guardrail the pipeline in Post 18 assumes.

### 9. Resources you now have 📦

| Resource | Name |
|---|---|
| GitHub repository | `plat-platform` (main protected), with `app/` and `data/` |
| Secret | `plat/github-webhook` |
| Role and function | `plat-webhook-role`, `plat-webhook-echo` (with a public function URL, signature-checked) |
| Webhook | push events to the function URL |

### Cleanup 🧹

All free at this scale. Keep the repository: every later post commits to it. Delete the webhook and function URL when you finish the series, or disable the webhook on the repository now if you don't want the log noise, since Post 18 replaces this mechanism.

---

## Quick Quiz 🧠

**Q1.** Your receiver returns `401` for every real delivery, though the secret is right. What is the most likely code bug?

<details>
<summary>Show answer</summary>

The HMAC is being computed over **something other than the raw body**: for example re-serialized JSON, a decoded or trimmed string, or the wrong encoding when the payload is base64-encoded by Lambda. Compute it over the exact bytes received.

</details>

**Q2.** Why use `hmac.compare_digest` instead of `==`?

<details>
<summary>Show answer</summary>

`==` can return as soon as it finds the first differing character, and the time taken can leak how much of a guessed signature was right. `compare_digest` takes **constant time**.

</details>

**Q3.** A teammate commits an AWS access key by mistake, then deletes the file in the next commit. Is the problem solved?

<details>
<summary>Show answer</summary>

No. The key remains in **history** and in any clones. **Rotate (deactivate) the key immediately**, then rewrite history if you need to remove it. Treat it as compromised.

</details>

**Q4.** What is the difference between how GitHub and GitLab authenticate a webhook?

<details>
<summary>Show answer</summary>

GitHub sends an **HMAC-SHA256 signature of the body** in `X-Hub-Signature-256`, which the receiver recomputes. GitLab (classically) sends the **secret token itself** in `X-Gitlab-Token`, which the receiver compares directly.

</details>

**Q5.** A webhook delivery fails because your function was down. What happens next?

<details>
<summary>Show answer</summary>

GitHub **does not retry on its own**. The delivery is recorded as failed, and you can **redeliver** it from the webhook's Recent Deliveries (or through the API).

</details>

---

## What's Next? 🚀

The code is in Git, and a push is now an event you can see. The next step is making infrastructure behave like code too: described in files, reviewed in pull requests, and re-created on demand. AWS has its own tool for this, and the industry has a popular alternative.

👉 **[Post 16: CloudFormation and Terraform](content/aws/16-cloudformation-and-terraform.md)**: the same small piece of infrastructure written twice, deployed twice, with drift, change sets, state and the mistakes that bite each tool.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
