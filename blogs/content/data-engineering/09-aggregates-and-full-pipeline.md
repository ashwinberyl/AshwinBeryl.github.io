---
title: "Aggregates and the Full Pipeline"
date: 2026-10-21
tags: [data-engineering, pyspark, aggregates, groupby, window-functions, first-principles]
description: How compute_session_summary rolls eight enriched RepoSphere events into four session rows — groupBy on two keys, count vs countDistinct, picking the first event per session with a struct-min or row_number and an event_id tie-breaker, the int casts — then the full main(), a pre-flight checklist and every expected lab output end to end.
---

# One Row per Session 📊

In [Post 08](content/data-engineering/08-point-in-time-joins.md), the two lanes of the pipeline finally met. Every event now knows **who** did it, **which session** it belongs to, and **what the repo looked like** at that exact instant.

That's eight rows of rich, correct detail. Product doesn't want eight rows of detail.

Product wants the table we promised back in [Post 01](content/data-engineering/01-what-is-data-engineering.md): **one row per work session**. When did it start, when did it end, how many repos were touched, how many events happened, and which repo the developer started on.

That's pipeline function #7, the last one: **`compute_session_summary`**. The spec:

| Column | Rule | Type |
|---|---|---|
| `actor_login` | Group key | string |
| `session_id` | Group key | int |
| `session_start` | Earliest `created_ts` in the session | timestamp |
| `session_end` | Latest `created_ts` in the session | timestamp |
| `distinct_repos_touched` | Number of different repos | **int** |
| `events_in_session` | Number of events | **int** |
| `primary_repo_at_session_start` | `repo_name` of the **first** event: smallest `created_ts`, ties broken by smallest `event_id`. **Null** if that event has no repo name | string |

Six of those seven columns are one-liners. The seventh is the hardest single line in Part 1.

Then we'll wire all seven functions into one `main()`, run the whole thing end to end, and check every stage against the lab.

---

## The Road Trip Logbook Analogy 🚗

You and a friend keep a logbook on a road trip. Every stop gets a line: time, place, what you did. Sometimes the ink smudges and a place name is unreadable.

At the end of each driving day, you write a summary line:

- **Set off** at the earliest time in the log. **Arrived** at the latest.
- **Stops**: count the lines.
- **Cities visited**: count the **different** cities, not the lines.
- **Started from**: the place on the **first** line of the day.

That last one has a rule people break. If the first line is smudged, you write **"unknown"**. You don't skip down to the second line and write that city. The second stop isn't where you started.

| Logbook | RepoSphere |
|---|---|
| One driving day | One `(actor_login, session_id)` group |
| A line in the log | An enriched event |
| Set off / arrived | `session_start` / `session_end` |
| Stops | `events_in_session` |
| Different cities | `distinct_repos_touched` |
| Started from | `primary_repo_at_session_start` |
| A smudged first line | e06 with `repo_name = null` |
| "Unknown", not the second city | `null`, not `beta-web` |

---

## What We're Summarising 📥

The input is the output of `enrich_with_repo_state` from Post 08:

```python
enriched = enrich_with_repo_state(sessions, repo_scd2)

(enriched
 .select("event_id", "actor_login", "session_id", "created_ts", "repo_id", "repo_name")
 .orderBy("actor_login", "session_id", "created_ts", "event_id")
 .show(truncate=False))
```

```
+--------+-----------+----------+-------------------+-------+-------------+
|event_id|actor_login|session_id|created_ts         |repo_id|repo_name    |
+--------+-----------+----------+-------------------+-------+-------------+
|e01     |dave       |1         |2024-03-01 09:50:00|101    |alpha-api    |
|e02     |dave       |1         |2024-03-01 10:10:00|202    |null         |
|e03     |dave       |1         |2024-03-01 10:40:00|101    |alpha-api    |
|e04     |dave       |2         |2024-03-01 11:20:00|101    |alpha-service|
|e05     |dave       |2         |2024-03-01 11:20:00|202    |beta-web     |
|e06     |jim        |1         |2024-03-01 10:15:00|202    |null         |
|e07     |jim        |1         |2024-03-01 10:35:00|202    |beta-web     |
|e08     |jim        |2         |2024-03-01 12:30:00|999    |null         |
+--------+-----------+----------+-------------------+-------+-------------+
```

