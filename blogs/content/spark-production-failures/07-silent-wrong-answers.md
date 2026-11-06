---
title: "Silent Wrong Answers — When the Job Succeeds and the Numbers Lie"
date: 2026-11-06
tags: [spark, pyspark, debugging, data-quality, joins, null, timezone, production-failures]
description: The scariest Spark failures never crash. Reproduce five silent wrong answers on RepoSphere's nine events — a join that fans 9 rows into 21, a != None that deletes everything, a join that quietly drops e09, a PUSHEVENT that slips past a filter, and a session time zone that moves the clock — then add the row-count reconciliation that catches all of them.
---

# The Job That Succeeded and Was Wrong 🎭

In [Post 06](content/spark-production-failures/06-bad-data-and-schema-drift.md), bad input made Spark **complain**: a corrupt line landed in `_corrupt_record`, a drifted schema produced nulls you could count. Loud, ugly, fixable.

Today is the opposite. The job finishes. The Spark UI is green. No stack trace, no retry, no page at 3 a.m. And on Thursday somebody in Finance says:

> *"Dave's activity is up 160% this week. What happened?"*

Nothing happened. Your **join** happened.

A silent wrong answer is the most expensive failure in data engineering, because nothing tells you to start debugging. You find out when a human distrusts a number, usually weeks late, usually in a meeting.

So this post is a bit different. Every other post in this series starts from an error message. This one starts from a **number that looks fine** and teaches you to catch it before anyone else does.

---

## The Broken Scale Analogy ⚖️

Picture a bathroom scale that reads **2 kg heavy**. It never crashes. It never shows an error. Every morning it gives you a confident number.

You'd only notice if you did one of two things:

- stood on it **holding a known weight** (a test with a known answer), or
- weighed yourself on **a second scale** (a reconciliation).

Spark pipelines need both habits. Our RepoSphere sample is the known weight: nine events, a hand-checkable answer for every step. And the reconciliation is a few lines of counting.

| Scale | Pipeline |
|---|---|
| The known weight | The nine-event sample and its answer key |
| The second scale | Row counts and distinct counts compared **between stages** |
| Reads 2 kg heavy, silently | A join that fans out, a filter that matches nothing |

---

## The Five Silent Failures at a Glance 🔭

Each one is a different mechanism. None of them throws.

| # | Symptom you'd notice | Root cause | Caught by |
|---|---|---|---|
| 1 | Counts too **high** | Join fan-out: one key matches many rows | Row count before vs after the join |
| 2 | Counts too **low**, or zero | `!= None`, or a null join key | Null counts, anti join on the key |
| 3 | A filter matches **fewer** rows than it should | `PUSHEVENT` vs `PushEvent` | Distinct values of the column |
| 4 | Times and dates **off by hours** | Session time zone | Pin the time zone, print one known row |
| 5 | You find out **last** | No reconciliation | Stage-to-stage count checks |

We'll take them in order. Each section follows the same shape: **symptom, what you see, root cause, fix, how to verify.**

---

## 1. The Fan-Out: 9 Rows In, 21 Rows Out 📈

**Symptom.** Every per-actor count is two or three times too big. Nothing errors.

**The setup.** We want each event next to the changes recorded for its repo. The innocent version:

```python
events  = read_events(spark, "data/events.jsonl")
changes = read_repo_changes(spark, "data/repo_changes.jsonl")
flat    = flatten_events(events)

joined = flat.join(changes.select("repo_id", "change_id"), "repo_id", "left")
print(flat.count(), joined.count())
```

```
9 21
```

Nine events went in. **Twenty-one** came out. Spark didn't warn you, because a join that multiplies rows is a perfectly valid join.

**What you see.** Count events per actor, before and after:

```python
flat.groupBy("actor_login").count().orderBy("actor_login").show(truncate=False)
joined.groupBy("actor_login").count().orderBy("actor_login").show(truncate=False)
```

