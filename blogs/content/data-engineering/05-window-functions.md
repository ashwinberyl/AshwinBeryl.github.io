---
title: "Window Functions — Letting Every Row See Its Neighbours"
date: 2026-10-13
tags: [data-engineering, pyspark, window-functions, lag-lead, ranking, first-principles]
description: How Spark window functions let each RepoSphere event look at the rows around it — partitionBy and orderBy, tie-breakers, lag and lead, row_number vs rank vs dense_rank, running totals, and the rowsBetween vs default rangeBetween frame trap that quietly double-counts ties.
---

# Every Row Gets Neighbours 🪟

In [Post 04](content/data-engineering/04-flattening-and-timestamps.md), we wrote `flatten_events`. Every RepoSphere event is now one flat row with six typed columns: `event_id`, `event_type`, `created_ts`, `event_date`, `repo_id`, `actor_login`.

Clean. Typed. And completely **alone**.

Look at what the next three functions need to know:

| # | Function | The question each row must answer |
|---|---|---|
| 4 | `build_repo_scd2` | "When does the **next** version of my repo start?" |
| 5 | `sessionize_actor_events` | "How long since this actor's **previous** event?" |
| 7 | `compute_session_summary` | "Am I the **first** event of my session?" |

None of those can be answered by a row on its own. Each one needs to look at **other rows in the same group**.

That's exactly what a **window function** does. It's one idea, and three of the seven pipeline functions are built on it. Get this post right and Posts 06, 07 and 09 become easy.

---

## The Queue-at-the-Counter Analogy ☕

Picture the coffee counter on a busy morning. There are two queues: one for **priya's** team, one for **rahul's**.

If the manager asks "how many people are in each queue?", you walk over, count, and write down two numbers. The people don't matter anymore. That's **`groupBy`**: each group collapses to one answer.

Now imagine instead that everybody in the queue turns to the person in front and asks, "How long have you been waiting?" Nobody leaves. Everybody just learns something about their **neighbour**. That's a **window**.

Three things define what each person can see:

- **Which queue they're in** → `partitionBy`
- **The order of the queue** → `orderBy`
- **How far they look** (just the person in front? everyone ahead?) → the **frame**

Keep that picture. Every window you'll ever write is those three choices.

