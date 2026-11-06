---
title: "Ingress — The Main Gate"
date: 2026-11-06
tags: [kubernetes, ingress, ingress-controller, routing, http, nginx, beginner]
description: Post 8 of the Kubernetes from First Principles series. Why Services alone aren't enough for public HTTP traffic, how an Ingress and its controller work together, and a lab that routes two apps through one gate by URL path.
---

# One Gate, Many Destinations 🚪

You have three apps: cargo handling, passenger services and a customs office. Each has a Service. How do outside visitors reach them?

Giving each its own NodePort or cloud load balancer means a different port or a separate bill per app. The port's answer is a **main gate**: one entrance, with a guard who reads the destination on each truck and points it the right way.

> `GET /cargo` → cargo app
> `GET /passengers` → passenger app

That's **Ingress**.

---

## Two Pieces, Not One ⚙️

This trips up almost everyone, so read it twice:

| Piece | What it is | Analogy |
|---|---|---|
| **Ingress** (resource) | A *rule set* you write: "paths and hosts → Services" | The written gate instructions |
| **Ingress controller** | A *running program* that reads those rules and does the routing | The guard who follows the instructions |

**Kubernetes ships the first, but not the second.** If you create an Ingress and no controller is installed, nothing happens. The rules sit there and no guard reads them. Popular controllers: ingress-nginx, Traefik, HAProxy, and cloud-provided ones.

The controller itself is just a pod (a reverse proxy like nginx) that **watches the API server** for Ingress resources and reconfigures itself, the reconcile loop again.

```text
Browser ──► gate (controller pod) ──► Service ──► Pods
              reads Ingress rules
```

![An ingress controller routes URL paths to Services](content/kubernetes/images/08-ingress.svg)

---

## An Ingress, Line by Line 📜

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: port-gate
spec:
  ingressClassName: nginx          # which controller should handle this
  rules:
    - http:
        paths:
          - path: /cargo
            pathType: Prefix       # matches /cargo, /cargo/anything
            backend:
              service:
                name: cargo
                port:
                  number: 80
          - path: /passengers
            pathType: Prefix
            backend:
              service:
                name: passengers
                port:
                  number: 80
```

Rules can also match on **host** (`host: shop.example.com`), and can terminate **TLS** (HTTPS). We'll stick to paths for this lab.

---

## Lab: Build the Gate 🛠️

Remember the `extraPortMappings` in the cluster config from Post 01? Your laptop's port **8080** forwards to port 80 on the control-plane node. We'll put the gate there.

### 1. Install the ingress controller

kind documents an install tuned for its clusters:

```bash
kubectl apply -f https://kind.sigs.k8s.io/examples/ingress/deploy-ingress-nginx.yaml
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=120s
```

(This pulls from the internet, so it needs a moment. If the URL ever moves, check kind's [Ingress guide](https://kind.sigs.k8s.io/docs/user/ingress/).) Look at what you installed:

```bash
kubectl get pods -n ingress-nginx
kubectl get ingressclass
```

One controller pod, and an `nginx` IngressClass.

### 2. Two apps, two greetings

We'll reuse one image and tell each Deployment to greet differently, using an environment variable (a preview of Post 09). Save as `two-apps.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cargo
spec:
  replicas: 2
  selector:
    matchLabels:
      app: cargo
  template:
    metadata:
      labels:
        app: cargo
    spec:
      containers:
        - name: app
          image: port-app:v1
          env:
            - name: GREETING
              value: "Welcome to CARGO"
          ports:
            - containerPort: 8080
---
apiVersion: v1
kind: Service
metadata:
  name: cargo
spec:
  selector:
    app: cargo
  ports:
    - port: 80
      targetPort: 8080
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: passengers
spec:
  replicas: 2
  selector:
    matchLabels:
      app: passengers
  template:
    metadata:
      labels:
        app: passengers
    spec:
      containers:
        - name: app
          image: port-app:v1
          env:
            - name: GREETING
              value: "Welcome to PASSENGERS"
          ports:
            - containerPort: 8080
---
apiVersion: v1
kind: Service
metadata:
  name: passengers
spec:
  selector:
    app: passengers
  ports:
    - port: 80
      targetPort: 8080
