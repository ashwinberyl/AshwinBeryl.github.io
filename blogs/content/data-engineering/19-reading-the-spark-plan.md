---
title: "Reading the Spark Plan — Stages, Shuffles & Partitions"
date: 2026-10-31
tags: [data-engineering, pyspark, performance, explain, spark-ui, shuffle, first-principles]
description: Part 3 begins. Learn to read what Spark actually plans to do with a RepoSphere job - explain(), the Exchange node, stages, tasks, partitions, and why some transformations are cheap (narrow) while others cost a shuffle (wide).
---

# Opening the Hood 🔧

In [Post 18](content/data-engineering/18-capstone-daily-run.md), we finished the pipeline. Eight functions, two parts, every output checked against a script of known answers.

Everything so far was about being **correct**. Part 3 is about being **fast**, and there's a catch: we have only ever run RepoSphere on **nine events**. We've never felt a slow job. A nine-row job finishes before you can blink, however badly it's written.

So before we tune anything, we learn to **see**. Spark doesn't run your code line by line. It turns your DataFrame calls into a **plan**, and that plan is where all the cost lives. If you can read the plan, you can find the expensive step *before* it costs you an hour.

> **A promise for this part:** nothing in these four posts quotes a timing from the nine-row sample. A number from nine rows tells you nothing about a billion. We'll read plans and reason about them here, and in [Post 22](content/data-engineering/22-measure-before-tuning.md) we'll see how to measure properly.

---

## The Restaurant Kitchen 👨‍🍳

Think about a restaurant that gets an order for a hundred meals.

You wouldn't have one cook make all hundred, one at a time. You'd split the work: five cooks each chop, season and cook **their own** share. That part is fast, because nobody needs anybody else.

But then the order says: *"group all the pasta dishes together on one tray per table."* Now every cook has to carry plates across the kitchen to the right table. Everybody waits for everybody. **That's the slow part**, and it's not the cooking. It's the **carrying**.

Spark is that kitchen:

| Kitchen | Spark | Term |
|---|---|---|
| A cook | A core running one piece of work | **Task** |
| One cook's share of the order | A slice of the data | **Partition** |
| Chop, season, cook your own share | `select`, `filter`, `withColumn` | **Narrow** transformation |
| Carry plates to the right table | Move rows between partitions | **Shuffle** |
| "Nobody starts the next step until the carrying is done" | A hard barrier in the plan | **Stage boundary** |

The lesson of this whole post fits in one line: **cooking is cheap, carrying is expensive.** Reading a plan is mostly spotting where the carrying happens.

---

## Meet `explain()` 🔍

Here's a small RepoSphere question: *how many push events did each actor make?* We start from the `flat` DataFrame that `flatten_events` built in [Post 04](content/data-engineering/04-flattening-and-timestamps.md):

```python
from pyspark.sql import functions as F

pushes = (flat
    .filter(F.col("event_type") == "pushevent")   # lowercased in Post 04, so PUSHEVENT counts too
    .groupBy("actor_login")
    .count())
```

Nothing has run. As [Post 02](content/data-engineering/02-spark-from-first-principles.md) taught us, those are all transformations. Spark has only written down a **recipe**.

`explain()` lets you read that recipe without running it:

```python
pushes.explain()
```

```
== Physical Plan ==
AdaptiveSparkPlan isFinalPlan=false
+- HashAggregate(keys=[actor_login#31], functions=[count(1)])
   +- Exchange hashpartitioning(actor_login#31, 200), ENSURE_REQUIREMENTS, [plan_id=45]
      +- HashAggregate(keys=[actor_login#31], functions=[partial_count(1)])
         +- Project [actor#12.login AS actor_login#31]
            +- Filter (isnotnull(event_type#10) AND (lower(event_type#10) = pushevent))
               +- FileScan json [event_type#10,actor#12] ...
```

> **Heads-up:** I trimmed the `FileScan` line to fit the page. The `#31`-style numbers are internal IDs that **change on every run**, so ignore them. What matters is the *shape*: which nodes exist, and in what order.

And for the record, the answer it describes:

```python
pushes.orderBy("actor_login").show()
```

```
+-----------+-----+
|actor_login|count|
+-----------+-----+
|null       |1    |
|dave       |3    |
|jim        |2    |
+-----------+-----+
```

