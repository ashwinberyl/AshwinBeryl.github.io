---
title: "Services — A Stable Address for Shifting Containers"
date: 2026-11-06
tags: [kubernetes, services, clusterip, nodeport, dns, endpoints, kube-proxy, beginner]
description: Post 7 of the Kubernetes from First Principles series. Why pod IPs can't be trusted, how a Service gives pods a stable name and load-balances across them, and a lab exploring ClusterIP, DNS, endpoints and NodePort.
---

# The Address Problem 📮

By now you've seen pods come and go, each with a fresh IP. So how does anything find them?

Imagine the port's customers having to track which berth each container is on. Container 42 was at Berth 3 yesterday, but today it's at Berth 7 because a crane broke. Impossible.

The port solves this with an **address that doesn't move**: "Warehouse Web." Send a truck there and the port forwards it to *whichever matching container is currently alive*.

In Kubernetes that's a **Service**.

---

## What a Service Is 🧭

A Service is:

1. A **stable virtual IP** and **DNS name** that never changes while the Service exists.
2. A **label selector** (the same idea as Post 05) saying which pods are "behind" it.
3. A **load balancer** that spreads connections across the healthy ones.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: port-app
spec:
  selector:
    app: web            # forward to pods carrying this label
  ports:
    - port: 80          # the Service's port (what callers use)
      targetPort: 8080  # the pod's port (where the app listens)
```

**Callers use `port`, the app listens on `targetPort`.** They don't have to match.

### How does it track pods?

Kubernetes keeps a live list of the ready pods matching the selector, stored as **EndpointSlices**. When a pod is created, dies, or becomes unready, the list updates. On every node, **kube-proxy** (Post 03) programs network rules so traffic to the Service IP is redirected to one of the listed pod IPs.

> **Key insight:** A Service isn't a process. There's no little proxy server sitting there. It's a *rule* on every node. That's why it's fast and why it keeps working even if individual pods vanish.

---

## Four Types of Address 🏷️

| Type | Reachable from | Analogy |
|---|---|---|
| **ClusterIP** (default) | Inside the cluster only | An internal extension number |
| **NodePort** | Outside, via any node's IP and a high port (30000-32767) | A side door cut in each berth wall |
| **LoadBalancer** | Outside, via a cloud load balancer | A public front desk (needs a cloud provider) |
| **ExternalName** | A DNS alias to an external name | A forwarding note |

ClusterIP is what you'll use most. In Post 08 we'll put **Ingress** in front of ClusterIP Services, which is how real HTTP traffic enters.

---

## DNS: Names, Not IPs 📛

Kubernetes runs a DNS server (CoreDNS; you saw it in Post 03). Every Service gets a name:

```text
<service>.<namespace>.svc.cluster.local
```

Inside the same namespace you can use just `port-app`. From another namespace, `port-app.default`. Apps call each other **by name** and never touch an IP.

---

## Lab: Give the Web App an Address 🛠️

### 1. Start the Deployment

Use the Deployment from Post 06 (or the simple one from Post 05) with `image: port-app:v1`:

```bash
kubectl apply -f web-deployment.yaml
kubectl rollout status deployment/web
```

### 2. Create a Service

Save as `web-service.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: port-app
spec:
  selector:
    app: web
  ports:
    - port: 80
      targetPort: 8080
```

```bash
kubectl apply -f web-service.yaml
kubectl get service port-app
```

You'll see a `CLUSTER-IP` (like `10.96.x.x`). That's the virtual address.

### 3. See who's behind it

```bash
kubectl get endpointslices -l kubernetes.io/service-name=port-app
kubectl get pods -l app=web -o wide
```

The endpoints list the **same IPs** as your three pods.

### 4. Call it by name, and watch the load balancing

Services are only reachable from inside the cluster, so run a throwaway pod to be the "caller":

```bash
kubectl run tmp --rm -it --image=busybox:1.36 --restart=Never -- sh
```

Inside that shell:

```sh
wget -qO- http://port-app
for i in 1 2 3 4 5 6 7 8; do wget -qO- http://port-app; done
```

Each line shows a `pod=` name. You'll see **different pods answering**, roughly randomly. (Short bursts can look uneven; kube-proxy picks per *connection*, not strictly in turn.) Also try `wget -qO- http://port-app.default.svc.cluster.local`. Same answer, full name. Type `exit` to leave.

