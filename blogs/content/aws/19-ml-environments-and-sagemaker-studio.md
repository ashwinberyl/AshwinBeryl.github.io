---
title: "ML Environments and SageMaker Studio"
date: 2026-11-08
tags: [aws, sagemaker, studio, conda, python, ecr, processing-jobs, containers, intermediate]
description: Post 19 of the AWS series. Reproducible Python environments, how a SageMaker domain, spaces and execution roles fit together, why ML containers follow a path convention, and a lab where Dave cleans events.csv with a processing job that runs in a private container.
---

# Where the Data Scientist Works 🧪

Dave's problem is rarely "how do I fit a model". It's "why does this notebook only work on Tuesday", "which pandas version produced this file" and "who has permission to read the raw data". This post builds the answers:

- A **reproducible Python environment** (so results can be repeated).
- A **SageMaker domain** (so Dave has a managed place to work, tied to his Identity Center login).
- A **container image in ECR** (so the same code runs identically anywhere).
- A **Processing job** (so cleaning happens on managed compute, not on a notebook instance).

![Studio, ECR, S3 and a processing job](content/aws/images/19-sagemaker-studio.svg)

---

## Python Environments, Briefly but Properly 🐍

| Tool | Does | Use it for |
|---|---|---|
| **`venv` + `pip`** | Isolated site-packages per project | Pure-Python projects |
| **Conda** (or mamba/micromamba) | Manages Python itself **and** compiled libraries | Data science stacks with native dependencies |
| **`requirements.txt`** | A pip list. Pin versions for repeatability | Containers and services |
| **`environment.yml`** | A conda list with channels | Notebook environments |
| **Kernel** | A named interpreter a notebook runs on | Making an environment selectable in Studio |

Repeatability rule: **pin what you depend on** (`pandas==2.2.*`), and keep the file in Git. "Works on my machine" is an unpinned environment.

## Container Registries 🗃️

| Registry | Notes |
|---|---|
| **ECR private** | Per account and region. Pulls are authorised by IAM. SageMaker pulls from here with the **execution role** |
| **ECR Public** | Anonymous pulls, no rate-limit surprises for AWS-hosted bases (`public.ecr.aws/...`) |
| **Docker Hub** | Anonymous pulls are **rate limited**. Shared NAT IPs hit the limit quickly |
| **Pull-through cache** | An ECR feature that caches upstream images into your private registry |

A SageMaker job runs your image with a **fixed folder convention**:

| Path in the container | Meaning |
|---|---|
| `/opt/ml/processing/input`, `/opt/ml/processing/<name>` | Processing job inputs and outputs, mapped to S3 |
| `/opt/ml/input/data/<channel>` | Training data channels (Post 20) |
| `/opt/ml/model` | Where training must write the model; uploaded to S3 at the end |
| `/opt/ml/output/failure` | Write a failure message here |

---

## SageMaker Studio: the Vocabulary 🧭