Dave has `e01`, `e04` (the `PUSHEVENT` one) and `e05`. Jim has `e06` and `e08`. And `e09`, the event with no login, forms its own `null` group. `groupBy` doesn't drop nulls, which is why [Post 07](content/data-engineering/07-sessionization-gaps-and-islands.md) had to remove that row on purpose.

---

## How to Read a Plan 📖

**Read it from the bottom up.** The bottom is where data comes from. The top is what you get back.

| Line (bottom to top) | What it means | Cost |
|---|---|---|
| `FileScan json [event_type, actor]` | Read the file. Only the **two columns the query needs** | I/O |
| `Filter (... lower(event_type) = pushevent)` | Keep push events | Cheap, per row |
| `Project [actor.login AS actor_login]` | Pull out the one column we group by | Cheap, per row |
| `HashAggregate ... partial_count(1)` | Count **inside each partition first** | Cheap |
| `Exchange hashpartitioning(actor_login, 200)` | **Shuffle.** Send every row to the partition chosen by its `actor_login` | **Expensive** |
| `HashAggregate ... count(1)` | Add up the partial counts per actor | Cheap |
| `AdaptiveSparkPlan isFinalPlan=false` | Spark may still revise the plan **while running** | n/a |

Three things in that plan are worth a closer look.

### 1. Spark rewrote your code ✨

You wrote `flatten_events`, which builds **six** columns, including `created_ts` and `event_date`. Look at the plan: they're gone. `FileScan` reads only `event_type` and `actor`.

Spark's optimizer noticed that nothing downstream needs the other columns, so it **pruned** them. It also moved your `filter` *below* the `Project`, so rows are dropped as early as possible. You wrote the steps in one order, Spark runs them in a better one.

### 2. The count happens twice 🤝

There are **two** `HashAggregate` nodes with an `Exchange` between them. Why not just shuffle the events and count afterwards?

Because shuffling is the expensive part, so Spark shrinks the data first. Each partition counts its own rows (`partial_count`), and only those small partial results cross the network. On our sample, six push events collapse to three partial rows (`dave 3`, `jim 2`, `null 1`) before anything moves. The second `HashAggregate` just adds up the partials.

### 3. `explain()` is free, mostly 🆓

Because we gave `read_events` an explicit schema in [Post 03](content/data-engineering/03-reading-json-lines-and-schemas.md), calling `explain()` reads no data at all. It only builds and prints the plan.

> **Trap:** If you read JSON *without* a schema, Spark has to scan the file just to infer one, and that scan happens at `read` time, before any action. An innocent `explain()` on an inferred-schema DataFrame can quietly trigger a job. Another reason to keep the explicit contract.

---

## Exchange = Shuffle = Stage Boundary 🚧

That one `Exchange` line is the most important line in the plan. It does three jobs at once:

1. It **moves rows** between partitions, hashed by the key. Every `dave` row must end up in the same partition, wherever it started.
2. It **splits the job into stages.** Everything below an `Exchange` can run without talking to anyone. Everything above it must wait until all of that is finished and written out.
3. It's where Spark **writes to disk and the network.** Shuffle data is written out by one stage and fetched by the next.

![The plan split at the Exchange node into two stages](content/data-engineering/images/plan_to_stages.svg)

That gives us the vocabulary Spark's own tools use:

| Term | Meaning | In our query |
|---|---|---|
| **Job** | The work triggered by one **action** (`show`, `count`, `write`) | One `show()` = one job |
| **Stage** | A stretch of the plan with **no shuffle inside it** | Stage 1 (scan to partial count), stage 2 (final count) |
| **Task** | One stage run on **one partition** | One per partition, per stage |
| **Partition** | One slice of the data | Input file splits, then shuffle partitions |

> **Key insight:** The number of stages is simply the number of `Exchange` nodes **plus one**. You don't need a profiler to count them. You need `explain()` and a pair of eyes.

---

## Narrow vs Wide 🛣️

Why does `filter` never cause an `Exchange`, while `groupBy` always does?

Because of what each one needs to know. A `filter` looks at **one row** and decides keep or drop. It can do that in whatever partition the row already sits in. A `groupBy` needs **all the rows with the same key together**, and those rows might be scattered across every partition.

![Narrow transformations keep each partition separate; wide ones send every partition to every other](content/data-engineering/images/narrow_vs_wide.svg)

