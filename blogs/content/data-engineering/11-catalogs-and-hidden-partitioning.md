---
title: "Catalogs and Hidden Partitioning"
date: 2026-10-23
tags: [data-engineering, apache-iceberg, pyspark, lakehouse, catalog, partitioning]
description: Wire Apache Iceberg into Spark and create the two RepoSphere tables. Covers the three pieces of init_spark_session (jar, SQL extensions, catalog), how local.reposphere.events maps to a folder, a safely re-runnable create_tables with IF NOT EXISTS and format version 2, and why days(created_ts) beats a partition column.
---

# Wiring Up the Lakehouse 🔌

In [Post 10](content/data-engineering/10-why-table-formats-iceberg.md), we learned **why** a folder of Parquet files isn't a table, and what Iceberg keeps on disk to fix that: a metadata tree, atomic commits, snapshots.

Now we stop talking and build. Two functions, and they come first in every Part 2 run:

1. `init_spark_session`: a Spark that speaks Iceberg.
2. `create_tables`: the two RepoSphere tables, `events` and `repo_dim`, ready for daily loads.

They look boring. They're also where three classic mistakes live: a missing extension that breaks things **later**, a `CREATE TABLE` that breaks the **second** run, and a partition column that quietly makes queries slower.

---

## The Address Book Analogy 📒

Think of a company phone system.

You don't dial a raw number. You dial `sales.london.alice`. The system reads it in parts: first the **office** (sales), then the **team** (london), then the **person** (alice). Each part narrows the search. Somewhere there's a **directory** that turns the final name into a real extension.

An Iceberg catalog is that directory.

| Phone system | Iceberg | RepoSphere |
|---|---|---|
| The directory | **Catalog** | `local` |
| A department | **Namespace** (database) | `reposphere` |
| A person | **Table** | `events`, `repo_dim` |
| The extension number | The pointer to the current `metadata.json` | Changes on every commit |
| Where the directory is stored | Catalog **type** and **warehouse** | `hadoop`, `warehouse/` |

So `local.reposphere.events` reads as: *in catalog `local`, namespace `reposphere`, table `events`.* Spark asks the catalog "where is the current metadata for this table?" and gets a pointer back.

---

## Step 1: A Spark Session That Speaks Iceberg ⚙️

Plain Spark doesn't know Iceberg. You add **three** things, all through session config.

![What init_spark_session adds to plain Spark](content/data-engineering/images/session_three_pieces.svg)

```python
from pyspark.sql import SparkSession


def init_spark_session() -> SparkSession:
    return (
        SparkSession.builder
        .appName("reposphere-lake")
        .master("local[*]")
        # 1. The library. Match YOUR Spark and Scala versions.
        .config("spark.jars.packages",
                "org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.6.1")
        # 2. SQL extensions: MERGE INTO, CALL procedures, partition DDL.
        .config("spark.sql.extensions",
                "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions")
        # 3. A catalog named "local", kept as files in warehouse/.
        .config("spark.sql.catalog.local", "org.apache.iceberg.spark.SparkCatalog")
        .config("spark.sql.catalog.local.type", "hadoop")
        .config("spark.sql.catalog.local.warehouse", "warehouse/")
        # Same session time zone as Part 1.
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )
```

A few details that save you an afternoon:

| Setting | What it does | Gotcha |
|---|---|---|
| `spark.jars.packages` | Downloads the Iceberg jar from Maven on first run | Needs internet once. The `3.5_2.12` part must match your Spark and Scala |
| `spark.sql.extensions` | Adds `MERGE INTO`, `CALL`, `ALTER TABLE ... PARTITION FIELD` to Spark's SQL | Without it, reads and inserts still work |
| `spark.sql.catalog.local` | Registers a catalog. **The name after `catalog.` is yours to choose** | It becomes the first part of every table name |
| `.type` = `hadoop` | The "current metadata" pointer lives in a file inside the warehouse | Perfect for learning and tests. Production uses Hive, Glue, REST or Nessie |
| `.warehouse` | Root folder for every table in this catalog | A relative path is relative to where you launch Spark |
| `spark.sql.session.timeZone` | Fixes how timestamps are parsed and shown | Same UTC rule as [Post 04](content/data-engineering/04-flattening-and-timestamps.md) |