| Term | Meaning |
|---|---|
| **Domain** | The top-level environment: auth method, network, a shared EFS volume for home directories, default settings |
| **User profile** | One person's identity in the domain (linked to an Identity Center user or an IAM identity) |
| **Space** | A workspace with its own storage and compute. A **JupyterLab space** runs one JupyterLab app on an instance you pick |
| **Execution role** | The IAM role that code in the space, and jobs it launches, run as |
| **Network mode** | **Public internet** (Studio's own path to the internet) or **VPC only** (everything through your VPC, NAT and endpoints) |
| **Instance type** | `ml.<family>.<size>`. Studio, processing, training and hosting each choose their own |

Two identities matter and are often confused: the **person** (Dave, via Identity Center) and the **role** (what his code can do). Dave's `AWSReservedSSO_DataScientist` permissions (view-only) say nothing about what his *notebook* may do. That comes from the execution role.

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "Creating a domain costs a lot." | The domain itself is free. You pay for **running apps** (instances), the domain's **EFS storage**, and the jobs you launch. |
| "Closing the browser stops the instance." | The JupyterLab app keeps **running and billing** until you stop it or an **idle shutdown** setting fires. |
| "The notebook uses my user's permissions." | It uses the **execution role** of the space or domain. Dave's SSO role is not involved once he's inside. |
| "A processing job runs on the notebook's instance." | It starts **separate, managed instances** (billed per second), runs your container, and terminates them. The notebook only calls the API. |
| "VPC-only mode just works." | The domain, spaces and jobs then use **your** network. You need NAT or endpoints for S3, ECR, CloudWatch Logs, and the SageMaker APIs, and a security group that allows traffic **within itself**. |
| "`ml.m5.large` is always available." | New accounts have **service quotas** per instance type per job type. A quota of 0 gives `ResourceLimitExceeded`. Request an increase early. |
| "My script can write anywhere." | Only paths mapped as **outputs** are uploaded to S3. Anything else vanishes with the instance. |
| "The job role needs the same permissions as me." | It needs exactly what the **container** does: read the input prefix, write the output prefix, KMS for the encrypted bucket, ECR pull, logs. Plus `iam:PassRole` for whoever **creates** the job. |
| "`Quick setup` is the production way." | It uses defaults (default VPC, broad role). Fine to learn, not a template for governed environments. |
| "Conda environments created in a terminal survive restarts." | Environments in the **home directory** (on the domain's EFS) persist. Ones created elsewhere on the instance's ephemeral disk don't. |
| "Studio and Studio Classic are the same." | AWS has a newer Studio experience (JupyterLab and other spaces) and an older Classic one. Screens and paths differ. This lab uses the newer one. |
| "`latest` base images are fine for ML." | Library versions change results. Pin the image digest or tag **and** the library versions. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| Identity Center users `dave`, `jim`, permission sets | Post 03 |
| `plat-vpc`, private subnets, NAT, S3 gateway endpoint | Post 04 |
| KMS key `alias/plat-data` and SSE-KMS bucket | Posts 05, 06 |
| `events.csv` in `raw/` (5,050 data rows including 50 replays) | Post 06 |
| ECR, `docker build` and `docker push` | Posts 09, 11 |
| Service Catalog product for project buckets (optional) | Post 17 |

| You create here | Used by |
|---|---|
| Role **`plat-sm-role`**, domain **`plat-studio`** | All SageMaker work |
| ECR repository **`plat/ml`**, image `1.0` | Processing now, training and the endpoint in Post 20 |
| **`processed/train/`** and **`processed/validation/`** | Training in Post 20 |

---

## Lab: Build the Environment and Clean the Data 🛠️

Jim does steps 1 to 4, Dave does steps 5 to 8. Replace `123456789012` with your account ID. Docker must run on your machine (Post 09).

### 1. Create the execution role

**IAM, Roles, Create role**: trusted entity **AWS service, SageMaker**. Skip managed policies on the wizard page. Name **`plat-sm-role`**. Then add the AWS managed policy **`AmazonSageMakerFullAccess`** (it gives Studio the SageMaker-internal permissions it needs) and this inline policy, **`plat-sm-data-access`**, which defines the *data* boundary:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadRaw",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::plat-data-123456789012-us-east-1",
        "arn:aws:s3:::plat-data-123456789012-us-east-1/*"
      ]
    },
    {
      "Sid": "WriteProcessedAndModels",
      "Effect": "Allow",
      "Action": ["s3:PutObject"],
      "Resource": [
        "arn:aws:s3:::plat-data-123456789012-us-east-1/processed/*",
        "arn:aws:s3:::plat-data-123456789012-us-east-1/models/*"
      ]
    },
    {
      "Sid": "KmsViaS3",
      "Effect": "Allow",
      "Action": ["kms:Decrypt", "kms:GenerateDataKey"],
      "Resource": "arn:aws:kms:us-east-1:123456789012:key/<your-key-id>",
      "Condition": { "StringEquals": { "kms:ViaService": "s3.us-east-1.amazonaws.com" } }
    },
    {
      "Sid": "PullPlatImages",
      "Effect": "Allow",
      "Action": ["ecr:GetAuthorizationToken"],
      "Resource": "*"
    },
    {
      "Sid": "PullPlatMl",
      "Effect": "Allow",
      "Action": ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"],
      "Resource": "arn:aws:ecr:us-east-1:123456789012:repository/plat/ml"
    }
  ]
}
```

> **Note:** `AmazonSageMakerFullAccess` is broad inside SageMaker, and it includes access to S3 buckets whose names contain `sagemaker`. The boundary that matters for our data is the inline policy plus the fact that this bucket's name does not match that pattern. In a stricter environment you would replace the managed policy with a reviewed minimal set.

### 2. Build and push the container

In your `plat-platform` clone, create a folder `ml/` with three files:

**`ml/requirements.txt`**

```text
pandas>=2.2,<3
scikit-learn>=1.5,<2
joblib>=1.4,<2
```

**`ml/preprocess.py`**

```python
import os

