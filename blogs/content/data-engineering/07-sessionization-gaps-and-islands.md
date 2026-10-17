---
title: "Sessionization — Gaps and Islands"
date: 2026-10-17
tags: [data-engineering, pyspark, sessionization, gaps-and-islands, window-functions, first-principles]
description: How sessionize_actor_events turns RepoSphere's loose stream of events into work sessions — the four-step gaps-and-islands recipe, why a gap of exactly 1800 seconds needs a strict >, cast("double") vs cast("long"), why the first row must be session 1, and why e09 has to go before the window ever runs.
---

# Finding the Islands in a Stream of Events 🏝️

In [Post 06](content/data-engineering/06-scd-type-2.md), we built the **dimension** side of RepoSphere: every version of every repo, each with a clean half-open lifetime. `lead` did the heavy lifting.

Now we go back to the **facts**. And to `lead`'s twin: `lag`.

Here's what Product asked for, back in [Post 01](content/data-engineering/01-what-is-data-engineering.md):

> "Dave worked from **09:50 to 10:40** and touched **2 repos**."

Look at what we actually have. After `flatten_events` ([Post 04](content/data-engineering/04-flattening-and-timestamps.md)), Dave is just five rows with timestamps: 09:50, 10:10, 10:40, 11:20, 11:20. Nothing in the data says "session". No `session_start` event. No "logged off" button.

Sessions don't exist in the raw data. **You have to invent them**, from the pauses between events.

That's pipeline function #5: **`sessionize_actor_events`**. The rule from the spec:

> A new session starts when the gap since the actor's previous event is **strictly greater than 30 minutes** (1800 seconds).

One sentence. Five ways to get it wrong. Let's go.

---

## The Photo Gallery Analogy 📸

Open the photo app on your phone. Scroll back to a holiday.

Your phone doesn't show 400 loose photos. It groups them into **moments**: "Beach, morning", "Dinner", "Airport". Nobody tagged those. The phone worked them out.

How? It walks through your photos **in time order** and asks one question of each photo:

> "How long since the **previous** photo?"

- 3 minutes? Same moment.
- 4 hours? That's a **new** moment.

That's it. Each photo only looks at **one** neighbour, the one right before it. Yet the whole gallery ends up neatly grouped.

Data people call this pattern **gaps and islands**. The **islands** are the runs of close-together rows. The **gaps** are the long pauses between them. Sessionization is gaps and islands, with "30 minutes" as the definition of a long pause.

Hold on to three ideas from the gallery:

- **Sort first.** A photo has to compare itself with the photo *before it in time*, not before it in the folder.
- **Each person has their own gallery.** Your photos never split someone else's moments.
- **The first photo always starts a moment.** There's nothing before it to compare with.

All three show up in the code.

---

## What We're Working With 📥

Here's the input: the output of `flatten_events` from Post 04, sorted so you can read it by actor.

```python
flat = flatten_events(read_events(spark, "data/events.jsonl"))
flat.orderBy("actor_login", "created_ts", "event_id").show(truncate=False)
```

```
+--------+----------------+-------------------+----------+-------+-----------+
|event_id|event_type      |created_ts         |event_date|repo_id|actor_login|
+--------+----------------+-------------------+----------+-------+-----------+
|e09     |pushevent       |2024-03-01 10:00:00|2024-03-01|101    |null       |
|e01     |pushevent       |2024-03-01 09:50:00|2024-03-01|101    |dave       |
|e02     |pullrequestevent|2024-03-01 10:10:00|2024-03-01|202    |dave       |
|e03     |issuesevent     |2024-03-01 10:40:00|2024-03-01|101    |dave       |
|e04     |pushevent       |2024-03-01 11:20:00|2024-03-01|101    |dave       |
|e05     |pushevent       |2024-03-01 11:20:00|2024-03-01|202    |dave       |
|e06     |pushevent       |2024-03-01 10:15:00|2024-03-01|202    |jim        |
|e07     |issuesevent     |2024-03-01 10:35:00|2024-03-01|202    |jim        |
|e08     |pushevent       |2024-03-01 12:30:00|2024-03-01|999    |jim        |
+--------+----------------+-------------------+----------+-------+-----------+
```

