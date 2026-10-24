---
title: "Idempotent Loads"
date: 2026-10-24
tags: [data-engineering, apache-iceberg, pyspark, idempotency, lakehouse]
description: Load RepoSphere events into an Iceberg table so that running the same batch twice changes nothing. Covers deduping inside the batch, an anti join against the table, aligning columns by name with typed NULLs, an error on extra columns, and why overwrite is repeatable but not idempotent.
---

# Load It Twice, Get It Once 🔁

In [Post 11](content/data-engineering/11-catalogs-and-hidden-partitioning.md), we built a Spark session that speaks Iceberg and created two empty tables. `local.reposphere.events` is ready, and it's waiting for its first rows.

Now comes the part that makes Part 2 different from Part 1. **Real data arrives twice.**

Upstream systems retry. A job crashes at 3 a.m., gets restarted, and sends yesterday's events again. Someone re-runs a batch "just to be safe". Batch 1 even has a duplicate **inside** it: `e03` appears on two lines.

If your load blindly appends every line, the table fills up with copies. And every re-run makes it worse.

The goal for this post is one sentence from the spec:

> Loading the same batch twice must leave every table exactly as it was after the first load.

That property has a name: **idempotent**. Let's build it.

---

## The Doorman Analogy 🚪

Picture a club with a doorman and a guest book.

A queue forms at the door. Three things can go wrong:

1. **The same person is in the queue twice.** Let one of them in.
2. **Someone is already inside.** They stepped out for air and came back. Don't write them into the club a second time.
3. **Someone shows up with a form in the wrong format.** Fix the form, or turn them away. Don't let them in half-registered.

A good doorman checks all three, in that order. At the end of the night the guest book is correct, no matter how many times people queued up.

| Doorman | Idempotent load | RepoSphere |
|---|---|---|
| The same person twice in the queue | **Duplicates inside the batch** | `e03` on two lines of batch 1 |
| Already inside | **Rows already in the table** | `e04` and `e05` replayed in batch 2 |
| Wrong form | **Columns that don't match the table** | A batch with a column the table lacks |
| The guest book | The Iceberg table | `local.reposphere.events` |

![Four steps between a batch and the table](content/data-engineering/images/idempotent_load_funnel.svg)

---

## The Two Batches 📥

Both files use the RepoSphere events you already know. Batch 1 is the first day's delivery:

```json
{"event_id":"e01","event_type":"PushEvent","created_at":"2024-03-01T09:50:00Z","repo":{"id":101,"name":"alpha-api"},"actor":{"id":1,"login":"dave"}}
{"event_id":"e02","event_type":"PullRequestEvent","created_at":"2024-03-01T10:10:00Z","repo":{"id":202,"name":"beta-web"},"actor":{"id":1,"login":"dave"}}
{"event_id":"e03","event_type":"IssuesEvent","created_at":"2024-03-01T10:40:00Z","repo":{"id":101,"name":"alpha-api"},"actor":{"id":1,"login":"dave"}}
{"event_id":"e03","event_type":"IssuesEvent","created_at":"2024-03-01T10:40:00Z","repo":{"id":101,"name":"alpha-api"},"actor":{"id":1,"login":"dave"}}
{"event_id":"e04","event_type":"PUSHEVENT","created_at":"2024-03-01T11:20:00Z","repo":{"id":101,"name":"alpha-service"},"actor":{"id":1,"login":"dave"}}
{"event_id":"e05","event_type":"PushEvent","created_at":"2024-03-01T10:15:00Z","repo":{"id":202,"name":"beta-web"},"actor":{"id":2,"login":"jim"}}
```

Batch 2 arrives the next day. It has seven lines, and the first two are **replays** of events we already stored:

| File | Lines | Distinct `event_id`s | New to the table |
|---|---|---|---|
| `data/batch_1/events.jsonl` | 6 (`e03` twice) | 5 | 5 |
| `data/batch_2/events.jsonl` | 7 (`e04`, `e05` are replays) | 7 | 5 (`e06` to `e10`) |
| `data/batch_2/events.jsonl` again | 7 | 7 | **0** |