import pandas as pd

INPUT = "/opt/ml/processing/input/events.csv"
OUT = "/opt/ml/processing"


def main():
    df = pd.read_csv(INPUT)
    rows_in = len(df)

    # Replayed events are exact copies, so they share an event_id.
    df = df.drop_duplicates(subset="event_id")
    unique = len(df)

    missing = int(df["minutes_7d"].isna().sum())
    df["minutes_7d"] = df["minutes_7d"].fillna(df["minutes_7d"].median())
    df["plan_pro"] = (df["plan"] == "pro").astype(int)

    # Label first, no header: the layout the training step expects.
    # user_id and event_id are identifiers, not features, so they are dropped.
    cols = ["churned", "sessions_7d", "minutes_7d", "tickets_30d", "plan_pro"]
    data = df[cols].sample(frac=1.0, random_state=42).reset_index(drop=True)

    cut = int(len(data) * 0.8)
    train, validation = data.iloc[:cut], data.iloc[cut:]

    for name, part in (("train", train), ("validation", validation)):
        os.makedirs(f"{OUT}/{name}", exist_ok=True)
        part.to_csv(f"{OUT}/{name}/{name}.csv", header=False, index=False)

    print(
        f"rows_in={rows_in} unique={unique} missing_minutes={missing} "
        f"train={len(train)} validation={len(validation)} "
        f"churn_rate={data['churned'].mean():.3f}"
    )


if __name__ == "__main__":
    main()
```

**`ml/Dockerfile`**

```dockerfile
FROM public.ecr.aws/docker/library/python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /opt/program

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY preprocess.py .
```

Create the repository and push:

```bash
aws sso login --profile plat-admin
ACCT=$(aws sts get-caller-identity --profile plat-admin --query Account --output text)
REG=$ACCT.dkr.ecr.us-east-1.amazonaws.com

aws ecr create-repository --repository-name plat/ml --profile plat-admin --region us-east-1 \
  --image-scanning-configuration scanOnPush=true --tags Key=project,Value=plat

aws ecr get-login-password --profile plat-admin --region us-east-1 \
  | docker login --username AWS --password-stdin $REG

cd ml
docker build --platform linux/amd64 -t $REG/plat/ml:1.0 .
docker push $REG/plat/ml:1.0
```

Test the script locally before paying for a cloud run. Put a copy of `events.csv` in a scratch folder:

```bash
mkdir -p /tmp/mltest/input /tmp/mltest/out
aws s3 cp s3://plat-data-$ACCT-us-east-1/raw/events.csv /tmp/mltest/input/ --profile plat-admin
docker run --rm \
  -v /tmp/mltest/input:/opt/ml/processing/input:ro \
  -v /tmp/mltest/out:/opt/ml/processing \
  $REG/plat/ml:1.0 python /opt/program/preprocess.py
```

```text
rows_in=5050 unique=5000 missing_minutes=156 train=4000 validation=1000 churn_rate=0.476
```

(The generator in Post 06 is seeded, so your numbers should match or be very close.) The container reads the same path SageMaker will use. This habit, **run the exact image locally with mounted folders first**, saves hours.

Commit `ml/` to Git on a branch and merge by pull request. The pipeline from Post 18 will run, and since `app/` didn't change it will rebuild an identical API image: harmless, and a good reminder that path filters on the trigger would avoid it.

### 3. Prepare the network pieces

**EC2, Security Groups, Create**: name **`plat-studio-sg`**, VPC `plat-vpc`. Inbound: **All traffic** from **itself** (add after creation: edit the rule, source = `plat-studio-sg`). Outbound: default allow all. Tag `project = plat`.

Studio and jobs in your VPC will reach S3 through the **gateway endpoint** and everything else (ECR, SageMaker APIs, logs, conda channels) through the **NAT gateway**. Make sure the NAT gateway is running.

### 4. Create the domain

**SageMaker AI, Admin configurations, Domains, Create domain, Set up for organizations**:

| Step | Setting |
|---|---|
| Domain details | Name **`plat-studio`**; authentication **AWS IAM Identity Center** |
| Roles | Default execution role: **`plat-sm-role`** (choose existing) |
| Network and storage | VPC `plat-vpc`; subnets **`plat-private-a`**, **`plat-private-b`**; security group **`plat-studio-sg`**; network access **VPC only** |
| Applications | Defaults; leave Canvas and others off |

Create it. After it reaches **Ready** (a few minutes), open the domain, **Users**: **Assign users and groups**, assign `dave` and `jim`. If IAM Identity Center authentication isn't offered (the instance must be in this region and organization-level), choose **IAM** authentication, create user profiles, and have users enter Studio from the console instead.

### 5. Dave opens Studio

As **dave**, sign in to the Identity Center portal. A **SageMaker Studio** application tile is available. Open it (the first launch takes a minute), then **JupyterLab, Create JupyterLab space**: name `churn-work`, instance **`ml.t3.medium`**, storage 5 GB. **Run space**, **Open JupyterLab**. In the space's settings enable **idle shutdown** (for example 60 minutes) if offered.

### 6. A reproducible environment

Open a **Terminal** in JupyterLab. Create the environment file:

```bash
cat > environment.yml <<'EOF'
name: plat-ml
channels:
  - conda-forge