| | **Narrow** | **Wide** |
|---|---|---|
| **Each output partition depends on** | One input partition | **Many** input partitions |
| **Shuffle?** | No | **Yes** (`Exchange`) |
| **Stage boundary?** | No, pipelined into one stage | **Yes** |
| **RepoSphere examples** | `select`, `withColumn`, `filter`, `lower`, `to_timestamp`, `alias` | `groupBy`, `orderBy`, `distinct`, `Window.partitionBy(...)`, most joins |
| **Cost** | Proportional to the rows | Rows **plus** network, disk, and waiting |

A useful habit: when you read your own pipeline code, **circle every wide operation.** In RepoSphere they're easy to find, because we've met each one:

| Pipeline step | Wide operation | What the plan shows |
|---|---|---|
| `build_repo_scd2` (Post 06) | `Window.partitionBy("repo_id")` | An `Exchange` hashed on `repo_id`, then a `Sort` and a `Window` node |
| `sessionize_actor_events` (Post 07) | `Window.partitionBy("actor_login")` | An `Exchange` hashed on `actor_login` |
| `enrich_with_repo_state` (Post 08) | A join, **but** the dimension is broadcast | A `BroadcastExchange` of the small side. The big events side **doesn't shuffle** |
| `compute_session_summary` (Post 09) | `groupBy("actor_login", "session_id")` | An `Exchange` hashed on both keys |
| Any `orderBy(...).show()` | Global sort | An `Exchange rangepartitioning` |

Notice what the broadcast in [Post 08](content/data-engineering/08-point-in-time-joins.md) really bought us. We said then it was "a performance hint only". Now you can see *why*: it turns a join that would have needed an `Exchange` on the big side into one that doesn't.

> **Why this matters:** In an `explain()` of the full pipeline, find the wide steps and ask: *how many rows reach this `Exchange`?* A shuffle in front of 9 rows is free. The same shuffle in front of a billion rows is your whole bill. That's the question the rest of Part 3 is about.

---

## The Number 200 🔢

Look back at the plan: `Exchange hashpartitioning(actor_login#31, 200)`.

That `200` is `spark.sql.shuffle.partitions`, and its default is **200**, no matter how big your data is. Run our query as is and, before any optimization, stage 2 has 200 tasks, even though there are only **three** distinct actors. At most three of those partitions can hold a row.

That's the cost of a one-size-fits-all default:

| Data size | 200 shuffle partitions means | Effect |
|---|---|---|
| Tiny (our sample) | Almost every task has nothing to do | Wasted scheduling |
| Reasonable | A good spread | Fine |
| Huge | Each partition may be enormous | Memory pressure, spills to disk |

You can change it and watch the plan respond:

```python
spark.conf.set("spark.sql.shuffle.partitions", "4")
pushes.explain()
```

```
+- Exchange hashpartitioning(actor_login#31, 4), ENSURE_REQUIREMENTS, [plan_id=45]
```

(Only the changed line is shown. The rest of the plan is identical.)

Don't over-read that, though. The `AdaptiveSparkPlan` node at the top means **Adaptive Query Execution (AQE)** is switched on, which is the default in modern Spark. AQE looks at the *real* size of each shuffle partition once stage 1 finishes, and merges the tiny ones. That's why the plan says `isFinalPlan=false`: the plan you print before running is a **first draft**. After an action has run, `explain()` shows the final one, and you'll see the coalescing there.

We'll come back to partition counts, and to how they decide how many files you write, in [Post 21](content/data-engineering/21-small-files-and-partitioning.md).

---

## Reading the Same Story in the Spark UI 🖥️

`explain()` shows you the *plan*. The **Spark UI** shows you the *run*. While a session is alive, it's at `http://localhost:4040`.

Our scripts call `spark.stop()` at the end, which closes the UI with it. To poke around, pause before stopping:

```python
pushes.orderBy("actor_login").show()
input("Spark UI is at http://localhost:4040 - press Enter to finish")
spark.stop()
```

You'll mostly use three tabs:

| Tab | What to look at | The question it answers |
|---|---|---|
| **SQL / DataFrame** | The query as a graph of boxes. It's the same shape as `explain()`, with row counts on each arrow | *Where did the rows go?* |
| **Jobs** | One entry per action, with its stages | *Which action triggered this?* |
| **Stages** | **Shuffle Write** of one stage, **Shuffle Read** of the next, and the **task table** (min, median, max duration) | *Where is the carrying, and is it even?* |

The row counts on the SQL tab are the best teaching tool there is. Follow the arrows through RepoSphere's `pushes` query and you'll see exactly what we traced by hand: nine rows out of the scan, six after the filter, three after the partial aggregate.

