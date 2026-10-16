---
title: "Reading JSON Lines & Schemas — Why Inference Is a Trap"
date: 2026-10-11
tags: [data-engineering, pyspark, json-lines, schema, structtype, first-principles]
description: How Spark reads JSON Lines, what schema inference really does, the missing-field trap that crashes a job on a quiet day, and how an explicit nested StructType turns read_events and read_repo_changes into a contract the whole RepoSphere pipeline can trust.
---

# From Raw Lines to a Trustworthy DataFrame 📥

In [Post 02](content/data-engineering/02-spark-from-first-principles.md), we built the RepoSphere events DataFrame **by hand**. Every field was already flat. Every type was already right. We even typed `None` for e09's missing login ourselves.

Real data never arrives like that.

It arrives as a text file. Nested. Incomplete. And on some days, missing a field on **every single line**.

So before we can flatten, sessionize or join anything, we need the first two functions of the pipeline:

| # | Function | Reads | Returns |
|---|---|---|---|
| 1 | `read_events` | `events.jsonl` | One row per event, with nested `repo` and `actor` |
| 2 | `read_repo_changes` | `repo_changes.jsonl` | One row per repo change, six flat columns |

They look like one-liners. They are one-liners. But the *one decision* inside them — who decides the schema — is the difference between a pipeline that survives a weird day and one that pages you at 3 a.m.

---

## What Is JSON Lines? 📜

Think of a **stack of index cards**.

Each card describes one thing, completely, on its own. You can add a new card to the top without touching the others. You can split the stack in half and give each half to a different person. And if one card is smudged, the rest of the stack is still readable.

That's **JSON Lines** (`.jsonl`): **one complete JSON object per line, one line per record.**

```json
{"event_id":"e01","event_type":"PushEvent","created_at":"2024-03-01T09:50:00Z","repo":{"id":101,"name":"alpha-api"},"actor":{"id":1,"login":"dave"}}
{"event_id":"e02","event_type":"PullRequestEvent","created_at":"2024-03-01T10:10:00Z","repo":{"id":202,"name":"beta-web"},"actor":{"id":1,"login":"dave"}}
```

Compare that with a normal JSON file — one big array:

| | **JSON array** `[{...}, {...}]` | **JSON Lines** `{...}\n{...}` |
|---|---|---|
| **Append a record** | Rewrite the closing `]` | Just add a line |
| **Split across machines** | Hard — must parse from the `[` | Easy — cut at any newline |
| **One corrupt record** | The whole file fails to parse | Only that line is bad |
| **Spark option** | `multiLine=True` | The default |

That second row is the one Spark cares about. Remember the kitchen from Post 02: many cooks, each with a share of the ingredients. A JSON Lines file can be cut at any newline and handed to different executors. A JSON array can't.

> **Key insight:** Logs, event streams and webhook dumps are almost always JSON Lines for exactly this reason. Writers can append forever, and readers can split freely.

---

## One Line, Many Shapes 🪆

Look closely at the last line of `events.jsonl`:

```json
{"event_id":"e09","event_type":"PushEvent","created_at":"2024-03-01T10:00:00Z","repo":{"id":101,"name":"alpha-api"},"actor":{"id":3}}
```

Three different shapes are hiding in it:

- **Plain values** — `event_id`, `event_type`, `created_at`. Strings.
- **Nested objects** — `repo` and `actor` are JSON objects *inside* the JSON object.
- **A missing key** — `actor` has an `id` but **no `login`**.

In Spark, a nested object becomes a **struct**: a column that holds a small row of its own.

![One line of events.jsonl becomes one row with two struct columns](content/data-engineering/images/jsonl_line_to_schema.svg)

The plain values and structs are easy. The missing key is the interesting part — because *what happens to it* depends entirely on who wrote the schema.

---

## Option A: Let Spark Guess 🔮

The shortest possible read:

```python
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

spark = (SparkSession.builder
         .appName("reposphere")
         .master("local[*]")
         .config("spark.sql.session.timeZone", "UTC")
         .getOrCreate())

raw = spark.read.json("data/events.jsonl")     # JSON Lines is the default
raw.printSchema()
```

