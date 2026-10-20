---
title: "Point-in-Time Joins"
date: 2026-10-20
tags: [data-engineering, pyspark, joins, point-in-time, scd-type-2, first-principles]
description: How enrich_with_repo_state joins every RepoSphere event to the repo version that was true at that instant — a left range join on [valid_from, valid_to) with the valid_to IS NULL branch, why e02, e06 and e08 come back with nulls, and the row-count check that catches most join bugs before anyone else does.
---

# Joining Facts to the Past ⏳

In [Post 07](content/data-engineering/07-sessionization-gaps-and-islands.md), every event learned **who** did it and **which session** it belongs to. In [Post 06](content/data-engineering/06-scd-type-2.md), every repo got a full **history**: each version with a clean `[valid_from, valid_to)` lifetime.

Two tables. One on each lane of the pipeline. This is where the lanes meet.

Here's the second thing Product asked for, back in [Post 01](content/data-engineering/01-what-is-data-engineering.md):

> "If an event happened at 10:40 when the repo was **private**, the report must say **private**, even though today it's public."

Look at Dave's 10:40 issue on repo 101 (that's e03). Today, repo 101 is called `alpha-service` and it's public. But at 10:40, it was still `alpha-api`, and for one hour it was **private**.

A normal join on `repo_id` can't tell those apart. It hands e03 **every** version of repo 101, or, if you join only to the current row, the **wrong** one.

That's pipeline function #6: **`enrich_with_repo_state`**. The rule:

> Join each event to the repo version that was in force **at the event's `created_ts`**. Keep every event. Append exactly three columns: `repo_name`, `visibility`, `default_branch`.

It's called a **point-in-time join**. It's one condition longer than a normal join, and that one condition is where all the bugs live.

---

## The Old Newspaper Analogy 📰

Say you're writing a biography. You find a letter from 1994 that mentions "the Prime Minister". Who's that?

You don't look up **today's** Prime Minister. You look up who held the office **on the day the letter was written**.

To do that, you need a list of every Prime Minister with a **start date** and an **end date**. Then you ask two questions about the letter's date:

- Had this person **started** by then?
- Had they **not yet left**?

Exactly one person passes both. That's your answer.

And if the letter is from before you have any records? You write "unknown". You **don't** guess the earliest name on your list.

Those three ideas map one to one onto RepoSphere:

| Biography | RepoSphere |
|---|---|
| The letter | An event (e03) |
| The letter's date | `created_ts` (10:40) |
| The list of office-holders | `repo_scd2` for repo 101 |
| Start and end of a term | `valid_from`, `valid_to` |
| "Still in office" | `valid_to IS NULL` |
| "No records that early" | No matching version → **null** details |

---

## What We're Joining 📥

The left side is the output of `sessionize_actor_events` from Post 07: eight events, e09 already gone.

```python
events    = read_events(spark, "data/events.jsonl")
changes   = read_repo_changes(spark, "data/repo_changes.jsonl")

sessions  = sessionize_actor_events(flatten_events(events))
repo_scd2 = build_repo_scd2(changes)

sessions.select("event_id", "actor_login", "created_ts", "repo_id", "session_id") \
        .orderBy("actor_login", "created_ts", "event_id").show(truncate=False)
```

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

The right side is Post 06's history table:

```python
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

Three events are going to be awkward. Spot them before reading on:

| Event | Repo | Time | What's awkward |
|---|---|---|---|
| **e02** | 202 | 10:10 | Repo 202's first known version starts at **10:30** |
| **e06** | 202 | 10:15 | Same: **before** any history for 202 |
| **e08** | 999 | 12:30 | Repo 999 (`ghost`) has **no history at all** |

The lab's expected output has nulls for all three. By the end of this post, you'll know exactly why, and why that's correct.

---

## Attempt 1: Join on `repo_id` Alone 💥

The obvious join. Same repo, done:

```python
naive = sessions.join(repo_scd2, "repo_id", "left")
print(sessions.count(), naive.count())
```

```
8 18
```

Eight events went in. **Eighteen** rows came out.

Zoom in on e03:

```python
(naive.filter(F.col("event_id") == "e03")
      .select("event_id", "created_ts", "repo_name", "visibility", "valid_from", "valid_to")
      .orderBy("valid_from")
      .show(truncate=False))