And the task table hides the next problem in this series. If most tasks in a stage take about the same time but **one** takes far longer, that's a sign the keys aren't spread evenly: one partition got more than its share. That's **skew**, and it's the whole story of [Post 20](content/data-engineering/20-joins-and-skew.md).

---

## Your Plan-Reading Checklist ✅

Before you tune anything, do these five things in order:

1. **Call `explain()`** on the final DataFrame. It's free.
2. **Read bottom-up.** What's scanned? Which columns? Which filters?
3. **Circle every `Exchange`.** Each is a shuffle and a stage boundary.
4. **For each one, ask what's being shuffled.** Which key? How many rows are about to cross?
5. **Look for what Spark already fixed for you.** Pruned columns, pushed filters, broadcast joins. Don't "optimize" what the optimizer already did.

> **Trap:** A filter wrapped in a function, like `lower(event_type) = 'pushevent'`, usually **can't be pushed down to the data source**. Spark can only hand a source simple comparisons between a bare column and a literal. For a JSON file that doesn't matter, because the whole file is read anyway. For Parquet and Iceberg tables, it decides whether Spark can skip whole files. Where a pipeline has a choice, keep the column bare: store the lowercased value once, as we did in `flatten_events`, and compare against it.

---

## Quick Quiz 🧠

**Q1.** You read a plan and find three `Exchange` nodes. How many stages does the job have, and what is it that separates them?

<details>
<summary>Show answer</summary>

**Four** stages: three `Exchange` nodes plus one. Each `Exchange` is a shuffle, and a shuffle is a hard boundary. Everything below it must finish and write its output before the stage above it can start reading.

</details>

**Q2.** Which of these is **wide**, and which is **narrow**: `withColumn("event_type", F.lower("event_type"))`, `Window.partitionBy("actor_login").orderBy("created_ts")`, `filter(F.col("actor_login").isNotNull())`, `groupBy("repo_id").count()`?

<details>
<summary>Show answer</summary>

`withColumn(... lower ...)` and `filter(... isNotNull())` are **narrow**: each row is handled where it already sits. The **window** and the **groupBy** are **wide**: they must bring every row with the same `actor_login` (or `repo_id`) into one partition, so they need an `Exchange`.

</details>

**Q3.** Why does the plan for `pushes` contain two `HashAggregate` nodes, one marked `partial_count` and one `count`?

<details>
<summary>Show answer</summary>

Spark counts **inside each partition first**, so only small partial results have to cross the shuffle. Here, six push events become three partial rows (`dave 3`, `jim 2`, `null 1`) before anything moves. The second aggregate, after the `Exchange`, adds the partials up. Shrinking data **before** a shuffle is one of the cheapest wins Spark gives you for free.

</details>

**Q4.** Your plan shows `Exchange hashpartitioning(actor_login, 200)`, but the data has only three actors. How many of the 200 shuffle partitions can hold a row, and what does that tell you about the default?

<details>
<summary>Show answer</summary>

At most **three**. Each distinct key hashes to exactly one partition, so three keys fill three partitions at most, and the other 197 are empty. It shows `spark.sql.shuffle.partitions = 200` is a fixed default that knows nothing about your data. AQE can merge the empty ones at run time, but the number you see in a plan printed *before* the run is just the starting setting.

</details>

**Q5.** `flatten_events` builds six columns, but the `FileScan` in the `pushes` plan lists only two. Did Spark skip part of your code?

<details>
<summary>Show answer</summary>

Yes, and that's correct. The optimizer **pruned** the columns nothing downstream uses (`created_ts`, `event_date`, `repo_id` and so on), so they're never computed. The result is the same, with less work. It's also why you should read the plan before hand-optimizing: Spark may have already done what you were about to.

</details>

---

## What's Next? 🚀

You can now open any Spark job and read its story: which nodes it has, where the shuffles are, and how they split the work into stages and tasks. You also know the two numbers that decide most of the cost, **how many rows reach an `Exchange`** and **how evenly its keys spread**.

Next, we look at the second one. RepoSphere has one hugely busy actor, and a join on that actor turns one task into the slowest thing in the whole job. We'll compare broadcast and sort-merge joins, and see how salting and AQE deal with skew.

👉 **[Post 20: Joins and Skew](content/data-engineering/20-joins-and-skew.md)**

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