Four sessions. Three null repo names. One same-second tie (e04 and e05). Every edge case the lab planted is sitting in this one table, waiting for the summary to trip over it.

---

## Step 1: Group by **Both** Keys 🔑

A `groupBy` collapses every group to **one row**. So the first question is: what's a group?

It's tempting to say "a session", and write this:

```python
enriched.groupBy("session_id").count().orderBy("session_id").show(truncate=False)
```

```
+----------+-----+
|session_id|count|
+----------+-----+
|1         |5    |
|2         |3    |
+----------+-----+
```

Five events in "session 1"? Dave's session 1 has three. Jim's has two. They got **merged**.

Remember how Post 07 built `session_id`: a running count **per actor**. Every actor starts at 1. So `session_id = 1` isn't a session. It's "the first session of *somebody*".

> **Key insight:** `session_id` is only unique **within** an actor. The real key of a session is the pair **`(actor_login, session_id)`**. Group by the full key, or different people's sessions collapse into one row.

```python
grouped = enriched.groupBy("actor_login", "session_id")
```

Four groups. Now everything inside `.agg(...)` runs once per group.

---

## Step 2: Start and End ⏱️

These two are as easy as they look:

```python
F.min("created_ts").alias("session_start"),
F.max("created_ts").alias("session_end"),
```

`min` and `max` on a timestamp compare instants, which is exactly why Post 04 parsed `created_at` into a real `TimestampType`.

Dave's session 2 has two events at the same second, so it starts and ends at **11:20**. A session can have zero length. Jim's session 2 has one event, so the same thing happens at **12:30**. Both are correct.

---

## Step 3: Counting Is Three Different Questions 🔢

Spark has several ways to count, and each one answers a different question. Run them side by side:

```python
(enriched.groupBy("actor_login", "session_id")
 .agg(F.count(F.lit(1)).alias("rows"),
      F.count("repo_name").alias("named"),
      F.countDistinct("repo_id").alias("repos"),
      F.countDistinct("repo_name").alias("repo_names"))
 .orderBy("actor_login", "session_id")
 .show(truncate=False))
```

```
+-----------+----------+----+-----+-----+----------+
|actor_login|session_id|rows|named|repos|repo_names|
+-----------+----------+----+-----+-----+----------+
|dave       |1         |3   |2    |2    |1         |
|dave       |2         |2   |2    |2    |2         |
|jim        |1         |2   |1    |1    |1         |
|jim        |2         |1   |0    |1    |0         |
+-----------+----------+----+-----+-----+----------+
```

| Expression | Counts | Nulls | Dave s1 |
|---|---|---|---|
| `F.count(F.lit(1))` or `F.count("*")` | Rows | Counted | 3 |
| `F.count("repo_name")` | Non-null values | **Skipped** | 2 |
| `F.countDistinct("repo_id")` | Different non-null values | Skipped | 2 |
| `F.countDistinct("repo_name")` | Different non-null names | Skipped | **1** ❌ |

`events_in_session` is the first one: count **rows**. `distinct_repos_touched` is the third.

Now look at the last column. It's the bug that looks most reasonable: "distinct repos? Count distinct repo **names**." But `repo_name` came from the point-in-time join, and three events got **null** names. `countDistinct` skips nulls.

- Dave's session 1 touched repos 101 **and** 202. Counting names says **1**, because e02's name is null.
- Jim's session 2 pushed to repo 999. Counting names says **0**. Jim touched no repos?

> **Trap:** Count the **key**, not the enriched label. `repo_id` came from the event itself, so it's never null here. `repo_name` came from a join that's allowed to miss. Same reason you'd count customer IDs, not customer names: names can be missing, duplicated, or renamed. Dave's session 2 proves the last point: repo 101 was `alpha-api` an hour earlier and `alpha-service` now.