```

```
+--------+-------------------+-------------+----------+-------------------+-------------------+
|event_id|created_ts         |repo_name    |visibility|valid_from         |valid_to           |
+--------+-------------------+-------------+----------+-------------------+-------------------+
|e03     |2024-03-01 10:40:00|alpha-api    |public    |2024-03-01 09:00:00|2024-03-01 10:00:00|
|e03     |2024-03-01 10:40:00|alpha-api    |private   |2024-03-01 10:00:00|2024-03-01 11:00:00|
|e03     |2024-03-01 10:40:00|alpha-service|public    |2024-03-01 11:00:00|null               |
+--------+-------------------+-------------+----------+-------------------+-------------------+
```

One event, three answers. The join matched e03 to **every** version of repo 101, because nothing in the condition mentions time.

Count it up: every repo-101 event gets 3 rows, every repo-202 event gets 2, and e08 gets 1 all-null row (left join, no match). That's 3 × 3 + 2 × 4 + 1 = **18**.

> **Key insight:** Joining a fact to an SCD Type 2 table on the business key alone is a **one-to-many** join. It multiplies each event by the number of versions. Every `count()` and `sum()` downstream inflates silently.

## Attempt 2: Join to the Current Row Only 🤷

"Fine. Just keep `is_current = true`." This is what an SCD Type 1 table would give you:

| Event | Time | Current-only join says | What was actually true | Right? |
|---|---|---|---|---|
| e01 | 09:50 | alpha-service · public · main | alpha-api · public · main | ❌ |
| e02 | 10:10 | beta-web · public · main | **no record yet** | ❌ |
| e03 | 10:40 | alpha-service · public · main | alpha-api · **private** · main | ❌ |
| e04 | 11:20 | alpha-service · public · main | alpha-service · public · main | ✅ |
| e05 | 11:20 | beta-web · public · main | beta-web · public · **master** | ❌ |
| e06 | 10:15 | beta-web · public · main | **no record yet** | ❌ |
| e07 | 10:35 | beta-web · public · main | beta-web · public · **master** | ❌ |
| e08 | 12:30 | null | null | ✅ |

The row count is right this time. **Six of eight answers are wrong.** And e03, the one Product named, says public.

This is the sneakier failure. Nothing duplicates, nothing crashes. The numbers just describe today instead of the day it happened.

---

## Attempt 3: The Point-in-Time Condition 🎯

We need both: match on the repo **and** on time. Three clauses, joined with `&`:

```python
e = sessions.alias("e")
r = repo_scd2.alias("r")

