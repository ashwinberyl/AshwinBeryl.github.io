---
title: "Containers on ECS: ECR, Fargate and an Application Load Balancer"
date: 2026-11-09
tags: [aws, terraform, ecr, ecs, fargate, alb, iam, security-groups, intermediate]
description: Post 9 of the AWS on Terraform series. An encrypted image registry with a lifecycle rule, a cluster, the execution role versus the task role, security groups that reference each other, a task definition built with jsonencode, and a service that Terraform creates and then stops managing.
---

# Running the API 🐳

This stack takes the container from the AWS series and makes it Terraform. It is `stacks/52-ecs`: a registry, a cluster, two roles, a task definition, a load balancer and a service. The load balancer and the service are behind a toggle because both bill every hour.

---

## The Pieces 🧱

| Piece | Resource(s) | Always on? |
|---|---|---|
| Registry `plat-api` + lifecycle rule | `aws_ecr_repository.api`, `aws_ecr_lifecycle_policy.api` | Yes (free until you push) |
| Cluster `plat-cluster` + log group | `aws_ecs_cluster.this`, `aws_cloudwatch_log_group.api` | Yes |
| Execution role and task role | `aws_iam_role.exec`, `aws_iam_role.task`, attachment and inline policy | Yes |
| `plat-alb-sg`, `plat-api-sg` + four rules | `aws_security_group.*`, `aws_vpc_security_group_*_rule.*` | Yes |
| Task definition `plat-api` | `aws_ecs_task_definition.api` | Yes (a definition costs nothing) |
| Load balancer, target group, listener | `aws_lb.api`, `aws_lb_target_group.api`, `aws_lb_listener.http` | **Toggle** `enable_service` |
| Service `plat-api-svc` | `aws_ecs_service.api` | **Toggle** `enable_service` |

![ECS on Fargate behind an ALB](content/aws-terraform/images/09-ecs-fargate-alb.svg)

### What it reads from other stacks

```hcl
# stacks/52-ecs/main.tf
locals {
  vpc_id     = data.terraform_remote_state.network.outputs.vpc_id
  public     = values(data.terraform_remote_state.network.outputs.public_subnet_ids)
  private    = values(data.terraform_remote_state.network.outputs.private_subnet_ids)
  kms_arn    = data.terraform_remote_state.security.outputs.kms_key_arn
  app_sg_id  = data.terraform_remote_state.security.outputs.app_sg_id
  bucket_arn = data.terraform_remote_state.data.outputs.data_bucket_arn
  bucket     = data.terraform_remote_state.data.outputs.data_bucket
  table_arn  = data.terraform_remote_state.data.outputs.jobs_table_arn
  table      = data.terraform_remote_state.data.outputs.jobs_table_name
  secret_arn = data.terraform_remote_state.data.outputs.rds_secret_arn
  rds_host   = data.terraform_remote_state.data.outputs.rds_endpoint
}
```

`secret_arn` and `rds_host` come from `40-data` and are `null` while RDS is off. The code is written so that "no database yet" is a valid state, not an error.

---

## Reading the Stack 📖

### The registry

```hcl
# stacks/52-ecs/main.tf
resource "aws_ecr_repository" "api" {
  name                 = "plat-api"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = local.kms_arn
  }
}

resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}
```

* `scan_on_push` runs a basic vulnerability scan whenever an image arrives.
* The repository is encrypted with the shared key. The principal that **pulls** images then needs `kms:Decrypt` on it, which the execution role gets through the managed policy only for ECR's own use. If a pull ever fails with a KMS error, this setting is why.
* `force_delete = true` lets `destroy` remove the repository even with images in it. Right for a lab; a mistake for production.
* The lifecycle policy expires everything beyond the ten newest images, so the registry cannot grow without limit.

### Two roles, two jobs

```hcl
# stacks/52-ecs/main.tf
resource "aws_iam_role" "exec" {
  name               = "plat-ecs-exec-role"
  assume_role_policy = data.aws_iam_policy_document.tasks_trust.json
}

resource "aws_iam_role_policy_attachment" "exec" {
  role       = aws_iam_role.exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "task" {
  name               = "plat-ecs-task-role"
  assume_role_policy = data.aws_iam_policy_document.tasks_trust.json
}
```