---

## Step 4: The First Row of Each Group 🥇

Here's the hard one: **`primary_repo_at_session_start`**.

Why is it hard? Because `groupBy` throws away **order**. Inside a group, rows are a bag, not a list. `min`, `max`, `count` don't care about order, so they're easy. "The value from the first row" cares about nothing **but** order.

There are two correct ways to do it, and a lot of wrong ones that look correct.

### Approach A: `row_number`, filter, join back

You already know this pattern from [Post 05](content/data-engineering/05-window-functions.md). Number the rows inside each session in time order, keep row 1:

```python
from pyspark.sql import Window

w_first = (Window
           .partitionBy("actor_login", "session_id")
           .orderBy("created_ts", "event_id"))      # event_id breaks the 11:20 tie

firsts = (enriched
    .withColumn("rn", F.row_number().over(w_first))
    .filter(F.col("rn") == 1)
    .select("actor_login", "session_id",
            F.col("repo_name").alias("primary_repo_at_session_start")))

firsts.orderBy("actor_login", "session_id").show(truncate=False)
```

```
+-----------+----------+-----------------------------+
|actor_login|session_id|primary_repo_at_session_start|
+-----------+----------+-----------------------------+
|dave       |1         |alpha-api                    |
|dave       |2         |alpha-service                |
|jim        |1         |null                         |
|jim        |2         |null                         |
+-----------+----------+-----------------------------+
```

Correct. Then you `groupBy` for the other five columns and **join** this back on `["actor_login", "session_id"]`.

It's easy to read. The cost is a second pass over the data and an extra join, for one column.

### Approach B: the minimum of a struct

Here's the trick. A **struct** is a little row packed into one value. And Spark can compare structs: **field by field, left to right**, the way a dictionary compares words letter by letter. The first field that differs decides.

So pack each event into a struct whose fields are in **sort order**, and put the value you want **last**:

```python
first_event = F.min(F.struct("created_ts", "event_id", "repo_name"))

(enriched.groupBy("actor_login", "session_id")
 .agg(first_event.alias("first_event"))
 .orderBy("actor_login", "session_id")
 .show(truncate=False))
```

```
+-----------+----------+-----------------------------------------+
|actor_login|session_id|first_event                              |
+-----------+----------+-----------------------------------------+
|dave       |1         |{2024-03-01 09:50:00, e01, alpha-api}    |
|dave       |2         |{2024-03-01 11:20:00, e04, alpha-service}|
|jim        |1         |{2024-03-01 10:15:00, e06, null}         |
|jim        |2         |{2024-03-01 12:30:00, e08, null}         |
+-----------+----------+-----------------------------------------+
```

The **minimum** struct is the earliest event. If two events tie on time, `event_id` decides. Then pull out the last field with `["repo_name"]` (or `.getField("repo_name")`):

```python
F.min(F.struct("created_ts", "event_id", "repo_name"))["repo_name"]
```

One pass. No window. No join. It lives inside the same `agg` as everything else.

![Struct-min for two sessions: Dave's session 2 has two structs tied at 11:20, so event_id decides and e04 wins with alpha-service; Jim's session 1 compares 10:15 against 10:35, so e06 wins and its null repo_name is returned instead of beta-web](content/data-engineering/images/struct_min_first_event.svg)

Two details make this work for RepoSphere:

| Session | What decides the min | Result |
|---|---|---|
| Dave s2 | `created_ts` ties at 11:20, so `event_id`: `"e04" < "e05"` | `alpha-service` ✅ |
| Jim s1 | `created_ts`: 10:15 < 10:35 | `null` ✅ |

Why does Jim's null survive? `min` skips **null values**, and a null value here would be a null **struct**. e06's struct isn't null. It's a perfectly good struct that happens to **contain** a null. So `min` considers it, picks it, and hands back its null field.

That's the logbook rule. Smudged first line → "unknown".