in_force = (
    (F.col("e.repo_id") == F.col("r.repo_id"))                     # 1. same repo
    & (F.col("r.valid_from") <= F.col("e.created_ts"))              # 2. version had started
    & (F.col("r.valid_to").isNull()                                 # 3. ...and hadn't ended
       | (F.col("e.created_ts") < F.col("r.valid_to")))
)
```

Read it like the biography: **same office**, **had started**, **hadn't left yet**. Clause 3 has two ways to say "hadn't left": the version is still current (`valid_to` is null), or the event came strictly before the version ended.

![The join condition checked against every version for e03 at 10:40: c1 passes repo_id and valid_from but fails 10:40 < 10:00; c2 passes all three clauses and matches; c3 fails 11:00 <= 10:40; repo 202's versions fail the repo_id check](content/data-engineering/images/pit_join_condition.svg)

Every clause knocks out a different wrong answer:

| Clause | Knocks out for e03 | Without it |
|---|---|---|
| `e.repo_id == r.repo_id` | Repo 202's versions | Every event matches every repo's versions |
| `r.valid_from <= e.created_ts` | c3 (alpha-service, starts **after** 10:40) | Events match versions from their **future** |
| `r.valid_to IS NULL OR e.created_ts < r.valid_to` | c1 (ended **before** 10:40) | Events match versions from their **past** |

Only c2 survives. e03 comes back `alpha-api`, `private`. That's Product's sentence, in data.

> **Key insight:** A point-in-time join is an **equi-join plus a range filter**. The equality (`repo_id`) finds the candidates. The range (`valid_from`, `valid_to`) picks the one that was true. Spark runs it exactly that way: it pairs rows by `repo_id`, then checks the range on each pair.

---

## Trap 1: Forgetting the `valid_to IS NULL` Branch 🕳️

It's tempting to write clause 3 as just the comparison:

```python
(F.col("e.created_ts") < F.col("r.valid_to"))       # ❌ no isNull branch
```

The current version of every repo has `valid_to = null`. And from [Post 02](content/data-engineering/02-spark-from-first-principles.md): `11:20 < null` is **null**, not true. A join treats null like false. So the current version **never matches anything**.

In our data, one event lives in a current version: e04 (repo 101 at 11:20, inside `[11:00, null)`).

| Event | Correct | Without the `isNull()` branch |
|---|---|---|
| e04 | alpha-service · public · main | **null · null · null** ❌ |
| every other event | unchanged | unchanged |

The row count stays 8. No error. One event quietly loses its details.

In real data, it's much worse. **Every event since the latest change to its repo** is in a current version. That's usually most of today's events, the ones people look at first.

> **Trap:** Any range check against an open-ended interval needs its own null branch. `null` means "still going". A comparison can't know that. You have to say it.

---

## Trap 2: Closing Both Ends of the Interval 🚪

Post 06 promised the intervals are **half-open**: `[valid_from, valid_to)`. Start included, end excluded. The join is where that promise gets cashed.

| Clause pair | Interval it describes | Event exactly at a boundary |
|---|---|---|
| `valid_from <= ts` and `ts < valid_to` ✅ | `[from, to)` | Matches **one** version: the new one |
| `valid_from <= ts` and `ts <= valid_to` ❌ | `[from, to]` | Matches **two** versions: old and new |
| `valid_from < ts` and `ts < valid_to` ❌ | `(from, to)` | Matches **zero** versions |

Here's the twist: **the lab data won't catch this bug.** No remaining event sits exactly on a boundary. (e09 did, at 10:00 on repo 101, and Post 06 used it to show this exact problem. But `sessionize_actor_events` dropped e09 for having no login.)

So add your own test row. Say Dave pushes to repo 101 at exactly **11:00:00**. Call it e10:

| Version of 101 | `valid_from <= 11:00` | `11:00 < valid_to` | `11:00 <= valid_to` |
|---|---|---|---|
| c1 `[09:00, 10:00)` | ✅ | ❌ | ❌ |
| c2 `[10:00, 11:00)` · private | ✅ | ❌ | ✅ |
| c3 `[11:00, null)` · alpha-service | ✅ | null branch ✅ | null branch ✅ |
| **Rows for e10** | | **1** (alpha-service) | **2** (private **and** alpha-service) |

With `<=` at the end, e10 becomes two rows. One says private, one says public. Every count over it doubles.

> **Trap:** Use `<=` at the start and `<` at the end. Then write a test event that lands **exactly** on a `valid_to`, because that's the only row where right and wrong disagree. Same lesson as the 1800-second gap in Post 07: test the boundary itself.

---

## Trap 3: Using an Inner Join 🧹

Swap `"left"` for `"inner"`, and three events disappear:

```python
inner = e.join(r, in_force, "inner")
print(inner.count())
print(sorted(row.event_id for row in inner.select("e.event_id").collect()))
```

```
5
['e01', 'e03', 'e04', 'e05', 'e07']
```

| Join type | e02, e06 (before 202's history) | e08 (repo 999, no history) | Rows |
|---|---|---|---|
| `inner` | Dropped | Dropped | 5 ❌ |
| `left` ✅ | Kept, three null columns | Kept, three null columns | 8 |

Enrichment **adds** information. It must never **remove** facts. Dave really did open that pull request at 10:10. Jim really did push to repo 999. Post 09's session summary counts events; with an inner join, Dave's session 1 shows 2 events instead of 3, and Jim's session 2 vanishes entirely.

> **Rule of thumb:** Facts on the **left**. Dimensions on the **right**. `how="left"`. Always.

### The sneaky version: a range check in `.filter()`

Someone writes the join on `repo_id` only, still `left`, then tidies up afterwards:

```python
wrong = (sessions.join(repo_scd2, "repo_id", "left")
         .filter((F.col("valid_from") <= F.col("created_ts")) &
                 (F.col("valid_to").isNull() | (F.col("created_ts") < F.col("valid_to")))))
