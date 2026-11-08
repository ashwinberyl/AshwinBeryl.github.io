---
title: "EKS"
date: 2026-11-08
tags: [aws, eks, kubernetes, pod-identity, access-entries, managed-node-group, kubectl, intermediate]
description: Post 12 of the AWS series. What EKS manages and what it leaves to you, how Kubernetes access and pod permissions map onto IAM, and a lab that builds a cluster with a managed node group and runs plat-api with its own pod role.
---

# Kubernetes, with AWS Identity Underneath ☸️

If you've read the Kubernetes series, you already know Deployments, Services, probes and `kubectl`. None of that changes on EKS. What changes is everything *around* the cluster:

- Who may call the Kubernetes API (that's **IAM**, not a kubeconfig certificate).
- Where the nodes live (**your VPC**, your subnets, your security groups).
- How a pod gets AWS permissions (**not** from the node's role, if you do it properly).

This post is about those seams.

![EKS: control plane, nodes, and the identity paths](content/aws/images/12-eks.svg)

---

## What EKS Manages and What You Manage 🧭

| | AWS manages | You manage |
|---|---|---|
| **Control plane** | API server and etcd across multiple AZs, upgrades of the control plane | Choosing the version, planning upgrades |
| **Nodes** | Managed node groups automate provisioning, draining and AMI updates | Instance type, size, subnets, the node IAM role, and *when* to roll |
| **Add-ons** | Can install and update VPC CNI, CoreDNS, kube-proxy, Pod Identity Agent | Their versions and settings |
| **Workloads** | Nothing | Everything in the cluster |

The control plane runs in an AWS-owned VPC. It reaches your nodes through ENIs it places **in your subnets**, and your nodes and tools reach it through the **cluster endpoint**, which can be public, private or both.

---

## Who Can Talk to the Cluster? 🔑

Authentication to the API server uses a signed IAM token (`aws eks get-token`), so the question becomes "what does this IAM principal do **inside** Kubernetes?" The modern answer is **access entries**:

| Concept | Detail |
|---|---|
| **Access entry** | Maps an IAM principal (user or role) to the cluster |
| **Access policy** | An AWS-managed set of Kubernetes permissions, for example `AmazonEKSClusterAdminPolicy` or `AmazonEKSViewPolicy`, scoped to the cluster or to namespaces |
| **Creator** | The IAM identity that created the cluster gets admin access, depending on a creation setting |
| **`aws-auth` ConfigMap** | The **older** mechanism. Prefer access entries, and don't mix them without understanding which wins |

An IAM Identity Center user arrives as an **`AWSReservedSSO_...` role** (Post 03). You map *that role* (without the `/aws-reserved/sso.amazonaws.com/` path in the old ConfigMap format).

---

## How Does a Pod Get AWS Permissions? 🪪

The wrong way: every pod uses the **node's instance role**. Then every pod on that node can do everything the node can. The right way is one role per workload:

| Method | How it works | Notes |
|---|---|---|
| **EKS Pod Identity** (newer) | An **agent add-on** on each node. You create an association: *cluster + namespace + service account → IAM role* | The role trusts `pods.eks.amazonaws.com`. No OIDC provider to set up. Reusable across clusters |
| **IRSA** (IAM Roles for Service Accounts) | The cluster has an **OIDC provider**. The role trusts that provider and a specific service account | Works everywhere, more setup, trust policy is per cluster |

We use **Pod Identity**. In both cases the pod's SDK finds the credentials automatically through its standard credential chain.

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "EKS is free except for the nodes." | The control plane is about **$0.10 per hour** (about $73/month) per cluster, **before any node**. Clusters on versions in extended support cost significantly more. |
| "I created the cluster, so my teammate can use it too." | Access is **per IAM principal**. Only the creator (and whoever you add through access entries) gets in. |
| "kubectl works from CloudShell without setup." | You must run `aws eks update-kubeconfig`, and the **cluster endpoint must be reachable** from where you are (public endpoint, or a network inside the VPC). |
| "Nodes use the cluster role." | There are **two roles**: the **cluster role** (used by EKS to manage your cluster's AWS resources) and the **node role** (used by kubelet to join the cluster and pull images). |
| "Pods get permissions from the node role." | They *can*, which is the problem. Set pod roles with Pod Identity or IRSA, and block pod access to the node role with a hop limit of 1 on metadata, or network policy. |
| "I attached the role to the service account, so it works." | Pods read credentials **at start**. Existing pods don't pick up a new association. **Restart them.** |
| "Pod IPs come from an overlay network." | With the **VPC CNI**, each pod gets a **real VPC IP** from the node's ENIs. A small subnet or a small instance type limits **how many pods fit on a node**. |
| "`Service type=LoadBalancer` is the modern way." | With no controller it creates a **Classic Load Balancer** through legacy code. Production clusters install the **AWS Load Balancer Controller** for ALB (Ingress) and NLB (Service). Public subnets must be tagged `kubernetes.io/role/elb=1` either way. |
| "Deleting the node group deletes the cluster's cost." | The **control plane keeps billing**. Delete the **cluster** to stop it. |
| "Upgrading is just a button." | Control plane first, then add-ons, then nodes. You can only move **one minor version** at a time, and APIs deprecated in a release will fail your manifests. |
| "Security groups on nodes protect pods individually." | By default pods share the **node's** security groups. Per-pod SGs need a CNI feature and compatible instance types. |
| "`kubectl` shows the nodes, so the node role is right." | Nodes joining only proves the **node role** and bootstrap work. Image pulls from ECR also need the node role's **registry read** permission. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| `plat-vpc` and its subnets, NAT gateway | Post 04 |
| Identity Center admin role (`AWSReservedSSO_PlatformAdmin_...`) | Post 03 |
| `plat/api:1.0.1` image in ECR and the same environment variables | Posts 09, 11 |
| Bucket, KMS key, `plat-jobs`, RDS secret | Posts 05, 06, 08 |
| Kubernetes objects: Deployment, Service, probes, ServiceAccount | The Kubernetes series |

| You create here | Used by |
|---|---|
| Cluster **`plat-eks`** and node group | A second home for `plat-api`; Container Insights in Post 21 can observe it |
| Role **`plat-eks-pod-role`** | The same least-privilege pattern as Post 11's task role |

---

## Lab: Build `plat-eks` and Run `plat-api` 🛠️

You'll spend about **$0.30 per hour** while this runs (control plane, two `t3.medium` nodes, a load balancer). Plan to finish in one sitting and delete it.

### 1. Roles

**Cluster role.** IAM, Roles, Create role, use case **EKS - Cluster**, policy `AmazonEKSClusterPolicy`, name **`plat-eks-cluster-role`**.

**Node role.** Create role, use case **EC2**, attach:

- `AmazonEKSWorkerNodePolicy`
- `AmazonEKS_CNI_Policy`
- `AmazonEC2ContainerRegistryReadOnly`

Name it **`plat-eks-node-role`**.

**Pod role.** Create role, trusted entity **Custom trust policy**, paste:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "pods.eks.amazonaws.com" },
      "Action": ["sts:AssumeRole", "sts:TagSession"]
    }
  ]
}
```

Skip managed policies. Name it **`plat-eks-pod-role`**, then add the **same inline policy `plat-api-access`** you used for `plat-ecs-task-role` in Post 11 (S3 read, KMS via S3, DynamoDB read, secret read, and KMS decrypt via Secrets Manager). Copy the JSON from that role.

### 2. Tag the public subnets

For the load balancer to find its subnets, open **VPC, Subnets**, select `plat-public-a` and `plat-public-b`, and add the tag **`kubernetes.io/role/elb = 1`**. For internal load balancers you'd tag private subnets with `kubernetes.io/role/internal-elb = 1`.

### 3. Create the cluster

**EKS, Create cluster, Custom configuration**:

| Setting | Value |
|---|---|
| Use EKS Auto Mode | **Off** (we want to see the pieces) |
| Name | `plat-eks` |
| Cluster IAM role | `plat-eks-cluster-role` |
| Kubernetes version | The **default (standard support)** version offered |
| Cluster creator admin permissions | **On** |
| Authentication mode | **EKS API and ConfigMap** (or EKS API) |
| VPC | `plat-vpc`, subnets **`plat-private-a`, `plat-private-b`** (add the public ones too if the console doesn't offer a mix) |
| Security group | Leave default (EKS creates a cluster SG) |
| Endpoint access | **Public and private** |
| Tags | `project = plat` |

Add-ons: keep **CoreDNS**, **kube-proxy**, **Amazon VPC CNI**, and add **EKS Pod Identity Agent**. Create. The cluster takes about **10 to 15 minutes** to reach *Active*.

### 4. Add nodes

When the cluster is *Active*, open it, **Compute, Add node group**:

| Setting | Value |
|---|---|
| Name | `plat-nodes` |
| Node IAM role | `plat-eks-node-role` |
| AMI type | **Amazon Linux 2023 (x86_64)** |
| Capacity | **On-Demand** |
| Instance type | **t3.medium** |
| Scaling | desired **2**, min **1**, max **3** |
| Subnets | `plat-private-a`, `plat-private-b` |

Wait for status *Active* (about 5 minutes). Nodes reach the control plane and ECR through the NAT gateway.

### 5. Reach the cluster

Open **CloudShell** in a normal (non-VPC) environment while signed in as Jim's SSO session, then:

```bash
aws eks update-kubeconfig --name plat-eks --region us-east-1
kubectl get nodes -o wide
```

```text
NAME                           STATUS   ROLES    AGE   VERSION               INTERNAL-IP
ip-10-20-10-143.ec2.internal   Ready    <none>   3m    v1.<minor>.x-eks-...  10.20.10.143
ip-10-20-11-62.ec2.internal    Ready    <none>   3m    v1.<minor>.x-eks-...  10.20.11.62
```

Two nodes, one in each private subnet. If you get `Unauthorized`, open **EKS, plat-eks, Access** and check that your role appears under access entries. Add it with policy **`AmazonEKSClusterAdminPolicy`** if not.

Check the system pods and add-ons:

```bash
kubectl get pods -n kube-system
```

You should see `aws-node` (VPC CNI), `coredns`, `kube-proxy` and `eks-pod-identity-agent`, one per node for the DaemonSets.

### 6. Deploy `plat-api`

Create a namespace and a service account:

```bash
kubectl create namespace plat
kubectl create serviceaccount plat-api -n plat
```

**`plat-api.yaml`**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: plat-api
  namespace: plat
  labels: { app: plat-api }
spec:
  replicas: 2
  selector:
    matchLabels: { app: plat-api }
  template:
    metadata:
      labels: { app: plat-api }
    spec:
      serviceAccountName: plat-api
      containers:
        - name: api
          image: 123456789012.dkr.ecr.us-east-1.amazonaws.com/plat/api:1.0.1
          ports:
            - containerPort: 8080
          env:
            - { name: APP_VERSION, value: "1.0.1-eks" }
            - { name: DATA_BUCKET, value: "plat-data-123456789012-us-east-1" }
            - { name: JOBS_TABLE,  value: "plat-jobs" }
            - { name: DB_HOST,     value: "plat-meta.xxxxxxxx.us-east-1.rds.amazonaws.com" }
            - { name: DB_NAME,     value: "platmeta" }
            - { name: DB_SECRET_ARN, value: "arn:aws:secretsmanager:us-east-1:123456789012:secret:rds!db-xxxx" }
          readinessProbe:
            httpGet: { path: /health, port: 8080 }
            initialDelaySeconds: 3
            periodSeconds: 5
          livenessProbe:
            httpGet: { path: /health, port: 8080 }
            initialDelaySeconds: 10
            periodSeconds: 10
          resources:
            requests: { cpu: 100m, memory: 128Mi }
            limits:   { memory: 256Mi }
---
apiVersion: v1
kind: Service
metadata:
  name: plat-api
  namespace: plat
spec:
  selector: { app: plat-api }
  ports:
    - port: 80
      targetPort: 8080
```