> **Why `event_id` as the tie-breaker?** Same reason as Post 07: without it, two events at the same second have no defined order, and Spark is free to pick either one on each run. The spec says "smallest `event_id`", so `event_id` goes **second** in the struct, after time and before the payload.

### The lookalikes 🎭

Every one of these is shorter than struct-min. None of them meets the spec:

| Expression | Dave s1 | Dave s2 | Jim s1 | Jim s2 | Problem |
|---|---|---|---|---|---|
| `F.min(F.struct("created_ts", "event_id", "repo_name"))["repo_name"]` ✅ | alpha-api | alpha-service | null | null | — |
| `F.min("repo_name")` | alpha-api | alpha-service | **beta-web** ❌ | null | Alphabetically smallest **name**, not the first event. Skips nulls |
| `F.first("repo_name", ignorenulls=True)` | alpha-api? | either? | **beta-web** ❌ | null | Skips e06's null and returns the **second** event |
| `F.first("repo_name")` after `orderBy` | ? | ? | ? | null | Order isn't guaranteed to survive the shuffle into `groupBy` |
| `F.min_by("repo_name", "created_ts")` | alpha-api | **either** ❌ | null | null | Can't break the 11:20 tie on a second column |
| `row_number()` ordered by `created_ts` only | alpha-api | **either** ❌ | null | null | Same: no tie-breaker |

Look at `F.min("repo_name")`. It gets **three out of four** right. It's correct for Dave's session 2 only because `"alpha-service" < "beta-web"` alphabetically. That's luck, not logic.

> **Trap:** A struct without the tie-breaker, `F.min(F.struct("created_ts", "repo_name"))`, has the same luck. At 11:20 it falls through to comparing **names**, and `alpha-service` wins alphabetically. Rename repo 202 to `aardvark-web` and Dave's session 2 silently flips. Tests that pass by accident are worse than tests that fail. Put `event_id` in the struct.

---

## Step 5: The `int` Casts 🔧

Build the summary without casts and check the types:

```python
for name, dtype in summary_no_casts.dtypes:
    print(f"{name:<31}{dtype}")
```

```
actor_login                    string
session_id                     int
session_start                  timestamp
session_end                    timestamp
distinct_repos_touched         bigint
events_in_session              bigint
primary_repo_at_session_start  string
```

`count` and `countDistinct` **always** return `bigint` (a 64-bit `long`), because Spark can't know in advance that your count fits in 32 bits. The spec says `int`. A test that compares schemas will fail on those two lines, even though every value is right.

`session_id` is already `int`. Post 07 cast it at the source, so the group key carries the type through.

> **Rule of thumb:** If the spec names a type, **cast to it** with `.cast("int")`, right where the column is made. "The numbers are right" isn't the same as "the output is right" when a downstream table, a test, or a BI tool checks the schema.

---

## `compute_session_summary`: The Full Function 🛠️

All five steps in one `agg`:

```python
from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def compute_session_summary(enriched: DataFrame) -> DataFrame:
    """One row per (actor_login, session_id).

    primary_repo_at_session_start is the repo_name of the session's first event:
    smallest created_ts, ties broken by smallest event_id. It stays null when
    that event had no matching repo version, even if later events did.
    """
    first_event = F.min(F.struct("created_ts", "event_id", "repo_name"))   # fields in sort order

    return (enriched
        .groupBy("actor_login", "session_id")                              # the full session key
        .agg(
            F.min("created_ts").alias("session_start"),
            F.max("created_ts").alias("session_end"),
            F.countDistinct("repo_id").cast("int").alias("distinct_repos_touched"),   # key, not name
            F.count(F.lit(1)).cast("int").alias("events_in_session"),                 # rows
            first_event["repo_name"].alias("primary_repo_at_session_start"),
        ))
```

Run it:

```python
summary = compute_session_summary(enriched)
summary.orderBy("actor_login", "session_id").show(truncate=False)
```

