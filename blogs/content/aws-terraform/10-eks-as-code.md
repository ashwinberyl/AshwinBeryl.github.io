---
title: "Kubernetes on EKS: Cluster, Nodes, Access Entries and Pod Identity"
date: 2026-11-10
tags: [aws, terraform, eks, kubernetes, pod-identity, iam, access-entries, intermediate]
description: Post 10 of the AWS on Terraform series. A cluster with API authentication and no aws-auth ConfigMap, a managed node group whose desired size Terraform leaves alone, a pod role delivered by EKS Pod Identity, and the manifest that completes the picture with kubectl.
---

# The Same API on Kubernetes ☸️

`stacks/55-eks` is the Kubernetes half of the compute story. Terraform builds what AWS owns: the control plane, the nodes, the roles and the binding between a Kubernetes service account and an IAM role. What runs **inside** the cluster is applied with `kubectl`, because that is Kubernetes's own API and its own tooling.

The whole stack sits behind `enable_eks`. The control plane alone bills about ten cents an hour, plus the node.

---

## The Pieces 🧱

| Piece | Resource(s) | Always on? |
|---|---|---|
| Cluster role + cluster `plat-eks` | `aws_iam_role.cluster`, `aws_iam_role_policy_attachment.cluster`, `aws_eks_cluster.this` | **Toggle** `enable_eks` |
| Node role + managed node group | `aws_iam_role.node`, three attachments, `aws_eks_node_group.this` | Toggle |
| Pod role + inline policy | `aws_iam_role.pod`, `aws_iam_role_policy.pod_access` | Toggle |
| Pod Identity agent and association | `aws_eks_addon.pod_identity`, `aws_eks_pod_identity_association.api` | Toggle |
| Database rule for the cluster's security group | `aws_vpc_security_group_ingress_rule.rds_from_cluster` | Toggle |

![EKS with Pod Identity](content/aws-terraform/images/10-eks-pod-identity.svg)

Everything carries `count = local.create`, where `local.create` is `1` or `0`. Outputs use `one(aws_eks_cluster.this[*].name)`, which returns `null` for an empty list, so other stacks can read them whether or not the cluster exists.

```hcl
# stacks/55-eks/main.tf
locals {
  private    = values(data.terraform_remote_state.network.outputs.private_subnet_ids)
  kms_arn    = data.terraform_remote_state.security.outputs.kms_key_arn
  bucket_arn = data.terraform_remote_state.data.outputs.data_bucket_arn
  table_arn  = data.terraform_remote_state.data.outputs.jobs_table_arn
  secret_arn = data.terraform_remote_state.data.outputs.rds_secret_arn
  rds_sg_id  = data.terraform_remote_state.data.outputs.rds_sg_id
  create     = var.enable_eks ? 1 : 0
}
```

---

## Reading the Stack 📖

### The cluster

```hcl
# stacks/55-eks/main.tf
data "aws_iam_policy_document" "eks_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cluster" {
  count = local.create

  name               = "plat-eks-cluster-role"
  assume_role_policy = data.aws_iam_policy_document.eks_trust.json
}

resource "aws_iam_role_policy_attachment" "cluster" {
  count = local.create

  role       = aws_iam_role.cluster[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_eks_cluster" "this" {
  count = local.create

  name     = "plat-eks"
  role_arn = aws_iam_role.cluster[0].arn
  version  = var.kubernetes_version

  vpc_config {
    subnet_ids              = local.private
    endpoint_private_access = true
    endpoint_public_access  = true
  }

  # Access entries instead of the old aws-auth ConfigMap. The identity that creates the cluster
  # (you, as PlatformAdmin) is made cluster admin automatically.
  access_config {
    authentication_mode                         = "API"
    bootstrap_cluster_creator_admin_permissions = true
  }

  depends_on = [aws_iam_role_policy_attachment.cluster]
}
```

