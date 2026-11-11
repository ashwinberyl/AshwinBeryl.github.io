---
title: "Delivery as Code: GitHub, CodeBuild and CodePipeline"
date: 2026-11-10
tags: [aws, terraform, codepipeline, codebuild, codestar-connections, ecr, ecs, iam-passrole, intermediate]
description: Post 12 of the AWS on Terraform series. A GitHub connection that Terraform creates and a person authorises, a build project with its buildspec inside the code, a three-stage pipeline with an optional deploy stage, the iam:PassRole condition, and a precondition that stops an impossible configuration at plan time.
---

# Pushing Code, Not Clicking 🚚

`stacks/80-delivery` closes the loop opened in Post 09. Until now a new version of the API meant running commands. Here a push to GitHub builds an image, pushes it to ECR and updates the ECS service, with no human involved.

One step cannot be automated, and it is worth understanding why: **authorising GitHub**. Terraform creates the connection object, which starts out `PENDING`, and a person has to log into GitHub and approve it. Credentials for a third-party account are not something AWS lets an API call grant on your behalf.

---

## The Pieces 🧱

| Piece | Resource(s) | Always on? |
|---|---|---|
| GitHub connection `plat-github` | `aws_codestarconnections_connection.github` | Yes (starts `PENDING`) |
| Artifact bucket | `module "artifacts"` | Yes |
| Build project + role + log group | `aws_codebuild_project.build`, `aws_iam_role.build`, `aws_iam_role_policy.build`, `aws_cloudwatch_log_group.build` | Yes |
| Pipeline + role | `aws_codepipeline.api`, `aws_iam_role.pipeline`, `aws_iam_role_policy.pipeline` | Yes |
| Deploy stage | a `dynamic "stage"` inside the pipeline | **Toggle** `enable_deploy_stage` |
| Failure alert | `aws_cloudwatch_event_rule.pipeline_failed`, `_target.pipeline_failed` | Yes |

![Delivery](content/aws-terraform/images/12-delivery.svg)

```hcl
# stacks/80-delivery/main.tf
locals {
  account_id   = data.aws_caller_identity.current.account_id
  repo_url     = data.terraform_remote_state.ecs.outputs.ecr_repository_url
  repo_arn     = data.terraform_remote_state.ecs.outputs.ecr_repository_arn
  cluster_name = data.terraform_remote_state.ecs.outputs.cluster_name
  service_name = data.terraform_remote_state.ecs.outputs.service_name
  task_role    = data.terraform_remote_state.ecs.outputs.task_role_arn
  exec_role    = data.terraform_remote_state.ecs.outputs.exec_role_arn
  topic_arn    = data.terraform_remote_state.events.outputs.topic_arn
  pipeline     = "plat-api-pipeline"
}
```

---

## Reading the Stack 📖

### The connection

```hcl
# stacks/80-delivery/main.tf
resource "aws_codestarconnections_connection" "github" {
  name          = "plat-github"
  provider_type = "GitHub"
}
```

Two arguments. The state after `apply` is `PENDING`. Open **Developer Tools, Settings, Connections**, choose `plat-github`, **Update pending connection**, log in to GitHub and install the AWS Connector app for your account. The status becomes `AVAILABLE`, and **it stays that way across later applies**: Terraform doesn't track the authorisation, only the object. The connection is the one piece of this series that exists in a half-built state by design.

### The artifact bucket

```hcl
# stacks/80-delivery/main.tf
module "artifacts" {
  source = "../../modules/s3-bucket"

  name          = "plat-pipeline-artifacts-${local.account_id}-${var.region}"
  versioning    = false
  force_destroy = true

  lifecycle_rules = [
    {
      id                              = "expire-artifacts"
      expiration_days                 = 14
      abort_incomplete_multipart_days = 1
    },
  ]
}
```

The same module as Post 06, called a third time with different arguments: no versioning, a 14-day expiry, force-destroy on. No KMS key (the default SSE-S3 is enough for build artifacts). The module's TLS policy and public-access block come with it for free.