```
+-----------+----------+-------------------+-------------------+----------------------+-----------------+-----------------------------+
|actor_login|session_id|session_start      |session_end        |distinct_repos_touched|events_in_session|primary_repo_at_session_start|
+-----------+----------+-------------------+-------------------+----------------------+-----------------+-----------------------------+
|dave       |1         |2024-03-01 09:50:00|2024-03-01 10:40:00|2                     |3                |alpha-api                    |
|dave       |2         |2024-03-01 11:20:00|2024-03-01 11:20:00|2                     |2                |alpha-service                |
|jim        |1         |2024-03-01 10:15:00|2024-03-01 10:35:00|1                     |2                |null                         |
|jim        |2         |2024-03-01 12:30:00|2024-03-01 12:30:00|1                     |1                |null                         |
+-----------+----------+-------------------+-------------------+----------------------+-----------------+-----------------------------+
```

That's the course lab's expected summary, row for row. And it's the exact table Post 01 showed you on day one, back when half of it looked strange.

Now every value has a reason:

| Row | Odd-looking value | Why |
|---|---|---|
| Dave s1 | 3 events, 2 repos | e01 and e03 both on 101, e02 on 202 |
| Dave s1 | `alpha-api` | e01 at 09:50 is first. c1 was in force |
| Dave s2 | starts and ends 11:20 | e04 and e05 share a second |
| Dave s2 | `alpha-service`, not `beta-web` | Tie at 11:20, `"e04" < "e05"` |
| Jim s1 | `null` | First event e06 at 10:15 is before repo 202's history begins at 10:30 |
| Jim s2 | 1 repo, `null` name | Repo 999 has no history. It still counts as a repo touched |
| Nobody | e09 | No login. Dropped in sessionize (Post 07) |

---

## The Full Pipeline: `main()` 🔗

Seven functions, each tested on its own. Here's the wiring:

```python
from pyspark.sql import SparkSession


def main() -> None:
    spark = (SparkSession.builder
             .appName("reposphere")
             .master("local[*]")
             .config("spark.sql.session.timeZone", "UTC")     # Post 04: dates must not depend on the laptop
             .getOrCreate())

    events  = read_events(spark, "data/events.jsonl")               # 1  (Post 03)
    changes = read_repo_changes(spark, "data/repo_changes.jsonl")   # 2  (Post 03)

    flat      = flatten_events(events)                              # 3  (Post 04)
    repo_scd2 = build_repo_scd2(changes)                            # 4  (Post 06)
    sessions  = sessionize_actor_events(flat)                       # 5  (Post 07)
    enriched  = enrich_with_repo_state(sessions, repo_scd2)         # 6  (Post 08)
    summary   = compute_session_summary(enriched)                   # 7  (this post)

    summary.orderBy("actor_login", "session_id").show(truncate=False)
    spark.stop()


if __name__ == "__main__":
    main()
```

Two things about the order are easy to miss:

- **Sessionize runs before enrich.** So enrich receives `session_id` already attached, and e09 is already gone. That's why Post 08 used `"e.*"` instead of hand-listing columns.
- **Nothing runs until `.show()`.** Every line above it just adds to a plan ([Post 02](content/data-engineering/02-spark-from-first-principles.md)). Spark optimises all seven steps together, then executes once.

Here's how many rows exist after each step:

```python
stages = [("read_events", events), ("read_repo_changes", changes),
          ("flatten_events", flat), ("build_repo_scd2", repo_scd2),
          ("sessionize", sessions), ("enrich", enriched), ("summary", summary)]

for name, df in stages:
    print(f"{name:<20}{df.count()}")
```

```
read_events         9
read_repo_changes   5
flatten_events      9
build_repo_scd2     5
sessionize          8
enrich              8
summary             4
```

![The full pipeline as two lanes: read_events 9, flatten_events 9, sessionize_actor_events 8 with e09 dropped; read_repo_changes 5, build_repo_scd2 5; both feed enrich_with_repo_state 8, which feeds compute_session_summary 4](content/data-engineering/images/pipeline_row_counts.svg)

Every count has exactly one expected change:

| Step | Rows | Should it change? |
|---|---|---|
| `flatten_events` | 9 → 9 | Never. It's a `select` |
| `build_repo_scd2` | 5 → 5 | Never. One version per change |
| `sessionize_actor_events` | 9 → 8 | Only by the null-login rows (e09) |
| `enrich_with_repo_state` | 8 → 8 | **Never.** A left join to non-overlapping versions |
| `compute_session_summary` | 8 → 4 | To the number of distinct `(actor, session)` pairs |

> **Key insight:** Print this table every time you change the pipeline. Most bugs in Part 1 show up as a count that moved when it shouldn't have, or didn't move when it should. It costs one line per stage and catches them before anyone reads a single value.

---

## Pre-Flight Checklist ✈️

Before you call the pipeline done, go down this list. Each line is a bug from Posts 02–09:

- [ ] If **no** line in the file has `actor.login`, does the job still run? (Explicit schema, Post 03)
- [ ] Every null check uses `.isNull()` / `.isNotNull()`, never `== None` or `!= None` (Post 02)
- [ ] Every computed column is **aliased** to the exact spec name (Post 04)
- [ ] `spark.sql.session.timeZone` is `UTC` (Post 04)
- [ ] Every window that needs a strict order has a **tie-breaker** (Posts 05, 06, 07, 09)
- [ ] Session boundary is `> 1800`, so a gap of exactly 1800 s stays in the session (Post 07)
- [ ] Each actor's first event gets session **1**, not 0 (Post 07)
- [ ] The running sum uses `rowsBetween`, not the default range frame (Posts 05, 07)
- [ ] The join keeps events with no match, **and** events in a current version (Post 08)
- [ ] Enriched row count equals the sessionized row count (Post 08)
- [ ] Summary is grouped by **`(actor_login, session_id)`**, not `session_id` alone
- [ ] `distinct_repos_touched` counts `repo_id`, not `repo_name`
- [ ] `session_id`, `distinct_repos_touched`, `events_in_session` are **`int`**, not `bigint`
- [ ] `primary_repo_at_session_start` stays **null** when the first event is unmatched, even if later ones matched
- [ ] Every helper column (`prev_ts`, `is_new_session`, `rn`) is dropped before returning

---

## If Your Output Differs 🩺

| Symptom | Likely cause | Post |
|---|---|---|
| e03 in Dave's session **2** | Boundary written as `>=` instead of `>` | 07 |
| A session numbered **0** | Missing the `prev_ts.isNull()` first-row branch | 07 |
| More than 8 enriched rows | Interval closed at both ends, or no time condition | 08 |
| e04 has null repo details | Missing the `valid_to IS NULL` branch | 08 |
| Only 5 enriched rows | Inner join, or range moved into `.filter()` | 08 |
| Only 2 summary rows | Grouped by `session_id` alone | 09 |
| Jim s2 shows 0 repos touched | Counted `repo_name` instead of `repo_id` | 09 |
| Dave s2 shows `beta-web` (sometimes) | No `event_id` tie-breaker for the first row | 09 |
| Jim s1 shows `beta-web` | Skipped nulls when picking the first row | 09 |
| Values right, schema test fails | Counts left as `bigint` | 09 |

---

## Every Expected Lab Output 📋

Sort the same way before comparing. Each stage, in pipeline order:

<details>
<summary>Expected · flatten_events (orderBy event_id)</summary>

```
+--------+----------------+-------------------+----------+-------+-----------+
|event_id|event_type      |created_ts         |event_date|repo_id|actor_login|
+--------+----------------+-------------------+----------+-------+-----------+
|e01     |pushevent       |2024-03-01 09:50:00|2024-03-01|101    |dave       |
|e02     |pullrequestevent|2024-03-01 10:10:00|2024-03-01|202    |dave       |
|e03     |issuesevent     |2024-03-01 10:40:00|2024-03-01|101    |dave       |
|e04     |pushevent       |2024-03-01 11:20:00|2024-03-01|101    |dave       |
|e05     |pushevent       |2024-03-01 11:20:00|2024-03-01|202    |dave       |
|e06     |pushevent       |2024-03-01 10:15:00|2024-03-01|202    |jim        |
|e07     |issuesevent     |2024-03-01 10:35:00|2024-03-01|202    |jim        |
|e08     |pushevent       |2024-03-01 12:30:00|2024-03-01|999    |jim        |
|e09     |pushevent       |2024-03-01 10:00:00|2024-03-01|101    |null       |
+--------+----------------+-------------------+----------+-------+-----------+
```

