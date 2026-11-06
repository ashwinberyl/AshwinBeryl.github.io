---
title: "Containers: The Shipping Container Inside the Port"
date: 2026-11-06
tags: [kubernetes, containers, docker, namespaces, cgroups, images, beginner]
description: Post 2 of the Kubernetes from First Principles series. What a container really is (a process with blinders and a budget), why images are layered, and a hands-on build of the small app we'll deploy for the rest of the series.
---

# Why Containers Come First 📦

Before shipping containers, cargo was loaded piece by piece: barrels, sacks, crates, all different shapes. Every port, crane and truck needed special handling for every cargo type. The **standard steel container** fixed that. Same box, same size, same hooks. A crane doesn't care what's inside.

Software had the same mess: "it works on my machine." Different servers have different libraries, different versions, different settings. A **container** is the standard box: your app plus everything it needs, sealed, identical everywhere.

Kubernetes doesn't run your code. It moves **containers** around. So we need to know exactly what one is.

---

## A Container Is Not a Tiny VM 🧱

A virtual machine pretends to be a whole computer, with its own kernel. A container doesn't. A container is **just a normal process on the host's Linux kernel**, with two tricks applied:

| Trick | Linux feature | The port analogy |
|---|---|---|
| **Blinders**: the process can only *see* its own stuff | **Namespaces** | The container has walls: it sees only its own contents, not the ship next to it |
| **A budget**: the process can only *use* so much | **cgroups** | A weight limit painted on the side: so much CPU, so much memory |

Namespaces hide things: other processes, the host's network, the host's file system. cgroups limit things: CPU time and memory. Put them together and you have a container.

> **Key insight:** Because containers share the host's kernel, they start in milliseconds and cost almost nothing, but they're also less isolated than VMs. Remember this in Post 12 when we talk security.

![A container is an ordinary process limited by namespaces and cgroups on a shared kernel](content/kubernetes/images/02-container-anatomy.svg)

---

## Images: The Packing List 📋

A **container image** is the sealed, read-only template. A **container** is a running instance of it, like a class and an object.

Images are built in **layers**, each one a change on top of the previous:

```text
Layer 4:  your app code (app.py)
Layer 3:  your settings
Layer 2:  Python runtime
Layer 1:  a minimal Linux file system
```

Layers are cached and shared. If ten images start from the same Linux layer, it's stored once. Change only your app code and only the top layer is rebuilt and re-shipped. That's why rebuilds take seconds.