Replace the account ID, bucket, RDS endpoint and secret ARN with yours (use the same values as the ECS task definition), then apply. In CloudShell, use the **Actions, Upload file** option, or paste with `cat > plat-api.yaml`:

```bash
kubectl apply -f plat-api.yaml
kubectl get pods -n plat -w
```

```text
NAME                        READY   STATUS    RESTARTS   AGE
plat-api-6c9d8b7f5d-4kq2m   1/1     Running   0          28s
plat-api-6c9d8b7f5d-x9w7t   1/1     Running   0          28s
```

The image came from ECR using the **node role**.

### 7. See the missing permission first

With no association yet, this pod has **no AWS identity of its own**. Call it from inside the cluster:

```bash
kubectl port-forward -n plat svc/plat-api 8080:80 &
sleep 2
curl -s localhost:8080/health
curl -s localhost:8080/data
curl -s localhost:8080/jobs/job-001
```

```text
{"status": "ok"}
{"error": "ClientError"}
{"error": "ClientError"}
```

Look at the logs: `kubectl logs -n plat deploy/plat-api --tail=5`. The pod fell back to the **node role** (which only has worker and registry permissions) and was refused. This is exactly what Pod Identity is meant to fix.

### 8. Create the Pod Identity association

**EKS, plat-eks, Access, Pod Identity associations, Create**:

| Field | Value |
|---|---|
| IAM role | `plat-eks-pod-role` |
| Kubernetes namespace | `plat` |
| Kubernetes service account | `plat-api` |

Restart the pods so they receive credentials:

```bash
kubectl rollout restart deployment/plat-api -n plat
kubectl rollout status deployment/plat-api -n plat
kill %1 2>/dev/null
kubectl port-forward -n plat svc/plat-api 8080:80 &
sleep 2
curl -s localhost:8080/data
curl -s localhost:8080/jobs/job-001
curl -s localhost:8080/datasets
```

```text
{"bucket": "plat-data-123456789012-us-east-1", "raw_objects": ["raw/events.csv"]}
{"job_id": "job-001", "status": "DONE", "created_at": "2026-11-08T09:00:00Z", "rows": "5050"}
[{"id": 1, "name": "events_2026_11", "s3_key": "raw/events.csv", "row_count": 5050}]
```

Check what the pod sees:

```bash
POD=$(kubectl get pod -n plat -l app=plat-api -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n plat $POD -- env | grep AWS_CONTAINER
```

```text
AWS_CONTAINER_CREDENTIALS_FULL_URI=http://169.254.170.23/v1/credentials
AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE=/var/run/secrets/pods.eks.amazonaws.com/serviceaccount/eks-pod-identity-token
```