### The build project

```hcl
# stacks/80-delivery/main.tf
resource "aws_codebuild_project" "build" {
  name         = "plat-api-build"
  service_role = aws_iam_role.build.arn

  source {
    type = "CODEPIPELINE"

    buildspec = <<-EOT
      version: 0.2
      phases:
        pre_build:
          commands:
            - aws ecr get-login-password --region $AWS_DEFAULT_REGION | docker login --username AWS --password-stdin $REPO_URL
            - IMAGE_TAG=$(echo $CODEBUILD_RESOLVED_SOURCE_VERSION | cut -c1-8)
        build:
          commands:
            - docker build -t $REPO_URL:$IMAGE_TAG -t $REPO_URL:latest .
        post_build:
          commands:
            - docker push $REPO_URL:$IMAGE_TAG
            - docker push $REPO_URL:latest
            - printf '[{"name":"%s","imageUri":"%s"}]' $CONTAINER_NAME $REPO_URL:$IMAGE_TAG > imagedefinitions.json
      artifacts:
        files:
          - imagedefinitions.json
    EOT
  }

  artifacts {
    type = "CODEPIPELINE"
  }

  environment {
    type            = "LINUX_CONTAINER"
    image           = "aws/codebuild/standard:7.0"
    compute_type    = "BUILD_GENERAL1_SMALL"
    privileged_mode = true # needed to run the Docker daemon

    environment_variable {
      name  = "REPO_URL"
      value = local.repo_url
    }

    environment_variable {
      name  = "CONTAINER_NAME"
      value = "api"
    }
  }

  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.build.name
    }
  }
}
```

* **`type = "CODEPIPELINE"`** for source and artifacts means the pipeline hands CodeBuild its input and takes its output; the project has no repository of its own.
* The **buildspec is inline** in the project. In many teams it lives in the application repository as `buildspec.yml`. We keep it here so the platform stays in one place; the trade-off is that changing the build means a Terraform apply.
* **`privileged_mode = true`** is required to run Docker inside the build container. It gives the build root-like access to its own container, so it is acceptable only for trusted source.
* The image tag is the first eight characters of the commit id, plus `latest`. An immutable tag per build is what makes a rollback possible: you can name the version you want.
* `imagedefinitions.json` is the contract with the ECS deploy action: container name and image URI.

### The build role

```hcl
# stacks/80-delivery/main.tf
data "aws_iam_policy_document" "codebuild_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "build" {
  name               = "plat-api-build-role"
  assume_role_policy = data.aws_iam_policy_document.codebuild_trust.json
}

data "aws_iam_policy_document" "build" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.build.arn}:*"]
  }

  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "EcrPush"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [local.repo_arn]
  }

  statement {
    sid       = "Artifacts"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:GetBucketLocation"]
    resources = [module.artifacts.arn, "${module.artifacts.arn}/*"]
  }
}

resource "aws_iam_role_policy" "build" {
  name   = "plat-api-build-access"
  role   = aws_iam_role.build.id
  policy = data.aws_iam_policy_document.build.json
}

resource "aws_cloudwatch_log_group" "build" {
  name              = "/codebuild/plat-api-build"
  retention_in_days = 14
}
```

Four needs, four statements. `ecr:GetAuthorizationToken` cannot be restricted to a repository (its resource must be `*`); the push actions can, and are. The artifact statement lists the bucket **and** `bucket/*` because `GetBucketLocation` applies to the bucket and the object actions to its contents.

### The pipeline