Images are identified by `name:tag`, like `port-app:v1`. The tag is just a label, and (as we'll see in Post 6) **you should never reuse a tag for different content**.

---

## Lab: Build the Cargo 🛠️

Throughout this series we'll ship one small web app. It's deliberately simple, but it has a few extra endpoints that let us *cause* problems on demand (crashes, memory hogs, unhealthy states) so we can watch Kubernetes react.

### 1. Make a folder and save two files

Download [app.py](https://ashwinberyl.github.io/blogs/content/kubernetes/lab/app.py) and [Dockerfile](https://ashwinberyl.github.io/blogs/content/kubernetes/lab/Dockerfile), or create them yourself.

**`Dockerfile`**

```dockerfile
FROM python:3.12-slim
ARG VERSION=v1
ENV VERSION=$VERSION \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY app.py .
EXPOSE 8080
USER 10001
CMD ["python", "-u", "app.py"]
```

Read it top to bottom as the packing list: start from a Python layer, record the version, copy in the app, run as a non-root user, start the server.

**`app.py`**: the full file is in the download link above. What matters for now:

| Endpoint | What it does | Used in |
|---|---|---|
| `/` | Replies with a greeting, the **pod name** and the **version** | everywhere |
| `/healthz` | `200 ok` normally; `500` after `/break` | Post 11 |
| `/break` | Makes `/healthz` fail | Post 11 |
| `/secret` | Reports whether `SECRET_TOKEN` is set (never shows it) | Post 9 |
| `/visit` | Appends a line to `/data/visits.log` and returns the count | Post 10 |
| `/burn?mb=N` | Allocates N MiB of memory and holds it | Post 11 |
| `/spin?s=N` | Burns CPU for N seconds | Post 11 |

### 2. Build the image

```bash
docker build -t port-app:v1 .
```

Watch the output: each instruction (`FROM`, `ENV`, `COPY`…) becomes a layer. Run it a second time and you'll see `CACHED` on every step.

### 3. Run it

```bash
docker run --rm -d --name port-test -p 9090:8080 port-app:v1
curl localhost:9090
```

Expected:

```text
Hello from the port | pod=3f2a9c1b7d4e | version=v1
```

The `pod=` value is the container's hostname, which is just its short ID. Remember that. In Kubernetes it becomes the pod's name and lets us see *which copy* answered.

### 4. Look at the blinders

```bash
docker exec port-test sh -c 'ls /proc | grep -E "^[0-9]+$"'
docker exec port-test cat /proc/1/cmdline | tr '\0' ' '; echo
```

The first command lists the process IDs the container can see: just a handful of low numbers. The second shows that **PID 1 is your app** (`python -u app.py`). Inside its own world, the app thinks it was the first process on the machine and that nothing else exists. That's the PID **namespace** at work. (We use `/proc` because the slim Python image doesn't ship the `ps` tool.) Compare with the host:

```bash
ps aux | grep "app.py" | head -3
```

On Linux you'll find the very same process, with a different ID, in the host's list. (On Mac/Windows it lives inside Docker's hidden VM, so you won't see it.) It was never a separate computer, just a process with blinders.

### 5. Feel the budget

```bash
docker rm -f port-test
docker run --rm -d --name port-test -m 64m -p 9090:8080 port-app:v1
docker inspect port-test --format '{{.HostConfig.Memory}}'
docker rm -f port-test
```

`-m 64m` set a **cgroup** memory limit of 64 MiB (printed in bytes: 67108864). Kubernetes will use this same mechanism in Post 11.

### 6. Hand the cargo to the port

Your kind nodes are Docker containers with their own image store, so they can't see images on your laptop's Docker. Load the image in:

```bash
kind load docker-image port-app:v1 --name port
```

In real clusters you'd push to a **registry** (Docker Hub, ECR, GHCR) and nodes would pull from it. Loading directly is the local-lab shortcut.

---

## Quick Quiz 🧠

**Q1.** What are the two Linux features that turn an ordinary process into a "container", and what does each do?

<details>
<summary>Show answer</summary>

**Namespaces** limit what the process can *see* (its own processes, network, file system). **cgroups** limit what it can *use* (CPU and memory).

</details>

**Q2.** Why does a container start in milliseconds while a VM takes much longer?

<details>
<summary>Show answer</summary>

A container is just a process on the host's existing kernel. A VM has to boot a whole separate operating system, kernel included.

</details>

**Q3.** You change one line in `app.py` and rebuild. Which layers are rebuilt, and why is it fast?

<details>
<summary>Show answer</summary>

Only the `COPY app.py` layer and everything after it. The base image and earlier layers come from cache, since Docker only re-runs a layer when its instruction or inputs change.

</details>

**Q4.** What's the difference between an image and a container?

<details>
<summary>Show answer</summary>

An image is the sealed, read-only template (the packing list plus contents). A container is a running instance created from it. You can start many containers from one image.

</details>

**Q5.** Why did we run `kind load docker-image`?

<details>
<summary>Show answer</summary>

kind's nodes are separate Docker containers with their own image storage. They can't see images on your laptop's Docker, so the image has to be copied in (or pulled from a registry).

</details>

---

## What's Next? 🚀

We have a sealed container and a three-node port. But who decides *which berth* it goes to? Who notices when a crane fails? Behind the scenes there's an office making those decisions, and it works on a surprisingly simple principle.

👉 **[Post 03: The Harbour Master's Office](content/kubernetes/03-the-harbour-masters-office.md)**: the control plane, the reconcile loop, and watching a pod get scheduled event by event.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
