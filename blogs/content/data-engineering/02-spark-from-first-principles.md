---
title: "Spark from First Principles — DataFrames, Lazy Evaluation & the NULL Trap"
date: 2026-10-11
tags: [data-engineering, pyspark, spark, dataframes, lazy-evaluation, null, first-principles]
description: Why Spark exists, what a DataFrame really is, why nothing runs until you ask for a result, the five verbs you'll use in every pipeline, and the NULL trap that silently deletes rows — all on the RepoSphere events.
---

# Why Plain Python Stops Working 🐍➡️⚡

In [Post 01](content/data-engineering/01-what-is-data-engineering.md), we met RepoSphere and looked at its events with plain Python. Nine events, a `Counter`, a `sorted()` — done in milliseconds.

Now imagine RepoSphere is real. **9 billion events a day.**

Your laptop has maybe 16 GB of memory. One day of events is a few terabytes. `json.loads(line) for line in f` would run for hours — and then crash when the list no longer fits in memory.

You don't need a faster laptop. You need **many machines working on the data at the same time**, without you having to write the code that splits the work, ships it around, and stitches the results back together.

That's exactly what **Apache Spark** does. And the beautiful part: the code you write for 9 rows is the *same code* that runs on 9 billion.

---

## The Kitchen Analogy 👨‍🍳

Think of a busy restaurant kitchen.

- The **head chef** doesn't cook every dish. They read the orders, plan the work, and hand out tasks.
- The **cooks** each take a share of the work and do it in parallel.
- The **ingredients** are split across stations, so each cook only handles their portion.

Spark is organised the same way:

| Kitchen | Spark | What it does |
|---|---|---|
| Head chef | **Driver** | Runs your Python code, builds the plan, hands out tasks |
| Cooks | **Executors** | Worker processes that actually crunch the data |
| Each cook's share of ingredients | **Partition** | A chunk of the rows, processed by one task |
| The full order | **DataFrame** | All partitions together, as one logical table |

![How Spark splits one job across many machines](content/data-engineering/images/spark_driver_executors.svg)

> **Key insight:** You never write "send rows 1–1,000,000 to machine 3". You describe *what* you want done to the table, and Spark decides *how* to split it. That's the whole deal.

On your laptop, `master("local[*]")` makes the driver and executors threads on one machine — one per CPU core. Same code, smaller kitchen.

---

## Setting Up 🛠️

```bash
pip install pyspark      # needs Java 17 (or 21) installed
```

Every Spark program starts with a **SparkSession** — your connection to the kitchen:

```python
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

spark = (SparkSession.builder
         .appName("reposphere")
         .master("local[*]")                               # use every core on this machine
         .config("spark.sql.session.timeZone", "UTC")      # reproducible dates (Post 04)
         .getOrCreate())
```

`functions` is imported as `F` by convention. Almost every column operation you write will start with `F.`

---

## What Is a DataFrame? 📋

A **DataFrame** is a table with named, typed columns — spread across partitions. For now, let's build one by hand from the RepoSphere events, already flattened (Posts 03 and 04 will do this properly from the raw file):

```python
rows = [
    ("e01", "PushEvent",        "priya", 101, "2024-03-01T09:50:00Z"),
    ("e02", "PullRequestEvent", "priya", 202, "2024-03-01T10:10:00Z"),
    ("e03", "IssuesEvent",      "priya", 101, "2024-03-01T10:40:00Z"),
    ("e05", "PushEvent",        "priya", 202, "2024-03-01T11:20:00Z"),
    ("e04", "PUSHEVENT",        "priya", 101, "2024-03-01T11:20:00Z"),
    ("e06", "PushEvent",        "rahul", 202, "2024-03-01T10:15:00Z"),
    ("e07", "IssuesEvent",      "rahul", 202, "2024-03-01T10:35:00Z"),
    ("e08", "PushEvent",        "rahul", 999, "2024-03-01T12:30:00Z"),
    ("e09", "PushEvent",        None,    101, "2024-03-01T10:00:00Z"),   # no login!
]
events = spark.createDataFrame(
    rows, ["event_id", "event_type", "actor_login", "repo_id", "created_at"])

events.printSchema()
events.show(truncate=False)
```

```
root
 |-- event_id: string (nullable = true)
 |-- event_type: string (nullable = true)
 |-- actor_login: string (nullable = true)
 |-- repo_id: long (nullable = true)
 |-- created_at: string (nullable = true)
```

