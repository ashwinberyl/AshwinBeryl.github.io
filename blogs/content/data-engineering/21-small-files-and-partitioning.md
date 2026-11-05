---
title: "Small Files and Partitioning — How Many Files Does a Run Write?"
date: 2026-11-02
tags: [data-engineering, pyspark, performance, small-files, partitioning, coalesce, repartition, iceberg, first-principles]
description: Part 3, post 3. A RepoSphere daily run decides how many files it writes without asking you. Learn the one rule behind the count, why coalesce(1) with a partitioned write still gives one file per day, when repartition helps and when it makes a skewed day worse, and how to size files so compaction has less to clean up.
---

# The Hidden File Count 📂

In [Post 20](content/data-engineering/20-joins-and-skew.md), we met the task that holds one key and slows the whole stage down. That was about **uneven** work.

This post is about the **amount of output**. Every RepoSphere run ends with a write, and the write decides how many files land on disk. You never type that number. It falls out of how many tasks held data when the write began.

Back in [Post 17](content/data-engineering/17-compaction-and-maintenance.md) we cleaned up small files **after** the damage was done. Today we ask the better question: *why were there so many in the first place, and can the run write fewer?*

> **A note on honesty:** I couldn't run Spark while writing this post, so there are **no timings** here. Every number below is either arithmetic you can check by hand or a file count that follows from a rule. All of them are quick for you to verify, and [Post 22](content/data-engineering/22-measure-before-tuning.md) is about how to measure properly.

---

## The Courier Analogy 🚚

Picture a warehouse. Each night, couriers arrive with deliveries. The rule is simple: **every courier makes their own trip, and brings a separate parcel for each shelf they're stocking.**

- The warehouse doesn't ask how many couriers *should* come. It gets however many were dispatched.
- A courier with one envelope still makes a full trip.
- A courier stocking two shelves makes two parcels.

Next month, someone has to find a customer's order by opening parcels. A thousand envelope-sized parcels is a slow month.

| Warehouse | Spark |
|---|---|
| A courier | A **task** in the write stage |
| A shelf | A **partition value** of the table, like one `event_date` |
| A parcel | One **file** on disk |
| Number of couriers dispatched | Number of **partitions** in the DataFrame at the moment of the write |

The fix isn't "fewer shelves". It's **dispatching the right number of couriers, each carrying a proper load.**

---

## The One Rule 📏

Here is everything you need, in one line:

> **Key insight:** A write produces **one file for each (task, partition value) pair that has rows**. A task with no rows for a value writes nothing for it.

So the total is bounded by arithmetic:

| What you write | Files from one run |
|---|---|
| Unpartitioned table, `n` tasks hold rows | About **`n`** files |
| Partitioned by day, `n` tasks, `d` days in the data | Anywhere from **`n`** up to **`n × d`** |
| Partitioned by day, rows clustered so each day sits in one task | Exactly **`d`**, one per day |

![One file per task per day it holds: no clustering, coalesce(1), and repartition by event_date](content/data-engineering/images/files_per_task_per_day.svg)

The "from `n` up to `n × d`" row is the sneaky one. If every task happens to hold rows from every day, you multiply. And which rows land in which task is **by chance** unless you say otherwise, so the exact count changes from run to run on the same data.

> **Why does Spark work this way?** A Parquet file is written by one task, start to finish. Tasks don't coordinate, and a file can't be shared between them. So the file count can't be smaller than the number of tasks that wrote something.

---

## Where Does the Task Count Come From? 🔢

You met this in [Post 19](content/data-engineering/19-reading-the-spark-plan.md): partitions come from two places.

| Where | How many | Control |
|---|---|---|
| **Reading files** | Input is split into chunks of up to `spark.sql.files.maxPartitionBytes` (default **128 MB**) | The file layout itself |
| **After a shuffle** (join, `groupBy`, window) | `spark.sql.shuffle.partitions` (default **200**), which AQE may merge down to fewer | A config, plus AQE |
| **After you ask** | Exactly what you request | `repartition(n)`, `coalesce(n)` |

You can ask any DataFrame how many partitions it holds. Here is a ten-row DataFrame built with a fixed number of slices, so the answers don't depend on your machine:

```python
ids = spark.range(0, 10, 1, 4)           # numbers 0..9 in 4 partitions

print("start         :", ids.rdd.getNumPartitions())
print("repartition(8):", ids.repartition(8).rdd.getNumPartitions())
print("repartition(2):", ids.repartition(2).rdd.getNumPartitions())
print("coalesce(2)   :", ids.coalesce(2).rdd.getNumPartitions())
print("coalesce(8)   :", ids.coalesce(8).rdd.getNumPartitions())
```

```
start         : 4
repartition(8): 8
repartition(2): 2
coalesce(2)   : 2
coalesce(8)   : 4
```