* **The cluster role** is assumed by the EKS service to manage network interfaces and load balancers on your behalf.
* **`authentication_mode = "API"`** means access is managed by **access entries**, an AWS API, instead of the old `aws-auth` ConfigMap inside the cluster. A mistake in that ConfigMap could lock everyone out; access entries cannot be broken from inside Kubernetes.
* **`bootstrap_cluster_creator_admin_permissions = true`** makes the identity that runs `apply` a cluster administrator automatically. That identity is your `PlatformAdmin` session. Anyone else gets an access entry (below).
* The cluster uses both private and public API endpoints. Public is convenient for a lab and limited by IAM; in production you would restrict it by CIDR or turn it off.
* Version is `null` unless you set it, so EKS picks its current default. Pin it for anything real, and upgrade by changing the variable.

### The nodes

```hcl
# stacks/55-eks/main.tf
resource "aws_iam_role" "node" {
  count = local.create

  name               = "plat-eks-node-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_trust.json
}

resource "aws_iam_role_policy_attachment" "node" {
  for_each = var.enable_eks ? toset([
    "AmazonEKSWorkerNodePolicy",
    "AmazonEKS_CNI_Policy",
    "AmazonEC2ContainerRegistryReadOnly",
  ]) : toset([])

  role       = aws_iam_role.node[0].name
  policy_arn = "arn:aws:iam::aws:policy/${each.key}"
}

resource "aws_eks_node_group" "this" {
  count = local.create

  cluster_name    = aws_eks_cluster.this[0].name
  node_group_name = "plat-nodes"
  node_role_arn   = aws_iam_role.node[0].arn
  subnet_ids      = local.private
  instance_types  = [var.node_instance_type]
  ami_type        = "AL2023_x86_64_STANDARD"

  scaling_config {
    desired_size = var.node_desired
    min_size     = 1
    max_size     = 2
  }

  update_config {
    max_unavailable = 1
  }

  # Something else (the cluster autoscaler, or you) may change the desired size later.
  lifecycle {
    ignore_changes = [scaling_config[0].desired_size]
  }

  depends_on = [aws_iam_role_policy_attachment.node]
}
```

The three managed policies are the standard set: join the cluster, let the CNI plugin manage network interfaces, and pull from ECR. The `for_each` over a set builds one attachment per policy name, keyed by the name. `ignore_changes = [scaling_config[0].desired_size]` is the same reasoning as the service in Post 09: if an autoscaler or you change the size later, Terraform should not undo it. The node group uses the private subnets, so nodes have no public address and need a **NAT** to join the cluster and pull images.

### The pod role

```hcl
# stacks/55-eks/main.tf
data "aws_iam_policy_document" "pods_trust" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]

    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "pod" {
  count = local.create

  name               = "plat-eks-pod-role"
  assume_role_policy = data.aws_iam_policy_document.pods_trust.json
}
```

Compare the trust policy with every earlier role. The principal is `pods.eks.amazonaws.com`, and the actions include **`sts:TagSession`**, because EKS adds session tags (cluster, namespace, service account) when it assumes the role for a pod. The permissions are the same list the ECS task role has: bucket, table, key and, when it exists, the database secret. Both compute options get the **same capability**, and only the trust differs.

### Binding the role to a service account

```hcl
# stacks/55-eks/main.tf
resource "aws_eks_addon" "pod_identity" {
  count = local.create

  cluster_name = aws_eks_cluster.this[0].name
  addon_name   = "eks-pod-identity-agent"

  depends_on = [aws_eks_node_group.this]
}

resource "aws_eks_pod_identity_association" "api" {
  count = local.create

  cluster_name    = aws_eks_cluster.this[0].name
  namespace       = "default"
  service_account = var.service_account
  role_arn        = aws_iam_role.pod[0].arn

  depends_on = [aws_eks_addon.pod_identity]
}
```

The add-on runs an agent on every node. The association says: pods in namespace `default` using service account `plat-api` get the role `plat-eks-pod-role`. Nothing needs to be annotated on the service account. The add-on needs nodes to run on, so it depends on the node group.

