---
title: "Linux and Docker Fundamentals"
date: 2026-11-08
tags: [aws, linux, amazon-linux, docker, containers, dockerfile, boto3, intermediate]
description: Post 9 of the AWS series. The Linux administration you need on every AWS instance (users, permissions, services, disks, logs, networking) and the Docker fundamentals that make container deployments predictable, plus a lab that builds the plat-api image the rest of the series deploys.
---

# Two Skills Every Compute Service Assumes 🐧

From here on we run things: a virtual machine, a container on ECS, a pod on EKS, a build in CodeBuild. Every one of them rests on the same two foundations.

**Linux**, because nearly every AWS workload runs on it, and when something misbehaves you'll be reading logs and checking ports in a shell. **Docker**, because a container image is the unit you actually ship.

This post is deliberately practical. You'll practise Linux administration inside an Amazon Linux container on your laptop, and then build the **`plat-api`** application image that Posts 11, 12 and 18 deploy.

---

## Part 1: Linux Administration for the Cloud 🛠️

We use **Amazon Linux 2023 (AL2023)**, AWS's default Linux. Everything here applies to most distributions.

### The commands you'll use constantly

| Task | Command | Gotcha |
|---|---|---|
| Who am I, what groups? | `whoami`, `id` | SSM sessions run as `ssm-user`, not `ec2-user` |
| Run as root | `sudo <command>` | Prefer `sudo` over logging in as root |
| Read permissions | `ls -l`, `stat file` | `-rw-r-----` is owner read/write, group read, others nothing |
| Change owner / mode | `chown user:group f`, `chmod 640 f` | `chmod 777` hides a problem instead of fixing it |
| Processes | `ps aux`, `top` | `ps aux \| grep x` matches the grep itself, too |
| Services | `systemctl status\|start\|stop\|enable <svc>` | **`start` is now, `enable` is at boot.** They're separate |
| Service logs | `journalctl -u <svc> --since "10 min ago" -f` | Many logs live in the journal, not `/var/log` |
| Disk space | `df -h`, `df -i`, `du -sh *` | A disk can be "full" because it ran out of **inodes** |
| Block devices | `lsblk` | Device names can change between boots |
| Open ports | `ss -tlnp` | `-p` needs root to show the owning process |
| Name resolution | `getent hosts <name>` | Tests what applications actually see (`dig` skips `/etc/hosts`) |
| HTTP test | `curl -v http://host:port/path` | The verbose flag shows connect vs TLS vs response time |
| Packages | `sudo dnf install -y <pkg>`, `dnf search <name>` | AL2023 ties packages to a **release version** |
| First-boot output | `/var/log/cloud-init-output.log` | Where EC2 user-data errors show up |

### Permissions in one picture

Every file has an **owner**, a **group** and **others**, each with **r**ead, **w**rite and e**x**ecute. In octal: read is 4, write is 2, execute is 1.

| Mode | Meaning | Typical use |
|---|---|---|
| `600` | Owner read and write | Private keys, credentials |
| `640` | Owner read/write, group read | App config readable by a service group |
| `644` | Everyone can read | Public files |
| `755` | Owner full, others read and execute | Executables, directories |

### Disks the right way

A new disk goes through four steps: **identify** (`lsblk`), **format** (`sudo mkfs.xfs /dev/nvme1n1`), **mount** (`sudo mount /dev/nvme1n1 /data`), and **persist** by adding a line to `/etc/fstab`. Use the **UUID**, not the device name, and add **`nofail`** so a missing disk doesn't stop the machine booting:

```text
UUID=1234abcd-12ab-34cd-56ef-1234567890ab  /data  xfs  defaults,nofail  0  2
```

We do this for real on EC2 in Post 10.

---

## Part 2: Docker Fundamentals 🐳

### Image, container, registry

| Term | What it is |
|---|---|
| **Image** | A read-only, layered filesystem plus start-up settings. The thing you build and ship |
| **Container** | A running instance of an image: isolated processes with a **thin writable layer** on top |
| **Registry** | Storage for images (Docker Hub, **Amazon ECR**, GitHub Container Registry) |
| **Tag** | A movable label on an image (`plat-api:1.0.0`) |
| **Digest** | The immutable content hash (`sha256:...`) that identifies an image exactly |

Containers are **not small virtual machines**. They share the host's kernel and are isolated using namespaces (what a process can see) and cgroups (how much it can use). That's why they start in milliseconds, and why a container can only run software built for the host's **CPU architecture**.

![Layers, images and containers](content/aws/images/09-docker-layers.svg)

### Layers and the build cache

Each Dockerfile instruction (`RUN`, `COPY`, `ADD`) creates a **layer**. Docker caches a layer and reuses it **as long as that instruction and everything before it is unchanged**. So order instructions from *least* to *most* frequently changing:

