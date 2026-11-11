---
title: "The Terraform Pipeline: Plan on Pull Request, Apply on Merge"
date: 2026-11-11
tags: [aws, terraform, github-actions, oidc, ci-cd, drift, least-privilege, environments, intermediate]
description: Post 18 of the AWS on Terraform series. Three workflows that plan changed stacks on pull requests, apply them after an approval, and look for drift every morning, the OIDC trust conditions that decide which job gets which role, why every switch must now be a committed file, and how to narrow the apply role from administrator.
---

# Terraform on Autopilot 🤖

Until now you were the pipeline: `scripts/tf.sh <stack> apply` on your laptop, with the credentials of a person. That is fine for learning and wrong for a team, for two reasons. **Nobody reviews the plan** unless you show it to someone, and **the person's powerful credentials do the work**.

This post moves the work into GitHub Actions. A pull request produces a plan, as a comment, for reviewers. A merge applies it, after a named approver clicks a button. Every morning a job plans everything and opens an issue when reality has drifted from the code. No AWS key is stored anywhere in GitHub.

The roles these workflows assume were created in Post 01. Here you see why they were built that way.

---

## The Pieces 🧱

| Piece | File | What it does |
|---|---|---|
| Plan workflow | `.github/workflows/plan.yml` | On pull requests: plan each stack the change touches, comment the result |
| Apply workflow | `.github/workflows/apply.yml` | After merge: apply those stacks, behind an approval |
| Drift workflow | `.github/workflows/drift.yml` | Daily: plan every stack, open an issue if it finds changes |
| Stack selection | `scripts/changed-stacks.sh` | Turns a git diff into the list of stacks to run |
| Roles | `bootstrap/main.tf` | `plat-tf-plan` (read-only) and `plat-tf-apply` |
| Repository settings | GitHub | Variables, the `production` environment, its reviewers |

![The Terraform pipeline](content/aws-terraform/images/18-terraform-pipeline.svg)

---

## Reading the Pipeline 📖

### Which stacks to run

```bash
# scripts/changed-stacks.sh
#!/usr/bin/env bash
# Prints a JSON array of the stacks a change touches, for use as a GitHub Actions matrix.
#   scripts/changed-stacks.sh origin/main
# Rules: a change under stacks/<name> selects that stack. A change under modules/, scripts/ or
# bootstrap-independent shared files selects every stack, because they all use the module.
set -euo pipefail
BASE="${1:-origin/main}"
ALL=$(ls stacks | sort)
CHANGED=$(git diff --name-only "$BASE"...HEAD)

if echo "$CHANGED" | grep -qE '^(modules/|scripts/tf.sh)'; then
  SELECT="$ALL"
else
  SELECT=$(echo "$CHANGED" | grep -E '^stacks/' | cut -d/ -f2 | sort -u || true)
fi

echo "$SELECT" | grep -v '^$' | python3 -c 'import json,sys; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))'
```

A change under `stacks/20-network` selects that one stack. A change under `modules/` or to `scripts/tf.sh` selects **all** of them, because every stack uses them. The script prints a JSON array, which GitHub Actions turns into a **matrix**: one job per stack. The list comes from `ls stacks | sort`, and the numeric prefixes (10, 20, ...) make that the correct apply order.

### Plan on pull request