![groupBy collapses each group to one row, while a window keeps all eight rows and gives each one its group's answer](content/data-engineering/images/window_vs_groupby.svg)

| | `groupBy(...).agg(...)` | `F.something().over(window)` |
|---|---|---|
| Rows out | One per group | **Same as rows in** |
| Other columns | Lost unless aggregated | **Kept** |
| Can see "previous" / "next" | No | **Yes** |
| Typical use | Daily totals, session summaries | Gaps, versions, rankings, running totals |

> **Key insight:** A window never changes how many rows you have. It only **adds columns** computed from each row's neighbours.

---

## Defining a Window 🧱

Here's the window every actor-level step in RepoSphere uses:

```python
from pyspark.sql import Window
from pyspark.sql import functions as F

flat = flatten_events(read_events(spark, "data/events.jsonl"))

w = (Window
     .partitionBy("actor_login")              # 1. which rows belong together
     .orderBy("created_ts", "event_id"))      # 2. their order (event_id = tie-breaker)
```

A `Window` object on its own does nothing. It's a **specification**. You attach it to a function with `.over(w)`:

```python
(flat
 .select(
     "actor_login", "event_id", "created_ts",
     F.row_number().over(w).alias("rn"),             # position in the group: 1, 2, 3...
     F.lag("created_ts").over(w).alias("prev_ts"),   # value from the previous row
     F.lead("created_ts").over(w).alias("next_ts"),  # value from the next row
 )
 .orderBy("actor_login", "rn")
 .show(truncate=False))
```

```
+-----------+--------+-------------------+--+-------------------+-------------------+
|actor_login|event_id|created_ts         |rn|prev_ts            |next_ts            |
+-----------+--------+-------------------+--+-------------------+-------------------+
|null       |e09     |2024-03-01 10:00:00|1 |null               |null               |
|priya      |e01     |2024-03-01 09:50:00|1 |null               |2024-03-01 10:10:00|
|priya      |e02     |2024-03-01 10:10:00|2 |2024-03-01 09:50:00|2024-03-01 10:40:00|
|priya      |e03     |2024-03-01 10:40:00|3 |2024-03-01 10:10:00|2024-03-01 11:20:00|
|priya      |e04     |2024-03-01 11:20:00|4 |2024-03-01 10:40:00|2024-03-01 11:20:00|
|priya      |e05     |2024-03-01 11:20:00|5 |2024-03-01 11:20:00|null               |
|rahul      |e06     |2024-03-01 10:15:00|1 |null               |2024-03-01 10:35:00|
|rahul      |e07     |2024-03-01 10:35:00|2 |2024-03-01 10:15:00|2024-03-01 12:30:00|
|rahul      |e08     |2024-03-01 12:30:00|3 |2024-03-01 10:35:00|null               |
+-----------+--------+-------------------+--+-------------------+-------------------+
```

Read it slowly. There's a lot in nine rows:

- **priya and rahul never mix.** rahul's e06 at 10:15 sits between priya's e02 and e03 in time, but it's in a different partition, so it's invisible to her.
- **e05 sits in the file before e04**, yet e04 gets `rn = 4`. The window sorts. File order doesn't matter.
- **The first row in each partition has `prev_ts = null`.** The last has `next_ts = null`.
- **e09 has no login**, so `actor_login` is `null`. All the null keys land in **one partition of their own**. Here that's a lonely partition of one.

> **Key insight:** Those `null`s from `lag` and `lead` aren't errors. They **carry meaning**. A null `prev_ts` says "a sequence starts here". A null `next_ts` says "nothing replaced me yet". Post 06 and Post 07 are built on exactly those two facts.

> **Trap:** e09's null partition is why `sessionize_actor_events` filters out null actors first (Post 07). Otherwise every login-less event in the day would be lumped into one fake "actor" called `null`.

---

## Tie-Breakers: Making the Order Unique 🎲

Look at priya's last two events again. e04 and e05 both happened at **11:20:00**, to the second.

Now drop the tie-breaker:

```python
w_loose = Window.partitionBy("actor_login").orderBy("created_ts")
```

Which one gets `rn = 4`? **Spark doesn't promise.** Both rows are "equal" as far as the order is concerned, so the answer depends on which partition of the data was read first, how the shuffle went, how many cores you had. It can be e04 today and e05 tomorrow.

That sounds harmless until you remember what row numbers are *for*. In Post 09 we pick each session's **first event** to report its primary repo. For priya's session 2, that's either e04 (`alpha-service`) or e05 (`beta-web`). Same data, two different reports.

| Ordering | priya's e04 / e05 | Same answer every run? |
|---|---|---|
| `orderBy("created_ts")` | 4 / 5 *or* 5 / 4 | ❌ No |
| `orderBy("created_ts", "event_id")` | **4 / 5** | ✅ Yes |

> **Rule:** If a spec says "ties broken by smallest X", X goes in as the **last** `orderBy` column. If it says nothing, add a unique column anyway. A window over a non-unique order is a coin flip.

> **Why does `event_id` sort correctly here?** Because every id is `e` plus two digits, so string order matches number order. Remember Post 03: with ids like `e9` and `e10`, string sorting puts `e10` first. Check the data before you trust a tie-breaker.

---

## `lag` and `lead`: Looking Back, Looking Ahead ⏪⏩

`lag(col)` returns `col` from the **previous** row in the window. `lead(col)` returns it from the **next** row. Both take an optional offset and default: `F.lag("created_ts", 2)` looks two rows back, and `F.lag("x", 1, 0)` returns `0` instead of `null` on the first row.

### Looking back: gaps between events

Subtract the previous timestamp from the current one, and you have the pause between events. Timestamps cast to `double` become seconds since the epoch, fractions included:

```python
prev_ts = F.lag("created_ts").over(w)
gap_s   = F.col("created_ts").cast("double") - prev_ts.cast("double")

(flat
 .filter(F.col("actor_login").isNotNull())
 .select("actor_login", "event_id", "created_ts", gap_s.alias("gap_s"))
 .orderBy("actor_login", "created_ts", "event_id")
 .show(truncate=False))
```

```
+-----------+--------+-------------------+------+
|actor_login|event_id|created_ts         |gap_s |
+-----------+--------+-------------------+------+
|priya      |e01     |2024-03-01 09:50:00|null  |
|priya      |e02     |2024-03-01 10:10:00|1200.0|
|priya      |e03     |2024-03-01 10:40:00|1800.0|
|priya      |e04     |2024-03-01 11:20:00|2400.0|
|priya      |e05     |2024-03-01 11:20:00|0.0   |
|rahul      |e06     |2024-03-01 10:15:00|null  |
|rahul      |e07     |2024-03-01 10:35:00|1200.0|
|rahul      |e08     |2024-03-01 12:30:00|6900.0|
+-----------+--------+-------------------+------+
```

This one column is most of sessionization. RepoSphere splits a session when the gap is **strictly greater than 30 minutes (1800 s)**. Spot the two splits: priya's e04 (2400 s) and rahul's e08 (6900 s).

And spot the trap waiting for Post 07: priya's e03 has a gap of **exactly 1800.0**. Is that a new session? With `> 1800`, no. With `>= 1800`, yes. One character changes priya's whole day.

> **Trap:** `gap_s` is `null` on the first row, and `null > 1800` is `null`, not `true`. If your "new session" flag only checks the gap, every actor's first event belongs to **no** session. The flag needs an explicit `prev_ts.isNull()` branch. That's step 3 of the recipe in Post 07.

### Looking ahead: when does a version end?

`lead` is the mirror image, and it builds an entire SCD Type 2 table on its own. Here are the raw repo changes, in file order:

```python
changes = read_repo_changes(spark, "data/repo_changes.jsonl")
changes.select("change_id", "repo_id", "changed_at", "repo_name", "visibility").show(truncate=False)
```

```
+---------+-------+--------------------+-------------+----------+
|change_id|repo_id|changed_at          |repo_name    |visibility|
+---------+-------+--------------------+-------------+----------+
|c1       |101    |2024-03-01T09:00:00Z|alpha-api    |public    |
|c3       |101    |2024-03-01T11:00:00Z|alpha-service|public    |
|c4       |202    |2024-03-01T10:30:00Z|beta-web     |public    |
|c2       |101    |2024-03-01T10:00:00Z|alpha-api    |private   |
|c5       |202    |2024-03-01T12:00:00Z|beta-web     |public    |
+---------+-------+--------------------+-------------+----------+
```

c2 arrived **late**: it's written after c3, but it happened before it. Each version of a repo ends when the next version *of the same repo* begins. "The next row for the same repo, in time order" is literally `lead` over a window:

```python
w_repo = Window.partitionBy("repo_id").orderBy("valid_from", "change_id")

versions = (changes
    .withColumn("valid_from", F.to_timestamp("changed_at"))
    .withColumn("valid_to",   F.lead("valid_from").over(w_repo))   # next version's start
    .withColumn("is_current", F.col("valid_to").isNull()))         # nothing replaced me yet

(versions
 .select("repo_id", "change_id", "repo_name", "visibility", "valid_from", "valid_to", "is_current")
 .orderBy("repo_id", "valid_from")
 .show(truncate=False))
```

```
+-------+---------+-------------+----------+-------------------+-------------------+----------+
|repo_id|change_id|repo_name    |visibility|valid_from         |valid_to           |is_current|
+-------+---------+-------------+----------+-------------------+-------------------+----------+
|101    |c1       |alpha-api    |public    |2024-03-01 09:00:00|2024-03-01 10:00:00|false     |
|101    |c2       |alpha-api    |private   |2024-03-01 10:00:00|2024-03-01 11:00:00|false     |
|101    |c3       |alpha-service|public    |2024-03-01 11:00:00|null               |true      |
|202    |c4       |beta-web     |public    |2024-03-01 10:30:00|2024-03-01 12:00:00|false     |
|202    |c5       |beta-web     |public    |2024-03-01 12:00:00|null               |true      |
+-------+---------+-------------+----------+-------------------+-------------------+----------+
```

The late c2 slotted into 10:00 with **zero special code**. The window sorted it into place, and `lead` did the rest. These rows match the course lab's expected `build_repo_scd2` output exactly. Post 06 turns this into the real function and explains every column.

> **Why `partitionBy("repo_id")`?** Without it, all repos share one timeline. Repo 202's c4 at 10:30 would "end" repo 101's c2 at 10:30 instead of 11:00. A version can only be replaced by a version **of the same thing**.

---

## Ranking: `row_number`, `rank`, `dense_rank` 🏅

All three number the rows of a window. They only disagree on **ties**.

Let's rank all nine events by time, across everybody. A window with no `partitionBy` treats the whole table as one group:

```python
by_time    = Window.orderBy("created_ts")
by_time_tb = Window.orderBy("created_ts", "event_id")

(flat
 .select(
     "event_id", "actor_login", "created_ts",
     F.row_number().over(by_time_tb).alias("row_number"),
     F.rank().over(by_time).alias("rank"),
     F.dense_rank().over(by_time).alias("dense_rank"),
 )
 .orderBy("created_ts", "event_id")
 .show(truncate=False))
```

```
+--------+-----------+-------------------+----------+----+----------+
|event_id|actor_login|created_ts         |row_number|rank|dense_rank|
+--------+-----------+-------------------+----------+----+----------+
|e01     |priya      |2024-03-01 09:50:00|1         |1   |1         |
|e09     |null       |2024-03-01 10:00:00|2         |2   |2         |
|e02     |priya      |2024-03-01 10:10:00|3         |3   |3         |
|e06     |rahul      |2024-03-01 10:15:00|4         |4   |4         |
|e07     |rahul      |2024-03-01 10:35:00|5         |5   |5         |
|e03     |priya      |2024-03-01 10:40:00|6         |6   |6         |
|e04     |priya      |2024-03-01 11:20:00|7         |7   |7         |
|e05     |priya      |2024-03-01 11:20:00|8         |7   |7         |
|e08     |rahul      |2024-03-01 12:30:00|9         |9   |8         |
+--------+-----------+-------------------+----------+----+----------+
```

Everything agrees until 11:20. Then:

| Function | e04 / e05 (tied) | e08 (next) | Rule |
|---|---|---|---|
| `row_number()` | 7 / 8 | 9 | Always unique. Ties split by the next `orderBy` column, or arbitrarily if there isn't one |
| `rank()` | 7 / 7 | **9** | Ties share a number, then it **skips** (like Olympic medals) |
| `dense_rank()` | 7 / 7 | **8** | Ties share a number, **no gap** |

> **Trap:** A window with no `partitionBy` sends **every row to a single task**. Spark warns you: `No Partition Defined for Window operation! Moving all data to a single partition`. On nine rows, fine. On a billion events, that's one core doing all the work while the rest of the cluster watches. Use it for small lookups, never for the main pipeline.

### "First row per group": `row_number`, not `rank`

The most common use of ranking in data engineering isn't leaderboards. It's **"give me one row per group"**: the latest version, the first event, the newest record.

Say you want each actor's **latest** event. Order descending and keep rank 1:

```python
latest = Window.partitionBy("actor_login").orderBy(F.col("created_ts").desc())

(flat
 .filter(F.col("actor_login").isNotNull())
 .withColumn("rk", F.rank().over(latest))
 .filter(F.col("rk") == 1)
 .select("actor_login", "event_id", "created_ts", "repo_id")
 .orderBy("actor_login", "event_id")
 .show(truncate=False))
```

```
+-----------+--------+-------------------+-------+
|actor_login|event_id|created_ts         |repo_id|
+-----------+--------+-------------------+-------+
|priya      |e04     |2024-03-01 11:20:00|101    |
|priya      |e05     |2024-03-01 11:20:00|202    |
|rahul      |e08     |2024-03-01 12:30:00|999    |
+-----------+--------+-------------------+-------+
```

You asked for one row per actor and got **three rows for two actors**. `rank` gave both of priya's 11:20 events a `1`. Any join downstream now duplicates priya.

Switch to `row_number` with a tie-breaker:

```python
latest_tb = (Window.partitionBy("actor_login")
             .orderBy(F.col("created_ts").desc(), F.col("event_id")))   # newest first, then smallest id

(flat
 .filter(F.col("actor_login").isNotNull())
 .withColumn("rn", F.row_number().over(latest_tb))
 .filter(F.col("rn") == 1)
 .select("actor_login", "event_id", "created_ts", "repo_id")
 .orderBy("actor_login")
 .show(truncate=False))
```

```
+-----------+--------+-------------------+-------+
|actor_login|event_id|created_ts         |repo_id|
+-----------+--------+-------------------+-------+
|priya      |e04     |2024-03-01 11:20:00|101    |
|rahul      |e08     |2024-03-01 12:30:00|999    |
+-----------+--------+-------------------+-------+
```

Exactly one row per actor, and the same one every run.

> **Key insight:** "One row per group" = `row_number()` + a **unique** order + `filter(rn == 1)`. `rank()` answers a different question: "which rows are tied for first?" Post 09 uses this exact pattern to find each session's first event.

---

## Running Totals and the Frame 🧮

Ranking functions and `lag`/`lead` only need a partition and an order. **Aggregates** like `sum`, `count`, `min` and `max` also work over a window, and for them a third setting matters: the **frame**, meaning which rows around the current one go into the calculation.

Let's count events per actor three ways:

```python
by_time = Window.partitionBy("actor_login").orderBy("created_ts")         # default frame

running = (Window.partitionBy("actor_login")
           .orderBy("created_ts", "event_id")
           .rowsBetween(Window.unboundedPreceding, Window.currentRow))    # explicit frame

whole   = Window.partitionBy("actor_login")                               # no order at all

(flat
 .filter(F.col("actor_login").isNotNull())
 .select(
     "actor_login", "event_id", "created_ts",
     F.count(F.lit(1)).over(by_time).alias("n_range"),
     F.count(F.lit(1)).over(running).alias("n_rows"),
     F.count(F.lit(1)).over(whole).alias("n_total"),
 )
 .orderBy("actor_login", "created_ts", "event_id")
 .show(truncate=False))
```

```
+-----------+--------+-------------------+-------+------+-------+
|actor_login|event_id|created_ts         |n_range|n_rows|n_total|
+-----------+--------+-------------------+-------+------+-------+
|priya      |e01     |2024-03-01 09:50:00|1      |1     |5      |
|priya      |e02     |2024-03-01 10:10:00|2      |2     |5      |
|priya      |e03     |2024-03-01 10:40:00|3      |3     |5      |
|priya      |e04     |2024-03-01 11:20:00|5      |4     |5      |
|priya      |e05     |2024-03-01 11:20:00|5      |5     |5      |
|rahul      |e06     |2024-03-01 10:15:00|1      |1     |3      |
|rahul      |e07     |2024-03-01 10:35:00|2      |2     |3      |
|rahul      |e08     |2024-03-01 12:30:00|3      |3     |3      |
+-----------+--------+-------------------+-------+------+-------+
```

Look at priya's e04. `n_rows` says **4**. `n_range` says **5**. Same data, same partition, same order column. What happened?

![For e04, the rows frame covers e01 to e04 and counts 4; the default range frame includes every row with created_ts up to 11:20, so e05 is included and the count is 5](content/data-engineering/images/window_frames_rows_vs_range.svg)

When you give a window an `orderBy` and **no frame**, Spark silently uses:

```python
.rangeBetween(Window.unboundedPreceding, Window.currentRow)
```

**Range** means "every row whose *order value* is ≤ mine". e05 has the same `created_ts` as e04, so it counts as "up to the current row", even though it comes after e04. Tied rows are treated as **one step**.

**Rows** means "every *physical row* up to and including me". It counts one row at a time.

| Window spec | Default frame | e04's count |
|---|---|---|
| `partitionBy` only, no `orderBy` | Whole partition | 5 (total) |
| `partitionBy` + `orderBy`, no frame | `rangeBetween(unboundedPreceding, currentRow)` | **5** (tie included) |
| `partitionBy` + `orderBy` + `rowsBetween(unboundedPreceding, currentRow)` | What you wrote | **4** |

> **Trap:** This bug doesn't crash and doesn't warn. On data without ties, both frames give identical answers, so every test you write by hand passes. Then the first day two events share a second, a running counter jumps by two. For running counters, **always write `rowsBetween` explicitly**, and make the order unique with a tie-breaker.

That matters directly in Post 07. Session numbers are a **running sum** of "new session" flags. With the default range frame, any two events at the same instant would get the sum that includes both of their flags. With `rowsBetween` and `event_id` in the order, every row gets its own exact running total.

> **Why does `lag` not care about frames?** `lag`, `lead`, `row_number`, `rank` and `dense_rank` are defined by **position** in the ordered partition. They come with a fixed frame of their own, and Spark raises an error if you give them a different one. Choosing a frame only matters for aggregates.

### One thing windows can't do

```python
F.countDistinct("repo_id").over(Window.partitionBy("actor_login"))
```

```
AnalysisException: Distinct window functions are not supported
```

If you need "distinct repos per actor" on every row, use `F.size(F.collect_set("repo_id")).over(...)`. For a one-row-per-session summary, which is what `compute_session_summary` actually wants, `groupBy(...).agg(F.countDistinct(...))` is simpler. That's Post 09.

---

## Determinism: The Rule Behind All of It 🎯

Every trap in this post has the same root: **an ordering that isn't unique**.

| Symptom | Cause | Fix |
|---|---|---|
| `row_number` flips between runs | Ties in `orderBy` | Add a unique tie-breaker as the last column |
| "One row per group" returns two | `rank()` instead of `row_number()` | `row_number()` + unique order |
| Running count jumps by 2 | Default `rangeBetween` frame on tied values | Explicit `rowsBetween` |
| A version ends at another repo's change | Missing `partitionBy` | Partition by the entity's key |
| One task does all the work | No `partitionBy` at all | Partition, unless the data is tiny |

> **Key insight:** A pipeline that gives different answers on different runs is broken even if each answer looks plausible. Tests compare exact tables. A window with a unique order and an explicit frame gives the same table every time.

---

## Where Each Tool Lands in the Pipeline 🗺️

| Pipeline function | Window | Function used | Post |
|---|---|---|---|
| `build_repo_scd2` | `partitionBy("repo_id").orderBy("valid_from", "change_id")` | `lead` → `valid_to` | 06 |
| `sessionize_actor_events` | `partitionBy("actor_login").orderBy("created_ts", "event_id")` | `lag` → gap, then running `sum` with `rowsBetween` | 07 |
| `compute_session_summary` | `partitionBy(actor, session).orderBy("created_ts", "event_id")` | `row_number() == 1` → first event | 09 |

Three functions, one idea: **partition, order, then look at your neighbours.**

---

## Quick Reference ✅

| You want | Write |
|---|---|
| Rows grouped and ordered | `Window.partitionBy("k").orderBy("ts", "id")` |
| Previous / next value | `F.lag("c").over(w)` / `F.lead("c").over(w)` |
| Position in the group | `F.row_number().over(w)` |
| Ties share a number | `F.rank()` (skips) or `F.dense_rank()` (no skip) |
| Group total on every row | `F.count(F.lit(1)).over(Window.partitionBy("k"))` |
| Running total | `F.sum("x").over(w.rowsBetween(Window.unboundedPreceding, Window.currentRow))` |
| One row per group | `row_number()` over a unique order, then `filter(rn == 1)` |
| Newest first | `.orderBy(F.col("ts").desc(), F.col("id"))` |

---

## Quick Quiz 🧠

**Q1.** You use `Window.partitionBy("actor_login").orderBy("created_ts")` and `F.row_number()`. Which of e04 and e05 gets `rn = 4`?

<details>
<summary>Show answer</summary>

**You can't know.** Both are at 11:20:00, so they're tied on every `orderBy` column, and Spark may order them differently on different runs. Add `event_id` as the last `orderBy` column, and e04 always gets 4 because `"e04" < "e05"`.

</details>

**Q2.** Over `Window.orderBy("created_ts")` across all nine events, what `rank` and `dense_rank` does e08 get?

<details>
<summary>Show answer</summary>

**rank 9, dense_rank 8.** e04 and e05 share rank 7. `rank` then skips 8 (two rows used up positions 7 and 8), so e08 is 9. `dense_rank` doesn't skip, so e08 is 8.

</details>

**Q3.** In the repo versions table, why is c3's `valid_to` null, and what does that null mean?

<details>
<summary>Show answer</summary>

c3 is the **last** row in repo 101's partition when ordered by `valid_from`, so `lead` has no next row to read. That null means **no later version has replaced it**: c3 (`alpha-service`, public) is the current version, which is exactly why `is_current` is `F.col("valid_to").isNull()`.

</details>

**Q4.** A teammate writes `F.sum(F.lit(1)).over(Window.partitionBy("actor_login").orderBy("created_ts"))` as a running event counter. What does it return for priya's e04, and how do you fix it?

<details>
<summary>Show answer</summary>

**5**, not 4. With an `orderBy` and no frame, Spark uses `rangeBetween(unboundedPreceding, currentRow)`, which includes every row with `created_ts` ≤ 11:20, so e05 is counted too. Fix: order by `("created_ts", "event_id")` **and** add `.rowsBetween(Window.unboundedPreceding, Window.currentRow)`. Then e04 gets 4 and e05 gets 5.

</details>

**Q5.** You need each actor's latest event, exactly one row per actor. Why does `F.rank().over(...)` with `filter(rk == 1)` fail on our data, and what's the correct version?

<details>
<summary>Show answer</summary>

priya's latest two events tie at 11:20, so `rank` gives **both** e04 and e05 a 1, and you get two rows for priya. Use `F.row_number()` over `partitionBy("actor_login").orderBy(F.col("created_ts").desc(), F.col("event_id"))` and keep `rn == 1`. That returns e04 for priya and e08 for rahul, every run.

</details>

---

## What's Next? 🚀

You've now seen `lead` build a version history from five messy change rows in four lines of code. But a real dimension table needs more care: what `valid_from` and `valid_to` really mean, why the interval is half-open, what SCD Types 1, 2 and 3 trade off, and what happens when two changes land at the same instant.

👉 **[Post 06 — SCD Type 2](content/data-engineering/06-scd-type-2.md)** — `build_repo_scd2` in full: SCD 1 vs 2 vs 3, `valid_from` / `valid_to` / `is_current`, half-open intervals, the late-arriving c2, and same-instant ties.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