```hcl
# stacks/80-delivery/main.tf
resource "aws_codepipeline" "api" {
  name          = local.pipeline
  role_arn      = aws_iam_role.pipeline.arn
  pipeline_type = "V2"

  artifact_store {
    location = module.artifacts.id
    type     = "S3"
  }

  stage {
    name = "Source"

    action {
      name             = "GitHub"
      category         = "Source"
      owner            = "AWS"
      provider         = "CodeStarSourceConnection"
      version          = "1"
      output_artifacts = ["source_output"]

      configuration = {
        ConnectionArn        = aws_codestarconnections_connection.github.arn
        FullRepositoryId     = var.source_repo
        BranchName           = var.source_branch
        OutputArtifactFormat = "CODE_ZIP"
        DetectChanges        = "true"
      }
    }
  }

  stage {
    name = "Build"

    action {
      name             = "DockerBuild"
      category         = "Build"
      owner            = "AWS"
      provider         = "CodeBuild"
      version          = "1"
      input_artifacts  = ["source_output"]
      output_artifacts = ["build_output"]

      configuration = {
        ProjectName = aws_codebuild_project.build.name
      }
    }
  }

  dynamic "stage" {
    for_each = var.enable_deploy_stage ? [1] : []

    content {
      name = "Deploy"

      action {
        name            = "EcsDeploy"
        category        = "Deploy"
        owner           = "AWS"
        provider        = "ECS"
        version         = "1"
        input_artifacts = ["build_output"]

        configuration = {
          ClusterName = local.cluster_name
          ServiceName = local.service_name
          FileName    = "imagedefinitions.json"
        }
      }
    }
  }

  lifecycle {
    precondition {
      condition     = !var.enable_deploy_stage || local.service_name != null
      error_message = "enable_deploy_stage needs the ECS service: apply 52-ecs with -var enable_service=true first."
    }
  }
}
```

`pipeline_type = "V2"` is the current type. The Source stage uses the connection with `DetectChanges`, so a push to the branch starts an execution. Build runs CodeBuild. The **Deploy stage is a `dynamic` block**: `for_each = var.enable_deploy_stage ? [1] : []` produces zero or one stage, the same idiom as optional statements in policy documents.

Look at the `lifecycle` block at the bottom. A **precondition** states that deploying requires an ECS service to exist, and fails the plan with an explicit message otherwise. Without it you would get a pipeline that is created happily and fails on every run. Pushing the check to plan time is the same idea as variable validation in Post 02, applied to a cross-stack fact.

### The pipeline role

```hcl
# stacks/80-delivery/main.tf
data "aws_iam_policy_document" "pipeline_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["codepipeline.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "pipeline" {
  name               = "plat-api-pipeline-role"
  assume_role_policy = data.aws_iam_policy_document.pipeline_trust.json
}

data "aws_iam_policy_document" "pipeline" {
  statement {
    sid       = "Artifacts"
    actions   = ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject", "s3:GetBucketLocation", "s3:ListBucket"]
    resources = [module.artifacts.arn, "${module.artifacts.arn}/*"]
  }

  statement {
    sid       = "UseGithubConnection"
    actions   = ["codestar-connections:UseConnection"]
    resources = [aws_codestarconnections_connection.github.arn]
  }

  statement {
    sid       = "RunBuild"
    actions   = ["codebuild:StartBuild", "codebuild:BatchGetBuilds"]
    resources = [aws_codebuild_project.build.arn]
  }

  statement {
    sid = "DeployToEcs"
    actions = [
      "ecs:DescribeServices",
      "ecs:DescribeTaskDefinition",
      "ecs:DescribeTasks",
      "ecs:ListTasks",
      "ecs:RegisterTaskDefinition",
      "ecs:UpdateService",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "PassTaskRolesToEcs"
    actions   = ["iam:PassRole"]
    resources = [local.task_role, local.exec_role]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "pipeline" {
  name   = "plat-api-pipeline-access"
  role   = aws_iam_role.pipeline.id
  policy = data.aws_iam_policy_document.pipeline.json
}
```