```

(`---` lets you keep several objects in one file.)

```bash
kubectl apply -f two-apps.yaml
kubectl get deployments,services
```

### 3. Write the gate rules

Save as `port-gate.yaml`:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: port-gate
spec:
  ingressClassName: nginx
  rules:
    - http:
        paths:
          - path: /cargo
            pathType: Prefix
            backend:
              service:
                name: cargo
                port:
                  number: 80
          - path: /passengers
            pathType: Prefix
            backend:
              service:
                name: passengers
                port:
                  number: 80
```

```bash
kubectl apply -f port-gate.yaml
kubectl get ingress port-gate
kubectl describe ingress port-gate
```

`describe` lists each path and the **backend pod IPs** it resolved to. That's the guard's notes.

### 4. Drive through the gate

```bash
curl localhost:8080/cargo
curl localhost:8080/passengers
```

```text
Welcome to CARGO | pod=cargo-5c7d...-abcde | version=v1
Welcome to PASSENGERS | pod=passengers-7f9b...-xyz12 | version=v1
```

One entrance on `localhost:8080`, two different apps. Run each a few times and watch the `pod=` name alternate between the two replicas.

(Our little app answers any path with its greeting, so it doesn't mind receiving `/cargo` in the URL. Many real apps expect to be served from `/`, so ingress-nginx offers a `nginx.ingress.kubernetes.io/rewrite-target` annotation to strip the prefix.)

### 5. What a path that matches nothing does

```bash
curl -i localhost:8080/customs
```

You get a **404** from the nginx controller itself: no rule matched, so the gate has nothing to forward to. (Add a `defaultBackend` if you want a catch-all.)

### 6. See the gate react to change

```bash
kubectl scale deployment cargo --replicas=4
kubectl describe ingress port-gate | grep -A2 cargo
```

The backend list grows to four pod IPs without you touching the Ingress. The controller is watching the same endpoints that Services use.

### 7. Look under the hood (optional)

```bash
kubectl exec -n ingress-nginx deploy/ingress-nginx-controller -- grep -m3 "cargo" /etc/nginx/nginx.conf
```

The controller turned your 15 lines of YAML into real nginx configuration. Clean up if you like:

```bash
kubectl delete -f port-gate.yaml -f two-apps.yaml
```

---

## Quick Quiz 🧠

**Q1.** You create an Ingress but no ingress controller is installed. What happens?

<details>
<summary>Show answer</summary>

Nothing: the Ingress is stored but never acted on. An Ingress is only a rule set; a controller must be running to read and enforce it.

</details>

**Q2.** What does the ingress controller itself consist of?

<details>
<summary>Show answer</summary>

Ordinary pods running a reverse proxy (for ingress-nginx, nginx plus a small program that watches the API server and regenerates the nginx config when Ingresses, Services or endpoints change).

</details>

**Q3.** Why use one Ingress instead of a NodePort (or cloud load balancer) per app?

<details>
<summary>Show answer</summary>

One entry point, one set of ports, one place for TLS and routing rules. With NodePorts you'd juggle many high port numbers; with cloud load balancers you'd pay for one per app.

</details>

**Q4.** In the Ingress, requests to `/cargo` reach the `cargo` **Service**. What's the next step after that?

<details>
<summary>Show answer</summary>

The Service's endpoints decide which `cargo` pod gets it. (In ingress-nginx the controller actually forwards straight to the pod IPs it reads from the endpoints, but it learns them through the Service's selector.)

</details>

**Q5.** A request for `/customs` returns 404 from nginx. Is something broken?

<details>
<summary>Show answer</summary>

No. No rule matched `/customs`, so the controller has nowhere to send it. That's correct behaviour. Add a rule or a default backend if you want it handled.

</details>

---

## What's Next? 🚀

Our traffic problems are solved: pods have stable addresses and a main gate. But look back at the labs. We've been baking settings into manifests (`GREETING: "Welcome to CARGO"`) and the app has an unused `/secret` endpoint. How do you configure an app *without rebuilding its image*, and where do passwords go?

👉 **[Post 09: Config and Secrets](content/kubernetes/09-config-and-secrets.md)**: customs paperwork versus locked cargo, and why a Secret isn't as secret as it sounds.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
