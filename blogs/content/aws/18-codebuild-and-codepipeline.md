---
title: "CodeBuild and CodePipeline"
date: 2026-11-08
tags: [aws, codebuild, codepipeline, ci-cd, buildspec, ecr, ecs, codeconnections, approvals, intermediate]
description: Post 18 of the AWS series. How a build runs, the three roles in a pipeline, how GitHub connects without a webhook you maintain, and a lab where a git push builds and pushes the plat-api image and deploys it to ECS behind a manual approval, with failure alerts.
---

# `git push` Becomes a Deployment 🚦

By now you can build the image on your laptop (Post 09), push it to ECR (Post 11) and update the ECS service by hand. Every one of those steps is the sort that gets skipped at 6 p.m. on a Friday. A pipeline performs them the same way every time, on a machine nobody's logged into, and leaves a record.

Two services do the work:

- **CodeBuild** runs a build in a short-lived container and then throws it away.
- **CodePipeline** orders stages (**source, build, approval, deploy**) and passes **artifacts** between them.

![From push to deployed service](content/aws/images/18-pipeline.svg)

---

## CodeBuild in Five Facts 🔨

| Concept | Detail |
|---|---|
| **Project** | Source, environment (image, compute, privileged mode), service role, buildspec, artifacts, logs |
| **Buildspec** | A `buildspec.yml` in your repo defining **phases**: `install`, `pre_build`, `build`, `post_build`, plus `artifacts` |
| **Environment** | A managed container image (Amazon Linux or Ubuntu) or your own. Docker builds need **privileged mode** |
| **Service role** | The IAM role the build runs as. It decides what the build can do in AWS |
| **Billing** | Per build minute for the chosen compute size. No charge while idle |

Useful built-in variables: `CODEBUILD_RESOLVED_SOURCE_VERSION` (the commit hash), `CODEBUILD_BUILD_ID`, `AWS_DEFAULT_REGION`.

## CodePipeline in Five Facts 🛤️

| Concept | Detail |
|---|---|
| **Pipeline** | A series of **stages**, each with one or more **actions** |
| **Artifacts** | Files passed between stages through an **S3 artifact bucket** |
| **Source** | GitHub or GitLab through an **AWS CodeConnections** connection (a GitHub App you authorise once), CodeCommit, S3 and others |
| **Triggers** | A push to the connected branch starts an execution. V2 pipelines allow filters on branches, tags and file paths |
| **Manual approval** | Pauses the pipeline until someone approves in the console. Can notify an SNS topic |

### The three roles

| Role | Used by | Can |
|---|---|---|
| **Pipeline service role** | CodePipeline | Read and write the artifact bucket, start builds, update the ECS service, pass roles to ECS |
| **CodeBuild service role** | The build container | Write logs, read the artifact bucket, **push to ECR** |
| **ECS task roles** | The running service | Unchanged from Post 11 |

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "My pipeline has a webhook I have to maintain." | With a **connection**, the GitHub App sends events to AWS and you manage nothing. The mechanism from Post 15 still exists, just hidden. |
| "The connection is ready once created." | It starts in **Pending**. A person must complete the GitHub handshake in the console before it becomes **Available**. |
| "Docker works in CodeBuild by default." | You must turn on **privileged mode**, or `docker build` fails with *Cannot connect to the Docker daemon*. |
| "The pipeline role pushes the image." | **The CodeBuild role** pushes to ECR. The pipeline role starts the build. Mixing them up leads to the wrong role getting edited. |
| "Pushing `latest` is simpler." | Tags tell you **what is running**. Use the commit hash. `latest` hides which build you deployed and makes rollback guesswork. |
| "`imagedefinitions.json` can be named anything." | The ECS standard deploy action expects that file name, and each entry's `name` must **equal the container name** in the task definition (`api`). |
| "The deploy action changes my environment variables." | It only swaps the **image** in a new task definition revision. Other settings carry over from the service's current definition. |
| "Build caching is automatic." | Each build starts with an empty Docker cache unless you configure **local or S3 caching**. Slow builds are normal at first. |
| "A green pipeline means a working service." | The ECS action waits for the **service to become stable**, but only your health checks tell you the app is healthy. Add checks that matter. |
| "Approval means I get an email automatically." | You need to configure an **SNS topic** on the approval action. The approver also needs IAM permission to approve. |
| "Environment variables are fine for passwords." | CodeBuild can load values from **Parameter Store** or **Secrets Manager** at start. Plain variables show in the console. |
| "Everything in the pipeline runs forever for free." | You pay for build minutes, and for pipeline use (V1 charges per active pipeline, V2 per action execution minute). Costs are small for a lab, but check current pricing. |
| "Re-running `Release change` re-deploys an old commit." | It re-runs with the **latest** source revision on the branch. To go back, revert in Git, or point ECS at an earlier task definition. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| Repository `plat-platform` and branch protection | Post 15 |
| `app/Dockerfile`, `app.py`, `requirements.txt`, base image on ECR Public | Post 09 |
| ECR `plat/api`, cluster `plat-cluster`, service `plat-api-svc`, ALB | Post 11 |
| SNS topic `plat-alerts` | Post 14 |
| EventBridge event patterns | Post 14 |