```
+-----------+-----+
|actor_login|count|
+-----------+-----+
|null       |1    |
|dave       |5    |
|jim        |3    |
+-----------+-----+
```

```
+-----------+-----+
|actor_login|count|
+-----------+-----+
|null       |3    |
|dave       |13   |
|jim        |5    |
+-----------+-----+
```

Dave went from 5 events to 13. That's the "up 160%" from the meeting. Nothing about Dave changed.

**Root cause.** The key `repo_id` is **not unique** on the right side. Repo 101 has three changes (`c1`, `c2`, `c3`) and repo 202 has two (`c4`, `c5`). Every event is copied once per matching row:

| repo_id | Events on the left | Rows on the right | Rows out |
|---|---|---|---|
| 101 | 4 (`e01`, `e03`, `e04`, `e09`) | 3 | 4 × 3 = **12** |
| 202 | 4 (`e02`, `e05`, `e06`, `e07`) | 2 | 4 × 2 = **8** |
| 999 | 1 (`e08`) | 0 (left join keeps it, nulls) | **1** |
| **Total** | **9** | | **21** |

![A join on a non-unique key multiplies each left row by the number of matches on the right: 4 times 3 plus 4 times 2 plus 1 gives 21 rows from 9 events](content/spark-production-failures/images/join_fan_out.svg)

> **Key insight:** Row count after a join = the sum, over keys, of *left rows × right rows*. If the right side isn't unique on the join key, the output **must** grow. Spark can't know that's not what you meant.

**Fix.** Make the right side **unique on the key**, or add the time condition that picks exactly one row. For RepoSphere that is the point-in-time join from [Post 08 of the first series](content/data-engineering/08-point-in-time-joins.md): join on `repo_id` **and** `valid_from <= created_ts < valid_to`. Eight events go in, eight come out.

**How to verify.** Never ship a join without this guard:

```python
def assert_same_rows(name: str, before: DataFrame, after: DataFrame) -> None:
    b, a = before.count(), after.count()
    if a != b:
        raise AssertionError(f"{name}: {b} rows in, {a} rows out")
```

Run it on the naive join and the job **fails loudly** instead of lying quietly: `assert_same_rows("repo join", flat, joined)` raises `repo join: 9 rows in, 21 rows out`.

> **Trap:** `distinct()` after the join "fixes" the count only when the duplicated rows are identical. Here, each copy carries a different `change_id`, so `distinct()` removes nothing. Fix the **join**, not the symptom.

---

## 2. Nulls That Delete Rows 🕳️

Two different bugs, one root cause: `NULL` is not a value, it is "unknown", and unknown never equals anything.

### 2a. The `!= None` filter

**Symptom.** A filter that should keep most rows returns nothing. The job succeeds with an empty output.

```python
flat.filter(F.col("actor_login") != None).count()
```

```
0
```

**Root cause.** `actor_login != NULL` is `NULL` for every row, and `filter` keeps only rows where the condition is `true`. This is the three-valued logic from [Post 02 of the first series](content/data-engineering/02-spark-from-first-principles.md), and it fails the same way in production.

**Fix and verify.**

```python
flat.filter(F.col("actor_login").isNotNull()).count()
```

```
8
```

Eight, because e09 has no login. Nine minus one, exactly what you'd predict by reading `events.jsonl`.

There's a quieter cousin. Ask for "everything **not** by Dave":

```python
flat.filter(F.col("actor_login") != "dave").count()
```

```
3
```

Three: `e06`, `e07`, `e08`, all Jim's. But e09 also wasn't by Dave. It was by *nobody known*, and `NULL != 'dave'` is `NULL`, so e09 vanished. If "not Dave" should include it, say so explicitly:

```python
flat.filter((F.col("actor_login") != "dave") | F.col("actor_login").isNull()).count()
```

```
4
```

### 2b. The join key that is null

**Symptom.** Row counts drop by a few after a join. No error.