Compare with the older approach, IRSA, where you create an OIDC provider and write the cluster's issuer URL into the role's trust policy, one trust statement per cluster. Pod Identity removes that coupling: the role's trust policy never mentions the cluster.

### Reaching the database

```hcl
# stacks/55-eks/main.tf
resource "aws_vpc_security_group_ingress_rule" "rds_from_cluster" {
  count = local.create

  security_group_id            = local.rds_sg_id
  referenced_security_group_id = aws_eks_cluster.this[0].vpc_config[0].cluster_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  description                  = "PostgreSQL from EKS nodes and pods"
}
```

Pods use the **cluster security group** EKS creates. The rule adds it as an allowed source on `plat-rds-sg` (the group lives in `40-data`, the rule lives here, in the stack that creates the reason for it). This works because rules are separate resources, as in Post 05.

---

## What Terraform doesn't apply ⚙️

```yaml
# stacks/55-eks/manifests/plat-api.yaml
# Applied by hand in Post 10 with: kubectl apply -f manifests/plat-api.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: plat-api            # must match var.service_account: the pod role is bound to it
  namespace: default
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: plat-api
  namespace: default
spec:
  replicas: 2
  selector:
    matchLabels:
      app: plat-api
  template:
    metadata:
      labels:
        app: plat-api
    spec:
      serviceAccountName: plat-api
      containers:
        - name: api
          image: public.ecr.aws/docker/library/nginx:stable
          ports:
            - containerPort: 80
          readinessProbe:
            httpGet:
              path: /
              port: 80
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
---
apiVersion: v1
kind: Service
metadata:
  name: plat-api-lb
  namespace: default
spec:
  type: LoadBalancer
  selector:
    app: plat-api
  ports:
    - port: 80
      targetPort: 80
```

The service account name must equal `var.service_account`. The Deployment uses that account and a `LoadBalancer` Service asks AWS for a load balancer. Terraform could manage these objects with a Kubernetes provider, but that couples this stack to the cluster being reachable and adds a second authentication path. For a course lab, `kubectl apply` is the clearer boundary.

---

## Nuances & Misconceptions 🧩

| What people assume | What's actually true |
|---|---|
| "The cluster creator is just another user." | With `bootstrap_cluster_creator_admin_permissions` they are an admin through a hidden access entry. Another identity gets `Unauthorized` until you add an entry for it. |
| "`aws-auth` is how EKS works." | It's the legacy method. With mode `API` it isn't used at all. |
| "Pod Identity needs an OIDC provider." | That is IRSA. Pod Identity needs only the agent add-on and the association. |
| "The pod role trusts the node role." | It trusts the **EKS Pods service**. A pod without the association can only use the **node** role's permissions, which are narrower. |
| "Pods can reach the database because the nodes can." | Security groups apply to the network interface. The rule must allow the **cluster security group**. |
| "Nodes in private subnets just work." | They need a NAT (or endpoints for EKS, ECR, S3, STS and more) to register. Without it the node group sits in `CREATE_FAILED`. |
| "Destroying the cluster removes the load balancer a Service created." | The balancer belongs to Kubernetes, not Terraform. **Delete the Service first**, or the ENIs it made block subnet and VPC deletion. |
| "`desired_size` in code is the size of the node group." | Only at creation. Later changes are ignored on purpose. |
| "The control plane price is per node." | It is a flat hourly price per cluster, whatever you run on it. |
| "Upgrading the Kubernetes version is a variable change and nothing else." | It upgrades the control plane in place, then nodes roll with `max_unavailable`. Add-ons and manifests may need updates for removed APIs. |
| "Terraform sees my pods." | It sees the cluster. Everything inside is invisible to state. |
| "A Service of type `LoadBalancer` is free." | It creates a billed AWS load balancer. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| `private_subnet_ids` (and tagged public subnets for load balancers) | `20-network` |
| `kms_key_arn` | `30-security` |
| bucket, table, `rds_secret_arn`, `rds_sg_id` | `40-data` |
| A NAT gateway | `20-network` (`enable_nat`) |

