---
title: "Executor OOM vs Container Killed — Two Deaths That Look Alike"
date: 2026-11-06
tags: [spark-production, pyspark, troubleshooting, memory, executor-oom, memory-overhead, yarn, kubernetes, first-principles]
description: Part of Spark in Production. A RepoSphere job loses executors at 3 a.m. and the log says "memory" but not which kind. Learn the difference between a JVM heap OutOfMemoryError and a container killed for exceeding its limit (exit 137), how an executor's memory is laid out, the four usual causes (giant partitions, giant rows, Python memory, too many cores), and a fix ladder you can verify in the Spark UI.
---

# The 3 A.M. Page 🔔

In [Post 02](content/spark-production-failures/02-driver-oom-collect-and-broadcast.md), the driver ran out of memory because we pulled too much data into one place. Today the victim is the other side of the cluster: the **executors**, the machines that do the real work.

Here's the page. RepoSphere's nightly job has run for months. Tonight it fails in the big shuffle stage. The alert says only:

> Job aborted. Stage failed 4 times. Executor lost.

You open the logs. Some runs show `java.lang.OutOfMemoryError`. Other runs show **no Java error at all**, just an executor that vanished, and a line about a container being killed.

Both are "out of memory". They are **not the same failure**, and the fix for one can do nothing for the other. This post teaches you to tell them apart in about two minutes, then walk the right fix ladder.

We'll follow the same shape every time: **Symptom → What you see → Root cause → Fix → How to verify.**

---

## The Moving Truck 🚚

Picture a moving company. Each truck has a **cargo area** and a **cab**. The cargo area holds your furniture. The cab holds the driver, the toolbox and the fuel.

A weigh station at the road checks the **whole truck**, not just the cargo.

Two different things can go wrong:

1. **The cargo area is packed solid.** The movers physically can't fit one more sofa in. They stop and say so. That's a **heap OutOfMemoryError**. The JVM itself raises the alarm.
2. **The truck is within its cargo limit, but the toolbox, the spare tyres and the driver's lunch push the total over the weigh limit.** The weigh station doesn't ask questions. It pulls the truck over and **takes the keys**. That's a **container kill**. Nobody inside raised an alarm. The process was simply ended from outside.

| Moving truck | Spark executor |
|---|---|
| Cargo area | **JVM heap** (`spark.executor.memory`) |
| Cab, toolbox, spare tyres | **Overhead**: Python workers, thread stacks, native and network buffers (`spark.executor.memoryOverhead`) |
| The weigh station | **YARN or Kubernetes**, enforcing the container limit |
| "We can't fit more" | `java.lang.OutOfMemoryError` |
| "You're over. Hand over the keys." | `SIGKILL`, exit code **137** |

The most useful sentence in this post: **a container kill leaves no Java error behind, because the JVM never got the chance to write one.**

---

## What's Inside One Executor 🔬

Before you can fix a memory problem you need a picture of where the memory goes.

![An executor container holds the JVM heap (execution plus storage, user memory, reserved) and a separate overhead area; the heap throws OutOfMemoryError when full, while the cluster kills the container when the total is over the limit](content/spark-production-failures/images/executor_container_layout.svg)

| Region | What lives there | Governed by |
|---|---|---|
| **Execution** | Shuffle buffers, sort and hash-join build data, aggregation state | Shares the **unified** pool with storage |
| **Storage** | Cached DataFrames (`.cache()`), broadcast copies | Same unified pool. Execution can evict storage, within limits |
| **User memory** | Your own objects, UDF data, the contents of a `collect_list` row | The rest of the heap |
| **Reserved** | A fixed slice (about 300 MB) Spark keeps for itself | Not configurable in normal use |
| **Overhead** | Python worker processes, thread stacks, native libraries, network buffers | `spark.executor.memoryOverhead` |

Two numbers worth knowing:

- The unified execution-plus-storage pool is `spark.memory.fraction` (default **0.6**) of the usable heap.
- The overhead default is a **fraction of executor memory with a floor**: roughly 10% of `spark.executor.memory`, but never less than 384 MiB. Some resource managers use a larger factor for Python jobs. Check your Spark version's docs rather than trusting a number from a blog.

The container the cluster enforces is **heap + overhead**. And if you set `spark.executor.pyspark.memory`, that's added on top as a limit for Python workers.

> **Key insight:** In PySpark, **Python is not in the heap.** Every Python UDF, every `pandas_udf`, every `toPandas` on the executor lives in separate worker processes, and they count against the **overhead**, not `spark.executor.memory`. That's why "I gave it more executor memory and it still got killed" is such a common PySpark story. You enlarged the cargo area. The toolbox was the problem.