The last line is the lesson. **`coalesce` can only go down.** Ask for 8 and you keep your 4.

---

## `coalesce` vs `repartition` ⚖️

Both change the partition count. They do it in opposite ways.

| | **`coalesce(n)`** | **`repartition(n)`** | **`repartition(n, col)`** or **`repartition(col)`** |
|---|---|---|---|
| **Shuffle?** | **No.** A narrow step ([Post 19](content/data-engineering/19-reading-the-spark-plan.md)) | **Yes** | **Yes** |
| **Direction** | Only **down** | Up or down | Up or down |
| **Result** | Neighbouring partitions glued together, so sizes can be **uneven** | Rows dealt out round-robin, so sizes are **even** | Rows with the same `col` value go to the **same** partition |
| **Plan node** | `Coalesce 2` | `Exchange RoundRobinPartitioning(4)` | `Exchange hashpartitioning(event_date, 200)` |
| **Use for** | Cheaply shrinking the count right before a write | Evening out sizes, or changing the count up | **Clustering** rows so each key is written by one task |

Look at the plan nodes in a real session (only the relevant line is shown, and IDs vary by run):

```python
flat.coalesce(1).explain()
```

```
Coalesce 1
```

```python
flat.repartition(4).explain()
```

```
Exchange RoundRobinPartitioning(4), REPARTITION_BY_NUM, [plan_id=...]
```

> **Key insight:** The tag `REPARTITION_BY_NUM` means you asked for an exact number, so AQE **leaves it alone**. A plain `repartition("event_date")` carries no number, so AQE is free to merge small partitions afterwards.

### The `coalesce(1)` trap 🪤

`coalesce(1)` looks like the obvious way to get one output file. It's also the easiest way to wreck a job.

Because `coalesce` has **no shuffle**, there's no stage boundary where Spark could change the number of tasks. The whole stage, **including the read and every transformation before it**, collapses to that single task.

![coalesce(1) merges the whole stage into one task; repartition(1) keeps stage 1 parallel and adds an Exchange before a single writer](content/data-engineering/images/coalesce_vs_repartition_one.svg)

| | `coalesce(1)` | `repartition(1)` |
|---|---|---|
| Work before the write | Runs in **one task** | Runs in **many tasks** |
| Cost | Nothing extra to plan | One shuffle |
| Right when | The data is already tiny | The upstream work is heavy and you still want a single file |

For RepoSphere's nine-event sample it makes no difference. For a billion rows, `coalesce(1)` can turn a parallel job into a serial one, and nothing in the output tells you.

---

## Counting the Files You Actually Get 🧮

Let's check the rule on real files. First, ten rows in **one** partition, written four ways. Every run starts from a clean folder:

```python
import glob, os
from pyspark.sql import functions as F

def count_parquet(path: str) -> int:
    return len(glob.glob(f"{path}/*.parquet"))

one = spark.range(0, 10, 1, 1)                      # 10 rows, ONE partition

one.repartition(4).write.mode("overwrite").parquet("out/rr4")
one.coalesce(1).write.mode("overwrite").parquet("out/co1")

print("repartition(4):", count_parquet("out/rr4"))
print("coalesce(1)   :", count_parquet("out/co1"))
```

```
repartition(4): 4
coalesce(1)   : 1
```

Round-robin deals ten rows across four partitions as 3, 3, 2, 2, so none is empty and each task writes one file. That's a hand trace, and the rule gives the same answer.

Now a **partitioned** write, using the RepoSphere data that matters. Batch 2 from [Post 18](content/data-engineering/18-capstone-daily-run.md) has seven events on two days:

```python
flat2 = flatten_events(read_events(spark, "data/batch_2/events.jsonl"))

flat2.groupBy("event_date").count().orderBy("event_date").show(truncate=False)
```

```
+----------+-----+
|event_date|count|
+----------+-----+
|2024-03-01|3    |
|2024-03-02|4    |
+----------+-----+
```

Two days, so `d = 2`. Now write it two ways and count files per day folder:

```python
def files_per_day(path: str) -> None:
    for folder in sorted(glob.glob(f"{path}/event_date=*")):
        print(os.path.basename(folder), len(glob.glob(f"{folder}/*.parquet")))

(flat2.coalesce(1)
      .write.mode("overwrite").partitionBy("event_date").parquet("out/events_co1"))

(flat2.repartition("event_date")
      .write.mode("overwrite").partitionBy("event_date").parquet("out/events_clustered"))

print("coalesce(1):");              files_per_day("out/events_co1")
print("repartition(event_date):");  files_per_day("out/events_clustered")
```

```
coalesce(1):
event_date=2024-03-01 1
event_date=2024-03-02 1
repartition(event_date):
event_date=2024-03-01 1
event_date=2024-03-02 1
```

