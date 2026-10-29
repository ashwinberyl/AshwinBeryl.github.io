---
title: "Compaction and Maintenance"
date: 2026-10-29
tags: [data-engineering, apache-iceberg, pyspark, compaction, maintenance, lakehouse]
description: Count RepoSphere's data files, merge them with rewrite_data_files, and prove nothing changed. Covers the files and partitions metadata tables, compact_events, why compaction makes disk use go up first, expire_snapshots, remove_orphan_files, and the order to run them in.
---

# Spring Cleaning for Your Lakehouse 🧹

In [Post 16](content/data-engineering/16-schema-evolution.md), we added a column without touching a single data file. Nice trick. But look at what we have been doing the rest of the time.

Every load writes new files. Batch 1 wrote some. Batch 2 wrote more. A `MERGE` that updates a row rewrites the file holding it. Now run that **once a day for a year**:

- 365 loads, each touching at least one partition
- every file costs a file open, a manifest entry and some planning time
- every old snapshot keeps its files alive, so nothing ever leaves

That is the **small files problem**, and it is the quiet way a healthy table turns slow. Today's job is requirement 8: `compact_events`. And because compaction creates a new problem of its own, we also meet the rest of the cleanup kit.

---

## The Library Analogy 📚

Picture a library that receives a **new stack of loose pages every day**. Nobody binds them. A year later, finding everything about one topic means digging through 365 piles.

The librarian's fix is not to lose anything. She **binds the loose pages into proper books**, and writes the new books into the catalogue.

But there is a catch. The old loose pages cannot be thrown away yet, because **last Tuesday's catalogue still points at them**. Only when she retires the old catalogues can the loose pages go in the bin.

| Library | Iceberg |
|---|---|
| Loose pages | Many small data files |
| Binding pages into a book | **Compaction** (`rewrite_data_files`) |
| A catalogue edition | A snapshot |
| Retiring old catalogue editions | **Expiring snapshots** |
| Pages dropped on the floor, in no catalogue | **Orphan files** |

Three jobs, in that order. Binding first, retiring second, sweeping the floor last.

---

## Counting Files 🔢

You cannot fix what you have not measured. Iceberg exposes the table's own file list as a **metadata table**, the same trick we used for `.snapshots` in [Post 15](content/data-engineering/15-snapshots-and-time-travel.md):

```python
spark.table("local.reposphere.events.files").filter("content = 0").count()
```

- `files` lists the data files in the **current** snapshot only.
- `content = 0` keeps data files and skips delete files. Delete files only appear in merge-on-read tables ([Post 13](content/data-engineering/13-merge-into-in-depth.md)), and ours is copy-on-write, but the filter keeps the count honest if that ever changes.

For a per-day view, use the `partitions` table:

```python
(spark.table("local.reposphere.events.partitions")
      .select("partition", "record_count", "file_count")
      .orderBy("partition")
      .show(truncate=False))
```

```
+------------+------------+----------+
|partition   |record_count|file_count|
+------------+------------+----------+
|{2024-03-01}|6           |3         |
|{2024-03-02}|4           |1         |
+------------+------------+----------+
```

> **Heads up:** The row counts are fixed by our data: six events on 1 March (`e01` to `e06`) and four on 2 March (`e07` to `e10`). The **file counts are illustrative**. How many files a write produces depends on your Spark parallelism, so yours will differ. The shape is what matters: 1 March was written by three separate commits, so it has several files, and 2 March has one.

Four files holding ten rows. Silly at this scale. At a billion rows it is the difference between a one-second plan and a one-minute one.

---

## The Fix: `rewrite_data_files` 📦

Iceberg ships maintenance as **stored procedures**. You run them with `CALL`, through the `system` namespace of your catalog:

```python
result = spark.sql("""
    CALL local.system.rewrite_data_files(
        table   => 'reposphere.events',
        options => map('min-input-files', '2')
    )
""")

result.select("rewritten_data_files_count", "added_data_files_count").show()
```

```
+--------------------------+----------------------+
|rewritten_data_files_count|added_data_files_count|
+--------------------------+----------------------+
|3                         |1                     |
+--------------------------+----------------------+
```

Three small files in, one bigger file out. A few things are worth knowing about that call:

| Detail | What it means |
|---|---|
| `table => 'reposphere.events'` | The name **inside** the catalog. No `local.` prefix |
| Combines **within a partition** | Two days of data can never become fewer than two files |
| Default `min-input-files` is **5** | A group with fewer files is left alone |
| We set it to **2** | So a tiny demo table actually gets compacted |
| Commits one snapshot, operation `replace` | Same rows, reorganised |

![Compaction merges files inside a partition, never across](content/data-engineering/images/compaction_before_after.svg)

> **Trap:** On the default `min-input-files = 5`, our table would not change at all. 1 March has 3 files and 2 March has 1, so no group reaches 5, and the call quietly does nothing. That is valid behaviour. It is also why a spec test of "files after is smaller" can fail on a toy table. Lower the threshold to watch it work.

2 March has one file, which is below our threshold of 2, so it is left alone. Our expectation after the call: **two** files, one per day.

