---
title: "Flattening & Timestamps — From Nested Text to Columns You Can Trust"
date: 2026-10-12
tags: [data-engineering, pyspark, flattening, timestamps, time-zones, first-principles]
description: How flatten_events turns RepoSphere's nested events into six flat, typed columns — dot paths and aliases, to_timestamp and to_date, lower() for messy event types, why the session time zone must be UTC, and why the output should carry only the columns you need.
---

# Unpacking the Boxes 📦

In [Post 03](content/data-engineering/03-reading-json-lines-and-schemas.md), we wrote `read_events` with an explicit schema. Every RepoSphere event now arrives as one row with the same five columns, every day, no matter what the file contains.

But look at what we actually have:

- `repo` and `actor` are **structs**, not columns an analyst can group by.
- `created_at` is **text**. You can't subtract two strings to get a gap in seconds.
- `event_type` says `PushEvent` on five lines and `PUSHEVENT` on one.

The data is *safe*. It isn't *usable* yet.

That's the job of the third function in the pipeline:

| # | Function | Takes | Returns |
|---|---|---|---|
| 3 | `flatten_events` | The nested DataFrame from `read_events` | Six flat, typed columns: `event_id`, `event_type`, `created_ts`, `event_date`, `repo_id`, `actor_login` |

It's about ten lines of code. Inside those ten lines are four decisions that every later post depends on.

---

## The Moving-Day Analogy 🚚

You've just moved house. Everything arrived in labelled boxes: a box called **repo** with an id and a name inside, a box called **actor** with an id and a login.

Boxes are great for *transport*. Nothing gets lost, and related things stay together.

But you can't cook out of boxes. So you unpack: each item goes onto a **labelled shelf** where you can see it and reach it. And while you unpack, you do three more things:

- **Relabel** things so the names make sense in the kitchen, not on the truck.
- **Fix** what got mangled in transit (that shouting `PUSHEVENT`).
- **Leave in the box** whatever you don't need in this room.

That's flattening. Structs are the boxes. Flat columns are the shelves.

![flatten_events maps one nested row to six flat columns](content/data-engineering/images/flatten_events_map.svg)

---

## Dot Paths: Reaching Into a Struct 🎯

To pull a field out of a struct, write its path with a dot:

```python
from pyspark.sql import functions as F

events = read_events(spark, "data/events.jsonl")

events.select("event_id", "repo.id", "actor.login").show(truncate=False)
```

```
+--------+---+-----+
|event_id|id |login|
+--------+---+-----+
|e01     |101|dave |
|e02     |202|dave |
|e03     |101|dave |
|e05     |202|dave |
|e04     |101|dave |
|e06     |202|jim  |
|e07     |202|jim  |
|e08     |999|jim  |
|e09     |101|null |
+--------+---+-----+
```

It works, and e09's missing login is a clean `null` thanks to the schema from Post 03.

But look at the header. The column from `repo.id` is called just **`id`**. Spark names a struct field after its *last* path segment. Now try to take both ids:

```python
events.select(F.col("repo.id"), F.col("actor.id")).columns
```

```
['id', 'id']
```

Two columns, one name. Any later `F.col("id")` is **ambiguous**, and Spark will refuse to guess.

> **Key insight:** A dot path reaches *into* the box. An **alias** puts a label on the shelf. You almost always need both: `F.col("repo.id").alias("repo_id")`.

### Computed columns need aliases too

It's not just struct fields. Any expression gets an auto-generated name:

```python
events.select(F.lower(F.col("event_type"))).columns
```

```
['lower(event_type)']
```

A test, a join or a teammate looking for `event_type` won't find `lower(event_type)`. Rule of thumb: **if it's not a bare column name, it gets an `.alias(...)`.**

### Three ways to flatten

| Approach | Example | Problem |
|---|---|---|
| **Star expansion** | `select("repo.*", "actor.*")` | Gives `id, name, id, login`. Two `id`s, and you get every field whether you need it or not. |
| **`withColumn` chain** | `.withColumn("repo_id", F.col("repo.id"))` | Keeps the original `repo` and `actor` structs too, unless you remember to `drop` them. |
| **One `select` with aliases** ✅ | `select(F.col("repo.id").alias("repo_id"), ...)` | None. The output is *exactly* the list you wrote. |