```
+--------+----------------+-----------+-------+--------------------+
|event_id|event_type      |actor_login|repo_id|created_at          |
+--------+----------------+-----------+-------+--------------------+
|e01     |PushEvent       |priya      |101    |2024-03-01T09:50:00Z|
|e02     |PullRequestEvent|priya      |202    |2024-03-01T10:10:00Z|
|e03     |IssuesEvent     |priya      |101    |2024-03-01T10:40:00Z|
|e05     |PushEvent       |priya      |202    |2024-03-01T11:20:00Z|
|e04     |PUSHEVENT       |priya      |101    |2024-03-01T11:20:00Z|
|e06     |PushEvent       |rahul      |202    |2024-03-01T10:15:00Z|
|e07     |IssuesEvent     |rahul      |202    |2024-03-01T10:35:00Z|
|e08     |PushEvent       |rahul      |999    |2024-03-01T12:30:00Z|
|e09     |PushEvent       |null       |101    |2024-03-01T10:00:00Z|
+--------+----------------+-----------+-------+--------------------+
```

Three things to notice already:

- Python's `None` became Spark's **`null`** — "no value here".
- Python `int` became **`long`** (a 64-bit integer).
- `created_at` is still just a **string**. Spark doesn't know it's a time yet. We'll fix that in Post 04.

### DataFrames are immutable

You **never change a DataFrame in place**. Every operation returns a *new* DataFrame and leaves the original untouched:

```python
lowered = events.withColumn("event_type", F.lower("event_type"))
# `events` still has "PUSHEVENT" — `lowered` is a brand-new DataFrame
```

> **Why immutable?** If a machine dies halfway through a job, Spark can rebuild the lost partition by replaying the steps from the original data. That only works if no step ever overwrote its input.

---

## Lazy Evaluation — Nothing Runs Until You Ask 💤

Here's the part that surprises everyone coming from pandas.

```python
clean = (events
    .withColumn("event_type", F.lower("event_type"))
    .filter(F.col("actor_login").isNotNull())
    .drop("created_at"))
```

This line returns **instantly** — even on 9 billion rows. Not because Spark is fast, but because it **hasn't done anything yet**.

Back to the kitchen: the head chef has written the order ticket, but nobody has started cooking. Spark only starts work when you ask for an actual result.

Operations come in two kinds:

| Kind | What it does | Examples |
|---|---|---|
| **Transformation** | Adds a step to the plan. Returns a new DataFrame. Reads no data. | `select`, `withColumn`, `filter`, `drop`, `groupBy`, `join` |
| **Action** | Runs the whole plan and produces a result. | `show()`, `count()`, `collect()`, `write` |

![Lazy evaluation: transformations write the order, actions cook it](content/data-engineering/images/spark_lazy_evaluation.svg)

> **Why lazy?** Because seeing the *whole* plan before running it lets Spark optimise it. It can push your `filter` down to the moment the file is read, skip columns you `drop`ped, and combine steps so each row is touched once. You write readable step-by-step code; Spark runs the efficient version.

> **Trap:** Lazy also means **errors show up late**. A typo in a column name inside a long chain may only surface when you finally call `show()` — which is why you'll test each function on its own.

---

## The Five Verbs You'll Use Constantly 🧰

Ninety percent of the RepoSphere pipeline is built from five operations:

| Verb | What it does | Keeps other columns? |
|---|---|---|
| `select(...)` | Pick, compute and rename columns | **No** — output has *only* what you list |
| `withColumn(name, expr)` | Add a column, or **overwrite** one with the same name | Yes |
| `filter(condition)` | Keep rows where the condition is **true** | Yes |
| `.alias(name)` | Name a computed column | — |
| `drop(...)` | Remove columns (helpers, mostly) | Yes |

Let's run the `clean` plan from above, plus one new column:

```python
clean = (events
    .withColumn("event_type", F.lower("event_type"))                  # overwrite in place
    .withColumn("is_push", F.col("event_type") == "pushevent")         # add a boolean column
    .filter(F.col("actor_login").isNotNull())                          # drop the event with no login
    .drop("created_at"))                                               # don't need it here

clean.show(truncate=False)
```

```
+--------+----------------+-----------+-------+-------+
|event_id|event_type      |actor_login|repo_id|is_push|
+--------+----------------+-----------+-------+-------+
|e01     |pushevent       |priya      |101    |true   |
|e02     |pullrequestevent|priya      |202    |false  |
|e03     |issuesevent     |priya      |101    |false  |
|e05     |pushevent       |priya      |202    |true   |
|e04     |pushevent       |priya      |101    |true   |
|e06     |pushevent       |rahul      |202    |true   |
|e07     |issuesevent     |rahul      |202    |false  |
|e08     |pushevent       |rahul      |999    |true   |
+--------+----------------+-----------+-------+-------+
```