The pipeline role touches five things: the artifact bucket, the connection, the build project, the ECS service, and **`iam:PassRole`**. The last one deserves attention. When the deploy action registers a new task definition it names the task role and the execution role, and **AWS requires the caller to be allowed to hand those roles to ECS**. The statement lists exactly two role ARNs and adds `iam:PassedToService = ecs-tasks.amazonaws.com`, so the pipeline can pass those roles only to ECS tasks and no others. Without `PassRole` the deploy fails with an error about the role, not about ECS.

### The failure alert

```hcl
# stacks/80-delivery/main.tf
resource "aws_cloudwatch_event_rule" "pipeline_failed" {
  name        = "plat-pipeline-failed"
  description = "plat-api-pipeline execution failed"

  event_pattern = jsonencode({
    source        = ["aws.codepipeline"]
    "detail-type" = ["CodePipeline Pipeline Execution State Change"]
    detail = {
      state    = ["FAILED"]
      pipeline = [local.pipeline]
    }
  })
}

resource "aws_cloudwatch_event_target" "pipeline_failed" {
  rule = aws_cloudwatch_event_rule.pipeline_failed.name
  arn  = local.topic_arn
}
```

Same shape as the EC2 rule from Post 11, with a pattern for `FAILED` executions of this pipeline. The topic policy already allows EventBridge, so the target needs nothing else.

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "Terraform can authorise the GitHub connection." | It creates it `PENDING`. Authorisation is a one-time manual step through the console. |
| "`PENDING` means something is broken." | It is the normal initial state. Pipelines referencing it fail at the Source stage until it is `AVAILABLE`. |
| "The pipeline role needs ECR permissions." | The **build** role pushes to ECR. The pipeline role starts the build and updates ECS. |
| "`iam:PassRole` is a minor detail." | It is the most common cause of deployment failures and a privilege-escalation path if written as `*`. Always name the roles and the service. |
| "Docker works in CodeBuild by default." | Only with `privileged_mode = true`, and a `docker` login to ECR first. |
| "The pipeline deploys the image tag `latest`." | It deploys the **commit-tagged** image named in `imagedefinitions.json`. `latest` is a convenience for humans. |
| "I changed the buildspec in the repo and nothing happened." | Here it is inline in Terraform. Edit it in `main.tf`, apply, then push. |
| "Terraform will undo the service's new image on the next apply." | Not with `ignore_changes` on the service (Post 09). This is the contract between the two stacks. |
| "A V2 pipeline with the Deploy stage off is invalid." | Two stages is valid. The Deploy stage is optional so the stack works before the service does. |
| "The failure rule can only watch the whole pipeline." | The pattern can also match a stage or an action. Here the pipeline's overall `FAILED` state is enough. |
| "The artifact bucket must be versioned." | Not for CodePipeline's own artifacts in this setup. They are disposable and expire in 14 days. |
| "The default source repository is mine." | `source_repo` defaults to the repository from the AWS series. Set it to the repository you are using. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| `ecr_repository_url`, `ecr_repository_arn`, `cluster_name`, `service_name`, task and execution role ARNs | `52-ecs` |
| `topic_arn` | `60-events` |
| The `s3-bucket` module | Post 06 |

| You create here | Used by |
|---|---|
| Pipeline `plat-api-pipeline` | Dashboard and alarms (Post 14), the verification script |
| Connection `plat-github` | The pipeline's source stage |
| Build log group `/codebuild/plat-api-build` | Log-based metrics and troubleshooting |

### Console clicks you no longer make

| In the AWS series you... | Here it is |
|---|---|
| **Developer Tools, Connections, Create connection** (then authorise) | `aws_codestarconnections_connection.github` + the same authorisation click |
| **CodeBuild, Create build project** (source, environment, buildspec, logs) | `aws_codebuild_project.build` |
| **CodePipeline, Create pipeline**: three stages | `aws_codepipeline.api` |
| **IAM, Create role** for both services, with policies | `aws_iam_role.build` and `aws_iam_role.pipeline` |
| **EventBridge, Create rule** for failed executions | `aws_cloudwatch_event_rule.pipeline_failed` |

---

