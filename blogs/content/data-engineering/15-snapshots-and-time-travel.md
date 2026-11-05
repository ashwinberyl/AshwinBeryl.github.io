---
title: "Snapshots and Time Travel"
date: 2026-10-27
tags: [data-engineering, apache-iceberg, pyspark, snapshots, time-travel, lakehouse]
description: Read RepoSphere's tables as they were. Covers the snapshots metadata table, list_snapshots, read_events_as_of, the three ways to time travel, why snapshot time and valid time are different questions, and the traps around counting snapshots and expiry.
---

# Git Log for Your Tables ⏳

In [Post 14](content/data-engineering/14-incremental-scd2.md), batch 2 closed `c1` at 10:00 and slotted in the late change `c2`. The table now says repo 101 was **private** at 10:30.

An auditor walks over and asks:

> *"After batch 1, before the late change arrived, what did the table say about repo 101 at 10:30?"*

With a plain Parquet folder, that answer is gone. The files were overwritten, and the old state lived only in someone's memory. With Iceberg, every commit left its old version behind, and we peeked at that in [Post 10](content/data-engineering/10-why-table-formats-iceberg.md).

Today we do it properly. We list the history, pick a version, and read the table exactly as it was. That is requirements 5 and 7: `list_snapshots` and `read_events_as_of`.

---

## It's `git log` for Data 🌳

You already know this model if you use git.

| git | Iceberg |
|---|---|
| A commit | A **snapshot**: the complete state of the table after one write |
| `parent` of a commit | `parent_id` of a snapshot |
| `git log` | The `snapshots` metadata table |
| `git show <sha>` | `VERSION AS OF <snapshot_id>` (read-only) |
| `git revert` / reset | `rollback_to_snapshot` |
| `git gc` | Snapshot expiry (Post 17) |

One difference matters. A snapshot is not a diff. It is a **complete** list of the data files that made up the table at that moment. Reading an old snapshot does not replay anything. You just follow a different pointer.

![Snapshot chains for events and repo_dim](content/data-engineering/images/snapshot_timeline.svg)

---

## The Metadata Tables 🔍

Every Iceberg table has read-only **metadata tables**. You reach them by adding a suffix to the table name:

| Suffix | One row per | Useful columns |
|---|---|---|
| `.snapshots` | Snapshot | `committed_at`, `snapshot_id`, `parent_id`, `operation`, `summary` |
| `.history` | Time the current snapshot changed | `made_current_at`, `snapshot_id`, `is_current_ancestor` |
| `.files` | Data file in the **current** snapshot | `file_path`, `record_count`, `content` |
| `.partitions` | Partition | `partition`, `record_count`, `file_count` |

`.snapshots` is today's table. `.files` is the star of [Post 17](content/data-engineering/17-compaction-and-maintenance.md).

---

## `list_snapshots` 📜

The spec asks for four columns, oldest first:

```python
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

CATALOG = "local.reposphere"


def list_snapshots(spark: SparkSession, table: str) -> DataFrame:
    return (spark.table(f"{CATALOG}.{table}.snapshots")
                 .select("committed_at", "snapshot_id", "parent_id", "operation")
                 .orderBy("committed_at"))
```

Run the three loads from the earlier posts (batch 1, batch 2, batch 2 again), then look at `events`:

```python
list_snapshots(spark, "events").show(truncate=False)
```

```
+-----------------------+-------------------+-------------------+---------+
|committed_at           |snapshot_id        |parent_id          |operation|
+-----------------------+-------------------+-------------------+---------+
|2026-10-27 09:00:14.512|3318704581192407731|null               |append   |
|2026-10-27 09:00:31.870|7459162230845513890|3318704581192407731|append   |
+-----------------------+-------------------+-------------------+---------+
```

> **Heads up:** Snapshot IDs are random 64-bit numbers and the times are when *you* ran the job. The values above are **illustrative**: the shape is real, the digits are not. Yours will differ.