> **Trap: forgetting the extensions.** This is the sneaky one. Without `spark.sql.extensions`, the session still creates tables, inserts rows and reads them back. Everything *looks* fine. Then, three posts from now, `MERGE INTO` fails with a parse error, miles from the real cause. Set it on day one.

> **Key insight:** The catalog name is just a label you picked. Call it `local`, `lake`, or `banana`. Every table name then starts with it. The requirement says `local`, so we use `local`.

---

## Step 2: Where Does a Table Actually Live? 📂

Once the session exists, a table name resolves to a folder.

![One table name, three parts, one folder on disk](content/data-engineering/images/catalog_name_resolution.svg)

With the `hadoop` catalog there's no server. **The warehouse folder is the catalog.** The namespace is a sub-folder, the table is a sub-folder inside that, and Iceberg splits each table into `metadata/` (the tree from Post 10) and `data/` (the Parquet files).

That's also why the lab says to delete `warehouse/` before each full test run. The tables are real files on disk, and they persist between runs. That's the whole point of Part 2.

---

## Step 3: `create_tables`, Safe to Run Twice 🧱

The spec for the two tables is precise, so let's read it as a contract.

| | `local.reposphere.events` | `local.reposphere.repo_dim` |
|---|---|---|
| Columns | `event_id`, `event_type`, `created_ts`, `event_date`, `repo_id`, `actor_login` | `change_id`, `repo_id`, `repo_name`, `visibility`, `default_branch`, `valid_from`, `valid_to`, `is_current` |
| Partitioning | **Hidden**, `days(created_ts)` | None needed |
| Format version | 2 | 2 |
| Re-runnable | Yes | Yes |

And the solution:

```python
def create_tables(spark: SparkSession) -> None:
    spark.sql("CREATE NAMESPACE IF NOT EXISTS local.reposphere")

    spark.sql("""
        CREATE TABLE IF NOT EXISTS local.reposphere.events (
            event_id     STRING,
            event_type   STRING,
            created_ts   TIMESTAMP,
            event_date   DATE,
            repo_id      BIGINT,
            actor_login  STRING
        )
        USING iceberg
        PARTITIONED BY (days(created_ts))
        TBLPROPERTIES ('format-version' = '2')
    """)

    spark.sql("""
        CREATE TABLE IF NOT EXISTS local.reposphere.repo_dim (
            change_id       STRING,
            repo_id         BIGINT,
            repo_name       STRING,
            visibility      STRING,
            default_branch  STRING,
            valid_from      TIMESTAMP,
            valid_to        TIMESTAMP,
            is_current      BOOLEAN
        )
        USING iceberg
        TBLPROPERTIES ('format-version' = '2')
    """)
```

Run it, then run it again. Nothing breaks and nothing is wiped:

```python
spark = init_spark_session()
create_tables(spark)
create_tables(spark)          # second call: a silent no-op

spark.sql("SHOW TABLES IN local.reposphere").show(truncate=False)
spark.table("local.reposphere.events").printSchema()
```

```
+----------+---------+-----------+
|namespace |tableName|isTemporary|
+----------+---------+-----------+
|reposphere|events   |false      |
|reposphere|repo_dim |false      |
+----------+---------+-----------+

root
 |-- event_id: string (nullable = true)
 |-- event_type: string (nullable = true)
 |-- created_ts: timestamp (nullable = true)
 |-- event_date: date (nullable = true)
 |-- repo_id: long (nullable = true)
 |-- actor_login: string (nullable = true)
```

Three small decisions in that code, each with a reason:

| Decision | Why |
|---|---|
| `IF NOT EXISTS` on the namespace **and** both tables | The job runs `create_tables` at the start of **every** run. Without it, run two dies with `TableAlreadyExistsException` |
| `USING iceberg` | Picks the table format. Without it, Spark falls back to its default and you don't get an Iceberg table |
| `'format-version' = '2'` | Version 2 allows **row-level deletes**, which `MERGE INTO` can use in merge-on-read mode (Post 13). Newer Iceberg releases default to 2, but saying it out loud removes the doubt |

> **Trap: "fixing" a failed re-run with `CREATE OR REPLACE TABLE`.** It makes the error go away, and it also **replaces the table on every run**. Monday's data, gone. Idempotent setup means "create if missing, otherwise leave it exactly alone".