dependencies:
  - python=3.11
  - pandas=2.2
  - scikit-learn=1.5
  - ipykernel
  - boto3
EOF

conda env create -f environment.yml
conda activate plat-ml
python -m ipykernel install --user --name plat-ml --display-name "Python (plat-ml)"
python -c "import pandas, sklearn; print(pandas.__version__, sklearn.__version__)"
```

```text
2.2.3 1.5.2
```

(Your exact patch versions may differ.) The environment solve needs the NAT gateway to reach the conda channel. In the notebook launcher you can now pick the kernel **Python (plat-ml)**. Because it was created under the home directory, it survives restarts of the space. Commit `environment.yml` to Git.

### 7. Run the processing job from a notebook

Create a notebook on the **Python (plat-ml)** kernel and run this in one cell. It finds the account itself and uses your private subnets:

```python
import time
import boto3

REGION = "us-east-1"
sm = boto3.client("sagemaker", region_name=REGION)
ec2 = boto3.client("ec2", region_name=REGION)
acct = boto3.client("sts").get_caller_identity()["Account"]

bucket = f"plat-data-{acct}-us-east-1"
image = f"{acct}.dkr.ecr.{REGION}.amazonaws.com/plat/ml:1.0"
role = f"arn:aws:iam::{acct}:role/plat-sm-role"

subnets = [s["SubnetId"] for s in ec2.describe_subnets(
    Filters=[{"Name": "tag:Name", "Values": ["plat-private-a", "plat-private-b"]}])["Subnets"]]
sgs = [g["GroupId"] for g in ec2.describe_security_groups(
    Filters=[{"Name": "group-name", "Values": ["plat-studio-sg"]}])["SecurityGroups"]]

job = "plat-preprocess-" + time.strftime("%Y%m%d-%H%M%S")
sm.create_processing_job(
    ProcessingJobName=job,
    RoleArn=role,
    AppSpecification={
        "ImageUri": image,
        "ContainerEntrypoint": ["python", "/opt/program/preprocess.py"],
    },
    ProcessingResources={"ClusterConfig": {
        "InstanceCount": 1, "InstanceType": "ml.m5.large", "VolumeSizeInGB": 10}},
    ProcessingInputs=[{
        "InputName": "events",
        "S3Input": {
            "S3Uri": f"s3://{bucket}/raw/events.csv",
            "LocalPath": "/opt/ml/processing/input",
            "S3DataType": "S3Prefix",
            "S3InputMode": "File",
        }}],
    ProcessingOutputConfig={"Outputs": [
        {"OutputName": "train", "S3Output": {
            "S3Uri": f"s3://{bucket}/processed/train/",
            "LocalPath": "/opt/ml/processing/train", "S3UploadMode": "EndOfJob"}},
        {"OutputName": "validation", "S3Output": {
            "S3Uri": f"s3://{bucket}/processed/validation/",
            "LocalPath": "/opt/ml/processing/validation", "S3UploadMode": "EndOfJob"}},
    ]},
    NetworkConfig={"VpcConfig": {"SecurityGroupIds": sgs, "Subnets": subnets}},
    StoppingCondition={"MaxRuntimeInSeconds": 900},
    Tags=[{"Key": "project", "Value": "plat"}],
)

while True:
    d = sm.describe_processing_job(ProcessingJobName=job)
    status = d["ProcessingJobStatus"]
    print(time.strftime("%H:%M:%S"), status)
    if status in ("Completed", "Failed", "Stopped"):
        print(d.get("FailureReason", ""))
        break
    time.sleep(20)
