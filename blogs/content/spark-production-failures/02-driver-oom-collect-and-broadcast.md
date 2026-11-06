---
title: "Driver OOM — collect(), toPandas() and Oversized Broadcasts"
date: 2026-11-06
tags: [spark, pyspark, debugging, driver, out-of-memory, collect, broadcast, production]
description: Post 2 of Spark in Production. RepoSphere's nightly job works on nine events and dies on nine billion. Learn the three ways a Spark driver runs out of memory (collect and toPandas, oversized broadcasts, too many files to list), how to recognise each in the logs and UI, the fix for each, and how to prove the fix worked.
---

# The Job That Worked on Nine Events 💥

In [Post 1](content/spark-production-failures/01-the-debugging-loop.md) we built a debugging loop. Now let's use it on the most common production failure there is.

Jim writes a reporting script for RepoSphere. It works perfectly on the nine-event sample. It works on a week of data. Then one night, six months in, the job dies, and the log ends with:

```
java.lang.OutOfMemoryError: Java heap space
```

Nothing is wrong with the executors. The cluster is nearly idle. The **driver**, the one process that holds the plan and the results, ran out of room.

**Symptom:** the *whole application* dies, often near the end, often after the heavy work finished.

---

## The Head Chef's Counter 🍳

Remember the kitchen from [Post 2 of the Data Engineering series](content/data-engineering/02-spark-from-first-principles.md): one **head chef** (driver), many **cooks** (executors). The cooks have big workbenches. The chef has **one small counter**.

Everything is fine while the cooks send back little plates: a count, a total, ten rows. It breaks the moment someone says *"just bring me every dish you made"*. A million plates arrive at one counter, and it collapses.

| Kitchen | Spark |
|---|---|
| Cooks' big benches | Executor memory, spread over many machines |
| The chef's small counter | **Driver memory**, one machine's heap |
| "Bring me everything" | `collect()`, `toPandas()` |
| Chef must read every supplier's price list before cooking | Broadcast join: the driver gathers the small side first |
| Chef must list every item in the pantry | Listing millions of files |

Three ways to overfill the counter. Let's take them one at a time.

