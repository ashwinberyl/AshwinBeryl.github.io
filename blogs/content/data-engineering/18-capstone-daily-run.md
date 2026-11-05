---
title: "Capstone: The Daily Run"
date: 2026-10-30
tags: [data-engineering, apache-iceberg, pyspark, capstone, lakehouse, first-principles]
description: Put all eight Part 2 requirements together. One daily run on RepoSphere's lakehouse, end to end - batch 1, a schema change, batch 2 twice, time travel and compaction. Includes the full main(), the predictions to make on paper, every expected table, and the checks that prove a reload changes nothing.
---

# The Dress Rehearsal 🎭

In [Post 17](content/data-engineering/17-compaction-and-maintenance.md), we wrote the last of the eight functions. Each one has been tested on its own, in its own post, on its own little table.

That is not the same as a **daily run**.

A real run strings them together, in order, against tables that already hold yesterday's data. One function leaves a table in a state the next one has to cope with. The schema changes between two loads. The same batch arrives twice. And at the end somebody asks what the table looked like on day 1.

Today is the **dress rehearsal**. Every actor has rehearsed alone. Now we run the whole show once, with the lights on, and check that the audience sees what the script promised.

By the end you will have:

- all **8 requirements** mapped to the posts that built them
- the full `main()` that runs them in the right order
- **predictions** you can make on paper before you run anything
- every table the run must produce, row for row
- a short list of **properties** to check, for the numbers that change on every run

---

## The Eight, Mapped 🗺️

Here is the whole of Part 2 on one page:

| # | Function | What it guarantees | Built in |
|---|---|---|---|
| 1 | `init_spark_session` | Iceberg jar, SQL extensions, a `local` catalog, UTC | [Post 11](content/data-engineering/11-catalogs-and-hidden-partitioning.md) |
| 2 | `create_tables` | Both tables exist, safe to re-run, `days(created_ts)` partitioning | [Post 11](content/data-engineering/11-catalogs-and-hidden-partitioning.md) |
| 3 | `upsert_events` | Dedupe, insert-only `MERGE`, returns rows actually inserted | [Post 12](content/data-engineering/12-idempotent-loads.md), [Post 13](content/data-engineering/13-merge-into-in-depth.md) |
| 4 | `merge_repo_scd2` | Affected repos only, null-safe diff, one `MERGE` | [Post 14](content/data-engineering/14-incremental-scd2.md) |
| 5 | `list_snapshots` | The table's history, oldest first | [Post 15](content/data-engineering/15-snapshots-and-time-travel.md) |
| 6 | `evolve_events_schema` | Add `actor_id`, no data rewritten, safe to re-run | [Post 16](content/data-engineering/16-schema-evolution.md) |
| 7 | `read_events_as_of` | Time travel, using that snapshot's schema | [Post 15](content/data-engineering/15-snapshots-and-time-travel.md), [Post 16](content/data-engineering/16-schema-evolution.md) |
| 8 | `compact_events` | Fewer files, identical contents | [Post 17](content/data-engineering/17-compaction-and-maintenance.md) |

Notice the shape. Numbers 1 and 2 build the stage. Numbers 3 and 4 are the **writers**. Numbers 5 to 8 are the **history and housekeeping** that only exist because the writers use Iceberg.

> **Key insight:** The thread through all eight is **idempotency**. Create twice, load twice, evolve twice, compact twice. The table ends in the same state. A daily job gets retried at 3 a.m. by something that is not you, so every step has to survive that.

---

## The Two Batches 📦

The data lives in `data/batch_1/` and `data/batch_2/`. Each folder has an `events.jsonl` and a `repo_changes.jsonl`. They were built so that every trap from Part 2 appears exactly once.