That last row is the whole point. Same file, second time, zero new rows.

> **Key insight:** Two different numbers hide in every batch. How many lines it **has** (7) and how many rows are **new to the table** (5, then 0). An idempotent load is built around the second number.

Flatten batch 1 with the functions from Part 1:

```python
events = read_events(spark, "data/batch_1/events.jsonl")
flat = flatten_events(events)
flat.orderBy("created_ts", "event_id").show(truncate=False)
```

```
+--------+----------------+-------------------+----------+-------+-----------+
|event_id|event_type      |created_ts         |event_date|repo_id|actor_login|
+--------+----------------+-------------------+----------+-------+-----------+
|e01     |pushevent       |2024-03-01 09:50:00|2024-03-01|101    |dave       |
|e02     |pullrequestevent|2024-03-01 10:10:00|2024-03-01|202    |dave       |
|e05     |pushevent       |2024-03-01 10:15:00|2024-03-01|202    |jim        |
|e03     |issuesevent     |2024-03-01 10:40:00|2024-03-01|101    |dave       |
|e03     |issuesevent     |2024-03-01 10:40:00|2024-03-01|101    |dave       |
|e04     |pushevent       |2024-03-01 11:20:00|2024-03-01|101    |dave       |
+--------+----------------+-------------------+----------+-------+-----------+
```

Six rows, and `e03` is there twice. Time to fix that.

---

## Layer 1: Duplicates Inside the Batch 🧹

```python
batch = flat.dropDuplicates(["event_id"])
```

One line. `dropDuplicates` with a column list keeps one row per `event_id`.

```python
print("raw rows:      ", flat.count())
print("after dedupe:  ", batch.count())
```

```
raw rows:       6
after dedupe:   5
```

Why is this a separate step from the table check? Because the table check can't see it.

> **Trap: layer 2 doesn't replace layer 1.** Imagine you skip the dedupe on batch 1. The table is empty, so *neither* copy of `e03` is "already stored". The anti join keeps both, and both land in the table. The anti join compares the batch to the **table**, never to **other rows of the same batch**.

One honest caveat. `dropDuplicates(["event_id"])` keeps **one** row per key, but which one is not defined. That's fine here, because replays are byte-for-byte identical. If copies could **differ** (a corrected event resent with a new value), choose deliberately with a window from [Post 05](content/data-engineering/05-window-functions.md):

```python
from pyspark.sql import Window

w = Window.partitionBy("event_id").orderBy(F.col("created_ts").desc())
batch = (
    flat.withColumn("rn", F.row_number().over(w))
        .filter("rn = 1")
        .drop("rn")
)
```

Order by something that really decides which copy wins, and add a tie-breaker so the result is deterministic.

---

## Layer 2: Rows Already in the Table 🔍

Now the other half. Which of the batch's `event_id`s are **not** in `events` yet?

That's an **anti join**: keep the rows of the left side that have **no match** on the right. Compare it with its relatives, using batch 2 against a table that already holds `e01` to `e05`:

| Join type | Keeps | Batch 2 result |
|---|---|---|
| `inner` | Batch rows **with** a match, both sides' columns | 2 rows (`e04`, `e05`) |
| `left_semi` | Batch rows **with** a match, batch columns only | 2 rows (`e04`, `e05`) |
| `left` | **Every** batch row, right side filled with NULL when there's no match | 7 rows |
| **`left_anti`** | Batch rows with **no** match, batch columns only | **5 rows** (`e06` to `e10`) |

```python
stored = spark.table("local.reposphere.events").select("event_id")
new_rows = batch.join(stored, on="event_id", how="left_anti")
```