One `select` is the tight option. What you list is what you get, in the order you list it.

---

## `lower()`: One Event Type, Two Spellings 🔡

Here's what the raw `event_type` looks like when you count it:

```python
events.groupBy("event_type").count().orderBy("event_type").show(truncate=False)
```

```
+----------------+-----+
|event_type      |count|
+----------------+-----+
|IssuesEvent     |2    |
|PUSHEVENT       |1    |
|PullRequestEvent|1    |
|PushEvent       |5    |
+----------------+-----+
```

To Spark, `PUSHEVENT` and `PushEvent` are **different strings**, so they're different groups. Ask "how many pushes today?" with `== "PushEvent"` and you get 5. The real answer is 6. e04 is hiding in its own row.

Normalize it once, at the flatten step:

```python
events.groupBy(F.lower("event_type").alias("event_type")) \
      .count().orderBy("event_type").show(truncate=False)
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

Six pushes, one group.

> **Why `lower()` and not something prettier?** `F.initcap` would turn `PUSHEVENT` into `Pushevent`, which still doesn't match `PushEvent`. Lowercasing is the one transform that maps every casing of a word to the same string. It's boring, and that's the point.

> **Trap:** Notice the sort order in the first table. `PUSHEVENT` comes *before* `PullRequestEvent`, because uppercase `U` sorts before lowercase `u`. Mixed-case data doesn't just split groups. It also scrambles your ordering.

---

## Timestamps: Why Text Isn't Time ⏱️

`created_at` holds values like `"2024-03-01T09:50:00Z"`. That's **ISO 8601**: date, then `T`, then time, then `Z` for UTC.

As long as every value has exactly this format, comparing the strings happens to give the right order. The moment one producer sends a time with an offset, it doesn't:

```python
pair = spark.createDataFrame(
    [("2024-03-01T09:50:00Z", "2024-03-01T11:20:00+05:30")], ["a", "b"])

pair.select(
    (F.col("b") > F.col("a")).alias("b_later_as_text"),
    (F.to_timestamp("b") > F.to_timestamp("a")).alias("b_later_as_time"),
).show(truncate=False)
```

```
+---------------+---------------+
|b_later_as_text|b_later_as_time|
+---------------+---------------+
|true           |false          |
+---------------+---------------+
```

As text, `"11:20"` beats `"09:50"`. As time, 11:20 in India is **05:50 UTC**, four hours *before* 09:50 UTC. The string comparison isn't just imprecise. It's backwards.

A **`TimestampType`** value is a single instant, stored internally as microseconds since 1970-01-01 UTC. Once you have that, three things become possible:

| You want to… | As a string | As a timestamp |
|---|---|---|
| Order events correctly across offsets | ❌ Wrong as soon as formats mix | ✅ Always |
| Compute a gap in seconds (Post 07) | ❌ Can't subtract text | ✅ `ts.cast("double")` and subtract |
| Ask "was this event inside [valid_from, valid_to)?" (Post 08) | ❌ Text ranges lie | ✅ Real comparisons |
| Get the calendar date | ⚠️ Chops off the written date, ignoring the offset | ✅ `F.to_date(ts)` in a known time zone |

### `to_timestamp` and `to_date`

```python
created_ts = F.to_timestamp(F.col("created_at"))     # ISO 8601 needs no pattern
event_date = F.to_date(created_ts)                   # drop the time of day
```

Two rules:

- **No pattern** for ISO 8601. `to_timestamp` understands `2024-03-01T09:50:00Z` and offsets like `+05:30` out of the box.
- **Parse first, then take the date.** `F.to_date(created_ts)` asks "what day was this instant?". `F.to_date` straight on the string only reads the characters before the `T`, and ignores the `Z` or offset entirely.

### Other formats need a pattern

If a source sends something else, give `to_timestamp` the pattern:

```python
odd = spark.createDataFrame(
    [("2024-03-01T10:40:00Z",), ("01/03/2024 10:40",)], ["created_at"])