The **execution role** is used by ECS itself, before and around your code: pull the image, write to the log group. The **task role** is used by your code: whatever the container calls through the SDK. Mixing them up is the commonest ECS permissions mistake, in both directions.

```hcl
# stacks/52-ecs/main.tf
data "aws_iam_policy_document" "task_access" {
  statement {
    sid       = "ListBucket"
    actions   = ["s3:ListBucket"]
    resources = [local.bucket_arn]
  }

  statement {
    sid       = "ReadWriteObjects"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${local.bucket_arn}/*"]
  }

  statement {
    sid       = "JobsTable"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"]
    resources = [local.table_arn, "${local.table_arn}/index/*"]
  }

  # Both the bucket and the table are encrypted with the platform key, so callers need it too.
  statement {
    sid       = "UseDataKey"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
    resources = [local.kms_arn]
  }

  # Only when RDS exists: its managed secret, and the key that encrypts it.
  dynamic "statement" {
    for_each = local.secret_arn == null ? [] : [local.secret_arn]

    content {
      sid       = "ReadDbSecret"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = [statement.value]
    }
  }
}

resource "aws_iam_role_policy" "task_access" {
  name   = "plat-api-access"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task_access.json
}
```

Three details:

* The table statement lists the **index ARN** (`/index/*`) as well as the table. A query through an index is authorised against the index resource.
* `UseDataKey` appears again, for the third time in this series, because the bucket and the table both use `plat-data`.
* The `dynamic "statement"` adds the secret permission **only when the database exists**. A policy with `resources = [null]` would be a plan error; a dynamic block with an empty list produces no statement at all.

### Security groups that point at each other

```hcl
# stacks/52-ecs/main.tf
resource "aws_security_group" "alb" {
  name        = "plat-alb-sg"
  description = "Public entry to the load balancer"
  vpc_id      = local.vpc_id

  tags = { Name = "plat-alb-sg" }
}

resource "aws_security_group" "api" {
  name        = "plat-api-sg"
  description = "API tasks: traffic from the load balancer only"
  vpc_id      = local.vpc_id

  tags = { Name = "plat-api-sg" }
}

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  description       = "HTTP from the internet"
}

resource "aws_vpc_security_group_egress_rule" "alb_to_api" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.api.id
  ip_protocol                  = "tcp"
  from_port                    = var.container_port
  to_port                      = var.container_port
  description                  = "To the API tasks"
}

resource "aws_vpc_security_group_ingress_rule" "api_from_alb" {
  security_group_id            = aws_security_group.api.id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = var.container_port
  to_port                      = var.container_port
  description                  = "From the load balancer"
}

resource "aws_vpc_security_group_egress_rule" "api_all" {
  security_group_id = aws_security_group.api.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "All outbound"
}
```

The load balancer accepts port 80 from anywhere and may talk only to `plat-api-sg`. The tasks accept their port only from `plat-alb-sg`. Referencing groups instead of address ranges means the rules stay correct however many tasks exist or whatever addresses they get. The ALB group has **no** all-outbound rule: remember that Terraform removes the default egress rule (Post 05), so only the rule above exists.

### The task definition

```hcl
# stacks/52-ecs/main.tf
resource "aws_ecs_task_definition" "api" {
  family                   = "plat-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.exec.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name      = "api"
    image     = var.container_image
    essential = true

    portMappings = [{ containerPort = var.container_port, protocol = "tcp" }]

    environment = [
      { name = "TABLE_NAME", value = local.table },
      { name = "BUCKET_NAME", value = local.bucket },
      { name = "DB_HOST", value = local.rds_host == null ? "" : local.rds_host },
      { name = "DB_SECRET_ARN", value = local.secret_arn == null ? "" : local.secret_arn },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.api.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "api"
      }
    }
  }])
}
```

