---
title: "Pods: The Smallest Spot on the Dock"
date: 2026-11-06
tags: [kubernetes, pods, sidecar, debugging, kubectl, beginner]
description: Post 4 of the Kubernetes from First Principles series. Why the pod, not the container, is Kubernetes' smallest unit, how containers in one pod share a network, and how to debug the most common pod failures.
---

# The Smallest Thing You Can Place on the Dock 🚢

In Post 03 you created a pod, deleted it, and it stayed gone. We'll fix that in Post 05. First we need to know what a **pod** actually is.

You never ask Kubernetes to run "a container." You ask it to run **a pod**: a small group of one or more containers that are **always placed together, on the same node, and share things**.

**The analogy:** a pod is the **spot on the dock** where a container (or two tightly bound containers) sits. The port plans, moves and removes *spots*, not individual boxes.

---

## Why Not Just Containers? 🤔

Some programs need a helper right beside them: a log shipper reading the app's log file, a proxy handling its network traffic, a refresher that updates its config. They must:

- be on the **same machine**,
- talk over **localhost**,
- sometimes **share files**,
- **start and stop together**.

The pod gives all of that:

| Shared in a pod | Meaning |
|---|---|
| **Network** | One IP address. Containers reach each other on `localhost`. Two containers can't both bind the same port. |
| **Storage** (if you ask) | Volumes mounted into several containers (more in Post 10). |
| **Lifecycle** | Scheduled together, live and die together. |

Each container still has its own image, its own file system and its own resource limits.

Most pods hold **one** container. A second container is called a **sidecar**, and it's only worth adding when two things are truly inseparable.

> **A pod is mortal.** It gets an IP when it starts and loses it when it dies. A replacement pod gets a *different* IP. Remember this: it's why Services exist (Post 07).

![A pod holds containers that share one network and one lifecycle](content/kubernetes/images/04-pod-anatomy.svg)

---

## The Pod Manifest, Line by Line 📜

```yaml
apiVersion: v1          # which API group/version defines this kind
kind: Pod               # what are we creating
metadata:
  name: hello           # its name (unique in the namespace)
  labels:               # sticky notes: key/value tags used to find things later
    app: hello
spec:                   # DESIRED STATE
  containers:
    - name: app
      image: port-app:v1
      ports:
        - containerPort: 8080   # documentation; doesn't open anything by itself
```

Four top-level fields appear in nearly every Kubernetes object: `apiVersion`, `kind`, `metadata`, `spec`. Learn them once.

**Labels** deserve a mention now: they're the glue of Kubernetes. Deployments, Services and Ingress all find pods *by label*, not by name.

---

## Lab: Place It, Poke It, Break It 🛠️

### 1. Create a pod with a sidecar

Create `pod-sidecar.yaml`:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: dock-spot
  labels:
    app: dock-spot
spec:
  containers:
    - name: app
      image: port-app:v1
      ports:
        - containerPort: 8080
    - name: sidecar
      image: busybox:1.36
      command: ["sleep", "3600"]
```

```bash
kubectl apply -f pod-sidecar.yaml
kubectl get pod dock-spot
```

Wait for `READY 2/2`. The `2/2` means two containers, both running.

### 2. Prove they share a network

The sidecar never ran a web server. Yet:

```bash
kubectl exec dock-spot -c sidecar -- wget -qO- http://localhost:8080
```

You'll get the app's greeting. The sidecar reached the app container on `localhost`, because they live in the **same network namespace** (Post 02, namespaces again).

### 3. Reach it from your laptop

```bash
kubectl port-forward pod/dock-spot 9090:8080
```

In another terminal: `curl localhost:9090`. Press `Ctrl+C` to stop the forward. (`port-forward` is a debugging tunnel, not how you'd expose a real app. That's Posts 07 and 08.)

### 4. Read the logs

```bash
kubectl logs dock-spot -c app
```

Two containers means you must say which one with `-c`.

### 5. Break it: a wrong image

Create `pod-broken.yaml`:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: broken
spec:
  containers:
    - name: app
      image: port-app:v99
```