Say we join to a small lookup of known actors. We invent this table just for the demo:

```python
actors = spark.createDataFrame([("dave", "platform"), ("jim", "web")], ["actor_login", "team"])

print(flat.count(), flat.join(actors, "actor_login").count())
```

```
9 8
```

**What you see.** One event is gone. Find out which with a **left anti join**, which returns the left rows that found no match:

```python
flat.join(actors, "actor_login", "left_anti").select("event_id", "actor_login").show(truncate=False)
```

```
+--------+-----------+
|event_id|actor_login|
+--------+-----------+
|e09     |null       |
+--------+-----------+
```

**Root cause.** `NULL = NULL` is not true, so a null key matches nothing, and an inner join drops the row.

**Fix.** Decide on purpose. In the series pipeline, [dropping e09 is deliberate](content/data-engineering/07-sessionization-gaps-and-islands.md) and documented. The bug is when **nobody decided**. Use a left join if you must keep the row, and count the unmatched keys:

| Choice | When it's right |
|---|---|
| Inner join, drop the null-key rows | You can't attribute them and have said so in the code |
| Left join, keep them with null details | Downstream still needs the event itself |
| `eqNullSafe` in the join condition | You really want `NULL` to match `NULL` (rare, and surprising to readers) |

> **Why `left_anti`?** It is the one-line answer to "which rows did my join lose?" Run it after any inner join you don't fully trust.

---

## 3. The Filter That Matched Too Little 🔤

**Symptom.** "How many push events did we get?" The answer is lower than the people who generated them expect.

Look at the raw file. Event `e04` has this type:

```
"event_type":"PUSHEVENT"
```

Every other push is `PushEvent`. Count pushes on the raw read:

```python
events.filter(F.col("event_type") == "PushEvent").count()
```

```
5
```

Five. The truth is six: `e01`, `e04`, `e05`, `e06`, `e08`, `e09`. Equality on strings is **case sensitive**, so `PUSHEVENT` slipped past.

Now the twist. `flatten_events` lower-cases the column ([Post 04 of the first series](content/data-engineering/04-flattening-and-timestamps.md)). So after flattening, the *same* filter is wrong in a new way:

```python
flat.filter(F.col("event_type") == "PushEvent").count()
```

```
0
```

Zero, because nothing is called `PushEvent` any more. The right filter is against the normalised value:

```python
flat.filter(F.col("event_type") == "pushevent").count()
```

```
6
```

**Root cause.** The comparison value doesn't match the data's actual spelling, and Spark treats a filter that matches nothing as a successful filter.

**Verify the habit.** Before you filter on a categorical column, look at what is really in it:

```python
flat.groupBy("event_type").count().orderBy("event_type").show(truncate=False)
```

```
+----------------+-----+
|event_type      |count|
+----------------+-----+
|issuesevent     |2    |
|pullrequestevent|1    |
|pushevent       |6    |
+----------------+-----+
```

Three distinct values and counts that sum to 9. If a spelling you expected is missing from that list, you've found your bug before it found you.

---

## 4. The Clock That Moved ⏰

**Symptom.** Daily numbers are off, but only for events near midnight, and only in some environments. The classic "works on my laptop, wrong on the cluster."

**Root cause.** A Spark `timestamp` is an **instant**, but Spark *displays* it, and takes `to_date` of it, in the **session time zone**, `spark.sql.session.timeZone`. If your laptop, your cluster and your scheduler disagree on that setting, the same instant lands on different dates.

Our events carry a `Z` (UTC) suffix, so the **instant** is always right. Watch only the display change:

```python
spark.conf.set("spark.sql.session.timeZone", "America/Los_Angeles")

(flat.filter(F.col("event_id").isin("e01", "e02", "e03"))
     .select("event_id", "created_ts", "event_date")
     .orderBy("event_id")
     .show(truncate=False))
```