Same output, two very different routes.

- **`coalesce(1)`** gives **one task**, holding both days. The rule says one file per (task, day), so that's **two files**. Not one.
- **`repartition("event_date")`** puts all of a day's rows in the same task, so each day gets **exactly one** file.

> **Trap:** `coalesce(1)` does **not** mean "one file" once you add `partitionBy`. It means one **task**, which writes one file per partition value it holds. If a day has no rows, there's no file for it.

What if you don't cluster at all, and just write with four tasks?

```python
(flat2.repartition(4)
      .write.mode("overwrite").partitionBy("event_date").parquet("out/events_rr4"))
```

Seven rows go round-robin into four partitions as 2, 2, 2, 1, so all four tasks write. Each writes one file per day it holds, and a task has at most two days. So you get **at least 4 and at most 8** files, and which number you get depends on row order. That's the "from `n` to `n × d`" row of the table in action. For seven rows. Imagine it for a year.

---

## What a Year of Small Writes Costs 📆

Let's do the arithmetic on a hypothetical RepoSphere feed where **one day's data is 40 MB of Parquet**. The table holds one day per partition, written once a day, and each run writes `f` files into that day's partition:

| Files per daily run | Files after 365 days | Average file size |
|---|---|---|
| **1** | 365 | 40 MB |
| **4** | 1,460 | 10 MB |
| **200** (every shuffle partition writes something) | 73,000 | 0.2 MB |

> **Heads up:** These figures are **illustrative arithmetic**, not a measurement. The 40 MB day is an assumption, and 200 files a day is the worst case, with empty partitions writing nothing and AQE usually merging many of them. The point is the shape: file count scales with `f`, and file size shrinks by the same factor.

Why do file counts matter at read time? From the reader's side:

| Cost | What happens with many small files |
|---|---|
| **File opens** | Every file is opened and its footer read, whatever its size |
| **Planning** | The table's metadata lists every file, so planning gets slower |
| **Tasks** | Spark packs small files into tasks, and counts each file as costing at least `spark.sql.files.openCostInBytes` (default **4 MB**) of work |
| **Compression and skipping** | Tiny files give column statistics and compression less to work with |

That's the same list from Post 17. The difference is where we fix it.

---

## Writing to Iceberg: Let the Table Cluster ❄️

In [Post 11](content/data-engineering/11-catalogs-and-hidden-partitioning.md), we partitioned `events` by `days(created_ts)`. **Hidden partitioning** means the partition column isn't one of your DataFrame columns, so you can't write `repartition("event_date")` and expect it to match the table's layout exactly.

You don't have to. Iceberg's Spark writer can **ask Spark to cluster the rows by the table's partition** before it writes. That's the table property `write.distribution-mode`:

| Mode | What it does |
|---|---|
| `none` | No clustering. You get the `n` to `n × d` situation |
| `hash` | Shuffle rows by the table's partition value, so each task owns whole days |
| `range` | Sort-based clustering, useful when you also sort the table |

```python
spark.sql("""
    ALTER TABLE local.reposphere.events
    SET TBLPROPERTIES ('write.distribution-mode' = 'hash')
""")
```

> **Heads up:** The default for partitioned tables changed between Iceberg versions, so check the docs for the version you run before relying on it. Setting the property explicitly removes the doubt.

Iceberg also **rolls a file over once it hits a target size**: `write.target-file-size-bytes`, default **512 MB**. That matters for the next trap.

---

## The Big-Day Trap 🐘

Clustering by day sounds perfect: one task per day, one file per day. Now recall [Post 20](content/data-engineering/20-joins-and-skew.md).

Clustering is a shuffle by key, and a key is **one partition**. If one day carries 50 GB of events (a migration, a bot, a replay), then that day's task holds all 50 GB. You've created a **skewed write**: 199 tasks idle while one writes.

| Clustering by day when... | Result |
|---|---|
| Days are all similar and modest | Ideal. One decent file per day |
| One day is huge | One slow task. Without a size limit, one giant file |
| You *only* want to cap file size | Use a **size cap**, not a count |

The way out is to limit the **size** of the files rather than count them:

```python
# Plain Parquet: start a new file after this many rows
(df.write.option("maxRecordsPerFile", 1_000_000)
   .partitionBy("event_date").parquet("out/events"))
```

In Iceberg, the target file size above does this for you, and the one slow task writes several files in a row. It still writes them **serially**. If the slowness hurts, spread the day across tasks with a salt, the same trick as Post 20.

> **Key insight:** The goal isn't "one file per day". It's **files near the target size**, with tasks that carry about the same load.

---

## How Many Files Do You Want? 🎯

Work backwards from size:

```
files per partition ≈ ceil(partition size ÷ target file size)
```

