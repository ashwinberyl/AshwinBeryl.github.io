---
title: "Why Kubernetes Exists — From One Ship to a Busy Port"
date: 2026-11-06
tags: [kubernetes, first-principles, containers, orchestration, kind, beginner]
description: The first post in the Kubernetes from First Principles series. What problem orchestration solves, the container-port analogy that runs through all 12 posts, and a three-node local cluster you build in ten minutes.
---

# Why This Series Exists ⚓

Most Kubernetes tutorials start with a wall of YAML. You copy it, it runs, and you still couldn't explain what just happened or why it was built that way.

This series starts from the problem instead. Every Kubernetes object we meet shows up only because something went wrong without it. And we'll use **one analogy for all 12 posts**: a busy **container port**.

By the end you'll be able to read a manifest, predict what the cluster will do with it, and debug it when it doesn't.

| Part | Posts | What you learn |
|---|---|---|
| **Part 1: The Port** | 01 – 03 | Why orchestration exists, what a container really is, how the control plane thinks |
| **Part 2: The Workloads** | 04 – 06 | Pods, Deployments, rolling updates and rollbacks |
| **Part 3: The Traffic** | 07 – 08 | Services and Ingress |
| **Part 4: The Cargo** | 09 – 10 | Configuration, Secrets, and storage |
| **Part 5: Running It for Real** | 11 – 12 | Scheduling, resources, probes, security, and a capstone |

Every post ends with a **hands-on lab** on your own laptop (free, no cloud account) and a short quiz with full answers.

---

## The Problem: One Ship Is Easy, a Port Is Not 🚢

Imagine you run one ship. You know the captain, you know where every container is, and if something breaks you walk down the dock and fix it.

Now imagine a port handling thousands of containers a day, from hundreds of shippers, on dozens of berths. Suddenly you have questions nobody asks about a single ship:

- **Where does this container go?** Which berth has room?
- **What if a crane breaks?** Who notices, and who moves the cargo?
- **What if demand triples on Monday?** Who adds capacity, and who removes it on Tuesday?
- **How do you replace a cargo type without closing the port?**
- **How does a truck find the right container** when containers keep moving?

Software went through the same growth. One app on one server is a ship. A modern system is dozens of small services, each running many copies, across many machines, changing several times a day. Doing that by hand, over SSH, doesn't scale.

---

## What Kubernetes Actually Is 🧭

**Kubernetes is the port authority.** You don't tell it *how* to do things step by step. You hand it a **standing order** describing what you want:

> "Keep three copies of the web app running. If one dies, replace it. When I ship a new version, swap them gradually."

Kubernetes then works continuously to make reality match that order. This is the single most important idea in the whole series, so here it is in one line:

> **Kubernetes is a system that compares *desired state* with *actual state* and keeps closing the gap.**

You'll hear this called **declarative** configuration (you declare the outcome) versus **imperative** (you issue commands). A shell script says "start a process." A Kubernetes manifest says "there should be three of these."

---

## The Port Map 🗺️

Here's the full analogy. Don't memorise it. Each row gets its own post, and you'll see it again and again.

| Port | Kubernetes | Post |
|---|---|---|
| A shipping container | **Container** (app plus everything it needs) | 02 |
| The harbour master's office | **Control plane** | 03 |
| A berth with a crane | **Node** (a machine that runs containers) | 03 |
| One container (or a tightly bound pair) on the dock | **Pod** | 04 |
| A standing order ("always keep 3 of X") | **Deployment** | 05 |
| Swapping cargo without closing the port | **Rolling update** | 06 |
| A port address that finds whichever container is alive | **Service** | 07 |
| The main gate that routes trucks by destination | **Ingress** | 08 |
| Customs paperwork and locked cargo | **ConfigMap and Secret** | 09 |
| The warehouse that outlives any container | **Volumes** | 10 |
| Berth planning and weight limits | **Scheduler, requests, limits** | 11 |
| Access badges and separate terminals | **RBAC and Namespaces** | 12 |