```python
new_rows.orderBy("created_ts").show(truncate=False)     # batch 2, first run
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

`e04` and `e05` are gone, because their ids are already stored. Two more things worth noticing:

- `e10` has no login (`null`). It's still a perfectly good event. This table stores facts, and we don't sessionize here, so it goes in.
- `e06` happened at 23:40 on 1 March but arrived in batch 2. Its `event_date` is still `2024-03-01`, and the `days(created_ts)` partition from Post 11 puts it in the right day.

> **Trap: NULL keys never match.** An equality join compares `event_id = event_id`, and `NULL = NULL` is not true (the three-valued logic from [Post 02](content/data-engineering/02-spark-from-first-principles.md)). A batch row with a NULL `event_id` is always "not found", so the anti join keeps it, every single run. Our data has no such row, but a real feed might.

> **Key insight:** The anti join is the "already inside?" check. First write wins. If a replay arrives later with **different** values for a stored `event_id`, the stored row stays as it was. That's the behaviour this requirement asks for.

---

## Layer 3: Columns That Must Match 📐

The third check is the wrong-form guest. A table has a fixed schema. A batch has whatever its source produced. Two situations come up all the time:

| Situation | Example | What should happen |
|---|---|---|
| The table has a column the batch doesn't | Post 16 adds `actor_id` to `events`. An older feed doesn't send it | Fill it with a **typed NULL** |
| The batch has a column the table doesn't | `flatten_events(..., include_actor_id=True)` (the Part 2 version of `flatten_events` gains this flag, off by default) runs **before** the table has `actor_id` | **Raise an error** |

Here's one function that does both:

```python
from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def align_to_table(df: DataFrame, table: str) -> DataFrame:
    """Shape df like the table: same columns, same order, same types."""
    target = df.sparkSession.table(table).schema

    extra = sorted(set(df.columns) - set(target.fieldNames()))
    if extra:
        raise ValueError(f"Batch has columns the table lacks: {extra}")

    return df.select([
        (F.col(f.name) if f.name in df.columns else F.lit(None))
            .cast(f.dataType)
            .alias(f.name)
        for f in target.fields            # table order, table types
    ])
```

Three decisions, three reasons:

| Decision | Why |
|---|---|
| `F.lit(None).cast(f.dataType)` | A bare `F.lit(None)` has type `void` (NullType). A `BIGINT` column won't accept it. **Always cast** the NULL to the table's type |
| `raise` on extra columns | Silently dropping a column means silently **losing data**. Nobody finds out until someone asks where it went. The fix is a deliberate schema change (Post 16) |
| Iterate over `target.fields` | The output comes in the **table's** column order. Some write paths, such as `INSERT INTO ... SELECT`, match columns by position |

Try the error. The table still has six columns, and we hand it a batch that has seven:

```python
with_id = flatten_events(events, include_actor_id=True)
align_to_table(with_id, "local.reposphere.events")
```

```
ValueError: Batch has columns the table lacks: ['actor_id']
```

And the other direction. Suppose the table **has** `actor_id` (after Post 16) and a six-column batch arrives. Here is `e06` after alignment:

```
+--------+----------+-------------------+----------+-------+-----------+--------+
|event_id|event_type|created_ts         |event_date|repo_id|actor_login|actor_id|
+--------+----------+-------------------+----------+-------+-----------+--------+
|e06     |pushevent |2024-03-01 23:40:00|2024-03-01|101    |jim        |null    |
+--------+----------+-------------------+----------+-------+-----------+--------+
```

A real `BIGINT` NULL, in the right place.

---

## Putting It Together: `upsert_events` 🧩

The three layers become one function. Dedupe, anti join, align, then count **before** writing:

```python
EVENTS = "local.reposphere.events"


def new_event_rows(df: DataFrame) -> DataFrame:
    spark = df.sparkSession
    batch = df.dropDuplicates(["event_id"])                     # layer 1
    stored = spark.table(EVENTS).select("event_id")
    new_rows = batch.join(stored, on="event_id", how="left_anti")   # layer 2
    return align_to_table(new_rows, EVENTS)                     # layer 3


def upsert_events(df: DataFrame) -> int:
    new_rows = new_event_rows(df)
    inserted = new_rows.count()          # rows new to the table, counted BEFORE the write
    if inserted:
        new_rows.writeTo(EVENTS).append()
    return inserted