</details>

<details>
<summary>Expected · build_repo_scd2 (orderBy repo_id, valid_from)</summary>

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

</details>

<details>
<summary>Expected · sessionize_actor_events (selected columns)</summary>

```
+--------+-----------+-------------------+-------+----------+
|event_id|actor_login|created_ts         |repo_id|session_id|
+--------+-----------+-------------------+-------+----------+
|e01     |dave       |2024-03-01 09:50:00|101    |1         |
|e02     |dave       |2024-03-01 10:10:00|202    |1         |
|e03     |dave       |2024-03-01 10:40:00|101    |1         |
|e04     |dave       |2024-03-01 11:20:00|101    |2         |
|e05     |dave       |2024-03-01 11:20:00|202    |2         |
|e06     |jim        |2024-03-01 10:15:00|202    |1         |
|e07     |jim        |2024-03-01 10:35:00|202    |1         |
|e08     |jim        |2024-03-01 12:30:00|999    |2         |
+--------+-----------+-------------------+-------+----------+
```

</details>

<details>
<summary>Expected · enrich_with_repo_state (selected columns)</summary>

```
+--------+-----------+----------+-------------------+-------+-------------+----------+--------------+
|event_id|actor_login|session_id|created_ts         |repo_id|repo_name    |visibility|default_branch|
+--------+-----------+----------+-------------------+-------+-------------+----------+--------------+
|e01     |dave       |1         |2024-03-01 09:50:00|101    |alpha-api    |public    |main          |
|e02     |dave       |1         |2024-03-01 10:10:00|202    |null         |null      |null          |
|e03     |dave       |1         |2024-03-01 10:40:00|101    |alpha-api    |private   |main          |
|e04     |dave       |2         |2024-03-01 11:20:00|101    |alpha-service|public    |main          |
|e05     |dave       |2         |2024-03-01 11:20:00|202    |beta-web     |public    |master        |
|e06     |jim        |1         |2024-03-01 10:15:00|202    |null         |null      |null          |
|e07     |jim        |1         |2024-03-01 10:35:00|202    |beta-web     |public    |master        |
|e08     |jim        |2         |2024-03-01 12:30:00|999    |null         |null      |null          |
+--------+-----------+----------+-------------------+-------+-------------+----------+--------------+
```

The full output also carries `event_type` and `event_date`, and has 8 rows.

</details>

<details>
<summary>Expected · compute_session_summary (orderBy actor_login, session_id)</summary>

```
+-----------+----------+-------------------+-------------------+----------------------+-----------------+-----------------------------+
|actor_login|session_id|session_start      |session_end        |distinct_repos_touched|events_in_session|primary_repo_at_session_start|
+-----------+----------+-------------------+-------------------+----------------------+-----------------+-----------------------------+
|dave       |1         |2024-03-01 09:50:00|2024-03-01 10:40:00|2                     |3                |alpha-api                    |
|dave       |2         |2024-03-01 11:20:00|2024-03-01 11:20:00|2                     |2                |alpha-service                |
|jim        |1         |2024-03-01 10:15:00|2024-03-01 10:35:00|1                     |2                |null                         |
|jim        |2         |2024-03-01 12:30:00|2024-03-01 12:30:00|1                     |1                |null                         |
+-----------+----------+-------------------+-------------------+----------------------+-----------------+-----------------------------+
```

</details>

---

## Part 1, Done 🎉

Nine posts. Seven functions. One table Product can actually use.