```
root
 |-- actor: struct (nullable = true)
 |    |-- id: long (nullable = true)
 |    |-- login: string (nullable = true)
 |-- created_at: string (nullable = true)
 |-- event_id: string (nullable = true)
 |-- event_type: string (nullable = true)
 |-- repo: struct (nullable = true)
 |    |-- id: long (nullable = true)
 |    |-- name: string (nullable = true)
```

It worked. This is **schema inference**: Spark scans the file, collects every key it sees on any line, picks a type for each, and fills in `null` wherever a line lacks a key. e09's missing login becomes `null`, because *other* lines had a login.

Four things to notice:

| What you see | Why |
|---|---|
| Columns are **alphabetical** — `actor` first, `event_id` third | Inference sorts field names. Your file order is lost. |
| `repo` and `actor` are **struct** | Nested objects become nested columns |
| `id` fields are **long** | JSON numbers without a decimal point become 64-bit integers |
| `created_at` is **string** | JSON has no timestamp type. A time is just text until you parse it (Post 04). |

So far, so convenient. Now let's break it.

---

## The Trap: A Field Missing From Every Line 💥

Inference has one fundamental limit: **it only knows about keys it actually saw.**

Imagine a quiet Sunday on RepoSphere. Nobody logged in. The only activity was an automation account pushing to repo 101 — and automation accounts have no login. Today's file has exactly one line:

```python
with open("data/events_quiet_day.jsonl", "w") as f:
    f.write('{"event_id":"e09","event_type":"PushEvent",'
            '"created_at":"2024-03-01T10:00:00Z",'
            '"repo":{"id":101,"name":"alpha-api"},"actor":{"id":3}}\n')

quiet = spark.read.json("data/events_quiet_day.jsonl")
quiet.printSchema()
```

```
root
 |-- actor: struct (nullable = true)
 |    |-- id: long (nullable = true)
 |-- created_at: string (nullable = true)
 |-- event_id: string (nullable = true)
 |-- event_type: string (nullable = true)
 |-- repo: struct (nullable = true)
 |    |-- id: long (nullable = true)
 |    |-- name: string (nullable = true)
```

Look at `actor`. It has `id`. **There is no `login` field at all.** Not a null value — no field.

Now run the exact code that worked yesterday:

```python
quiet.select("event_id", F.col("actor.login").alias("actor_login")).show()
```

```
AnalysisException: [FIELD_NOT_FOUND] No such struct field `login` in `id`.
```

The job **crashes**. Same code, same pipeline. The only thing that changed was *what the data happened to contain today*.

> **Trap:** With inference, your schema is a property of today's data — not of your pipeline. A field that's rare (a login, a coupon code, an error message) will one day be absent from a whole file, and every line of code that references it will fail.

And that's not the only way inference bites:

| Inference risk | RepoSphere example | What you get |
|---|---|---|
| **Field absent from every line** | A day with only automation accounts | `AnalysisException` on `actor.login` |
| **Type drift** | One producer sends `"id":"101"` (quoted) | `repo.id` silently becomes `string` for the whole file |
| **Column order** | Inferred columns are alphabetical | `select("*")` output changes shape vs your spec |
| **Cost** | A 2 TB day of events | Spark scans the data once just to infer, before the real read |

Notice the second row. If even one line quotes a number, inference widens the type to `string` — and later, sorting by `repo_id` sorts text, not numbers. No error. Just a different answer.

---

## Option B: Write the Schema Yourself 📐

Think of a **paper form with printed boxes**.

If someone leaves the "login" box blank, the box is still on the form — it's just empty. You never get a form where the box itself has vanished. That's what an explicit schema gives you.

Here is the real `read_events`:

```python
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.types import StructType, StructField, StringType, LongType

EVENT_SCHEMA = StructType([
    StructField("event_id",   StringType()),
    StructField("event_type", StringType()),
    StructField("created_at", StringType()),        # parsed to a timestamp in Post 04
    StructField("repo", StructType([
        StructField("id",   LongType()),
        StructField("name", StringType()),
    ])),
    StructField("actor", StructType([
        StructField("id",    LongType()),
        StructField("login", StringType()),         # missing on some lines — that's fine
    ])),
])


def read_events(spark: SparkSession, path: str) -> DataFrame:
    """Read RepoSphere events (JSON Lines) with a fixed, nested schema."""
    return spark.read.schema(EVENT_SCHEMA).json(path)
```

