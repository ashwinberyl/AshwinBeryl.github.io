---
title: "Bad Data & Schema Drift — The Failures That Don't Crash"
date: 2026-11-06
tags: [spark, production, troubleshooting, json, schema-drift, corrupt-records, data-quality, first-principles]
description: One truncated line in RepoSphere's events file turns into a row of nulls, and nobody is told. Learn how PERMISSIVE, DROPMALFORMED and FAILFAST really behave, how to capture bad lines with _corrupt_record, the cache rule that trips everyone up, what each kind of schema drift does to an explicit schema, and a small set of checks that turn silent damage into a loud alert.
---

# The Job That Succeeded and Was Wrong 🫥

In [Post 05](content/spark-production-failures/05-fetch-failed-and-shuffle-errors.md), the failures were loud. Executors died, stages retried, a pager went off. You always knew something had happened.

This post is about the opposite. The job **finishes green**. The dashboard **refreshes**. And one day later, someone says: "Why does Dave have no sessions on Friday?"

Two causes produce most of these tickets:

| Cause | What happened | Why nobody noticed |
|---|---|---|
| **Bad lines** | A writer was killed mid-line, or a bad record slipped in | Spark turned it into a row of nulls (or dropped it) |
| **Schema drift** | A producer renamed, added or retyped a field | The explicit schema from [Post 03 of the first series](content/data-engineering/03-reading-json-lines-and-schemas.md) kept the job from crashing, and kept the damage invisible |

We'll break both on purpose, in RepoSphere, and then build the checks that would have caught them.

---

## The Smudged Index Card 🗂️

Remember the JSON Lines stack of **index cards**: one record per card. If one card is smudged, the rest are still readable. That was the good news.

Now imagine the clerk reading the cards aloud into a spreadsheet. When they hit an unreadable card, they have three choices:

| Clerk's choice | Spark's mode |
|---|---|
| Type an **empty row** and carry on | `PERMISSIVE` (the default) |
| **Skip** the card, say nothing | `DROPMALFORMED` |
| **Stop** the whole job and shout | `FAILFAST` |

None of these is wrong. The disaster is picking one **without knowing it picked**. And there is a fourth choice that most teams forget: **set the card aside in a tray**, with a note saying what was wrong. That is the `_corrupt_record` column, and it's the one we'll use.

---

## Breaking RepoSphere on Purpose 💣

Take the nine-event file and add a tenth line, cut off mid-write when a producer was killed. It has no closing braces:

```python
good = open("data/events.jsonl").read()
bad_line = ('{"event_id":"e10","event_type":"PushEvent",'
            '"created_at":"2024-03-01T13:00:00Z",'
            '"repo":{"id":101,"name":"alpha-api"},'
            '"actor":{"id":1,"login":"dave"')          # truncated: no closing braces

with open("data/events_bad.jsonl", "w") as f:
    f.write(good)
    if not good.endswith("\n"):
        f.write("\n")
    f.write(bad_line + "\n")
```

Now read it with the **exact same** `read_events` from the first series, and count nulls by login:

```python
events = read_events(spark, "data/events_bad.jsonl")
print(events.count())

(events.groupBy(F.col("actor.login").alias("login"))
       .count()
       .orderBy(F.desc("count"))
       .show())
```

```
10
```

```
+-----+-----+
|login|count|
+-----+-----+
| dave|    5|
|  jim|    3|
| null|    2|
+-----+-----+
```

No error. Ten rows. But look at `null`: it was **1** in the clean file (just e09), and now it is **2**. The extra one is e10, which should have been `dave`. It became a row where **every column is null**, including `event_id`.

![Four reader behaviours on the same bad line](content/spark-production-failures/images/read_modes_on_a_bad_line.svg)

> **Trap:** In the default `PERMISSIVE` mode with an explicit schema, a malformed line becomes a **row of nulls**. The job succeeds, the row count is right (10), and downstream code that drops null actors ([Post 07 of the first series](content/data-engineering/07-sessionization-gaps-and-islands.md)) quietly eats e10. Dave loses an event and nobody sees an error.

Here is what the other modes do with the same file:

```python
dropped = (spark.read.schema(EVENT_SCHEMA)
                .option("mode", "DROPMALFORMED")
                .json("data/events_bad.jsonl"))
print(dropped.count())
```

```
9
```

Nine rows: the output looks perfectly clean, and one event is simply gone.

