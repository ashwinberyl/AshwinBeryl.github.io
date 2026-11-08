---
title: "SageMaker Training and Endpoints"
date: 2026-11-08
tags: [aws, sagemaker, training, endpoints, byoc, inference, model-artifact, intermediate]
description: Post 20 of the AWS series. The container contract SageMaker expects for training and hosting, the difference between a model, an endpoint configuration and an endpoint, and a lab that trains a churn model, serves it behind an HTTPS endpoint and calls it from plat-api through the pipeline.
---

# From Cleaned Data to a Prediction Over HTTPS 🎯

The data is split (`processed/train/` and `processed/validation/`). This post finishes the machine-learning path:

1. A **training job** reads those files, fits a model, and leaves a **model artifact** in S3.
2. A **real-time endpoint** loads that artifact and answers `POST` requests.
3. The **API** from Posts 11 and 18 calls the endpoint and returns a churn probability.

We use our own container image, **`plat/ml`**, instead of a prebuilt framework. That keeps the contract visible: you can see exactly what SageMaker needs from a container, and exactly what it does for you.

![Training, model artifact, endpoint, and the API that calls it](content/aws/images/20-sagemaker-endpoint.svg)

---

## The Container Contract 📜

SageMaker starts your image with a single argument, and your code follows conventions:

| Phase | SageMaker runs | Your code must |
|---|---|---|
| **Processing** | Your chosen `ContainerEntrypoint` | Read `/opt/ml/processing/...` (Post 19) |
| **Training** | `docker run <image> train` | Read `/opt/ml/input/data/<channel>/`, hyperparameters from `/opt/ml/input/config/hyperparameters.json`, write the model to **`/opt/ml/model`** |
| **Hosting** | `docker run <image> serve` | Listen on **port 8080**; answer `GET /ping` with 200 and `POST /invocations` |

At the end of training, SageMaker compresses `/opt/ml/model` into **`model.tar.gz`** and uploads it to S3. When hosting, it downloads and unpacks the archive back to `/opt/ml/model` in the serving container.

### Three objects, not one

| Object | What it is | Created by |
|---|---|---|
| **Model** | A *definition*: container image + model artifact location + role | `create_model` |
| **Endpoint configuration** | Instance type, count and variants (which model gets what traffic) | `create_endpoint_config` |
| **Endpoint** | The running, billed fleet with a stable name and HTTPS address | `create_endpoint` |

You delete them separately, and **only deleting the endpoint stops the charges**.

### Inference options

| Option | Use when |
|---|---|
| **Real-time endpoint** | Low-latency, steady traffic. Billed per instance-hour, **always on** |
| **Serverless inference** | Sporadic traffic, tolerating cold starts. Pay per use |
| **Asynchronous inference** | Large payloads or long processing, results delivered to S3 |
| **Batch transform** | Score a whole dataset once, no endpoint |

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "An endpoint scales to zero when idle." | A real-time endpoint runs on instances **continuously** and bills per hour even with zero requests. Delete it, or use serverless inference. |
| "Deleting the endpoint configuration deletes the endpoint." | It doesn't. Delete the **endpoint**. Config and model are just definitions (free). |
| "Accuracy of 0.65 is a good score." | Compare with the **baseline**. With the classes split roughly 52/48, always predicting the majority class already scores about 0.52. Look at **AUC** and the baseline together. |
| "Hyperparameters arrive as numbers." | They arrive as **strings** in the JSON file. Cast them yourself. |
| "My metric will show up in CloudWatch automatically." | Only if you define a **metric definition** with a regular expression that matches a line your code prints. |
| "The endpoint is healthy once the container starts." | It is `InService` only after `/ping` returns 200. A model that fails to load keeps `/ping` failing and the endpoint ends `Failed` after a timeout. |
| "I can pass any content type." | Your `serve` code decides what it accepts. We accept `text/csv` and JSON and return `415` for others. |
| "`sagemaker:DescribeEndpoint` lets me call it." | Calling needs **`sagemaker:InvokeEndpoint`**, a separate permission, on the endpoint's ARN. |
| "A VPC-attached endpoint can reach S3 without help." | The model artifact is fetched using your network. You need the **S3 gateway endpoint** or NAT, as in our VPC. |
| "Retraining replaces the model in place." | A new training job writes a **new artifact path**. To use it, create a new model and endpoint config, then **update the endpoint** (SageMaker does a blue/green swap). |
| "Training job names can be reused." | Job names are **unique per account and region**. Add a timestamp. |
| "The feature order doesn't matter." | The model sees columns by **position**. Training, serving and the API must use the same order: sessions, minutes, tickets, plan_pro. |
| "Endpoint quotas are the same as training quotas." | Quotas are **per instance type and per usage type** (endpoint, training, processing). A zero quota blocks only that use. |
| "An endpoint is private because it is in my VPC." | The runtime API is IAM-protected and reached through the regional `runtime.sagemaker` address. The VPC settings control the container's network, not who can call it. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| `processed/train` and `processed/validation` | Post 19 |
| `plat-sm-role`, `plat-studio-sg`, the Studio space | Post 19 |
| ECR `plat/ml`, the local build and run habit | Posts 09, 19 |
| `plat-api`, its task role, task definition and the pipeline | Posts 11, 18 |
| Bucket `models/` prefix, KMS key | Posts 05, 06 |