odd.select(
    "created_at",
    F.to_timestamp("created_at").alias("iso"),
    F.to_timestamp("created_at", "dd/MM/yyyy HH:mm").alias("dmy"),
).show(truncate=False)
```

```
+--------------------+-------------------+-------------------+
|created_at          |iso                |dmy                |
+--------------------+-------------------+-------------------+
|2024-03-01T10:40:00Z|2024-03-01 10:40:00|null               |
|01/03/2024 10:40    |null               |2024-03-01 10:40:00|
+--------------------+-------------------+-------------------+
```

Each value parses under one rule and comes back `null` under the other. **No error.**

> **Trap:** A value that fails to parse becomes `null` silently (on Spark 3.x defaults). A bad timestamp doesn't crash the job. It quietly drops out of every session and every join later on. After flattening, check: `flat.filter(F.col("created_ts").isNull()).count()` should be `0`. For our file, it is.

> **Version note:** With ANSI mode on, the default since Spark 4.0, `to_timestamp` raises an error on unparseable input instead of returning `null`. If you want the forgiving behaviour there, use `F.try_to_timestamp` (available since Spark 3.5).

---

## The Session Time Zone Trap 🌍

Here's the subtle one.

A timestamp is an **instant**: the moment a rocket left the pad. Everyone on Earth agrees on *when* that was. What they don't agree on is **what the clock said**, or even **what day it was**.

When Spark shows a timestamp, or turns one into a date, it has to pick a clock. That clock is the setting **`spark.sql.session.timeZone`**. If you never set it, Spark uses your machine's local zone.

Let's add a hypothetical late-evening event, e10 at 20:15 UTC, and read it on three different clocks:

```python
late = spark.createDataFrame([("e10", "2024-03-01T20:15:00Z")],
                             ["event_id", "created_at"])

def parse(df):
    ts = F.to_timestamp("created_at")
    return df.select("event_id",
                     ts.alias("created_ts"),
                     F.to_date(ts).alias("event_date"),
                     ts.cast("long").alias("epoch_s"))

for tz in ["UTC", "Asia/Kolkata", "America/Los_Angeles"]:
    spark.conf.set("spark.sql.session.timeZone", tz)
    print(tz)
    parse(late).show(truncate=False)

spark.conf.set("spark.sql.session.timeZone", "UTC")   # back to sanity
```

```
UTC
+--------+-------------------+----------+----------+
|event_id|created_ts         |event_date|epoch_s   |
+--------+-------------------+----------+----------+
|e10     |2024-03-01 20:15:00|2024-03-01|1709324100|
+--------+-------------------+----------+----------+

Asia/Kolkata
+--------+-------------------+----------+----------+
|event_id|created_ts         |event_date|epoch_s   |
+--------+-------------------+----------+----------+
|e10     |2024-03-02 01:45:00|2024-03-02|1709324100|
+--------+-------------------+----------+----------+

America/Los_Angeles
+--------+-------------------+----------+----------+
|event_id|created_ts         |event_date|epoch_s   |
+--------+-------------------+----------+----------+
|e10     |2024-03-01 12:15:00|2024-03-01|1709324100|
+--------+-------------------+----------+----------+
```

Read that carefully:

- **`epoch_s` never changes.** It's the same instant in all three runs: 1,709,324,100 seconds after 1970-01-01 UTC.
- **`created_ts` as displayed** changes with the clock.
- **`event_date` changes too.** On a laptop in India, e10 belongs to **2 March**. On a server in UTC, it belongs to **1 March**.

![The same instant gives a different date in each session time zone](content/data-engineering/images/one_instant_three_dates.svg)

Now picture the real failure. You develop on your laptop in Bengaluru, and your tests pass. The job runs on a cluster set to UTC, and the daily counts per `event_date` come out different. Same code, same data, different answers, depending on **where the code ran**.

> **Trap:** `event_date` is the column every daily report groups by. If it depends on whoever's laptop ran the job, every downstream number is suspect. The same goes for Iceberg's day partitions in Post 11.

The fix is one line in the session builder. Set it and never think about it again:

```python
spark = (SparkSession.builder
         .appName("reposphere")
         .master("local[*]")
         .config("spark.sql.session.timeZone", "UTC")   # dates mean the same thing everywhere
         .getOrCreate())