```

> **Why count before writing?** The spec says to return the rows **actually inserted**. If you count `batch` you get 7 for the replayed file. If you count the table after the write you get 10, not "how many I added". The anti join result is exactly the set of rows that go in, so its count is the answer.

This is a **first version**. The write is a plain append, and the anti join gets evaluated twice (once to count, once to write). That's fine for one writer. The spec wants a single insert-only `MERGE INTO`, and [Post 13](content/data-engineering/13-merge-into-in-depth.md) swaps the last lines for exactly that. Everything above it stays.

Now run the three loads from the lab: batch 1, batch 2, batch 2 again.

```python
spark = init_spark_session()
create_tables(spark)

for batch in ["batch_1", "batch_2", "batch_2"]:
    flat = flatten_events(read_events(spark, f"data/{batch}/events.jsonl"))
    print(batch, "->", upsert_events(flat))
```

```
batch_1 -> 5
batch_2 -> 5
batch_2 -> 0
```

Five, five, zero. That's the lab's answer. And the table after the last run:

```python
spark.table(EVENTS).orderBy("created_ts", "event_id").show(truncate=False)
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
|e06     |pushevent       |2024-03-01 23:40:00|2024-03-01|101    |jim        |
|e07     |issuesevent     |2024-03-02 09:05:00|2024-03-02|202    |jim        |
|e08     |pushevent       |2024-03-02 09:45:00|2024-03-02|303    |meera      |
|e09     |pullrequestevent|2024-03-02 10:00:00|2024-03-02|101    |dave       |
|e10     |pushevent       |2024-03-02 10:30:00|2024-03-02|999    |null       |
+--------+----------------+-------------------+----------+-------+-----------+
```

Ten distinct events. No `e03` twice, no `e04` twice. (In the full lab, `actor_id` is added between the batches. We'll get to that in Post 16, and the alignment function is what makes that painless.)

---

## Why `overwrite` Isn't the Answer 🧨

There's a tempting shortcut. "I'll just overwrite. Re-running overwrites with the same thing, so it's idempotent, right?"

Let's try it on batch 2 with Iceberg's partition overwrite:

```python
batch_2 = flatten_events(read_events(spark, "data/batch_2/events.jsonl"))
batch_2.writeTo(EVENTS).overwritePartitions()
```

`overwritePartitions` replaces every partition **the batch touches** with the batch's rows. Batch 2 touches both `2024-03-01` (via `e04`, `e05`, `e06`) and `2024-03-02`. So both partitions are replaced:

```
+--------+----------------+-------------------+----------+-------+-----------+
|event_id|event_type      |created_ts         |event_date|repo_id|actor_login|
+--------+----------------+-------------------+----------+-------+-----------+
|e05     |pushevent       |2024-03-01 10:15:00|2024-03-01|202    |jim        |
|e04     |pushevent       |2024-03-01 11:20:00|2024-03-01|101    |dave       |
|e06     |pushevent       |2024-03-01 23:40:00|2024-03-01|101    |jim        |
|e07     |issuesevent     |2024-03-02 09:05:00|2024-03-02|202    |jim        |
|e08     |pushevent       |2024-03-02 09:45:00|2024-03-02|303    |meera      |
|e09     |pullrequestevent|2024-03-02 10:00:00|2024-03-02|101    |dave       |
|e10     |pushevent       |2024-03-02 10:30:00|2024-03-02|999    |null       |
+--------+----------------+-------------------+----------+-------+-----------+
```

Seven rows. `e01`, `e02` and `e03` are **gone**. Run it again and you get the same seven rows, so it *is* repeatable. It's also wrong.

![Same batch 2, two different tables](content/data-engineering/images/overwrite_vs_incremental.svg)

| | Overwrite | Dedupe + anti join + add |
|---|---|---|
| Re-run gives the same table | Yes | Yes |
| Keeps rows the batch doesn't mention | **No** | Yes |
| A replayed batch can erase good data | **Yes** | No |
| Rows after batch 2 | 7 | 10 |

> **Trap: repeatable is not idempotent.** Idempotent means "the second run changes nothing", **and the first run was right**. Overwrite satisfies the first half and wrecks the second. For incremental loads, idempotent means: add what's new, and leave everything else exactly alone.

Overwrite has its place. Rebuilding a whole table from the full raw history is a fine job for it. A daily **increment** is not.

---

## Pre-Flight Checklist ✅

Before you trust `upsert_events`, check these:

| Check | Why it matters |
|---|---|
| Dedupe on `event_id` **inside** the batch first? | The anti join can't see two copies in the same batch |
| Anti join against the **table's** ids? | This is what makes a re-run insert 0 |
| Count the new rows **before** the write? | "Rows actually inserted" is the anti join's count, not the batch's |
| Missing columns cast to the table's type? | An untyped NULL is `void` and gets rejected |
| Extra columns raise an error? | Dropping them silently loses data |
| No `overwrite` on an incremental load? | It deletes everything the batch doesn't mention |
| Does the second run return `0` and leave the table byte-for-byte equal? | That is the spec |

---

## Quick Quiz 🧠

**Q1.** Batch 1 has 6 lines but `e03` appears twice. The table is empty. If you skip `dropDuplicates` and go straight to the anti join, how many rows does batch 1 insert, and why?

<details>
<summary>Show answer</summary>

**6.** The anti join compares the batch to the **table**, and the table is empty, so no `event_id` is "already stored". Both copies of `e03` pass through and both get written. In-batch duplicates are a separate problem and need their own step, `dropDuplicates(["event_id"])`, **before** the anti join.

</details>

**Q2.** What does `upsert_events` return for the three lab loads (batch 1, batch 2, batch 2 again), and which two events does batch 2 lose to the anti join?

<details>
<summary>Show answer</summary>

**5, 5, 0.** Batch 1 has 6 lines but only 5 distinct ids. Batch 2 has 7 lines, but `e04` and `e05` are replays of events already stored, so the anti join drops them and 5 rows (`e06` to `e10`) go in. On the second run of batch 2, every id is stored already, so nothing is new.

</details>

**Q3.** You write `F.lit(None).alias("actor_id")` instead of `F.lit(None).cast(f.dataType).alias("actor_id")`. What's wrong with the column?

<details>
<summary>Show answer</summary>

A bare `lit(None)` has type `void` (NullType), not `BIGINT`. The table's `actor_id` is a `BIGINT`, so the write fails or needs an implicit conversion. Casting to the **table's** data type (`f.dataType`) gives a properly typed NULL, which every Iceberg write path accepts.

</details>

**Q4.** A batch arrives with an extra column the table doesn't have. Why does `align_to_table` raise instead of just selecting the table's columns and ignoring the extra one?

<details>
<summary>Show answer</summary>

Because ignoring it **silently discards data**. The batch contains information the table has nowhere to put, and nobody would notice until much later. An error forces a decision: either the column is a mistake, or the table needs a deliberate schema change (Post 16). Loud failure beats quiet loss.

</details>

**Q5.** After batch 1, someone "fixes" batch 2 with `overwritePartitions()` because re-running it gives the same table. How many rows does the table end with, and what's lost?

<details>
<summary>Show answer</summary>

**7 rows.** Batch 2 touches both the `2024-03-01` and `2024-03-02` partitions, so both are replaced by the batch alone. `e01`, `e02` and `e03` from batch 1 are deleted. The result is repeatable (the same 7 rows on every re-run), but it isn't correct: the right answer is 10 rows. Idempotent loading means adding what's new and leaving the rest untouched.

</details>

---

## What's Next? 🚀

You can now load a batch so that replays, in-batch duplicates and mismatched columns can't hurt the table, and a re-run adds **0** rows.

But look at the last two lines of `upsert_events`. It reads the table to find what's new, then writes in a separate step. Two steps means a gap between them, and a plain append can't update a row that already exists.

Next, we turn that into one atomic statement: `MERGE INTO`. Insert-only for events, conditional updates for history, the `<=>` operator, what happens with duplicate source keys, and how Iceberg actually executes an update.

👉 **[Post 13 — MERGE INTO in Depth](content/data-engineering/13-merge-into-in-depth.md)**: insert-only MERGE for `upsert_events`, conditional update, `<=>` null-safe equality, duplicate source keys, copy-on-write vs merge-on-read, and skipping empty sources.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
