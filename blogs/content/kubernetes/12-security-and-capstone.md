---
title: "Access Badges and the Grand Opening — Security and Capstone"
date: 2026-11-06
tags: [kubernetes, namespaces, rbac, security-context, capstone, hardening, intermediate]
description: Post 12 of the Kubernetes from First Principles series. Separate terminals with namespaces, access badges with RBAC, locked-down containers with security contexts, then one capstone that deploys everything from this series in a single namespace.
---

# Who's Allowed on the Dock? 🪪

Our port now runs, heals, routes and stores. But so far **anyone with the cluster key could do anything**: delete the cargo, read the locked containers, change the gate rules. A real port issues **badges**, divides itself into **terminals**, and **locks down the containers** themselves.

Three tools, one for each:

| Port | Kubernetes | Controls |
|---|---|---|
| **Separate terminals** | **Namespaces** | *Where* things live: names, quotas and permissions are scoped per terminal |
| **Access badges** | **RBAC** | *Who* can do *what* to *which* resources |
| **Container locks** | **Security contexts** | *What a running container itself may do* |

---

## Namespaces: Separate Terminals 🏗️

A **namespace** is a named partition of the cluster. Two teams can each have a Deployment called `web` without colliding, because they live in different namespaces (`port-dev/web` and `port-prod/web`).

Namespaces give you:

- **Name scoping**: names must be unique only within a namespace.
- **A boundary for permissions** and **resource quotas** ("this terminal may use at most 4 CPUs").
- **Organisation**: `kubectl get pods -n port-dev` shows only that terminal.

They are *not* a hard security wall by themselves: pods in different namespaces can still talk to each other unless you add **NetworkPolicies** (below), and cluster-wide objects (nodes, PVs) live outside any namespace.

You've been using one all along: `default`. System components live in `kube-system`.

---

## RBAC: Access Badges 🎫

RBAC (Role-Based Access Control) answers *who may do what* with four objects:

| Object | Meaning | Analogy |
|---|---|---|
| **ServiceAccount** | An identity for a *program* running in a pod | A badge issued to a robot |
| **Role** | A set of permissions **within one namespace**: verbs on resources | "May view and list containers at Terminal A" |
| **RoleBinding** | Attaches a Role to a user or ServiceAccount | Handing the badge to someone |
| **ClusterRole / ClusterRoleBinding** | The cluster-wide versions | A port-wide master badge |

A rule reads like a sentence: *"allow `get`, `list`, `watch` on `pods`."* Anything not allowed is denied: RBAC is **deny by default**.

> **Principle of least privilege:** give each identity only what it needs. Dave once gave a bot `cluster-admin` "to get it working." Jim's rule: if you can't name the verbs, you're not ready to grant them.

---

## Security Contexts: Locking the Container 🔒

Remember from Post 02: a container is a process sharing the host's kernel, so it's **less isolated than a VM**. A security context tightens what that process may do:

```yaml
securityContext:
  runAsNonRoot: true                # refuse to start if the image tries to run as root
  runAsUser: 10001
  readOnlyRootFilesystem: true      # the container can't modify its own files
  allowPrivilegeEscalation: false   # no gaining extra privileges via setuid etc.
  capabilities:
    drop: ["ALL"]                   # remove all special Linux powers
  seccompProfile:
    type: RuntimeDefault            # block risky system calls
```

Most apps run fine with these. If something breaks, you learn precisely what it was relying on.

**NetworkPolicies** do the same job for networking: "only the gate may talk to the ledger." They need a network plugin that enforces them. kind's default one doesn't, so we'll leave them as a concept here, but keep them on your list for real clusters.

![RBAC lets a ServiceAccount do only what its Role lists](content/kubernetes/images/12-namespaces-and-rbac.svg)

---

## Lab Part 1: Terminals and Badges 🛠️

### 1. Create two terminals

```bash
kubectl create namespace port-dev
kubectl create namespace port-prod
kubectl get namespaces
```