```

| What the session time zone affects | Example |
|---|---|
| How timestamps are **displayed** in `show()` | e10 shows as 20:15, 01:45 or 12:15 |
| How timestamps are turned into **dates** | e10 is 1 March or 2 March |
| How strings **without** an offset are parsed | `"2024-03-01 09:50:00"` is read as 09:50 *in that zone* |
| The stored **instant** itself | ❌ Never. `epoch_s` is identical everywhere. |

> **Key insight:** Our events all carry a `Z`, so parsing is safe in any zone. It's the **date** and the **display** that drift. UTC in the builder makes both reproducible.

---

## Keep the Column List Tight ✂️

One more decision, and it's about the future.

`flatten_events` could happily keep `repo.name` as `repo_name`. It's right there in the struct. Why leave it behind?

Look ahead to Post 08. `enrich_with_repo_state` will **append** three columns from the SCD2 repo table: `repo_name`, `visibility` and `default_branch`. If the flat events already have a `repo_name`, the joined result has **two** of them. The first `F.col("repo_name")` after that fails with an `AMBIGUOUS_REFERENCE` error.

And there's a second, deeper reason. The event's own `repo.name` is just what the logger wrote at that moment. e04 says `alpha-service`. The **point-in-time** join exists precisely to give each event the name, visibility and branch that were *actually* true at its timestamp, from the dimension table. Carrying the event's copy alongside would just invite someone to use the wrong one.

| Field in the struct | Kept? | Why |
|---|---|---|
| `repo.id` → `repo_id` | ✅ | The join key for the repo table |
| `repo.name` | ❌ | Collides with the SCD2 `repo_name`. The join supplies the history-correct one |
| `actor.login` → `actor_login` | ✅ | Sessions are per developer (Post 07) |
| `actor.id` | ❌ | Not in the output spec. Nothing downstream uses it |

> **Rule:** A flatten step should output **what the spec lists, and nothing else**. Every extra column is a future name collision, wider files and one more thing to explain.

---

## The Real `flatten_events` ✅

Here's the whole function, with all four decisions in it:

```python
from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def flatten_events(events: DataFrame) -> DataFrame:
    """Turn nested RepoSphere events into six flat, typed columns."""
    created_ts = F.to_timestamp(F.col("created_at"))      # ISO 8601 with Z: no pattern needed

    return events.select(
        F.col("event_id"),
        F.lower(F.col("event_type")).alias("event_type"),  # PUSHEVENT -> pushevent
        created_ts.alias("created_ts"),
        F.to_date(created_ts).alias("event_date"),         # date of the instant, in session TZ (UTC)
        F.col("repo.id").alias("repo_id"),                 # dot path + alias
        F.col("actor.login").alias("actor_login"),         # null for e09, never a crash
    )
```

Notice `created_ts` is defined **once** as a Python variable and used twice. It's just a column expression, not data, so nothing is computed until an action runs. It also guarantees `event_date` is derived from exactly the same parse.

Now run it on the RepoSphere lab file:

```python
events = read_events(spark, "data/events.jsonl")
flat = flatten_events(events)

flat.printSchema()
flat.orderBy("event_id").show(truncate=False)
```

```
root
 |-- event_id: string (nullable = true)
 |-- event_type: string (nullable = true)
 |-- created_ts: timestamp (nullable = true)
 |-- event_date: date (nullable = true)
 |-- repo_id: long (nullable = true)
 |-- actor_login: string (nullable = true)