---

## Step 1: Which Death Was It? 🕵️

Open the log of the **lost executor**, not just the driver's summary. The driver only sees "executor lost"; the executor's own log, or the resource manager's note about it, says why.

![Flowchart: search the executor log for OutOfMemoryError for a heap OOM, or for Container killed, exit code 137 or OOMKilled for a container over its limit, with a short fix list for each](content/spark-production-failures/images/which_death.svg)

### Death A: JVM heap `OutOfMemoryError`

**Symptom:** tasks fail, and retries on a *different* executor often fail the same way.

**What you see** (illustrative log excerpt, trimmed, the details differ per job):

```
java.lang.OutOfMemoryError: Java heap space
    at ...
```

A close cousin is `java.lang.OutOfMemoryError: GC overhead limit exceeded`, which means the JVM spent nearly all its time in garbage collection and recovered almost nothing. Same family, same direction: the **heap** is too small for what the task holds.

### Death B: container killed

**Symptom:** the executor disappears. Tasks that were running on it show up as failed with `ExecutorLostFailure`. There may be **no stack trace**.

**What you see on YARN** (illustrative log excerpt, the figures vary):

```
ExecutorLostFailure (executor 7 exited caused by one of the running tasks)
Reason: Container killed by YARN for exceeding memory limits.
X GB of Y GB physical memory used.
Consider boosting spark.executor.memoryOverhead.
```

**What you see on Kubernetes:** run `kubectl describe pod` on the executor pod and look at its last state:

```
Last State:  Terminated
  Reason:    OOMKilled
  Exit Code: 137
```

**Reading the exit code:** exit code **137** is 128 plus 9, meaning the process received `SIGKILL`. That's what a memory-limit enforcer sends. Exit code **143** is 128 plus 15, `SIGTERM`, a polite request to stop. On YARN you may see 143 as a *consequence* of something else going wrong, so use it as a clue and not a verdict, and read the diagnostics line next to it.

| | **Heap OOM** | **Container killed** |
|---|---|---|
| Who noticed? | The JVM | The resource manager (YARN, Kubernetes) |
| Java stack trace? | **Yes** | **Usually no** |
| Exit code | Often a normal JVM failure exit | **137** (`SIGKILL`) or a diagnostics note |
| Pod status on K8s | May stay `Running`, or `Error` | `OOMKilled` |
| Region that ran out | Heap | **Heap + overhead combined** |
| First config to look at | `spark.executor.memory`, partition size | `spark.executor.memoryOverhead`, Python usage |

> **Trap:** "Container killed" does not always mean the **overhead** is too small. A heap that is nearly full also pushes the total up. Treat the overhead hint in the YARN message as a *first thing to try*, not a proof. The real test is the next section: find out **what is big**.

---

## Step 2: Find What's Big 🔎

Memory problems almost always trace back to one of four things. Work through them in this order, because each is cheaper to fix than the next.

### Cause 1: A partition that is simply too big

A task processes one partition. If a partition is huge, one task needs huge memory, and all the tasks running at once on that executor are competing for the same pool.

Open the **Stages** tab, find the failing stage, and look at the task summary metrics: **Shuffle Read Size / Records**, **Input Size**, and the two spill columns, **Spill (Memory)** and **Spill (Disk)**.

> **Key insight:** **Spill is Spark's pressure valve, not a failure.** When execution memory runs out, Spark writes intermediate data to disk and carries on. A little spill is normal. A stage where *most* tasks spill heavily is telling you the partitions are too big for the memory they get. A stage where *one* task spills is telling you about skew, which is [Post 04](content/spark-production-failures/04-the-straggler-skew-stuck-stage.md).

How big is "too big"? It depends on your executor size, so there is **no universal number**. What you can do is compare: if the biggest shuffle-read partition is many times the median, you have skew. If they're all large, you need **more, smaller partitions**:

```python
spark.conf.set("spark.sql.shuffle.partitions", "800")   # example value, size it to YOUR data
```

You can change that setting at runtime. With **AQE** on (the default in recent Spark), Spark also coalesces tiny shuffle partitions toward `spark.sql.adaptive.advisoryPartitionSizeInBytes` (default **64 MB**), so raising the initial count is safe: AQE merges the small ones back.

### Cause 2: A giant **row**, not a giant partition

This one fools people, because splitting into more partitions doesn't help. Let's build it on RepoSphere. Product wants "all event ids per actor, in one row":

