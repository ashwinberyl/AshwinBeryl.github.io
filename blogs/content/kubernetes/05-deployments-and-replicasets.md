---
title: "Deployments and ReplicaSets — The Standing Order"
date: 2026-11-06
tags: [kubernetes, deployments, replicasets, self-healing, scaling, labels, beginner]
description: Post 5 of the Kubernetes from First Principles series. How a Deployment keeps a fixed number of pods alive, how labels connect the layers, and a lab where you kill pods and watch the port heal itself.
---

# The Order Nobody Forgets 📑

Dave once placed a container on the dock by hand, went to lunch, and a crane operator moved it out of the way. Nobody noticed until the customer called. A bare pod is Dave's container: if it disappears, it's gone for good.

What the port needs is a **standing order**, written down and checked continuously:

> "Always keep **three** containers of the web app on the dock. If one goes missing, put another out. Don't ask me."

In Kubernetes that standing order is a **Deployment**.

---

## Three Layers, Each With One Job 🧅

```text
Deployment   →   ReplicaSet   →   Pods
(the plan)       (the counter)     (the work)
```

| Layer | Port analogy | What it does |
|---|---|---|
| **Pod** | A container on the dock | Runs your app |
| **ReplicaSet** | The clerk with a tally counter | Ensures *exactly N* matching pods exist. Too few, create. Too many, delete. |
| **Deployment** | The standing order | Owns ReplicaSets. Handles updates and rollbacks (Post 06). |

You almost never create a ReplicaSet yourself. You create a Deployment, and it creates the ReplicaSet, which creates the pods. Why the extra layer? Because the Deployment needs *two* counters during an update (one for the old version, one for the new). That's Post 06.

![A Deployment owns a ReplicaSet, which keeps exactly N pods alive](content/kubernetes/images/05-deployment-layers.svg)

---

## Labels: How the Clerk Finds Its Containers 🏷️

How does the ReplicaSet know which pods are "its" pods? **Labels and selectors.**

```yaml
selector:
  matchLabels:
    app: web           # "count every pod with the label app=web"
template:
  metadata:
    labels:
      app: web         # stamp this label on every pod I create
```

The selector says *which pods count*. The template says *what to create*, including the label that makes the new pods match. These two **must agree**, or the Deployment is rejected.

> **Key insight:** The ReplicaSet doesn't track pods by name or by who created them. It counts whatever currently carries the label. Hold that thought. It explains a nice party trick in the lab.

---

## The Manifest, Line by Line 📜

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
spec:
  replicas: 3                  # desired state: three pods
  selector:
    matchLabels:
      app: web                 # which pods are mine
  template:                    # the blueprint for each pod
    metadata:
      labels:
        app: web
    spec:
      containers:
        - name: app
          image: port-app:v1
          ports:
            - containerPort: 8080
