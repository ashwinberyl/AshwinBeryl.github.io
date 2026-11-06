---
title: "Storage — The Warehouse That Outlives Any Container"
date: 2026-11-06
tags: [kubernetes, storage, persistentvolume, persistentvolumeclaim, statefulset, emptydir, intermediate]
description: Post 10 of the Kubernetes from First Principles series. Why container storage vanishes, how PersistentVolumes and Claims separate "I need storage" from "here's the disk", and a lab proving data survives pod death, plus a StatefulSet.
---

# The Container Forgets Everything 🧽

A container's file system is **scratch paper**. Write to it, and when the container is replaced, the paper is thrown away. For our stateless web app that's perfect. For a database, it's a catastrophe.

**The analogy:** the dock is temporary. Containers arrive and leave. If you need something to still be there tomorrow, you put it in the **warehouse**, a building that stays put whatever happens to the containers outside.

In Kubernetes, the warehouse is a **volume**.

---

## Prove the Problem First 🔬

Before the fix, let's see the failure. Our app has a `/visit` endpoint that appends a line to `/data/visits.log` and returns the line count. Without a volume, `/data` doesn't even exist. So we'll start with the simplest volume.

---

## Three Kinds of Warehouse 🏭

| Type | Lives as long as | Use it for |
|---|---|---|
| **emptyDir** | The *pod* | Scratch space shared between containers in a pod. Survives *container* restarts, lost when the pod is deleted. |
| **PersistentVolumeClaim** | Independent of any pod | Data that must survive pod replacement: databases, uploads. |
| **configMap / secret** | The pod (they're re-injected) | Config (Post 09) |

### PV and PVC: Separating "I need" from "here's a disk"

Two objects, and the split is the whole idea:

| Port | Object | Who writes it | Meaning |
|---|---|---|---|
| **A storage rental request** | **PersistentVolumeClaim (PVC)** | The app developer | "I need 1 GiB, one writer at a time." |
| **The actual warehouse space** | **PersistentVolume (PV)** | The cluster / a provisioner | A real chunk of disk somewhere. |
| **The rental agency** | **StorageClass** | The cluster admin | Rules for *creating* PVs on demand: "disks of type X from provider Y." |

You, the developer, write only the **claim**. You never need to know whether the disk is a cloud volume or an NFS share. A **StorageClass** notices an unfulfilled claim and **dynamically provisions** a PV for it. In kind, a default StorageClass called `standard` does this using the node's local disk.

> **Access modes.** `ReadWriteOnce` (RWO) means one *node* can mount it read-write. That's what most block disks offer, and it's what we'll use.

---

## Lab: Data That Survives 🛠️

### 1. Watch data die with an emptyDir

Save as `scratch.yaml`:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: scratch
spec:
  securityContext:
    fsGroup: 10001
  containers:
    - name: app
      image: port-app:v1
      ports:
        - containerPort: 8080
      volumeMounts:
        - name: data
          mountPath: /data
  volumes:
    - name: data
      emptyDir: {}
```

```bash
kubectl apply -f scratch.yaml
kubectl wait --for=condition=ready pod/scratch --timeout=60s
kubectl port-forward pod/scratch 9090:8080
```

In another terminal:

```bash
curl localhost:9090/visit     # visit #1
curl localhost:9090/visit     # visit #2
```

Stop the forward, delete the pod, recreate it, and visit again:

```bash
kubectl delete pod scratch
kubectl apply -f scratch.yaml
kubectl wait --for=condition=ready pod/scratch --timeout=60s
kubectl port-forward pod/scratch 9090:8080
curl localhost:9090/visit     # visit #1  ← the count restarted
```

`emptyDir` lives and dies with the **pod**. (`fsGroup: 10001` lets our non-root app user write to the volume.) Stop the forward and `kubectl delete pod scratch`.

### 2. Claim real storage

Save as `ledger-pvc.yaml`:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ledger-data
spec:
  accessModes: ["ReadWriteOnce"]
  resources:
    requests:
      storage: 100Mi
```

```bash
kubectl get storageclass
kubectl apply -f ledger-pvc.yaml
kubectl get pvc ledger-data
```

You'll see the PVC `Pending`. That isn't an error: kind's default class uses `volumeBindingMode: WaitForFirstConsumer`, meaning **no disk is created until a pod actually needs it**, so the disk can be placed on the same node as the pod.

### 3. Use the claim from a Deployment

Save as `ledger.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ledger
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
      securityContext:
        fsGroup: 10001
      containers:
        - name: app
          image: port-app:v1
          ports:
            - containerPort: 8080
          volumeMounts:
            - name: data
              mountPath: /data
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: ledger-data
```

```bash
kubectl apply -f ledger.yaml
kubectl rollout status deployment/ledger
kubectl get pvc,pv
```

The claim is now `Bound`, and a PV appeared automatically. Nobody created it by hand.

### 4. The real test

```bash
kubectl port-forward deployment/ledger 9090:8080
```

In another terminal:

```bash
curl localhost:9090/visit     # visit #1
curl localhost:9090/visit     # visit #2
curl localhost:9090/visit     # visit #3
```

Now **kill the pod**:

```bash
kubectl delete pod -l app=ledger
kubectl rollout status deployment/ledger
```

Restart your port-forward (the old tunnel was attached to the dead pod) and visit again:

```bash
curl localhost:9090/visit     # visit #4, and the hostname is a new pod's
```

**The count continued.** The pod is new, but it mounted the same claim and found the same file. The data outlived the container: warehouse stock stayed put while the dock turned over.

### 5. A caveat worth seeing

```bash
kubectl get pv -o jsonpath='{.items[0].spec.nodeAffinity}'; echo
kubectl get pods -l app=ledger -o wide
```

kind's local storage creates a disk **on one specific node**, and the PV is pinned to it. That means the pod will always be scheduled to that node. Cloud volumes (EBS, Persistent Disk) work similarly. That's one reason RWO volumes and node failures need care.

### 6. StatefulSet: when each pod needs its *own* warehouse

With a Deployment, all replicas would try to share one claim. Databases usually want each replica to have **its own** stable identity and storage. That's a **StatefulSet**. Save as `stateful.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: vault
spec:
  clusterIP: None            # "headless": gives each pod its own DNS name
  selector:
    app: vault
  ports:
    - port: 8080
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: vault
spec:
  serviceName: vault
  replicas: 2
  selector:
    matchLabels:
      app: vault
  template:
    metadata:
      labels:
        app: vault
    spec:
      securityContext:
        fsGroup: 10001
      containers:
        - name: app
          image: port-app:v1
          ports:
            - containerPort: 8080
          volumeMounts:
            - name: data
              mountPath: /data
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 100Mi
```

```bash
kubectl apply -f stateful.yaml
kubectl get pods -l app=vault --watch
kubectl get pvc
```

Notice three differences from a Deployment:

1. **Predictable names**: `vault-0`, `vault-1`, not random suffixes.
2. **Ordered start**: `vault-0` is ready before `vault-1` begins.
3. **One PVC per pod**: `data-vault-0` and `data-vault-1`, created from `volumeClaimTemplates`.

Visit each separately and see independent counters:

```bash
kubectl exec vault-0 -- python -c "import urllib.request as u;print(u.urlopen('http://localhost:8080/visit').read().decode())"
kubectl exec vault-0 -- python -c "import urllib.request as u;print(u.urlopen('http://localhost:8080/visit').read().decode())"
kubectl exec vault-1 -- python -c "import urllib.request as u;print(u.urlopen('http://localhost:8080/visit').read().decode())"
```

`vault-0` reports visit #2, `vault-1` reports visit #1. Now delete `vault-0`:

```bash
kubectl delete pod vault-0
kubectl get pods -l app=vault --watch
```

It returns **with the same name and re-attaches to `data-vault-0`**. Identity and storage follow the *name*, not the pod instance.

### 7. Clean up, and the "gotcha"

```bash
kubectl delete -f stateful.yaml -f ledger.yaml
kubectl get pvc
```

Deleting the workloads leaves the **PVCs behind**. That's deliberate: Kubernetes won't delete your data just because you deleted the app. Remove them yourself when you're sure:

```bash
kubectl delete pvc ledger-data data-vault-0 data-vault-1
```

---

## Quick Quiz 🧠

**Q1.** A pod writes a file to its own container file system, then the pod is replaced. Is the file still there?

<details>
<summary>Show answer</summary>

No. The container's writable layer is discarded with the container. Use a volume to keep data.

</details>

**Q2.** What's the difference between a PVC and a PV?

<details>
<summary>Show answer</summary>

The **PVC** is the *request* ("I need 100Mi, one writer"), written by the app owner. The **PV** is the *actual storage* that satisfies it, usually created automatically by a StorageClass.

</details>

**Q3.** Why did the PVC show `Pending` until a pod used it?

<details>
<summary>Show answer</summary>

The StorageClass uses `WaitForFirstConsumer`: it delays creating the disk until a pod needs it, so it can create it on the same node the pod is scheduled to.

</details>

**Q4.** What does an `emptyDir` give you that the container's own file system doesn't, and what does it *not* give you?

<details>
<summary>Show answer</summary>

It survives **container restarts** within the pod and can be **shared between containers** in the pod. It does *not* survive the pod being deleted or rescheduled.

</details>

**Q5.** When would you choose a StatefulSet over a Deployment?

<details>
<summary>Show answer</summary>

When each replica needs a **stable identity** (predictable name and DNS) and **its own storage**, as with databases and clustered systems. For interchangeable stateless pods, use a Deployment.

</details>

---

## What's Next? 🚀

You can now run stateless and stateful workloads. But so far we've let the cluster place pods wherever it likes, with no limits on what they consume. What stops one greedy container from starving its neighbours? What happens if you ask for more than any berth has? And how does the port *know* a container is healthy?

👉 **[Post 11: Scheduling, Resources and Probes](content/kubernetes/11-scheduling-resources-and-probes.md)**: berth planning, weight limits, OOM kills, and health checks.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