```python
strict = (spark.read.schema(EVENT_SCHEMA)
               .option("mode", "FAILFAST")
               .json("data/events_bad.jsonl"))
strict.count()          # the failure appears when an action runs
```

```
Illustrative log excerpt (wording varies by Spark version)

org.apache.spark.SparkException: Malformed records are detected in record parsing.
Parse Mode: FAILFAST. To process malformed records as null result, try setting
the option 'mode' as 'PERMISSIVE'.
```

| Mode | Rows | Bad line | Loud? |
|---|---|---|---|
| `PERMISSIVE` | 10 | Row of nulls | No |
| `DROPMALFORMED` | 9 | Gone | No |
| `FAILFAST` | n/a | Job fails | **Yes** |

> **Heads up:** `FAILFAST` is lazy like everything else in Spark. The `read` line succeeds; the exception appears when the first **action** reads the bad line. If your error shows up in a later stage, the data is the cause, not the stage.

---

## The Fix: Keep the Evidence With `_corrupt_record` 🧾

`FAILFAST` blocks the whole day for one bad line. `PERMISSIVE` hides it. The best of both: **keep running, but keep the bad line's raw text**.

To do that, add a string column to your schema, named `_corrupt_record` (the default name, controlled by `spark.sql.columnNameOfCorruptRecord`). Spark fills it with the raw line for malformed records, and leaves it `null` for good ones.

```python
from pyspark.sql.types import StructType, StructField, StringType

EVENT_WITH_CORRUPT = StructType(
    EVENT_SCHEMA.fields + [StructField("_corrupt_record", StringType())]
)
```

> **Trap:** Don't write `EVENT_SCHEMA.add("_corrupt_record", StringType())`. `StructType.add` **mutates the schema in place** and returns it, so your original contract would silently gain a column everywhere else it is used. Build a new `StructType` instead.

Now read, and look at the evidence:

```python
raw = (spark.read.schema(EVENT_WITH_CORRUPT)
            .option("mode", "PERMISSIVE")
            .json("data/events_bad.jsonl")
            .cache())                       # important: see the rule below

raw.filter(F.col("_corrupt_record").isNotNull()) \
   .select("_corrupt_record") \
   .show(truncate=False)
```

```
+--------------------------------------------------------------------------------------------------------------------------------------------------+
|_corrupt_record                                                                                                                                   |
+--------------------------------------------------------------------------------------------------------------------------------------------------+
|{"event_id":"e10","event_type":"PushEvent","created_at":"2024-03-01T13:00:00Z","repo":{"id":101,"name":"alpha-api"},"actor":{"id":1,"login":"dave"|
+--------------------------------------------------------------------------------------------------------------------------------------------------+
```

There is the smudged card, in full, with the exact cut point visible. Now you can **see** it, count it, send it to a quarantine folder and ask the producer team what happened.

### The cache rule that trips everyone up ⚠️

Why did we `.cache()` above? Spark has a deliberate restriction: a query on raw JSON or CSV files that references **only** the `_corrupt_record` column is rejected.

```
Illustrative log excerpt

org.apache.spark.sql.AnalysisException: Since Spark 2.3, the queries from raw JSON/CSV
files are disallowed when the referenced columns only include the internal corrupt
record column (named _corrupt_record by default). ...
```

The reason is that Spark prunes the columns it parses. If you only ask for the corrupt column, it wouldn't parse the other fields, and it couldn't tell which lines are malformed. The two fixes are the same idea: **parse everything first**.

| Fix | How |
|---|---|
| **Cache** the DataFrame, then query it | `raw = ... .cache()` as above, then filter |
| **Select another column too** | Reference a real column in the same query |

---

## A Reader That Fails Loudly, but Only When It Should 🚦

Now let's wrap this up into a reader that splits good from bad and applies a **threshold**. A tiny number of bad lines is a fact of life. A **sudden spike** is an incident.

```python
def read_events_checked(spark, path, max_bad_ratio=0.01):
    """Read events, quarantine malformed lines, fail if too many are bad."""
    raw = (spark.read.schema(EVENT_WITH_CORRUPT)
                .option("mode", "PERMISSIVE")
                .json(path)
                .cache())

    bad  = raw.filter(F.col("_corrupt_record").isNotNull())
    good = raw.filter(F.col("_corrupt_record").isNull()).drop("_corrupt_record")

    total, n_bad = raw.count(), bad.count()
    if total and n_bad / total > max_bad_ratio:
        raise ValueError(f"{n_bad} of {total} lines malformed ({n_bad / total:.1%})")
    return good, bad
```

