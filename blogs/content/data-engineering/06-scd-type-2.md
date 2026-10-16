---
title: "SCD Type 2 — Keeping Every Version of the Truth"
date: 2026-10-17
tags: [data-engineering, pyspark, scd-type-2, dimensions, window-functions, first-principles]
description: How build_repo_scd2 turns RepoSphere's messy repo-change snapshots into a history table — SCD Types 1, 2 and 3 compared, what valid_from, valid_to and is_current really mean, why the interval must be half-open, how the late-arriving c2 slots in for free, and what to do when two changes land at the same instant.
---

# Every Version, Kept 🗂️

In [Post 05](content/data-engineering/05-window-functions.md), `lead` built a version history from five repo changes in four lines of code. It looked almost too easy.

This post is about why those four lines are **right**, and what breaks the moment you change one of them.

Here's the question that started it all, back in Post 01:

> At **10:40**, Dave filed an issue (`e03`) on repo 101. Was the repo **public or private** at that moment?

Today repo 101 is public and called `alpha-service`. But at 10:40 it was `alpha-api`, and it was **private**. An auditor asking "did anyone touch a private repo?" needs the 10:40 answer, not today's.

A table that only knows today can't answer that. You need a table that remembers **every version**, and **when** each one was true.

That's a **Slowly Changing Dimension, Type 2**. It's function #4 in the pipeline: `build_repo_scd2`.

---

## The Shop Signboard Analogy 🏪

Picture a café on your street. Over the years it's been renamed twice and repainted once.

There are three ways the city records could track it:

| Approach | What's on file | "What was it called in 2019?" |
|---|---|---|
| **Repaint the sign** | Only today's name | ❌ No idea |
| **Photo album** | One photo per look, each labelled "from … to …" | ✅ Find the photo whose dates cover 2019 |
| **"Formerly known as"** | Today's name, plus the one before | 🤷 Only if 2019 was exactly one name ago |

Those three are, in order, **SCD Type 1**, **Type 2** and **Type 3**.

The photo album is the only one that can answer *any* question about the past. Each photo is a **version**, and the label is its **validity interval**.

> **Key insight:** SCD Type 2 doesn't store *changes*. It stores *versions*, each with a start and an end. A change is just the moment one version ends and the next begins.

---

## Facts vs Dimensions, One More Time 📚

Quick refresher from Post 01. RepoSphere has two inputs, and they're different kinds of data:

| | `events.jsonl` | `repo_changes.jsonl` |
|---|---|---|
| Kind | **Fact** | **Dimension** |
| Grammar | A verb: "Dave pushed to 101 at 09:50" | A noun: "Repo 101 is called X and is private" |
| Changes? | Never. It happened | Slowly. Renames, visibility flips, branch switches |
| Each row is… | One action | A **full snapshot** of the repo after a change |

That last row matters. Every change row carries **all three** attributes (`repo_name`, `visibility`, `default_branch`), not just the one that changed. So each change row already *is* a complete version. We just need to work out when each version ends.

Here are the five snapshots, exactly as they sit in the file:

```python
changes = read_repo_changes(spark, "data/repo_changes.jsonl")   # from Post 03
changes.show(truncate=False)
```

```
+---------+-------+--------------------+-------------+----------+--------------+
|change_id|repo_id|changed_at          |repo_name    |visibility|default_branch|
+---------+-------+--------------------+-------------+----------+--------------+
|c1       |101    |2024-03-01T09:00:00Z|alpha-api    |public    |main          |
|c3       |101    |2024-03-01T11:00:00Z|alpha-service|public    |main          |
|c4       |202    |2024-03-01T10:30:00Z|beta-web     |public    |master        |
|c2       |101    |2024-03-01T10:00:00Z|alpha-api    |private   |main          |
|c5       |202    |2024-03-01T12:00:00Z|beta-web     |public    |main          |
+---------+-------+--------------------+-------------+----------+--------------+
```

Three changes for repo 101, two for repo 202. And c2 is sitting in the wrong place. Hold that thought.

---

## SCD Types 1, 2 and 3 on Real Data ⚖️

Let's build all three from the same five rows, so you can see exactly what each one throws away.

### Type 1: overwrite

Keep only the **latest** snapshot per repo. That's "first row per group, newest first", which is a `row_number` job from Post 05:

```python
from pyspark.sql import Window
from pyspark.sql import functions as F

w_latest = (Window.partitionBy("repo_id")
            .orderBy(F.to_timestamp("changed_at").desc(), F.col("change_id").desc()))

scd1 = (changes
    .withColumn("rn", F.row_number().over(w_latest))
    .filter(F.col("rn") == 1)
    .select("repo_id", "repo_name", "visibility", "default_branch"))

scd1.orderBy("repo_id").show(truncate=False)
```

```
+-------+-------------+----------+--------------+
|repo_id|repo_name    |visibility|default_branch|
+-------+-------------+----------+--------------+
|101    |alpha-service|public    |main          |
|202    |beta-web     |public    |main          |
+-------+-------------+----------+--------------+
```

Two rows, perfectly accurate **for right now**. Ask it about 10:40, and it says repo 101 was `public`. Wrong, and with no hint that it's wrong.

### Type 3: one column of memory

Keep the latest snapshot, plus a `prev_visibility` column filled by `lag`:

```python
w_time = Window.partitionBy("repo_id").orderBy(F.to_timestamp("changed_at"), "change_id")

scd3 = (changes
    .withColumn("prev_visibility", F.lag("visibility").over(w_time))
    .withColumn("rn", F.row_number().over(w_latest))
    .filter(F.col("rn") == 1)
    .select("repo_id", "repo_name", "visibility", "prev_visibility", "default_branch"))

scd3.orderBy("repo_id").show(truncate=False)
```

```
+-------+-------------+----------+---------------+--------------+
|repo_id|repo_name    |visibility|prev_visibility|default_branch|
+-------+-------------+----------+---------------+--------------+
|101    |alpha-service|public    |private        |main          |
|202    |beta-web     |public    |public         |main          |
+-------+-------------+----------+---------------+--------------+
```

Now you know repo 101 *was* private at some point. But **when**? From what time to what time? Was e03 inside that window? The table can't say.

And look at repo 202: `prev_visibility = public`. Its last change (c5) only switched the default branch. SCD3 tracks **one attribute, one step back**, and nothing else.

### Type 2: every version

This is the `lead` trick from Post 05. Every snapshot becomes a row, and each row's end is the next row's start:

```
+-------+-------------+----------+--------------+-------------------+-------------------+----------+
|repo_id|repo_name    |visibility|default_branch|valid_from         |valid_to           |is_current|
+-------+-------------+----------+--------------+-------------------+-------------------+----------+
|101    |alpha-api    |public    |main          |2024-03-01 09:00:00|2024-03-01 10:00:00|false     |
|101    |alpha-api    |private   |main          |2024-03-01 10:00:00|2024-03-01 11:00:00|false     |
|101    |alpha-service|public    |main          |2024-03-01 11:00:00|null               |true      |
|202    |beta-web     |public    |master        |2024-03-01 10:30:00|2024-03-01 12:00:00|false     |
|202    |beta-web     |public    |main          |2024-03-01 12:00:00|null               |true      |
+-------+-------------+----------+--------------+-------------------+-------------------+----------+
```

Five rows. Ask about 10:40 and the answer is right there: the `private` row, `[10:00, 11:00)`.

![Repo 101 under SCD Types 1, 2 and 3, and what e03 at 10:40 sees under each](content/data-engineering/images/scd_types_1_2_3.svg)

| Type | On change | Rows for repo 101 | "What was it at 10:40?" | Use it for |
|---|---|---|---|---|
| **SCD 1** | Overwrite | 1 | ❌ Today's value, silently | Typos, fields nobody audits |
| **SCD 2** | Add row, close old row | 3 | ✅ Exact version, with times | Anything history must be right for |
| **SCD 3** | Shift to `prev_*` column | 1 | 🤷 One step back, no times | "Old region vs new region" reports |

> **Why not always SCD 2?** It costs rows and complexity. A repo renamed 500 times has 500 versions, and every lookup needs a time range. For a field where only today matters, like fixing a typo in a description, SCD 1 is the honest choice. RepoSphere needs visibility *at event time*, so it needs SCD 2.

---

## The Three Columns, Exactly 🎯

SCD 2 adds three columns. Each one has a precise meaning, and the precision is what makes Post 08's join work.