That's it. The only change from Option A is `.schema(EVENT_SCHEMA)` — but it changes who's in charge.

```python
events = read_events(spark, "data/events.jsonl")
events.printSchema()
events.show(truncate=False)
```

```
root
 |-- event_id: string (nullable = true)
 |-- event_type: string (nullable = true)
 |-- created_at: string (nullable = true)
 |-- repo: struct (nullable = true)
 |    |-- id: long (nullable = true)
 |    |-- name: string (nullable = true)
 |-- actor: struct (nullable = true)
 |    |-- id: long (nullable = true)
 |    |-- login: string (nullable = true)
```

```
+--------+----------------+--------------------+--------------------+----------+
|event_id|event_type      |created_at          |repo                |actor     |
+--------+----------------+--------------------+--------------------+----------+
|e01     |PushEvent       |2024-03-01T09:50:00Z|{101, alpha-api}    |{1, dave} |
|e02     |PullRequestEvent|2024-03-01T10:10:00Z|{202, beta-web}     |{1, dave} |
|e03     |IssuesEvent     |2024-03-01T10:40:00Z|{101, alpha-api}    |{1, dave} |
|e05     |PushEvent       |2024-03-01T11:20:00Z|{202, beta-web}     |{1, dave} |
|e04     |PUSHEVENT       |2024-03-01T11:20:00Z|{101, alpha-service}|{1, dave} |
|e06     |PushEvent       |2024-03-01T10:15:00Z|{202, beta-web}     |{2, jim}  |
|e07     |IssuesEvent     |2024-03-01T10:35:00Z|{202, beta-web}     |{2, jim}  |
|e08     |PushEvent       |2024-03-01T12:30:00Z|{999, ghost}        |{2, jim}  |
|e09     |PushEvent       |2024-03-01T10:00:00Z|{101, alpha-api}    |{3, null} |
+--------+----------------+--------------------+--------------------+----------+
```

Read the output like this:

- Columns come out in **your declared order**, not alphabetical.
- Each struct prints as `{field1, field2}` — `{101, alpha-api}` is `repo.id = 101`, `repo.name = alpha-api`.
- e09's actor is `{3, null}` — the `login` box exists, it's just empty.
- Rows are in **file order**: e05 before e04, exactly as written. Reading doesn't sort anything. (That ordering matters in Post 07.)
- `PUSHEVENT` is still uppercase. Reading doesn't clean — that's Post 04's job.

Now the quiet-day file, through the same function:

```python
quiet = read_events(spark, "data/events_quiet_day.jsonl")
quiet.select("event_id", F.col("actor.login").alias("actor_login")).show()
```

```
+--------+-----------+
|event_id|actor_login|
+--------+-----------+
|     e09|       null|
+--------+-----------+
```

No crash. `actor.login` exists because **you** said it exists. On a day with no logins, it's simply `null` everywhere — and the null rules from Post 02 take it from there.

![Same quiet-day file, two ways to read it](content/data-engineering/images/schema_inference_vs_contract.svg)

> **Key insight:** An explicit schema is a **contract**: "these columns will exist, with these types, in this order." Every function downstream — flatten, sessionize, join — can rely on it without checking. That's what makes the pipeline testable one function at a time.

> **Bonus:** Spark also skips the inference scan entirely. On terabytes of events, that's a whole extra pass over the data you don't pay for.

### The same schema, as a DDL string

If nested `StructType` feels verbose, Spark also accepts a SQL-style string. This is identical:

```python
EVENT_DDL = """
    event_id STRING, event_type STRING, created_at STRING,
    repo  STRUCT<id: BIGINT, name: STRING>,
    actor STRUCT<id: BIGINT, login: STRING>
"""
events = spark.read.schema(EVENT_DDL).json("data/events.jsonl")
```

`BIGINT` is SQL's name for `LongType`. Use whichever your team finds easier to review — the contract is the same.

---

## `read_repo_changes`: The Flat One 🔁

The second input is simpler: no nesting, six columns, every line complete. Same approach anyway — the contract matters *more* on days the data surprises you, not less.