---

## `compact_events` 🧰

Now wrap it up the way the spec asks: count, compact, count again, return both numbers.

```python
from pyspark.sql import SparkSession

CATALOG = "local.reposphere"
EVENTS = f"{CATALOG}.events"


def count_data_files(spark: SparkSession, table: str) -> int:
    return spark.table(f"{table}.files").filter("content = 0").count()


def compact_events(spark: SparkSession) -> tuple[int, int]:
    before = count_data_files(spark, EVENTS)
    spark.sql("""
        CALL local.system.rewrite_data_files(
            table   => 'reposphere.events',
            options => map('min-input-files', '2')
        )
    """)
    after = count_data_files(spark, EVENTS)
    return before, after
```

Run it on the table after batch 2:

```python
print(compact_events(spark))
```

```
(4, 2)
```

> **Key insight:** `compact_events` is **idempotent** in effect. Run it again and there is nothing left to combine, so it returns `(2, 2)` and rewrites nothing. That is the same contract as every load in this series.

---

## Proving Nothing Changed 🕵️

Compaction rewrites your data. "It should be the same" is not a test. Prove it, and use time travel from [Post 15](content/data-engineering/15-snapshots-and-time-travel.md) to make it easy.

Grab the latest snapshot ID **before** you compact, then compare the old and new reads:

```python
pre_id = list_snapshots(spark, "events").collect()[-1]["snapshot_id"]

compact_events(spark)

before_df = read_events_as_of(spark, pre_id)
after_df = spark.table(EVENTS)

print(before_df.count(), after_df.count())
print(before_df.exceptAll(after_df).count(), after_df.exceptAll(before_df).count())
```

```
10 10
0 0
```

Same row count, and no row exists on one side that does not exist on the other. `exceptAll` is the right tool here because it respects duplicates, so it would also catch a row that had been silently doubled.

Compaction also leaves a footprint in the history:

```python
list_snapshots(spark, "events").show(truncate=False)
```

```
+-----------------------+-------------------+-------------------+---------+
|committed_at           |snapshot_id        |parent_id          |operation|
+-----------------------+-------------------+-------------------+---------+
|2026-10-27 09:00:14.512|3318704581192407731|null               |append   |
|2026-10-27 09:00:31.870|7459162230845513890|3318704581192407731|append   |
|2026-10-29 06:15:02.347|5530281847702916654|7459162230845513890|replace  |
+-----------------------+-------------------+-------------------+---------+
```

> **Heads up:** As in Post 15, the IDs and times are **illustrative**. The shape is real: a third snapshot, `operation = replace`, whose parent is the last load.

The `replace` operation is Iceberg saying "same data, different files". That is exactly the row we promised in the operation table last time.

---

## The Catch: Disk Use Goes Up ⬆️

Here is the surprising part. After compaction, the table is **bigger on disk**, not smaller.

Look back at the diagram. Files A, B and C are no longer in the *current* snapshot. But snapshots S1 and S2 still list them, and we promised time travel would keep working. So Iceberg cannot delete them. Right now the disk holds the old small files **and** the new big one.

| After step | Current snapshot reads | Files on disk |
|---|---|---|
| Batch 2 loaded | A, B, C, D | A, B, C, D |
| `rewrite_data_files` | E, D | A, B, C, D, **E** |
| `expire_snapshots` (old ones) | E, D | D, E |

Reads got faster at the second row. Storage only shrinks at the third. That third step is the next tool.

---

## `expire_snapshots`: Retiring Old History 🗓️

```python
spark.sql("""
    CALL local.system.expire_snapshots(
        table       => 'reposphere.events',
        older_than  => TIMESTAMP '2026-10-29 00:00:00',
        retain_last => 1
    )
""").show()
```

Iceberg drops every snapshot older than the cutoff (always keeping the newest `retain_last`), then deletes the data files that **only** those snapshots used. For us that is files A, B and C. D and E stay, because the current snapshot still uses them.

The result is a one-row table of counts, starting with `deleted_data_files_count`. We would expect `3` there. The remaining columns count manifest and metadata files, and their exact set depends on your Iceberg version.

And now the price. The day-1 snapshot is gone:

```python
read_events_as_of(spark, 3318704581192407731)   # raises an error: snapshot not found
```

> **Trap:** Expiry is a **policy decision**, not a cleanup chore. Every snapshot you expire is an audit question you can no longer answer. Remember the auditor from Post 15 asking what the table said at 10:30? Set retention to what your auditors need, **before** the first expiry job runs. A cutoff of "7 days" means last month's `VERSION AS OF` fails.

If you leave the arguments off, Iceberg falls back to table properties: `history.expire.max-snapshot-age-ms` and `history.expire.min-snapshots-to-keep`. Setting those once is safer than trusting every future caller to pass the right `older_than`.

---

## `remove_orphan_files`: Sweeping the Floor 🧽

Remember the crashed writer from [Post 10](content/data-engineering/10-why-table-formats-iceberg.md)? It wrote three Parquet files, died before the pointer swap, and left them on disk with no metadata pointing at them. Those are **orphan files**. `expire_snapshots` cannot find them, because no snapshot ever mentioned them.