| Column | Meaning | Where it comes from |
|---|---|---|
| `valid_from` | The instant this version **became** true | The snapshot's own `changed_at` |
| `valid_to` | The instant the **next** version replaced it | `lead(valid_from)` over the repo's timeline |
| `is_current` | This is the version in force **now** | `valid_to IS NULL` |

Two of those deserve a closer look.

### `valid_to` is null, on purpose

The last version of each repo has no successor, so `lead` returns null. That null **means something**: "nothing has replaced me yet."

Some warehouses use a sentinel date like `9999-12-31` instead. Here's the trade-off:

| Open end as… | Pros | Cons |
|---|---|---|
| `null` | Honest: "unknown future". It's what `lead` gives you for free | Every range check needs an `IS NULL` branch |
| `9999-12-31` | Range checks stay simple: `ts < valid_to` always works | A fake date can leak into reports and date math |

RepoSphere's spec uses **null**. So `is_current` is just a readable name for `valid_to IS NULL`. It's never computed any other way.

> **Trap:** Don't compute `is_current` by comparing `valid_from` to "now" or by taking the max per repo separately. Two definitions can disagree. Derive it from `valid_to` and they can't.

### The interval is half-open

Each version covers **`[valid_from, valid_to)`**. The square bracket means the start is **included**. The round bracket means the end is **excluded**.

So the instant 10:00 belongs to c2, not c1. c1 covers 09:00 up to *but not including* 10:00.

Why be this fussy? Because one of our events lands **exactly** on a boundary. `e09` happened at **10:00:00**, the very second repo 101 went private.

Here's a lookup with a closed interval, where `between` includes **both** ends:

```python
flat = flatten_events(read_events(spark, "data/events.jsonl"))   # from Post 04
e, v = flat.alias("e"), repo_scd2.alias("v")

closed = e.join(v,
    (F.col("e.repo_id") == F.col("v.repo_id")) &
    F.col("e.created_ts").between(
        F.col("v.valid_from"),
        F.coalesce(F.col("v.valid_to"), F.lit("9999-12-31").cast("timestamp"))))

(closed.filter(F.col("e.event_id") == "e09")
 .select("e.event_id", "e.created_ts", "v.visibility", "v.valid_from", "v.valid_to")
 .orderBy("v.valid_from")
 .show(truncate=False))
```

```
+--------+-------------------+----------+-------------------+-------------------+
|event_id|created_ts         |visibility|valid_from         |valid_to           |
+--------+-------------------+----------+-------------------+-------------------+
|e09     |2024-03-01 10:00:00|public    |2024-03-01 09:00:00|2024-03-01 10:00:00|
|e09     |2024-03-01 10:00:00|private   |2024-03-01 10:00:00|2024-03-01 11:00:00|
+--------+-------------------+----------+-------------------+-------------------+
```

**One event, two rows.** Was it public or private? Both, apparently. Every count downstream is now off by one.

Now the half-open version: `>=` on the start, `<` on the end, plus the null branch:

```python
half_open = e.join(v,
    (F.col("e.repo_id") == F.col("v.repo_id")) &
    (F.col("e.created_ts") >= F.col("v.valid_from")) &
    (F.col("v.valid_to").isNull() | (F.col("e.created_ts") < F.col("v.valid_to"))))

(half_open.filter(F.col("e.event_id") == "e09")
 .select("e.event_id", "e.created_ts", "v.visibility", "v.valid_from", "v.valid_to")
 .show(truncate=False))
```

```
+--------+-------------------+----------+-------------------+-------------------+
|event_id|created_ts         |visibility|valid_from         |valid_to           |
+--------+-------------------+----------+-------------------+-------------------+
|e09     |2024-03-01 10:00:00|private   |2024-03-01 10:00:00|2024-03-01 11:00:00|
+--------+-------------------+----------+-------------------+-------------------+
```

Exactly one match. The versions sit end to end with **no gaps and no overlaps**, so every instant belongs to exactly one version (or none).

![Repo versions as half-open intervals, with each event placed on the timeline](content/data-engineering/images/repo_scd2_timeline.svg)

> **Key insight:** "`valid_to` of one row equals `valid_from` of the next" only works if exactly one side owns the boundary. Half-open intervals make the **later** version own it. That's also how a real clock works: at 10:00:00 the repo has *already* gone private.

(e09 has no actor, so sessionize drops it in Post 07 and it never reaches the real join. But the boundary problem is real, and in production data it happens every day.)