| Planted in | What it is | Which function must handle it |
|---|---|---|
| Batch 1 events | `e03` appears **twice** in the same file | `upsert_events` (dedupe the batch) |
| Batch 2 events | `e04` and `e05` are **replays** of batch 1 | `upsert_events` (skip what's stored) |
| Batch 2 events | `e06` arrives late, but happened at 23:40 on **1 March** | Hidden partitioning (lands in the 1 March partition) |
| Batch 2 events | `e10` has **no login**, only `actor.id = 3` | Stored as-is, `actor_login` is `null` |
| Batch 2 events | Every row has `actor.id` | `evolve_events_schema` must run first |
| Batch 2 changes | `c3` is a **replay** | `merge_repo_scd2` (new changes only) |
| Batch 2 changes | `c2` is **late**: 10:00 falls inside `c1`'s window | The recompute must shorten `c1` |
| Batch 2 changes | `c6` is a **new repo** (303) | Plain insert |
| Not in batch 2 | Repo 202 gets no new change | Must never be read or rewritten |

Batch 1 has 6 event lines and 3 repo changes. Batch 2 has 7 event lines and 3 repo changes.

---

## Predict First ✍️

Before you run a single line, answer these on paper. It is the cheapest debugging you will ever do, because a wrong prediction tells you which post to re-read.

1. What do the three `upsert_events` calls in `main()` return?
2. Which partition does `e06` land in?
3. After batch 2, what is `e04`'s `actor_id`? What is `e10`'s `actor_login`?
4. In batch 2's first `merge_repo_scd2`, which `repo_dim` rows are **updated**, which are **inserted**, and which are **left alone**?
5. Is repo 202 read during that rebuild?
6. What does batch 2's **second** `merge_repo_scd2` call do?
7. How many rows and columns does `read_events_as_of(day1_snapshot)` return?

Keep your answers. We check them against the real run below.

---

## The Full `main()` 🎬

The functions are exactly the ones from Posts 11 to 17. `flatten_events` is the version from [Post 16](content/data-engineering/16-schema-evolution.md), with its `include_actor_id` flag. `read_events` and `read_repo_changes` come from [Post 03](content/data-engineering/03-reading-json-lines-and-schemas.md).

```python
def main() -> None:
    spark = init_spark_session()                                           # 1
    create_tables(spark)                                                   # 2

    # ---------- Day 1 ----------
    flat_1 = flatten_events(read_events(spark, "data/batch_1/events.jsonl"))
    print("batch_1 events   ->", upsert_events(flat_1))                    # 3
    merge_repo_scd2(read_repo_changes(spark, "data/batch_1/repo_changes.jsonl"))   # 4

    day1_snapshot = list_snapshots(spark, "events").first()["snapshot_id"]  # 5

    # ---------- The schema changes BETWEEN the days ----------
    evolve_events_schema(spark)                                            # 6

    # ---------- Day 2, loaded twice ----------
    for run in (1, 2):
        flat_2 = flatten_events(read_events(spark, "data/batch_2/events.jsonl"),
                                include_actor_id=True)
        print(f"batch_2 run {run}    ->", upsert_events(flat_2))           # 3
        merge_repo_scd2(read_repo_changes(spark, "data/batch_2/repo_changes.jsonl"))  # 4

    # ---------- Audit and housekeeping ----------
    then = read_events_as_of(spark, day1_snapshot)                         # 7
    print("day 1, as it was ->", len(then.columns), "columns,", then.count(), "rows")

    pre_rows = spark.table("local.reposphere.events").count()
    files_before, files_after = compact_events(spark)                      # 8
    print("compaction       ->", (files_before, files_after),
          "| rows before/after:", pre_rows, spark.table("local.reposphere.events").count())
```

![One daily run: set up, batch 1, bookmark, evolve, batch 2, batch 2 again, then time travel and compaction, with row counts for both tables after each step](content/data-engineering/images/daily_run_timeline.svg)

Three things in that order are easy to get wrong:

- **Bookmark before evolve.** `day1_snapshot` is read from the table **before** the schema change, so requirement 7 can show a six-column table.
- **Evolve before batch 2.** If `actor_id` arrives in the data before it exists in the table, `align_to_table` raises, which is the correct behaviour ([Post 16](content/data-engineering/16-schema-evolution.md)).
- **Batch 2 runs twice on purpose.** That loop is the idempotency test. The second pass must insert 0 events and change 0 `repo_dim` rows.

Delete the `warehouse/` folder before each full test run. State persists between runs, which is the whole point of Part 2, and a leftover table from yesterday's run will quietly give you wrong counts.

---

## Day 1: What the Tables Hold 🌅

Run `main()` up to the bookmark. The prints say:

```
batch_1 events   -> 5
```

Six lines in, five rows stored, because `e03` appeared twice. Now the two tables:

```python
spark.table("local.reposphere.events").orderBy("created_ts").show(truncate=False)
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
```

```python
spark.table("local.reposphere.repo_dim").orderBy("repo_id", "valid_from").show(truncate=False)
```

```
+---------+-------+-------------+----------+--------------+-------------------+-------------------+----------+
|change_id|repo_id|repo_name    |visibility|default_branch|valid_from         |valid_to           |is_current|
+---------+-------+-------------+----------+--------------+-------------------+-------------------+----------+
|c1       |101    |alpha-api    |public    |main          |2024-03-01 09:00:00|2024-03-01 11:00:00|false     |
|c3       |101    |alpha-service|public    |main          |2024-03-01 11:00:00|null               |true      |
|c4       |202    |beta-web     |public    |master        |2024-03-01 10:30:00|null               |true      |
+---------+-------+-------------+----------+--------------+-------------------+-------------------+----------+
```

Five events, three versions. Hold on to the first table: it is also **exactly** what `read_events_as_of(day1_snapshot)` must return at the end.

> **Heads up:** Table order is not row order. Without an `orderBy`, `show()` can print rows in any order, because Iceberg makes no promise about it. Every table in this post is sorted explicitly. Do the same when you compare against it.

---

## The Schema Moves, Then Batch 2 🔀

`evolve_events_schema` runs. Nothing is rewritten, no snapshot is added, and `events` now has a seventh column, `actor_id`, that reads `null` for all five existing rows ([Post 16](content/data-engineering/16-schema-evolution.md)).

Now batch 2 goes through twice. The prints:

```
batch_2 run 1    -> 5
batch_2 run 2    -> 0
```

So the three `upsert_events` calls return **5, 5, 0**. Seven lines in batch 2, minus two replays (`e04`, `e05`), gives five new events. The second run finds nothing new and returns before it even builds a `MERGE`.

### The events table

```
+--------+----------------+-------------------+----------+-------+-----------+--------+
|event_id|event_type      |created_ts         |event_date|repo_id|actor_login|actor_id|
+--------+----------------+-------------------+----------+-------+-----------+--------+
|e01     |pushevent       |2024-03-01 09:50:00|2024-03-01|101    |dave       |null    |
|e02     |pullrequestevent|2024-03-01 10:10:00|2024-03-01|202    |dave       |null    |
|e05     |pushevent       |2024-03-01 10:15:00|2024-03-01|202    |jim        |null    |
|e03     |issuesevent     |2024-03-01 10:40:00|2024-03-01|101    |dave       |null    |
|e04     |pushevent       |2024-03-01 11:20:00|2024-03-01|101    |dave       |null    |
|e06     |pushevent       |2024-03-01 23:40:00|2024-03-01|101    |jim        |2       |
|e07     |issuesevent     |2024-03-02 09:05:00|2024-03-02|202    |jim        |2       |
|e08     |pushevent       |2024-03-02 09:45:00|2024-03-02|303    |meera      |4       |
|e09     |pullrequestevent|2024-03-02 10:00:00|2024-03-02|101    |dave       |1       |
|e10     |pushevent       |2024-03-02 10:30:00|2024-03-02|999    |null       |3       |
+--------+----------------+-------------------+----------+-------+-----------+--------+
```

Read three things off it:

- **`e06`** arrived in batch 2 but sits on 1 March. Its partition comes from its own timestamp, not from the day it was loaded.
- **`e04`** still has `actor_id = null`, even though batch 2 carried `1` for it. Insert-only means an existing key is **never touched** ([Post 13](content/data-engineering/13-merge-into-in-depth.md)).
- **`e10`** has no login but does have `actor_id = 3`. We store it, because this pipeline does not sessionize.

To prove the partition claim without trusting your eyes, ask the table itself:

```python
(spark.table("local.reposphere.events.partitions")
      .select("partition", "record_count")
      .orderBy("partition")
      .show(truncate=False))
```

```
+------------+------------+
|partition   |record_count|
+------------+------------+
|{2024-03-01}|6           |
|{2024-03-02}|4           |
+------------+------------+
```

Two partitions, six rows and four rows. It adds up to ten.

### The repo_dim table

Batch 2's first `merge_repo_scd2` call builds a diff before it merges. If you print it, it must be **exactly** these three rows:

```
+---------+-------+---------+----------+--------------+-------------------+-------------------+----------+
|change_id|repo_id|repo_name|visibility|default_branch|valid_from         |valid_to           |is_current|
+---------+-------+---------+----------+--------------+-------------------+-------------------+----------+
|c1       |101    |alpha-api|public    |main          |2024-03-01 09:00:00|2024-03-01 10:00:00|false     |
|c2       |101    |alpha-api|private   |main          |2024-03-01 10:00:00|2024-03-01 11:00:00|false     |
|c6       |303    |gamma-cli|public    |trunk         |2024-03-02 09:00:00|null               |true      |
+---------+-------+---------+----------+--------------+-------------------+-------------------+----------+
```

![What batch 2 does to repo_dim: c1 updated, c2 and c6 inserted, c3 skipped as a replay, c4 untouched because repo 202 had no new change](content/data-engineering/images/batch2_repo_dim_routing.svg)

`c1` is the interesting one. It is the late-arriving case: `c2` at 10:00 cuts `c1`'s window short, so `c1`'s `valid_to` moves from 11:00 to 10:00. That is the **only** stored row that changes. And the table after both runs:

```
+---------+-------+-------------+----------+--------------+-------------------+-------------------+----------+
|change_id|repo_id|repo_name    |visibility|default_branch|valid_from         |valid_to           |is_current|
+---------+-------+-------------+----------+--------------+-------------------+-------------------+----------+
|c1       |101    |alpha-api    |public    |main          |2024-03-01 09:00:00|2024-03-01 10:00:00|false     |
|c2       |101    |alpha-api    |private   |main          |2024-03-01 10:00:00|2024-03-01 11:00:00|false     |
|c3       |101    |alpha-service|public    |main          |2024-03-01 11:00:00|null               |true      |
|c4       |202    |beta-web     |public    |master        |2024-03-01 10:30:00|null               |true      |
|c6       |303    |gamma-cli    |public    |trunk         |2024-03-02 09:00:00|null               |true      |
+---------+-------+-------------+----------+--------------+-------------------+-------------------+----------+
```

Three versions of repo 101 with no gap and no overlap, one of 202 exactly as it was, and a fresh one for 303. The second call to `merge_repo_scd2` did **nothing**: after deduping and removing stored `change_id`s, no new change remains, so it returns before any `MERGE`.

> **Key insight:** The strongest test of the SCD2 merge is Part 1's own function. Run `build_repo_scd2` over **every change ever loaded** and compare it to the table with `exceptAll` in both directions, as in [Post 14](content/data-engineering/14-incremental-scd2.md). If both counts are `0`, the incremental path and the from-scratch path agree.

---

## Time Travel and Compaction ⏪

Back to the dress rehearsal's final act. The audit question: what did `events` hold on day 1?

```
day 1, as it was -> 6 columns, 5 rows
```

Six columns, not seven, and five rows, not ten. A snapshot remembers **its own** schema ([Post 16](content/data-engineering/16-schema-evolution.md)), so `actor_id` does not exist as far as day 1 is concerned. Show it and it is the Day 1 events table from earlier, byte for byte.

Then compaction:

```
compaction       -> (4, 2) | rows before/after: 10 10
```

> **Heads up:** The `(4, 2)` is **illustrative**, the same shape [Post 17](content/data-engineering/17-compaction-and-maintenance.md) showed. How many files a write produces depends on your Spark parallelism, so your first number will differ. What must hold is: `files_after` is at most `files_before`, it is at least 2 (one per day), and the row count is `10` on both sides.

---

## Properties to Check ✅

Snapshot IDs, commit times and file counts come from **your** run, so you cannot compare them with a printed table. Check properties instead:

```python
snaps = list_snapshots(spark, "events").collect()

print(snaps[0]["parent_id"] is None,
      all(b["parent_id"] == a["snapshot_id"] for a, b in zip(snaps, snaps[1:])),
      [s["operation"] for s in snaps])
```

```
True True ['append', 'append', 'replace']
```

Read it left to right: the first snapshot has no parent, every later one points at the one before, and the operations tell the story. Batch 1 was an `append`. Batch 2's first run was an `append`. The second run committed nothing. Compaction was a `replace`. The schema change did not appear at all.

| Check | Expect | Because |
|---|---|---|
| `events` snapshots, oldest first | `append`, `append`, `replace` | Two real loads, then compaction. Evolve and the re-run commit nothing |
| `repo_dim` snapshots | An `append`, then a non-`append` | Batch 2's first `MERGE` rewrote the file holding `c1` |
| `repo_dim` snapshot count after the re-run | Unchanged | The second call never reached its `MERGE` |
| `events.partitions` | Two rows: 6 and 4 | `days(created_ts)`, late `e06` in the right day |
| `compact_events()` | `after <= before`, `after >= 2` | Compaction never merges across partitions |
| Rows before and after compaction | `10` and `10`, plus `exceptAll` of `0` both ways | Same data, different files |

---

## If Your Output Differs 🔧

A wrong number points at one specific post:

| What you see | Likely cause | Re-read |
|---|---|---|
| Re-run returns `5` or `7`, not `0` | Counting the batch, or counting **after** the `MERGE` | [Post 12](content/data-engineering/12-idempotent-loads.md) |
| `e04` and `e05` appear twice | Appended instead of an insert-only `MERGE` | [Post 13](content/data-engineering/13-merge-into-in-depth.md) |
| `e03` appears twice | No in-batch dedupe | [Post 12](content/data-engineering/12-idempotent-loads.md) |
| Void-type error on batch 1 | Missing columns not added as **typed** NULLs | [Post 12](content/data-engineering/12-idempotent-loads.md) |
| `c1` still ends at 11:00, or `c2` has a null `valid_to` | The window ran over new changes only | [Post 14](content/data-engineering/14-incremental-scd2.md) |
| `c4` is rewritten | Affected repos not limited to those with new changes | [Post 14](content/data-engineering/14-incremental-scd2.md) |
| Day-1 time travel shows `actor_id` | Read the current table, not the snapshot | [Post 15](content/data-engineering/15-snapshots-and-time-travel.md) |
| `files_after == files_before` | Default `min-input-files` of 5 not met | [Post 17](content/data-engineering/17-compaction-and-maintenance.md) |

> **Trap:** Don't run `main()` twice **without** deleting `warehouse/` and then compare the first print with the answer key. The second full run starts from a table that already holds everything, so `batch_1` prints `0`, not `5`. That is idempotency doing its job. It just isn't the test you meant to run.

---

## Pre-Flight Checklist 🛫

| Check | Why it matters |
|---|---|
| Does every `CREATE` and `ALTER` survive being run twice? | The 3 a.m. retry |
| Is `events` partitioned by `days(created_ts)`, not `event_date`? | Late rows land in the right day |
| Batch deduped **and** stored keys excluded? | Replays and in-file duplicates are different problems |
| Inserted rows counted **before** the `MERGE`? | A reload must return `0` |
| Batch missing `actor_id` loads with typed NULLs, an unknown column fails loudly? | Schema changes are deliberate |
| `valid_to` recomputed over stored history **plus** new changes, affected repos only? | Late changes need the full picture |
| Diff uses `eqNullSafe`, `UPDATE SET` lists only `valid_to` and `is_current`? | Closing a current row is detected, nothing else changes |
| `MERGE` skipped when there is nothing to do? | No empty commits |
| Day-1 time travel returns 6 columns and 5 rows? | Snapshots keep their own schema |
| Only data files counted, `CALL` given the in-catalog name? | `content = 0`, no `local.` prefix |
| Rows identical before and after compaction? | Prove it, don't assume it |

---

## Quick Quiz 🧠

**Q1.** Batch 2 is loaded a second time. Why does `upsert_events` return `0`, and why does `events` get **no** new snapshot?

<details>
<summary>Show answer</summary>

After deduping the batch and anti-joining against the stored `event_id`s, no new rows remain, so the count is `0`. `upsert_events` returns **before** it builds the `MERGE`, so nothing is committed, and a commit is what creates a snapshot.

</details>

**Q2.** Batch 2 carries `actor.id = 1` for `e04`, yet the table shows `actor_id = null` for it. Is that a bug?

<details>
<summary>Show answer</summary>

No. `e04` was stored in batch 1, and the `MERGE` is insert-only: a key that already exists is never touched, so the replay's extra column is ignored. Backfilling old rows would be a separate, deliberate `MERGE ... WHEN MATCHED` job.

</details>

**Q3.** Which rows does batch 2 send to the `repo_dim` `MERGE`, and why is `c4` not among them?

<details>
<summary>Show answer</summary>

Exactly `c1` (updated, `valid_to` becomes 10:00), `c2` (inserted) and `c6` (inserted). `c3` is a replay already stored with the same recomputed validity, so it drops out of the diff. `c4` belongs to repo 202, which has no new change, so it is never an **affected repo** and is never read or rewritten.

</details>

**Q4.** `read_events_as_of(day1_snapshot)` returns 6 columns and 5 rows. Why not 7 columns and 10 rows?

<details>
<summary>Show answer</summary>

A snapshot is the table **as it was** at that commit, including its schema. On day 1 there was no `actor_id` column, and only batch 1's five events existed. Reading the *current* table would give 7 columns and 10 rows, which is the mistake the checklist guards against.

</details>

**Q5.** After compaction, `before_df.exceptAll(after_df)` and `after_df.exceptAll(before_df)` both count `0`. Why is that the right proof, and why compare in **both** directions?

<details>
<summary>Show answer</summary>

One direction only shows nothing was lost, or only that nothing was added. Both together mean the two sides hold the same rows, and `exceptAll` respects duplicates, so a doubled row would show up too. With `10` rows on both sides, it proves compaction changed the files and not the data.

</details>

---

## What's Next? 🚀

Part 2 is done. You can now build a lakehouse that loads safely, corrects itself, remembers every version, changes shape without a rewrite, and tidies up after itself, and you have checked it end to end against a script of known answers.

Everything so far was about being **correct**. Part 3 is about being **fast**. We have only ever run on ten rows, which means we have never felt a slow job. Next, we open the hood: what Spark actually plans to do with a RepoSphere job, where the shuffles are, and how to read it.

👉 **[Post 19: Reading the Spark Plan](content/data-engineering/19-reading-the-spark-plan.md)**

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