Three things to read off it:

- **`parent_id`** links each snapshot to the one before. The first has none. That is the chain.
- **Two rows, not three.** The batch 2 re-run returned before its MERGE ([Post 13](content/data-engineering/13-merge-into-in-depth.md)), so it committed nothing.
- **`operation`** tells you what kind of commit it was.

| `operation` | What happened | Where you meet it |
|---|---|---|
| `append` | Only new files were added | Insert-only MERGE on `events` |
| `overwrite` | Files were replaced | A MERGE that updates rows, such as `repo_dim` in batch 2 |
| `delete` | Files were removed | `DELETE FROM` |
| `replace` | Same rows, reorganized | Compaction, [Post 17](content/data-engineering/17-compaction-and-maintenance.md) |

Now `repo_dim`, where batch 2 *updated* `c1`:

```python
list_snapshots(spark, "repo_dim").show(truncate=False)
```

```
+-----------------------+-------------------+-------------------+---------+
|committed_at           |snapshot_id        |parent_id          |operation|
+-----------------------+-------------------+-------------------+---------+
|2026-10-27 09:00:16.204|8021355469172034418|null               |append   |
|2026-10-27 09:00:33.441|1274890326651873092|8021355469172034418|overwrite|
+-----------------------+-------------------+-------------------+---------+
```

Batch 1 only inserted rows, so it is an `append`. Batch 2 rewrote the file that held `c1`, so it is not.

> **Trap:** Don't write logic that depends on **how many** snapshots exist. Whether a no-op write still commits depends on the operation and the Iceberg version. A schema change ([Post 16](content/data-engineering/16-schema-evolution.md)) creates none at all. Our count of two is a fact about *our* code. Read snapshot IDs from the table, never assume them.

A cheap sanity check that the chain is intact:

```python
snaps = list_snapshots(spark, "events").collect()

assert snaps[0]["parent_id"] is None
assert all(b["parent_id"] == a["snapshot_id"] for a, b in zip(snaps, snaps[1:]))
print("chain ok:", len(snaps), "snapshots")
```

```
chain ok: 2 snapshots
```

---

## Reading an Old Version ⏪

Iceberg gives you three ways in:

| Style | Example | Use when |
|---|---|---|
| By snapshot id (SQL) | `... VERSION AS OF 3318704581192407731` | You know exactly which commit |
| By time (SQL) | `... TIMESTAMP AS OF '2026-10-27 09:00:20'` | "As the table stood at this moment" |
| By snapshot id (reader) | `.option("snapshot-id", id)` | Inside Python code, no string building |

`TIMESTAMP AS OF` picks the snapshot that was **current** at that moment: the latest commit at or before it. The timestamp is read in the session time zone, which is why [Post 04](content/data-engineering/04-flattening-and-timestamps.md) pinned ours to UTC.

> **Trap:** A timestamp earlier than the very first commit has no snapshot to point at, so the query fails with an error. It does not return an empty table.

Our function uses the reader form:

```python
EVENTS = f"{CATALOG}.events"


def read_events_as_of(spark: SparkSession, snapshot_id: int) -> DataFrame:
    return (spark.read.format("iceberg")
                 .option("snapshot-id", snapshot_id)
                 .load(EVENTS))
```

Grab the first snapshot's ID from `list_snapshots`. `first()` returns a `Row`, and indexing it by name gives a plain Python `int`:

```python
s1 = list_snapshots(spark, "events").first()["snapshot_id"]

then = read_events_as_of(spark, s1)
now = spark.table(EVENTS)

then.orderBy("created_ts").show(truncate=False)
print(then.count(), len(then.columns), now.count())
```

