---
title: "Schema Evolution"
date: 2026-10-28
tags: [data-engineering, apache-iceberg, pyspark, schema-evolution, lakehouse]
description: Add a column to RepoSphere's events table without rewriting a single data file. Covers evolve_events_schema, why Iceberg's column IDs make ADD, RENAME and DROP metadata-only, why old rows read NULL, the load-order trap, and why time travel still returns the old schema.
---

# Change the Shape Without Moving a Byte 🧬

In [Post 15](content/data-engineering/15-snapshots-and-time-travel.md), `read_events_as_of` handed back **six columns** for the day-1 snapshot. I promised that would still be true after we add a seventh.

Here is the request that forces the issue. The product team has started sending `actor.id` in every event, and analysts want it as a column called `actor_id`. Right now the `events` table has this:

```
event_id | event_type | created_ts | event_date | repo_id | actor_login
```

Five rows are already stored without it. Ten more events arrive in batch 2, and those **do** have an actor ID. So we need a seventh column, and we need it **today**.

> **The question:** Do we rewrite every stored file to add `actor_id`?

On a Parquet folder, yes. You read everything, add the column, write everything back, and hope no reader looks in the middle. On a table with years of history, that is a weekend.

On Iceberg, the answer is no. That is requirement 6: `evolve_events_schema`.

---

## The Packing List Analogy 📦

Picture a warehouse full of **sealed boxes**. Each box was packed on a different day. A **packing list** at the front desk says which fields every box is supposed to contain.

Someone asks for a new field. You have two options:

- **Open every box**, add a slip of paper to each, and seal it again.
- **Update the packing list**: "field 7 is `actor_id`. If a box has no field 7, report it as empty."

The second one takes a minute, and no box is ever opened. That is Iceberg. The sealed boxes are Parquet files. The packing list is the table's **schema**, stored in the metadata.

| Warehouse | Iceberg |
|---|---|
| Sealed box | A Parquet data file |
| Packing list | The schema in `metadata.json` |
| "Field 7 is empty if missing" | The reader fills in `NULL` |
| A new copy of the packing list | A new `metadata.json` version |

---

## One Line of SQL ➕

```python
spark.sql("ALTER TABLE local.reposphere.events ADD COLUMN actor_id BIGINT")
```

That is the whole change. Check the schema:

```python
spark.table("local.reposphere.events").printSchema()
```

```
root
 |-- event_id: string (nullable = true)
 |-- event_type: string (nullable = true)
 |-- created_ts: timestamp (nullable = true)
 |-- event_date: date (nullable = true)
 |-- repo_id: long (nullable = true)
 |-- actor_login: string (nullable = true)
 |-- actor_id: long (nullable = true)
```

And the five rows from batch 1, right after the `ALTER`:

```python
spark.table("local.reposphere.events").orderBy("created_ts").show(truncate=False)
```

```
+--------+----------------+-------------------+----------+-------+-----------+--------+
|event_id|event_type      |created_ts         |event_date|repo_id|actor_login|actor_id|
+--------+----------------+-------------------+----------+-------+-----------+--------+
|e01     |pushevent       |2024-03-01 09:50:00|2024-03-01|101    |dave       |null    |
|e02     |pullrequestevent|2024-03-01 10:10:00|2024-03-01|202    |dave       |null    |
|e05     |pushevent       |2024-03-01 10:15:00|2024-03-01|202    |jim        |null    |
|e03     |issuesevent     |2024-03-01 10:40:00|2024-03-01|101    |dave       |null    |
|e04     |pushevent       |2024-03-01 11:20:00|2024-03-01|101    |dave       |null    |
+--------+----------------+-------------------+----------+-------+-----------+--------+
```

A new column, all `null`, and no file touched. The `null` is not stored anywhere. The reader makes it up on the fly.

> **Key insight:** In Iceberg, a schema change is a **metadata commit**, not a data rewrite. The cost is the same on a 5-row table and a 5-billion-row table.

---

## Why It's Safe: Column IDs 🔑

How can a reader open a file that has no `actor_id` and not crash? Because Iceberg does not find columns by **name** or by **position**. It finds them by **ID**.