```

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

This is the verified expected output for the lab. What to check, row by row:

- **e04** is now `pushevent`, the same as its neighbours. It's one push among six.
- **e04 and e05** both show `11:20:00`. Same instant, so we'll need `event_id` as a tie-breaker in Post 07.
- **e09** keeps its row, with `actor_login = null`. Flatten doesn't drop anything. Deciding what to do with a login-less actor is sessionize's job.
- **e08** still points at repo `999`, which has no entry in `repo_changes.jsonl`. Flatten doesn't care. The join in Post 08 will.
- **`created_ts`** prints with a space instead of `T`, and no `Z`. That's how Spark *displays* a timestamp in the session zone (UTC). The value is a real instant now, not text.
- **9 rows in, 9 rows out.** `select` never changes the row count.

> **Why `orderBy("event_id")`?** Only to compare with the expected table. `flatten_events` itself doesn't sort. Sorting is expensive, and the order would be lost by the next shuffle anyway.

---

## Quick Reference ✅

- [ ] Reach into a struct with a dot path: `F.col("repo.id")`
- [ ] Alias **every** struct field and computed column, or you get `id` and `lower(event_type)`
- [ ] Flatten with **one `select`**: the output is exactly what you list
- [ ] `F.lower()` messy categorical strings before anyone groups or filters on them
- [ ] `F.to_timestamp(col)` for ISO 8601. Add a pattern only for other formats
- [ ] Parse first, then `F.to_date(ts)`. Never take a date straight off the string
- [ ] Unparseable timestamps become `null` silently on Spark 3.x. Count the nulls after parsing
- [ ] Set `spark.sql.session.timeZone` to `UTC` in the builder, always
- [ ] Output only the columns the spec lists. Extra columns become collisions at the join

---

## Quick Quiz 🧠

Commit to an answer before you open each one.

**Q1.** Before flattening, `events.filter(F.col("event_type") == "PushEvent").count()` returns what? And after flattening, `flat.filter(F.col("event_type") == "pushevent").count()`?

<details>
<summary>Show answer</summary>

**5**, then **6**. The raw filter misses e04, whose type is spelled `PUSHEVENT`. After `lower()`, all six pushes (e01, e04, e05, e06, e08, e09) share one spelling.

</details>

**Q2.** What does `events.select(F.col("repo.id"), F.col("actor.login")).columns` return?

<details>
<summary>Show answer</summary>

**`['id', 'login']`.** A struct field is named after its last path segment. Without aliases, you lose the context (whose id?), and selecting `actor.id` as well would give you two columns called `id`.

</details>

**Q3.** Your laptop is in Asia/Kolkata and you forgot the time-zone config. An event has `created_at = "2024-03-01T19:00:00Z"`. What `created_ts` does `show()` print, and what is `event_date`? What would a UTC cluster print?

<details>
<summary>Show answer</summary>

Laptop: **`2024-03-02 00:30:00`** and **`2024-03-02`** (19:00 + 5:30 crosses midnight). UTC cluster: **`2024-03-01 19:00:00`** and **`2024-03-01`**. Same instant, different calendar day. This is why the builder sets `spark.sql.session.timeZone` to UTC.

</details>

**Q4.** With the session time zone set to UTC, what are `created_ts` and `event_date` for `"2024-03-01T23:30:00-05:00"` and for `"2024-03-01T03:00:00+05:30"`?

<details>
<summary>Show answer</summary>

- `23:30` at `-05:00` is **`2024-03-02 04:30:00`** UTC, date **2024-03-02**.
- `03:00` at `+05:30` is **`2024-02-29 21:30:00`** UTC, date **2024-02-29**. (2024 is a leap year.)

The date written in the string and the UTC date can differ in **either** direction. That's also why taking the date straight off the string is wrong: it would say 2024-03-01 for both.

</details>

**Q5.** A teammate adds `F.col("repo.name").alias("repo_name")` to `flatten_events` "for convenience". What breaks, and when?

<details>
<summary>Show answer</summary>

Nothing breaks immediately. In Post 08, `enrich_with_repo_state` appends `repo_name` from the SCD2 table, so the joined DataFrame has **two** `repo_name` columns, and any reference to it fails with an ambiguous-reference error. Worse, the event's own copy is just what the logger wrote, not the point-in-time truth. Keep flatten's output to the six spec columns.

</details>

---

## What's Next? 🚀

We now have clean, flat events: six columns, real timestamps, one spelling per event type, and dates that mean the same thing on every machine. But every row still lives alone. It has no idea what came before it or after it.

To build sessions, version histories and "first event per group", each row needs to see its **neighbours**.

👉 **[Post 05 — Window Functions](content/data-engineering/05-window-functions.md)** — `partitionBy` and `orderBy`, tie-breakers, `lag` and `lead`, `row_number` vs `rank` vs `dense_rank`, running totals, and the `rowsBetween` vs `rangeBetween` frame trap.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