| You create here | Used by |
|---|---|
| `buildspec.yml` in the repo | Every build |
| Pipeline **`plat-api-pipeline`** and the build project | The deployment path of the platform |
| Rule `plat-pipeline-failed` | Joins the alert stream with Post 21's alarms |

---

## Lab: A Pipeline from GitHub to ECS 🛠️

Work as Jim, in **N. Virginia**. The ECS service must be running with desired count 2 (Post 11). Replace `123456789012` with your account ID.

### 1. Add the buildspec to the repository

On your machine, in `plat-platform`:

**`buildspec.yml`**

```yaml
version: 0.2

env:
  variables:
    IMAGE_REPO: plat/api

phases:
  pre_build:
    commands:
      - echo "Checking the code compiles"
      - python3 -m py_compile app/app.py
      - ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
      - REGISTRY=$ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com
      - TAG=$(echo $CODEBUILD_RESOLVED_SOURCE_VERSION | cut -c1-7)
      - aws ecr get-login-password | docker login --username AWS --password-stdin $REGISTRY
  build:
    commands:
      - echo "Building $REGISTRY/$IMAGE_REPO:$TAG"
      - docker build --platform linux/amd64 -t $REGISTRY/$IMAGE_REPO:$TAG app/
  post_build:
    commands:
      - docker push $REGISTRY/$IMAGE_REPO:$TAG
      - printf '[{"name":"api","imageUri":"%s"}]' "$REGISTRY/$IMAGE_REPO:$TAG" > imagedefinitions.json
      - cat imagedefinitions.json

artifacts:
  files:
    - imagedefinitions.json
```

Commit it through a branch and pull request, as branch protection requires:

```bash
git switch main && git pull
git switch -c ci/buildspec
git add buildspec.yml
git commit -m "Add buildspec: compile check, build and push image, emit imagedefinitions"
git push -u origin ci/buildspec
# open a pull request on GitHub and merge it
git switch main && git pull
```

The `printf` line writes the file the ECS deploy action reads. The container name `api` matches the task definition from Post 11.

### 2. Connect GitHub

**Developer Tools (Settings), Connections, Create connection**: provider **GitHub**, name **`plat-github`**. Click **Connect to GitHub**, authorise, **Install a new app** for your account, and limit it to the `plat-platform` repository. Back in AWS, press **Connect**. The status must read **Available**.

### 3. Run a build by hand first (CodeBuild alone)

**CodeBuild, Create build project**:

| Setting | Value |
|---|---|
| Project name | `plat-api-build-manual` |
| Source provider | **GitHub**, using connection `plat-github`, repository `plat-platform` |
| Source version | `main` |
| Environment | **Managed image**, Amazon Linux, **Standard** runtime, the latest image offered |
| Privileged | **Enable** this flag (needed to build Docker images) |
| Service role | **New service role** (accept the generated name) |
| Compute | The smallest general option is fine (3 GB, 2 vCPUs) |
| Buildspec | **Use a buildspec file** (root `buildspec.yml`) |
| Logs | CloudWatch Logs on, group `/aws/codebuild/plat-api-build-manual` |