```
+--------+----------------+-------------------+----------+-------+-----------+
|event_id|event_type      |created_ts         |event_date|repo_id|actor_login|
+--------+----------------+-------------------+----------+-------+-----------+
|e01     |pushevent       |2024-03-01 09:50:00|2024-03-01|101    |dave       |
|e02     |pullrequestevent|2024-03-01 10:10:00|2024-03-01|202    |dave       |
|e05     |pushevent       |2024-03-01 10:15:00|2024-03-01|202    |jim        |
|e03     |issuesevent     |2024-03-01 10:40:00|2024-03-01|101    |dave       |
|e04     |pushevent       |2024-03-01 11:20:00|2024-03-01|101    |dave       |
+--------+----------------+-------------------+----------+-------+-----------+
5 6 10
```

Five rows, six columns, while the live table has ten. Even though `e03` appears twice in the batch 1 file, only one copy was ever stored ([Post 12](content/data-engineering/12-idempotent-loads.md)).

A time-travel read gives you that snapshot's rows **and that snapshot's schema**. When we add `actor_id` in Post 16, this call will still return six columns, because that column did not exist at S1.

### What changed between the two? 🔎

Two DataFrames plus `exceptAll` answer "what did batch 2 add?":

```python
now.exceptAll(then).orderBy("created_ts").show(truncate=False)
```

```
+--------+----------------+-------------------+----------+-------+-----------+
|event_id|event_type      |created_ts         |event_date|repo_id|actor_login|
+--------+----------------+-------------------+----------+-------+-----------+
|e06     |pushevent       |2024-03-01 23:40:00|2024-03-01|101    |jim        |
|e07     |issuesevent     |2024-03-02 09:05:00|2024-03-02|202    |jim        |
|e08     |pushevent       |2024-03-02 09:45:00|2024-03-02|303    |meera      |
|e09     |pullrequestevent|2024-03-02 10:00:00|2024-03-02|101    |dave       |
|e10     |pushevent       |2024-03-02 10:30:00|2024-03-02|999    |null       |
+--------+----------------+-------------------+----------+-------+-----------+
```

Five new events, including the late `e06` that belongs to 1 March but only arrived in batch 2. Nothing in S1 was touched, because snapshots are immutable.

---

## Two Kinds of Time 🕰️

Back to the auditor. We have two time axes, and they answer different questions.

| | Valid time | Snapshot time |
|---|---|---|
| Question | What was true **in the world**? | What did **our table say**? |
| Lives in | `valid_from` / `valid_to` columns | The snapshot you read |
| Set by | The data itself (SCD2, [Post 06](content/data-engineering/06-scd-type-2.md)) | When we committed |
| Late data | Rewrites the past of this axis | Never rewrites an old snapshot |

Ask both at once: *who was repo 101 at 10:30 on 1 March, according to each version of the table?*

```python
s1 = list_snapshots(spark, "repo_dim").first()["snapshot_id"]
REPO_DIM = f"{CATALOG}.repo_dim"

QUERY = """
    SELECT change_id, repo_name, visibility
    FROM {source}
    WHERE repo_id = 101
      AND valid_from <= TIMESTAMP '2024-03-01 10:30:00'
      AND (valid_to IS NULL OR valid_to > TIMESTAMP '2024-03-01 10:30:00')
"""

spark.sql(QUERY.format(source=f"{REPO_DIM} VERSION AS OF {s1}")).show(truncate=False)   # after batch 1
spark.sql(QUERY.format(source=REPO_DIM)).show(truncate=False)                            # now
```

```
+---------+---------+----------+
|change_id|repo_name|visibility|
+---------+---------+----------+
|c1       |alpha-api|public    |
+---------+---------+----------+

+---------+---------+----------+
|change_id|repo_name|visibility|
+---------+---------+----------+
|c2       |alpha-api|private   |
+---------+---------+----------+
```

Same question, same valid time, two answers. After batch 1 the table said **public**, because `c2` had not arrived. Now it says **private**.

![Same question, two snapshots](content/data-engineering/images/two_kinds_of_time.svg)

