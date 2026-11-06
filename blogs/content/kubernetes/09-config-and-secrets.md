---
title: "Config and Secrets — Customs Paperwork and Locked Cargo"
date: 2026-11-06
tags: [kubernetes, configmap, secrets, configuration, environment-variables, base64, beginner]
description: Post 9 of the Kubernetes from First Principles series. How to keep configuration out of your images with ConfigMaps, how Secrets differ (and don't), and a lab injecting both as environment variables and files.
---

# Same Container, Different Port 🌍

The same shipping container can go to Rotterdam or Singapore. What changes is the **paperwork** attached to it: destination, customs codes, handling instructions. You don't rebuild the container for each trip.

Apps are the same. One image should run in dev, test and production. What differs between them is **configuration**: database addresses, feature flags, greeting messages, and **secrets** like passwords and API keys.

Baking those into the image is a mistake:

- A new setting means a **rebuild and redeploy**.
- Your password ends up **inside the image**, visible to anyone who can pull it.
- You can't reuse one image across environments.

Kubernetes separates the two:

| Port | Object | Holds |
|---|---|---|
| **Customs paperwork** | **ConfigMap** | Non-sensitive settings |
| **Locked cargo** | **Secret** | Sensitive values: passwords, tokens, keys |

---

## ConfigMap: The Paperwork 📄

A ConfigMap is just a bag of key/value pairs (or whole files) stored in the cluster.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: port-config
data:
  GREETING: "Welcome aboard"
  motd.txt: |
    The port opens at 06:00.
    Hard hats are mandatory.
```

A pod can consume it in two ways:

| Method | How | Updates when ConfigMap changes? |
|---|---|---|
| **Environment variable** | `valueFrom.configMapKeyRef` or `envFrom` | **No.** Read once at container start. |
| **Mounted file** | A `volume` of type `configMap` | **Yes**, eventually (the kubelet refreshes the files after a delay of up to about a minute). Your app must re-read the file. |

> **Key insight:** Changing a ConfigMap does **not** restart pods that use it as env vars. They keep the old value until they're recreated. Many teams trigger a rollout whenever config changes for exactly this reason.

---

## Secret: The Locked Cargo 🔐

A Secret looks almost identical, with one difference in how it's stored:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: port-secret
type: Opaque
stringData:                      # write plain text here...
  SECRET_TOKEN: "s3cr3t-crane-key"
```

Kubernetes stores `data` values **base64-encoded**. (`stringData` is a convenience: you write plain text and it's encoded for you.)

### The hard truth about Secrets

**Base64 is encoding, not encryption.** Anyone who can read the Secret can decode it in one command:

```bash
echo 'czNjcjN0LWNyYW5lLWtleQ==' | base64 -d
```

So what does a Secret actually buy you?

- It's a **separate object type**, so you can apply stricter **access rules (RBAC, Post 12)** to Secrets than to ConfigMaps.
- It's **not printed** in `kubectl describe`, and it can be **encrypted at rest** in etcd if the cluster is configured for it. (Not by default.)
- It's mounted in memory (`tmpfs`) on the node rather than written to disk.
- It keeps passwords **out of your image and out of your Deployment YAML**.

What it does *not* do: protect a value from anyone with permission to read it, or from being committed to Git by accident if you store the YAML there. Real teams add external secret managers (cloud vaults, tools that sync them into Secrets) and never commit Secret manifests.

---

## Lab: Paperwork and Locked Cargo 🛠️

### 1. Create the ConfigMap and Secret from the command line

Creating a Secret imperatively keeps it out of any YAML file you might commit:

```bash
kubectl create configmap port-config \
  --from-literal=GREETING="Welcome aboard" \
  --from-literal=motd.txt=$'The port opens at 06:00.\nHard hats are mandatory.'

kubectl create secret generic port-secret \
  --from-literal=SECRET_TOKEN='s3cr3t-crane-key'
```

Look at them:

```bash
kubectl get configmap port-config -o yaml
kubectl get secret port-secret -o yaml
kubectl describe secret port-secret
```

The ConfigMap is plain text. The Secret shows `SECRET_TOKEN: czNjcjN0...` (base64) and `describe` shows only the **size** of each value, not the value. Decode it yourself:

```bash
kubectl get secret port-secret -o jsonpath='{.data.SECRET_TOKEN}' | base64 -d; echo
```

That's the "not encryption" point, in one line.

### 2. Consume both in a Deployment

Save as `configured-app.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: configured
spec:
  replicas: 1
  selector:
    matchLabels:
      app: configured
  template:
    metadata:
      labels:
        app: configured
    spec:
      containers:
        - name: app
          image: port-app:v1
          ports:
            - containerPort: 8080
          env:
            - name: GREETING                 # from the ConfigMap
              valueFrom:
                configMapKeyRef:
                  name: port-config
                  key: GREETING
            - name: SECRET_TOKEN             # from the Secret
              valueFrom:
                secretKeyRef:
                  name: port-secret
                  key: SECRET_TOKEN
          volumeMounts:
            - name: notices
              mountPath: /etc/port           # each ConfigMap key becomes a file here
              readOnly: true
      volumes:
        - name: notices
          configMap:
            name: port-config
```

```bash
kubectl apply -f configured-app.yaml
kubectl rollout status deployment/configured
kubectl port-forward deployment/configured 9090:8080
```

In another terminal:

```bash
curl localhost:9090/          # the greeting from the ConfigMap
curl localhost:9090/secret    # reports the secret is set, never prints it
```

You should see `Welcome aboard | pod=... | version=v1` and `SECRET_TOKEN is set (16 chars)`. The image didn't change; its behaviour did.

### 3. Look at the mounted files

```bash
kubectl exec deploy/configured -- ls -l /etc/port
kubectl exec deploy/configured -- cat /etc/port/motd.txt
```

Each ConfigMap key became a **file**. Our app doesn't read them, but many real apps (nginx configs, application.properties) want files, and this is how you supply them.

### 4. The env-var gotcha

Change the ConfigMap:

```bash
kubectl patch configmap port-config --type merge -p '{"data":{"GREETING":"Welcome ABOARD, mates"}}'
```

Check both consumers:

```bash
curl localhost:9090/                                   # (restart the port-forward if it dropped)
kubectl exec deploy/configured -- cat /etc/port/GREETING
```

The **file** shows the new value (it can take up to a minute to appear; try again). The **env var** (what `curl` shows) still says the old greeting. Env vars are fixed at container start. Restart the pods:

```bash
kubectl rollout restart deployment/configured
kubectl rollout status deployment/configured
```

Reconnect your port-forward and `curl` again: now it matches.

### 5. See where Secrets really leak

Dave's shortcut: put the password directly in the Deployment YAML as a plain `value:`.

```bash
kubectl get deployment configured -o yaml | grep -B1 -A3 SECRET_TOKEN
```

Notice what you see: only a **reference** (`secretKeyRef`), not the value. If Dave had hard-coded it, the password would be here in plain text, in Git history, and in every `kubectl get deployment -o yaml`. Using a Secret keeps it out. That alone is worth the object.

Clean up:

```bash
kubectl delete deployment configured
kubectl delete configmap port-config
kubectl delete secret port-secret
```

---

## Quick Quiz 🧠

**Q1.** Why keep configuration out of the container image?

<details>
<summary>Show answer</summary>

So one image works in every environment, so a setting change doesn't need a rebuild, and so passwords aren't baked into something many people can pull.

</details>

**Q2.** You update a ConfigMap that's consumed as an env var. Do running pods see the change?

<details>
<summary>Show answer</summary>

No. Env vars are read at container start. You have to recreate the pods (e.g. `kubectl rollout restart`). A ConfigMap **mounted as a file** *is* refreshed in place, though the app must re-read it.

</details>

**Q3.** Is a Secret encrypted?

<details>
<summary>Show answer</summary>

Not by itself. Values are base64-**encoded**, which anyone can reverse. Encryption at rest in etcd is an optional cluster setting. The Secret's value is in separate access control (RBAC), hidden from `describe`, and kept out of images and manifests.

</details>

**Q4.** You decode a Secret with `base64 -d`. Why does that not mean Kubernetes is broken?

<details>
<summary>Show answer</summary>

Because you had permission to read it. Secrets are protected by *who may read them*, not by obscurity. If you'd lacked `get secrets` permission, the API would have refused.

</details>

**Q5.** A teammate commits `secret.yaml` (with `stringData`) to Git "because it's a Secret, so it's safe." What's wrong?

<details>
<summary>Show answer</summary>

The file contains the value in plain text (or trivially decodable base64), and Git history is forever. Create Secrets out-of-band (CLI, CI, or an external secrets tool) and never commit their values.

</details>

---

## What's Next? 🚀

Everything we've built so far is **disposable**. Pods die and take their file systems with them. That's fine for a stateless web app, but disastrous for a database or anything that must remember. What survives when a container disappears?

👉 **[Post 10: Storage](content/kubernetes/10-storage.md)**: the warehouse that outlives any container: PersistentVolumes, claims and StatefulSets.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
