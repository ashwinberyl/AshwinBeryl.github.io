---
title: "Incremental SCD Type 2"
date: 2026-10-26
tags: [data-engineering, apache-iceberg, pyspark, scd2, merge, lakehouse]
description: Turn RepoSphere's repo history into an incremental job. Covers the six-step recipe for merge_repo_scd2 - new changes only, affected repos, recompute with the same window, diff against what is stored, then one MERGE - plus the proof that incremental equals a full rebuild.
---

# Rebuild Less, Change Only What Moved 🔧

In [Post 13](content/data-engineering/13-merge-into-in-depth.md), we handed `repo_diff` to a MERGE and it updated `c1`, inserted `c2` and `c6`, and left everything else alone. I told you to take that diff as given.

Time to earn it.

Back in [Post 06](content/data-engineering/06-scd-type-2.md), `build_repo_scd2` took **every** repo change and produced the full history. That works when the whole file is on your desk. It does not work when history is already stored and each day brings a handful of new rows.

Rebuild everything every night and you rewrite files that did not change, churn out a snapshot full of no-ops, and pay more every month as history grows. So the question for today:

> **Given what is already stored and today's batch, what is the smallest set of rows that must change?**

---

## The Relay Race Analogy 🏃

Picture a relay race. Each runner holds the baton **until the next runner starts**. That is `valid_to`: it is always the next runner's `valid_from`.

Now a late entry shows up. A new runner must be slotted **between** two runners who already ran.

Who has to change?

- The runner **before** the new one: they now hand over earlier.
- The new runner: they get a row.
- Everyone else: nothing. Their start and end are the same as before.

And the other relay teams in the stadium? They never notice.

| Relay race | RepoSphere |
|---|---|
| A team | A `repo_id` |
| A runner's leg | A version row in `repo_dim` |
| The late runner | Late change `c2` |
| The runner before them | `c1`, whose `valid_to` moves from 11:00 to 10:00 |
| A team with no new runner | Repo 202 |

![Repo 101 before and after batch 2](content/data-engineering/images/repo101_incremental.svg)

---

## Where We Start 📍

After batch 1, `repo_dim` holds three rows:

```
+---------+-------+-------------+----------+--------------+-------------------+-------------------+----------+
|change_id|repo_id|repo_name    |visibility|default_branch|valid_from         |valid_to           |is_current|
+---------+-------+-------------+----------+--------------+-------------------+-------------------+----------+
|c1       |101    |alpha-api    |public    |main          |2024-03-01 09:00:00|2024-03-01 11:00:00|false     |
|c3       |101    |alpha-service|public    |main          |2024-03-01 11:00:00|null               |true      |
|c4       |202    |beta-web     |public    |master        |2024-03-01 10:30:00|null               |true      |
+---------+-------+-------------+----------+--------------+-------------------+-------------------+----------+
```

Batch 2 brings three lines. `c3` is a **replay**. `c2` is a **late change**: its 10:00 lands inside `c1`'s `[09:00, 11:00)`. `c6` belongs to a **brand-new repo**:

```python
changes = read_repo_changes(spark, "data/batch_2/repo_changes.jsonl")
changes.show(truncate=False)
```

```
+---------+-------+--------------------+-------------+----------+--------------+
|change_id|repo_id|changed_at          |repo_name    |visibility|default_branch|
+---------+-------+--------------------+-------------+----------+--------------+
|c3       |101    |2024-03-01T11:00:00Z|alpha-service|public    |main          |
|c2       |101    |2024-03-01T10:00:00Z|alpha-api    |private   |main          |
|c6       |303    |2024-03-02T09:00:00Z|gamma-cli    |public    |trunk         |
+---------+-------+--------------------+-------------+----------+--------------+
```

The goal is a function that, given this DataFrame, leaves `repo_dim` equal to what a full rebuild would give. And running it twice must change nothing.

---

## The Six-Step Recipe 🧭

![The six steps on batch 2](content/data-engineering/images/merge_repo_scd2_steps.svg)