---

## Step 4: Hidden Partitioning, the Part Worth Slowing Down For 🙈

Partitioning splits a table's files by some rule, so a query for one day can skip every other day.

The old Hive way: add a **column** for the partition, and make your code fill it in.

```sql
-- Hive style: you maintain a separate partition column
PARTITIONED BY (event_date)
```

The Iceberg way: partition by a **transform** of a column you already have.

```sql
-- Iceberg style: derived from created_ts, nothing extra to store
PARTITIONED BY (days(created_ts))
```

![Same filter, two partition styles](content/data-engineering/images/hive_vs_hidden_partitioning.svg)

| | Hive style `PARTITIONED BY (event_date)` | Iceberg hidden `PARTITIONED BY (days(created_ts))` |
|---|---|---|
| Who fills the partition value? | Your code, on every row. A wrong `event_date` means a wrong folder | Iceberg, from `created_ts` |
| Query filters on `created_ts` | Scans **everything**. The planner doesn't know the two columns are related | Skips other days automatically |
| Query filters on `event_date` | Prunes | Doesn't prune by itself: filter `created_ts` instead |
| Want months instead of days later? | Rewrite the table | Change the partition spec. Old files keep the old layout |

> **Why not partition by `event_date`?** Because users naturally filter on the *real* column, `created_ts`. A partition column that nobody filters on is dead weight. Keeping `event_date` as a convenience column is fine, and we do. Just don't partition by it.

The built-in transforms:

| Transform | Example | Good for |
|---|---|---|
| `years(ts)` / `months(ts)` / `days(ts)` / `hours(ts)` | `days(created_ts)` | Time-series tables |
| `bucket(N, col)` | `bucket(16, repo_id)` | Spreading a high-cardinality key |
| `truncate(W, col)` | `truncate(4, repo_name)` | Grouping by a prefix |
| `identity` (a plain column) | `PARTITIONED BY (visibility)` | Low-cardinality categories |

### What does `days(created_ts)` do to our data?

A row's partition comes from **its own timestamp**, never from the day it was loaded. You can see that without Spark. This is the transform in plain Python, applied to batch 2's events:

```python
from datetime import datetime

batch_2 = [
    ("e04", "2024-03-01T11:20:00Z"),   # replay of a batch 1 event
    ("e05", "2024-03-01T10:15:00Z"),   # replay of a batch 1 event
    ("e06", "2024-03-01T23:40:00Z"),   # late: belongs to day 1
    ("e07", "2024-03-02T09:05:00Z"),
    ("e08", "2024-03-02T09:45:00Z"),
    ("e09", "2024-03-02T10:00:00Z"),
    ("e10", "2024-03-02T10:30:00Z"),
]

for event_id, created_at in batch_2:
    day = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").date()
    print(event_id, created_at, "->", f"created_ts_day={day}")
```

```
e04 2024-03-01T11:20:00Z -> created_ts_day=2024-03-01
e05 2024-03-01T10:15:00Z -> created_ts_day=2024-03-01
e06 2024-03-01T23:40:00Z -> created_ts_day=2024-03-01
e07 2024-03-02T09:05:00Z -> created_ts_day=2024-03-02
e08 2024-03-02T09:45:00Z -> created_ts_day=2024-03-02
e09 2024-03-02T10:00:00Z -> created_ts_day=2024-03-02
e10 2024-03-02T10:30:00Z -> created_ts_day=2024-03-02
```

Look at **e06**. It shows up in batch 2, but it happened at 23:40 on 1 March, so it lands in the **2024-03-01** partition. The table's "1 March" stays correct even when data arrives late. (Posts 12 and 13 deal with the replays, e04 and e05.)

Once both batches are loaded, the `partitions` metadata table confirms the layout. The lab's expected result is two partitions, 6 rows on 1 March and 4 on 2 March:

```python
from pyspark.sql import functions as F

(spark.table("local.reposphere.events.partitions")
      .select(F.col("partition.created_ts_day").alias("day"), "record_count")
      .orderBy("day")
      .show(truncate=False))
```

```
+----------+------------+
|day       |record_count|
+----------+------------+
|2024-03-01|6           |
|2024-03-02|4           |
+----------+------------+
```

Six on 1 March: e01 to e05 from batch 1, plus the late e06. Four on 2 March: e07 to e10. Ten events in total, which is exactly the "events after batch 2" table the lab expects.