`container_definitions` is a JSON string; `jsonencode` writes it from an HCL list so there is no escaping to get wrong. `awsvpc` mode gives each task its own network interface and address, which is what lets security groups apply to tasks. The default image is a public nginx so the service can start **before** you push anything to ECR; you switch to your own image with `container_image`.

### Balancer and service

```hcl
# stacks/52-ecs/main.tf
resource "aws_lb" "api" {
  count = var.enable_service ? 1 : 0

  name                       = "plat-alb"
  load_balancer_type         = "application"
  subnets                    = local.public
  security_groups            = [aws_security_group.alb.id]
  drop_invalid_header_fields = true
}

resource "aws_lb_target_group" "api" {
  count = var.enable_service ? 1 : 0

  name        = "plat-api-tg"
  port        = var.container_port
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = local.vpc_id

  deregistration_delay = 30

  health_check {
    path                = var.health_check_path
    matcher             = "200-399"
    interval            = 15
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "http" {
  count = var.enable_service ? 1 : 0

  load_balancer_arn = aws_lb.api[0].arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api[0].arn
  }
}
```

`target_type = "ip"` is required for Fargate, because tasks register by address, not by instance id. A short `deregistration_delay` keeps deployments quick.

```hcl
# stacks/52-ecs/main.tf
resource "aws_ecs_service" "api" {
  count = var.enable_service ? 1 : 0

  name                              = "plat-api-svc"
  cluster                           = aws_ecs_cluster.this.id
  task_definition                   = aws_ecs_task_definition.api.arn
  desired_count                     = var.desired_count
  launch_type                       = "FARGATE"
  health_check_grace_period_seconds = 30

  network_configuration {
    subnets          = local.private
    security_groups  = [aws_security_group.api.id, local.app_sg_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api[0].arn
    container_name   = "api"
    container_port   = var.container_port
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # The pipeline (Post 12) registers new task definition revisions, and an autoscaler may change the count.
  # Terraform creates the service and then stops fighting over those two fields.
  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }

  depends_on = [aws_lb_listener.http]
}
```

Two lines carry the design:

* The **circuit breaker** with rollback stops a deployment whose tasks keep failing and returns to the last working revision.
* `ignore_changes = [task_definition, desired_count]`: **Terraform creates the service, and the pipeline owns it from then on.** When CodePipeline deploys a new revision (Post 12), Terraform must not "correct" it back to the revision in code. The same applies to the count if an autoscaler adjusts it.

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "The task role pulls the image." | The **execution role** does. The task role is for your code. |
| "A private subnet can pull from ECR automatically." | It needs a path: a NAT gateway, or the ECR endpoints (`ecr.api`, `ecr.dkr`) plus the S3 gateway endpoint. The default nginx image also needs a NAT because it lives on `public.ecr.aws`. |
| "The service shows Terraform's task definition forever." | Only until the first deployment. After that the service runs whatever the pipeline registered; `ignore_changes` is what permits it. |
| "`terraform destroy` is blocked while tasks are running." | The service is deleted and drained for you. It can take a few minutes. |
| "Target type `instance` works for Fargate." | Fargate tasks have no instance. Use `ip`. |
| "A health check of `/` is fine for any app." | The check decides whether a task lives. A path that returns 404 gets tasks killed in a loop. Use a real health route and a matching `matcher`. |
| "Security group rules in the ALB are enough." | Both sides need a rule: the ALB's egress to the tasks and the tasks' ingress from the ALB. |
| "I can ignore container logs." | Without the `awslogs` block you get a task that dies with no explanation. The log group is the first place to look. |
| "`desired_count = 2` in code scales the service." | Only on creation. With `ignore_changes` later edits are ignored on purpose; scale with the CLI or an autoscaler. |
| "A load balancer is free when idle." | It bills per hour and per capacity unit as soon as it exists. |
| "The image tag `latest` always runs the newest image." | A running task keeps the image it started with. A new deployment is what pulls again. |
| "Everything in `container_definitions` is validated at plan time." | It is a string to Terraform. Typos in field names are found by ECS at apply or at task start. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| `vpc_id`, public and private subnet ids | `20-network` |
| `kms_key_arn`, `app_sg_id` | `30-security` |
| bucket, table, `rds_secret_arn`, `rds_endpoint` | `40-data` |