We take them one at a time, on batch 2.

### Step 1: New changes only 🆕

Dedupe the batch on `change_id`, then anti join against the `change_id`s already stored. That is the same two layers from [Post 12](content/data-engineering/12-idempotent-loads.md), applied to history.

```python
REPO_DIM = "local.reposphere.repo_dim"
COLS = ["change_id", "repo_id", "repo_name", "visibility", "default_branch", "valid_from"]

dim = spark.table(REPO_DIM)

new = (changes.dropDuplicates(["change_id"])
       .join(dim.select("change_id"), "change_id", "left_anti")
       .withColumn("valid_from", F.to_timestamp("changed_at"))
       .select(*COLS))

new.orderBy("change_id").show(truncate=False)
```

```
+---------+-------+---------+----------+--------------+-------------------+
|change_id|repo_id|repo_name|visibility|default_branch|valid_from         |
+---------+-------+---------+----------+--------------+-------------------+
|c2       |101    |alpha-api|private   |main          |2024-03-01 10:00:00|
|c6       |303    |gamma-cli|public    |trunk         |2024-03-02 09:00:00|
+---------+-------+---------+----------+--------------+-------------------+
```

`c3` is gone. If `new` were empty here, we would stop right now. Hold that thought, because it is what makes a re-run free.

### Step 2: Affected repos 🎯

Only repos that got a new change can have rows that change:

```python
affected = new.select("repo_id").distinct()
affected.orderBy("repo_id").show()
```

```
+-------+
|repo_id|
+-------+
|101    |
|303    |
+-------+
```

Repo 202 is not in the list. From here on, its rows are never read.

### Step 3: Their full history 📚

This step decides whether the whole job is correct. For each affected repo we need **everything**: the versions already stored, plus the new ones.

```python
history = (dim.join(affected, "repo_id", "left_semi")     # stored rows, affected repos only
              .select(*COLS)
              .unionByName(new))                           # plus today's new changes
history.orderBy("repo_id", "valid_from").show(truncate=False)
```

```
+---------+-------+-------------+----------+--------------+-------------------+
|change_id|repo_id|repo_name    |visibility|default_branch|valid_from         |
+---------+-------+-------------+----------+--------------+-------------------+
|c1       |101    |alpha-api    |public    |main          |2024-03-01 09:00:00|
|c2       |101    |alpha-api    |private   |main          |2024-03-01 10:00:00|
|c3       |101    |alpha-service|public    |main          |2024-03-01 11:00:00|
|c6       |303    |gamma-cli    |public    |trunk         |2024-03-02 09:00:00|
+---------+-------+-------------+----------+--------------+-------------------+
```

A **left semi** join keeps the rows of the left side that have a match on the right, and adds no columns. It is the "filter by this list" join. Both sides are shaped to the same six columns first, and `unionByName` matches them by **name**, not position.

> **Trap: recomputing only the new rows.** Run `lead` over `new` alone and `c2` has nothing after it, so its `valid_to` is `NULL`. Stored `c1` is never looked at, and stored `c3` is still current. This is what that wrong diff would look like:

```
+---------+-------+-------------------+--------+----------+
|change_id|repo_id|valid_from         |valid_to|is_current|
+---------+-------+-------------------+--------+----------+
|c2       |101    |2024-03-01 10:00:00|null    |true      |
|c6       |303    |2024-03-02 09:00:00|null    |true      |
+---------+-------+-------------------+--------+----------+
```

Insert that, and repo 101 has two "current" rows (`c2` and `c3`) and a `c1` that overlaps `c2`. The window must see the stored history too.

### Step 4: Recompute 🔄

Same window as Post 06: partition by repo, order by `valid_from`, break ties with `change_id`. `lead` gives each version the next version's start.

```python
w = Window.partitionBy("repo_id").orderBy("valid_from", "change_id")

candidates = (history
    .withColumn("valid_to", F.lead("valid_from").over(w))
    .withColumn("is_current", F.col("valid_to").isNull()))

candidates.orderBy("repo_id", "valid_from").show(truncate=False)
```