| Partition size | Target | Files wanted |
|---|---|---|
| 40 MB | 128 MB | **1** |
| 2 GB | 256 MB | **8** |
| 50 GB | 512 MB | About **100** |

That's your `n`. For a one-off size, `repartition(n)` before the write gives even loads. For a table that gets a write every day, prefer table settings (distribution mode and target size) over a number you hardcode and forget.

A rough guide for target sizes is in the low hundreds of megabytes. Too small and you're back to the small files problem. Too big and a single task has too much to read or rewrite.

---

## Prevent or Repair? 🛠️

You now have two tools for the same problem, from opposite ends:

| | **Write well** (this post) | **Compact later** ([Post 17](content/data-engineering/17-compaction-and-maintenance.md)) |
|---|---|---|
| **When** | During every run | On a schedule |
| **Cost** | Usually a shuffle before the write | Reads and rewrites files you already wrote |
| **Fixes** | The count from *this* run | Accumulation across *many* runs |
| **Can't fix** | Files already on disk | Needless work the writer could have avoided |

You usually want **both**. A careful writer slows file growth, and compaction handles what remains, such as late-arriving data that touches an old day or a `MERGE` that rewrites a file.

> **Key insight:** Compaction fixes the past. Clustering and sizing at write time stop the problem repeating.

---

## Your File-Count Checklist ✅

1. **Count your tasks before the write:** `df.rdd.getNumPartitions()`.
2. **Apply the rule:** files ≈ tasks × partition values each holds. Bound it.
3. **Don't trust `coalesce(1)` for one file** once the table is partitioned.
4. **Use `repartition`, not `coalesce`,** when the upstream work is heavy.
5. **Cluster by the partition column** (or set `write.distribution-mode`) so each task owns whole partitions.
6. **Watch for the big day.** Cap by size, not just by count.
7. **Look at the result:** count files per partition, as in the helper above.
8. **Keep compaction on the schedule** for the files you can't prevent.

---

## Quick Quiz 🧠

**Q1.** A job shuffles with the default `spark.sql.shuffle.partitions` of 200 and then writes ten rows to an unpartitioned table. Can it write 200 files? Why or why not?

<details>
<summary>Show answer</summary>

No. A task with no rows has nothing to write, and ten rows can fill **at most ten** partitions, so you'd see **at most ten** files. (AQE also tends to merge those tiny partitions first.) The default of 200 is a ceiling set by configuration. It isn't a promise about output, and it's the **non-empty** tasks that write files.

</details>

**Q2.** You write batch 2 (seven rows, two days) with `coalesce(1)` and `partitionBy("event_date")`. How many files do you get, and why?

<details>
<summary>Show answer</summary>

**Two.** `coalesce(1)` leaves a single task, but a task writes one file for every partition value it holds. That task holds rows for both 1 March and 2 March, so it writes one file in each day's folder.

</details>

**Q3.** What's the difference between `coalesce(1)` and `repartition(1)` for the work **before** the write?

<details>
<summary>Show answer</summary>

`coalesce(1)` is a narrow step with no shuffle, so the whole stage up to the write, including the read and the transformations, runs in a **single task**. `repartition(1)` adds an `Exchange`, so the upstream stage keeps its parallelism, and only the final write runs in one task. Both give one output file for an unpartitioned table, and the second keeps the heavy work parallel.

</details>

**Q4.** Why can `repartition("event_date")` make a job **worse** on a day with 50 GB of events?

<details>
<summary>Show answer</summary>

Because it sends all rows with the same `event_date` to **one** partition, and so to one task. A huge day becomes a hot key, exactly like `dave` in Post 20: one slow task, and without a file-size limit one enormous file. Cap the file size (Iceberg's target size, or `maxRecordsPerFile`) and spread the day with a salt if the single writer is too slow.

</details>

**Q5.** A day produces 2 GB of Parquet and you want files near 256 MB. How many files should the write produce, and how do you get close to that number?

<details>
<summary>Show answer</summary>

About `ceil(2 GB ÷ 256 MB) = 8` files. Get there by making sure **8 tasks** each carry about a quarter-gigabyte, for example with `repartition(8)` before the write for a one-off, or by setting the table's distribution mode and target file size so every daily run is sized the same way. The result is approximate, because Parquet's compressed size doesn't track row count exactly.

</details>

---

## What's Next? 🚀

You can now predict how many files a write produces, explain why `coalesce(1)` isn't "one file" on a partitioned table, choose between `coalesce` and `repartition`, and size files from the target backwards.

One question is left, and it's the most important one in Part 3. All the advice so far came as a rule of thumb. How do you know a change actually made RepoSphere **faster**? Why is timing a nine-row sample worthless? And which knobs deserve your attention, and which are folklore?

👉 **[Post 22: Measure Before You Tune](content/data-engineering/22-measure-before-tuning.md)**

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
