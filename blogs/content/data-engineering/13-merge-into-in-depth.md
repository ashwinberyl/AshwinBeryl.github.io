---
title: "MERGE INTO in Depth"
date: 2026-10-25
tags: [data-engineering, apache-iceberg, pyspark, merge, lakehouse]
description: Turn RepoSphere's two-step load into one atomic MERGE INTO. Covers the anatomy of a MERGE, insert-only upserts for events, conditional updates with the null-safe operator, duplicate source keys, copy-on-write vs merge-on-read, and skipping empty sources.
---

# One Statement, All or Nothing 🔀

In [Post 12](content/data-engineering/12-idempotent-loads.md), we built `upsert_events`: dedupe the batch, anti join against the table, align the columns, append. Load batch 2 twice and the second run inserts **0** rows.

It works. But look at its shape:

1. **Read** the table to find what's new.
2. **Write** the new rows in a separate step.

Between those two steps, the world can change. And there's a bigger gap. An append can only **add** rows. Last time a repo's history changed (a late `c2` arrives and cuts `c1` short), we have to **edit a row we already stored**. Append can't do that.

You need one statement that says: *"for each incoming row, find its twin in the table. If there's none, insert. If there is one, maybe update it."* All of it committed as a single snapshot.

That statement is **`MERGE INTO`**.

---

## The Receptionist Analogy 🗂️

Picture a receptionist with a register of visitors, and a stack of today's arrival cards.

For **each card**, she does the same thing:

1. Look up the name in the register. That's the **match rule**.
2. **Name not found?** Write a new line.
3. **Name found?** Check whether anything changed. If yes, correct that one line. If no, leave it alone.

She doesn't rewrite the register, and she doesn't re-enter people who are already in it.

| Receptionist | MERGE INTO | RepoSphere |
|---|---|---|
| The register | **Target** table | `local.reposphere.events`, `repo_dim` |
| The stack of cards | **Source** (a view of the batch) | `incoming_events`, `repo_diff` |
| "Look up the name" | The **`ON`** condition | `t.event_id = s.event_id` |
| "Not found, write a line" | `WHEN NOT MATCHED THEN INSERT` | New events, new repo versions |
| "Found, fix the line" | `WHEN MATCHED THEN UPDATE` | Close `c1`'s `valid_to` |
| "Found, nothing changed" | No clause fires | Replays, unchanged history |

![What MERGE does with each source row](content/data-engineering/images/merge_row_routing.svg)

---

## Anatomy of a MERGE 🔬

```sql
MERGE INTO local.reposphere.repo_dim AS t      -- target: the Iceberg table
USING repo_diff AS s                           -- source: a table or temp view
ON t.change_id = s.change_id                   -- how a source row finds its twin
WHEN MATCHED [AND <extra condition>] THEN UPDATE SET ... | DELETE
WHEN NOT MATCHED [AND <extra condition>] THEN INSERT ...
```

For every source row, Spark checks `ON`:

- **A twin exists** → it runs the first `WHEN MATCHED` clause whose extra condition is true.
- **No twin** → it runs the first true `WHEN NOT MATCHED` clause.
- **No clause is true** → that row is left alone.

And all of it lands as **one snapshot**, or nothing does. That's the atomic commit from [Post 10](content/data-engineering/10-why-table-formats-iceberg.md) doing its job.

Spark SQL can't see a DataFrame directly. You register it as a **temp view** first:

```python
batch.createOrReplaceTempView("incoming_events")   # visible to spark.sql in this session
```

> **Key insight:** MERGE is a **join** with three possible outcomes per row: insert, update, or ignore. Think about each outcome separately and it stops being scary.

---

## Pattern 1: Insert-Only (`upsert_events`) ➕

For events, the rule from Post 12 stays: **first write wins**, and a stored event is never touched.

```sql
MERGE INTO local.reposphere.events t
USING incoming_events s
ON t.event_id = s.event_id
WHEN NOT MATCHED THEN INSERT *
```