```yaml
# .github/workflows/plan.yml
name: plan

# Every pull request: plan each stack the change touches, using the READ-ONLY role.
on:
  pull_request:
    paths: ["stacks/**", "modules/**", "scripts/tf.sh"]

permissions:
  id-token: write       # lets the job ask GitHub for an OIDC token
  contents: read
  pull-requests: write  # to post the plan as a comment

jobs:
  find:
    runs-on: ubuntu-latest
    outputs:
      stacks: ${{ steps.pick.outputs.stacks }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - id: pick
        run: echo "stacks=$(scripts/changed-stacks.sh origin/${{ github.base_ref }})" >> "$GITHUB_OUTPUT"

  plan:
    needs: find
    if: needs.find.outputs.stacks != '[]'
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      max-parallel: 1        # stacks read each other's state, so plan them in order, one at a time
      matrix:
        stack: ${{ fromJSON(needs.find.outputs.stacks) }}
    concurrency:
      group: tf-${{ matrix.stack }}
      cancel-in-progress: false
    env:
      AWS_REGION: us-east-1
      TF_VAR_users: ${{ vars.USERS_JSON || '{}' }}
      TF_VAR_alert_email: ${{ vars.ALERT_EMAIL || '' }}
      TF_IN_AUTOMATION: "true"
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: 1.10.5
          terraform_wrapper: false
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ vars.AWS_PLAN_ROLE_ARN }}
          aws-region: us-east-1
      - name: plan
        id: plan
        run: |
          set +e
          scripts/tf.sh ${{ matrix.stack }} plan -input=false -no-color -detailed-exitcode -out=tfplan > plan.txt 2>&1
          echo "code=$?" >> "$GITHUB_OUTPUT"
          cat plan.txt
          exit 0
      - name: comment
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const code = '${{ steps.plan.outputs.code }}';
            const status = code === '0' ? 'No changes' : code === '2' ? 'Changes' : 'ERROR';
            let body = fs.readFileSync('plan.txt', 'utf8');
            if (body.length > 60000) body = '...(truncated)...\n' + body.slice(-60000);
            await github.rest.issues.createComment({
              ...context.repo, issue_number: context.issue.number,
              body: `### Plan: \`${{ matrix.stack }}\` (${status})\n<details><summary>Show plan</summary>\n\n\`\`\`\n${body}\n\`\`\`\n</details>`
            });
      - name: fail on error
        if: steps.plan.outputs.code == '1'
        run: exit 1
```

Points worth slowing down for:

* **`permissions: id-token: write`** is what allows the job to request a signed token from GitHub. Without it the credentials step fails, with an error that doesn't mention permissions.
* **`max-parallel: 1`**: stacks read each other's state, and concurrent plans would race on the state lock of a shared upstream. One at a time, in order.
* **`concurrency` per stack**: two runs for the same stack queue instead of running together, so a rapid second push doesn't collide with the first plan's lock.
* **`-detailed-exitcode`**: exit code `0` means no changes, `2` means changes, `1` means an error. The step stores the code and still exits `0`, so the next step can post the plan **even when it failed**, then a final step fails the job on `1`.
* **`terraform_wrapper: false`** stops the setup action from wrapping the binary in a script that rewrites output and exit codes.
* The roles come from **repository variables**, not secrets. A role ARN isn't secret, and using a variable keeps it visible in the logs when something goes wrong.

### Apply on merge

```yaml
# .github/workflows/apply.yml
name: apply

# After merge to main: apply each changed stack, but only after a human approves the "production" environment.
on:
  push:
    branches: [main]
    paths: ["stacks/**", "modules/**", "scripts/tf.sh"]

permissions:
  id-token: write
  contents: read

jobs:
  find:
    runs-on: ubuntu-latest
    outputs:
      stacks: ${{ steps.pick.outputs.stacks }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - id: pick
        run: echo "stacks=$(scripts/changed-stacks.sh ${{ github.event.before }})" >> "$GITHUB_OUTPUT"

  apply:
    needs: find
    if: needs.find.outputs.stacks != '[]'
    runs-on: ubuntu-latest
    environment: production    # configure required reviewers on this environment in the repository settings
    strategy:
      max-parallel: 1
      matrix:
        stack: ${{ fromJSON(needs.find.outputs.stacks) }}
    concurrency:
      group: tf-${{ matrix.stack }}
      cancel-in-progress: false
    env:
      AWS_REGION: us-east-1
      TF_VAR_users: ${{ vars.USERS_JSON || '{}' }}
      TF_VAR_alert_email: ${{ vars.ALERT_EMAIL || '' }}
      TF_IN_AUTOMATION: "true"
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: 1.10.5
          terraform_wrapper: false
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ vars.AWS_APPLY_ROLE_ARN }}
          aws-region: us-east-1
      - run: scripts/tf.sh ${{ matrix.stack }} apply -input=false -auto-approve
```

`environment: production` is the gate. A job that targets an environment waits until the environment's **required reviewers** approve it. For the OIDC token this has a consequence that surprises almost everyone: when a job declares an environment, the token's `sub` claim becomes `repo:OWNER/REPO:environment:production`, and **the branch is no longer in it**. That is why the apply role in Post 01 trusts the environment, and why the environment must be restricted to the `main` branch in repository settings.

### Drift

```yaml
# .github/workflows/drift.yml
name: drift

