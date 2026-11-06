---
title: "FetchFailed & Shuffle Errors — The Reader Fails, the Writer Is to Blame"
date: 2026-11-06
tags: [spark, production, troubleshooting, shuffle, fetch-failed, executors, spot-instances, first-principles]
description: A RepoSphere job fails with FetchFailedException on a stage that did nothing wrong. Learn why the error is raised on the reader but caused by the writer, how to find the executor that really died (OOM kill, spot preemption, heartbeat timeout, full disk), what the stage retry ladder does, which timeouts are worth touching, and how to size spark.sql.shuffle.partitions from first principles.
---

# The Stage That Did Nothing Wrong 🕵️

In [Post 04](content/spark-production-failures/04-the-straggler-skew-stuck-stage.md), one task ran for hours while its siblings finished in seconds. That was a **slow** failure. You could stare at it in the Spark UI and see the culprit.

Today's failure is meaner. The job was healthy for two hours. Then you get paged, and the log says this:

```
org.apache.spark.shuffle.FetchFailedException: Failed to connect to ip-10-0-3-17/10.0.3.17:7337
```

You open the failing stage. It is the **sessionization stage**: a window over `actor_login`, nothing exotic. The code is the same code that ran fine yesterday. The data is the same shape. Nothing in this stage looks broken.

And you'd be right. **This stage is innocent.** The exception is raised where the failure was *noticed*, not where it *happened*. Today you learn to follow it to the real crime scene.

---

## The Locker Room Analogy 🗄️

Picture a relay between two teams in a warehouse.

- **Team 1 (the map stage)** sorts parcels. Each worker puts the parcels for *each customer* into a **locker in their own corridor** and walks away.
- **Team 2 (the reduce stage)** is one worker per customer. Each walks the whole warehouse, opens a locker in *every* corridor, and collects their parcels.

Now a corridor floods and its lockers are destroyed. A Team 2 worker arrives, finds an empty wall, and shouts: **"I can't get my parcels!"**

That shout is `FetchFailedException`. The Team 2 worker did nothing wrong. The fault is the flooded corridor, and the only useful question is: **what happened to that corridor?**

| Warehouse | Spark |
|---|---|
| Sorting parcels into lockers | **Shuffle write**: map tasks partition their output by key |
| The lockers | Shuffle files on the **local disk of the executor** that wrote them |
| The customer's worker | A **reduce task** reading its partition |
| Walking to every corridor | **Shuffle read**: a fetch from every map output |
| A flooded corridor | A **lost executor**: killed, preempted, stalled or out of disk |

![Shuffle files live on the executor that wrote them, so a lost executor breaks every reader](content/spark-production-failures/images/shuffle_lockers_fetch_failed.svg)

> **Key insight:** Shuffle data is **not** stored somewhere safe. By default it sits on the local disk of the executor that produced it. If that executor goes away, its shuffle output goes with it, and every reduce task that needed a slice of it fails.

In RepoSphere, our `sessionize_actor_events` step does `partitionBy("actor_login")` ([Post 07 of the first series](content/data-engineering/07-sessionization-gaps-and-islands.md)). That forces a shuffle. Here is what a shuffle is *doing* on our nine events:

```python
events = read_events(spark, "data/events.jsonl")

(events.groupBy(F.col("actor.login").alias("login"))
       .count()
       .orderBy(F.desc("count"))
       .show())
```

```
+-----+-----+
|login|count|
+-----+-----+
| dave|    5|
|  jim|    3|
| null|    1|
+-----+-----+
```

Every row for `dave` (e01 to e05) has to end up with the **same reduce task**, wherever it was originally read. So each map task writes a piece for dave, a piece for jim and a piece for null, and each reducer collects its pieces from **all** the map tasks. That all-to-all fetch is exactly what breaks when one writer disappears.

---

## Symptom → Evidence → Cause 🔎

Run the same four-step routine every time. We'll use it for every failure in this series.

### Step 1: Read the whole message, bottom-up

`FetchFailedException` is a wrapper. The line that matters is what it says *about the host*, and the last `Caused by`.

```
Illustrative log excerpt (wording varies by Spark version)

org.apache.spark.shuffle.FetchFailedException: Failed to connect to ip-10-0-3-17/10.0.3.17:7337
    at org.apache.spark.storage.ShuffleBlockFetcherIterator.throwFetchFailedException(...)
    ...
Caused by: java.io.IOException: Failed to connect to ip-10-0-3-17/10.0.3.17:7337
Caused by: java.net.ConnectException: Connection refused
```

The useful facts: **which host** the data lived on, and **how** the connection failed.