```

Everything under `template:` is just a pod spec, the same thing from Post 04. A Deployment is a pod spec plus a number.

---

## Lab: Kill Pods and Watch the Port Heal 🛠️

### 1. Place the standing order

Save as `web-deployment.yaml` (the YAML above), then:

```bash
kubectl apply -f web-deployment.yaml
kubectl get deployment,replicaset,pods -l app=web
```

You'll see one Deployment, one ReplicaSet (named `web-<hash>`), and three pods (named `web-<hash>-<suffix>`). The names nest: pod names are built from their parent's name.

```bash
kubectl get pods -l app=web -o wide
```

Check the `NODE` column. The scheduler (Post 03) spread them across your workers.

### 2. Kill one

Open a second terminal and watch:

```bash
kubectl get pods -l app=web --watch
```

In the first terminal, pick a pod name and delete it:

```bash
kubectl delete pod <one-of-the-web-pod-names>
```

In the watch window: the pod goes `Terminating`, and *almost immediately* a brand-new pod appears. The ReplicaSet saw "2 found, 3 desired" and created one. The reconcile loop from Post 03, in action.

### 3. Kill several at once

```bash
kubectl delete pods -l app=web
```

All three vanish. All three come back, with new names and new IPs. Remember: pods are mortal. The *order* is immortal.

### 4. Scale up and down

```bash
kubectl scale deployment web --replicas=6
kubectl get pods -l app=web
kubectl scale deployment web --replicas=2
kubectl get pods -l app=web
```

You changed the *desired count*, and the cluster did the rest. (The better habit is to edit `replicas:` in the YAML and `kubectl apply` again, so your file remains the source of truth.)

### 5. The party trick: label games

Because the ReplicaSet counts by label, not by "who made it", try this:

```bash
kubectl scale deployment web --replicas=3
POD=$(kubectl get pods -l app=web -o name | head -1)
kubectl label $POD app=quarantine --overwrite
kubectl get pods -l app=web
kubectl get pods -l app=quarantine
```

You removed one pod's `app=web` label. The ReplicaSet now sees only 2 matching pods and **creates a replacement**, while your relabelled pod keeps running, orphaned and ignored. You've just seen how engineers pull a misbehaving pod out of service *without destroying it*, so they can inspect it. Clean up the orphan:

```bash
kubectl delete pods -l app=quarantine
```

### 6. What owns what?

```bash
kubectl get pod -l app=web -o jsonpath='{.items[0].metadata.ownerReferences[0].kind}{"\n"}'
```

It prints `ReplicaSet`. Every pod records its owner, and deleting the Deployment cascades down:

```bash
kubectl delete deployment web
kubectl get replicaset,pods -l app=web
```

Everything is gone. Deleting the owner deletes what it owns.

### Stretch (optional): kill a whole berth

Re-apply the Deployment, then stop one worker:

```bash
kubectl apply -f web-deployment.yaml
docker stop port-worker2
kubectl get nodes --watch
```

After about 40 seconds the node shows `NotReady`. **Pods on it are not replaced immediately**: by default Kubernetes waits about five minutes (`tolerationSeconds: 300`) before evicting them, in case the node is just rebooting. Then replacements appear on the surviving worker. Bring it back with `docker start port-worker2`.

---

## Quick Quiz 🧠

**Q1.** Name the three layers from top to bottom and what each is responsible for.

<details>
<summary>Show answer</summary>

**Deployment** (the plan: owns updates and rollbacks) → **ReplicaSet** (keeps exactly N matching pods) → **Pods** (run the app).

</details>

**Q2.** A Deployment has `replicas: 3` and you delete one pod. Describe, step by step, why a new one appears.

<details>
<summary>Show answer</summary>

The ReplicaSet controller is in a reconcile loop. It counts pods matching its label selector, finds 2, compares to desired 3, and creates one pod from the template. The scheduler then assigns it a node and that node's kubelet starts it.

</details>

**Q3.** The selector says `app: web` but the template labels say `app: website`. What happens?

<details>
<summary>Show answer</summary>

The API server rejects the Deployment. The pods it creates wouldn't match its own selector, so it could never count them correctly.

</details>

**Q4.** You remove the `app=web` label from one running pod. What happens to that pod and to the replica count?

<details>
<summary>Show answer</summary>

The pod keeps running but is no longer counted. The ReplicaSet sees one fewer matching pod and creates a replacement, so there are briefly 4 pods running (3 matching plus the orphan). This is a standard way to quarantine a suspicious pod for debugging.

</details>

**Q5.** Why does a pod's name look like `web-5d8f7c9b6-x2k4q`?

<details>
<summary>Show answer</summary>

`web` is the Deployment, `5d8f7c9b6` is a hash of the pod template (which identifies the ReplicaSet), and `x2k4q` is a random suffix for the individual pod. The name records its ancestry.

</details>

---

## What's Next? 🚀

Self-healing is great, but your app will change: new version, new features, new bugs. How do you swap *every* container for a new one without closing the port, and what if the new cargo turns out to be rotten? That's where the ReplicaSet layer earns its keep.

👉 **[Post 06: Rolling Updates and Rollbacks](content/kubernetes/06-rolling-updates-and-rollbacks.md)**: replace cargo while the port stays open, and undo a bad release in one command.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