```python
spark.sql("""
    CALL local.system.remove_orphan_files(
        table      => 'reposphere.events',
        older_than => TIMESTAMP '2026-10-26 00:00:00',
        dry_run    => true
    )
""").show(truncate=False)
```

With `dry_run => true` it **lists** what it would delete and removes nothing. On a healthy table the list is empty, and that is what we expect for ours.

> **Trap:** An orphan file and an **in-flight write** look identical. Both are files that no metadata mentions yet. If you sweep with `older_than` set to "now", you can delete files a running job is about to commit. That corrupts the table. The default margin is three days, and you should never go below the longest job you run. Always dry-run first.

---

## The Maintenance Order 📋

![The maintenance order: compact, expire, sweep](content/data-engineering/images/maintenance_order.svg)

| Procedure | What it does | When | Watch out |
|---|---|---|---|
| `rewrite_data_files` | Merges small files into bigger ones | After many small commits | Disk use rises until step 2 |
| `expire_snapshots` | Forgets old snapshots, deletes files only they used | After compaction | Time travel to expired snapshots is gone |
| `remove_orphan_files` | Deletes files no metadata references | Least often | Keep an `older_than` margin, dry-run first |
| `rewrite_manifests` | Reorganises the metadata layer itself | When planning slows on a table with very many commits | Usually not needed at our scale |

What about running compaction while the daily load is writing? That is the **optimistic concurrency** from Post 10. Two writers that touched different files both commit. If compaction rewrote the very file a `MERGE` was updating, one of them fails with an error and you re-run it on the new state. Nobody's update is silently lost, but schedule compaction away from the load window anyway.

---

## Pre-Flight Checklist 🛫

| Check | Why it matters |
|---|---|
| Counts files with `.files` filtered to `content = 0`? | Delete files are not data files |
| `min-input-files` lowered for the demo? | Default 5 leaves a toy table untouched |
| Files after is at most files before, and at least one per partition? | Compaction never merges across partitions |
| Row count and `exceptAll` both checked? | Proves the contents did not change |
| Latest snapshot operation is `replace`? | Confirms it was a reorganisation |
| Retention agreed **before** `expire_snapshots` runs? | Expiry destroys time travel |
| `remove_orphan_files` dry-run first, with a safe margin? | In-flight writes look like orphans |
| Order is compact, then expire, then sweep? | Each step frees what the previous one released |

---

## Quick Quiz 🧠

**Q1.** `events` has 3 files for 1 March and 1 file for 2 March. You run `rewrite_data_files` with the **default** options. What happens?

<details>
<summary>Show answer</summary>

Almost certainly nothing. The default `min-input-files` is 5, and no group of files reaches it. The call succeeds, rewrites zero files and adds no snapshot. Setting it to `2` combines the three 1 March files and leaves 2 March alone, which gives `(4, 2)`.

</details>

**Q2.** Why can `compact_events` never return `(4, 1)` on our table?

<details>
<summary>Show answer</summary>

Compaction only combines files **within a partition**. `events` is partitioned by `days(created_ts)` and holds two days of data, so the floor is one file per day, which is two files. Merging across days would break the partitioning that lets a query skip a whole day.

</details>

**Q3.** After `compact_events`, `before_df.exceptAll(after_df).count()` returns `0` and `after_df.exceptAll(before_df).count()` returns `0`. Why check **both** directions, and what does `0, 0` prove?

<details>
<summary>Show answer</summary>

One direction only shows that nothing was **lost**, or only that nothing was **added**. Checking both shows the two sides hold the same rows. `exceptAll` also respects duplicates, so a row that was doubled would show up on one side. Together with equal counts of `10` and `10`, it proves compaction changed the files and not the data.

</details>

**Q4.** You run compaction and then check disk usage. It went **up**. Did something go wrong?

<details>
<summary>Show answer</summary>

No, that is expected. The old small files are still referenced by older snapshots, so Iceberg cannot delete them, and the new big file now sits beside them. Space comes back only after `expire_snapshots` retires those snapshots. That is also why expiry comes **after** compaction in the maintenance order.

</details>

**Q5.** A teammate runs `remove_orphan_files` with `older_than` set to the current time, "to be thorough", while the nightly load is mid-write. What is the risk?

<details>
<summary>Show answer</summary>

The load's new Parquet files exist on disk but no metadata mentions them until the final pointer swap, so they look exactly like orphans. The sweep can delete them, and the load then commits metadata that points at **files that are gone**. The table is corrupted. Keep a margin longer than your longest job (the default is three days) and dry-run first.

</details>

---

## What's Next? 🚀

You can now keep a table fast and tidy: count the files, merge them, prove nothing changed, then retire the history you no longer need.

That was the last new tool. Next, we put the whole of Part 2 together: batch 1, schema change, batch 2, the same batch again, time travel and compaction in a single daily run, mapped to all eight requirements, with the full lab to check against.

👉 **[Post 18: Capstone: The Daily Run](content/data-engineering/18-capstone-daily-run.md)**

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