# Every morning: does reality still match the code? A plan with changes means someone edited AWS by hand.
on:
  schedule:
    - cron: "30 1 * * *"   # 07:00 in Bengaluru
  workflow_dispatch:

permissions:
  id-token: write
  contents: read
  issues: write

jobs:
  drift:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      max-parallel: 1
      matrix:
        stack: [10-identity, 20-network, 30-security, 40-data, 50-ec2, 52-ecs, 55-eks, 60-events, 70-ml, 80-delivery, 90-observe, 95-cost]
    env:
      AWS_REGION: us-east-1
      TF_VAR_users: ${{ vars.USERS_JSON || '{}' }}
      TF_VAR_alert_email: ${{ vars.ALERT_EMAIL || '' }}
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: 1.10.5
          terraform_wrapper: false
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ vars.AWS_PLAN_ROLE_ARN }}
          aws-region: us-east-1
      - name: plan
        id: plan
        run: |
          set +e
          scripts/tf.sh ${{ matrix.stack }} plan -input=false -no-color -detailed-exitcode > plan.txt 2>&1
          echo "code=$?" >> "$GITHUB_OUTPUT"
          exit 0
      - name: open an issue when drift is found
        if: steps.plan.outputs.code == '2'
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh label create drift --color D93F0B --description "Reality differs from the code" 2>/dev/null || true
          OPEN=$(gh issue list --label drift --state open --search "Drift in ${{ matrix.stack }} in:title" --json number --jq length)
          if [ "$OPEN" = "0" ]; then
            gh issue create --label drift --title "Drift in ${{ matrix.stack }}" \
              --body "The scheduled plan found changes. Run: scripts/tf.sh ${{ matrix.stack }} plan"
          fi
      - name: fail on plan error
        if: steps.plan.outputs.code == '1'
        run: cat plan.txt && exit 1
```

A scheduled workflow always runs on the default branch, so its token's `sub` is the **main** branch, not a pull request. That is the reason the plan role trusts `ref:refs/heads/main` as well: it is read-only, so the extra trust costs nothing. A plan with exit code `2` opens an issue (once per stack, so a long-lived drift doesn't flood you). The schedule is `01:30 UTC`, 07:00 in Bengaluru.

### The trust that makes it work

```hcl
# bootstrap/main.tf
data "aws_iam_policy_document" "plan_trust" {
  count = var.enable_ci_roles ? 1 : 0

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${local.github_sub_prefix}:pull_request", "${local.github_sub_prefix}:ref:refs/heads/main"]
    }
  }
}