| What the message says | What it points to |
|---|---|
| `Failed to connect to host:port` / `Connection refused` | The executor (or shuffle service) on that host is **gone** |
| `Connection reset by peer` | The remote side died or was killed **mid-transfer** |
| `Connection timed out` / `TimeoutException` | The remote executor is alive but **stalled** (long GC, overloaded) or the network is bad |
| `MetadataFetchFailedException: Missing an output location for shuffle N` | The driver has **no record** of where that map output lives (it was already marked lost) |
| `java.io.IOException: No space left on device` (on the writer) | The corridor's **disk filled up** while writing shuffle files |

### Step 2: Find the executor that disappeared

Open the **Executors** tab in the Spark UI and look for rows that are *dead* (or a count of "removed" executors). Then check the **driver log** around the same time for the removal reason:

```
Illustrative log excerpt (wording varies by cluster manager)

WARN  TaskSetManager: Lost task 12.0 in stage 5.0: ExecutorLostFailure
      (executor 7 exited caused by one of the running tasks)
      Reason: Container killed by YARN for exceeding memory limits.
ERROR TaskSchedulerImpl: Lost executor 7 on ip-10-0-3-17: <reason from the cluster manager>
```

The **reason** is the key. It is almost always one of five things:

| Reason for the lost executor | Typical evidence | Where to go next |
|---|---|---|
| **Killed for memory** (OOM or container limit) | `Container killed ... exceeding memory limits`, exit code 137 or 143 | [Post 03](content/spark-production-failures/03-executor-oom-and-container-killed.md): fix memory first |
| **Spot / preemptible instance reclaimed** | Many executors vanish **together**, reason mentions the node or instance, no OOM | Section below |
| **Heartbeat timeout** (stalled, usually GC) | `Executor heartbeat timed out after ... ms` | Timeouts section below |
| **Disk full** | `No space left on device` in executor logs | Add or clean local disk; shrink the shuffle |
| **Node or network failure** | Whole host disappears, nothing in the executor's own log | Infrastructure team; retries and blacklisting help |

### Step 3: Ask "who else was hit?"

One executor lost points at one bad task. **Many executors lost at once** points at the platform (spot reclaim, a node pool scale-down, a network blip). A pattern like "it fails at 02:00 every night" points at a scheduled event, not at your code.

### Step 4: Confirm the stage is actually retrying

In the **Stages** tab, a stage that was re-run shows up as `Stage 5 (retry 1)`. That tells you Spark already tried to recover on its own, and the question becomes: *why didn't recovery work?*

> **Trap:** Fixing the *reducer*. Teams see `FetchFailedException` in the sessionize stage, then spend a day tuning the window logic. The reader was never the problem. Always find the dead executor **first**.

---

## What Spark Does Next: The Retry Ladder 🪜

A normal task failure is retried on another executor, up to `spark.task.maxFailures` times (default 4). A **fetch failure is different**, because retrying the *reduce task* is pointless when the data it needs no longer exists.

Instead, Spark escalates to a **stage retry**:

![A fetch failure triggers a stage retry, not a task retry](content/spark-production-failures/images/fetch_failed_retry_ladder.svg)

1. The reduce task reports a fetch failure to the driver.
2. The driver **unregisters** the lost map output (and, depending on settings, the outputs on that executor or host).
3. The **map stage** is resubmitted, but only for the partitions whose output went missing.
4. The **reduce stage** is retried. The UI labels it `(retry 1)`.
5. If it keeps failing, the job is aborted after `spark.stage.maxConsecutiveAttempts` attempts (default 4).

Two consequences are worth remembering:

| Consequence | Why it matters |
|---|---|
| `FetchFailed` **doesn't** count against `spark.task.maxFailures` | Raising that setting does nothing for this error |
| Recovery recomputes upstream work | A late fetch failure can silently **double the runtime** of a job that "succeeded" |

> **Why "it succeeded but took twice as long" is a failure too:** If your nightly job usually finishes in an hour and sometimes in two, check the Stages tab for `(retry N)`. You may be losing executors every night and recovering without anyone noticing.

---

## Three Real Scenarios 🎬

### Scenario A: The OOM-killed executor

Dave's 02:00 RepoSphere run reads a fat day of events. During the sessionize stage, one executor exceeds its container limit and is killed. Its shuffle files disappear. Three other executors then report `FetchFailedException` against it.

- **Symptom:** FetchFailed in the stage *after* the heavy one
- **Evidence:** `Container killed ... exceeding memory limits` in the driver log; one dead executor
- **Root cause:** memory, not the shuffle
- **Fix:** the memory work in [Post 03](content/spark-production-failures/03-executor-oom-and-container-killed.md), plus smaller partitions
- **Verify:** zero dead executors on the next run, and no `(retry N)` in the Stages tab

### Scenario B: The spot instance that was reclaimed

The team moves executors onto cheap preemptible instances. Now a cloud provider takes some of them back mid-run. Nothing is wrong with memory, yet FetchFailed appears at random.

