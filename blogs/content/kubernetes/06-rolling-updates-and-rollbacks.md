---
title: "Rolling Updates and Rollbacks — Swapping Cargo Without Closing the Port"
date: 2026-11-06
tags: [kubernetes, deployments, rolling-update, rollback, maxsurge, maxunavailable, beginner]
description: Post 6 of the Kubernetes from First Principles series. How a Deployment replaces pods gradually, what maxSurge and maxUnavailable control, and a lab where you ship v2, ship a broken v3, and roll back.
---

# The Naive Way to Update 🙈

The old way to ship a new version: stop everything, replace it, start again. The port closes for a while. Customers see errors.

Better: replace containers **one at a time**. Bring a new one up, check it's alive, take an old one away, repeat. At every moment, most of the dock is still working. That's a **rolling update**, and it's the default behaviour of a Deployment.

---

## How a Rolling Update Works 🔄

This is where the ReplicaSet layer from Post 05 pays off. Suppose you change the image from `v1` to `v2`:

```text
Before:    ReplicaSet-v1 [●●●]
During:    ReplicaSet-v1 [●●○]   ReplicaSet-v2 [●]
           ReplicaSet-v1 [●○○]   ReplicaSet-v2 [●●]
After:     ReplicaSet-v1 [○○○]   ReplicaSet-v2 [●●●]
```

1. Changing the pod template (image, env, anything) creates a **new ReplicaSet** for the new version.
2. The Deployment **scales the new one up and the old one down**, in small steps.
3. The old ReplicaSet stays, at zero pods, **as history**. That's what makes rollback instant.

Two dials control the speed and safety:

| Setting | Meaning | Default |
|---|---|---|
| **`maxSurge`** | How many *extra* pods above `replicas` are allowed during the update | 25% |
| **`maxUnavailable`** | How many pods may be *missing* from the desired count | 25% |

With 3 replicas and the defaults, Kubernetes rounds `maxSurge` up (to 1) and `maxUnavailable` down (to 0). So it adds one new pod, waits for it to be ready, removes one old pod, and repeats. Capacity never drops below 3.

> **Key insight:** A rolling update only protects you if Kubernetes can tell whether the new pod is **ready**. Without a readiness check, "started" counts as "ready", so a pod that boots but is broken still receives traffic. In this post a *failure to start* will stop the rollout. In Post 11 we add readiness probes to catch *broken-but-running* pods.

---

## Never Reuse a Tag 🏷️

Kubernetes notices a change only if the **pod template** changes. If you rebuild `port-app:v1` with new code but keep the tag `v1`, the template is identical and nothing happens. And different nodes might even hold different cached copies of "v1." Use a new tag for every release (`v2`, `v3`, a git SHA), so the template changes and everyone runs the same bytes.

---

## Lab: Ship, Break, Roll Back 🛠️

### 1. Set up the Deployment

Use this version of the manifest, with the update strategy written out and a slightly slower pace so you can watch. Save as `web-deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
spec:
  replicas: 3
  minReadySeconds: 5            # a new pod must stay up 5s before it counts as available
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app: web
  template:
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

```bash
kubectl apply -f web-deployment.yaml
kubectl rollout status deployment/web
```

### 2. Build and load v2

In the folder with your Dockerfile from Post 02:

```bash
docker build --build-arg VERSION=v2 -t port-app:v2 .
kind load docker-image port-app:v2 --name port
```

### 3. Watch traffic during the update

Terminal A: watch the pods change:

```bash
kubectl get pods -l app=web --watch
```

Terminal B. Ship v2:

```bash
kubectl set image deployment/web app=port-app:v2
kubectl rollout status deployment/web
```

In Terminal A you'll see the dance: one new `web-<newhash>` pod appears `ContainerCreating` → `Running`, then an old one `Terminating`, three times. Never fewer than three running.

```bash
kubectl get replicaset -l app=web
```

Two ReplicaSets: the new one with 3 pods, the old one with **0 but still present**.

Confirm the version really changed. Port-forward to the Deployment and curl:

```bash
kubectl port-forward deployment/web 9090:8080
```

In another terminal: `curl localhost:9090` now says `version=v2`. (Stop the forward with `Ctrl+C`.)

### 4. Look at the history

```bash
kubectl rollout history deployment/web
kubectl rollout history deployment/web --revision=2
```

Each pod-template change is a numbered **revision**. Revision 2 shows `Image: port-app:v2`.

### 5. Ship a broken release

Jim built v3 carefully. Dave typed the tag by hand and got it wrong, an image that doesn't exist:

```bash
kubectl set image deployment/web app=port-app:v3-typo
kubectl rollout status deployment/web --timeout=30s
```

The status command waits, then times out. Look at what's happening:

```bash
kubectl get pods -l app=web
```

You'll see **three old (v2) pods still `Running`** and one new pod in `ErrImagePull` / `ImagePullBackOff`. Because `maxUnavailable: 0`, Kubernetes refuses to remove a working pod until the new one is ready, and the new one never will be. **The rollout is stuck, but your users are still being served by v2.** That's the safety net working.

```bash
kubectl describe deployment web | grep -A3 Conditions
```

### 6. Roll back

```bash
kubectl rollout undo deployment/web
kubectl rollout status deployment/web
kubectl get pods -l app=web
```

The bad pod disappears and you're back on v2 (revision 2's template becomes the new revision 4, so history keeps moving forward). To go to a specific revision: `kubectl rollout undo deployment/web --to-revision=1`.

### 7. Pause and resume (optional)

```bash
kubectl set image deployment/web app=port-app:v1
kubectl rollout pause deployment/web
kubectl rollout resume deployment/web
```

Pausing mid-rollout freezes the mix of old and new pods, so you can inspect before continuing.

---

## Quick Quiz 🧠

**Q1.** What does a Deployment create when you change the image, and what happens to the old one?

<details>
<summary>Show answer</summary>

A **new ReplicaSet** for the new template. The Deployment scales it up while scaling the old one down. The old ReplicaSet is kept at 0 replicas as **revision history**, which is what makes rollback quick.

</details>

**Q2.** With `replicas: 4`, `maxSurge: 1`, `maxUnavailable: 0`, what's the most pods that can exist at any moment during an update, and the fewest ready?

<details>
<summary>Show answer</summary>

Most: **5** (4 desired plus 1 surge). Fewest ready: **4**, since nothing may be unavailable.

</details>

**Q3.** The v3 rollout was stuck, yet users saw no errors. Why?

<details>
<summary>Show answer</summary>

With `maxUnavailable: 0`, Kubernetes won't remove an old pod until a new one is ready. The new pod could never start, so the old v2 pods kept serving. A failed rollout leaves the old version running.

</details>

**Q4.** You rebuild `port-app:v1` with new code and push it to the same tag. Why might nothing happen?

<details>
<summary>Show answer</summary>

The Deployment's pod template didn't change (same image name and tag), so no rollout starts. Nodes with the image cached won't re-pull it by default either. Always use a **new tag** per release.

</details>

**Q5.** Does `kubectl rollout undo` take you "back in time" to the old revision number?

<details>
<summary>Show answer</summary>

No. It applies the **old template** again as a *new* revision. Revision numbers only move forward, so you keep a complete history.

</details>

---

## What's Next? 🚀

Your pods now update safely, but there's a problem we've been dodging. Every time a pod is replaced, it gets a new IP. How does anything *find* them? How does a truck outside the port, or another service inside it, reach "the web app" when its containers keep changing places?

👉 **[Post 07: Services](content/kubernetes/07-services.md)**: a stable address in front of shifting pods, cluster DNS, and how a Service decides who's behind it.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