```python
REPO_CHANGE_SCHEMA = StructType([
    StructField("change_id",      StringType()),
    StructField("repo_id",        LongType()),
    StructField("changed_at",     StringType()),    # parsed when we build SCD2 (Post 06)
    StructField("repo_name",      StringType()),
    StructField("visibility",     StringType()),
    StructField("default_branch", StringType()),
])


def read_repo_changes(spark: SparkSession, path: str) -> DataFrame:
    """Read RepoSphere repo-change snapshots with a fixed, flat schema."""
    return spark.read.schema(REPO_CHANGE_SCHEMA).json(path)
```

```python
changes = read_repo_changes(spark, "data/repo_changes.jsonl")
changes.printSchema()
changes.show(truncate=False)
```

```
root
 |-- change_id: string (nullable = true)
 |-- repo_id: long (nullable = true)
 |-- changed_at: string (nullable = true)
 |-- repo_name: string (nullable = true)
 |-- visibility: string (nullable = true)
 |-- default_branch: string (nullable = true)
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

There's our late-arriving `c2` from Post 01, sitting after `c3` — exactly as the file has it. The reader's job is to **load faithfully**, not to fix. Putting `c2` in its rightful place is a job for a window function (Post 05) and SCD Type 2 (Post 06).

> **Why keep `created_at` and `changed_at` as strings here?** You *could* declare them as `TimestampType` and let the reader parse them. But keeping the reader dumb has two benefits: all parsing lives in one place (Post 04), and if a value ever fails to parse, the original text is still sitting in the raw DataFrame for you to inspect.

---

## What the Contract Does With Surprises 🧾

A schema isn't just about missing fields. Here's how `read_events` behaves when the file doesn't match the contract:

| Surprise in the file | What `read_events` does |
|---|---|
| A key is **missing** on some lines (`actor.login` on e09) | That field is `null` for those lines |
| A key is missing on **every** line | The column still exists — all `null` |
| An **extra** key you didn't declare (say RepoSphere adds `payload`) | Silently ignored. It's not in the contract. |
| A value that **doesn't fit** the type (`"id":"abc"` for a `LongType`) | Treated as malformed. In the default mode, you get `null`s instead of a crash. |
| A line that **isn't valid JSON** at all | Same — malformed. Its fields come out `null`. |

That last pair is controlled by the reader's `mode` option:

| `mode` | Malformed line becomes… | Use when |
|---|---|---|
| `PERMISSIVE` (default) | A row of `null`s | You'd rather keep running and check for nulls |
| `DROPMALFORMED` | Nothing — the line is dropped | You've decided bad lines are noise |
| `FAILFAST` | An exception that stops the job | Bad data must never get through silently |

> **Trap:** "Silently ignored" and "becomes null" are both quiet. An explicit schema stops *crashes*, but it can't tell you the data got worse. After reading, a cheap sanity check like `events.filter(F.col("actor.login").isNull()).count()` (it's `1` for our file — just e09) tells you whether today looks like yesterday.

And the extra-key row has a sequel: when RepoSphere really does add a field you need, you'll change the contract on purpose. Doing that on a live table without rewriting history is Post 16.

---

## Strings vs Longs: The Sorting Trap 🔢

One more schema decision that looks cosmetic and isn't: **is an ID a string or a number?**

Strings compare **character by character**. Numbers compare by **value**. On IDs, those disagree:

```python
ids = spark.createDataFrame([("101",), ("202",), ("999",), ("1000",)], ["repo_id"])