| You create here | Used by |
|---|---|
| `plat/ml:1.1` with `train` and `serve` | Training now, and every retrain |
| Model artifact `models/<job>/output/model.tar.gz` | The endpoint |
| Endpoint **`plat-churn`** | The API's `/predict` route; alarms on its metrics in Post 21 |

---

## Lab: Train, Serve, Call 🛠️

Jim builds the image (steps 1 to 2), Dave trains and deploys from Studio (3 to 5), and Jim wires the API (6 to 8). Replace `123456789012` with your account ID.

### 1. Add training and serving code

In the `plat-platform` clone, in `ml/`:

**`ml/requirements.txt`** (replace the file)

```text
pandas>=2.2,<3
scikit-learn>=1.5,<2
joblib>=1.4,<2
flask>=3,<4
gunicorn>=22,<24
```

**`ml/train.py`**

```python
import json
import os
import sys
import traceback

import joblib
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

PREFIX = "/opt/ml"
HYPERPARAMETERS = f"{PREFIX}/input/config/hyperparameters.json"
FEATURES = ["sessions_7d", "minutes_7d", "tickets_30d", "plan_pro"]


def load(channel):
    df = pd.read_csv(f"{PREFIX}/input/data/{channel}/{channel}.csv", header=None)
    return df.iloc[:, 1:].to_numpy(), df.iloc[:, 0].to_numpy()  # label is column 0


def main():
    hp = json.load(open(HYPERPARAMETERS)) if os.path.exists(HYPERPARAMETERS) else {}
    c = float(hp.get("C", "1.0"))               # hyperparameters are strings
    max_iter = int(hp.get("max_iter", "200"))

    x_train, y_train = load("train")
    x_val, y_val = load("validation")

    model = make_pipeline(StandardScaler(), LogisticRegression(C=c, max_iter=max_iter))
    model.fit(x_train, y_train)

    proba = model.predict_proba(x_val)[:, 1]
    accuracy = accuracy_score(y_val, proba >= 0.5)
    auc = roc_auc_score(y_val, proba)
    baseline = max(y_val.mean(), 1 - y_val.mean())

    print(f"rows train={len(y_train)} validation={len(y_val)} baseline_accuracy={baseline:.4f}")
    print(f"validation_accuracy={accuracy:.4f}")
    print(f"validation_auc={auc:.4f}")

    os.makedirs(f"{PREFIX}/model", exist_ok=True)
    joblib.dump(model, f"{PREFIX}/model/model.joblib")
    with open(f"{PREFIX}/model/features.json", "w") as f:
        json.dump({"features": FEATURES}, f)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        os.makedirs(f"{PREFIX}/output", exist_ok=True)
        with open(f"{PREFIX}/output/failure", "w") as f:
            f.write(traceback.format_exc())
        traceback.print_exc()
        sys.exit(1)
```

**`ml/serve.py`**