```
+---------+-------+-------------+----------+--------------+-------------------+-------------------+----------+
|change_id|repo_id|repo_name    |visibility|default_branch|valid_from         |valid_to           |is_current|
+---------+-------+-------------+----------+--------------+-------------------+-------------------+----------+
|c1       |101    |alpha-api    |public    |main          |2024-03-01 09:00:00|2024-03-01 10:00:00|false     |
|c2       |101    |alpha-api    |private   |main          |2024-03-01 10:00:00|2024-03-01 11:00:00|false     |
|c3       |101    |alpha-service|public    |main          |2024-03-01 11:00:00|null               |true      |
|c6       |303    |gamma-cli    |public    |trunk         |2024-03-02 09:00:00|null               |true      |
+---------+-------+-------------+----------+--------------+-------------------+-------------------+----------+
```

These are the **candidates**: what the table should say for repos 101 and 303. Notice `c1` ends at 10:00 now, and `c2` slots in between `c1` and `c3`. Repo 303 is simply a single current row.

### Step 5: Diff 🔍

Most candidates are identical to what is stored (`c3` is). We only want rows that are **new**, or whose `valid_to` or `is_current` **differ** from storage.

```python
stored = dim.select(
    F.col("change_id").alias("stored_id"),
    F.col("valid_to").alias("old_valid_to"),
    F.col("is_current").alias("old_is_current"),
)

repo_diff = (candidates
    .join(stored, candidates.change_id == stored.stored_id, "left")
    .where(
        F.col("stored_id").isNull()                                   # not stored yet
        | ~(F.col("valid_to").eqNullSafe(F.col("old_valid_to"))
            & F.col("is_current").eqNullSafe(F.col("old_is_current")))  # stored, but changed
    )
    .select(*COLS, "valid_to", "is_current"))

repo_diff.orderBy("change_id").show(truncate=False)
```

```
+---------+-------+---------+----------+--------------+-------------------+-------------------+----------+
|change_id|repo_id|repo_name|visibility|default_branch|valid_from         |valid_to           |is_current|
+---------+-------+---------+----------+--------------+-------------------+-------------------+----------+
|c1       |101    |alpha-api|public    |main          |2024-03-01 09:00:00|2024-03-01 10:00:00|false     |
|c2       |101    |alpha-api|private   |main          |2024-03-01 10:00:00|2024-03-01 11:00:00|false     |
|c6       |303    |gamma-cli|public    |trunk         |2024-03-02 09:00:00|null               |true      |
+---------+-------+---------+----------+--------------+-------------------+-------------------+----------+
```

That is exactly the `repo_diff` from Post 13. Three rows: one update (`c1`), two inserts (`c2`, `c6`).

> **Trap: `!=` hides the "closing" case.** A stored current row has `valid_to = NULL`. When a newer version arrives, the candidate has a real timestamp. `NULL != timestamp` is `NULL`, so the row is dropped and never closed. `eqNullSafe` (SQL: `<=>`) always returns true or false.

### Step 6: MERGE ✏️

Pattern 2 from Post 13, unchanged:

```python
repo_diff.createOrReplaceTempView("repo_diff")

spark.sql(f"""
    MERGE INTO {REPO_DIM} t
    USING repo_diff s
    ON t.change_id = s.change_id
    WHEN MATCHED AND NOT (t.valid_to <=> s.valid_to AND t.is_current <=> s.is_current)
      THEN UPDATE SET t.valid_to = s.valid_to, t.is_current = s.is_current
    WHEN NOT MATCHED THEN INSERT *
""")
```

`INSERT *` works because `repo_diff` carries all eight table columns by name. The `UPDATE SET` touches only the two columns that may move.

---

## The Whole Function 🧩

Here it is in one piece:

```python
from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F

REPO_DIM = "local.reposphere.repo_dim"
COLS = ["change_id", "repo_id", "repo_name", "visibility", "default_branch", "valid_from"]


def merge_repo_scd2(df: DataFrame) -> None:
    spark = df.sparkSession
    dim = spark.table(REPO_DIM)

    # 1. new changes only
    new = (df.dropDuplicates(["change_id"])
             .join(dim.select("change_id"), "change_id", "left_anti")
             .withColumn("valid_from", F.to_timestamp("changed_at"))
             .select(*COLS))
    if new.isEmpty():
        return                                            # a re-run ends here

    # 2. affected repos
    affected = new.select("repo_id").distinct()

    # 3. their full history: stored + new
    history = (dim.join(affected, "repo_id", "left_semi")
                  .select(*COLS)
                  .unionByName(new))

    # 4. recompute validity with the Part 1 window
    w = Window.partitionBy("repo_id").orderBy("valid_from", "change_id")
    candidates = (history
        .withColumn("valid_to", F.lead("valid_from").over(w))
        .withColumn("is_current", F.col("valid_to").isNull()))

    # 5. diff against what is stored
    stored = dim.select(F.col("change_id").alias("stored_id"),
                        F.col("valid_to").alias("old_valid_to"),
                        F.col("is_current").alias("old_is_current"))
    repo_diff = (candidates
        .join(stored, candidates.change_id == stored.stored_id, "left")
        .where(F.col("stored_id").isNull()
               | ~(F.col("valid_to").eqNullSafe(F.col("old_valid_to"))
                   & F.col("is_current").eqNullSafe(F.col("old_is_current"))))
        .select(*COLS, "valid_to", "is_current"))

    # 6. one atomic MERGE
    repo_diff.createOrReplaceTempView("repo_diff")
    spark.sql(f"""
        MERGE INTO {REPO_DIM} t
        USING repo_diff s
        ON t.change_id = s.change_id
        WHEN MATCHED AND NOT (t.valid_to <=> s.valid_to AND t.is_current <=> s.is_current)
          THEN UPDATE SET t.valid_to = s.valid_to, t.is_current = s.is_current
        WHEN NOT MATCHED THEN INSERT *
    """)
```

Notice there is no second emptiness check before the MERGE. Once `new` has a row, that row is always in `repo_diff`, so the diff cannot be empty.

Now run batch 1, batch 2, and batch 2 again:

```python
for name in ["batch_1", "batch_2", "batch_2"]:
    merge_repo_scd2(read_repo_changes(spark, f"data/{name}/repo_changes.jsonl"))
    print(name, "->", spark.table(REPO_DIM).count(), "rows")
```

```
batch_1 -> 3 rows
batch_2 -> 5 rows
batch_2 -> 5 rows
```

And the table:

```python
spark.table(REPO_DIM).orderBy("repo_id", "valid_from").show(truncate=False)
```

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

The second batch 2 run stopped at step 1: after the anti join, nothing was left. No diff, no MERGE, no new snapshot.

---

## Proof: Incremental Equals Full Rebuild ✅

"It looks right" is not a test. The real contract is stronger: **for every repo, the stored rows must equal what `build_repo_scd2` gives over all changes ever loaded.**

Build that expected table from both batches, then compare in both directions with `exceptAll`:

```python
all_changes = (read_repo_changes(spark, "data/batch_1/repo_changes.jsonl")
               .unionByName(read_repo_changes(spark, "data/batch_2/repo_changes.jsonl"))
               .dropDuplicates(["change_id"]))

expected = build_repo_scd2(all_changes)
actual = spark.table(REPO_DIM).select(expected.columns)    # drops change_id, same order

print(expected.exceptAll(actual).count())
print(actual.exceptAll(expected).count())
```

```
0
0
```

Two zeros mean nothing is missing and nothing is extra. Keep this check around. It is the one test that catches a broken window, a lost tie-break, or a `!=` that should be `<=>`.

---

## Full Rebuild vs Incremental ⚖️