---

## `build_repo_scd2`, In Full 🛠️

Here's the real function. It's short because the window does the hard work:

```python
from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F


def build_repo_scd2(repo_changes: DataFrame) -> DataFrame:
    """Turn repo-change snapshots into SCD Type 2 versions.

    One row per change. Each version is valid on [valid_from, valid_to);
    valid_to is null for the version still in force.
    """
    w = Window.partitionBy("repo_id").orderBy("valid_from", "change_id")

    return (repo_changes
        .withColumn("valid_from", F.to_timestamp("changed_at"))
        .withColumn("valid_to",   F.lead("valid_from").over(w))
        .withColumn("is_current", F.col("valid_to").isNull())
        .select("repo_id", "repo_name", "visibility", "default_branch",
                "valid_from", "valid_to", "is_current"))
```

```python
repo_scd2 = build_repo_scd2(changes)
repo_scd2.orderBy("repo_id", "valid_from").show(truncate=False)
```

```
+-------+-------------+----------+--------------+-------------------+-------------------+----------+
|repo_id|repo_name    |visibility|default_branch|valid_from         |valid_to           |is_current|
+-------+-------------+----------+--------------+-------------------+-------------------+----------+
|101    |alpha-api    |public    |main          |2024-03-01 09:00:00|2024-03-01 10:00:00|false     |
|101    |alpha-api    |private   |main          |2024-03-01 10:00:00|2024-03-01 11:00:00|false     |
|101    |alpha-service|public    |main          |2024-03-01 11:00:00|null               |true      |
|202    |beta-web     |public    |master        |2024-03-01 10:30:00|2024-03-01 12:00:00|false     |
|202    |beta-web     |public    |main          |2024-03-01 12:00:00|null               |true      |
+-------+-------------+----------+--------------+-------------------+-------------------+----------+
```

This matches the course lab's expected `build_repo_scd2` output, row for row.

Every line has a reason:

| Line | Why it's there |
|---|---|
| `partitionBy("repo_id")` | A version can only be replaced by a version **of the same repo** |
| `orderBy("valid_from", ...)` | Time order, not file order. This is what fixes c2 |
| `..., "change_id")` | Tie-breaker. Two changes at the same second still sort the same way every run |
| `F.to_timestamp("changed_at")` | Compare instants, not strings. Post 03 left `changed_at` as text on purpose |
| `F.lead("valid_from")` | "When does the next version of *my* repo start?" |
| `F.col("valid_to").isNull()` | `is_current` is defined by `valid_to`, so the two can never disagree |
| `.select(...)` | Exactly the seven spec columns. `changed_at` and `change_id` stay behind |

> **Why sort by `valid_from` and not `changed_at`?** They hold the same instant, but `valid_from` is a real timestamp and `changed_at` is a string. ISO strings happen to sort correctly *in this file*. A single `+05:30` offset would break that. Order by the parsed column.

Notice the version for c5. Its name and visibility match c4's. Only `default_branch` changed, `master` → `main`. It's still a new version, because SCD 2 tracks the **whole snapshot**. An event at 11:20 on repo 202 must report `master`, and an event at 12:30 must report `main`.

---

## The Late-Arriving c2 🐢

c2 happened at 10:00 but was written to the file **after** c3 (11:00). It's late-arriving data, and it's normal: logs get retried, queues reorder, a backfill lands a day late.

Our function handled it with zero special code. To see why that matters, here's what you get if you trust **file order** instead of time. `monotonically_increasing_id` stands in for "line number in the file":

```python
w_file = Window.partitionBy("repo_id").orderBy("file_pos")

bad = (changes
    .withColumn("file_pos",   F.monotonically_increasing_id())   # position in the file
    .withColumn("valid_from", F.to_timestamp("changed_at"))
    .withColumn("valid_to",   F.lead("valid_from").over(w_file))
    .withColumn("is_current", F.col("valid_to").isNull()))

(bad.select("repo_id", "change_id", "visibility", "valid_from", "valid_to", "is_current")
 .orderBy("repo_id", "file_pos")
 .show(truncate=False))
```