```python
import json
import os

import joblib
import numpy as np
from flask import Flask, Response, request

MODEL_DIR = os.environ.get("MODEL_DIR", "/opt/ml/model")
FEATURE_COUNT = 4  # sessions_7d, minutes_7d, tickets_30d, plan_pro

app = Flask(__name__)
model = joblib.load(os.path.join(MODEL_DIR, "model.joblib"))  # fails loudly if missing


@app.get("/ping")
def ping():
    return Response("\n", status=200)


@app.post("/invocations")
def invocations():
    content_type = request.content_type or ""
    body = request.get_data(as_text=True)
    try:
        if content_type.startswith("text/csv"):
            rows = [[float(v) for v in line.split(",")]
                    for line in body.strip().splitlines() if line.strip()]
        elif content_type.startswith("application/json"):
            rows = json.loads(body)["instances"]
        else:
            return Response(f"unsupported content type: {content_type}", status=415)
        x = np.array(rows, dtype=float)
        if x.ndim != 2 or x.shape[1] != FEATURE_COUNT:
            return Response(f"expected {FEATURE_COUNT} features per row", status=400)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        return Response(f"bad request: {exc}", status=400)

    proba = model.predict_proba(x)[:, 1]
    return Response("\n".join(f"{p:.6f}" for p in proba), mimetype="text/csv")
```

**`ml/train`** (no extension)

```sh
#!/bin/sh
exec python /opt/program/train.py
```

**`ml/serve`** (no extension)

```sh
#!/bin/sh
cd /opt/program
exec gunicorn --bind 0.0.0.0:8080 --workers 1 --timeout 60 serve:app
```

**`ml/Dockerfile`** (replace the file)

```dockerfile
FROM public.ecr.aws/docker/library/python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/opt/program:${PATH}"
WORKDIR /opt/program

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY preprocess.py train.py serve.py train serve ./
RUN chmod +x train serve
```

`chmod` in the image means the scripts work even if your Git client dropped the executable bit (common on Windows). Build and push `1.1`:

```bash
ACCT=$(aws sts get-caller-identity --profile plat-admin --query Account --output text)
REG=$ACCT.dkr.ecr.us-east-1.amazonaws.com
aws ecr get-login-password --profile plat-admin --region us-east-1 \
  | docker login --username AWS --password-stdin $REG

cd ml
docker build --platform linux/amd64 -t $REG/plat/ml:1.1 .
docker push $REG/plat/ml:1.1
```

Only the layers after `COPY requirements.txt` rebuild if you re-run it with a code change: the cache from Post 09 at work.

### 2. Test both commands locally

Use the files your Post 19 local test produced in `/tmp/mltest/out`:

```bash
mkdir -p /tmp/mltrain/data/train /tmp/mltrain/data/validation /tmp/mltrain/config /tmp/mltrain/model
cp /tmp/mltest/out/train/train.csv /tmp/mltrain/data/train/
cp /tmp/mltest/out/validation/validation.csv /tmp/mltrain/data/validation/
echo '{"C":"1.0","max_iter":"200"}' > /tmp/mltrain/config/hyperparameters.json

docker run --rm \
  -v /tmp/mltrain/data:/opt/ml/input/data:ro \
  -v /tmp/mltrain/config:/opt/ml/input/config:ro \
  -v /tmp/mltrain/model:/opt/ml/model \
  $REG/plat/ml:1.1 train
```

```text
rows train=4000 validation=1000 baseline_accuracy=0.5210
validation_accuracy=0.6890
validation_auc=0.7619
```

(The data generator is seeded, so your numbers should match or be very close.) The model clearly beats the 0.52 baseline. Now serve it:

```bash
docker run --rm -d --name mlserve -p 8080:8080 \
  -v /tmp/mltrain/model:/opt/ml/model:ro $REG/plat/ml:1.1 serve
sleep 3
curl -s -o /dev/null -w "ping: %{http_code}\n" localhost:8080/ping
printf '2,20,3,0\n12,150,0,1\n' | curl -s -X POST -H "Content-Type: text/csv" --data-binary @- localhost:8080/invocations
docker stop mlserve
```