Run it on our file with the default 1% tolerance:

```python
good, bad = read_events_checked(spark, "data/events_bad.jsonl")
```

```
ValueError: 1 of 10 lines malformed (10.0%)
```

One bad line in ten is 10%, far above 1%, so the job stops with a **specific, actionable message** instead of a green tick and wrong numbers. On a 10-billion-line day, the same single line would be well below the threshold and the job would continue:

```python
good, bad = read_events_checked(spark, "data/events_bad.jsonl", max_bad_ratio=0.2)
print(good.count(), bad.count())
```

```
9 1
```

```python
# quarantine the evidence for the producer team (path is yours to choose)
bad.select("_corrupt_record").write.mode("append").text("quarantine/events/2024-03-01")
```

> **Why a ratio, not "any bad line"?** Real producers have rare glitches. A threshold turns "perfect or nothing" into a **tuned alarm**. Pick the number from what a normal day looks like, and review it when it fires.

---

## Schema Drift: When the Producer Changes 🌊

Bad lines are accidents. **Drift** is a deliberate change by someone who didn't know you depend on the old shape. It rarely announces itself.

![What an explicit schema does for each kind of drift](content/spark-production-failures/images/schema_drift_kinds.svg)

The most dangerous one is the **rename**. Suppose RepoSphere's producer team renames `actor.login` to `actor.username` for every line. Our explicit schema still says `login`, so every row comes out with a `null` login. No crash. Because [sessionization drops null actors](content/data-engineering/07-sessionization-gaps-and-islands.md), the output is simply **empty**. A job that produces zero rows still exits with status 0.

You can catch this with a **null-rate check**: for the columns your pipeline depends on, compute how often each is null, and compare with a normal day.

```python
def null_rates(df, cols):
    return df.select([
        F.round(F.avg(F.col(c).isNull().cast("int")), 2).alias(c.replace(".", "_"))
        for c in cols
    ])

null_rates(read_events(spark, "data/events.jsonl"),
           ["event_id", "actor.login", "repo.id"]).show()
```

```
+--------+-----------+-------+
|event_id|actor_login|repo_id|
+--------+-----------+-------+
|     0.0|       0.11|    0.0|
+--------+-----------+-------+
```

On a normal day, `actor_login` is null in 1 of 9 rows (e09), so `0.11`. If the rename happened, the same check would report `1.0` for `actor_login` and `0.0` for the others. A rule like "fail if a column's null rate moves by more than a set amount from the last known-good run" would have stopped the job before anyone saw an empty dashboard.

A second, cheaper check compares **keys in the file with keys in the contract**. This is the one time inference is useful, in a separate check, not in the pipeline:

```python
def unexpected_top_level_keys(spark, path, schema):
    seen = set(spark.read.json(path).schema.fieldNames())
    return sorted(seen - set(schema.fieldNames()))

unexpected_top_level_keys(spark, "data/events.jsonl", EVENT_SCHEMA)
```

```
[]
```

An empty list means the file has nothing the contract doesn't know about. If the producer adds a top-level `payload` field, you'd get `['payload']`, and a human decides whether that's noise or something to adopt. (This sketch checks top-level keys only. Nested keys such as `actor.username` need the same comparison one level down.)

---

## Types That Drift: Read Raw, Cast Deliberately 🔡

We saw in the first series that one quoted id makes an *inferred* column a string. With an **explicit** numeric schema, how a quoted number is treated depends on the reader and the Spark version, which is exactly the kind of behaviour you don't want to rely on.

A robust pattern for fields that have drifted before: declare them as `StringType` in the raw read, then **cast on purpose and count the failures**.

```python
raw_ids = spark.createDataFrame(
    [("e01", "101"), ("e0x", "abc"), ("e0y", None)],
    ["event_id", "repo_id_raw"],
)   # a made-up bad batch, not part of the sample file

typed = raw_ids.withColumn("repo_id", F.col("repo_id_raw").cast("long"))
typed.show()
```

```
+--------+-----------+-------+
|event_id|repo_id_raw|repo_id|
+--------+-----------+-------+
|     e01|        101|    101|
|     e0x|        abc|   null|
|     e0y|       null|   null|
+--------+-----------+-------+
```

```python
cast_failures = typed.filter(F.col("repo_id_raw").isNotNull() & F.col("repo_id").isNull())
cast_failures.show()
```