![Three ways the driver's heap fills up](content/spark-production-failures/images/driver_memory_pressure.svg)

---

## Cause 1: `collect()` and `toPandas()` 📦

`collect()` pulls **every row of the result into the driver's memory**, as Python objects. `toPandas()` does the same, into a pandas DataFrame.

On RepoSphere's sample:

```python
rows = events.collect()
print(len(rows))
```

```
9
```

Nine rows. Fine. Now imagine the same line against the full event history. The driver must hold **every row at once**, and Python objects are much bigger than the compact format Spark stores them in.

### What you see

There are two fingerprints, and which one appears depends on a setting:

| Fingerprint | Where | Meaning |
|---|---|---|
| `Total size of serialized results of N tasks (X) is bigger than spark.driver.maxResultSize (Y)` | Driver log, a `SparkException` | Spark's **safety limit** tripped *before* memory ran out. Default for `spark.driver.maxResultSize` is `1g` |
| `java.lang.OutOfMemoryError: Java heap space` in the driver | Driver log | The result fit under the limit (or the limit is off), but the heap still ran out |

Here is an **illustrative log excerpt** of the first kind (sizes and task counts will differ):

```
org.apache.spark.SparkException: Job aborted due to stage failure:
  Total size of serialized results of 200 tasks (1030.0 MiB) is bigger than
  spark.driver.maxResultSize (1024.0 MiB)
```

> **Trap:** The tempting fix is `--conf spark.driver.maxResultSize=0` (unlimited). That removes the **guard rail**, not the problem. The next failure is a hard `OutOfMemoryError` that takes the driver down with no warning message at all.

### The fix: don't bring the data to the driver

Ask what the driver actually *needs*. Almost always the answer is *a summary*, so compute the summary on the executors:

```python
from pyspark.sql import functions as F

(events
    .groupBy(F.col("actor.login").alias("actor_login"))
    .count()
    .orderBy(F.desc("count"), "actor_login")
    .show())
```

```
+-----------+-----+
|actor_login|count|
+-----------+-----+
|       dave|    5|
|        jim|    3|
|       null|    1|
+-----------+-----+
```

Nine events became three rows **before** anything reached the driver. Dave has five events (e01 to e05), Jim has three (e06 to e08), and `e09` has no login.

Here is the decision table for the common situations:

| You wanted to... | Instead of `collect()` | Why it's safe |
|---|---|---|
| Look at some rows | `df.show(20)` or `df.limit(20).collect()` | Bounded: 20 rows, always |
| Get a total or a summary | `groupBy(...).agg(...)` first, then collect the small result | Result size is the number of groups, not the number of rows |
| Save the data | `df.write.parquet(path)` (or an Iceberg table) | Executors write directly; **the driver never sees the rows** |
| Loop over all rows in Python | `df.toLocalIterator()` | Streams **one partition at a time** instead of everything |
| Use pandas on a sample | `df.limit(10_000).toPandas()` or `df.sample(...)` | You choose the size, so it can't surprise you |

> **Key insight:** Before every `collect()` or `toPandas()`, ask: **"how big is this result, in the worst case?"** If you can't answer, you shouldn't call it yet. Put a `limit()` or an aggregation in front.

For `toPandas()` there's a bonus knob: setting `spark.sql.execution.arrow.pyspark.enabled` to `true` makes the transfer much more compact. It helps speed and memory, but it is **not** a license to convert unbounded data. The result still lands in one process.

---

## Cause 2: The Oversized Broadcast 📡

A **broadcast join** is the "send the small table to every cook" trick from [Post 20 of the Data Engineering series](content/data-engineering/20-joins-and-skew.md). The mechanics matter here: Spark first **collects the small side to the driver**, then **ships it to every executor**. So a broadcast table must fit in the driver *and* in each executor.

Spark only does this automatically when its size *estimate* is under `spark.sql.autoBroadcastJoinThreshold` (default 10 MB). The danger comes from two places:

| Danger | What happens |
|---|---|
| **A forced hint**: `F.broadcast(df)` | You are telling Spark "trust me, it's small." It stops checking. When the table grows, nothing stops it |
| **A wrong estimate** | Spark thinks a table is tiny (stale statistics, a filter it assumed was very selective) and broadcasts something large |

RepoSphere's `repo_changes` table is a textbook *good* broadcast candidate: three repos, five changes. But imagine it grows into a full history of every repository's changes for ten years, and the code still says:

```python
enriched = events_flat.join(F.broadcast(repo_changes_flat), "repo_id", "left")
```

The hint is a promise the data no longer keeps.

### What you see

| Where | Fingerprint |
|---|---|
| Driver log | `java.lang.OutOfMemoryError` while building the broadcast |
| Driver log | `SparkException: Cannot broadcast the table that is larger than 8GB` (Spark's hard ceiling) |
| Driver log | `Could not execute broadcast in 300 secs` (`spark.sql.broadcastTimeout` expired while collecting a too-large table) |
| **SQL tab** | A **BroadcastExchange** box whose data size is far bigger than you expected |

Exact wording varies a little between Spark versions, but the family is the same: the failure happens *during the broadcast*, before the join's real work.

### The fix

1. **Remove the forced `F.broadcast()`** and let Spark decide. If it picks a sort-merge join, the job gets slower but **stops crashing**.
2. If you need it, **lower or disable** the automatic threshold: set `spark.sql.autoBroadcastJoinThreshold` to `-1` to disable automatic broadcasting entirely.
3. Reduce the small side: **select only the columns the join needs** and **filter** it before the join.
4. Keep a **guard** in your code: broadcast only tables you've *measured*, and re-check as they grow.

> **Why not just give the driver more memory?** You can, and sometimes you should. But a broadcast is copied to *every* executor too, so an oversized one threatens the whole cluster, not just the driver. Fix the join strategy first.

---

## Cause 3: Too Many Files to List 🗂️

Before reading a folder of Parquet or JSON files, Spark has to know **what files exist**, and that list lives in the driver. A table made of **millions of tiny files** means millions of entries to list, hold and plan over.

You met this in [Post 21 of the Data Engineering series](content/data-engineering/21-small-files-and-partitioning.md) from the performance side. It has a failure side too:

| Symptom | Where |
|---|---|
| A long, silent pause *before any stage starts* | **Jobs** tab: nothing running, driver busy |
| Driver OOM or a long GC pause during planning | Driver log |
| Thousands of tiny tasks, each reading a few KB | **Stages** tab |

### The fix

| Fix | How |
|---|---|
| Write fewer, bigger files in the first place | Control partitions before the write (Post 21) |
| Compact what's already there | Iceberg's `rewrite_data_files` ([Post 17](content/data-engineering/17-compaction-and-maintenance.md)) |
| Don't scan what you don't need | Filter on the partition column so whole folders are skipped |
| A table format that tracks files in metadata | Iceberg keeps manifests instead of re-listing folders ([Post 10](content/data-engineering/10-why-table-formats-iceberg.md)) |

---

## Last Resort: A Bigger Counter 🛋️

Sometimes the driver legitimately needs more room: a big plan, a moderate broadcast, many partitions. Then raise it, **but know the rules**:

| Setting | Meaning | Gotcha |
|---|---|---|
| `spark.driver.memory` | Driver heap size | In **client mode** it must be set **before the driver JVM starts** (on `spark-submit` or in the launcher). Setting it inside your Python code after the session exists does nothing |
| `spark.driver.memoryOverhead` | Extra, non-heap memory for the driver process | Matters especially on Kubernetes and YARN, where the container limit includes it |
| `spark.driver.maxResultSize` | Cap on the total size of results sent to the driver | Raise modestly. Setting `0` removes the safety net |

```bash
spark-submit \
  --driver-memory 8g \
  --conf spark.driver.maxResultSize=2g \
  reposphere_job.py
```

The `8g` and `2g` above are **placeholders**: the right numbers depend on your result sizes and your cluster. Treat any increase as a *temporary patch* and still fix the cause.

---

## How to Verify the Fix ✅

Follow the loop from Post 1. A fix is verified when you can show all three:

| Check | What to look for |
|---|---|
| **The failing action no longer ships bulk data** | No `collect()` / `toPandas()` on unbounded data in the code; output is *written* or *aggregated* |
| **The UI agrees** | **Executors** tab, driver row: memory use and GC time are healthy during the run |
| **The answer is unchanged** | On the nine-event sample, the aggregate still shows dave 5, jim 3, null 1. On production, row counts match the source |

---

## Quick Quiz 🧠

**Q1.** A job fails with `Total size of serialized results of 200 tasks ... is bigger than spark.driver.maxResultSize`. A teammate suggests setting it to `0`. Why is that a bad fix?

<details>
<summary>Show answer</summary>

`0` means **unlimited**, which removes the guard rail but not the cause. The data is still being funnelled into one JVM, so the next failure is a hard `OutOfMemoryError` with no friendly message. The real fix is to **aggregate, limit, or write the data** instead of collecting it.

</details>

**Q2.** What is `toLocalIterator()` for, and how does it differ from `collect()`?

<details>
<summary>Show answer</summary>

It lets Python loop over every row while fetching **one partition at a time**, so the driver doesn't need to hold the whole result at once. `collect()` pulls *everything* into driver memory in one go. `toLocalIterator()` is slower, but its memory use is bounded by the size of a partition.

</details>

**Q3.** Why can a broadcast join crash the *driver*, when the "big" table is on the executors?

<details>
<summary>Show answer</summary>

Because Spark first **collects the small side to the driver**, then ships it to every executor. If the "small" table is actually large, the driver runs out of memory (or hits the 8 GB broadcast limit or the broadcast timeout) while building the broadcast, before the join starts.

</details>

**Q4.** The `repo_changes` table was safe to broadcast last year. The code still says `F.broadcast(repo_changes)`. What changed, and what should you do?

<details>
<summary>Show answer</summary>

The **table grew**, but the hint is a *forced* promise that it's small, so Spark never re-checks. Remove the hint and let `spark.sql.autoBroadcastJoinThreshold` decide, or keep it only after **measuring** the current size, and trim the table to the columns and rows the join needs.

</details>

**Q5.** You set `spark.driver.memory` to `8g` inside your Python code, after creating the `SparkSession`, in client mode. Nothing improves. Why?

<details>
<summary>Show answer</summary>

In client mode the driver JVM is **already running** when your code executes, so its heap size is fixed. `spark.driver.memory` has to be given at launch, for example `spark-submit --driver-memory 8g` or in the launcher's configuration.

</details>

---

## What's Next? 🚀

The driver is one machine. The **executors** are many, and they run out of memory in a different, sneakier way: sometimes Spark raises a clean `OutOfMemoryError`, and sometimes the cluster simply **kills the container** with no Java error at all.

👉 **[Post 3: Executor OOM and the Container That Got Killed](content/spark-production-failures/03-executor-oom-and-container-killed.md)**

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