```text
ping: 200
0.859755
0.085118
```

Few sessions, low minutes, three tickets, free plan: high churn probability. Many sessions, no tickets, pro plan: low. If that matches intuition, the container is behaving.

### 3. Train in SageMaker (Dave)

Open the JupyterLab space `churn-work` from Post 19 (start it if stopped) and a notebook on the **Python (plat-ml)** kernel:

```python
import time
import boto3

REGION = "us-east-1"
sm = boto3.client("sagemaker", region_name=REGION)
ec2 = boto3.client("ec2", region_name=REGION)
acct = boto3.client("sts").get_caller_identity()["Account"]
bucket = f"plat-data-{acct}-us-east-1"
image = f"{acct}.dkr.ecr.{REGION}.amazonaws.com/plat/ml:1.1"
role = f"arn:aws:iam::{acct}:role/plat-sm-role"

subnets = [s["SubnetId"] for s in ec2.describe_subnets(
    Filters=[{"Name": "tag:Name", "Values": ["plat-private-a", "plat-private-b"]}])["Subnets"]]
sgs = [g["GroupId"] for g in ec2.describe_security_groups(
    Filters=[{"Name": "group-name", "Values": ["plat-studio-sg"]}])["SecurityGroups"]]

def channel(name):
    return {
        "ChannelName": name,
        "ContentType": "text/csv",
        "InputMode": "File",
        "DataSource": {"S3DataSource": {
            "S3DataType": "S3Prefix",
            "S3Uri": f"s3://{bucket}/processed/{name}/",
            "S3DataDistributionType": "FullyReplicated"}},
    }

job = "plat-train-" + time.strftime("%Y%m%d-%H%M%S")
sm.create_training_job(
    TrainingJobName=job,
    RoleArn=role,
    AlgorithmSpecification={
        "TrainingImage": image,
        "TrainingInputMode": "File",
        "MetricDefinitions": [
            {"Name": "validation:auc", "Regex": "validation_auc=([0-9\\.]+)"},
            {"Name": "validation:accuracy", "Regex": "validation_accuracy=([0-9\\.]+)"},
        ],
    },
    HyperParameters={"C": "1.0", "max_iter": "200"},
    InputDataConfig=[channel("train"), channel("validation")],
    OutputDataConfig={"S3OutputPath": f"s3://{bucket}/models/"},
    ResourceConfig={"InstanceType": "ml.m5.large", "InstanceCount": 1, "VolumeSizeInGB": 10},
    VpcConfig={"SecurityGroupIds": sgs, "Subnets": subnets},
    StoppingCondition={"MaxRuntimeInSeconds": 900},
    Tags=[{"Key": "project", "Value": "plat"}],
)

while True:
    d = sm.describe_training_job(TrainingJobName=job)
    print(time.strftime("%H:%M:%S"), d["TrainingJobStatus"], d.get("SecondaryStatus", ""))
    if d["TrainingJobStatus"] in ("Completed", "Failed", "Stopped"):
        break
    time.sleep(20)

print(d.get("FailureReason", ""))
print(d["ModelArtifacts"]["S3ModelArtifacts"])
for m in d.get("FinalMetricDataList", []):
    print(m["MetricName"], m["Value"])
```

```text
10:52:03 InProgress Starting
10:54:23 InProgress Training
10:55:43 Completed Completed

s3://plat-data-123456789012-us-east-1/models/plat-train-20261108-105203/output/model.tar.gz
validation:auc 0.7619
validation:accuracy 0.689
```

The statuses show the stages: *Starting* (instance and image pull, the slow part) then *Training* then *Uploading*. The metrics came from your `print` lines through the regular expressions. Confirm the artifact exists:

```python
!aws s3 ls s3://{bucket}/models/{job}/output/
```

### 4. Deploy the endpoint (Dave)

Run in the same notebook. It creates the three objects in order. **From this point the clock runs on a billed instance.**