| # | Function | The one idea that makes it work | Post |
|---|---|---|---|
| 1 | `read_events` | An explicit nested schema is a contract | 03 |
| 2 | `read_repo_changes` | Same contract, flat | 03 |
| 3 | `flatten_events` | Dot paths, aliases, real timestamps in UTC | 04 |
| 4 | `build_repo_scd2` | `lead` over a sorted window closes each version | 05, 06 |
| 5 | `sessionize_actor_events` | Lag, gap, flag, running sum | 05, 07 |
| 6 | `enrich_with_repo_state` | Left join on key **and** half-open range | 08 |
| 7 | `compute_session_summary` | Full group key, count the key, struct-min with a tie-breaker | 09 |

Notice what **didn't** come up: speed, clusters, tuning. Every bug in Part 1 was a **correctness** bug. A null that got skipped, a tie with no winner, a boundary on the wrong side. That's most of data engineering.

---

## Quick Quiz 🧠

**Q1.** Your teammate's summary has **2** rows instead of 4, with `events_in_session` of 5 and 3. What did they group by?

<details>
<summary>Show answer</summary>

**`session_id` alone.** Session numbers restart at 1 for every actor, so Dave's session 1 (3 events) and Jim's session 1 (2 events) merge into one group of 5, and both session 2s merge into one group of 3. The key of a session is `(actor_login, session_id)`.

</details>

**Q2.** Jim's session 2 comes out with `distinct_repos_touched = 0`. What's the bug, and why is 0 wrong?

<details>
<summary>Show answer</summary>

They used **`F.countDistinct("repo_name")`**. e08's repo 999 has no history, so the point-in-time join gave it a null `repo_name`, and `countDistinct` skips nulls. But Jim **did** push to a repo: `repo_id` 999. Count the key from the event (`repo_id`), not the label from the join.

</details>

**Q3.** Why does `F.min(F.struct("created_ts", "event_id", "repo_name"))` return **null** for Jim's session 1, when `F.min` is supposed to skip nulls?

<details>
<summary>Show answer</summary>

`min` skips null **values**, and the values here are structs. e06's struct, `{10:15, e06, null}`, isn't null; it just **contains** a null field. It has the smallest `created_ts`, so it's the minimum, and `["repo_name"]` reads its null field out. That's exactly the spec: the first event had no repo name, so the answer is null, not e07's `beta-web`.

</details>

**Q4.** Someone uses `F.min(F.struct("created_ts", "repo_name"))`, with no `event_id`. The lab output matches perfectly. What's wrong?

<details>
<summary>Show answer</summary>

It's **right by accident**. At Dave's 11:20 tie, the struct falls through to comparing `repo_name`, and `"alpha-service" < "beta-web"` alphabetically, which happens to match `"e04" < "e05"`. If repo 202 were named `aardvark-web`, Dave's session 2 would flip to it. The spec breaks ties by `event_id`, so `event_id` must be the second field.

</details>

**Q5.** Every value in your summary matches the lab, but the schema test fails. Which columns would you check first, and what's the fix?

<details>
<summary>Show answer</summary>

**`distinct_repos_touched` and `events_in_session`.** `count` and `countDistinct` always return `bigint`. The spec says `int`, so add `.cast("int")` to both. (`session_id` is already `int` because `sessionize_actor_events` cast it.)

</details>

---

## What's Next? 🚀

Part 1 is complete: a correct pipeline, from raw JSON to session summary. But it has a problem we haven't faced yet. Every run starts from scratch and writes its output... where, exactly? Plain folders of Parquet files can't do atomic updates, can't undo a bad load, and can't tell two writers apart.

Part 2 fixes that, starting with the table format underneath a modern lakehouse.

👉 **[Post 10 — Why Table Formats? Apache Iceberg](content/data-engineering/10-why-table-formats-iceberg.md)** — what goes wrong with plain Parquet folders, Iceberg's metadata tree, atomic commits, optimistic concurrency, and how Iceberg compares with Delta.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