(Spark sorts nulls **first** in ascending order, which is why e09 leads.)

Four rows in that table are the whole reason this post exists:

| Row | What's special | Which trap it tests |
|---|---|---|
| **e03** | Exactly **30 minutes** after e02 | `>` vs `>=` |
| **e04, e05** | Same second, `11:20:00`, and e05 comes **first** in the file | Tie-breaker |
| **e01, e06** | First event for each actor. Nothing before them | The first-row branch |
| **e09** | `actor_login` is **null** | Null partition keys |

The lab's test data was written to hit every one of them. So will we.

---

## The Four-Step Recipe 🧑‍🍳

Every gaps-and-islands problem, in any SQL engine, in any company, gets solved the same way:

1. **Order** each actor's rows by time, with a tie-breaker.
2. **Look back** with `lag` to get the previous row's time, and compute the gap in seconds.
3. **Flag** the start of each new session: `1` if there's no previous row **or** the gap is over the limit, else `0`.
4. **Number** the sessions with a **running sum** of the flags.

Plus a **step 0** that's specific to our data: drop events with no actor.

![The four-step recipe applied to Dave's five events: order by created_ts and event_id, lag to get prev_ts and gap_s, flag the first row and the 2400-second gap, then a running sum gives session ids 1, 1, 1, 2, 2](content/data-engineering/images/sessionize_four_steps.svg)

Step 4 is the clever one. Read the flags column top to bottom: `1, 0, 0, 1, 0`. Now keep a running total: `1, 1, 1, 2, 2`. **The running total is the session number.** Every `1` bumps the counter. Every `0` inherits the number above it.

> **Key insight:** You can't number islands directly, because no single row knows which island it's in. But every row **can** know whether it **starts** an island, by looking at one neighbour. A running sum turns "where islands start" into "which island am I in".

Now let's build each step for real.

---

## Step 0: Drop Events With No Actor 🚫

e09 has `actor_login = null`. Why not just let it through?

Because `partitionBy("actor_login")` treats **null as a value**. Every null-login event lands in **one** partition, together. Here there's only e09, so it would quietly become "session 1 of actor null". With a hundred anonymous events from fifty different people, you'd get one giant fake person whose "sessions" mix strangers' work.

| Option | What happens to e09 | Problem |
|---|---|---|
| Keep it | Gets `session_id = 1` under actor `null` | A session for **nobody**. Inflates Post 09's summary |
| Group by `actor.id` instead | Gets a session under actor 3 | The spec groups by **login**, and `flatten_events` doesn't even carry `actor.id` |
| **Filter it out** ✅ | Removed before the window | Matches the spec: no login, no session |

```python
with_actor = flat.filter(F.col("actor_login").isNotNull())
print(flat.count(), with_actor.count())
```

```
9 8
```

> **Trap:** `F.col("actor_login") != None` looks like the same filter. It isn't. As [Post 02](content/data-engineering/02-spark-from-first-principles.md) showed, it compiles to `actor_login != NULL`, which is **null for every row**, so `filter` drops all nine. Always `.isNotNull()`.

> **Why filter first, not last?** If you filter **after** the window, e09 has already been through `lag` and the running sum in its own partition. The final rows come out the same, but it's wasted work, and a filter tacked on at the end is the one that gets forgotten. Remove what doesn't belong **before** you compute over it.

---

## Step 1: Order, With a Tie-Breaker 📏

```python
w = Window.partitionBy("actor_login").orderBy("created_ts", "event_id")
```

`partitionBy("actor_login")` is the "each person has their own gallery" rule. Jim's 10:15 push never splits Dave's morning.

`orderBy("created_ts", ...)` sorts by **time**, not by file position. Remember the file has e05 **before** e04.

`..., "event_id")` is the tie-breaker. e04 and e05 both happened at `11:20:00`. Without a second sort column, Spark is free to put them in either order, and it may choose differently on different runs ([Post 05](content/data-engineering/05-window-functions.md)'s determinism rule). With it, `"e04" < "e05"`, so e04 always comes first.

> **Why does that order matter if they're in the same session anyway?** Their `session_id` doesn't change. But which one is the **first event of session 2** does. Post 09 picks `primary_repo_at_session_start` from that first event: e04 (repo 101, `alpha-service`) versus e05 (repo 202, `beta-web`). Get the order wrong here and the summary is wrong there.

---

## Step 2: Look Back With `lag` ⏪

```python
prev_ts = F.lag("created_ts").over(w)
gap_s   = F.col("created_ts").cast("double") - prev_ts.cast("double")
```

`lag("created_ts")` hands each row the timestamp of the row **before it in its window**. Casting a timestamp to `double` gives **seconds since the epoch**, so subtracting two of them gives the gap in seconds.

Let's look at it before we use it:

```python
(with_actor
 .select("event_id", "actor_login", "created_ts",
         prev_ts.alias("prev_ts"), gap_s.alias("gap_s"))
 .orderBy("actor_login", "created_ts", "event_id")
 .show(truncate=False))
```

```
+--------+-----------+-------------------+-------------------+------+
|event_id|actor_login|created_ts         |prev_ts            |gap_s |
+--------+-----------+-------------------+-------------------+------+
|e01     |dave       |2024-03-01 09:50:00|null               |null  |
|e02     |dave       |2024-03-01 10:10:00|2024-03-01 09:50:00|1200.0|
|e03     |dave       |2024-03-01 10:40:00|2024-03-01 10:10:00|1800.0|
|e04     |dave       |2024-03-01 11:20:00|2024-03-01 10:40:00|2400.0|
|e05     |dave       |2024-03-01 11:20:00|2024-03-01 11:20:00|0.0   |
|e06     |jim        |2024-03-01 10:15:00|null               |null  |
|e07     |jim        |2024-03-01 10:35:00|2024-03-01 10:15:00|1200.0|
|e08     |jim        |2024-03-01 12:30:00|2024-03-01 10:35:00|6900.0|
+--------+-----------+-------------------+-------------------+------+
```

Three things to notice:

- **e01 and e06** have `prev_ts = null`. Each is the first row in its partition. That null **means something**: "I start a sequence".
- **e03**'s gap is **exactly 1800.0**. Our boundary case.
- **e05**'s gap is **0.0**. It sits right after e04, at the same instant. Thanks to the tie-breaker, it's e05 that gets the 0, every run.

### Why `double` and not `long`?

| Cast | `10:40:00.000` minus `10:10:00.000` | `10:40:00.600` minus `10:10:00.000` | New session at > 1800? |
|---|---|---|---|
| `cast("long")` | 1800 | **1800** (fraction dropped) | No ❌ |
| `cast("double")` | 1800.0 | **1800.6** | Yes ✅ |

`cast("long")` drops fractions of a second. A gap of 1800.6 seconds **is** strictly more than 30 minutes, but as a `long` it rounds down to 1800 and slips into the old session. Our sample has whole seconds, so both casts agree here. Real event streams carry milliseconds. `double` keeps them.

> **Why not `F.unix_timestamp`?** It also returns whole seconds (a `long`), so it has the same problem. Cast to `double`.

---

## Step 3: Flag the Start of Each Session 🚩

```python
is_new_session = F.when(prev_ts.isNull() | (gap_s > 1800), 1).otherwise(0)
```

Two reasons to start a session, joined with `|` (never Python's `or`), each side in parentheses:

- `prev_ts.isNull()`: I'm the first event for this actor.
- `gap_s > 1800`: the pause before me was **strictly** longer than 30 minutes.

That first branch looks redundant. It isn't. Here's what happens without it.

### Trap: forgetting the first row

For e01, `gap_s` is null. And `null > 1800` is **null**, not true. `F.when` treats null like false, so the row falls through to `.otherwise(0)`.

| Flag expression | Dave's flags | Dave's session ids | Jim's session ids |
|---|---|---|---|
| `when(gap_s > 1800, 1)` | 0, 0, 0, 1, 0 | **0, 0, 0, 1, 1** ❌ | **0, 0, 1** ❌ |
| `when(prev_ts.isNull() \| (gap_s > 1800), 1)` | 1, 0, 0, 1, 0 | **1, 1, 1, 2, 2** ✅ | **1, 1, 2** ✅ |

Numbering starts at **0**. No error, no warning, and every session id is off by one. Any test checking for session 1 fails, and any join to "session 1" in Post 09 silently misses.

> **Key insight:** That's three-valued logic from Post 02 again. Any comparison with null is null. When the null **means something** (here: "there is no previous row"), handle it with its own explicit branch.

### Trap: `>` versus `>=`

The spec says **strictly greater than**. e03 is exactly on the line:

| Boundary | e03's gap 1800 > limit? | Dave's session ids | Sessions for Dave |
|---|---|---|---|
| `gap_s > 1800` ✅ | No | 1, 1, **1**, 2, 2 | 2 |
| `gap_s >= 1800` ❌ | Yes | 1, 1, **2**, 3, 3 | 3 |

One character, and Dave's first session splits in two. His 09:50 to 10:40 block becomes 09:50 to 10:10, plus a one-event session at 10:40. Product's headline example breaks.

> **Trap:** When a spec says "more than 30 minutes", "over 30 minutes" or "exceeds 30 minutes", that's `>`. When it says "30 minutes or more", that's `>=`. Read the words. Then write a test with a gap of **exactly** the limit, because that's the only row where the two disagree.

![Timeline of Dave's and Jim's events: Dave's e01, e02 and e03 form session 1 (gaps 20 and exactly 30 minutes), a 40-minute gap starts session 2 for e04 and e05; Jim's e06 and e07 are session 1, a 115-minute gap starts session 2 for e08; e09 with no login is filtered out](content/data-engineering/images/sessions_gaps_and_islands.svg)

---

## Step 4: Number the Islands With a Running Sum 🔢

```python
running = w.rowsBetween(Window.unboundedPreceding, Window.currentRow)
session_id = F.sum("is_new_session").over(running).cast("int")
```

From the first row of the partition up to **this** row, add up the flags. That's the session number.

### Why a running sum, and not `row_number` or `dense_rank`?

| Function | Dave's result | Why |
|---|---|---|
| `row_number()` | 1, 2, 3, 4, 5 | Counts **rows**, not islands |
| `dense_rank()` over `created_ts` | 1, 2, 3, 4, 4 | Ranks **timestamps**, not islands |
| `dense_rank()` over "the island" | (can't write it) | You'd need a column that's already the same within each island. That column **is** the answer |
| **`sum(is_new_session)`** running | **1, 1, 1, 2, 2** ✅ | Counts how many islands have **started** so far |

### Why `rowsBetween`?

Post 05 showed that `.over(w)` with no frame uses the **range** frame, which lumps tied rows together. Here's a subtle thing: in **this** recipe, the two frames happen to agree. Our order includes `event_id`, so no two rows tie. And even if you ordered by `created_ts` alone, the tied row (e05) has a gap of 0, so it's never flagged, and adding its 0 changes nothing.

Write `rowsBetween` anyway:

- It says what you mean: "this row and every row before it".
- It doesn't depend on a coincidence that a later edit (a different flag rule, a different order) could break.
- Being explicit costs nothing.

### Why `.cast("int")`?

`F.sum` over integers returns a **long** (`bigint`). The spec says `session_id` is an `int`. Tests compare schemas, and so do downstream tables. One cast fixes it:

```python
flags = with_actor.withColumn("is_new_session", is_new_session)

print(flags.withColumn("session_id", F.sum("is_new_session").over(running)).dtypes[-1])  # no cast
print(flags.withColumn("session_id", session_id).dtypes[-1])                             # .cast("int")
```

```
('session_id', 'bigint')
('session_id', 'int')
```

---

## `sessionize_actor_events`: The Full Function 🛠️

Put the five steps together:

```python
from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F

SESSION_GAP_SECONDS = 30 * 60   # 1800: a gap must be STRICTLY greater to start a new session


def sessionize_actor_events(events: DataFrame) -> DataFrame:
    """Assign a per-actor session_id: a new session starts after a gap > 30 minutes."""
    w = (Window
         .partitionBy("actor_login")                     # each actor has their own timeline
         .orderBy("created_ts", "event_id"))             # time order; event_id breaks same-second ties

    prev_ts = F.lag("created_ts").over(w)                # previous event's time, null for the first
    gap_s = F.col("created_ts").cast("double") - prev_ts.cast("double")   # seconds, fractions kept

    return (events
        .filter(F.col("actor_login").isNotNull())        # step 0: no login, no session (drops e09)
        .withColumn("is_new_session",                    # step 3: first row OR gap strictly > 1800
            F.when(prev_ts.isNull() | (gap_s > SESSION_GAP_SECONDS), 1).otherwise(0))
        .withColumn("session_id",                        # step 4: running count of session starts
            F.sum("is_new_session")
             .over(w.rowsBetween(Window.unboundedPreceding, Window.currentRow))
             .cast("int"))
        .drop("is_new_session"))                         # helpers never leave the function
```

Notice `prev_ts` and `gap_s` are **column expressions**, not data. They're defined once, up top, and evaluated inside `withColumn`, **after** the filter. So e09 never enters the window at all.

Run it on the lab data:

```python
sessions = sessionize_actor_events(flat)

(sessions
 .select("event_id", "actor_login", "created_ts", "repo_id", "session_id")
 .orderBy("actor_login", "created_ts", "event_id")
 .show(truncate=False))
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

That's the course lab's expected `sessionize_actor_events` output, row for row.

```python
print(sessions.columns)
print(sessions.count())
```

```
['event_id', 'event_type', 'created_ts', 'event_date', 'repo_id', 'actor_login', 'session_id']
8
```

All six columns from `flatten_events`, plus `session_id`. No `prev_ts`, no `gap_s`, no `is_new_session`. 9 rows in, 8 out: only e09 is gone.

### Read it back like Product would

| Actor | Session | From | To | Events | Why it ended |
|---|---|---|---|---|---|
| Dave | 1 | 09:50 | 10:40 | e01, e02, e03 | 40-minute pause before e04 |
| Dave | 2 | 11:20 | 11:20 | e04, e05 | End of data |
| Jim | 1 | 10:15 | 10:35 | e06, e07 | 115-minute pause before e08 |
| Jim | 2 | 12:30 | 12:30 | e08 | End of data |

"Dave worked from 09:50 to 10:40 and touched 2 repos" (101 and 202). There's Product's sentence, in data. Post 09 will compute it with `groupBy`.

---

## What Each Line Protects You From 🛡️

| Line | Remove it and… |
|---|---|
| `.filter(F.col("actor_login").isNotNull())` | e09 becomes "session 1 of nobody" |
| `partitionBy("actor_login")` | Jim's events split Dave's sessions. One global timeline |
| `orderBy("created_ts", ...)` | Spark refuses `lag` over an unordered window. Order by anything but time and gaps come out wrong, or negative |
| `..., "event_id")` | e04 vs e05 order flips between runs. Post 09's first-event pick flips with it |
| `.cast("double")` | Gaps of 1800.6 s round to 1800 and stay in the session |
| `prev_ts.isNull() \|` | Session numbering starts at 0 |
| `> SESSION_GAP_SECONDS` (not `>=`) | e03 starts its own session. Dave gets 3 sessions |
| `rowsBetween(...)` | Correct today by coincidence. Fragile tomorrow |
| `.cast("int")` | `session_id` is `bigint`. Schema checks fail |
| `.drop("is_new_session")` | A helper column leaks into enrich and the summary |

---

## Quick Reference ✅

- [ ] Drop null actors **before** the window, with `.isNotNull()`
- [ ] `Window.partitionBy("actor_login").orderBy("created_ts", "event_id")`
- [ ] `prev_ts = F.lag("created_ts").over(w)`
- [ ] Gap in seconds with `cast("double")`, not `long`, not `unix_timestamp`
- [ ] Flag: `prev_ts.isNull() | (gap_s > 1800)`: strict `>`, explicit first-row branch
- [ ] Number: `F.sum(flag)` over `rowsBetween(unboundedPreceding, currentRow)`
- [ ] `.cast("int")` on `session_id`
- [ ] Drop every helper column before returning
- [ ] Test row: a gap of **exactly** the limit (e03)
- [ ] Test rows: two events in the **same second** (e04, e05)

---

## Quick Quiz 🧠

**Q1.** Jim does one more thing: **e10**, a push at **11:05:00**. With the spec's rule, what are the session ids for e06, e07, e10 and e08?

<details>
<summary>Show answer</summary>

**1, 1, 1, 2.** e10 is exactly 30 minutes (1800 s) after e07 at 10:35, and 1800 is not `> 1800`, so it stays in session 1. e08 at 12:30 is now 85 minutes (5100 s) after e10, so it still starts session 2. Adding e10 changed Jim's session 1 end time, not his session count.

</details>

**Q2.** A teammate writes the flag as `F.when(gap_s > 1800, 1).otherwise(0)`. What session ids does Dave get, and why?

<details>
<summary>Show answer</summary>

**0, 0, 0, 1, 1.** For e01, `gap_s` is null, `null > 1800` is null, and `F.when` sends null to `.otherwise(0)`. So the first session is numbered 0, and every later one is off by one. Fix: add the explicit `prev_ts.isNull() |` branch.

</details>

**Q3.** Two events from Dave are 1800.4 seconds apart. Using `cast("long")` for the gap, are they in the same session? Using `cast("double")`?

<details>
<summary>Show answer</summary>

With `cast("long")`, both timestamps lose their fractions. Depending on where the fraction falls, the gap comes out as 1800 or 1801. When it's 1800, the second event stays in the old session, even though the real gap of 1800.4 s **is** strictly more than 30 minutes. With `cast("double")`, the gap is 1800.4, `1800.4 > 1800` is true, and a new session starts every time. `double` gives the right answer regardless of the fractions.

</details>

**Q4.** Why is e09 dropped in `sessionize_actor_events`, and not left for Post 09's summary to ignore?

<details>
<summary>Show answer</summary>

`partitionBy("actor_login")` would put every null-login event into **one** partition and give them sessions as if they were one person. That's invented data. Every later step (the enrich join, the summary) would carry it along. Filter at the first step that needs the actor, before the window, so nothing downstream has to remember to clean it up. It also means enrich in Post 08 receives 8 rows, not 9.

</details>

**Q5.** Why can't you get session ids with `F.dense_rank().over(w)`?

<details>
<summary>Show answer</summary>

`dense_rank` gives tied rows the same rank, based on the **order-by value**. Ordered by `created_ts`, Dave gets 1, 2, 3, 4, 4: it ranks timestamps, not sessions. To rank sessions, you'd need a column that's already the same for every row in a session. That column **is** the session id. The running sum of "new session" flags is how you build it.

</details>

---

## What's Next? 🚀

Every event now knows **who** did it and **which session** it belongs to. And from Post 06, every repo knows **what it was** at any instant. Time to bring the two together.

👉 **[Post 08 — Point-in-Time Joins](content/data-engineering/08-point-in-time-joins.md)** — `enrich_with_repo_state` in full: a left range join on `[valid_from, valid_to)` with the `valid_to IS NULL` branch, why e02, e06 and e08 come back with null repo details, and how to prove the row count never changes.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