### 5. Prove the address is stable

Open a watch on the endpoints, then kill pods:

```bash
kubectl get endpointslices -l kubernetes.io/service-name=port-app --watch
```

In another terminal:

```bash
kubectl delete pods -l app=web
```

The **endpoint IPs change** as pods are replaced, but `kubectl get service port-app` shows the **same CLUSTER-IP** throughout. Callers never noticed.

### 6. Reach it from your laptop

```bash
kubectl port-forward service/port-app 9090:80
```

`curl localhost:9090` works. (Again: a debugging tunnel.)

### 7. NodePort: the side door

Change the Service type. Save as `web-nodeport.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: port-app-nodeport
spec:
  type: NodePort
  selector:
    app: web
  ports:
    - port: 80
      targetPort: 8080
      nodePort: 30080
```

```bash
kubectl apply -f web-nodeport.yaml
kubectl get nodes -o wide
```

Note a worker's `INTERNAL-IP`. From a throwaway pod, use it:

```bash
kubectl run tmp --rm -it --image=busybox:1.36 --restart=Never -- wget -qO- http://<worker-internal-ip>:30080
```

Every node listens on 30080 and forwards to the same pods, no matter which node the pods are on. (We haven't mapped 30080 to your laptop in this lab, which is why we test it from inside. On a real cluster you'd reach it at a node's public IP, and in the real world you'd use Ingress or a LoadBalancer instead.)

### 8. What happens if nothing matches?

```bash
kubectl delete deployment web
kubectl get endpointslices -l kubernetes.io/service-name=port-app
```

The Service still exists, with its IP, but has **no endpoints**. Calls fail. A Service doesn't care whether anyone's home. Clean up:

```bash
kubectl delete service port-app port-app-nodeport
```

---

## Quick Quiz 🧠

**Q1.** Why can't you point other services at pod IPs directly?

<details>
<summary>Show answer</summary>

Pod IPs belong to individual pod instances. When a pod is replaced, rescheduled or scaled, its IP changes or disappears. A Service gives a stable address that always forwards to the *current* set.

</details>

**Q2.** In `port: 80` / `targetPort: 8080`, which does a caller use and which does the app listen on?

<details>
<summary>Show answer</summary>

Callers use `port` (80) on the Service. The app listens on `targetPort` (8080) inside the pod.

</details>

**Q3.** How does a Service know which pods to send traffic to?

<details>
<summary>Show answer</summary>

Its **label selector** matches pods; the ready ones are listed in **EndpointSlices**, which Kubernetes keeps updated as pods come and go. kube-proxy turns that list into forwarding rules on each node.

</details>

**Q4.** A Service shows a `CLUSTER-IP` but calls to it hang, and the endpoints list is empty. What are the two most likely causes?

<details>
<summary>Show answer</summary>

Either the **selector doesn't match** any pod's labels (typo in `app: web`), or there are **no ready pods** (all crashed, still starting, or failing readiness checks).

</details>

**Q5.** What's the difference between `ClusterIP` and `NodePort`?

<details>
<summary>Show answer</summary>

`ClusterIP` is reachable only from inside the cluster. `NodePort` additionally opens the same high port on every node so traffic from outside can reach the Service via a node's IP.

</details>

---

## What's Next? 🚀

Services give us stable addresses *inside* the port. But real customers arrive by road, over HTTP, asking for `/cargo` or `/passengers`, and you don't want a NodePort per service. You want one **main gate** that reads the destination and sends each truck to the right place.

👉 **[Post 08: Ingress](content/kubernetes/08-ingress.md)**: the main gate. Install an ingress controller and route two apps by path.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