```python
model_name = "plat-churn-" + job.removeprefix("plat-train-").replace("-", "")
endpoint_name = "plat-churn"
artifact = d["ModelArtifacts"]["S3ModelArtifacts"]

sm.create_model(
    ModelName=model_name,
    ExecutionRoleArn=role,
    PrimaryContainer={"Image": image, "ModelDataUrl": artifact},
    VpcConfig={"SecurityGroupIds": sgs, "Subnets": subnets},
    Tags=[{"Key": "project", "Value": "plat"}],
)
sm.create_endpoint_config(
    EndpointConfigName=model_name,
    ProductionVariants=[{
        "VariantName": "AllTraffic",
        "ModelName": model_name,
        "InstanceType": "ml.m5.large",
        "InitialInstanceCount": 1,
        "InitialVariantWeight": 1.0,
    }],
    Tags=[{"Key": "project", "Value": "plat"}],
)
sm.create_endpoint(
    EndpointName=endpoint_name,
    EndpointConfigName=model_name,
    Tags=[{"Key": "project", "Value": "plat"}],
)

while True:
    e = sm.describe_endpoint(EndpointName=endpoint_name)
    print(time.strftime("%H:%M:%S"), e["EndpointStatus"])
    if e["EndpointStatus"] in ("InService", "Failed"):
        print(e.get("FailureReason", ""))
        break
    time.sleep(30)
```

```text
11:01:10 Creating
...
11:07:40 InService
```

It takes about five to ten minutes. SageMaker started an instance, pulled `plat/ml:1.1`, downloaded and unpacked `model.tar.gz` into `/opt/ml/model`, ran `serve`, and waited for `/ping`. If it ends `Failed`, read the log group `/aws/sagemaker/Endpoints/plat-churn` in CloudWatch: the usual cause is the model file not loading, or no path to S3/ECR.

### 5. Call it

In the notebook:

```python
rt = boto3.client("sagemaker-runtime", region_name=REGION)
resp = rt.invoke_endpoint(
    EndpointName="plat-churn",
    ContentType="text/csv",
    Body="2,20,3,0\n12,150,0,1\n",
)
print(resp["Body"].read().decode())
```

```text
0.859755
0.085118
```

Look at **CloudWatch, Metrics, SageMaker, Endpoint metrics**: `Invocations` and `ModelLatency` for `plat-churn`.

### 6. Let the API call the endpoint (Jim)

**IAM**: add this statement to the inline policy `plat-api-access` on **`plat-ecs-task-role`**:

```json
{
  "Sid": "CallChurnModel",
  "Effect": "Allow",
  "Action": "sagemaker:InvokeEndpoint",
  "Resource": "arn:aws:sagemaker:us-east-1:123456789012:endpoint/plat-churn"
}
```

**ECS**: open task definition `plat-api`, **Create new revision**, add the environment variable **`ENDPOINT_NAME` = `plat-churn`** to the `api` container, create it, and **update the service** to the new revision. The pipeline's deploy action only swaps the image, so this variable is carried forward.

### 7. Add the route and let the pipeline ship it

In `app/app.py`, add the import at the top with the other imports:

```python
from urllib.parse import parse_qs, urlparse
```

After the line `DB_SECRET_ARN = os.environ.get("DB_SECRET_ARN")` add:

```python
ENDPOINT = os.environ.get("ENDPOINT_NAME")
runtime = boto3.client("sagemaker-runtime", region_name=REGION)
```

In `do_GET`, directly **before** the final `return self._send(404, {"error": "no such route"})`, add:

```python
            if path == "/predict":
                if not ENDPOINT:
                    return self._send(503, {"error": "ENDPOINT_NAME not set"})
                q = parse_qs(urlparse(self.path).query)
                row = [float(q.get(k, ["0"])[0]) for k in ("sessions", "minutes", "tickets", "pro")]
                resp = runtime.invoke_endpoint(
                    EndpointName=ENDPOINT,
                    ContentType="text/csv",
                    Body=",".join(str(v) for v in row),
                )
                prob = float(resp["Body"].read().decode().strip())
                return self._send(200, {"churn_probability": round(prob, 4), "features": row})
```

Commit on a branch, open a pull request, merge. The pipeline from Post 18 builds the image, waits for your approval, then deploys. After approving and waiting for the service to settle:

```bash
curl -s "http://$ALB/predict?sessions=2&minutes=20&tickets=3&pro=0"
curl -s "http://$ALB/predict?sessions=12&minutes=150&tickets=0&pro=1"
```

```text
{"churn_probability": 0.8598, "features": [2.0, 20.0, 3.0, 0.0]}
{"churn_probability": 0.0851, "features": [12.0, 150.0, 0.0, 1.0]}
```

That is the whole platform path: **Git push → pipeline → ECR → ECS → SageMaker endpoint → model artifact → S3 → processed data → a CSV uploaded to S3**. Every arrow is an IAM permission you wrote.

### 8. Prove the permission boundary

Remove `sagemaker:InvokeEndpoint` from the task role (or add a `Deny`), wait a minute, and call `/predict` again: the API returns a `502` and the log at `/ecs/plat-api` shows `AccessDeniedException`. Restore it. This is the same pattern as the DynamoDB test in Post 11.

### 9. Resources you now have 📦

| Resource | Name |
|---|---|
| Image | `plat/ml:1.1` (train, serve) |
| Training job | `plat-train-<timestamp>` and the artifact `models/.../model.tar.gz` |
| Model, config, endpoint | `plat-churn-<timestamp>` (model and config), **`plat-churn`** (endpoint, `ml.m5.large`) |
| API | Route `/predict`, task-role permission, `ENDPOINT_NAME` variable |

### Cleanup 🧹

**Delete the endpoint now.** An `ml.m5.large` real-time endpoint costs roughly a few cents per hour and runs all day. In the notebook:

```python
sm.delete_endpoint(EndpointName="plat-churn")
sm.delete_endpoint_config(EndpointConfigName=model_name)
sm.delete_model(ModelName=model_name)
```

Verify in **SageMaker, Inference, Endpoints** that the list is empty. After this, `/predict` returns `502` until you redeploy; that is expected. **Post 21 needs the endpoint again for one step**: re-run the step 4 cell then (about ten minutes), and delete it again right after. Keep the model artifact in S3; it costs almost nothing.

Stop the Studio space as well.

---

## Quick Quiz 🧠

**Q1.** You deleted the endpoint configuration and model but the bill continues. Why?

<details>
<summary>Show answer</summary>

The **endpoint** is what runs and bills. Models and endpoint configurations are definitions. Delete the endpoint itself.

</details>

**Q2.** The endpoint goes `Failed` and the log shows `FileNotFoundError: model.joblib`. What is wrong?

<details>
<summary>Show answer</summary>

The artifact doesn't contain `model.joblib` at the top level (the training code didn't write to `/opt/ml/model`, or the `ModelDataUrl` points at the wrong archive). `serve.py` loads it at import, so the container never answers `/ping`.

</details>

**Q3.** Training reports `validation_accuracy=0.53` with a baseline of `0.52`. Is the model good?

<details>
<summary>Show answer</summary>

No. It barely beats always predicting the majority class. Check the AUC, the features, and whether the pipeline preprocessing is right before blaming the algorithm.

</details>

**Q4.** The API gets `AccessDeniedException` calling the endpoint though `DescribeEndpoint` works from the same role. Why?

<details>
<summary>Show answer</summary>

Describing and invoking are different actions. The role needs **`sagemaker:InvokeEndpoint`** on the endpoint ARN.

</details>

**Q5.** Your traffic is a few requests a day. Which inference option fits better than a real-time endpoint?

<details>
<summary>Show answer</summary>

**Serverless inference** (pay per use, tolerates cold starts), or **batch transform** if you can score data in bulk. A real-time endpoint bills continuously regardless of traffic.

</details>

---

## What's Next? 🚀

Everything is built, and half of it can quietly misbehave: a queue that stops draining, a service with two failing tasks, an endpoint that bills overnight, a disk that fills up. The last part makes the platform **observable** and its cost **accountable**.

👉 **[Post 21: CloudWatch, Agent and Alarms](content/aws/21-cloudwatch-agent-and-alarms.md)**: metrics, logs and alarms across the services we've built, the CloudWatch agent on `plat-ec2` for memory and disk, and alarms that notify `plat-alerts`.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