```
+-------+---------+----------+-------------------+-------------------+----------+
|repo_id|change_id|visibility|valid_from         |valid_to           |is_current|
+-------+---------+----------+-------------------+-------------------+----------+
|101    |c1       |public    |2024-03-01 09:00:00|2024-03-01 11:00:00|false     |
|101    |c3       |public    |2024-03-01 11:00:00|2024-03-01 10:00:00|false     |
|101    |c2       |private   |2024-03-01 10:00:00|null               |true      |
|202    |c4       |public    |2024-03-01 10:30:00|2024-03-01 12:00:00|false     |
|202    |c5       |public    |2024-03-01 12:00:00|null               |true      |
+-------+---------+----------+-------------------+-------------------+----------+
```

Three separate disasters, and **no error**:

| Row | What went wrong | Consequence |
|---|---|---|
| c1 | Ends at 11:00 instead of 10:00 | e03 at 10:40 reports **public**. The audit question gets the wrong answer |
| c3 | Ends at 10:00, *before* it starts | A negative interval. Nothing can ever fall inside it |
| c2 | Marked current | Repo 101 is "private right now". It's public |

Repo 202 looks fine only because its changes happened to arrive in order. That's the dangerous part: a file-order bug passes every test until the one day the data arrives out of order.

> **Trap:** Never derive history from the order rows arrive in. Files, Kafka partitions and `union`s all reorder rows. The **only** trustworthy order is the event's own timestamp, plus a tie-breaker.

---

## Two Changes at the Same Instant ⏱️

Our file doesn't have this case, but production data will. Suppose a second snapshot for repo 202 lands at **exactly 12:00:00**, making it private:

```
{"change_id":"c6","repo_id":202,"changed_at":"2024-03-01T12:00:00Z","repo_name":"beta-web","visibility":"private","default_branch":"main"}
```

Run the same window over repo 202 (keeping `change_id` visible for the moment so you can tell the rows apart):

```
+-------+---------+----------+-------------------+-------------------+----------+
|repo_id|change_id|visibility|valid_from         |valid_to           |is_current|
+-------+---------+----------+-------------------+-------------------+----------+
|202    |c4       |public    |2024-03-01 10:30:00|2024-03-01 12:00:00|false     |
|202    |c5       |public    |2024-03-01 12:00:00|2024-03-01 12:00:00|false     |
|202    |c6       |private   |2024-03-01 12:00:00|null               |true      |
+-------+---------+----------+-------------------+-------------------+----------+
```

c5 gets `[12:00, 12:00)`: a **zero-length interval**. Under half-open rules, no instant can satisfy `12:00 <= t < 12:00`, so no event will ever match it. c6, the later one in the ordering, becomes the effective version.

That's fine, **as long as it's the same every run**. Without `change_id` in the `orderBy`, Spark is free to put c5 and c6 in either order. Some days c5 is current and the repo is public, some days c6 wins and it's private. Same input, different answer.

| Ordering | c5 / c6 order | Current visibility | Deterministic? |
|---|---|---|---|
| `orderBy("valid_from")` | Whatever Spark picks | public *or* private | ❌ |
| `orderBy("valid_from", "change_id")` | c5 then c6, always | private | ✅ |

> **Should you filter out zero-length rows?** You can, with `valid_to IS NULL OR valid_to > valid_from`. But they're harmless to a half-open join, and keeping them preserves the fact that c5 *was* recorded. The spec's lab keeps one row per change, so we do too.

---

## Before the First Version 🕳️

One more thing the table makes visible. Here's every event looked up against `repo_scd2` with the half-open condition, using a **left** join so nothing is dropped:

```
+--------+-------------------+-------+-------------+----------+
|event_id|created_ts         |repo_id|repo_name    |visibility|
+--------+-------------------+-------+-------------+----------+
|e01     |2024-03-01 09:50:00|101    |alpha-api    |public    |
|e09     |2024-03-01 10:00:00|101    |alpha-api    |private   |
|e03     |2024-03-01 10:40:00|101    |alpha-api    |private   |
|e04     |2024-03-01 11:20:00|101    |alpha-service|public    |
|e02     |2024-03-01 10:10:00|202    |null         |null      |
|e06     |2024-03-01 10:15:00|202    |null         |null      |
|e07     |2024-03-01 10:35:00|202    |beta-web     |public    |
|e05     |2024-03-01 11:20:00|202    |beta-web     |public    |
|e08     |2024-03-01 12:30:00|999    |null         |null      |
+--------+-------------------+-------+-------------+----------+
```

e03 finally gets the right answer: **private**.