Every column gets a permanent numeric ID when it is created. Iceberg writes that ID into every Parquet file next to the column. The reader walks the **table's** schema and, for each ID, looks inside the file:

- ID found: read the values.
- ID not found: return `NULL`.

![Old file, new schema: ID 7 is missing, so it reads NULL](content/data-engineering/images/column_ids_old_file.svg)

That one rule makes a whole family of changes safe:

| Change | SQL | Data files touched | Why it is safe |
|---|---|---|---|
| **Add** a column | `ALTER TABLE t ADD COLUMN c BIGINT` | None | Brand-new ID. Old files lack it and read `NULL` |
| **Rename** | `ALTER TABLE t RENAME COLUMN a TO b` | None | The ID stays the same, so old files still match |
| **Drop** | `ALTER TABLE t DROP COLUMN c` | None | The ID is retired and **never reused** |
| **Widen a type** | `ALTER TABLE t ALTER COLUMN c TYPE BIGINT` | None | `INT` to `BIGINT` and `FLOAT` to `DOUBLE` always fit |
| **Reorder** | `ALTER TABLE t ALTER COLUMN c AFTER d` | None | Position is not identity |

And the two things Iceberg refuses by default: **narrowing** a type (`BIGINT` to `INT` could lose values) and adding a **required** column to a table that already has rows (the old rows have nothing to put there). New columns arrive nullable.

> **Why IDs and not names?** Compare a Hive-style Parquet folder, where columns are matched by name or position. Rename `actor_login` and every old file now disagrees with the schema. Drop a column and add a different one with the same name, and the old values quietly flow into the new column. IDs rule both of those out.

Which brings up a neat consequence:

> **Key insight:** Drop `actor_id` and later add a *new* column also called `actor_id`. The new column gets a **new ID**, so old files do not bring their values back. A dropped column stays dropped.

> **Trap:** A rename is safe for the **table** and unsafe for its **consumers**. Every dashboard, job, or notebook that selects `actor_login` breaks the moment you rename it. Metadata-safe is not the same as downstream-safe. Announce renames, or add a new column and migrate readers before you drop the old one.

---

## `evolve_events_schema`: Safe to Re-Run 🔁

The spec says the function must be **safe to re-run**. Run `ADD COLUMN` twice and the second call fails, because the column already exists. So we check first:

```python
from pyspark.sql import SparkSession

EVENTS = "local.reposphere.events"


def evolve_events_schema(spark: SparkSession) -> None:
    if "actor_id" not in spark.table(EVENTS).columns:
        spark.sql(f"ALTER TABLE {EVENTS} ADD COLUMN actor_id BIGINT")
```

Three lines, and the whole requirement is in them: the existence check makes it idempotent, `BIGINT` matches the type of `repo_id` and the actor IDs in the JSON, and nothing in the table is rewritten.

Don't take my word for the "nothing rewritten" part. Let's measure. Right after batch 1, capture the data-file list and the snapshot count, call the function **twice**, then compare:

```python
def data_files(spark):
    rows = spark.table(f"{EVENTS}.files").select("file_path").collect()
    return {r["file_path"] for r in rows}


files_before = data_files(spark)
snaps_before = list_snapshots(spark, "events").count()

evolve_events_schema(spark)
evolve_events_schema(spark)        # second call: column exists, nothing runs

print(data_files(spark) == files_before,
      snaps_before,
      list_snapshots(spark, "events").count(),
      len(spark.table(EVENTS).columns))
```

```
True 1 1 7
```

Read that from left to right:

- **`True`**: the exact same set of data files, so nothing was rewritten.
- **`1 1`**: one snapshot before, one after. A schema change is **not** a snapshot. That is the line I put in the trap box of Post 15.
- **`7`**: seven columns, even after two calls.

---

## Order Matters: The Column Comes First 🚦

Now we have to load batch 2, and batch 2 carries `actor.id`. First, a small change to Part 1's `flatten_events`. It gains a flag, **off by default**, so every earlier post still works as written:

```python
from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def flatten_events(events: DataFrame, include_actor_id: bool = False) -> DataFrame:
    created_ts = F.to_timestamp(F.col("created_at"))

    cols = [
        F.col("event_id"),
        F.lower(F.col("event_type")).alias("event_type"),
        created_ts.alias("created_ts"),
        F.to_date(created_ts).alias("event_date"),
        F.col("repo.id").alias("repo_id"),
        F.col("actor.login").alias("actor_login"),
    ]
    if include_actor_id:
        cols.append(F.col("actor.id").alias("actor_id"))

    return events.select(*cols)
```

Why a flag instead of always including it? Because batch 1 was loaded **before** the column existed. Its flat DataFrame has six columns, and the table had six at that moment.

What if someone loads batch 2 with `include_actor_id=True` **before** running `evolve_events_schema`? Remember `align_to_table` from [Post 12](content/data-engineering/12-idempotent-loads.md):

```python
flat = flatten_events(read_events(spark, "data/batch_2/events.jsonl"), include_actor_id=True)
upsert_events(flat)      # table still has six columns
```

```
ValueError: Batch has columns the table lacks: ['actor_id']
```

Good. That error is the correct behaviour. The batch holds data the table has nowhere to put, and **evolving the schema is a deliberate act that comes first**.

> **Trap:** Spark can also auto-merge schemas on write (the `mergeSchema` write option). It sounds convenient, but then one typo in an upstream field name, say `actor_idd`, becomes a **permanent column** that you can only drop. Explicit evolution costs one extra line, and it means a human decided.

Here is the order that works, as it appears in the daily run:

```python
spark = init_spark_session()
create_tables(spark)

batch_1 = flatten_events(read_events(spark, "data/batch_1/events.jsonl"))
print("batch_1 ->", upsert_events(batch_1))
day1_snapshot = list_snapshots(spark, "events").first()["snapshot_id"]

evolve_events_schema(spark)                      # the column arrives BETWEEN the days

for _ in range(2):                               # batch 2, loaded twice
    batch_2 = flatten_events(read_events(spark, "data/batch_2/events.jsonl"),
                             include_actor_id=True)
    print("batch_2 ->", upsert_events(batch_2))
```

```
batch_1 -> 5
batch_2 -> 5
batch_2 -> 0
```

Same **5, 5, 0** as before. The new column did not disturb idempotency. The second pass still finds nothing new, and `upsert_events` does not even reach its `MERGE`.

Batch 1's six-column DataFrame and batch 2's seven-column one both go through the same `upsert_events`, because `align_to_table` pads the missing column with a typed `NULL` in one direction and raises in the other. That is the Post 12 design paying off.

---

## The Table After Batch 2 📋

```python
spark.table(EVENTS).orderBy("created_ts").show(truncate=False)
```

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

Two patterns to read off it:

- **Old rows (`e01` to `e05`)** still have a `null` actor ID. Those files were never rewritten.
- **`e10`** has no login but **does** have `actor_id = 3`. The ID was in the JSON all along. The login was the missing piece.

A one-line summary of how mixed the table is:

```python
spark.table(EVENTS).select(
    F.count("*").alias("rows"),
    F.count("actor_id").alias("with_actor_id"),     # count(col) skips NULLs
).show()
```

```
+----+-------------+
|rows|with_actor_id|
+----+-------------+
|  10|            5|
+----+-------------+
```

Ten rows, five with an ID. And now look closer at `e04` and `e05`.

> **Trap:** Both `e04` and `e05` appear in batch 2 **with** an actor ID (1 and 2). They still show `null` above. Our load is **insert-only** ([Post 13](content/data-engineering/13-merge-into-in-depth.md)): a key that already exists is never touched, so the replay's extra information is ignored. Backfilling old rows is a separate, deliberate job (a `MERGE ... WHEN MATCHED` that fills only the NULLs). It should be a decision, not a side effect of a replay.

---

## Time Travel Still Tells the Truth ⏪

Back to the promise from Post 15. Compare the day-1 snapshot with the live table:

```python
then = read_events_as_of(spark, day1_snapshot)
now = spark.table(EVENTS)

print(len(then.columns), len(now.columns), then.count(), now.count())
```

```
6 7 5 10
```

Six columns and five rows for the old snapshot. Seven columns and ten rows for now.

![Each snapshot remembers its schema](content/data-engineering/images/schema_versions_metadata.svg)

Each snapshot records which schema it was written with. Reading `S1` applies schema 0 on top of the batch-1 file. Reading the live table applies schema 1. The **same file** serves both readers, and only the schema laid over it differs.

That is the right behaviour for an audit. The report built after batch 1 had six columns, and re-running it against `S1` must return exactly that, not a table that has quietly grown a column of `NULL`s.

> **Heads up:** If your `read_events_as_of` returns **seven** columns, you are reading the current table's schema instead of the snapshot's. Check that you are passing `snapshot-id` to the reader and that your Iceberg version applies the snapshot's own schema.

---

## Pre-Flight Checklist 🛫

| Check | Why it matters |
|---|---|
| `evolve_events_schema` checks `columns` before `ALTER`? | A second run must not fail |
| New column is nullable `BIGINT`? | Old rows have nothing to put there, and the type matches the JSON ID |
| Schema change runs **before** the batch that needs it? | Otherwise `align_to_table` correctly raises |
| `flatten_events(..., include_actor_id=False)` by default? | Batch 1 and the earlier posts must keep working |
| Snapshot count and file set unchanged by the `ALTER`? | Proves it was metadata-only |
| Time travel to day 1 returns six columns? | Snapshots keep their own schema |
| Backfilling `e01` to `e05` treated as a separate job? | Insert-only loads never update existing rows |

---

## Quick Quiz 🧠

**Q1.** After `evolve_events_schema` runs on the five stored events, how many data files were rewritten and how many snapshots were added?

<details>
<summary>Show answer</summary>

Zero and zero. The `ALTER` commits a new `metadata.json` with a new schema and nothing else. The current snapshot is still the one batch 1 created. Our check printed `True 1 1 7`: same files, one snapshot before and after, seven columns.

</details>

**Q2.** Why do `e01` to `e05` read `NULL` for `actor_id` instead of raising an error?

<details>
<summary>Show answer</summary>

Iceberg matches columns by **ID**. The old files contain IDs 1 to 6 and no ID 7. For every ID in the table's schema that a file lacks, the reader returns `NULL`. The `NULL` is never written anywhere.

</details>

**Q3.** Someone loads batch 2 with `include_actor_id=True` before `evolve_events_schema` has run. What happens, and is that good?

<details>
<summary>Show answer</summary>

`align_to_table` raises `ValueError: Batch has columns the table lacks: ['actor_id']` and nothing is written. That is good. Silently dropping the column would lose data, and auto-merging would let a typo become a permanent column. The fix is to evolve the schema first, then load.

</details>

**Q4.** `e05` is replayed in batch 2 with actor ID 2. After the load, what is its `actor_id`?

<details>
<summary>Show answer</summary>

`null`. `e05` already exists in the table, and the load is insert-only, so the existing row is never touched. Filling it in would be a separate, deliberate backfill `MERGE`.

</details>

**Q5.** You drop `actor_id`, then add a new column that is also named `actor_id`. Do the old values come back for the rows that were stored before?

<details>
<summary>Show answer</summary>

No. The new column gets a **new** column ID, and IDs are never reused. Old files only know the retired ID, so the new column reads `NULL` for them. That is exactly the protection that name-based matching in a plain Parquet folder cannot give you.

</details>

---

## What's Next? 🚀

You can now change a table's shape without moving a byte, and you know why the old snapshot still returns six columns.

But look at what we have been doing: every load writes new files, and every `MERGE` that updates something rewrites a few more. Run this daily for a year and you have a mountain of tiny files, plus a pile of old snapshots keeping them alive.

Next, we count those files, merge them back into fewer big ones, and clean up after ourselves.

👉 **[Post 17: Compaction and Maintenance](content/data-engineering/17-compaction-and-maintenance.md)**

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