```
+--------+-------------------+----------+
|event_id|created_ts         |event_date|
+--------+-------------------+----------+
|e01     |2024-03-01 01:50:00|2024-03-01|
|e02     |2024-03-01 02:10:00|2024-03-01|
|e03     |2024-03-01 02:40:00|2024-03-01|
+--------+-------------------+----------+
```

The same `e01` that read `09:50` in [Post 04 of the first series](content/data-engineering/04-flattening-and-timestamps.md) now reads `01:50`. In March 2024, Los Angeles is eight hours behind UTC. It is the same instant, shown on a different wall clock.

All nine sample events happen to stay on 1 March in this zone, so the data won't show you a **date** move. A real dataset will. Here is a **hypothetical** event, not in our files, at `2024-03-01T23:30:00Z`:

| Session time zone | `created_ts` shown | `event_date` |
|---|---|---|
| `UTC` | 2024-03-01 23:30:00 | **2024-03-01** |
| `America/Los_Angeles` | 2024-03-01 15:30:00 | 2024-03-01 |
| `Asia/Kolkata` | 2024-03-02 05:00:00 | **2024-03-02** |

Group by `event_date` in two environments and the same event lands in two different days' totals.

There is a second, sharper edge: **strings without a zone**. Parsing `2024-03-01 09:50:00` has no `Z` to anchor it, so Spark reads it *in the session time zone*, and the **instant itself** changes:

```python
def epoch(tz: str) -> int:
    spark.conf.set("spark.sql.session.timeZone", tz)
    return (spark.range(1)
                 .select(F.to_timestamp(F.lit("2024-03-01 09:50:00")).cast("long"))
                 .first()[0])

print(epoch("America/Los_Angeles") - epoch("UTC"))
```

```
28800
```

28,800 seconds is exactly eight hours. Same text, two different moments.

**Fix.** Pin it once, at session start, in every environment, and say why:

```python
spark.conf.set("spark.sql.session.timeZone", "UTC")   # one clock for the whole pipeline
```

**Verify.** Print one known row (`e01` must read `09:50:00` and `2024-03-01`) as the first line of your run log. If it doesn't, stop.

> **Trap:** Don't "fix" this by adding or subtracting hours in the data. The instant was right all along. Fix the **display setting** and the stored values stay correct.

---

## 5. The Safety Net: Reconcile Between Stages 🧮

The four bugs above share a property: each one changes a **count** somewhere. That makes counts your cheapest detector.

Here is the whole idea in one function. It states how many rows you *expect* each stage to lose, and fails if reality disagrees:

```python
def check_rows(name: str, before: DataFrame, after: DataFrame, expected_drop: int = 0) -> None:
    b, a = before.count(), after.count()
    ok = (b - a == expected_drop)
    print(f"{name:<26}{b} -> {a}   expected drop {expected_drop}   {'OK' if ok else 'MISMATCH'}")
    if not ok:
        raise AssertionError(f"{name}: expected to lose {expected_drop} rows, lost {b - a}")
```

Wire it between the RepoSphere stages, using the known answers from the first series:

```python
flat      = flatten_events(read_events(spark, "data/events.jsonl"))
sessions  = sessionize_actor_events(flat)
enriched  = enrich_with_repo_state(sessions, build_repo_scd2(read_repo_changes(spark, "data/repo_changes.jsonl")))

check_rows("flatten_events",           read_events(spark, "data/events.jsonl"), flat)
check_rows("sessionize_actor_events",  flat,     sessions, expected_drop=1)   # e09, no login
check_rows("enrich_with_repo_state",   sessions, enriched)
```

```
flatten_events            9 -> 9   expected drop 0   OK
sessionize_actor_events   9 -> 8   expected drop 1   OK
enrich_with_repo_state    8 -> 8   expected drop 0   OK
```

![A funnel of row counts between RepoSphere stages: 9 raw, 9 flattened, 8 sessionized because e09 has no login, 8 enriched; each arrow carries an expected-drop check](content/spark-production-failures/images/reconciliation_funnel.svg)