There is **no** `WHEN MATCHED` clause. A replayed `e04` finds its twin and... nothing happens. That's the whole trick.

`INSERT *` maps source columns to target columns **by name**, so the source needs exactly the table's columns. That's the guarantee `align_to_table` from Post 12 gives you.

Here's `upsert_events`, rebuilt around one MERGE:

```python
EVENTS = "local.reposphere.events"


def upsert_events(df: DataFrame) -> int:
    spark = df.sparkSession
    batch = align_to_table(df.dropDuplicates(["event_id"]), EVENTS)

    stored = spark.table(EVENTS).select("event_id")
    inserted = batch.join(stored, "event_id", "left_anti").count()
    if inserted == 0:
        return 0                                  # nothing to do, skip the MERGE

    batch.createOrReplaceTempView("incoming_events")
    spark.sql(f"""
        MERGE INTO {EVENTS} t
        USING incoming_events s
        ON t.event_id = s.event_id
        WHEN NOT MATCHED THEN INSERT *
    """)
    return inserted
```

Same three loads as before:

```python
for name in ["batch_1", "batch_2", "batch_2"]:
    flat = flatten_events(read_events(spark, f"data/{name}/events.jsonl"))
    print(name, "->", upsert_events(flat))
```

```
batch_1 -> 5
batch_2 -> 5
batch_2 -> 0
```

The table ends with the same ten events as Post 12, and the difference is how they got there. Each load is now **one commit** instead of a read followed by an append.

> **Why keep the anti join if MERGE already skips stored ids?** Two reasons. MERGE can't tell you **how many** rows it inserted, and the spec wants that number back. And when the count is `0` we skip the MERGE entirely (more on that below).

---

## Trap: Duplicate Keys in the Source 👯

This one catches everybody. What if you forget `dropDuplicates` and batch 1 goes in with `e03` on two lines?

| MERGE shape | Two source rows share a key | Result |
|---|---|---|
| Has a `WHEN MATCHED` clause, and the key already exists in the table | Both source rows match **one** target row | **Error.** Spark refuses: it can't decide which source row should update the target row |
| Insert-only, and the key is new | Neither copy matches anything | **No error.** Both copies are inserted |

Run batch 1 through the insert-only MERGE without Layer 1 and the table gets **6** rows. `e03` sits there twice, and nobody gets a warning.

> **Trap: the quiet failure is the dangerous one.** An error stops the job and you fix it. Duplicate inserts keep going, and the damage spreads into every `COUNT(*)` downstream. **Always dedupe the source on the match key before a MERGE.**

---

## Pattern 2: Update Only When Something Changed ✏️

Now the history table. Batch 2 brings three repo changes:

| change_id | repo | What it is |
|---|---|---|
| `c3` | 101 | A **replay**. Already stored. |
| `c2` | 101 | A **late change**: `changed_at` 10:00 lands inside `c1`'s `[09:00, 11:00)` |
| `c6` | 303 | A change for a **new repo** |

Post 14 builds the diff DataFrame step by step. For now, take it as given. After dropping the replay and recomputing history for repos 101 and 303, the rows that **differ** from what's stored are:

```python
repo_diff.orderBy("change_id").show(truncate=False)
```

```
+---------+-------+-------------+----------+--------------+-------------------+-------------------+----------+
|change_id|repo_id|repo_name    |visibility|default_branch|valid_from         |valid_to           |is_current|
+---------+-------+-------------+----------+--------------+-------------------+-------------------+----------+
|c1       |101    |alpha-api    |public    |main          |2024-03-01 09:00:00|2024-03-01 10:00:00|false     |
|c2       |101    |alpha-api    |private   |main          |2024-03-01 10:00:00|2024-03-01 11:00:00|false     |
|c6       |303    |gamma-cli    |public    |trunk         |2024-03-02 09:00:00|null               |true      |
+---------+-------+-------------+----------+--------------+-------------------+-------------------+----------+
```

Three rows, three jobs:

- `c1` **exists**, and its `valid_to` has to move from 11:00 to 10:00 → **update**.
- `c2` is new → **insert**.
- `c6` is new → **insert**.

`c3` and `c4` aren't here at all, so MERGE never sees them. They stay exactly as stored.

```sql
MERGE INTO local.reposphere.repo_dim t
USING repo_diff s
ON t.change_id = s.change_id
WHEN MATCHED AND NOT (t.valid_to <=> s.valid_to AND t.is_current <=> s.is_current)
  THEN UPDATE SET t.valid_to = s.valid_to, t.is_current = s.is_current
WHEN NOT MATCHED THEN INSERT *
```

```python
spark.table("local.reposphere.repo_dim").orderBy("repo_id", "valid_from").show(truncate=False)
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

Repo 101's history is now three clean, back-to-back versions. Repo 202 was never read or written.

Two details in that statement deserve a close look.

**`UPDATE SET` lists only the columns that may change.** `UPDATE SET *` would overwrite every column. For history rows, `repo_name`, `visibility` and `valid_from` are facts about that version. Only the end of the interval and the `is_current` flag may move.

**`<=>` is null-safe equality.** Plain `=` gives `NULL` when either side is `NULL`, and a `WHEN MATCHED AND NULL` clause **does not fire**. `<=>` always gives true or false:

| `t.valid_to` | `s.valid_to` | `t.valid_to != s.valid_to` | `NOT (t.valid_to <=> s.valid_to)` |
|---|---|---|---|
| 11:00 | 10:00 | true → update | true → update |
| null | null | null → skip | false → skip |
| **null** | **12:00** | **null → skip (bug)** | **true → update** |

That last row isn't in today's data, so here is a **hypothetical**. Say a later change `c7` arrives for repo 101 at 12:00. It must close `c3`, whose `valid_to` is `NULL` today. With `!=`, the comparison is `NULL`, the clause never fires, and `c3` stays "current" forever. Repo 101 ends up with **two** current rows.

> **Trap: `!=` and `NULL` strike again.** This is the same three-valued logic from [Post 02](content/data-engineering/02-spark-from-first-principles.md), now hiding inside a MERGE. Whenever a column can be `NULL` and you're asking "did it change?", reach for `<=>`. In the DataFrame API, that's `col.eqNullSafe(other)`.

---

## How Iceberg Actually Updates a Row 🧱

Parquet files can't be edited in place. So when MERGE updates `c1`, what happens on disk? Iceberg has two answers, and you pick one per table:

| | **Copy-on-write** (default) | **Merge-on-read** (format v2 only) |
|---|---|---|
| On update | Rewrites each data file that holds a matched row | Writes a small **delete file** that marks the old row, plus the new row |
| Write cost | Higher: whole files are rewritten | Lower: only the changed rows are written |
| Read cost | Lowest: files are already clean | Higher: readers apply the delete files on the fly |
| Good for | Read-heavy tables, infrequent updates | Frequent small updates |

You choose with a table property:

```sql
ALTER TABLE local.reposphere.repo_dim
SET TBLPROPERTIES ('write.merge.mode' = 'merge-on-read')
```

That's why Post 11 insisted on `format-version = 2`. Merge-on-read needs row-level deletes, and v2 is where they live.

For RepoSphere, copy-on-write is the right call. `repo_dim` is tiny, and we read it far more than we change it.

> **Key insight:** In both modes, a MERGE that touches matched rows costs more than a MERGE that only inserts. Insert-only just adds new files. That's another reason the `events` table uses the cheap shape.

---

## Skip the Empty MERGE 🪫

On the re-run of batch 2, the source for `repo_dim` shrinks to **zero rows**. Every change was already stored, so there's nothing to diff.

You could still send an empty source to MERGE. Don't. Spark would plan the join, scan the table and ask for a commit, all to do nothing.

```python
if repo_diff.isEmpty():
    return