Deploy the same-named app into each:

```bash
kubectl create deployment web --image=port-app:v1 -n port-dev
kubectl create deployment web --image=port-app:v1 -n port-prod
kubectl get deployments -A | grep web
```

Two Deployments called `web`, no collision. Work in one terminal by default:

```bash
kubectl config set-context --current --namespace=port-dev
kubectl get deployments
```

(Reset later with `--namespace=default`.)

### 2. Issue a badge

We'll make a ServiceAccount that may **only read pods in `port-dev`**. Save as `dockhand-rbac.yaml`:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: dockhand
  namespace: port-dev
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: pod-reader
  namespace: port-dev
rules:
  - apiGroups: [""]               # "" is the core API group (pods, services, secrets…)
    resources: ["pods"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: dockhand-reads-pods
  namespace: port-dev
subjects:
  - kind: ServiceAccount
    name: dockhand
    namespace: port-dev
roleRef:
  kind: Role
  name: pod-reader
  apiGroup: rbac.authorization.k8s.io
```

```bash
kubectl apply -f dockhand-rbac.yaml
```

### 3. Test the badge

`kubectl auth can-i` asks the API server "would this identity be allowed?" and lets us impersonate with `--as`:

```bash
SA=system:serviceaccount:port-dev:dockhand

kubectl auth can-i list pods     -n port-dev  --as=$SA     # yes
kubectl auth can-i delete pods   -n port-dev  --as=$SA     # no  (verb not granted)
kubectl auth can-i list secrets  -n port-dev  --as=$SA     # no  (resource not granted)
kubectl auth can-i list pods     -n port-prod --as=$SA     # no  (other namespace)
```

Four questions, one `yes` and three `no`. The Role is a *whitelist*: only exactly what's written. Try the real thing:

```bash
kubectl get pods -n port-dev  --as=$SA
kubectl get pods -n port-prod --as=$SA
```

The first lists pods; the second returns a **Forbidden** error naming the account and the namespace. That message is how you debug RBAC in practice.

Compare with your own admin badge: `kubectl auth can-i '*' '*'` prints `yes`.

### 4. Clean up this part

```bash
kubectl delete namespace port-dev port-prod
kubectl config set-context --current --namespace=default
```

Deleting a namespace deletes everything inside it, which makes namespaces handy for tearing down a whole environment, and dangerous to delete casually.

---

## Lab Part 2: The Grand Opening (Capstone) 🎉

Everything from the series, in one namespace. We'll open a small port called **harbour** with two parts:

- **gate**: a stateless, public-facing app. 3 replicas, probes, resource limits, locked-down container, config from a ConfigMap, a Secret, and reachable through Ingress.
- **ledger**: a stateful app that keeps data on a PersistentVolume, reachable internally through its own Service (and, for this demo, through Ingress too).

(To be upfront: our one sample image doesn't call across tiers. The *structure*, with separate Deployments, Services, storage and config, is what a real two-tier app looks like. The app inside is the part you'd swap.)

Make sure the ingress controller from Post 08 is still installed, and that its tunnel is open in a spare terminal (`kubectl -n ingress-nginx port-forward service/ingress-nginx-controller 8080:80`). Then work through these steps. (As noted in Post 08, ingress-nginx is retired; it's fine for this throwaway lab, but not for real systems.)

### 1. Namespace, config and secret

```bash
kubectl create namespace harbour
kubectl -n harbour create configmap harbour-config --from-literal=GREETING="Welcome to Harbour"
kubectl -n harbour create secret generic harbour-secret --from-literal=SECRET_TOKEN='opening-day-key'
```

### 2. The manifest

Save as `harbour.yaml`:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: harbour-app
  namespace: harbour
automountServiceAccountToken: false     # these pods never need to call the Kubernetes API
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gate
  namespace: harbour
spec:
  replicas: 3
  minReadySeconds: 5
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app: gate
  template:
    metadata:
      labels:
        app: gate
    spec:
      serviceAccountName: harbour-app
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        fsGroup: 10001
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: app
          image: port-app:v1
          ports:
            - containerPort: 8080
          env:
            - name: GREETING
              valueFrom:
                configMapKeyRef:
                  name: harbour-config
                  key: GREETING
            - name: SECRET_TOKEN
              valueFrom:
                secretKeyRef:
                  name: harbour-secret
                  key: SECRET_TOKEN
          resources:
            requests:
              cpu: "50m"
              memory: "64Mi"
            limits:
              cpu: "250m"
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
            periodSeconds: 10
            failureThreshold: 3
          securityContext:
            readOnlyRootFilesystem: true
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
---
apiVersion: v1
kind: Service
metadata:
  name: gate
  namespace: harbour
spec:
  selector:
    app: gate
  ports:
    - port: 80
      targetPort: 8080
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ledger-data
  namespace: harbour
spec:
  accessModes: ["ReadWriteOnce"]
  resources:
    requests:
      storage: 100Mi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ledger
  namespace: harbour
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ledger
  template:
    metadata:
      labels:
        app: ledger
    spec:
      serviceAccountName: harbour-app
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        fsGroup: 10001
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: app
          image: port-app:v1
          ports:
            - containerPort: 8080
          env:
            - name: GREETING
              value: "Ledger office"
          resources:
            requests:
              cpu: "50m"
              memory: "64Mi"
            limits:
              cpu: "250m"
              memory: "128Mi"
          readinessProbe:
            httpGet:
              path: /healthz
              port: 8080
            periodSeconds: 3
          securityContext:
            readOnlyRootFilesystem: true
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
          volumeMounts:
            - name: data
              mountPath: /data
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: ledger-data
---
apiVersion: v1
kind: Service
metadata:
  name: ledger
  namespace: harbour
spec:
  selector:
    app: ledger
  ports:
    - port: 80
      targetPort: 8080
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: harbour-gate
  namespace: harbour
  annotations:
    nginx.ingress.kubernetes.io/use-regex: "true"
    nginx.ingress.kubernetes.io/rewrite-target: /$2
spec:
  ingressClassName: nginx
  rules:
    - http:
        paths:
          - path: /gate(/|$)(.*)
            pathType: ImplementationSpecific
            backend:
              service:
                name: gate
                port:
                  number: 80
          - path: /ledger(/|$)(.*)
            pathType: ImplementationSpecific
            backend:
              service:
                name: ledger
                port:
                  number: 80
```

The `rewrite-target: /$2` annotation strips the `/gate` or `/ledger` prefix before the request reaches the app. That's the trick promised back in Post 08.

```bash
kubectl apply -f harbour.yaml
kubectl -n harbour rollout status deployment/gate
kubectl -n harbour rollout status deployment/ledger
kubectl -n harbour get all,pvc,ingress
```

### 3. Open the gates

```bash
curl localhost:8080/gate/
curl localhost:8080/gate/secret
curl localhost:8080/ledger/visit
curl localhost:8080/ledger/visit
```

Expected: the config-driven greeting with a pod name and version, `SECRET_TOKEN is set (15 chars)`, then `visit #1` and `visit #2`.

### 4. Try to break it (and watch it hold)

Run through the greatest hits of the series:

```bash
# Self-healing (Post 05)
kubectl -n harbour delete pods -l app=gate
kubectl -n harbour get pods -l app=gate

# Persistence (Post 10)
kubectl -n harbour delete pod -l app=ledger
kubectl -n harbour rollout status deployment/ledger
curl localhost:8080/ledger/visit        # counter continues

# Rolling update with probes (Posts 06, 11)
# (run the next two lines in the folder that holds your Dockerfile)
docker build --build-arg VERSION=v2 -t port-app:v2 .
kind load docker-image port-app:v2 --name port
kubectl -n harbour set image deployment/gate app=port-app:v2
kubectl -n harbour rollout status deployment/gate
curl localhost:8080/gate/               # version=v2

# Bad release rolled back (Post 06)
kubectl -n harbour set image deployment/gate app=port-app:oops
kubectl -n harbour rollout status deployment/gate --timeout=30s
kubectl -n harbour rollout undo deployment/gate
```

### 5. Confirm the locks

```bash
kubectl -n harbour exec deploy/gate -- id
kubectl -n harbour exec deploy/gate -- sh -c 'touch /app/test || echo "read-only filesystem: write refused"'
```

`id` shows `uid=10001`, not root, and the write attempt fails. The container really is locked down.

### 6. Tear down

```bash
kubectl delete namespace harbour
```

One command removes the whole port: Deployments, Services, Ingress, PVC and all. If you're finished with the series entirely:

```bash
kind delete cluster --name port
```

---

## Quick Quiz 🧠

**Q1.** Two teams each create a Deployment named `web`. Why doesn't that clash?

<details>
<summary>Show answer</summary>

Names only need to be unique within a **namespace**. If the teams use different namespaces, `team-a/web` and `team-b/web` are different objects.

</details>

**Q2.** A ServiceAccount has a Role granting `get`/`list` on `pods` in `port-dev`. Can it list pods in `port-prod`? Delete pods in `port-dev`? Why?

<details>
<summary>Show answer</summary>

No to both. A **Role** is scoped to its own namespace, and RBAC is **deny by default**: it only allows exactly the verbs and resources listed, and `delete` wasn't listed.

</details>

**Q3.** What's the difference between a Role and a RoleBinding?

<details>
<summary>Show answer</summary>

The **Role** defines *what's permitted* (verbs on resources). The **RoleBinding** says *who* gets those permissions. Neither does anything without the other.

</details>

**Q4.** Why set `readOnlyRootFilesystem: true` and `runAsNonRoot: true`?

<details>
<summary>Show answer</summary>

Containers share the host kernel, so reducing what a compromised process can do matters. Non-root limits its privileges; a read-only root file system stops it from modifying the app, dropping tools or persisting changes. Writable paths are provided explicitly (like a mounted `/data`).

</details>

**Q5.** Is a Namespace a security boundary on its own?

<details>
<summary>Show answer</summary>

Not fully. It scopes names, RBAC and quotas, but pods in different namespaces can still talk over the network by default. Add **NetworkPolicies** (with a network plugin that enforces them), RBAC and quotas for real isolation.

</details>

---

## You Made It 🎓

Look at what the port now does, and which post taught each part:

| What you can explain | Post |
|---|---|
| Why orchestration exists; desired vs actual state | 01 |
| What a container really is | 02 |
| How the control plane and reconcile loop work | 03 |
| Pods, and how to debug them | 04 |
| Self-healing and scaling with Deployments | 05 |
| Zero-downtime updates and rollbacks | 06 |
| Stable addresses with Services | 07 |
| One gate for many apps with Ingress | 08 |
| Config and Secrets | 09 |
| Persistent storage and StatefulSets | 10 |
| Scheduling, resource limits, and probes | 11 |
| Namespaces, RBAC, and hardened containers | 12 |

### Where to go next

- **Package it**: Helm and Kustomize, so you don't hand-edit YAML per environment.
- **Automate delivery**: GitOps tools (Argo CD, Flux) that make Git the source of truth, the reconcile loop applied to your whole repo.
- **Observe it**: metrics (Prometheus), logs and traces. You can't fix what you can't see.
- **Run it for real**: managed clusters (EKS, GKE, AKS), cluster upgrades, node autoscaling, backups.
- **Extend it**: Custom Resources and Operators: teaching the port to manage new kinds of cargo.
- **Modernise the gate**: the Gateway API, the successor to Ingress and the migration path the Kubernetes project recommends now that ingress-nginx is retired.
- **Harden it more**: NetworkPolicies, Pod Security Standards, image scanning, secret managers.

Every one of those is the same idea you learned in Post 03, applied once more: **declare what you want, and let a loop make it true.**

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
