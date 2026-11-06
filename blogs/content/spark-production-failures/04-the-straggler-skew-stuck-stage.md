---
title: "The Straggler — Skew and the Stuck Stage"
date: 2026-11-06
tags: [spark-production, pyspark, troubleshooting, skew, stuck-stage, aqe, salting, speculation, spark-ui, first-principles]
description: Part of Spark in Production. A RepoSphere job sits at "199 of 200 tasks" for hours and nothing has crashed. Learn to read the median-versus-max task metrics in the Spark UI, tell real skew apart from a bad machine, a memory-starved task or an unsplittable file, and fix it with AQE, a broadcast, or a deterministic salt, then prove the fix with a reconciliation check.
---

# The Job That Never Finishes ⏳

In [Post 03](content/spark-production-failures/03-executor-oom-and-container-killed.md), the failure was loud: an executor died and the log told you why. This one is the opposite.

Nothing crashes. No error. The Spark UI shows a stage at **199 of 200 tasks complete**, and it has said so for three hours. One task is still running. Everything else is idle, and you're paying for the idle machines.

This is the **straggler**: the single task that sets the length of the whole stage. In [Post 20 of the first series](content/data-engineering/20-joins-and-skew.md) we met skew from the *design* side: why one hot key overloads one partition. Today we meet it from the *oncall* side. You have a live job, a stuck stage, and a decision to make.

And here is the twist that makes this a troubleshooting post and not a repeat: **skew is only one of five reasons a single task is slow.** If you reach for the skew fix every time, you'll sometimes fix the wrong thing. The skill is telling them apart.

Same shape as always: **Symptom → What you see → Root cause → Fix → How to verify.**

---

## The Relay Race 🏃

A relay team of 200 runners. Each runs one leg, and the team's time is the moment the **last** runner crosses the line.

Now picture why one runner might finish late:

1. **Their leg is ten times longer than everyone else's.** Not the runner's fault. The course was cut badly. (That's **skew**.)
2. **They're carrying a backpack that's far too heavy** and keep stopping to rest. (That's **memory pressure**: garbage collection and spill.)
3. **They were handed a single enormous package that can't be shared out.** (That's an **unsplittable input file**.)
4. **They're healthy and the leg is normal, but they tripped and sprained an ankle.** (That's a **slow machine**: bad disk, noisy neighbour, flaky network.)
5. **They stop at every lamppost to phone a friend.** (That's a **per-row external call** inside the task.)

You would treat these five very differently. A coach who re-cuts the course for a runner who simply sprained an ankle has wasted a week.

| Relay | Spark |
|---|---|
| A runner | A **task** |
| The team's finish time | The **stage** duration (slowest task) |
| A badly cut course | A **hot key** in a shuffle |
| Sprained ankle | A slow or failing **executor / node** |

---

## Step 1: Read the Median and the Max 📏

Everything starts in one place. In the Spark UI, open **Stages**, click the stuck stage, and scroll to the **Summary Metrics for Completed Tasks**. (Tasks that are still running aren't in "completed", so if the stage is genuinely stuck, look at the **Tasks** table at the bottom and sort by Duration.)

You get a five-number summary for each metric: **min, 25th percentile, median, 75th percentile, max.**

![Three stages drawn as bars: healthy where all tasks are similar; a hot key where the slow task also read the most data; and a sick machine where the slow task read a normal amount of data](content/spark-production-failures/images/task_duration_shapes.svg)

The picture above is the whole method. Compare the slow task's **duration** with what it **read**:

| Metric to check | Skew looks like | Something else looks like |
|---|---|---|
| **Duration** | Max is many times the median | Same (this is just the symptom) |
| **Shuffle Read Size / Records** (or **Input Size** in a read stage) | Max is **also** many times the median | Max is about the **same as the median** |
| **GC Time** | Low or moderate | **High** → memory pressure |
| **Spill (Disk)** | Often only on the slow task | Heavy on **many** tasks → partitions too big overall |
| **Executor** column (Tasks table) | The slow task could be on any executor | Always the **same executor** → a sick machine |

> **Key insight:** The deciding question is always: **did the slow task do more work, or the same work more slowly?** More data in means skew or a big file. Same data in but slow means the environment or memory.

![Decision tree: is max duration far above the median; did that task read far more data; if yes check whether the stage reads files or follows an Exchange, if no check GC time and spill](content/spark-production-failures/images/slow_task_decision.svg)

---

## Step 2: Check Skew Before You Treat It 🔬

Before changing anything, look at the **key distribution** itself. It's one cheap query, and it works on the live data, not on guesses. On the RepoSphere sample:

```python
from pyspark.sql import functions as F

raw  = spark.read.json("data/events.jsonl")
flat = raw.select("event_id", F.col("actor.login").alias("actor_login"))

total = flat.count()
(flat.groupBy("actor_login").count()
     .withColumn("pct", F.round(F.col("count") / total * 100, 1))
     .withColumnRenamed("count", "events")
     .orderBy(F.desc("events"))
     .show())
```

```
+-----------+------+----+
|actor_login|events|pct |
+-----------+------+----+
|dave       |5     |55.6|
|jim        |3     |33.3|
|null       |1     |11.1|
+-----------+------+----+
```

Dave owns more than half of the nine rows. Now compare that to what an even spread would give. If a shuffle has **N** partitions, a perfectly even key would hold roughly `100 / N` percent of the rows. With the default `spark.sql.shuffle.partitions` of 200, that's **0.5%** per partition. A key holding 55.6% is over a hundred times its fair share. That's skew, and no hardware change fixes it.

> **Trap:** Look at the **null** row. Every row with a null join or group key lands in the **same** partition, because null hashes to one fixed place. In a real feed where events without an actor (deleted accounts, system events) are common, `null` can be your biggest key. Always read the null line before reading any other.

If the top key is only a little above its fair share, skew is **not** your problem. Go back to the decision tree.

---

## Step 3: The Fix Ladder for Skew 🪜

Start at the top. Each rung is cheaper to apply than the next, and you should stop as soon as the stage's max duration comes back near its median.

### Rung 1: Let AQE do it (joins only)

**Adaptive Query Execution** can split an oversized partition in a **sort-merge join** into smaller sub-partitions at runtime. It's on by default in recent Spark versions. The settings that control it, with their documented defaults:

| Setting | Default | Meaning |
|---|---|---|
| `spark.sql.adaptive.enabled` | `true` (Spark 3.2+) | Master switch for AQE |
| `spark.sql.adaptive.skewJoin.enabled` | `true` | Split skewed partitions in shuffle joins |
| `spark.sql.adaptive.skewJoin.skewedPartitionFactor` | `5.0` | A partition is skewed if it is more than this many times the **median** partition size |
| `spark.sql.adaptive.skewJoin.skewedPartitionThresholdInBytes` | `256MB` | ...and also bigger than this size |

Both conditions must hold. So a partition that is 20 times the median but only 40 MB is **not** treated as skewed, and AQE leaves it alone.

> **Trap:** AQE's skew handling applies to **joins**. A `groupBy(...).count()` or `agg(...)` over a hot key is **not** split by it. If your stuck stage is an aggregation, skip to rung 3.

### Rung 2: Avoid the shuffle (broadcast)

If one side of the join is small, broadcast it and the big side never shuffles, so it **cannot** skew. This is the same trick that kept `enrich_with_repo_state` safe in the first series:

```python
big.join(F.broadcast(small), "actor_login", "left")
```

The condition from [Post 02](content/spark-production-failures/02-driver-oom-collect-and-broadcast.md) applies: the small side must really be small, because it is built on the driver and copied to every executor.

### Rung 3: Salt the key (aggregations)

When AQE can't help and a broadcast isn't possible, change **the rule that assigns the lane**. For an aggregation the idea is two steps: aggregate *partially* on `(key, salt)` so Dave's rows spread across several tasks, then combine the partials on `key`:

```python
N_SALT = 8   # how many pieces to split a hot key into; pick it for YOUR data

salted = flat.withColumn(
    "salt", F.pmod(F.hash("event_id"), F.lit(N_SALT)))   # deterministic

partial = salted.groupBy("actor_login", "salt").count()

final = (partial.groupBy("actor_login")
                .agg(F.sum("count").alias("events"))
                .orderBy(F.desc("events")))

final.show()
```

```
+-----------+------+
|actor_login|events|
+-----------+------+
|dave       |5     |
|jim        |3     |
|null       |1     |
+-----------+------+
```

Same answer as the plain `groupBy`, which is the point. The salt only changes **where the work happens**, never the result.

Two details in that code are worth stopping on:

- **The salt is derived from `event_id`, not from `rand()`.** A `rand()` salt gives a row a *different* salt each time it's recomputed, for example when a stage is retried after a lost executor. A hash of a real column gives the same salt every time, so a retry reproduces exactly the same grouping. Prefer deterministic salts.
- **`pmod` keeps the value non-negative.** `F.hash` can return a negative integer, and `pmod` maps it into `0 .. N_SALT-1`.

> **Trap:** Salting works only when partial results **can be combined**: `count`, `sum`, `min`, `max`. It does **not** work directly for `countDistinct`, medians or percentiles, because you can't add two distinct-counts together. For those, deduplicate first or use approximate versions (`approx_count_distinct`).

For salting in a **join** (spreading the hot key on the big side and replicating the small side), the full recipe is in [Post 20 of the first series](content/data-engineering/20-joins-and-skew.md).

### What does *not* help

| Tempting action | Why it fails for a hot key |
|---|---|
| Raising `spark.sql.shuffle.partitions` | The hot key still hashes to **one** partition. You just have more empty ones |
| Adding more executors | The extra machines finish their tasks and sit idle. The slow task still runs on one core |
| Raising executor memory | May stop a crash, but the task is still the longest one. Speed is unchanged |

---

## When It Isn't Skew 🧯

Back to the relay race. If the slow task read a **normal** amount of data, here's what each of the other causes looks like and what to do.

| Cause | Tell-tale in the UI | Fix |
|---|---|---|
| **Memory pressure** | High **GC Time** or heavy **Spill** on the slow task, with a normal input size | The fix ladder in [Post 03](content/spark-production-failures/03-executor-oom-and-container-killed.md) |
| **Unsplittable input** | The stuck stage is the **first** stage, reading files. A few tasks read **huge** inputs while others read nothing | A single compressed file such as one big `.json.gz` can't be split, so one task reads all of it. Split or recompress it upstream into many smaller files |
| **A slow machine** | The slow tasks are always on **one executor** or host, with normal data sizes | Enable **speculation** (below), or exclude the node |
| **Per-row external call** | Low CPU and low GC, but long task time. Your code calls an API, database or service inside a UDF or `foreachPartition` | Batch the calls, add a cache, or move the lookup into a join |

### Speculation for slow machines

**Speculative execution** lets Spark launch a **duplicate** of a slow task on another executor and keep whichever finishes first. It's off by default:

```python
spark = (SparkSession.builder
    .config("spark.speculation", "true")
    .getOrCreate())
```

The documented defaults for how aggressive it is are `spark.speculation.quantile` of **0.75** (wait until 75% of tasks have finished) and `spark.speculation.multiplier` of **1.5** (a task is slow if it's more than 1.5 times the median).

> **Trap:** Speculation helps with **slow machines** and does **nothing** for skew. A duplicate of Dave's task has to process all the same rows, so it's just as slow, and you've now paid for it twice. It also means a task can run twice at once, so only enable it when your task output is safe to produce twice. Read the docs for your output committer and table format first.

For a node that keeps misbehaving, newer Spark versions can exclude it from scheduling after repeated failures with `spark.excludeOnFailure.enabled` (older versions called this `spark.blacklist.enabled`).

---

## Step 4: Prove It Worked ✅

Three checks, and the first matters most.

1. **Reconcile the result.** A skew fix must change *where* the work happens and never *what* the answer is. Run the old and new versions on the same input and compare totals. On the sample, the salted counts above add up to 5 + 3 + 1 = **9**, which equals the nine input events:

   ```python
   assert final.agg(F.sum("events")).first()[0] == flat.count()   # 9 == 9
   ```

2. **Re-read the stage metrics.** The max duration, and the max shuffle read, should now sit close to the median. If the slowest task is still far out, the hot key is still landing in one task. Check whether AQE actually applied by looking at the **SQL** tab's plan for skewed-partition split markers, or raise `N_SALT`.
3. **Check the busy day.** Skew depends on the data. A fix that is green on a quiet Tuesday can still stall on the day a bot floods one repo. Re-test on your busiest recorded day.

And as in every post of this series: **change one thing at a time**, so you know which rung worked.

---

## A Triage Cheat Sheet 📋

| What you see | Most likely cause | First thing to try |
|---|---|---|
| Stuck at "N−1 of N" after an `Exchange` and the slow task read far more | Hot key | Check the key distribution, then AQE, broadcast or salt |
| Stuck in the **first** stage, few tasks read huge inputs | Unsplittable file | Split the input files upstream |
| Slow task on the same executor every time, normal data size | Sick node | Speculation or exclusion |
| Slow task with high GC time or heavy spill | Memory pressure | [Post 03](content/spark-production-failures/03-executor-oom-and-container-killed.md) |
| Low CPU, long task, calls an API inside the task | External call | Batch or cache the calls |
| Aggregation skewed and AQE did nothing | AQE only splits **joins** | Salt the aggregation |
| Skew fix works, then breaks again next month | Hot key moved or grew | Monitor the top-key share, not just the runtime |

---

## Quick Quiz 🧠

**1. A stage shows 199 of 200 tasks complete for hours. What is the first thing you compare in the Spark UI, and why?**

<details>
<summary>Show answer</summary>

Compare the slow task's **duration** with how much it **read** (Shuffle Read Size, or Input Size in a read stage), against the median. If it read far more, it's skew or a big file. If it read a normal amount, the environment or memory is the cause. The fix for each is different, so this comparison decides what you do next.

</details>

**2. You raise `spark.sql.shuffle.partitions` from 200 to 2,000 and the stuck stage is exactly as slow. Why?**

<details>
<summary>Show answer</summary>

A hot key hashes to **one** partition, however many partitions exist. More partitions just creates more empty ones. The task holding the hot key still has the same rows to process. The fix must change how that key's rows are spread, such as AQE splitting, a broadcast, or a salt.

</details>

**3. Your stuck stage is a `groupBy("actor_login").count()` and AQE skew join is enabled, yet nothing improves. Why, and what do you try?**

<details>
<summary>Show answer</summary>

AQE's skew handling splits oversized partitions in **joins**, not in aggregations. For an aggregation, **salt** it: compute partial counts on `(actor_login, salt)`, then sum them per `actor_login`. Use a deterministic salt such as `pmod(hash(event_id), N)` so retries reproduce the same grouping.

</details>

**4. Why can't you salt a `countDistinct`, and what can you do instead?**

<details>
<summary>Show answer</summary>

Salting relies on combining partial results, and distinct counts can't be added: the same value could appear in two salt groups and be counted twice. Deduplicate first (for example `distinct` on the key and the value) and then count, or use `approx_count_distinct` when an approximate answer is acceptable.

</details>

**5. Speculation is on and the stage is still stuck on one task. When will speculation never help?**

<details>
<summary>Show answer</summary>

When the slowness comes from the **data** (skew or one huge input). The duplicate task gets the same rows and is just as slow. Speculation only helps when the slowness comes from the **machine or environment**, because the copy runs somewhere healthier.

</details>

---

## What's Next? 🚀

You can now tell a straggler from a crash, and a hot key from a sick machine, and you know the cheapest fix for each. One quiet assumption sat under all of it: that the shuffle itself works. Sometimes it doesn't. Executors disappear mid-shuffle, and the next stage can't find the data it needs.

👉 **[Post 05: FetchFailed and Shuffle Errors](content/spark-production-failures/05-fetch-failed-and-shuffle-errors.md)**

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