```

Cheap, obvious, and it makes the idempotent re-run really cheap. It's the same instinct as `if inserted == 0: return 0` in `upsert_events`.

The fix for copy-on-write cost is the same: **shrink the source** to rows that really need a change. Filtering before the MERGE is nearly free. Filtering inside it can still send Spark to rewrite files.

---

## Pre-Flight Checklist ✅

| Check | Why it matters |
|---|---|
| Source deduped on the `ON` key? | Duplicates cause an error with `WHEN MATCHED`, and silent double inserts without it |
| Insert-only for facts, with **no** `WHEN MATCHED`? | A replay can't overwrite a good row |
| `UPDATE SET` lists named columns, not `*`? | Only the columns that may change can change |
| `<=>` instead of `!=` when a column can be `NULL`? | `!=` silently skips the NULL-to-value case |
| Source filtered down to real changes? | Less to rewrite, and an empty source can skip MERGE entirely |
| Source columns match the target by name? | `INSERT *` maps by name |

---

## Quick Quiz 🧠

**Q1.** Why does `upsert_events` have no `WHEN MATCHED` clause at all?

<details>
<summary>Show answer</summary>

Because events are **facts**, and the rule is first write wins. With no `WHEN MATCHED` clause, a replayed `e04` finds its twin and nothing happens: no update, no rewrite. The table stays exactly as it was, which is what makes the load idempotent.

</details>

**Q2.** You skip `dropDuplicates` and run batch 1 (with `e03` twice) through the insert-only MERGE into an empty table. How many rows go in, and does Spark warn you?

<details>
<summary>Show answer</summary>

**6 rows, and no warning.** Neither copy of `e03` has a twin in the table, so both match `WHEN NOT MATCHED` and both are inserted. The "multiple source rows" error only appears when a source key matches an **existing** target row under a `WHEN MATCHED` clause. Always dedupe the source on the key first.

</details>

**Q3.** Batch 2's `repo_diff` has three rows: `c1`, `c2`, `c6`. Which are updates, which are inserts, and what happens to `c3` and `c4`?

<details>
<summary>Show answer</summary>

`c1` is the **update**: its `valid_to` moves from 11:00 to 10:00. `c2` and `c6` are **inserts**. `c3` and `c4` aren't in the source, so MERGE never touches them. That's exactly why we diff first: only rows that really change go in.

</details>

**Q4.** A later change `c7` for repo 101 arrives at 12:00. Why would `WHEN MATCHED AND t.valid_to != s.valid_to` fail to close `c3`, and what fixes it?

<details>
<summary>Show answer</summary>

`c3` is stored with `valid_to = NULL`, and `NULL != 12:00` evaluates to **NULL**, not true. A `WHEN MATCHED AND NULL` clause doesn't fire, so `c3` never gets closed and repo 101 has two current rows. Use the null-safe form `NOT (t.valid_to <=> s.valid_to AND ...)`, which returns true for NULL vs a real timestamp.

</details>

**Q5.** When would you switch `repo_dim` to `merge-on-read`, and why is it the wrong choice today?

<details>
<summary>Show answer</summary>

Switch when updates become **frequent and small** on a big table, so that rewriting whole files on every MERGE gets too expensive. Merge-on-read writes tiny delete files instead, at the cost of slower reads until compaction cleans up. `repo_dim` is small and read far more than it changes, so the default **copy-on-write** is simpler and faster to read.

</details>

---

## What's Next? 🚀

You now have one atomic statement that inserts what's new, updates what changed (and only that), and leaves everything else alone. You also know the three traps: duplicate source keys, `!=` against `NULL`, and sending a MERGE work it doesn't need.

But we skipped something. How did we get `repo_diff` in the first place? Why did only repos 101 and 303 get read, and how do we know the result matches a full rebuild from Part 1?

Next, we build `merge_repo_scd2` step by step: pick the affected repos, recompute their history with the same window logic, diff against what's stored, and MERGE.

👉 **[Post 14 — Incremental SCD Type 2](content/data-engineering/14-incremental-scd2.md)**: the six-step recipe for `merge_repo_scd2`, affected repos only, recompute, diff, MERGE.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