print(wrong.count())
```

```
5
```

Same five as the inner join. Why? The filter runs **after** the join. For e08, the left join produced one row with `valid_from = null`. `null <= 12:30` is null, and `filter` drops null. For e02 and e06, both of their candidate rows fail the range, so both get filtered and nothing is left.

> **Key insight:** In a left join, conditions in the **`ON`** decide which right-side row to attach, and the left row survives either way. Conditions in a **`WHERE`/`.filter()`** decide which rows survive. Move the range out of the join and your left join becomes an inner join.

---

## Why e02, e06 and e08 Get Nulls 🔍

Those nulls aren't a bug. They're the **correct answer**.

| Event | Why there's no match | Could we fill it in? |
|---|---|---|
| e02 · 202 · 10:10 | Repo 202's history starts at 10:30. Nothing covers 10:10 | Only by guessing |
| e06 · 202 · 10:15 | Same: 20 minutes before the first known change | Only by guessing |
| e08 · 999 · 12:30 | Repo 999 never appears in `repo_changes.jsonl` | Only by guessing |

"Just use 202's earliest version for anything before it" is tempting. But at 10:10 the repo might have been private, or named differently. c4 says `master` at 10:30. You have no idea what it said at 10:10. **Null means "we don't know", and that's the truth.**

What about e08? The raw event did carry `"name": "ghost"`. But `flatten_events` didn't keep `repo.name`, on purpose. [Post 04](content/data-engineering/04-flattening-and-timestamps.md) kept the column list tight for exactly this moment: if the events already had a `repo_name` column, appending `r.repo_name` would give you **two columns with one name**, and every later reference would be ambiguous.

> **Why does this matter for Post 09?** The summary's `primary_repo_at_session_start` comes from the **first** event of each session. Jim's session 1 starts with e06. e06 has no repo name, so the answer is null, even though e07, later in the same session, matched `beta-web`. The nulls you keep here decide the answer there.

---

## Aliases and `"e.*"` 🏷️

Both tables have a `repo_id` column. Write `F.col("repo_id")` in the condition and Spark can't tell which one you mean. It refuses to run, with an `AnalysisException` saying the reference is **ambiguous**.

Aliases fix that. `sessions.alias("e")` and `repo_scd2.alias("r")` give each side a name, so `e.repo_id` and `r.repo_id` are different columns.

Then the select:

```python
.select("e.*", F.col("r.repo_name"), F.col("r.visibility"), F.col("r.default_branch"))
```

`"e.*"` brings every events column, in its original order. The three `r.` columns are exactly what the spec asks for. Everything else on the right stays out: `r.repo_id` would duplicate `e.repo_id`, and `valid_from`, `valid_to`, `is_current` are plumbing.

`"e.*"` matters more than it looks. Notice that `main()` runs sessionize **before** enrich. So the events coming in already carry `session_id`. If you had written out the six `flatten_events` columns by name, `session_id` would silently fall off. `"e.*"` doesn't care what's on the left. It keeps all of it.

---

## `enrich_with_repo_state`: The Full Function 🛠️

```python
from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def enrich_with_repo_state(events: DataFrame, repo_scd2: DataFrame) -> DataFrame:
    """Attach the repo version that was in force at each event's created_ts.

    Left join: every event is kept. Events with no matching version
    (before the repo's first change, or an unknown repo) get nulls.
    """
    e = events.alias("e")
    r = repo_scd2.alias("r")

    in_force = (
        (F.col("e.repo_id") == F.col("r.repo_id"))                    # same repo
        & (F.col("r.valid_from") <= F.col("e.created_ts"))             # start: inclusive
        & (F.col("r.valid_to").isNull()                                # current version, or
           | (F.col("e.created_ts") < F.col("r.valid_to")))            # end: exclusive
    )

    return (e.join(F.broadcast(r), in_force, "left")                  # dimension is small: broadcast it
             .select("e.*",                                            # every event column, as-is
                     F.col("r.repo_name"),
                     F.col("r.visibility"),
                     F.col("r.default_branch")))