```bash
kubectl apply -f pod-broken.yaml
kubectl get pod broken
```

After a few seconds:

```text
NAME     READY   STATUS             RESTARTS   AGE
broken   0/1     ErrImagePull       0          10s
```

and then `ImagePullBackOff`. Kubernetes tries, fails, and waits longer between each retry (**back-off**). Find out *why*:

```bash
kubectl describe pod broken
```

Scroll to the **Events** section at the bottom. You'll see a failure to pull `port-app:v99` (the image doesn't exist, or you aren't allowed to pull it, which Kubernetes can't tell apart). **`describe` and its Events section are your first stop for any pod problem.**

Fix it: delete and recreate with the right tag.

```bash
kubectl delete pod broken
```

### 6. Break it differently: a crash

```bash
kubectl run crasher --image=busybox:1.36 --restart=Always -- sh -c 'echo "I am about to crash"; exit 1'
kubectl get pod crasher --watch
```

You'll see `CrashLoopBackOff` and a rising `RESTARTS` count. The container starts, exits, and the kubelet restarts it, each time waiting longer. Look at why:

```bash
kubectl logs crasher
kubectl logs crasher --previous
```

`--previous` shows the logs of the *last, dead* instance, which is often the only place the real error is.

### 7. The key moment

Delete the app pod and watch:

```bash
kubectl delete pod dock-spot
kubectl get pods
```

It doesn't come back. A bare pod is **not rebuilt** if you delete it, and if its node dies, it's gone. Pods are meant to be managed by something bigger. Clean up:

```bash
kubectl delete pod crasher
```

---

## Cheat Sheet: Reading Pod Status 🩺

| Status | Usually means | First command |
|---|---|---|
| `Pending` | Not scheduled yet, or image still pulling | `kubectl describe pod` |
| `ErrImagePull` / `ImagePullBackOff` | Wrong image name/tag or no access | `kubectl describe pod` (Events) |
| `CrashLoopBackOff` | The container starts then exits, repeatedly | `kubectl logs --previous` |
| `Running` but `0/1` ready | Running but not passing its readiness check | `kubectl describe pod` |
| `Completed` | Container finished successfully (normal for jobs) | n/a |

---

## Quick Quiz 🧠

**Q1.** Why is the pod, not the container, Kubernetes' smallest deployable unit?

<details>
<summary>Show answer</summary>

Some containers must be co-located, share a network and sometimes storage, and live and die together. The pod is that group. Kubernetes schedules and manages pods, not individual containers.

</details>

**Q2.** In `dock-spot`, the sidecar ran `wget http://localhost:8080` and reached the app. Why did `localhost` work?

<details>
<summary>Show answer</summary>

All containers in a pod share one **network namespace**, so they share the same IP and the same `localhost`. A port opened by one container is reachable by the others.

</details>

**Q3.** A pod shows `CrashLoopBackOff`. What are the first two commands you run?

<details>
<summary>Show answer</summary>

`kubectl logs <pod> --previous` (the last crashed instance's output) and `kubectl describe pod <pod>` (events, exit code, restart reason).

</details>

**Q4.** You delete a bare pod and it doesn't return. Why, and what does that imply for running real apps?

<details>
<summary>Show answer</summary>

Nothing is watching it. Something has to hold a *desired count* and recreate missing pods. For real apps, don't create bare pods; create a **Deployment** (Post 05) that manages them.

</details>

**Q5.** Why shouldn't you rely on a pod's IP address?

<details>
<summary>Show answer</summary>

The IP belongs to that pod instance. When it's replaced, the new pod gets a different IP. You need a stable address in front of changing pods. That's a **Service**.

</details>

---

## What's Next? 🚀

Pods die and stay dead. The fix is to give Kubernetes a *standing order*: "always keep three copies of this pod running." In the port, that's the most important document on the harbour master's desk.

👉 **[Post 05: Deployments and ReplicaSets](content/kubernetes/05-deployments-and-replicasets.md)**: the standing order, self-healing in action, and scaling up and down.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