## Lab: Push, Build, Deploy 🛠️

You need a GitHub repository with something to build. Make a tiny one:

```bash
gh repo create plat-api-demo --public --clone && cd plat-api-demo
printf 'FROM public.ecr.aws/docker/library/nginx:stable\nCOPY index.html /usr/share/nginx/html/index.html\n' > Dockerfile
echo 'version one' > index.html
git add . && git commit -m "first version" && git push -u origin main
cd ..
```

### 1. Plan and apply

```bash
export AWS_PROFILE=plat-admin AWS_REGION=us-east-1
scripts/tf.sh 80-delivery plan -var source_repo=<your-github-user>/plat-api-demo
```

```
Plan: 16 to add, 0 to change, 0 to destroy.
```

The connection (1), the artifact bucket module (6), the build project with role, policy and log group (4), the pipeline with role and policy (3), and the failure rule with its target (2).

```bash
scripts/tf.sh 80-delivery apply -var source_repo=<your-github-user>/plat-api-demo
```

### 2. Authorise the connection

Console, **Developer Tools, Settings, Connections**, `plat-github`, **Update pending connection**, sign in and install the AWS Connector for GitHub on your account. Then:

```bash
aws codestar-connections list-connections --query 'Connections[?ConnectionName==`plat-github`].ConnectionStatus' --output text
```

```
AVAILABLE
```

The execution that started when the pipeline was created has already failed at Source. Look:

```bash
aws codepipeline list-pipeline-executions --pipeline-name plat-api-pipeline --query 'pipelineExecutionSummaries[0].status' --output text
```

```
Failed
```

### 3. Run the pipeline

```bash
aws codepipeline start-pipeline-execution --name plat-api-pipeline
sleep 120
aws codepipeline get-pipeline-state --name plat-api-pipeline \
  --query 'stageStates[].[stageName,latestExecution.status]' --output text
```

```
Source  Succeeded
Build   Succeeded
```

The image is in the registry, tagged by commit:

```bash
aws ecr describe-images --repository-name plat-api --query 'imageDetails[0].imageTags' --output text
```

```
3f9c2a1d  latest
```

### 4. Switch on the deploy stage

The pipeline needs a running ECS service. Without one, Terraform refuses:

```bash
scripts/tf.sh 80-delivery plan -var source_repo=<your-github-user>/plat-api-demo -var enable_deploy_stage=true
```

```
Error: Resource precondition failed
  enable_deploy_stage needs the ECS service: apply 52-ecs with -var enable_service=true first.
```

That is the precondition doing its job, and it produces no partial change. Bring up the service from Post 09 and try again:

```bash
scripts/tf.sh 52-ecs apply -var enable_service=true
scripts/tf.sh 80-delivery apply -var source_repo=<your-github-user>/plat-api-demo -var enable_deploy_stage=true
```

```
Plan: 0 to add, 1 to change, 0 to destroy.
```

The pipeline gains a stage, in place.

### 5. Ship a change

```bash
cd plat-api-demo && echo 'version two' > index.html && git commit -qam "second version" && git push && cd ..
sleep 240
ALB=$(terraform -chdir=stacks/52-ecs output -raw alb_dns_name)
curl -s http://$ALB/
```

```
version two
```

A `git push` became a running change with nothing typed. Confirm that Terraform doesn't mind:

```bash
scripts/tf.sh 52-ecs plan -var enable_service=true
```

```
No changes. Your infrastructure matches the configuration.
```

The service now runs revision 2 with your commit's image, and `ignore_changes` is the reason this plan is quiet.

### 6. Break it: a failing build

```bash
cd plat-api-demo && echo 'FROM nonexistent-base-image:1' > Dockerfile && git commit -qam "break the build" && git push && cd ..
sleep 120
aws codepipeline get-pipeline-state --name plat-api-pipeline --query 'stageStates[].[stageName,latestExecution.status]' --output text
aws logs tail /codebuild/plat-api-build --since 5m | grep -i "error\|not found" | head -3
```