```

> **Why `F.broadcast`?** The dimension is tiny compared with the events. A broadcast sends a full copy of `repo_scd2` to every executor, so the big events table never has to shuffle across the network. It's a performance hint only: the result is identical with or without it.

Run it on the lab data:

```python
enriched = enrich_with_repo_state(sessions, repo_scd2)

(enriched
 .select("event_id", "actor_login", "session_id", "created_ts",
         "repo_id", "repo_name", "visibility", "default_branch")
 .orderBy("actor_login", "created_ts", "event_id")
 .show(truncate=False))
```

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

That's the course lab's expected `enrich_with_repo_state` output, row for row.

Read the good rows against the history:

- **e01** at 09:50 → c1, `alpha-api`, public. Before the flip to private.
- **e03** at 10:40 → c2, **private**. The late-arriving c2 from Post 06 earns its keep here.
- **e04** at 11:20 → c3, `alpha-service`. The renamed, current version, found thanks to the `isNull()` branch.
- **e05** at 11:20 → c4, `beta-web` on **`master`**. Repo 202 doesn't switch to `main` until 12:00.
- **e07** at 10:35 → c4, five minutes after 202's history begins.

Now the shape:

```python
print(enriched.columns)
print(sessions.count(), enriched.count())
```

```
['event_id', 'event_type', 'created_ts', 'event_date', 'repo_id', 'actor_login', 'session_id', 'repo_name', 'visibility', 'default_branch']
8 8
```

All seven input columns, `session_id` included, then exactly three new ones. **Eight rows in, eight rows out.**

---

## The One Check You Should Always Run ✔️

> **Key insight:** A left join from facts to a dimension with **non-overlapping** intervals can never change the row count. Each event matches **at most one** version. If it matches none, the left join keeps it anyway.

So this one line is a test for most of the bugs in this post:

```python
assert enriched.count() == sessions.count(), "point-in-time join changed the row count"
```

![Row counts for five join variants: the correct left half-open range join returns 8; joining on repo_id only returns 18; an inner join returns 5; a left join with the range moved into a filter returns 5; dropping the valid_to IS NULL branch returns 8 but e04 loses its details](content/data-engineering/images/join_variants_row_count.svg)

| Bug | Count | Caught by the count check? |
|---|---|---|
| No time condition at all | 18 | ✅ More rows |
| `<=` at the end, event on a boundary | 9+ | ✅ More rows |
| Two versions with overlapping intervals | 9+ | ✅ More rows |
| `how="inner"` | 5 | ✅ Fewer rows |
| Range moved into `.filter()` | 5 | ✅ Fewer rows |
| No `valid_to IS NULL` branch | 8 | ❌ Same count, wrong values |
| Join to current row only | 8 | ❌ Same count, wrong values |

The count check catches five of seven. For the last two, you need a **value** test: one event in a current version (e04 must say `alpha-service`), and one event in a past version (e03 must say `private`). The lab has both.

---

## What Each Line Protects You From 🛡️

| Line | Remove it and… |
|---|---|
| `.alias("e")`, `.alias("r")` | `repo_id` is ambiguous. `AnalysisException` |
| `e.repo_id == r.repo_id` | Every event matches every repo's history |
| `r.valid_from <= e.created_ts` | e03 also matches c3, its future |
| `r.valid_to.isNull() \|` | e04, and every event in a current version, loses its details |
| `e.created_ts < r.valid_to` (not `<=`) | Events on a boundary become two rows |
| `"left"` | e02, e06, e08 vanish. Post 09's counts drop |
| Range inside the join, not a filter | Same as an inner join |
| `"e.*"` | Hand-listed columns drop `session_id` |
| Only three `r.` columns | `valid_from`, `valid_to` and a second `repo_id` leak out |
| `F.broadcast(r)` | Still correct. Slower on big data |

---

## Quick Reference ✅

- [ ] Facts on the left, `how="left"`. Enrichment never removes rows
- [ ] Alias both sides: `events.alias("e")`, `repo_scd2.alias("r")`
- [ ] Condition = key match **and** `valid_from <= ts` **and** (`valid_to IS NULL` **or** `ts < valid_to`)
- [ ] Every condition goes **inside** the join, never in a later `.filter()`
- [ ] `select("e.*", ...)` plus exactly `repo_name`, `visibility`, `default_branch`
- [ ] `assert enriched.count() == events.count()`
- [ ] Value test: an event in a **current** version (e04 → `alpha-service`)
- [ ] Value test: an event in a **past** version (e03 → `private`)
- [ ] Boundary test: an event **exactly** at a `valid_to`
- [ ] Nulls for e02, e06, e08 are correct. Don't back-fill them

---

## Quick Quiz 🧠

**Q1.** Jim pushes to repo 202 at exactly **12:00:00**. What `repo_name`, `visibility` and `default_branch` does `enrich_with_repo_state` give that event?

<details>
<summary>Show answer</summary>

**`beta-web`, `public`, `main`** — that's c5. The c4 version `[10:30, 12:00)` fails because `12:00 < 12:00` is false. c5 `[12:00, null)` passes: `12:00 <= 12:00` is true, and its `valid_to` is null. With `<=` at the end, the event would match **both** and become two rows, one saying `master` and one saying `main`.

</details>

**Q2.** A teammate's version returns 8 rows, but e04 has `repo_name = null`. Which part of the condition is missing?

<details>
<summary>Show answer</summary>

The **`r.valid_to.isNull() |`** branch. e04 at 11:20 belongs to repo 101's current version, c3, whose `valid_to` is null. `11:20 < null` is null, which the join treats as false, so c3 never matches. No other version covers 11:20, so the left join fills nulls. The row count can't catch this; only a value test on an event in a current version can.

</details>

**Q3.** You switch `"left"` to `"inner"`. How many rows come out, and which events are gone?

<details>
<summary>Show answer</summary>

**5 rows.** Gone: **e02** and **e06** (repo 202 at 10:10 and 10:15, before its first known version at 10:30) and **e08** (repo 999, no history at all). In Post 09's summary, Dave's session 1 would show 2 events instead of 3, and Jim's session 2 would disappear completely.

</details>

**Q4.** After a new day's data, `enriched.count()` is 1 higher than `sessions.count()`. The join code hasn't changed and still uses `<` at the end. Where would you look?

<details>
<summary>Show answer</summary>

At the **dimension**: two versions of the same repo now **overlap**, so one event matches both. A `lead`-built table like Post 06's can't overlap, because each version ends exactly where the next begins. The classic cause is a table maintained some other way, such as an incremental load that appends a new version without closing the old one, leaving **two** rows with `valid_to = null` for one repo. First find the event that appears twice (`groupBy("event_id").count().filter("count > 1")`), then look at its repo's versions.

</details>

**Q5.** Why not fill e02's nulls with repo 202's earliest known version (c4: `beta-web`, `public`, `master`)?

<details>
<summary>Show answer</summary>

Because c4 is only known to be true **from 10:30**. At 10:10 the repo could have been private, named differently, or on another branch. Copying c4 backwards turns "we don't know" into a confident claim that might be false. A point-in-time join reports what was **recorded** as true at that instant, and for 10:10 nothing was. Null is the honest answer.

</details>

---

## What's Next? 🚀

Every event now carries **who** (actor), **when** (session) and **what the repo was** at that moment. All that's left is to roll it up into the table Product actually asked for.

👉 **[Post 09 — Aggregates and the Full Pipeline](content/data-engineering/09-aggregates-and-full-pipeline.md)** — `compute_session_summary` with `countDistinct`, picking the first row per group with a struct-min or `row_number` and an `event_id` tie-breaker, the int casts, the full `main()`, a pre-flight checklist, and every expected lab output end to end.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