Three events come back null, for two different reasons:

- **e02 and e06** hit repo 202 at 10:10 and 10:15. Its first known version starts at **10:30**. The repo surely existed, but we have no snapshot that covers those minutes. An honest SCD 2 table says "unknown", not a guess.
- **e08** hits repo 999, which has **no versions at all**.

Don't "fix" these by stretching the first version back to the beginning of time. You'd be inventing history. Post 08 builds the real point-in-time join and shows why keeping these nulls is exactly what the spec wants.

---

## Your `build_repo_scd2` Checklist ✅

- [ ] Window is `partitionBy("repo_id")`, so repos never share a timeline
- [ ] Ordered by the **parsed** timestamp, never by file position
- [ ] `change_id` as the last `orderBy` column, so same-instant ties are deterministic
- [ ] `valid_to` comes from `lead(valid_from)`, and is null for the latest version
- [ ] `is_current` is `valid_to IS NULL`, and nothing else
- [ ] Every lookup uses `[valid_from, valid_to)`: `>=` on the start, `<` on the end, plus an `IS NULL` branch
- [ ] Output is exactly the seven spec columns
- [ ] One row per input change, including zero-length versions

---

## Quick Quiz 🧠

**Q1.** An auditor asks: "Was repo 101 private when e03 happened?" Which of SCD 1, 2 or 3 can answer correctly from our data, and what would the others say?

<details>
<summary>Show answer</summary>

Only **SCD 2**. It has the version `[10:00, 11:00) private`, and 10:40 falls inside it. **SCD 1** says `public`, today's value, which is wrong. **SCD 3** says "currently public, previously private", but has no times, so it can't tell you whether 10:40 was during the private spell.

</details>

**Q2.** Repo 101 gets a new snapshot, c7, at 15:00 making it private again. Without re-running anything in your head first: which existing row changes, and how?

<details>
<summary>Show answer</summary>

Only **c3's row**. Its `valid_to` changes from `null` to `15:00`, and its `is_current` flips from `true` to `false`. A new row appears for c7: `[15:00, null)`, private, `is_current = true`. c1 and c2 are untouched. That's the whole SCD 2 contract: **add a row, close the previous one**.

</details>

**Q3.** If you join all nine events to `repo_scd2` with a **left** join using `between(valid_from, coalesce(valid_to, '9999-12-31'))`, how many rows do you get, and why?

<details>
<summary>Show answer</summary>

**10**, not 9. `between` includes both ends, and e09 at exactly 10:00:00 sits on the boundary between c1 `[09:00, 10:00]` and c2 `[10:00, 11:00]`, so it matches both. Every other event matches at most one version. The half-open condition (`>=` start, `<` end) fixes it back to 9.

</details>

**Q4.** A teammate "simplifies" the window to `Window.partitionBy("repo_id").orderBy("changed_at")`. The output looks identical on our file. What two risks have they introduced?

<details>
<summary>Show answer</summary>

1. **String ordering.** `changed_at` is text. ISO strings in UTC sort correctly, but one row written with an offset like `+05:30` sorts in the wrong place, and its version gets the wrong `valid_to`.
2. **Non-deterministic ties.** With no `change_id` tie-breaker, two changes at the same instant can come out in either order. Which one is current, and which is zero-length, can flip between runs.

</details>

**Q5.** Why does e06 (repo 202, 10:15) get null repo details, even though e07 on the same repo 20 minutes later gets `beta-web`?

<details>
<summary>Show answer</summary>

Repo 202's first known snapshot is c4 at **10:30**. e06 at 10:15 is before any version starts, so no `[valid_from, valid_to)` interval contains it. e07 at 10:35 falls inside c4's `[10:30, 12:00)`. The table doesn't invent a version for the time before the first snapshot, so e06 honestly gets nulls.

</details>

---

## What's Next? 🚀

The repo side of the pipeline is done: read, then build a clean, deterministic version history. Now back to the events. Dave's day isn't nine separate clicks. It's two bursts of work with a break in between.

👉 **[Post 07 — Sessionization: Gaps & Islands](content/data-engineering/07-sessionization-gaps-and-islands.md)** — `sessionize_actor_events` and the four-step recipe: order, look back with `lag`, flag the gaps, and number the sessions with a running sum. Plus the gap of exactly 1800 seconds, and what happens to e09.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