| | Full rebuild | Incremental (`merge_repo_scd2`) |
|---|---|---|
| Rows read from history | All repos, every run | Affected repos only |
| Rows written | The whole table | Changed and new rows only |
| Re-run of the same batch | Rewrites everything, same result | Returns at step 1, writes nothing |
| Cost as history grows | Grows every night | Grows with the **batch**, not the table |
| Risk | Simple, hard to get wrong | Needs the equality test above |

> **Key insight:** Incremental does not mean "apply the new rows". It means **recompute the small part of the world the new rows can affect, then write back only the difference**.

---

## Pre-Flight Checklist 🛫

| Check | Why it matters |
|---|---|
| Batch deduped, then anti joined on `change_id`? | Replays must drop out before anything else |
| Return early when nothing is new? | Makes the re-run free and snapshot-free |
| History for affected repos includes **stored** rows? | Otherwise `lead` has nothing to look at and `c1` is never closed |
| Window orders by `valid_from`, then `change_id`? | Same-instant changes must resolve the same way every run |
| Diff uses `eqNullSafe`, not `!=`? | Closing a current row means going from `NULL` to a value |
| `UPDATE SET` names only `valid_to` and `is_current`? | Version facts are never rewritten |
| Equality check against `build_repo_scd2` passes? | The proof that incremental equals a full rebuild |

---

## Quick Quiz 🧠

**Q1.** In batch 2, why is repo 202 never read, and what would go wrong if you recomputed it anyway?

<details>
<summary>Show answer</summary>

It has no new change, so none of its rows can be affected. Recomputing it would give the same answer as what is stored, and the diff would drop it. You would still pay to scan and window it. At scale that is waste, and in copy-on-write mode it can mean rewriting files for no reason.

</details>

**Q2.** You compute `lead` over only the new rows `c2` and `c6`. What does repo 101 look like after the MERGE?

<details>
<summary>Show answer</summary>

`c2` gets `valid_to = NULL` and `is_current = true`, because nothing follows it in the batch. Stored `c1` is untouched, so it still runs to 11:00 and overlaps `c2`. Stored `c3` is still current. Repo 101 now has **two current rows** and an overlap. The window must see stored history as well.

</details>

**Q3.** `c3` is in the batch and in the table. Where does it drop out, and what does the batch-2 re-run do?

<details>
<summary>Show answer</summary>

It drops out at **step 1**, in the anti join on `change_id`. On the re-run, `c2` and `c6` are stored too, so `new` is empty and `merge_repo_scd2` returns immediately. No diff is built, no MERGE runs, and no snapshot is committed.

</details>

**Q4.** Suppose a later change `c7` for repo 202 arrives with `changed_at` 12:00. Which rows end up in `repo_diff`, and why does null-safe comparison matter?

<details>
<summary>Show answer</summary>

Two rows. `c4` is stored with `valid_to = NULL`, and the candidate says `valid_to = 12:00` with `is_current = false`, so it goes in as an **update**. `c7` is new, so it goes in as an **insert**. With `!=`, `NULL != 12:00` is `NULL` and `c4` would never be closed. `eqNullSafe` returns false for that pair, so the negation is true and the row is kept.

</details>

**Q5.** Why is the final check a pair of `exceptAll` counts, and why `exceptAll` instead of `except`?

<details>
<summary>Show answer</summary>

You need **both directions**: `expected - actual` finds rows that are missing, `actual - expected` finds rows that should not be there. `exceptAll` respects duplicate counts, while `except` removes duplicates first. A table that held the same row twice would pass `except` and fail `exceptAll`. Two zeros means the tables are identical.

</details>

---

## What's Next? 🚀

You now have the whole incremental history engine: find the new changes, recompute only the repos they touch, diff against storage, and write back the difference in one commit. And you can prove it matches a full rebuild.

Both tables are now being written, one commit per batch. Every one of those commits left an old version behind. What did the table look like **after batch 1**, before the late change arrived?

Next, we open the snapshot history and read the table as it was.

👉 **[Post 15 — Snapshots and Time Travel](content/data-engineering/15-snapshots-and-time-travel.md)**: `list_snapshots` and `read_events_as_of`.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