```python
from pyspark.sql import functions as F

raw = spark.read.json("data/events.jsonl")
flat = raw.select("event_id", F.col("actor.login").alias("actor_login"))

per_actor = (flat.groupBy("actor_login")
                 .agg(F.sort_array(F.collect_list("event_id")).alias("event_ids")))

per_actor.orderBy("actor_login").show(truncate=False)
```

```
+-----------+-------------------------+
|actor_login|event_ids                |
+-----------+-------------------------+
|null       |[e09]                    |
|dave       |[e01, e02, e03, e04, e05]|
|jim        |[e06, e07, e08]          |
+-----------+-------------------------+
```

Nine events in, three rows out. Fine on the sample. Now imagine Dave is a bot with hundreds of millions of events. The `dave` row would hold **hundreds of millions of ids inside one array**.

Here's the part that matters: **one key becomes exactly one row, and one row must fit inside one task's memory.** You can raise `spark.sql.shuffle.partitions` to a million and the `dave` row is still one row.

| Pattern | Why it explodes | Safer alternative |
|---|---|---|
| `collect_list` / `collect_set` on a hot key | One row holds the whole group | Aggregate instead (`count`, `min`, `max`), or keep one row per event and use a window |
| `explode` of a big array | Multiplies rows, and the exploded rows are wider | Filter before exploding |
| Wide rows (very long strings, big nested structs) | Fewer rows fit per partition | Select only the columns you need, early |
| `toPandas` or a pandas UDF on a whole group | The group must fit in Python memory | Use smaller groups, or push the logic into native Spark functions |

If the data you need is "how many events per actor", ask for that. A `count` for Dave is one number, whatever his traffic:

```python
flat.groupBy("actor_login").count()
```

> **Trap:** `collect_list` ordering is **not guaranteed**. We wrapped it in `sort_array` above so the output is deterministic. If you forget, the order of `event_ids` can change between runs, which is how a "flaky test" is born.

### Cause 3: Python and UDF memory

If your job uses Python UDFs, `pandas_udf`, or libraries that allocate natively (NumPy, Arrow, ML libraries), that memory is outside the heap. Symptoms: **container kills with a perfectly healthy-looking heap.** Check the **Executors** tab: if **GC Time** is low and the heap isn't full but executors still die, suspect the overhead.

Fixes, in order of preference:

1. Replace the UDF with built-in functions (they run inside the JVM and are also much faster to plan).
2. Shrink batch sizes for pandas UDFs (`spark.sql.execution.arrow.maxRecordsPerBatch`).
3. Raise `spark.executor.memoryOverhead`, or set `spark.executor.pyspark.memory` so Python has an explicit budget.

### Cause 4: Too many tasks sharing one executor

Every executor runs `spark.executor.cores` tasks **at the same time**, and they share one heap. Four cores means four partitions in memory together. If your executor has 8 GB and 4 cores, each task effectively gets a share of that, not 8 GB.

That makes **fewer cores per executor** a legitimate memory fix: the same cluster, the same data, but fewer concurrent tasks competing for the same pool. You trade some parallelism for headroom.

---

## Step 3: The Fix Ladder 🪜

Start at the top. **Stop at the first rung that works**, because every rung down costs more money or more speed.

| Rung | Change | Costs you | Use when |
|---|---|---|---|
| **1. Shape the data** | More partitions, drop columns early, filter before wide operations, replace `collect_list` with an aggregate | Nothing, it's usually faster | Almost always the root cause |
| **2. Fewer cores per executor** | Lower `spark.executor.cores` | Some parallelism per executor | Heap is the issue and partitions are already reasonable |
| **3. More overhead** | Raise `spark.executor.memoryOverhead` | A bigger container per executor | Container kills, Python or native memory suspected |
| **4. More heap** | Raise `spark.executor.memory` | A bigger container per executor | Genuine heap OOM after rungs 1 and 2 |

An example of setting rungs 3 and 4. These are **illustrative values, not recommendations**. Size them to your own job:

```python
spark = (SparkSession.builder
    .appName("reposphere-nightly")
    .config("spark.executor.memory", "8g")
    .config("spark.executor.memoryOverhead", "2g")
    .config("spark.executor.cores", "4")
    .getOrCreate())
```

In this example the container request is the 8 GB heap plus 2 GB overhead, so **10 GB per executor** from the cluster's point of view. Always add the two together when you check what you are actually asking for.

> **Trap:** Executor memory and cores are fixed **when the executors launch**. Setting them with `spark.conf.set(...)` in a running session does nothing for executors that already exist. Pass them at submit time (`--conf`), in your cluster config, or when building the session **before** it starts. `spark.sql.shuffle.partitions`, by contrast, *can* change at runtime.

