---
title: "Berth Planning — Scheduling, Resources and Probes"
date: 2026-11-06
tags: [kubernetes, scheduler, resources, requests, limits, oomkilled, probes, hpa, intermediate]
description: Post 11 of the Kubernetes from First Principles series. How the scheduler picks a node, what requests and limits really mean, how probes tell the cluster a pod is healthy, with labs that cause a Pending pod, an OOMKill, and a self-healing restart.
---

# A Port Has Limits ⚖️

So far we've let the cluster put containers wherever it liked and use however much it liked. Real ports can't run that way:

- A berth has finite **space and crane capacity**. You can't place 50 heavy containers on a berth that holds 10.
- A greedy container can **starve its neighbours**.
- You need to know **whether a container is actually working**, not just whether it arrived.

This post covers all three: **scheduling**, **resources**, and **probes**.

---

## How the Scheduler Chooses 🧮

Recall from Post 03: the scheduler looks at new pods with no node and picks one. It does this in two steps:

1. **Filter**: throw out nodes that *can't* run the pod (not enough free CPU/memory, wrong labels, tainted, etc.).
2. **Score**: rank the remaining nodes (spread pods out, prefer nodes that already have the image…) and pick the best.

If **no node passes the filter**, the pod stays **`Pending`** and the scheduler records why. That's a very common, very fixable situation.

You can influence the choice:

| Tool | Meaning | Analogy |
|---|---|---|
| **nodeSelector** | "Only nodes with this label" | "Heavy cargo only on the deep-water berths" |
| **Affinity / anti-affinity** | "Near / away from these other pods" | "Don't put both refrigerated containers on one crane" |
| **Taints and tolerations** | Nodes *repel* pods unless the pod tolerates the taint | A berth reserved for special cargo |
| **topologySpreadConstraints** | Spread replicas across zones/nodes | Don't put every container on one berth |

---

## Requests and Limits: Two Different Promises 📏

Each container can declare:

```yaml
resources:
  requests:
    cpu: "100m"        # 0.1 of a CPU core
    memory: "64Mi"
  limits:
    cpu: "500m"
    memory: "128Mi"
```

| | **Request** | **Limit** |
|---|---|---|
| **Meaning** | "I need at least this." | "I must never exceed this." |
| **Who uses it** | The **scheduler**: it only places a pod where the requests *fit* | The **kubelet / kernel (cgroups, Post 02)**: it enforces the cap |
| **Port analogy** | The space reserved on the berth | The weight painted on the container's side |

(`100m` = 100 *millicores*, a tenth of a core.) What happens at the limit differs by resource, and that difference matters:

| Resource | Exceeding the limit | Why |
|---|---|---|
| **CPU** | **Throttled**: slowed down, but alive | CPU is *compressible*: you can just give less of it |
| **Memory** | **OOMKilled**: the container is killed and restarted | Memory is *not compressible*: you can't take it back |

> **Key insight:** If you set **no requests**, the scheduler assumes your pod needs nothing and may pack a node until it falls over. If you set **no memory limit**, one leaky pod can take down a whole node. Set both, and base them on measurement.

---

## Probes: Is It Actually Working? 🩺

A container can be *running* and still be broken: deadlocked, still loading data, or out of database connections. Kubernetes can't know unless you tell it how to ask. Three kinds of **probe**:

| Probe | Question | If it fails |
|---|---|---|
| **Startup** | "Has the app finished booting?" | Keep waiting (and don't run the others yet); give up after N failures |
| **Readiness** | "Can it handle traffic *right now*?" | **Removed from Service endpoints**: no traffic is sent, but it isn't restarted |
| **Liveness** | "Is it still alive, or hopelessly stuck?" | **The container is killed and restarted** |

Remember the key insight from Post 06? A rolling update only knows a new pod is good when its **readiness probe passes**. This is the piece that makes zero-downtime rollouts honest.

```yaml
readinessProbe:
  httpGet:
    path: /healthz
    port: 8080
  periodSeconds: 3
livenessProbe:
  httpGet:
    path: /healthz
    port: 8080
  periodSeconds: 5
  failureThreshold: 2      # two misses in a row → restart
```

![Requests, limits and the three probes in one picture](content/kubernetes/images/11-resources-and-probes.svg)

---

## Lab: Overload It, Starve It, Heal It 🛠️

### 1. A pod that can't be placed

Jim asked for a node with 100 CPU cores. Save as `huge.yaml`:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: huge
spec:
  containers:
    - name: app
      image: port-app:v1
      resources:
        requests:
          cpu: "100"
```

```bash
kubectl apply -f huge.yaml
kubectl get pod huge
kubectl describe pod huge | tail -8
```

It sits in `Pending`, and the Events say something like **`0/3 nodes are available: 3 Insufficient cpu`** (the control-plane node may also be reported as having an untolerated taint). The scheduler filtered every node out and told you exactly why. See what the nodes actually have:

```bash
kubectl describe node port-worker | grep -A8 "Allocated resources"
```

Clean up: `kubectl delete pod huge`.

### 2. Cause an OOMKill

Save as `limited.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: limited
spec:
  replicas: 1
  selector:
    matchLabels:
      app: limited
  template:
    metadata:
      labels:
        app: limited
    spec:
      containers:
        - name: app
          image: port-app:v1
          ports:
            - containerPort: 8080
          resources:
            requests:
              cpu: "50m"
              memory: "64Mi"
            limits:
              cpu: "500m"
              memory: "128Mi"
```

```bash
kubectl apply -f limited.yaml
kubectl rollout status deployment/limited
kubectl port-forward deployment/limited 9090:8080
```

In another terminal, ask the app to hold more memory than its 128 MiB limit:

```bash
curl localhost:9090/burn?mb=50
curl localhost:9090/burn?mb=200
```

The second call hangs or errors: the process got killed mid-request. Look:

```bash
kubectl get pods -l app=limited
kubectl describe pod -l app=limited | grep -A6 "Last State"
```

You'll see `RESTARTS: 1` and **`Last State: Terminated, Reason: OOMKilled`** (exit code 137). The kernel enforced the cgroup limit from Post 02, and the kubelet restarted the container. Memory limit exceeded, container killed. That's the rule from the table, live.

### 3. Add probes, then break the app on purpose

Replace `limited.yaml` with this version: two replicas, plus the readiness and liveness probes:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: limited
spec:
  replicas: 2
  selector:
    matchLabels:
      app: limited
  template:
    metadata:
      labels:
        app: limited
    spec:
      containers:
        - name: app
          image: port-app:v1
          ports:
            - containerPort: 8080
          resources:
            requests:
              cpu: "50m"
              memory: "64Mi"
            limits:
              cpu: "500m"
              memory: "128Mi"
          readinessProbe:
            httpGet:
              path: /healthz
              port: 8080
            periodSeconds: 3
          livenessProbe:
            httpGet:
              path: /healthz
              port: 8080
            periodSeconds: 5
            failureThreshold: 2
```

```bash
kubectl apply -f limited.yaml
kubectl rollout status deployment/limited
kubectl get pods -l app=limited
```

Wait for both pods to show `1/1`. Now make **one** pod unhealthy. Pick a pod and tunnel to it:

```bash
POD=$(kubectl get pods -l app=limited -o name | head -1)
kubectl port-forward $POD 9090:8080
```

In another terminal:

```bash
curl localhost:9090/break
```

and watch:

```bash
kubectl get pods -l app=limited --watch
```

What you'll see, in order:

1. Within a few seconds the broken pod's `READY` becomes **`0/1`**: the **readiness** probe fails (`/healthz` returns 500). It's pulled out of the Service's endpoints, so **no traffic goes to it**, yet it isn't restarted.
2. After two failed **liveness** checks (about 10 seconds), the container is **killed and restarted**. `RESTARTS` goes to 1, and it comes back healthy (the app's "broken" flag lived in memory and is gone).

Confirm the story in the Events:

```bash
kubectl describe ${POD} | tail -15
```

You'll see `Readiness probe failed` and then `Liveness probe failed ... will be restarted`.

### 4. Readiness keeps bad releases out

This is the missing piece from Post 06. Simulate a new version that *starts fine but never becomes ready* by pointing the readiness probe at a port nothing listens on:

```bash
kubectl patch deployment limited --type json -p \
  '[{"op":"replace","path":"/spec/template/spec/containers/0/readinessProbe/httpGet/port","value":9999}]'
kubectl rollout status deployment/limited --timeout=40s
kubectl get pods -l app=limited
```

The new pod is `Running` but never `READY`, so the rollout **stalls with the old pods still serving**. This is the same safety net as the image typo in Post 06, now for a pod that *starts fine and just isn't ready*. Undo it:

```bash
kubectl rollout undo deployment/limited
```

### 5. Optional: autoscale (HPA)

A **HorizontalPodAutoscaler** adds and removes replicas based on a measured metric. It needs the **metrics-server**, which doesn't come with kind. This is a good stretch exercise:

```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
kubectl patch -n kube-system deployment metrics-server --type=json \
  -p '[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
kubectl autoscale deployment limited --cpu-percent=50 --min=1 --max=5
kubectl get hpa --watch
```

(The `--kubelet-insecure-tls` flag is only acceptable for a local lab.) After a minute `kubectl top pods` works and the HPA shows current CPU relative to the *request* (`50m`), which is why requests matter here. Generate load with `curl localhost:9090/spin?s=30` in a few terminals and watch `REPLICAS` rise.

Clean up:

```bash
kubectl delete hpa limited
kubectl delete deployment limited
```

---

## Quick Quiz 🧠

**Q1.** A pod stays `Pending` with "Insufficient memory." What does that tell you about the scheduler's decision?

<details>
<summary>Show answer</summary>

Every node failed the **filter** step: none had enough *unrequested* memory to fit the pod's `requests`. The scheduler didn't try and fail. It determined no placement was possible.

</details>

**Q2.** What's the difference between a request and a limit?

<details>
<summary>Show answer</summary>

A **request** is what the scheduler reserves for the pod when choosing a node (a guaranteed minimum). A **limit** is the ceiling the kernel enforces at runtime.

</details>

**Q3.** A container hits its CPU limit; another hits its memory limit. What happens to each?

<details>
<summary>Show answer</summary>

CPU: **throttled**, so it runs slower but stays alive. Memory: **OOMKilled** and restarted, because memory can't be reclaimed from a running process.

</details>

**Q4.** A pod is `Running` but shows `0/1` READY and isn't receiving traffic. Which probe is failing, and will Kubernetes restart it?

<details>
<summary>Show answer</summary>

The **readiness** probe. A failing readiness probe only removes the pod from Service endpoints. It is **not** restarted. Only a failing **liveness** probe triggers a restart.

</details>

**Q5.** Why is a readiness probe essential for safe rolling updates?

<details>
<summary>Show answer</summary>

The Deployment waits for new pods to become *ready* before removing old ones. Without a readiness probe, "container started" counts as ready, so a broken-but-running new version would replace healthy old pods.

</details>

---

## What's Next? 🚀

You can now run workloads that are placed sensibly, limited, health-checked and self-healing. One thing remains before you can call this production-shaped: **who's allowed to do what**, and how do you keep teams' workloads separate from each other? Time to issue the access badges and put it all together.

👉 **[Post 12: Security and Capstone](content/kubernetes/12-security-and-capstone.md)**: namespaces, RBAC, security contexts, and one final deployment that uses everything.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