Swap in the naive join from section 1 and the third line becomes an `AssertionError` instead of a mystery in a meeting. Notice the design: the one drop we **expect** (e09) is written down in the code. A reviewer can see that the loss is deliberate.

Two more one-liners worth adding:

```python
flat.count() == flat.select("event_id").distinct().count()          # key is unique: 9 == 9
flat.filter(F.col("actor_login").isNull()).count()                    # nulls on purpose: 1
```

---

## The Silent-Failure Triage Table 🩺

When a number looks wrong but nothing failed, ask these in order:

| Question | How to answer it | Points at |
|---|---|---|
| Did a join change the row count? | `count()` before and after | Fan-out (1) |
| Did rows go missing? | `left_anti` join on the key | Null or unmatched keys (2b) |
| Did a filter return 0 or too few? | `groupBy(col).count()` on the filtered column | Spelling or `!= None` (2a, 3) |
| Are boundary days off? | Print one known row in each environment | Time zone (4) |
| Which stage first disagrees with the answer key? | `check_rows` between stages | The guilty step (5) |

---

## Quick Quiz 🧠

**Q1.** `flat` has 9 events. You left-join it to `repo_changes` on `repo_id` alone and get 21 rows. Where does 21 come from?

<details>
<summary>Show answer</summary>

Per repo, rows out = events × matches. Repo 101: 4 events × 3 changes = 12. Repo 202: 4 events × 2 changes = 8. Repo 999 has no changes, but a left join keeps `e08` with nulls: 1. Total 12 + 8 + 1 = **21**.

</details>

**Q2.** Why does `flat.filter(F.col("actor_login") != None).count()` return `0` instead of `8`?

<details>
<summary>Show answer</summary>

It builds `actor_login != NULL`, and any comparison with `NULL` is `NULL`, not `true`. `filter` keeps only rows where the condition is `true`, so every row is dropped. Use `isNotNull()`, which returns **8** because e09 has no login.

</details>

**Q3.** An inner join of `flat` to a lookup of known actors returns 8 rows instead of 9. How do you find the missing row, and why did it go?

<details>
<summary>Show answer</summary>

Run the same join as `left_anti`. It returns `e09`, whose `actor_login` is `null`. A null key is never equal to anything, including another null, so the inner join found no match and dropped the row.

</details>

**Q4.** `events.filter(F.col("event_type") == "PushEvent").count()` gives 5 on the raw data. The truth is 6. What happened, and what does the same filter return after `flatten_events`?

<details>
<summary>Show answer</summary>

`e04` is spelled `PUSHEVENT`, and string equality is case sensitive. After `flatten_events` lower-cases the column, nothing is called `PushEvent`, so the filter returns **0**. The correct filter on flattened data is `== "pushevent"`, which returns **6**.

</details>

**Q5.** `to_timestamp("2024-03-01 09:50:00")` returns a different instant on two clusters. Why, and what is the fix?

<details>
<summary>Show answer</summary>

The string has no zone, so Spark interprets it in `spark.sql.session.timeZone`, and the two clusters have different settings. For Los Angeles versus UTC the instants differ by 28,800 seconds (eight hours). Pin the session time zone to `UTC` at session start in every environment, and print a known row to confirm.

</details>

---

## What's Next? 🚀

You now have a detector for the failures that never page you: **count between stages**, **anti join on the key**, **look at distinct values before filtering**, and **pin the clock**.

The last post in this series moves from the pipeline to the **table**. Two jobs write to the same Iceberg table, one of them fails with a commit error, and then a cleanup job deletes a file that a query still needed.

👉 **[Post 08 — Iceberg Commit Conflicts and Missing Files](content/spark-production-failures/08-iceberg-commit-conflicts-and-missing-files.md)**: reading `CommitFailedException` and `ValidationException`, why concurrent writers collide, and how a too-eager `remove_orphan_files` corrupts a table.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