```dockerfile
COPY requirements.txt .          # changes rarely
RUN pip install -r requirements.txt   # slow, cached until requirements change
COPY app.py .                    # changes often, so it goes last
```

Put `COPY . .` first and every code edit re-installs every dependency.

### Instructions that trip people up

| Instruction | What it really does |
|---|---|
| `EXPOSE 8080` | **Documentation only.** It doesn't publish anything. You publish with `-p` at run time |
| `CMD` vs `ENTRYPOINT` | `ENTRYPOINT` is the program. `CMD` is its default arguments. `docker run image X` replaces `CMD` |
| `USER` | Switches the user for later steps *and* at runtime. Always end on a non-root user |
| `HEALTHCHECK` | Used by plain Docker only. **ECS and Kubernetes ignore it** and use their own health checks |
| `ENV` / `ARG` | Both are **visible** (`docker inspect`, `docker history`). Never put secrets in them |

---

## Nuances & Misconceptions 🧩

### Linux

| What people assume | What's actually true |
|---|---|
| "`chmod 777` fixes permission errors." | It makes the error go away by removing the protection. Fix the **owner or group** instead. |
| "The service is running, so it'll survive a reboot." | `systemctl start` runs it now. `systemctl enable` makes it start at boot. You need both. |
| "`df` says there's free space, so the disk isn't full." | You can run out of **inodes** (`df -i`), or space may be held by a **deleted file a process still has open** (`lsof +L1`). |
| "I can mount by device name in fstab." | Names like `/dev/xvdf` **can change**. Use the **UUID**, and add `nofail`. |
| "All logs are in `/var/log`." | Service logs go to the **systemd journal** (`journalctl`). First-boot script output is in **`/var/log/cloud-init-output.log`**. |
| "`dnf update` is always safe on a production host." | On AL2023 it moves you to a **newer release version** of every package. Pin the release and test changes on a copy first. |

### Docker

| What people assume | What's actually true |
|---|---|
| "A container is a lightweight VM." | It shares the **host kernel**. It isolates processes, it doesn't virtualise hardware. |
| "`:latest` is the newest version." | It's just a tag, and **mutable**. It points at whatever was last pushed under that name. Use explicit version tags. |
| "`EXPOSE` opens the port." | It only **documents** it. Publish with `-p host:container`, or map ports in your orchestrator. |
| "Data written in a container is saved." | The writable layer **disappears with the container**. Use volumes, or better, S3, EFS or a database. |
| "An image built on my laptop will run on AWS." | Not necessarily. An image built on an **Apple Silicon (arm64)** Mac fails on an x86 host with `exec format error`. Build with `--platform`. |
| "Running as root in a container is fine, it's isolated." | A container escape is far worse as root. Run as a **non-root user**. |
| "Build arguments hide secrets." | `ARG` values remain in **image history**. Fetch secrets **at runtime** with an IAM role. |
| "Mounting `~/.aws` is how containers get credentials." | That's a **local-only shortcut**. In AWS the container uses a **task role** or **pod identity**. Nothing is mounted. |
| "Docker Hub will always serve my base image." | Anonymous pulls are **rate limited** per IP, and shared build servers hit the limit. Pull base images from **ECR Public** or an ECR pull-through cache instead. |

---

## How This Connects 🔗

| This post uses | From |
|---|---|
| The `plat-admin` SSO profile, to run the app locally against real AWS | Post 03 |
| The bucket `plat-data-<account>-us-east-1` and `raw/events.csv` | Post 06 |
| DynamoDB table `plat-jobs`, with the item `job-001` | Post 08 |

| You create here | Used by |
|---|---|
| **`plat-api:1.0.0`** image and its source | ECR and ECS (11), EKS (12), CodeBuild (18) |
| The Linux toolkit | EC2 labs (10) and the CloudWatch agent (21) |
| `/health` endpoint | Load balancer health checks (11), Kubernetes probes (12) |

---

## Lab: Linux Drills, Then the `plat-api` Image 🛠️

You need **Docker** on your computer (Docker Desktop or Docker Engine) and your `plat-admin` SSO profile. All files below also live in the repo under `content/aws/lab/`.

### Part A: Linux drills in an Amazon Linux container

```bash
docker run --rm -it public.ecr.aws/amazonlinux/amazonlinux:2023 bash
```

You're in a fresh AL2023 as root. Try each of these:

```bash
cat /etc/os-release | head -3
dnf install -y iproute procps-ng shadow-utils util-linux >/dev/null

useradd -m jim && useradd -m dave
echo "quarterly numbers" > /home/jim/report.txt
chown jim:jim /home/jim/report.txt
chmod 640 /home/jim/report.txt
ls -l /home/jim/report.txt

su dave -c 'cat /home/jim/report.txt'      # Permission denied: dave is "others"
groupadd analysts && usermod -aG analysts dave
chgrp analysts /home/jim/report.txt
chmod 750 /home/jim                        # dave must be able to enter the directory too
su dave -c 'cat /home/jim/report.txt'      # works after a fresh login
```