Create it and **Start build**. It fails in `PRE_BUILD`:

```text
An error occurred (AccessDenied) ... ecr:GetAuthorizationToken
```

The generated role can write logs and use the connection but has **no ECR permissions**. Open the role (link on the project page) and add this inline policy `push-plat-api`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*" },
    {
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart", "ecr:CompleteLayerUpload",
        "ecr:PutImage", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"
      ],
      "Resource": "arn:aws:ecr:us-east-1:123456789012:repository/plat/api"
    }
  ]
}
```

Start the build again. The phase list should end with `SUCCEEDED`, and the log contains:

```text
Building 123456789012.dkr.ecr.us-east-1.amazonaws.com/plat/api:3b9f1c2
...
[{"name":"api","imageUri":"123456789012.dkr.ecr.us-east-1.amazonaws.com/plat/api:3b9f1c2"}]
```

In ECR, `plat/api` now has a tag equal to the commit's first seven characters. The tag came from `CODEBUILD_RESOLVED_SOURCE_VERSION`. If the build fails with a Docker daemon error, privileged mode was not enabled.

### 4. Create the pipeline

**CodePipeline, Create pipeline, Build custom pipeline**:

| Step | Setting |
|---|---|
| Settings | Name **`plat-api-pipeline`**, type **V2**, new service role, execution mode **Queued** |
| Source | **GitHub (via GitHub App)**, connection `plat-github`, repository `plat-platform`, branch **`main`**, trigger on **push to branch** |
| Build | **Other build providers, AWS CodeBuild**, **Create project**: name `plat-api-build`, same environment settings as before (**privileged on**, managed Standard image), buildspec file, new service role |
| Test | Skip |
| Deploy | Skip for now (we add stages next) |

Create it. Add the missing ECR policy to the new CodeBuild role, exactly as in step 3. The first execution starts when the pipeline is created. Watch **Source** and **Build** go green, and open the **Build** action's output artifact: it contains `imagedefinitions.json`.

### 5. Add an approval and the deploy

Edit the pipeline. **Add stage** `Approve`, **Add action group**:

| Setting | Value |
|---|---|
| Action | **Manual approval** |
| Name | `ApproveDeploy` |
| SNS topic | `plat-alerts` |
| Comments | `Check the image tag in the build log before approving` |

Add stage `Deploy`, **Add action group**:

| Setting | Value |
|---|---|
| Action provider | **Amazon ECS** |
| Input artifact | `BuildArtifact` |
| Cluster / Service | `plat-cluster` / `plat-api-svc` |
| Image definitions file | `imagedefinitions.json` |

Save the pipeline. If the Deploy action later reports an authorisation error, check the pipeline role: it needs ECS update actions and `iam:PassRole` for the task and execution roles. The console generally adds these when you create the pipeline with a deploy action, but a stage added afterwards may need the policy extended by hand.

### 6. Ship a change

Make a visible change on a branch and merge it through a pull request:

```bash
git switch -c feature/ci-label
sed -i 's/"app": "plat-api"/"app": "plat-api-ci"/' app/app.py
git add app/app.py
git commit -m "Label the root response so deployments are visible"
git push -u origin feature/ci-label
# open a pull request and merge it
```

The merge to `main` is a push, so the pipeline starts. Watch it:

1. **Source** fetches the new commit.
2. **Build** runs `py_compile`, builds and pushes the new tag, and emits the artifact.
3. **Approve** pauses. You get an email from `plat-alerts` (once the subscription is confirmed). Open the pipeline, **Review**, and **Approve**.
4. **Deploy** registers a new task definition revision with the new image and starts a rolling deployment.

When the service is stable:

```bash
curl -s http://$ALB/
```

```text
{"app": "plat-api-ci", "version": "1.0.2", "host": "ip-10-20-11-34.ec2.internal"}
```

In ECS the service's task definition now has a **new revision** whose image tag is the commit hash. `git log --oneline` and the ECR tag tell you which code is running.

### 7. Make the pipeline fail, and be told

First create the alert. **EventBridge, Rules, Create rule** `plat-pipeline-failed`, pattern:

```json
{
  "source": ["aws.codepipeline"],
  "detail-type": ["CodePipeline Pipeline Execution State Change"],
  "detail": {
    "state": ["FAILED"],
    "pipeline": ["plat-api-pipeline"]
  }
}
```

Target: SNS topic `plat-alerts`. If emails don't arrive, add the EventBridge publish statement to the topic policy as in Post 14.

Now break the code on a branch:

```bash
git switch -c feature/break-it
echo "def broken(:" >> app/app.py
git add app/app.py
git commit -m "Deliberately break the build"
git push -u origin feature/break-it
# open a pull request and merge it
```

The pipeline starts, and the Build stage **fails** in `PRE_BUILD` at `py_compile`. The pipeline stops: **the Approve and Deploy stages never run**, so the running service is unaffected. Confirm with `curl -s http://$ALB/` (still the previous version), and within a minute or two you get the failure email.