| You create here | Used by |
|---|---|
| ECR repo `plat-api` | CodeBuild pushes to it, the task pulls from it (Post 12) |
| Cluster and service names | The pipeline's deploy action, dashboard and alarms (Post 14) |
| `alb_arn_suffix`, `target_group_arn_suffix` | CloudWatch alarm dimensions (Post 14) |
| Task role | The API's permissions on S3, DynamoDB and the secret |

### Console clicks you no longer make

| In the AWS series you... | Here it is |
|---|---|
| **ECR, Create repository**, scan setting, lifecycle rule | `aws_ecr_repository` + `aws_ecr_lifecycle_policy` |
| **ECS, Create cluster**, Container Insights | `aws_ecs_cluster.this` |
| **Task definitions, Create**: size, roles, container, port, log settings | `aws_ecs_task_definition.api` |
| **EC2, Load Balancers, Create**: listener, target group, health check | `aws_lb.*`, `aws_lb_target_group.*`, `aws_lb_listener.*` |
| **ECS, Create service**: networking, load balancer, circuit breaker | `aws_ecs_service.api` |
| Three **Create role** dialogs and two security groups | `aws_iam_*` and `aws_security_group` resources |

---

## Lab: Bring the API Up 🛠️

### 1. Give the private subnets a way out

The default image comes from the internet, so switch the NAT on:

```bash
export AWS_PROFILE=plat-admin AWS_REGION=us-east-1
scripts/tf.sh 20-network plan -var enable_nat=true
```

```
Plan: 3 to add, 0 to change, 0 to destroy.
```

An address, the gateway, and the route. Apply it.

### 2. Plan the stack with the service off

```bash
scripts/tf.sh 52-ecs plan
```

```
Plan: 15 to add, 0 to change, 0 to destroy.
```

Repository and lifecycle policy (2), cluster and log group (2), two roles with an attachment and an inline policy (4), two groups with four rules (6), the task definition (1). Apply, then plan again with the service:

```bash
scripts/tf.sh 52-ecs apply
scripts/tf.sh 52-ecs plan -var enable_service=true
```

```
Plan: 4 to add, 0 to change, 0 to destroy.
```

The balancer, target group, listener and service.

### 3. Apply and watch the rollout

```bash
scripts/tf.sh 52-ecs apply -var enable_service=true
aws ecs describe-services --cluster plat-cluster --services plat-api-svc \
  --query 'services[0].[status,runningCount,desiredCount,deployments[0].rolloutState]' --output text
```

Take about three minutes. Then:

```
ACTIVE  1  1  COMPLETED
```

### 4. Call it

```bash
ALB=$(terraform -chdir=stacks/52-ecs output -raw alb_dns_name)
curl -s -o /dev/null -w '%{http_code}\n' http://$ALB/
aws elbv2 describe-target-health \
  --target-group-arn $(aws elbv2 describe-target-groups --names plat-api-tg --query 'TargetGroups[0].TargetGroupArn' --output text) \
  --query 'TargetHealthDescriptions[].TargetHealth.State' --output text
```

```
200
healthy
```

If you get a 503 for the first minute, the target is still registering. You are looking at the nginx welcome page, served from a task that has no public address.

### 5. Prove the fence

From the instance in Post 08, or any machine, the task's address is unreachable. From your computer, only the load balancer answers:

```bash
aws ecs list-tasks --cluster plat-cluster --service-name plat-api-svc --query 'taskArns[0]' --output text \
  | xargs -I{} aws ecs describe-tasks --cluster plat-cluster --tasks {} \
      --query 'tasks[0].attachments[0].details[?name==`privateIPv4Address`].value' --output text
```

That prints a `10.20.x.x` address. There is no public one to try.

### 6. Break it: a bad health check