Neither answer is a bug. Both are true statements about what the table said at that point. That is exactly what an auditor needs: *"our report on 1 March used snapshot S1, and here it is."*

> **Key insight:** SCD2 lets you ask what was true at a time in the world. Snapshots let you ask what you *believed* at a time in the pipeline. A late change moves the first answer and never the second.

---

## Undoing a Bad Load ↩️

Suppose a bad batch lands. Time travel reads are read-only, but Iceberg can make an old snapshot **current** again:

```sql
CALL local.system.rollback_to_snapshot('reposphere.events', 3318704581192407731)
```

Readers then see S1 as the live table. The newer snapshot is still listed, so you can inspect what went wrong. After a rollback, re-running a batch is safe, thanks to idempotent loads.

> **Trap:** Time travel is not free forever. Every snapshot pins its data files on disk. Once you **expire** a snapshot ([Post 17](content/data-engineering/17-compaction-and-maintenance.md)), `VERSION AS OF` that ID fails and its exclusive files can be deleted. Decide how much history auditors need *before* you set the retention.

---

## Pre-Flight Checklist 🛫

| Check | Why it matters |
|---|---|
| `list_snapshots` reads `.snapshots` and sorts by `committed_at`? | The first row must be the oldest |
| First `parent_id` null, each later one equals the previous `snapshot_id`? | Proves the chain is intact |
| Snapshot IDs read from the table, never hard-coded? | They are random and differ every run |
| Time travel uses the reader option or `VERSION AS OF`? | Not a filter on `committed_at` in your own data |
| Code does not assume a fixed number of snapshots? | No-op writes and schema changes vary |
| Session time zone is UTC when using `TIMESTAMP AS OF`? | The string is interpreted in that zone |

---

## Quick Quiz 🧠

**Q1.** Batch 2 is loaded a second time. Does `list_snapshots(spark, "events")` gain a row, and why?

<details>
<summary>Show answer</summary>

No. `upsert_events` counts the genuinely new rows first, finds zero, and returns before running the MERGE. No write means no commit, so no snapshot. This is a property of our code, not a guarantee from Iceberg, so don't hard-code "two".

</details>

**Q2.** Why does `repo_dim`'s second snapshot show `overwrite` while `events`' second shows `append`?

<details>
<summary>Show answer</summary>

Batch 2's MERGE into `repo_dim` **updated** `c1`, so the data file holding it was replaced (copy-on-write). The `events` MERGE was insert-only, so it only added new files.

</details>

**Q3.** `read_events_as_of(spark, s1)` returns how many rows and columns, and why not 6 rows?

<details>
<summary>Show answer</summary>

Five rows and six columns. The batch 1 file has six lines, but `e03` appears twice, and the load deduplicates before writing. S1 only ever contained five distinct events.

</details>

**Q4.** After batch 2, a colleague asks "who owned repo 101 at 10:30?" Why might two correct reports disagree?

<details>
<summary>Show answer</summary>

They read different snapshots. A report built from S1 says `public` (`c1` covered 10:30). A report built after batch 2 says `private`, because the late change `c2` now covers 10:30. Valid time is the same, snapshot time is not. Record which snapshot a report used.

</details>

**Q5.** Your retention job expires every snapshot older than 7 days. Can you still run `VERSION AS OF` on a snapshot from last month?

<details>
<summary>Show answer</summary>

No. Expired snapshots are removed from the metadata, so the ID is unknown, and files only they referenced can be deleted. Time travel only reaches back as far as you keep snapshots.

</details>

---

## What's Next? 🚀

You can now list every commit, read any version of a table, and explain why two correct answers can differ.

But look at that `events` read: it returned six columns. What happens when the business wants a new field, say `actor_id`, and half the history was written without it? Do we rewrite years of data?

Next, we change a table's shape without touching a single data file.

👉 **[Post 16: Schema Evolution](content/data-engineering/16-schema-evolution.md)**

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