data "aws_iam_policy_document" "apply_trust" {
  count = var.enable_ci_roles ? 1 : 0

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${local.github_sub_prefix}:environment:production"]
    }
  }
}
```

The `aud` condition says the token was minted for AWS. The **`sub`** condition says which job is asking. A list of values means "any of these". Compare the two roles: a pull request, which may contain unreviewed code, can only be the read-only role; the apply role needs a job that went through an approval.

### Narrowing the apply role

The apply role starts with `AdministratorAccess`. That is convenient while building and far too much for a pipeline. The bootstrap stack contains a switch to narrow it:

```hcl
# bootstrap/main.tf
resource "aws_iam_role_policy_attachment" "apply_admin" {
  count = var.enable_ci_roles && !var.apply_role_scoped ? 1 : 0

  role       = aws_iam_role.apply[0].name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

resource "aws_iam_role_policy_attachment" "apply_power_user" {
  count = var.enable_ci_roles && var.apply_role_scoped ? 1 : 0

  role       = aws_iam_role.apply[0].name
  policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}

data "aws_iam_policy_document" "apply_scoped_iam" {
  statement {
    sid     = "ManagePlatIam"
    actions = ["iam:*"]

    resources = [
      "arn:aws:iam::${local.account_id}:role/plat-*",
      "arn:aws:iam::${local.account_id}:policy/plat-*",
      "arn:aws:iam::${local.account_id}:instance-profile/plat-*",
    ]
  }

  statement {
    sid       = "ReadIamAndCreateServiceLinkedRoles"
    actions   = ["iam:Get*", "iam:List*", "iam:CreateServiceLinkedRole", "iam:SimulatePrincipalPolicy"]
    resources = ["*"]
  }

  statement {
    sid       = "OrganizationsReadForIdentityCenter"
    actions   = ["organizations:Describe*", "organizations:List*"]
    resources = ["*"]
  }

  statement {
    sid       = "NeverTouchTheCiRoles"
    effect    = "Deny"
    actions   = ["iam:*"]
    resources = ["arn:aws:iam::${local.account_id}:role/plat-tf-*"]
  }
}

resource "aws_iam_role_policy" "apply_scoped_iam" {
  count = var.enable_ci_roles && var.apply_role_scoped ? 1 : 0

  name   = "plat-scoped-iam"
  role   = aws_iam_role.apply[0].id
  policy = data.aws_iam_policy_document.apply_scoped_iam.json
}
```

With `apply_role_scoped = true` the role has:

* **`PowerUserAccess`**: every service **except** IAM, Organizations and account management. That covers S3, EC2, ECS, EKS, Lambda, SageMaker and the rest of what the stacks build.
* **IAM limited to the platform's names**: it may manage roles, policies and instance profiles named `plat-*`, and read everything else in IAM. It cannot create a role called `admin-backdoor`.
* **An explicit Deny on `plat-tf-*`**: the pipeline can never edit its own roles, so a compromised pipeline cannot widen its own access. Those roles are changed only by you, from bootstrap, on your computer.

This is a starting point, not a certificate. Some actions the stacks use may need adding (see the lab), and that is the normal way to discover the real minimum.

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "OIDC means I need to store a token in GitHub." | There is nothing to store. GitHub signs a token per job and AWS exchanges it for credentials that expire in an hour. |
| "The `sub` is `repo:OWNER/REPO:ref:refs/heads/main` for any main-branch job." | Only for jobs without an environment. A job with an environment gets `...:environment:NAME`. |
| "A pull request from a branch can use the apply role if I name the same branch." | The apply role trusts the **environment**, which is restricted to `main` and requires approval. |
| "A read-only plan role needs no write permissions." | A plan **takes the state lock**, which writes an object in the state bucket. The plan role has that one write. |
| "The plan I reviewed is what gets applied." | The apply workflow runs a **fresh** plan after merge. If the world changed in between, the result can differ. Saving and approving the exact plan file is the stricter pattern. |
| "I can run the pipeline without committing toggles." | Variables passed with `-var` on your laptop are not stored. The pipeline runs with defaults, so it would **switch every costly toggle off** on the next apply. |
| "Branch protection isn't needed because there's an approval." | Both are needed: protection decides what reaches `main`, the approval decides what reaches AWS. |
| "Drift detection only needs a plan." | And somewhere to tell people. The workflow opens an issue so it isn't a log line nobody reads. |
| "Applying stacks in parallel is faster." | Stacks depend on each other's state and outputs; parallel runs race. |
| "A pull request can plan a stack whose upstream isn't applied yet." | It can't read outputs that don't exist yet. For changes spanning stacks, merge and apply the upstream stack first. |
| "`PowerUserAccess` can't touch IAM at all." | Correct, which is why the scoped policy adds IAM back, limited to `plat-*`. |
| "The apply role should be able to change the CI roles." | It should not: that is how a pipeline compromise becomes permanent. Bootstrap stays a human job. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| OIDC provider and the two roles | Bootstrap (Post 01) |
| Remote state, `tf.sh` and the backend | Post 01 |
| Quality workflows | Post 17 |
| Stack order and toggles | Every stack |

| You create here | Used by |
|---|---|
| Plan comments | Reviewers |
| The `production` environment | The apply workflow |
| Drift issues | You |
| Committed toggle files | The pipeline's idea of what should exist |

### Console clicks you no longer make

| Habit | Replaced by |
|---|---|
| Run `apply` on your laptop with your admin session | `apply.yml` with the apply role |
| Paste a plan into a chat to get it reviewed | `plan.yml` comments on the pull request |
| Remember to check the console for surprises | `drift.yml` and its issues |
| Create an IAM user with access keys for CI | The OIDC trust: no keys |

---

## Lab: Run It For Real 🛠️

This lab needs the code pushed to a GitHub repository named `plat-platform-terraform` under your account (the name the bootstrap roles trust, `github_owner` and `github_repo` in `bootstrap/variables.tf`). Create it empty on GitHub, push this directory to it, and enable Actions.

### 1. Make the trust current

Earlier versions of the bootstrap code trusted the `main` branch for the apply role. The current code trusts the environment. Re-apply bootstrap:

```bash
export AWS_PROFILE=plat-admin AWS_REGION=us-east-1
scripts/tf.sh bootstrap plan
```

```
  # aws_iam_role.apply[0] will be updated in-place
  ~ assume_role_policy = jsonencode(...)
  # aws_iam_role.plan[0] will be updated in-place
  ~ assume_role_policy = jsonencode(...)

Plan: 0 to add, 2 to change, 0 to destroy.
```

Apply it. (If you applied bootstrap after this post's code arrived, the plan is empty.)

### 2. Tell GitHub which roles to use

```bash
gh variable set AWS_PLAN_ROLE_ARN  --body "$(terraform -chdir=bootstrap output -raw plan_role_arn)"
gh variable set AWS_APPLY_ROLE_ARN --body "$(terraform -chdir=bootstrap output -raw apply_role_arn)"
gh variable set USERS_JSON --body '{}'
gh variable set ALERT_EMAIL --body "you@example.com"
```

`USERS_JSON` is the Identity Center user map from Post 03 as JSON, for example `{"jim":{"given_name":"Jim","family_name":"Halpert","email":"jim@example.com","groups":["Scientists"]}}`. The command above sets `{}`, which makes the identity stack plan to remove any users it manages. If you manage users here, set the real map instead.

### 3. Create the approval gate

```bash
OWNER=$(gh api user --jq .login); ID=$(gh api user --jq .id); REPO=plat-platform-terraform
cat > /tmp/env.json <<JSON
{"reviewers":[{"type":"User","id":$ID}],"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}
JSON
gh api -X PUT repos/$OWNER/$REPO/environments/production --input /tmp/env.json
gh api -X POST repos/$OWNER/$REPO/environments/production/deployment-branch-policies -f name=main
```

A required reviewer (you) and a restriction to `main`. For a team, list more reviewers. On a personal account, GitHub may not let the author approve their own run when "prevent self-review" is on; leave it off for the lab.

### 4. Write the toggles down

Anything you switched on with `-var` in earlier labs is invisible to the pipeline. Put each in a committed file so that "the code" and "what exists" agree. For example, if the NAT and the ECS service are on:

```bash
echo 'enable_nat = true'     > stacks/20-network/toggles.auto.tfvars
echo 'enable_service = true' > stacks/52-ecs/toggles.auto.tfvars
git add stacks/*/toggles.auto.tfvars
```

`*.auto.tfvars` files load automatically, and this repository's `.gitignore` explicitly allows them. From now on **turning something on or off is a commit**, reviewed and applied like any other change. (`make pause` still works, but it only changes your local run: the next merge would put the file's values back.)

### 5. Open a pull request and read the plan

```bash
git checkout -b raise-budget
sed -i 's/default     = "20"/default     = "25"/' stacks/95-cost/variables.tf
git commit -am "Raise the monthly budget to 25" && git push -u origin raise-budget
gh pr create --fill
```

In the pull request, the `plan` workflow starts. After a minute or two a comment appears:

```
### Plan: `95-cost` (Changes)

  # aws_budgets_budget.monthly will be updated in-place
  ~ limit_amount = "20" -> "25"

Plan: 0 to add, 1 to change, 0 to destroy.
```

Only `95-cost` ran, because only that directory changed. **That comment is what a reviewer approves.** Notice there is also a `quality` check running tflint, trivy and the module tests from Post 17.

### 6. Merge and approve

Merge the pull request. The `apply` workflow starts and **waits**: in the Actions tab, open the run and click **Review deployments**, tick `production`, **Approve and deploy**. Then:

```
aws_budgets_budget.monthly: Modifying...
aws_budgets_budget.monthly: Modifications complete
Apply complete! Resources: 0 added, 1 changed, 0 destroyed.
```

No key was stored, and no one ran `terraform` on a laptop.

### 7. Break it: a pull request tries to use the apply role

On a new branch, edit `.github/workflows/plan.yml` to use `vars.AWS_APPLY_ROLE_ARN` instead of `vars.AWS_PLAN_ROLE_ARN`, push, and open a pull request. The credentials step fails:

```
Error: Could not assume role with OIDC: Not authorized to perform sts:AssumeRoleWithWebIdentity
```

That is the trust policy doing its job. The pull request's token has the subject `repo:OWNER/plat-platform-terraform:pull_request`, which the apply role doesn't list. Close the pull request without merging.

### 8. Find drift

Change something by hand, then run the drift job without waiting for the morning:

```bash
aws cloudwatch disable-alarm-actions --alarm-names plat-dlq-not-empty
gh workflow run drift
sleep 180
gh issue list --label drift
```

```
12  Drift in 90-observe  drift  about 1 minute ago
```

The workflow creates the `drift` label if needed and opens **one** issue per stack: a second night of the same drift doesn't add a second issue. Apply `90-observe` locally, or merge a no-op change to it, to clear the drift, and close the issue.

### 9. Narrow the apply role

```bash
echo 'apply_role_scoped = true' > bootstrap/toggles.auto.tfvars
scripts/tf.sh bootstrap plan
```

```
  # aws_iam_role_policy.apply_scoped_iam[0] will be created
  # aws_iam_role_policy_attachment.apply_admin[0] will be destroyed
  # aws_iam_role_policy_attachment.apply_power_user[0] will be created
Plan: 2 to add, 0 to change, 1 to destroy.
```

Apply it, then make a trivial change to one stack through the pull-request flow and watch the apply succeed. If an apply fails with `AccessDenied` for some action, the message names the action and the resource: add it to `data.aws_iam_policy_document.apply_scoped_iam`, re-apply bootstrap from your computer, and re-run. That loop is how a least-privilege policy is actually found, and the explicit deny means the pipeline can never add the permission itself.

### 10. Resources you now have 📦

| Resource | Where | Notes |
|---|---|---|
| Workflows | `.github/workflows/` | `plan`, `apply`, `drift`, `quality`, `terraform` |
| Repository variables | GitHub | Role ARNs, users, alert email |
| Environment `production` | GitHub | Reviewers + main only |
| Roles | AWS | `plat-tf-plan`, `plat-tf-apply` |

### Cleanup 🧹

Nothing to remove in AWS; these cost nothing. Disable the `drift` workflow if you don't want daily runs while the lab is paused (`gh workflow disable drift`).

---

## Quick Quiz 🧠

**Q1.** The apply job fails with `Not authorized to perform sts:AssumeRoleWithWebIdentity` although the role ARN is right and the job runs on `main`. What did you probably miss?

<details>
<summary>Show answer</summary>

The job declares `environment: production`, so its token's `sub` is `repo:OWNER/REPO:environment:production`, not the `ref:refs/heads/main` form. The role's trust policy has to name the environment.

</details>

**Q2.** Why does a read-only plan role need `s3:PutObject` on the state bucket?

<details>
<summary>Show answer</summary>

Terraform's native lock is an **object written to the bucket** next to the state. Even a plan takes the lock, so the role needs to create and delete that object (and nothing else is written).

</details>

**Q3.** You committed no toggle files. What happens at the next merge?

<details>
<summary>Show answer</summary>

The pipeline plans and applies with **default** values, so every toggle that you had switched on with `-var` (NAT, service, RDS...) is switched **off**. Toggles that should persist belong in committed `*.auto.tfvars` files.

</details>

**Q4.** Why does the apply role carry an explicit `Deny` on `role/plat-tf-*`?

<details>
<summary>Show answer</summary>

So the pipeline cannot edit its **own** roles. An explicit deny overrides any allow, which means a compromised or buggy apply cannot widen its own access. Changes to those roles are human-only, from bootstrap.

</details>

**Q5.** Why is the drift workflow's plan role trusted on `ref:refs/heads/main`?

<details>
<summary>Show answer</summary>

Scheduled workflows run on the default branch and have **no pull request and no environment**, so their `sub` is the main-branch form. The role is read-only, so trusting it costs nothing.

</details>

---

## What's Next? 🚀

Everything is in place: code, tests, a pipeline. The last post puts it together: one command to bring the platform up, one to check it, a table of what costs what, and the order to tear it all down.

👉 [Post 19: The Capstone: Bring It Up, Check It, Tear It Down](content/aws-terraform/19-the-capstone.md)

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