- **Symptom:** FetchFailed that moves around, a different executor each night
- **Evidence:** several executors removed at nearly the same timestamp, reason mentions the node, no OOM
- **Root cause:** shuffle data stored on machines that can vanish
- **Fix options:**

| Option | What it does | Cost or catch |
|---|---|---|
| Keep **drivers and a stable core** on on-demand nodes | The disappearing part is only the optional executors | Costs more than all-spot |
| **Graceful decommissioning** (`spark.decommission.enabled`, plus `spark.storage.decommission.shuffleBlocks.enabled`) | Executors migrate shuffle blocks before the node goes | Needs a cluster manager that sends a warning signal; the warning window is short |
| **External shuffle service** (`spark.shuffle.service.enabled`) | Shuffle files are served by a process that outlives the executor | Doesn't help if the whole **node** is reclaimed |
| A **remote shuffle service** | Shuffle data lives off the compute nodes entirely | Extra infrastructure to run |
| **Fewer, bigger shuffles** | Less data at risk per run | Needs query changes |

- **Verify:** run with executors deliberately removed in a test and confirm the stage retries cheaply

> **Heads up:** With **dynamic allocation** (`spark.dynamicAllocation.enabled`), idle executors are released on purpose. If they hold shuffle files that later stages need, you get the same symptom. You need either the external shuffle service or `spark.dynamicAllocation.shuffleTracking.enabled`, which keeps executors alive while their shuffle data is still needed.

### Scenario C: The executor that stopped answering

An executor is alive but stuck in a long garbage-collection pause. It misses its heartbeats. The driver decides it is dead. Readers trying to fetch from it time out.

- **Symptom:** `Executor heartbeat timed out after ... ms`, then FetchFailed with a timeout
- **Evidence:** huge GC time in the **Executors** tab; the same executor shows a very high task time
- **Root cause:** memory pressure again, expressed as a pause instead of a kill
- **Fix:** reduce memory pressure first (smaller partitions, fewer columns). Only then consider the timeouts below.

---

## The Timeouts: Useful, But Don't Hide Problems ⏲️

These real settings control how long Spark waits before giving up on a peer:

| Setting | What it controls | Default (Spark 3.x) |
|---|---|---|
| `spark.network.timeout` | General network and RPC wait; the umbrella for several others | `120s` |
| `spark.executor.heartbeatInterval` | How often an executor reports it's alive. Must stay **well below** `spark.network.timeout` | `10s` |
| `spark.shuffle.io.maxRetries` | How many times a **single** shuffle fetch is retried | `3` |
| `spark.shuffle.io.retryWait` | Wait between those fetch retries | `5s` |
| `spark.stage.maxConsecutiveAttempts` | How many stage retries before the job is aborted | `4` |
| `spark.excludeOnFailure.enabled` | Stop scheduling on executors and nodes that keep failing (named `spark.blacklist.*` before Spark 3.1) | `false` |

A common first aid for GC stalls is to raise `spark.shuffle.io.maxRetries` and `spark.shuffle.io.retryWait`, which gives a paused executor more time to recover before the reader gives up.

```python
spark = (SparkSession.builder
         .config("spark.shuffle.io.maxRetries", "10")
         .config("spark.shuffle.io.retryWait", "10s")
         .getOrCreate())
```

> **Trap:** Timeouts are **painkillers**. Raising them can make a symptom disappear while the cause (memory pressure, a skewed partition, a dying node) gets worse. Treat a bigger timeout as a **bridge** while you fix the real problem, and write down that you did it.

---

## Sizing the Shuffle: Too Many, Too Few 📐

Every shuffle has two numbers: **M** map tasks writing, **R** reduce partitions reading. The number of fetches is roughly **M × R**, because each reducer asks every mapper for its slice.

`R` is set by `spark.sql.shuffle.partitions` (default **200**). Our `groupBy` plan shows it:

```python
(events.groupBy(F.col("actor.login")).count()).explain()
```

```
Simplified from the physical plan:

HashAggregate(keys=[actor.login], functions=[count(1)])
+- Exchange hashpartitioning(actor.login, 200)
   +- HashAggregate(keys=[actor.login], functions=[partial_count(1)])
      +- Scan json
```

`Exchange hashpartitioning(..., 200)` is the shuffle, and **200** is `R`. Both extremes hurt:

| `R` is... | What goes wrong | How it looks |
|---|---|---|
| **Far too small** for the data | Each partition is huge, so tasks spill, run out of memory and get killed | OOM, lost executors, then FetchFailed |
| **Far too large** for the data | Millions of tiny fetches, huge scheduling overhead | Slow shuffle read, "Shuffle Read Blocked Time" high |
| **About right** | Partitions in the low hundreds of MB | Steady tasks, few retries |

Notice our nine-event sample: 200 partitions for 9 rows means almost every reduce task is **empty**. Fine on a laptop, wasteful on a cluster. That's exactly the problem AQE's partition coalescing solves.