Those variables were **injected by the Pod Identity webhook** when the pod started. That's why a restart was needed.

> **Note:** `/datasets` needs the pods to reach RDS. Pods use the **node's security groups**, not `plat-app-sg`. If this call fails with a timeout, add an inbound rule to `plat-rds-sg`: **PostgreSQL 5432** from the **EKS cluster security group** (shown on the cluster's Networking tab). This is the same SG-reference pattern as before, applied to a new client.

### 9. Expose it

Create a load balancer:

```bash
kubectl expose deployment plat-api -n plat --name=plat-api-lb --type=LoadBalancer --port=80 --target-port=8080
kubectl get svc -n plat plat-api-lb -w
```

After a minute or two, `EXTERNAL-IP` shows a name such as `a1b2...us-east-1.elb.amazonaws.com`. Then:

```bash
curl -s http://<that-name>/
```

```text
{"app": "plat-api", "version": "1.0.1-eks", "host": "plat-api-6c9d8b7f5d-4kq2m"}
```

The `host` is now a **pod name**, where on ECS it was a task IP hostname. In the EC2 console you'll find a **Classic Load Balancer** that Kubernetes created for you, in your tagged public subnets. For production, install the **AWS Load Balancer Controller** and use an Ingress (ALB) or NLB Service.

### 10. Resources you now have 📦

| Resource | Name |
|---|---|
| Cluster, node group | `plat-eks`, `plat-nodes` (2 × t3.medium) |
| Roles | `plat-eks-cluster-role`, `plat-eks-node-role`, `plat-eks-pod-role` |
| Pod Identity association | `plat/plat-api` → `plat-eks-pod-role` |
| Kubernetes objects | namespace `plat`, ServiceAccount, Deployment, two Services |
| Load balancer | A Classic LB created by `plat-api-lb` |

### Cleanup 🧹

Order matters, because a Kubernetes-created load balancer must be deleted through Kubernetes:

```bash
kubectl delete svc plat-api-lb -n plat
kubectl delete namespace plat
```

Wait until the load balancer disappears from the EC2 console. Then delete the **node group**, then the **cluster** (console, EKS). Remove the extra inbound rule on `plat-rds-sg` and the two subnet tags if you like. The roles are free and can stay.

> If you delete the cluster first, the leftover load balancer and its ENIs can **block VPC deletion later**.

---

## Quick Quiz 🧠

**Q1.** A colleague runs `kubectl get nodes` against `plat-eks` and gets `Unauthorized`. Where do you look and what do you add?

<details>
<summary>Show answer</summary>

**EKS, the cluster, Access**: add an **access entry** for the colleague's IAM role (for Identity Center users, the `AWSReservedSSO_...` role) and attach an **access policy** such as `AmazonEKSViewPolicy` or `AmazonEKSClusterAdminPolicy`.

</details>

**Q2.** Which role pulls the image from ECR for a pod: the pod role, the cluster role, or the node role?

<details>
<summary>Show answer</summary>

The **node role** (kubelet pulls images), which is why it carries `AmazonEC2ContainerRegistryReadOnly`. The pod role is for application code.

</details>

**Q3.** You created the Pod Identity association, but `/data` still fails. What did you forget?

<details>
<summary>Show answer</summary>

**Restarting the pods.** Credentials are wired in when a pod starts. Also confirm the association's namespace and **service account name** match, and the Deployment uses that `serviceAccountName`.

</details>

**Q4.** You deleted the node group to save money, but the bill continues. Why?

<details>
<summary>Show answer</summary>

The **control plane** (about $0.10 per hour) bills for as long as the cluster exists. Delete the cluster itself.

</details>

**Q5.** Name one difference between Pod Identity and IRSA.

<details>
<summary>Show answer</summary>

Pod Identity uses an **agent add-on** and an EKS-side association, and the role trusts `pods.eks.amazonaws.com`, so there's **no OIDC provider** to manage and the trust policy isn't tied to one cluster. IRSA needs the cluster's **OIDC provider** and a trust policy naming that provider and service account.

</details>

---

## What's Next? 🚀

The platform now runs on two kinds of compute. But a lot of work doesn't need a server running at all: something lands in S3, you process it, and you stop. That's the event-driven side of AWS.

👉 **[Post 13: Lambda](content/aws/13-lambda.md)**: write a function that processes an uploaded file, understand execution roles, resource policies, cold starts and timeouts, and wire it to S3 and DynamoDB.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