```text
-rw-r----- 1 jim jim 18 Nov  8 10:00 /home/jim/report.txt
cat: /home/jim/report.txt: Permission denied
quarterly numbers
```

Notice step two of the fix: reading a file needs **execute permission on every directory** leading to it. Then look at the system:

```bash
df -h /
df -i /
ss -tlnp
ps aux | head -5
exit
```

`systemctl` and `journalctl` don't work inside a container (there's no systemd), so we practise those on a real instance in Post 10.

### Part B: Build the application image

Create a folder `plat-api/` with four files.

**`app.py`**

```python
import json
import os
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import boto3

VERSION = os.environ.get("APP_VERSION", "1.0.0")
REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
BUCKET = os.environ.get("DATA_BUCKET")
JOBS_TABLE = os.environ.get("JOBS_TABLE")
DB_HOST = os.environ.get("DB_HOST")
DB_NAME = os.environ.get("DB_NAME", "platmeta")
DB_SECRET_ARN = os.environ.get("DB_SECRET_ARN")

s3 = boto3.client("s3", region_name=REGION)
ddb = boto3.resource("dynamodb", region_name=REGION)
secrets = boto3.client("secretsmanager", region_name=REGION)


def log(**fields):
    print(json.dumps({"ts": time.time(), **fields}), flush=True)


def db_rows():
    import pg8000.native  # imported lazily so the app starts without a database

    secret = json.loads(secrets.get_secret_value(SecretId=DB_SECRET_ARN)["SecretString"])
    con = pg8000.native.Connection(
        user=secret["username"],
        password=secret["password"],
        host=DB_HOST,
        database=DB_NAME,
        ssl_context=True,
        timeout=5,
    )
    try:
        rows = con.run("SELECT id, name, s3_key, row_count FROM datasets ORDER BY id")
    finally:
        con.close()
    return [{"id": r[0], "name": r[1], "s3_key": r[2], "row_count": r[3]} for r in rows]


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        data = json.dumps(body, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        try:
            if path == "/health":
                return self._send(200, {"status": "ok"})
            if path == "/":
                return self._send(200, {"app": "plat-api", "version": VERSION,
                                        "host": socket.gethostname()})
            if path == "/data":
                if not BUCKET:
                    return self._send(503, {"error": "DATA_BUCKET not set"})
                resp = s3.list_objects_v2(Bucket=BUCKET, Prefix="raw/", MaxKeys=100)
                keys = [o["Key"] for o in resp.get("Contents", [])]
                return self._send(200, {"bucket": BUCKET, "raw_objects": keys})
            if path.startswith("/jobs/"):
                if not JOBS_TABLE:
                    return self._send(503, {"error": "JOBS_TABLE not set"})
                job_id = path[len("/jobs/"):]
                item = ddb.Table(JOBS_TABLE).get_item(Key={"job_id": job_id}).get("Item")
                return self._send(200 if item else 404, item or {"error": "not found"})
            if path == "/datasets":
                if not (DB_HOST and DB_SECRET_ARN):
                    return self._send(503, {"error": "database not configured"})
                return self._send(200, db_rows())
            return self._send(404, {"error": "no such route"})
        except Exception as exc:  # report the class, log the detail
            log(level="error", path=path, error=str(exc))
            return self._send(502, {"error": type(exc).__name__})

    def log_message(self, fmt, *args):
        log(level="info", client=self.client_address[0], request=fmt % args)


if __name__ == "__main__":
    log(level="info", msg="starting", version=VERSION)
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
```

**`requirements.txt`**

```text
boto3>=1.35,<2
pg8000>=1.31,<2
```

**`.dockerignore`**

```text
.git
__pycache__
*.pyc
.env
```

**`Dockerfile`**

```dockerfile
FROM public.ecr.aws/docker/library/python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py .

RUN useradd --uid 10001 --create-home app
USER app

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/health', timeout=2).status == 200 else 1)"

CMD ["python", "app.py"]
```

Three details worth noticing: the base image comes from **ECR Public** (no Docker Hub rate limits), the dependencies are installed *before* the code is copied (cache), and the process runs as **user 10001**.

Build it **for x86**, which is what the AWS compute we use runs on:

```bash
docker build --platform linux/amd64 -t plat-api:1.0.0 .
docker image ls plat-api
docker run --rm plat-api:1.0.0 id
```

```text
uid=10001(app) gid=10001(app) groups=10001(app)
```