| You create here | Used by |
|---|---|
| Cluster `plat-eks` | Dashboard in Post 14 (Container Insights is separate), `kubectl` |
| Role `plat-eks-pod-role` | Your pods |
| Output `kubeconfig_command` | The lab below |

### Console clicks you no longer make

| In the AWS series you... | Here it is |
|---|---|
| **EKS, Create cluster**, role, networking, access, add-ons | `aws_eks_cluster.this` and `aws_eks_addon.pod_identity` |
| **Add node group**: role, instance type, scaling | `aws_eks_node_group.this` |
| **Access, Create access entry** | `access_config` (creator) and `aws_eks_access_entry` (others, below) |
| **Pod Identity associations, Create** | `aws_eks_pod_identity_association.api` |
| **IAM, Create role** for the cluster, the nodes and the pods | Three `aws_iam_role` resources |

---

## Lab: Run the API on Kubernetes 🛠️

You need `kubectl`. The NAT from Post 09 must still be on.

### 1. Plan

```bash
export AWS_PROFILE=plat-admin AWS_REGION=us-east-1
scripts/tf.sh 55-eks plan -var enable_eks=true
```

```
Plan: 13 to add, 0 to change, 0 to destroy.
```

Cluster role and its attachment (2), the cluster, node role with three attachments (4), the node group, pod role with its inline policy (2), the add-on, the association and the database rule.

### 2. Apply

```bash
scripts/tf.sh 55-eks apply -var enable_eks=true
```

This takes **12 to 18 minutes**: about ten for the control plane, then the nodes. Terraform prints `Still creating...` the whole time. That is normal.

### 3. Connect

```bash
$(terraform -chdir=stacks/55-eks output -raw kubeconfig_command)
kubectl get nodes
kubectl get pods -n kube-system -l app.kubernetes.io/name=eks-pod-identity-agent
```

```
NAME                          STATUS   ROLES    AGE   VERSION
ip-10-20-10-143.ec2.internal  Ready    <none>   4m    v1.33.x
NAME                           READY   STATUS    RESTARTS   AGE
eks-pod-identity-agent-x7k2p   1/1     Running   0          3m
```

If `kubectl` answers `You must be logged in to the server (Unauthorized)`, you are running as a different identity than the one that created the cluster (a new SSO session for another permission set, say). The next step grants access to another identity.

### 4. Add access for someone else (optional)

```bash
aws eks create-access-entry --cluster-name plat-eks --principal-arn <role-or-user-arn>
aws eks associate-access-policy --cluster-name plat-eks --principal-arn <role-or-user-arn> \
  --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSViewPolicy --access-scope type=cluster
```

Access entries are AWS API objects: they show up in `aws eks list-access-entries --cluster-name plat-eks`, and you can manage them in Terraform with `aws_eks_access_entry` and `aws_eks_access_policy_association` once you decide who they are for.

### 5. Deploy the manifest

```bash
kubectl apply -f stacks/55-eks/manifests/plat-api.yaml
kubectl rollout status deployment/plat-api
kubectl get svc plat-api-lb -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'; echo
```

```
deployment "plat-api" successfully rolled out
a1b2c3d4e5f6g7h8-123456789.us-east-1.elb.amazonaws.com
```

The load balancer takes a couple of minutes to answer. `curl -s -o /dev/null -w '%{http_code}\n' http://<hostname>/` returns `200`.

### 6. Prove Pod Identity

Run a throw-away pod under the same service account and ask AWS who it is:

```bash
kubectl run who --rm -it --restart=Never --image=public.ecr.aws/aws-cli/aws-cli \
  --overrides='{"spec":{"serviceAccountName":"plat-api"}}' --command -- aws sts get-caller-identity --query Arn --output text
```