```
+--------+-----------+-------+
|event_id|repo_id_raw|repo_id|
+--------+-----------+-------+
|     e0x|        abc|   null|
+--------+-----------+-------+
```

Only `e0x` is a **cast failure**: it had a value that didn't convert. `e0y` was already null, which is a different fact. Keeping those two apart is the whole point.

> **Heads up:** This output assumes the default (non-ANSI) cast, which returns `null` for text that isn't a number. If `spark.sql.ansi.enabled` is on (the default in Spark 4), a bad cast **raises an error** instead. That is *louder*, so arguably better, but know which one your cluster runs. In SQL, `try_cast` always returns `null` on failure.

---

## Troubleshooting Runbook: "The Numbers Look Wrong" 🧭

| Step | Question | How to answer it |
|---|---|---|
| 1 | Did the **row count** change from yesterday? | Count at the end of the read, not the end of the job |
| 2 | Did the **null rate** of any key column jump? | `null_rates` on the columns you depend on |
| 3 | Are there **malformed lines**? | `_corrupt_record IS NOT NULL` (cache first) |
| 4 | Did the **keys** in the file change? | Compare file keys with the contract |
| 5 | Did a **type** drift? | Cast failures: non-null raw, null after cast |
| 6 | **Where** did it start? | Run the read, then each step, comparing counts to the last good run |
| 7 | **Fix and prove** | Re-run on the bad file; the check should now fire or pass, as intended |

And the prevention list, in the order of effort:

- [ ] Use an **explicit schema** with a `_corrupt_record` column
- [ ] Put a **bad-line ratio** alarm on every reader
- [ ] Add **null-rate checks** on columns that joins and filters depend on
- [ ] **Quarantine** bad lines instead of throwing them away
- [ ] Agree on a **schema change process** with producers (a heads-up beats a postmortem)

---

## Quick Quiz 🧠

Commit to an answer before you open each one.

**Q1.** In the default `PERMISSIVE` mode with an explicit schema and **no** corrupt-record column, what happens to a truncated JSON line?

<details>
<summary>Show answer</summary>

It becomes a **row where every field is null**, and the job succeeds. The row count still includes it, so only a null-rate or bad-line check will reveal the problem. In our example, e10 added a second `null` login group instead of counting as `dave`.

</details>

**Q2.** Why does `spark.read.schema(S).json(p).filter("_corrupt_record IS NOT NULL").count()` fail on raw files, and how do you fix it?

<details>
<summary>Show answer</summary>

Since Spark 2.3, queries on raw JSON/CSV that reference **only** the corrupt-record column are rejected, because Spark would prune the other columns and couldn't tell which lines are malformed. **Cache** the DataFrame first (or include another real column in the query) so every field is parsed.

</details>

**Q3.** Why is `EVENT_SCHEMA.add("_corrupt_record", StringType())` a bug waiting to happen?

<details>
<summary>Show answer</summary>

`StructType.add` **modifies the schema in place** and returns it. Every other function that uses `EVENT_SCHEMA` now sees an extra column. Build a new schema with `StructType(EVENT_SCHEMA.fields + [StructField(...)])` instead.

</details>

**Q4.** The producer renames `actor.login` to `actor.username` on every line. What does `read_events` do, and what check would catch it?

<details>
<summary>Show answer</summary>

It returns `null` for `actor.login` on **every** row (the new key isn't in the contract, so it's ignored). Nothing crashes, and downstream steps may produce empty output. A **null-rate check** on `actor.login` (normally `0.11` on our sample, suddenly `1.0`) or a **key comparison** between the file and the schema would catch it.

</details>

**Q5.** Your tolerance is `max_bad_ratio=0.01` and one line in 10 is malformed. What does `read_events_checked` do, and why is a ratio better than "fail on any bad line"?

<details>
<summary>Show answer</summary>

It raises `ValueError: 1 of 10 lines malformed (10.0%)`. A ratio lets a huge file tolerate the rare glitch that real producers produce, while still **alarming on a spike**. Failing on any single bad line would block the whole day for noise.

</details>

---

## What's Next? 🚀

You can now stop bad lines and drifted fields from slipping through quietly. But the quietest failures of all don't come from the input. They come from **our own code**: a join that duplicates rows, a filter that drops them, a time zone that moves an event to the wrong day.

👉 **[Post 07: Silent Wrong Answers](content/spark-production-failures/07-silent-wrong-answers.md)**

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