> **Key insight:** A partition value in Iceberg is *metadata about a file*, not data inside the rows. That's why no `created_ts_day` column ever appears when you `SELECT *`.

---

## Putting It Together 🧩

Here's the start of `main()` for Part 2. Two lines, and everything after them can assume the tables exist:

```python
def main():
    spark = init_spark_session()
    create_tables(spark)
    # ... load batch 1, evolve schema, load batch 2 twice, compact ...
```

And the checklist for this post's two functions:

| Check | Why it matters |
|---|---|
| Is `spark.sql.extensions` set? | Otherwise `MERGE` and `CALL` fail later |
| Does every `CREATE` have `IF NOT EXISTS`? | Run two must be a no-op |
| Is `events` partitioned by `days(created_ts)`, not `event_date`? | Filters on `created_ts` should prune |
| Are both tables `format-version` 2? | Row-level deletes and updates need it |
| Is the warehouse wiped before a *fresh* test run? | State persists on purpose |

---

## Quick Quiz 🧠

**Q1.** A teammate's session sets the jar and the `local` catalog, but forgets `spark.sql.extensions`. Why might they not notice for a while, and where does it finally break?

<details>
<summary>Show answer</summary>

Because nothing in Post 11 needs the extensions. `CREATE TABLE`, `INSERT` and `SELECT` all work with just the jar and the catalog. The failure appears when they first run `MERGE INTO` (Post 13) or `CALL local.system.rewrite_data_files(...)` (Post 17), which need the extension's SQL parser. The error then looks unrelated to configuration, which is why it's worth setting on day one.

</details>

**Q2.** What does the name `local` in `spark.sql.catalog.local` control?

<details>
<summary>Show answer</summary>

It's just the label you chose for the catalog, and it becomes the **first part of every table name**: `local.reposphere.events`. You could have called it `lake` and written `lake.reposphere.events`. The keys after it (`.type`, `.warehouse`) configure that one catalog. The class, `org.apache.iceberg.spark.SparkCatalog`, is what makes it an Iceberg catalog.

</details>

**Q3.** `create_tables` runs at the start of every daily job. Someone replaces `CREATE TABLE IF NOT EXISTS` with `CREATE OR REPLACE TABLE` to stop the "already exists" error. What happens on the second day?

<details>
<summary>Show answer</summary>

The error disappears, and so does yesterday's data. `CREATE OR REPLACE` swaps the table for a fresh empty one on every run, so each day starts from nothing. `IF NOT EXISTS` is the right tool: create it when it's missing, leave it completely alone when it's there.

</details>

**Q4.** Event e06 has `created_at` of `2024-03-01T23:40:00Z` but arrives in batch 2, on 2 March. Which `days(created_ts)` partition does it go into, and is that what you want?

<details>
<summary>Show answer</summary>

**2024-03-01.** The partition is computed from the row's own timestamp, not the load date. That's what you want: a query for "events on 1 March" finds e06 in the right place, and 1 March's partition simply grows by one row. If partitions followed load date, late data would pollute the wrong day.

</details>

**Q5.** The table is partitioned by `days(created_ts)`. A user runs `WHERE event_date = '2024-03-02'`. Will Iceberg skip the 1 March files, and what should the user filter on instead?

<details>
<summary>Show answer</summary>

Not through the partition spec: it's defined on `created_ts`, and `event_date` is just an ordinary column here, so the planner has no partition rule connecting the two. Filter on the real column instead, for example `WHERE created_ts >= '2024-03-02' AND created_ts < '2024-03-03'`. That's the whole idea of hidden partitioning: users write predicates on real columns, and pruning follows without them knowing the partition layout.

</details>

---

## What's Next? 🚀

You now have a session that speaks Iceberg, a catalog called `local` backed by a `warehouse/` folder, and two empty tables that survive being created over and over.

Next, we put the first data in. Duplicates inside a batch, replays from yesterday, and a column the table doesn't have yet: how to load all of that so that running the same batch twice changes nothing.

👉 **[Post 12 — Idempotent Loads](content/data-engineering/12-idempotent-loads.md)**: dedupe the batch, anti join against the table, align columns by name with typed NULLs, and why `overwrite` isn't idempotent.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
