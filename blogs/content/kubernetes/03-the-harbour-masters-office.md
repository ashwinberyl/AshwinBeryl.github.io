---
title: "The Harbour Master's Office — Control Plane and the Reconcile Loop"
date: 2026-11-06
tags: [kubernetes, control-plane, api-server, etcd, scheduler, controllers, kubelet, beginner]
description: Post 3 of the Kubernetes from First Principles series. The five components that make a cluster work, the reconcile loop at the heart of Kubernetes, and a lab where you watch a pod being scheduled event by event.
---

# Who Runs the Port? 🏢

A port doesn't run itself. There's an office with a front desk, a ledger, a berth planner and supervisors. Cranes do the lifting, but the *office* decides what gets lifted where.

Kubernetes has exactly that split:

- **Control plane**: the office. Decides and records.
- **Nodes**: the berths. Do the actual work.

In our kind cluster, `port-control-plane` is the office and `port-worker` and `port-worker2` are the berths.

---

## The Office, Desk by Desk 🗂️

| Port | Component | Job |
|---|---|---|
| **Front desk**: every request goes through it | **API server** | The only door in. Validates requests, stores them, tells others about changes. |
| **The ledger** | **etcd** | A small, reliable database holding the cluster's entire desired and actual state. |
| **Berth planner** | **Scheduler** | Looks at new, unassigned pods and picks a node for each. |
| **Supervisors** | **Controller manager** | Runs many controllers, each watching one kind of thing and fixing drift. |

And on **every node** there's a crane operator:

| Port | Component | Job |
|---|---|---|
| **Crane operator** | **kubelet** | Takes assignments for its node, starts and stops containers, reports status back. |
| **Local signaller** | **kube-proxy** | Maintains the network rules that make Services work (Post 07). |

Notice the design: **nobody talks to anybody directly.** The scheduler doesn't call the kubelet. The kubelet doesn't call the scheduler. Everyone reads from and writes to the **API server**, which keeps the ledger. It's a bulletin board, not a phone tree.

---

## The Reconcile Loop: The One Idea ♻️

Every controller does the same thing, forever:

```text
loop:
    desired = what the ledger says should exist
    actual  = what really exists
    if desired != actual:
        take a small step to close the gap
```

That's it. There's no "run this deployment script." There are only loops comparing two things.

Here's what happens when you ask for a pod:

1. You send a request to the **API server**. It writes it to **etcd**. At this moment the pod exists *in the ledger* but nowhere else, with no node assigned.
2. The **scheduler** is watching for pods with no node. It picks one (say `port-worker`) and writes that decision back.
3. The **kubelet** on `port-worker` is watching for pods assigned to *its* node. It sees one, pulls the image, starts the container, and writes the status back.
4. You ask "what's running?" and the API server reads the ledger.

> **Key insight:** Because everything is "watch, compare, fix," Kubernetes heals itself naturally. If a container dies, the kubelet notices actual ≠ desired and starts a new one. Nothing special happens. It's the same loop running again.

---

## What `kubectl` Really Does 🔍

`kubectl` isn't magic: it makes HTTP calls to the API server. You can see them:

```bash
kubectl get pods -v=6
```

Among the lines you'll see something like `GET https://127.0.0.1:xxxxx/api/v1/namespaces/default/pods`. That's the entire "command": an HTTP GET. Everything in Kubernetes is a **resource** (pods, services, nodes…) in a REST API, and `kubectl` is a friendly client for it.

---

## Lab: Watch the Office at Work 🛠️

This assumes the `port` cluster from Post 01 is running.

### 1. Find the control plane's own components

```bash
kubectl get pods -n kube-system -o wide
```

You'll see (names have suffixes): `etcd-port-control-plane`, `kube-apiserver-port-control-plane`, `kube-scheduler-port-control-plane`, `kube-controller-manager-port-control-plane`, plus one `kube-proxy-…` per node and `coredns-…`. The office is itself running as pods. Kubernetes runs on Kubernetes.

Look at the `NODE` column: the control-plane pieces are on `port-control-plane`, and `kube-proxy` appears on all three nodes.

### 2. Open two terminals

**Terminal A**: watch events as they happen:

```bash
kubectl get events --watch
```

**Terminal B**: ask for a pod. Create `hello-pod.yaml`:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: hello
spec:
  containers:
    - name: app
      image: port-app:v1
```

```bash
kubectl apply -f hello-pod.yaml
```

### 3. Read the story

In Terminal A, you'll see something like:

```text
Scheduled   pod/hello   Successfully assigned default/hello to port-worker
Pulled      pod/hello   Container image "port-app:v1" already present on machine
Created     pod/hello   Created container app
Started     pod/hello   Started container app
```

Match each line to the cast:

- **Scheduled** was the **scheduler** (berth planner) choosing `port-worker`.
- **Pulled / Created / Started** were the **kubelet** (crane operator) on that node.

Notice `already present on machine`. That's the `kind load` from Post 02 paying off.

Press `Ctrl+C` to stop the watch. Then:

```bash
kubectl get pod hello -o wide
```

### 4. Read the ledger entry

```bash
kubectl get pod hello -o yaml | head -60
```

Find two things:

- `spec:`, **what you asked for** (desired state).
- `status:`, **what the cluster reports** (actual state): phase, container state, pod IP, which node.

You write `spec`. The system writes `status`. The reconcile loop is the machinery that makes them agree.

### 5. Peek inside a node

Who actually runs your container? Remember, a node is a Docker container, so you can look inside it:

```bash
docker exec port-worker crictl ps
docker exec port-worker2 crictl ps
```

(Use whichever node your pod landed on.) You'll see `app` among the containers. **Kubernetes runs containers via a *container runtime***, and kind's nodes use `containerd`, with `crictl` as its client. Docker isn't even involved inside the node.

Clean up:

```bash
kubectl delete pod hello
```

---

## Quick Quiz 🧠

**Q1.** You run `kubectl apply -f pod.yaml`. Which component first sees the pod, and where is it stored?

<details>
<summary>Show answer</summary>

The **API server** receives it and stores it in **etcd**. Every other component learns about it from the API server.

</details>

**Q2.** Does the scheduler start containers?

<details>
<summary>Show answer</summary>

No. The scheduler only **chooses a node** and records that choice. The **kubelet** on that node starts the containers.

</details>

**Q3.** A container on a worker node crashes. Which component notices, and why doesn't Kubernetes need special "self-healing" code?

<details>
<summary>Show answer</summary>

The **kubelet** notices (it watches its node's containers). There's no special code: it's the normal reconcile loop. Desired state says "this container should be running", actual state says it isn't, so the loop restarts it.

</details>

**Q4.** In a pod's YAML, what's the difference between `spec` and `status`?

<details>
<summary>Show answer</summary>

`spec` is the **desired state**, which you write. `status` is the **observed actual state**, which the system writes. Controllers work to make `status` match `spec`.

</details>

**Q5.** Why is it a good design that components talk through the API server instead of calling each other directly?

<details>
<summary>Show answer</summary>

Each component can fail, restart or be replaced independently and simply re-read the current state from the API server. There's one source of truth, no tangled web of direct connections, and you can add new controllers without changing the old ones.

</details>

---

## What's Next? 🚀

We just created a pod by hand and deleted it, and nothing brought it back. That's the clue that a bare pod is only half the story. What *is* a pod, exactly, and why isn't it just a container? Time to open one up and break it on purpose.

👉 **[Post 04: Pods](content/kubernetes/04-pods.md)**: the smallest unit in Kubernetes, how containers in one pod share a network, and how to debug a pod that won't start.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