> **Why not just raise memory first?** Because it hides the cause and bills you for it. A job that needs one giant partition to fit will need a *bigger* giant partition next month. Reshaping the data makes the job cheaper and more stable. Raising memory only buys time.

---

## Step 4: Prove It Worked ✅

A fix that wasn't verified is a hypothesis. After the change, check:

| Where | Look for |
|---|---|
| **Job result** | The same output as before. Re-run the nine-event sample and confirm your numbers still match the answer key |
| **Stages tab** | Spill columns smaller or gone, shuffle-read max much closer to the median |
| **Executors tab** | No lost executors, GC Time a small share of task time |
| **Cluster events** | No `OOMKilled` pods, no "Container killed" diagnostics |
| **Over several runs** | Memory failures often depend on the day's data. One green run on a quiet day proves little, so watch the busiest day too |

And one rule from [Post 01](content/spark-production-failures/01-the-debugging-loop.md): **change one thing at a time.** If you shrink partitions, drop cores *and* raise memory in the same run, a green result teaches you nothing about which one mattered.

---

## A Triage Cheat Sheet 📋

| What you see | Most likely cause | First thing to try |
|---|---|---|
| `OutOfMemoryError: Java heap space` in a shuffle stage | Partitions too big | More shuffle partitions, then check skew |
| `OutOfMemoryError: GC overhead limit exceeded` | Heap nearly full of live data | Same as above, then fewer cores |
| `Container killed by YARN ... memoryOverhead` | Heap plus off-heap over the limit | Check for Python UDFs, then raise overhead |
| `OOMKilled`, exit code 137 on Kubernetes | Same as above | Same as above |
| One task spills, the rest don't | Skew | [Post 04](content/spark-production-failures/04-the-straggler-skew-stuck-stage.md) |
| Fails only on a `collect_list` or `groupBy` with lists | Giant row | Replace with an aggregate |
| Fine for weeks, dies on one busy day | Data volume or one hot key grew | Look at that day's shuffle-read max vs median |

---

## Quick Quiz 🧠

**1. A log shows `java.lang.OutOfMemoryError: Java heap space`. Another run shows only "exit code 137, OOMKilled". Which one left a Java stack trace, and why?**

<details>
<summary>Show answer</summary>

The **heap OOM** did. The JVM was still alive when it ran out of room, so it raised the error and wrote a trace. A container kill is sent by the resource manager as `SIGKILL`, which ends the process immediately, so the JVM never gets to write anything.

</details>

**2. Your PySpark job uses a pandas UDF. You doubled `spark.executor.memory` and executors are still killed with "Container killed ... memoryOverhead". Why did the change not help?**

<details>
<summary>Show answer</summary>

Python workers run in **separate processes outside the JVM heap**, so their memory counts against the **overhead**, not `spark.executor.memory`. Doubling the heap enlarged the wrong region. Look at `spark.executor.memoryOverhead` or `spark.executor.pyspark.memory`, and consider replacing the UDF with built-in functions.

</details>

**3. A `collect_list` of event ids per actor fails on one actor. Raising `spark.sql.shuffle.partitions` to a huge number does not help. Why?**

<details>
<summary>Show answer</summary>

One key produces exactly **one row**, and that row (holding the whole list) must fit in one task's memory. More partitions only spread *different* keys apart. They can't split a single row. Replace the list with an aggregate such as `count`, or keep one row per event.

</details>

**4. The container request for an executor with `spark.executor.memory=8g` and `spark.executor.memoryOverhead=2g` is how large, and what must you also remember about when you set it?**

<details>
<summary>Show answer</summary>

About **10 GB** (heap plus overhead, plus `spark.executor.pyspark.memory` if you set it). And these settings must be given **when the executors launch** (submit-time `--conf` or session builder). Changing them with `spark.conf.set` in a running session doesn't resize executors that already exist.

</details>

**5. Heavy spill appears on every task in a stage. Is the job broken?**

<details>
<summary>Show answer</summary>

Not broken, but it is telling you something. Spill is Spark moving data to disk when execution memory runs out, which is a safety valve. Spill on **all** tasks means partitions are too big for the memory available, so try more (smaller) partitions or fewer cores per executor. Spill on **one** task points to skew instead.

</details>

---

## What's Next? 🚀

You can now tell a **heap OOM** from a **container kill**, find what's big, and climb the fix ladder in the cheapest order. But the second cause had a hint of something bigger: one key owning one giant chunk of work.

Next, we go after the failure that doesn't crash anything. It just sits there at "199 of 200 tasks" for hours.

👉 **[Post 04: The Straggler — Skew and the Stuck Stage](content/spark-production-failures/04-the-straggler-skew-stuck-stage.md)**

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