ids.orderBy("repo_id").show()                          # sorted as text
ids.orderBy(F.col("repo_id").cast("long")).show()      # sorted as numbers
```

```
+-------+
|repo_id|
+-------+
|   1000|
|    101|
|    202|
|    999|
+-------+
```

```
+-------+
|repo_id|
+-------+
|    101|
|    202|
|    999|
|   1000|
+-------+
```

As text, `"1000"` comes first, because `'1' < '2'` and the comparison stops there. Repo 1000 is "smaller" than repo 101.

This matters far beyond `orderBy`. Later in the pipeline, IDs become **tie-breakers**. In Post 01, e04 and e05 both happened at exactly 11:20. To decide which came "first" in Dave's session, we'll order by time *and then* by `event_id` (Posts 07 and 09).

So check the real data before you choose the type:

| Field | Values in the file | Type | Why |
|---|---|---|---|
| `event_id` | `"e01"` … `"e09"` | `StringType` | It has a letter. And it's zero-padded, so text order = numeric order: `"e04" < "e05"` |
| `repo.id`, `repo_id` | `101`, `202`, `999` | `LongType` | Real numbers. Read them as numbers, sort them as numbers |
| `actor.id` | `1`, `2`, `3` | `LongType` | Same |

> **Trap:** Zero-padding only *delays* the string problem. Once RepoSphere reaches event 100, `"e100" < "e99"` as text. If you ever control the ID format, make it a number — or pad it wide enough for the data you'll have in five years.

---

## Quick Reference ✅

- [ ] JSON Lines = one JSON object per line; it's Spark's default for `spark.read.json`
- [ ] Nested objects become **struct** columns; reach inside with `F.col("actor.login")`
- [ ] Inference builds the schema **from today's data** — alphabetical, and blind to fields no line contains
- [ ] Always pass an explicit `StructType` (or DDL string) with `.schema(...)` in production readers
- [ ] A declared-but-missing field becomes `null`, never a crash
- [ ] Undeclared keys are ignored; malformed values become `null` in `PERMISSIVE` mode
- [ ] Readers load faithfully — no sorting, no cleaning, no parsing
- [ ] Choose ID types from the real data: numbers as `LongType`, letter-prefixed IDs as `StringType`

---

## Quick Quiz 🧠

Commit to an answer before you open each one.

**Q1.** With `spark.read.json("data/events.jsonl")` and no schema, which column comes first in `printSchema()`, and why?

<details>
<summary>Show answer</summary>

**`actor`.** Schema inference sorts field names alphabetically: `actor`, `created_at`, `event_id`, `event_type`, `repo`. The order of keys in the file doesn't matter. With an explicit schema, columns come out in the order you declared.

</details>

**Q2.** On the quiet-day file (only e09, no login anywhere), what does `read_events(spark, path).filter(F.col("actor.login").isNull()).count()` return? What would the same filter do on `spark.read.json(path)`?

<details>
<summary>Show answer</summary>

**1** with `read_events` — `actor.login` exists in the contract and is `null` for e09. With plain `spark.read.json`, the inferred `actor` struct has no `login` field, so the filter fails with an `AnalysisException` before returning anything.

</details>

**Q3.** A teammate reads `repo_id` as `StringType`. RepoSphere now has repos 101, 999 and 1000. What does `orderBy("repo_id")` return?

<details>
<summary>Show answer</summary>

**`"1000"`, `"101"`, `"999"`.** Text compares character by character. `"1000"` and `"101"` match on `1` and `0`, then `'0' < '1'` decides it — so `"1000"` comes first. Both start with `'1'`, which is less than `'9'`, so `"999"` is last. Read numeric IDs as `LongType` and you get 101, 999, 1000.

</details>

**Q4.** Tomorrow, RepoSphere starts adding a `"payload": {...}` object to every event. Does `read_events` fail? Do you see the payload?

<details>
<summary>Show answer</summary>

**Neither.** The read succeeds, and `payload` is silently ignored — it isn't in the contract. That's usually what you want (new upstream fields don't break you), but it means nobody notices the new field until someone adds it to the schema on purpose. Post 16 covers evolving a schema safely.

</details>

**Q5.** Why does `read_events` return e05 *before* e04, even though e04 has the smaller ID and the same timestamp?

<details>
<summary>Show answer</summary>

Because that's the order of the lines in the file, and **reading never sorts**. A DataFrame has no guaranteed order at all unless you ask for one. When order matters — inside a session, or when picking a "first" row — you must say so explicitly, with `event_id` as the tie-breaker. That's Posts 05, 07 and 09.

</details>

---

## What's Next? 🚀

We now have two trustworthy DataFrames: events with nested `repo` and `actor` structs, and repo changes in six flat columns. But analysts don't want structs, `created_at` is still text, and `PUSHEVENT` is still shouting.

👉 **[Post 04 — Flattening & Timestamps](content/data-engineering/04-flattening-and-timestamps.md)** — `flatten_events`: dot paths and aliases, `to_timestamp` and `to_date`, `lower()`, why the session time zone must be UTC, and why the output should carry only the columns you need.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