```bash
scripts/tf.sh 52-ecs apply -var enable_service=true -var health_check_path=/does-not-exist
sleep 120
aws elbv2 describe-target-health --target-group-arn $(aws elbv2 describe-target-groups --names plat-api-tg --query 'TargetGroups[0].TargetGroupArn' --output text) \
  --query 'TargetHealthDescriptions[].[TargetHealth.State,TargetHealth.Reason]' --output text
aws ecs describe-services --cluster plat-cluster --services plat-api-svc --query 'services[0].events[:3].message' --output text
```

```
unhealthy  Target.ResponseCodeMismatch
... (service plat-api-svc) has begun draining connections on 1 tasks.
```

nginx answers 404 to that path, the matcher wants 200 to 399, and ECS replaces the task over and over. Restore the default path and the service settles. The point is that **a health check is an assertion about your application**, and a wrong one is an outage.

### 7. Show that the pipeline owns the revision

Register a new revision by hand, as the pipeline will:

```bash
aws ecs register-task-definition --cli-input-json "$(aws ecs describe-task-definition --task-definition plat-api --query taskDefinition | jq 'del(.taskDefinitionArn,.revision,.status,.requiresAttributes,.compatibilities,.registeredAt,.registeredBy)')" >/dev/null
aws ecs update-service --cluster plat-cluster --service plat-api-svc --task-definition plat-api >/dev/null
scripts/tf.sh 52-ecs plan -var enable_service=true
```

```
No changes. Your infrastructure matches the configuration.
```

The service now runs revision 2; Terraform has nothing to say about it. Remove `ignore_changes` from the code and the same plan would try to put revision 1 back.

### 8. Resources you now have 📦

| Resource | Name | Notes |
|---|---|---|
| ECR repository | `plat-api` | KMS, scan on push, keep 10 |
| ECS cluster | `plat-cluster` | Container Insights on |
| Roles | `plat-ecs-exec-role`, `plat-ecs-task-role` | |
| Security groups | `plat-alb-sg`, `plat-api-sg` | |
| Task definition | `plat-api` | Fargate, 256 CPU, 512 MB |
| ALB, target group, service | `plat-alb`, `plat-api-tg`, `plat-api-svc` | **Hourly cost.** Only with `enable_service` |

### Cleanup 🧹

```bash
scripts/tf.sh 52-ecs apply            # service off: removes the ALB, target group, listener and service
```

Keep the rest. The NAT stays on while you continue; `make pause` turns it off when you stop for the day.

---

## Quick Quiz 🧠

**Q1.** A task stops at start-up with `CannotPullContainerError`. Which role and which network path do you check?

<details>
<summary>Show answer</summary>

The **execution role** (it pulls images) and the **path from the private subnet** to the registry: a NAT gateway for `public.ecr.aws`, or the ECR interface endpoints plus the S3 gateway endpoint for a private ECR repository.

</details>

**Q2.** Why does the task role's DynamoDB statement list `${table_arn}/index/*`?

<details>
<summary>Show answer</summary>

A `Query` against a global secondary index is authorised against the **index's** ARN, not the table's. Without the second resource the API could read the table but not use the status index.

</details>

**Q3.** Why does the service ignore changes to `task_definition`?

<details>
<summary>Show answer</summary>

The delivery pipeline deploys new revisions. If Terraform managed the field, every plan would try to revert the service to the revision in code, which would undo each deployment.

</details>

**Q4.** What does the circuit breaker with rollback do?

<details>
<summary>Show answer</summary>

If tasks of a new deployment repeatedly fail to become healthy, ECS stops the rollout and **returns the service to the last deployment that worked**, instead of retrying indefinitely.

</details>

**Q5.** Why is there no inbound rule on the tasks for `0.0.0.0/0`?

<details>
<summary>Show answer</summary>

`plat-api-sg` allows the container port only from `plat-alb-sg`, and tasks have no public address. The load balancer is the single entry point, so every request passes through one place that you control and can monitor.

</details>

---

## What's Next? 🚀

Same application, different scheduler. Next we run the API on Kubernetes with EKS and replace the instance-profile style of permission with Pod Identity.

👉 [Post 10: Kubernetes on EKS: Cluster, Nodes, Access Entries and Pod Identity](content/aws-terraform/10-eks-as-code.md)

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