Fix it by reverting the commit:

```bash
git switch main && git pull
git revert HEAD --no-edit
git push origin HEAD:revert/break-it     # then pull request and merge
```

The pipeline runs again and the next approved deployment restores a good version. In Git history this is a clean, reviewable record, and it is the rollback the pipeline understands.

### 8. Clean up the practice project

Delete the standalone `plat-api-build-manual` project (**CodeBuild, Build projects, Delete**) and its role. Keep the pipeline.

### 9. Resources you now have 📦

| Resource | Name |
|---|---|
| GitHub connection | `plat-github` (Available) |
| CodeBuild project | `plat-api-build` (privileged, role with ECR push) |
| Pipeline | `plat-api-pipeline` (Source, Build, Approve, Deploy), artifact bucket created by the wizard |
| Rule | `plat-pipeline-failed` to `plat-alerts` |
| In the repository | `buildspec.yml` |

### Cleanup 🧹

Idle pipelines cost little, and builds cost only while running. Keep it. If you pause the series, **disable the transition** into the Deploy stage so a stray push doesn't redeploy. Optionally set a lifecycle rule on the pipeline's artifact bucket.

---

## Quick Quiz 🧠

**Q1.** The build fails with `Cannot connect to the Docker daemon`. What is the fix?

<details>
<summary>Show answer</summary>

Enable **privileged mode** in the CodeBuild project's environment. Docker-in-build needs it.

</details>

**Q2.** The build gets to `docker push` and fails with `no basic auth credentials` or `AccessDenied`. Which role do you check, and which actions?

<details>
<summary>Show answer</summary>

The **CodeBuild service role**. It needs `ecr:GetAuthorizationToken` on `*` and the layer upload and `PutImage` actions on the repository. Also check the login command ran in `pre_build`.

</details>

**Q3.** The ECS deploy action fails: *container `api` not found*. What did you get wrong?

<details>
<summary>Show answer</summary>

The `name` in `imagedefinitions.json` must **equal the container name** in the task definition. Fix the `printf` in the buildspec, or the container name.

</details>

**Q4.** Why tag images with the commit hash instead of `latest`?

<details>
<summary>Show answer</summary>

You can trace running code back to an exact commit, each deployment is a distinct task-definition revision, and rolling back means selecting an earlier tag. With `latest` a pull may return anything, and running tasks don't update.

</details>

**Q5.** A broken commit reaches `main` and the pipeline fails in Build. Is production affected?

<details>
<summary>Show answer</summary>

No. Later stages **don't run** when an earlier stage fails, so the service keeps the version it had. You still revert or fix forward in Git.

</details>

---

## What's Next? 🚀

The delivery chain is complete: code in Git, infrastructure in templates, a pipeline to ship it. That finishes the engineering platform. Next comes the part this platform exists for: the **machine learning environment**. We need a reproducible Python environment, a place to explore data, and a way to run work that doesn't depend on someone's notebook.

👉 **[Post 19: ML Environments and SageMaker Studio](content/aws/19-ml-environments-and-sagemaker-studio.md)**: Conda environments, containers for ML, a SageMaker domain, and Dave running a processing job that cleans `events.csv`.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