- `PUSHEVENT` (e04) is now `pushevent` — the problem from Post 01 is gone.
- `e09` disappeared — its `actor_login` was null.
- `created_at` is gone; `is_push` is new.

### Why `.alias()` matters

Compute a column inside `select` without naming it, and Spark invents a name for you:

```python
events.select("event_id", F.upper("actor_login")).show(3, truncate=False)
```

```
+--------+------------------+
|event_id|upper(actor_login)|
+--------+------------------+
|e01     |PRIYA             |
|e02     |PRIYA             |
|e03     |PRIYA             |
+--------+------------------+
only showing top 3 rows
```

A column literally called `upper(actor_login)`. Any test or downstream step looking for `actor_login` won't find it. Always name computed columns:

```python
events.select("event_id", F.upper("actor_login").alias("actor_login"))
```

> **Key insight:** `select` is a whitelist — anything you don't list is gone. `withColumn` is surgical — it touches one column and keeps the rest. Pick based on whether you're *shaping* the output or *patching* one column.

---

## The NULL Trap ⚠️

This one silently deletes data in real pipelines every day. Let's say you want every event that *has* a login. Coming from Python, this looks right:

```python
events.filter(F.col("actor_login") != None).count()
```

```
0
```

**Zero.** Not 8. Every single row vanished.

### Why? Three-valued logic

`F.col("actor_login") != None` isn't Python. It builds the SQL expression `actor_login != NULL`. And in SQL, **any comparison with NULL is NULL** — not true, not false, but *unknown*.

| Expression | Result |
|---|---|
| `'priya' != 'rahul'` | `true` |
| `'priya' != 'priya'` | `false` |
| `'priya' != NULL` | **`null`** |
| `NULL != NULL` | **`null`** |
| `NULL = NULL` | **`null`** (not true!) |

And `filter` keeps **only** rows where the condition is `true`. Both `false` *and* `null` rows are dropped. Since every row compared against NULL gives `null`, every row is dropped.

The fix — always use the dedicated null checks:

```python
events.filter(F.col("actor_login").isNotNull()).count()
```

```
8
```

| Never write | Always write |
|---|---|
| `F.col("x") == None` | `F.col("x").isNull()` |
| `F.col("x") != None` | `F.col("x").isNotNull()` |

### The sneakier version

Now the one that even experienced engineers miss. Find every event *not* by priya:

```python
events.filter(F.col("actor_login") != "priya").show(truncate=False)
```

```
+--------+----------------+-----------+-------+--------------------+
|event_id|event_type      |actor_login|repo_id|created_at          |
+--------+----------------+-----------+-------+--------------------+
|e06     |PushEvent       |rahul      |202    |2024-03-01T10:15:00Z|
|e07     |IssuesEvent     |rahul      |202    |2024-03-01T10:35:00Z|
|e08     |PushEvent       |rahul      |999    |2024-03-01T12:30:00Z|
+--------+----------------+-----------+-------+--------------------+
```

Where's `e09`? Its actor definitely isn't priya. But `NULL != 'priya'` is `null`, so `filter` dropped it. If you genuinely want "not priya, including unknowns", say so:

```python
events.filter((F.col("actor_login") != "priya") | F.col("actor_login").isNull()) \
      .select("event_id", "actor_login", "repo_id").show(truncate=False)
```

```
+--------+-----------+-------+
|event_id|actor_login|repo_id|
+--------+-----------+-------+
|e06     |rahul      |202    |
|e07     |rahul      |202    |
|e08     |rahul      |999    |
|e09     |null       |101    |
+--------+-----------+-------+
```

> **Trap:** Whenever a column can be null, ask: *"What should happen to the null rows?"* If you don't decide, `filter` decides for you — and it always drops them.

---

## Combining Conditions: `&`, `|`, `~` 🔗

Python's `and`, `or` and `not` don't work on Spark columns. Use the operators instead — and **wrap every condition in parentheses**:

| Python | Spark columns |
|---|---|
| `a and b` | `(a) & (b)` |
| `a or b` | `(a) \| (b)` |
| `not a` | `~(a)` |

Why the parentheses? In Python, `&` binds *tighter* than `>` or `<`. So this:

```python
events.filter(F.col("repo_id") > 100 & F.col("repo_id") < 300)
```

is read by Python as `F.col("repo_id") > (100 & F.col("repo_id")) < 300` — a chained comparison, which forces Python to treat a Column as `True`/`False`:

```
ValueError: Cannot convert column into bool: please use '&' for 'and', '|' for 'or', '~' for 'not' when building DataFrame boolean expressions.
```

With parentheses, it works:

```python
events.filter((F.col("repo_id") > 100) & (F.col("repo_id") < 300))
```

> **Key insight:** That error message is your friend — it tells you *exactly* what to fix. The silent failures are the NULL ones. Those never raise an error; they just give you fewer rows.

---

## Putting It Together 🧩

One small, real question for RepoSphere: **how many pushes did each developer make?**

```python
pushes = (events
    .withColumn("event_type", F.lower("event_type"))
    .filter((F.col("event_type") == "pushevent") & F.col("actor_login").isNotNull())
    .groupBy("actor_login").count()
    .orderBy("actor_login"))

pushes.show()
```

```
+-----------+-----+
|actor_login|count|
+-----------+-----+
|      priya|    3|
|      rahul|    2|
+-----------+-----+
```

(Notice the values are right-aligned — that's the default `show()`. With `truncate=False` they're left-aligned, which is easier to read for strings. Same data either way.)

Now remove the `lower()` line and filter on `"PushEvent"` instead:

```
+-----------+-----+
|actor_login|count|
+-----------+-----+
|      priya|    2|
|      rahul|    2|
+-----------+-----+
```

priya lost a push — `e04` was spelt `PUSHEVENT`. **No error. Just a wrong number.** That's what data quality bugs look like: the job succeeds, the dashboard renders, and the answer is quietly off.

---

## Quick Reference ✅

- [ ] DataFrames are **immutable** — every operation returns a new one
- [ ] **Transformations** build a plan; **actions** (`show`, `count`, `collect`, `write`) run it
- [ ] `select` keeps only what you list; `withColumn` changes one column and keeps the rest
- [ ] Always `.alias()` computed columns
- [ ] Never compare with `None` — use `.isNull()` / `.isNotNull()`
- [ ] `filter` drops `false` **and** `null` rows — decide what nulls should do
- [ ] Combine conditions with `&`, `|`, `~`, with **every condition in parentheses**

---

## Quick Quiz 🧠

Commit to an answer before you open each one.

**Q1.** You run `big = events.filter(F.col("repo_id") == 101)` on a 5 TB table. It returns in 50 milliseconds. Is Spark incredibly fast?

<details>
<summary>Show answer</summary>

No — it hasn't done anything yet. `filter` is a **transformation**; it only adds a step to the plan. The 5 TB are read only when you call an **action** like `count()` or `show()`.

</details>

**Q2.** How many rows does `events.filter(F.col("actor_login") == "priya")` return? And `events.filter(~(F.col("actor_login") == "priya"))`?

<details>
<summary>Show answer</summary>

**5** and **3**. The first keeps priya's five events. The second keeps rahul's three — but **not e09**. For e09, `NULL == 'priya'` is `null`, and `~null` is still `null`, so it's dropped by *both* filters. 5 + 3 = 8, not 9. One row fell through the gap.

</details>

**Q3.** What's the difference between these two lines?

```python
events.select(F.lower("event_type").alias("event_type"))
events.withColumn("event_type", F.lower("event_type"))
```

<details>
<summary>Show answer</summary>

The first returns a DataFrame with **one column** — `select` only keeps what you list. The second returns **all five columns**, with `event_type` lowercased in place.

</details>

**Q4.** Why does this raise an error, and how do you fix it?

```python
events.filter(F.col("is_push") and F.col("repo_id") == 101)
```

<details>
<summary>Show answer</summary>

Python's `and` tries to turn the first Column into `True`/`False`, which Spark refuses — `ValueError: Cannot convert column into bool`. Fix: `events.filter((F.col("is_push")) & (F.col("repo_id") == 101))`. (It would also fail for a second reason: `events` has no `is_push` column — that only exists on `clean`!)

</details>

**Q5.** A teammate writes `events.filter(F.col("actor_login") != None)` and the job succeeds with 0 output rows. Why didn't Spark raise an error?

<details>
<summary>Show answer</summary>

Because nothing is *invalid*. `actor_login != NULL` is a perfectly legal SQL expression — it just evaluates to `null` for every row, and `filter` drops `null`. Spark did exactly what it was told. That's what makes NULL bugs so dangerous: they're silent.

</details>

---

## What's Next? 🚀

We built today's DataFrame by hand, with every field already flat and every type already right. Real data doesn't arrive like that. It arrives as raw JSON Lines — nested, incomplete, and sometimes missing a field on *every* line.

👉 **[Post 03 — Reading JSON Lines & Schemas](content/data-engineering/03-reading-json-lines-and-schemas.md)** — `read_events` and `read_repo_changes`, why schema inference is a trap, and how an explicit schema becomes a contract the rest of the pipeline can trust.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