Two dockworkers, **Jim** and **Dave**, will show up in the stories. Jim is careful and checks everything twice. Dave likes shortcuts. You can guess who gets into trouble.

---

## Lab: Build Your Own Port 🛠️

We'll use **kind** ("Kubernetes IN Docker"), which runs a whole cluster as Docker containers on your laptop. It's free and disposable.

### 1. Install the tools

You need three things:

- **Docker** (Docker Desktop on Mac/Windows, Docker Engine on Linux)
- **kubectl**, the command-line client for talking to a cluster
- **kind**

Install instructions change, so use the official pages: [Docker](https://docs.docker.com/get-docker/), [kubectl](https://kubernetes.io/docs/tasks/tools/), [kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation). Then check:

```bash
docker version --format '{{.Server.Version}}'
kubectl version --client
kind version
```

### 2. Describe the port

Create `kind-port.yaml`. It asks for one control-plane node and two worker nodes, and opens a door from your laptop's port 8080 into the cluster. We'll use that door in Post 08.

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    kubeadmConfigPatches:
      - |
        kind: InitConfiguration
        nodeRegistration:
          kubeletExtraArgs:
            node-labels: "ingress-ready=true"
    extraPortMappings:
      - containerPort: 80
        hostPort: 8080
        protocol: TCP
  - role: worker
  - role: worker
```

Notice something already: this file is *declarative*. You didn't say "start three containers and connect them." You described the shape you want.

### 3. Build it

```bash
kind create cluster --name port --config kind-port.yaml
```

This takes a minute or two. When it finishes:

```bash
kubectl cluster-info --context kind-port
kubectl get nodes
```

Expected output (ages and versions will differ):

```text
NAME                 STATUS   ROLES           AGE   VERSION
port-control-plane   Ready    control-plane   60s   v1.xx.x
port-worker          Ready    <none>          40s   v1.xx.x
port-worker2         Ready    <none>          40s   v1.xx.x
```

Three berths. One is the harbour master's office, two are working berths with cranes.

### 4. See that it's just containers

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}'
```

You'll see three containers named `port-control-plane`, `port-worker`, and `port-worker2`. Each *is* a node. The "machines" in your port are Docker containers pretending to be servers.

> **Keep this cluster.** Every lab in the series builds on it. If you ever want to start fresh: `kind delete cluster --name port`.

---

## Quick Quiz 🧠

**Q1.** In one sentence, what does "declarative" mean, and how is it different from running a shell script?

<details>
<summary>Show answer</summary>

You describe the **end state** you want ("three copies running") and the system works out the steps. A script lists the **steps** and has no idea whether the end state is still true five minutes later. Kubernetes keeps re-checking and repairing; a script runs once.

</details>

**Q2.** Your app crashes at 3 a.m. with no Kubernetes in the picture. Name two things that must happen for it to come back, and who does them.

<details>
<summary>Show answer</summary>

Someone (or something) must **notice** it's down, and then **restart** it on a healthy machine. Without orchestration that's a person with a pager, or a hand-written script. Kubernetes makes noticing and restarting a built-in, continuous job.

</details>

**Q3.** In the port analogy, what are the control plane and a node?

<details>
<summary>Show answer</summary>

The **control plane** is the harbour master's office: it holds the orders and decides what should happen. A **node** is a berth with a crane: a machine that actually runs the containers.

</details>

**Q4.** After `kind create cluster`, `docker ps` shows three containers. What does that tell you about how kind works?

<details>
<summary>Show answer</summary>

Each Kubernetes **node is itself a Docker container**. kind fakes a multi-machine cluster on one computer, which is why it's cheap and disposable. Real clusters use real or virtual machines.

</details>

---

## What's Next? 🚀

We keep saying "container" as if you know exactly what one is. Do you? Why can the *same* app run on your laptop, a colleague's Mac and a cloud server without changes? Before we can orchestrate containers, we need to know what we're actually moving around the port.

👉 **[Post 02: Containers, the Shipping Container](content/kubernetes/02-containers-the-shipping-container.md)**: what's really inside a container, why it isn't a tiny VM, and you'll build one yourself.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