```
Source  Succeeded
Build   Failed
Deploy  Succeeded
```

The Deploy line is the **previous** execution's result. The service keeps serving `version two`, because a failed build never reaches the deploy action. If you set `alert_email` in Post 11, an email about the failed execution arrives from `plat-pipeline-failed`. Restore the Dockerfile and push.

### 7. Cause drift on the build project

```bash
aws codebuild update-project --name plat-api-build \
  --environment type=LINUX_CONTAINER,image=aws/codebuild/standard:7.0,computeType=BUILD_GENERAL1_MEDIUM,privilegedMode=true
scripts/tf.sh 80-delivery plan -var source_repo=<your-github-user>/plat-api-demo -var enable_deploy_stage=true
```

```
  # aws_codebuild_project.build will be updated in-place
      ~ compute_type = "BUILD_GENERAL1_MEDIUM" -> "BUILD_GENERAL1_SMALL"
Plan: 0 to add, 1 to change, 0 to destroy.
```

Someone gave the build more compute and a bigger bill. Apply to put it back.

### 8. Resources you now have 📦

| Resource | Name | Notes |
|---|---|---|
| Connection | `plat-github` | Authorised by hand |
| Bucket | `plat-pipeline-artifacts-<account>-<region>` | 14-day expiry |
| CodeBuild project | `plat-api-build` | Small, privileged |
| Pipeline | `plat-api-pipeline` | V2, Source, Build, (Deploy) |
| Roles | `plat-api-build-role`, `plat-api-pipeline-role` | |
| EventBridge rule | `plat-pipeline-failed` | To `plat-alerts` |

### Cleanup 🧹

Nothing here bills while idle apart from build minutes and artifact storage, which are cents. The ECS service and its load balancer from Post 09 are the real cost: `scripts/tf.sh 52-ecs apply` (service off) removes them, and the next push will then fail at the Deploy stage, which is the expected behaviour.

---

## Quick Quiz 🧠

**Q1.** The pipeline fails at Source with a message about the connection, immediately after `apply`. What is the likeliest reason?

<details>
<summary>Show answer</summary>

The connection is still **`PENDING`**: Terraform created it, but nobody has authorised it in the console. Once it is `AVAILABLE`, start the pipeline again.

</details>

**Q2.** Why is `iam:PassRole` limited by `iam:PassedToService`?

<details>
<summary>Show answer</summary>

`PassRole` lets a principal attach a role to a service. Restricting it to `ecs-tasks.amazonaws.com` means the pipeline can hand the two named roles only to ECS tasks, so a compromised pipeline cannot use them anywhere else.

</details>

**Q3.** `enable_deploy_stage = true` with the ECS service off fails at plan. Which feature produces that, and why is it better than failing at apply?

<details>
<summary>Show answer</summary>

A **`precondition`** in the pipeline's `lifecycle` block. It stops the plan with a clear message before anything is created, instead of leaving a half-built pipeline that fails on every execution.

</details>

**Q4.** The service runs a newer image than Terraform's task definition, and the plan is clean. Why?

<details>
<summary>Show answer</summary>

`ignore_changes = [task_definition, desired_count]` on `aws_ecs_service.api`. The pipeline owns deployments after creation, and Terraform deliberately does not compare them.

</details>

**Q5.** Which role needs ECR push permissions, the pipeline role or the build role?

<details>
<summary>Show answer</summary>

The **build role**: CodeBuild runs `docker push`. The pipeline role only starts builds and updates ECS, and nothing it does touches the registry.

</details>

---

## What's Next? 🚀

The platform is complete as a delivery chain. Machine learning is the part with its own lifecycle and its own costs: a Studio domain, a model and an endpoint you will want to switch off the minute you finish.

👉 [Post 13: SageMaker as Code: Studio, Models and an Endpoint on a Switch](content/aws-terraform/13-sagemaker-as-code.md)

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