```

```text
10:41:05 InProgress
...
10:44:45 Completed
```

It takes about three to five minutes, most of it starting the instance and pulling the image. Then read the log line from your script:

```python
logs = boto3.client("logs", region_name=REGION)
streams = logs.describe_log_streams(
    logGroupName="/aws/sagemaker/ProcessingJobs", logStreamNamePrefix=job)["logStreams"]
for e in logs.get_log_events(logGroupName="/aws/sagemaker/ProcessingJobs",
                             logStreamName=streams[0]["logStreamName"])["events"]:
    print(e["message"])
```

```text
rows_in=5050 unique=5000 missing_minutes=156 train=4000 validation=1000 churn_rate=0.476
```

### 8. Check the outputs and what failed first

```bash
aws s3 ls s3://plat-data-123456789012-us-east-1/processed/ --recursive
```

```text
... processed/train/train.csv
... processed/validation/validation.csv
```

Notice that Dave's own `ViewOnlyAccess` permissions never touched these files. **The role wrote them.**

If the job failed, read `FailureReason`. The usual causes and their signatures:

| Message mentions | Look at |
|---|---|
| `ClientError: ... ResourceLimitExceeded` | Service quota for `ml.m5.large` for processing jobs |
| `AccessDenied` on `kms` or `s3` | `plat-sm-data-access`, including the key condition |
| `CannotPullContainerError` / image not found | Image tag, region, ECR pull permissions on `plat-sm-role` |
| Hangs at start, then timeout | No path to ECR/S3: NAT gateway stopped, or missing endpoint |
| `Failed` with exit code 1 | Your script: open the CloudWatch log |

### 9. Resources you now have 📦

| Resource | Name |
|---|---|
| Role | `plat-sm-role` |
| ECR repository | `plat/ml` (tag `1.0`) |
| Security group | `plat-studio-sg` |
| Domain | `plat-studio` (Identity Center, VPC only), users `dave` and `jim` |
| JupyterLab space | `churn-work` (`ml.t3.medium`), kernel `Python (plat-ml)` |
| S3 objects | `processed/train/train.csv`, `processed/validation/validation.csv` |

### Cleanup 🧹

**Stop the JupyterLab space** (Studio, Spaces, **Stop**). Jobs already terminated themselves. Keep the domain: its cost when idle is the EFS home volume. If you pause the series for a long time, delete the apps, spaces and then the domain (deleting the domain can also remove its EFS).

---

## Quick Quiz 🧠

**Q1.** Dave's SSO role has only `ViewOnlyAccess`. Why can his notebook still create a processing job and write to S3?

<details>
<summary>Show answer</summary>

The notebook and jobs run as the **domain's execution role** (`plat-sm-role`), not as his SSO role. That role carries the data and SageMaker permissions. The risk to manage is therefore *what the execution role allows*.

</details>

**Q2.** A job ends with `Completed`, but no files appear in `processed/`. What is the most likely cause?

<details>
<summary>Show answer</summary>

The script wrote to a path that is **not mapped as a processing output** (or used a different `LocalPath`). Only mapped output directories are uploaded.

</details>

**Q3.** The job sits in `InProgress` and then fails with a timeout when starting. The domain is VPC only. What do you check?

<details>
<summary>Show answer</summary>

The **network path** from the job's subnets to ECR, S3, CloudWatch Logs and the SageMaker APIs: the NAT gateway state, route tables, the S3 gateway endpoint, and the security group (self-reference and outbound).

</details>

**Q4.** Dave closes the browser tab on Friday afternoon. What happens to the cost?

<details>
<summary>Show answer</summary>

The JupyterLab app **keeps running and billing** until it is stopped or idle shutdown triggers. Always enable idle shutdown.

</details>

**Q5.** Why run the container locally with mounted folders before creating the job?

<details>
<summary>Show answer</summary>

The container sees the same **paths** SageMaker mounts, so most bugs (bad paths, missing libraries, wrong file layout) show in seconds, free, instead of minutes into a billed job.

</details>

---

## What's Next? 🚀

The data is cleaned and split. Now we teach a model the pattern, keep the result, and serve it as an HTTPS endpoint the API can call, then take the endpoint down before it quietly bills for the weekend.

👉 **[Post 20: SageMaker Training and Endpoints](content/aws/20-sagemaker-training-and-endpoints.md)**: a training job in the `plat/ml` image, a model artifact in S3, a real-time endpoint, and an API call from Lambda or ECS.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