(Passing `id` replaced the default `CMD`, so Docker ran `id` as the image's user instead of the app.)

### Part C: Prove the build cache

Change `VERSION` in `app.py` to `"1.0.1"` and rebuild:

```bash
docker build --platform linux/amd64 -t plat-api:1.0.1 .
```

You'll see the `pip install` step marked **CACHED**, and only the `COPY app.py` layer and below rebuild. Now reverse the order of the `COPY` lines in a scratch copy of the Dockerfile and watch `pip install` run every time.

### Part D: Run it against real AWS

Refresh your SSO session, set the variables, and run the container with your profile mounted (a **local-only shortcut**):

```bash
aws sso login --profile plat-admin
export BUCKET=plat-data-$(aws sts get-caller-identity --profile plat-admin --query Account --output text)-us-east-1

docker run --rm -p 8080:8080 \
  -e AWS_PROFILE=plat-admin -e AWS_REGION=us-east-1 \
  -e DATA_BUCKET=$BUCKET -e JOBS_TABLE=plat-jobs \
  -v ~/.aws:/home/app/.aws:ro \
  plat-api:1.0.0
```

In a second terminal:

```bash
curl -s localhost:8080/health
curl -s localhost:8080/
curl -s localhost:8080/data
curl -s localhost:8080/jobs/job-001
curl -s -o /dev/null -w "%{http_code}\n" localhost:8080/jobs/nope
curl -s localhost:8080/datasets
```

```text
{"status": "ok"}
{"app": "plat-api", "version": "1.0.0", "host": "3f2a9c1d8b7e"}
{"bucket": "plat-data-123456789012-us-east-1", "raw_objects": ["raw/", "raw/events.csv"]}
{"job_id": "job-001", "status": "DONE", "created_at": "2026-11-08T09:00:00Z", "rows": "5050"}
404
{"error": "database not configured"}
```

Your laptop is reading **real S3 and DynamoDB** with your own SSO identity. The `/datasets` route says "database not configured" because we didn't pass `DB_HOST`. And even if we had, your laptop **has no route** to a database in a private subnet. In Post 11 the same image runs *inside* the VPC with a role instead of your credentials, and `/datasets` starts working. Stop the container with `Ctrl+C`.

### Resources you now have 📦

| Resource | Name | Notes |
|---|---|---|
| Image (local) | `plat-api:1.0.0`, `plat-api:1.0.1` | `linux/amd64`, non-root |
| Source folder | `plat-api/` (also in `content/aws/lab/`) | Reused in Posts 11, 12, 15 and 18 |

### Cleanup 🧹

Nothing in AWS to clean. To free disk space locally: `docker image prune`.

---

## Quick Quiz 🧠

**Q1.** You build an image on an Apple Silicon Mac and deploy it to an x86 ECS task. It crashes at start with `exec format error`. Why, and what's the fix?

<details>
<summary>Show answer</summary>

The image was built for **arm64**, and the host CPU is **x86-64**, so the binary can't execute. Build with `docker build --platform linux/amd64` (or use a multi-architecture build, or run on Graviton arm64 hosts).

</details>

**Q2.** Why does the Dockerfile copy `requirements.txt` and run `pip install` *before* copying `app.py`?

<details>
<summary>Show answer</summary>

Docker reuses a layer only if the instruction and **all earlier layers** are unchanged. Dependencies change rarely and are slow to install; code changes constantly. Putting dependencies first keeps the slow layer **cached** across code edits.

</details>

**Q3.** `systemctl start myapp` works, but after a reboot the service isn't running. What did you forget?

<details>
<summary>Show answer</summary>

`systemctl enable myapp`. **`start`** runs the service now, and **`enable`** registers it to start at boot. They're independent.

</details>

**Q4.** Dave can't read `/home/jim/report.txt` even though the file is group-readable by his group. What else might block him?

<details>
<summary>Show answer</summary>

The **directory permissions**. Reading a file needs the **execute** bit on every directory in its path. If `/home/jim` is `700`, Dave can't traverse it, whatever the file's own mode says. (Also, group membership applies to *new* login sessions.)

</details>

**Q5.** Why is mounting `~/.aws` into the container acceptable on your laptop but wrong in production?

<details>
<summary>Show answer</summary>

It copies **long-lived or user-scoped credentials** into the container, so anything in it acts as *you*. In AWS, containers receive **short-lived credentials for a purpose-built role** (a task role or pod identity), scoped to exactly what that workload needs, with nothing stored in the image or on disk.

</details>

---

## What's Next? 🚀

We have a Linux toolkit and a container image. Time to run Linux for real. How do you launch an instance with no SSH port open, give it an identity through a role, mount the EFS file system from Post 07, and read its credentials safely?

👉 **[Post 10: EC2](content/aws/10-ec2.md)**: a private instance reached with Session Manager, an attached disk, EFS mounted over TLS, and the metadata service explained.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