```
arn:aws:sts::123456789012:assumed-role/plat-eks-pod-role/eks-plat-eks-who-...
```

Now the same without the service account:

```bash
kubectl run who2 --rm -it --restart=Never --image=public.ecr.aws/aws-cli/aws-cli \
  --command -- aws sts get-caller-identity --query Arn --output text
```

```
arn:aws:sts::123456789012:assumed-role/plat-eks-node-role/i-0abc...
```

The **only** difference is the service account. The first pod got the role from the association; the second fell back to the node's role, which cannot read the data bucket.

### 7. Break it: delete the association

```bash
aws eks list-pod-identity-associations --cluster-name plat-eks --query 'associations[0].associationId' --output text \
  | xargs -I{} aws eks delete-pod-identity-association --cluster-name plat-eks --association-id {}
scripts/tf.sh 55-eks plan -var enable_eks=true
```

```
  # aws_eks_pod_identity_association.api[0] will be created
Plan: 1 to add, 0 to change, 0 to destroy.
```

Re-run the pod from step 6 and it reports the node role: the binding is gone and nothing in Kubernetes says so. Apply to recreate it. This is exactly the kind of cross-system link that is invisible in the console and obvious in a plan.

### 8. Resources you now have 📦

| Resource | Name | Notes |
|---|---|---|
| Cluster | `plat-eks` | **About $0.10/hour** |
| Node group | `plat-nodes` | One `t3.medium`, bills hourly |
| Roles | `plat-eks-cluster-role`, `plat-eks-node-role`, `plat-eks-pod-role` | |
| Add-on | `eks-pod-identity-agent` | |
| Load balancer | created by the Service | **Not in state.** Remove with kubectl |

### Cleanup 🧹

**Order matters**: Kubernetes first, then Terraform.

```bash
kubectl delete -f stacks/55-eks/manifests/plat-api.yaml     # removes the AWS load balancer
scripts/tf.sh 55-eks apply                                  # plan is 13 to destroy
```

Skipping the first line leaves a load balancer whose network interfaces block the VPC from being deleted later, and an apply that hangs on the subnet.

---

## Quick Quiz 🧠

**Q1.** A pod using service account `plat-api` gets `AccessDenied` on S3, and `sts get-caller-identity` shows the **node** role. What is missing?

<details>
<summary>Show answer</summary>

The **Pod Identity association** (or the agent add-on): without a match on namespace and service account, the pod falls back to the node's credentials. Check `aws eks list-pod-identity-associations` and that the pod uses the right service account.

</details>

**Q2.** Why does the pod role's trust policy include `sts:TagSession`?

<details>
<summary>Show answer</summary>

EKS attaches **session tags** (cluster name, namespace, service account) when it assumes the role for a pod. Without `TagSession` in the trust policy the assume call is denied.

</details>

**Q3.** What replaced the `aws-auth` ConfigMap, and why is it safer?

<details>
<summary>Show answer</summary>

**Access entries** managed through the EKS API. They are not stored in the cluster, so a bad edit inside Kubernetes cannot lock administrators out, and they can be audited and managed with Terraform.

</details>

**Q4.** `terraform destroy` hangs on the subnets after you skipped `kubectl delete`. Why?

<details>
<summary>Show answer</summary>

The Service of type LoadBalancer created an AWS load balancer **outside Terraform's state**, and its network interfaces still occupy the subnets. Delete the Service (or the load balancer) first.

</details>

**Q5.** Why does the node group ignore `desired_size`?

<details>
<summary>Show answer</summary>

Capacity is expected to be changed by something else (an autoscaler, or an operator). Managing it in code would make each plan reset the size to the value in the file.

</details>

---

## What's Next? 🚀

Both compute options are up. Next we add the part that reacts: an upload lands in S3, a queue absorbs it, a function processes it, and a nightly schedule produces a report.

👉 [Post 11: Events as Code: S3, SQS, Lambda, EventBridge and SNS](content/aws-terraform/11-events-as-code.md)

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