### A way to pick `R`

Start from the shuffle size, not from a magic number:

```
R  ≈  total shuffle data  ÷  target partition size
```

For a hypothetical **2 TB** shuffle and a target of roughly **128 MB** per partition:

```
2 TB = 2 × 1024 × 1024 MB = 2,097,152 MB
2,097,152 MB ÷ 128 MB = 16,384 partitions
```

Look at the **Stages** tab for your *actual* "Shuffle Write" size, because the 2 TB here is only an example. And remember **M × R** if `M` is also large, the fetch count explodes.

| Setting | Role | Default (Spark 3.x) |
|---|---|---|
| `spark.sql.shuffle.partitions` | Initial `R` for SQL and DataFrame shuffles | `200` |
| `spark.sql.adaptive.enabled` | Let AQE re-plan using real shuffle sizes | `true` since Spark 3.2 |
| `spark.sql.adaptive.coalescePartitions.enabled` | Merge small shuffle partitions after the fact | `true` |
| `spark.sql.adaptive.advisoryPartitionSizeInBytes` | The target size AQE coalesces toward | `64MB` |

> **Why set `R` high and let AQE shrink it?** A generous starting `R` keeps partitions from being too big on an unexpectedly large day, and AQE coalesces the empties on a small day. That is more robust than hand-tuning one number for both.

Don't treat any of these numbers as final. Per [Post 22 of the first series](content/data-engineering/22-measure-before-tuning.md): change **one** setting at a time and check the Stages tab before and after.

---

## The Troubleshooting Checklist ✅

Next time a stage dies with `FetchFailedException`:

- [ ] Read the message for the **host** and the **connection error**
- [ ] Open **Executors**: is there a dead executor? When did it die?
- [ ] Read the driver log for the **removal reason** (OOM kill, preemption, heartbeat, disk)
- [ ] Count: one executor lost, or **many at once**?
- [ ] Check the Stages tab for `(retry N)`: did Spark recover, and at what cost?
- [ ] Fix the **cause** (memory, spot strategy, disk), not the reader
- [ ] Only then consider timeouts, retries and partition counts, **one at a time**
- [ ] Re-run and confirm: no dead executors, no `(retry N)`

---

## Quick Quiz 🧠

Commit to an answer before you open each one.

**Q1.** The sessionize stage fails with `FetchFailedException`. Is the bug in the sessionize code?

<details>
<summary>Show answer</summary>

**Almost certainly not.** The exception is raised in the stage that **reads** shuffle data. The cause is the executor that **wrote** it: it was killed, preempted, stalled or ran out of disk. Find the dead executor in the **Executors** tab and its removal reason in the driver log.

</details>

**Q2.** You raise `spark.task.maxFailures` from 4 to 20 to get past a FetchFailed. Does it help?

<details>
<summary>Show answer</summary>

**No.** A fetch failure doesn't count toward `spark.task.maxFailures`. Spark handles it with a **stage retry**, which is limited by `spark.stage.maxConsecutiveAttempts` (default 4). Raising the task limit changes nothing for this error.

</details>

**Q3.** Five executors disappear at the same second, none with an OOM message. What is the likely cause, and what are two ways to reduce the damage?

<details>
<summary>Show answer</summary>

A **platform event**, such as spot or preemptible instances being reclaimed or a node pool scaling down. Reduce the damage by keeping a stable core on on-demand nodes, enabling graceful decommissioning with shuffle block migration, using the external shuffle service (where whole nodes aren't lost), or moving shuffle data to a remote shuffle service.

</details>

**Q4.** Your job "succeeds" but now takes twice as long as last month. Where do you look for a hidden fetch-failure problem?

<details>
<summary>Show answer</summary>

The **Stages** tab, for stages labelled `(retry N)`, and the **Executors** tab for removed executors. A stage retry recomputes lost map output, so a job can recover from executor loss and still pay for the work twice.

</details>

**Q5.** Why is a very low `spark.sql.shuffle.partitions` risky, and why is a very high one wasteful?

<details>
<summary>Show answer</summary>

Too low: each partition is huge, so tasks spill to disk or exceed memory, executors get killed, and you end up with lost shuffle files and FetchFailed. Too high: the number of fetches (roughly maps × reducers) explodes, and the job drowns in tiny tasks and scheduling overhead. Start from **shuffle size ÷ target partition size**, and let AQE coalesce the rest.

</details>

---

## What's Next? 🚀

You can now trace a shuffle error back to the executor that really died. The next failure is quieter and more embarrassing: nothing crashes at all, but a few **bad lines** in the input (or a producer that changed a field) quietly spoil the output.

👉 **[Post 06: Bad Data and Schema Drift](content/spark-production-failures/06-bad-data-and-schema-drift.md)**

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
