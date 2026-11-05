---
title: "Joins and Skew — When One Key Is Too Busy"
date: 2026-11-01
tags: [data-engineering, pyspark, performance, joins, skew, broadcast, salting, aqe, first-principles]
description: Part 3, post 2. How Spark picks between broadcast and sort-merge joins on RepoSphere data, why one hot actor_login turns a single task into the slowest thing in the job, and the three ways out - broadcast the small side, let AQE split the skewed partition, or salt the key yourself.
---

# The One Slow Task 🐌

In [Post 19](content/data-engineering/19-reading-the-spark-plan.md), we learned to read a plan: circle every `Exchange`, then ask *how many rows reach it* and *how evenly its keys spread*.

This post is about the second question. It's the one that bites in production, and it never shows up on a nine-row sample.

Here's the pattern. Your job runs fine for weeks. Then a bot starts pushing to a thousand repos an hour, or a team migrates a monorepo, and one `actor_login` suddenly owns most of the traffic. The job doesn't crash. It just sits at "199 of 200 tasks complete" for an hour, and you stare at the last one.

That's **skew**. And joins are where it hurts most, because a join has to put every row with the same key in the same place.

---

## The Supermarket Checkout 🛒

Picture a supermarket with 200 checkout lanes and a rule: **your lane is decided by your surname.** Everyone called Smith goes to lane 17. Always.

On a normal day, shoppers spread out across the lanes and everyone's done in minutes. Then one family called Smith arrives with six hundred thousand items.

You can open all the other lanes you like. Lane 17 is still scanning, and **the store can't close until it's done.**

| Supermarket | Spark |
|---|---|
| A lane | A shuffle partition, worked by one **task** |
| Surname decides the lane | `hash(join key) % number_of_partitions` |
| The giant family | One **hot key** (`dave`, in our case) |
| "We close when the last lane is empty" | A stage finishes when its **slowest task** finishes |

Adding lanes doesn't help, because the rule says all the Smiths use lane 17. The fix has to change **the rule**, or take the Smiths' trolley out of the normal queue. Both fixes appear below.

---

## Two Ways to Join 🤝

Before skew, we need to know what a join physically does. Spark has a few strategies, and two matter day to day.

| | **Broadcast hash join** | **Sort-merge join** |
|---|---|---|
| **Idea** | Copy the **small** table to every executor. Each task looks up keys in memory | Shuffle **both** tables by the key, sort each partition, walk them in step |
| **Shuffles the big side?** | **No** | **Yes**, and the small side too |
| **Plan nodes** | `BroadcastExchange` + `BroadcastHashJoin` | Two `Exchange` + two `Sort` + `SortMergeJoin` |
| **Used when** | One side is under `spark.sql.autoBroadcastJoinThreshold` (default **10 MB**), or you hint it | Both sides are big. It's the default for big-vs-big equi-joins |
| **Skew risk** | **None** for the big side: its rows never move | **High**: all rows for one key land in one partition |
| **Weakness** | The small side must really fit in memory, on the driver and on every executor | Needs a full shuffle and sort of both sides |

![Broadcast hash join copies the small table to every executor while the big table stays put; sort-merge join shuffles both tables by key](content/data-engineering/images/join_strategies.svg)

Two more exist, and you'll meet them in plans: a **shuffle hash join** (shuffle both, but build a hash table instead of sorting, rarely chosen by default) and the **broadcast nested loop join**, which is what you get when there is *no* equality in the join condition. It compares every pair of rows. If you see it on a big table, something is wrong.

> **Key insight:** You already used a broadcast join. In [Post 08](content/data-engineering/08-point-in-time-joins.md), `enrich_with_repo_state` joined events to `repo_scd2` on `repo_id` **plus** a range. Because there was an equality (`repo_id`), Spark could use a hash join and treat the range as an extra check on each match. And because we broadcast the small dimension, the big events side **never shuffled**. That join cannot be skewed, whichever repo is the busiest.

---

## A New Join: Who's on Which Team? 👥

Product has a new ask: tag every event with the **team** its actor belongs to. We'll invent a tiny `actors` dimension for this post:

```python
actors = spark.createDataFrame(
    [("dave", "platform"), ("jim", "web")],
    ["actor_login", "team"])

joined = flat.join(actors, "actor_login", "left")

(joined.select("event_id", "actor_login", "team")
       .orderBy("event_id")
       .show(truncate=False))
```

```
+--------+-----------+--------+
|event_id|actor_login|team    |
+--------+-----------+--------+
|e01     |dave       |platform|
|e02     |dave       |platform|
|e03     |dave       |platform|
|e04     |dave       |platform|
|e05     |dave       |platform|
|e06     |jim        |web     |
|e07     |jim        |web     |
|e08     |jim        |web     |
|e09     |null       |null    |
+--------+-----------+--------+
```

Nine events in, nine rows out. It's a **left** join, so every fact is kept, the same rule as [Post 08](content/data-engineering/08-point-in-time-joins.md). And e09, the event with no login, gets a null team. From [Post 02](content/data-engineering/02-spark-from-first-principles.md): `null = 'dave'` is never true, so a null key matches nothing.

Because `actors` is two rows, Spark broadcasts it on its own. Here is the shape of the plan (trimmed, and the `#` IDs change on every run):

```
== Physical Plan ==
AdaptiveSparkPlan isFinalPlan=false
+- BroadcastHashJoin [actor_login#31], [actor_login#52], LeftOuter, BuildRight
   :- Project [event_id#9, actor#12.login AS actor_login#31]
   :  +- FileScan json [event_id#9,actor#12] ...
   +- BroadcastExchange HashedRelationBroadcastMode(...)
      +- LocalTableScan [actor_login#52, team#53]
```

No `Exchange` on the events side. Now force the other strategy, to see what *would* happen if both tables were big:

```python
spark.conf.set("spark.sql.autoBroadcastJoinThreshold", "-1")   # never broadcast
flat.join(actors, "actor_login", "left").explain()
```

```
== Physical Plan ==
AdaptiveSparkPlan isFinalPlan=false
+- SortMergeJoin [actor_login#31], [actor_login#52], LeftOuter
   :- Sort [actor_login#31 ASC NULLS FIRST], false, 0
   :  +- Exchange hashpartitioning(actor_login#31, 200), ENSURE_REQUIREMENTS
   :     +- Project ...
   +- Sort [actor_login#52 ASC NULLS FIRST], false, 0
      +- Exchange hashpartitioning(actor_login#52, 200), ENSURE_REQUIREMENTS
         +- LocalTableScan [actor_login#52, team#53]
```

Same answer, very different plan. Two `Exchange` nodes, both hashed on `actor_login`. Each distinct login now goes to **exactly one** partition. That one sentence is the entire cause of skew.

---

## What Skew Looks Like 📊

Count the rows per key in the nine-event sample:

```python
flat.groupBy("actor_login").count().orderBy(F.desc("count")).show()
```

```
+-----------+-----+
|actor_login|count|
+-----------+-----+
|dave       |5    |
|jim        |3    |
|null       |1    |
+-----------+-----+
```

Dave has more than half the rows. Whichever partition his key hashes to must hold **at least five of the nine**. That's a tiny version of the problem, and it's too small to measure, so let's scale the *shape* up.

The script below generates a million RepoSphere-style push events, where `dave` makes **60%** of them and 199 other actors share the rest. The seed is fixed, so you'll get the same counts:

```python
import json, random
from collections import Counter

random.seed(42)
N = 1_000_000
actors = ["dave"] + [f"user{i:03d}" for i in range(1, 200)]     # 200 actors
weights = [0.60] + [0.40 / 199] * 199                          # dave = 60% of traffic

counts = Counter()
with open("skewed_events.jsonl", "w") as f:
    for i in range(1, N + 1):
        a = random.choices(actors, weights)[0]
        counts[a] += 1
        f.write(json.dumps({"event_id": f"x{i:07d}", "event_type": "PushEvent",
                            "repo": {"id": 101 + i % 50}, "actor": {"login": a}}) + "\n")

print(counts.most_common(3))
print("total:", sum(counts.values()), "| actors:", len(counts))
print("median rows per actor:", sorted(counts.values())[len(counts) // 2])
```

```
[('dave', 599741), ('user104', 2165), ('user183', 2146)]
total: 1000000 | actors: 200
median rows per actor: 2013
```

Read those numbers slowly:

| | Rows |
|---|---|
| `dave` | **599,741** |
| The next-busiest actor (`user104`) | 2,165 |
| The median actor | 2,013 |
| An even spread over 200 shuffle partitions | 5,000 |

Dave's partition holds **at least 599,741 rows**, about **300 times** the median actor and at least **120 times** an even share. The other 199 tasks finish quickly and sit idle. The stage is as slow as the one task that has Dave in it.

![Rows per key for the nine-event sample: dave 5, jim 3, null 1. The task holding the biggest key sets the length of the stage](content/data-engineering/images/skewed_partitions.svg)

> **A note on honesty:** This post gives no timings. I haven't run this dataset on a cluster, so I won't invent a "47 seconds to 9 seconds" story. What we *can* say for certain is arithmetic: the work in the slowest task is at least the rows of the hottest key. [Post 22](content/data-engineering/22-measure-before-tuning.md) is about measuring this properly.

### How you spot it in the Spark UI 🔎

Open the **Stages** tab, pick the stage after the `Exchange`, and look at the **summary metrics** for its tasks (min, 25th percentile, median, 75th percentile, max):

| Metric | Healthy | Skewed |
|---|---|---|
| **Duration** | Max is close to the median | Max is **many times** the median |
| **Shuffle Read Size / Records** | Similar across tasks | One task reads far more than the rest |
| **Spill (memory / disk)** | Usually none | Often appears on the one big task only |

The signature is always the same: *a flat line, with one spike.*

---

## The Null Key Is a Hot Key Too 🕳️

Look back at the sample. `e09` has no `actor.login`, so its `actor_login` is **null**.

In a shuffle, the partition is chosen by hashing the key, and null hashes to one fixed value. So **every null-key row in the table lands in the same partition**. In RepoSphere's sample that's one row. In a real feed where some fraction of events has no actor (deleted accounts, system events), it can be the *largest* key in the table.

How Spark treats it depends on the join type:

| Join | What happens to the null-key rows |
|---|---|
| **Inner** | Spark adds `isnotnull(actor_login)` below the join. Null rows are dropped **before** the shuffle |
| **Left** (facts on the left) | Nulls must be kept, so they **shuffle together** into one partition, match nothing, and come out with a null `team` |

> **Trap:** In a left join, a lot of null keys on the fact side means one overloaded partition that contributes *nothing* to the result. If you don't need those rows enriched, split them off first, join the rest, and `union` the null rows back:
>
> ```python
> with_login    = flat.filter(F.col("actor_login").isNotNull())
> without_login = flat.filter(F.col("actor_login").isNull())
> ```
>
> That's the same instinct as [Post 07](content/data-engineering/07-sessionization-gaps-and-islands.md), where we dropped e09 on purpose before sessionizing.

---

## Fix 1: Don't Shuffle the Big Side 📡

The cheapest fix is the one from the top of this post. A broadcast join never moves the big side, so there is no partition for Dave to overload.

```python
joined = flat.join(F.broadcast(actors), "actor_login", "left")
```

If the small side is genuinely small, **stop here.** It's the right answer for RepoSphere's `actors` table, and for `repo_scd2`.

It stops being an option when both sides are big: say a billion-row `actor_activity_history` joined to a billion-row `events` table. You can't ship a copy of a billion rows to every executor. Then you have to live with a sort-merge join, and handle the skew.

---

## Fix 2: Let AQE Split the Hot Partition 🪄

From [Post 19](content/data-engineering/19-reading-the-spark-plan.md): **Adaptive Query Execution** re-plans after each shuffle stage, using the real partition sizes. One of the things it can do is **skew join handling**. It's on by default in modern Spark.

How it works, in order:

1. Stage 1 finishes and writes its shuffle files. Spark now knows the exact size of every partition.
2. A partition counts as **skewed** only if it's bigger than `skewedPartitionFactor` × the median partition **and** bigger than `skewedPartitionThresholdInBytes`.
3. Spark **splits** that partition into several smaller ones, targeting `advisoryPartitionSizeInBytes` each.
4. The matching partition from the *other* side is **read once per piece**, so each piece still meets all the rows it needs.

| Setting | Default | Meaning |
|---|---|---|
| `spark.sql.adaptive.skewJoin.enabled` | `true` | Turn the feature on |
| `spark.sql.adaptive.skewJoin.skewedPartitionFactor` | `5.0` | Skewed = more than 5× the median partition size... |
| `spark.sql.adaptive.skewJoin.skewedPartitionThresholdInBytes` | `256MB` | ...and bigger than this |
| `spark.sql.adaptive.advisoryPartitionSizeInBytes` | `64MB` | Target size of each piece after splitting |

After the run, `explain()` marks the node: `SortMergeJoin(skew=true)`. That's how you know AQE stepped in.

AQE is excellent, and it has **three limits** that matter for RepoSphere:

| Limit | Why it bites |
|---|---|
| **Both conditions must hold** | Our generated file is about **102 MB in total** (measured: 102,200,777 bytes for a million lines). Even Dave's 60% is well under the 256 MB threshold, so by default AQE would call it *not skewed* and leave it alone. You'd have to lower the threshold to see it act. The shuffle size isn't identical to the file size, but it's the same order of magnitude |
| **Only joins** | Skew handling applies to shuffle joins. A `Window.partitionBy("actor_login")` or a `groupBy` is not rescued by it |
| **It can only split the "safe" side** | In a left join, Spark can split the **left** (fact) side, but not the right one. If the hot key is on the side Spark isn't allowed to split, nothing happens |

> **Key insight:** AQE fixes skew *you didn't plan for*. It does not replace knowing which keys are hot. If you already know one actor produces most of the traffic, design for it.

---

## Fix 3: Salting, Spreading the Key Yourself 🧂

When AQE can't help, you change the rule. **Salting** adds a small random-looking number to the key, so one hot key becomes several keys that hash to different partitions.

Think of the supermarket: instead of "all Smiths go to lane 17", you hand out lane stickers, "Smith-0", "Smith-1", and so on, so the family's trolleys split across K lanes.

There are two halves, and they must agree:

1. **Big side:** add a `salt` column holding a number from `0` to `K-1`.
2. **Small side:** **copy every row K times**, once per salt value, so each salted key still finds its partner.

Let's do it on the sample, with K = 2. For a demo that you can check by hand, we'll derive the salt from the event number (`e03` gives 3, and 3 % 2 = 1):

```python
K = 2   # tiny for the sample. Think 8 to 32 for a real hot key

salted_events = (flat
    .filter(F.col("actor_login").isNotNull())          # null keys handled separately
    .withColumn("salt", F.pmod(F.regexp_extract("event_id", r"\d+", 0).cast("int"),
                               F.lit(K))))

salted_actors = actors.withColumn(
    "salt", F.explode(F.array(*[F.lit(i) for i in range(K)])))
```

First, did the salt split Dave?

```python
salted_events.groupBy("actor_login", "salt").count().orderBy("actor_login", "salt").show()
```

```
+-----------+----+-----+
|actor_login|salt|count|
+-----------+----+-----+
|dave       |0   |2    |
|dave       |1   |3    |
|jim        |0   |2    |
|jim        |1   |1    |
+-----------+----+-----+
```

One key (`dave`, 5 rows) became two (`dave/0` with 2 rows, `dave/1` with 3). The biggest group dropped from **5 to 3**. The small side grew from two rows to four:

```python
salted_actors.orderBy("actor_login", "salt").show()
```

```
+-----------+--------+----+
|actor_login|team    |salt|
+-----------+--------+----+
|dave       |platform|0   |
|dave       |platform|1   |
|jim        |web     |0   |
|jim        |web     |1   |
+-----------+--------+----+
```

Now join on **both** columns:

```python
result = (salted_events
    .join(salted_actors, ["actor_login", "salt"], "left")
    .select("event_id", "actor_login", "salt", "team")
    .orderBy("event_id"))

result.show(truncate=False)
print(salted_events.count(), result.count())
```

```
+--------+-----------+----+--------+
|event_id|actor_login|salt|team    |
+--------+-----------+----+--------+
|e01     |dave       |1   |platform|
|e02     |dave       |0   |platform|
|e03     |dave       |1   |platform|
|e04     |dave       |0   |platform|
|e05     |dave       |1   |platform|
|e06     |jim        |0   |web     |
|e07     |jim        |1   |web     |
|e08     |jim        |0   |web     |
+--------+-----------+----+--------+

8 8
```

Same teams as the unsalted join, and **eight in, eight out**. That last check is the one to keep: each event finds exactly one row in the exploded dimension, because the dimension has one row per `(actor_login, salt)` pair. A salting bug (a missing salt value on one side) shows up as nulls, and a doubled one shows up as extra rows.

![Salting: the hot dave key splits into dave/0 and dave/1 on the big side, and the dimension row is copied once per salt](content/data-engineering/images/salting.svg)

On the million-row file with K = 8, an even salt would turn Dave's 599,741 rows into eight groups of roughly **75,000** each. Still the biggest keys in the job, but about eight times smaller.

### The price of salting 💸

| Cost | Detail |
|---|---|
| **Dimension grows K×** | Every dimension row is copied K times, including the ones for actors who aren't hot. Better: salt only the known hot keys and give the rest a salt of `0` |
| **More code, more bugs** | Two sides must agree on K. Change one and rows silently stop matching |
| **Salt must be stable** | Don't use `F.rand()` for the salt unless you are certain no task is ever retried. If a task recomputes, it may draw different salts than the first attempt. Derive the salt from a column that's already there, such as `pmod(hash(event_id), K)` |

> **Why not salt everything?** Because salting multiplies the small side and adds a column everyone has to remember. Most keys aren't hot. Use it for the keys you can name.

---

## Not Every Wide Step Is a Join 🧱

Skew isn't only a join problem. Look at the wide steps from Post 19 and ask which ones a hot actor can hurt:

| Step | Shuffle key | Hot-actor risk | Why |
|---|---|---|---|
| `enrich_with_repo_state` (Post 08) | Broadcast, no shuffle of events | **None** | The big side never moves |
| `groupBy("actor_login", "session_id")` (Post 09) | Two keys | **Low** | A hot actor has *many* sessions. The pair of keys spreads them over many partitions. Also, `count`/`sum` do a partial aggregate first, so few rows cross the shuffle |
| `Window.partitionBy("actor_login")` in `sessionize_actor_events` (Post 07) | One key | **High** | The window needs one actor's whole history **in one partition, sorted**. Neither AQE nor salting can split it without changing the logic |

The window is the real danger in this pipeline. If Dave's history grows to hundreds of thousands of rows, one task has to sort all of them. The mitigations change the *problem*, not just the settings: filter old history out before sessionizing, or sessionize one `event_date` at a time and stitch the boundary sessions together. Both are bigger changes than a config flag, and both are worth knowing about **before** the day Dave becomes a bot.

---

## Your Join and Skew Checklist ✅

1. **Is one side small?** Broadcast it (`F.broadcast`). Done.
2. **Check the key distribution:** `groupBy(key).count().orderBy(F.desc("count"))`. Compare the top row with the median.
3. **Look for null keys.** In a left join they all pile into one partition.
4. **Read the Stages tab:** is Max duration far above the median?
5. **Let AQE try first,** but check whether your data clears the 5× **and** 256 MB bars.
6. **Salt only if you know the hot keys,** and keep the row-count check (events in = rows out).
7. **For windows and aggregates,** reshape the work. Joins aren't the only wide step.

---

## Quick Quiz 🧠

**Q1.** A sort-merge join and a broadcast hash join both give the right answer for `events` joined to `actors`. Why does only the sort-merge version have a skew problem?

<details>
<summary>Show answer</summary>

A sort-merge join shuffles **both** tables by the join key, so all rows for one key land in **one** partition, and one task has to process them. A broadcast join copies the small table to every executor and leaves the big table where it is, so no partition ever collects all of Dave's rows.

</details>

**Q2.** Your dataset has 1,000,000 events, 200 actors, and one actor with 599,741 of them. Why won't adding more shuffle partitions (say, 2,000 instead of 200) fix the slow task?

<details>
<summary>Show answer</summary>

Because partitioning is decided by the **key**. Every `dave` row hashes to the same partition number no matter how many partitions exist. More partitions make the *other* 199 actors' work finer-grained, but Dave's task still holds at least 599,741 rows. To split a key you have to change the key (salting) or let AQE split the partition.

</details>

**Q3.** In a left join of `flat` onto `actors`, what happens to e09 (no login), and why can it still hurt performance on a big table?

<details>
<summary>Show answer</summary>

e09 is kept (it's a left join) and comes out with a null `team`, because a null key never equals anything. But for the shuffle, **all null-key rows hash to the same partition**. With few nulls that's harmless, but if a large share of events have no actor, that single partition is overloaded and contributes nothing to the result. Splitting the null rows off before the join avoids it.

</details>

**Q4.** In the salting example, why does the `actors` side use `explode(array(0..K-1))`? What would go wrong if you only salted the events?

<details>
<summary>Show answer</summary>

Each salted event key looks like `dave/0` or `dave/1`, and the dimension must contain a matching row for **every** salt value. Exploding creates one `actors` row per `(actor_login, salt)` pair. If you salted only the events, `dave/1` would find no partner in the dimension, and a left join would quietly return a null `team` for those events: right row count, wrong data. The check `8 in, 8 out` doesn't catch that, but a null count on `team` does.

</details>

**Q5.** AQE's skew handling is on by default, yet a 600,000-row hot key in a ~100 MB dataset isn't split. Give two reasons it might not be.

<details>
<summary>Show answer</summary>

First, the **size threshold**: a partition is only treated as skewed if it's both more than 5× the median **and** over `skewedPartitionThresholdInBytes` (256 MB by default). A 100 MB dataset can't clear that bar. Second, AQE's skew handling only applies to **shuffle joins** and only to a side it's allowed to split. A window or a `groupBy`, or a hot key on the unsplittable side of an outer join, is left alone.

</details>

---

## What's Next? 🚀

You can now explain why a broadcast join can't be skewed, how a hot key creates the one slow task, what AQE does about it (and what it can't), and how to salt a key by hand and check you didn't lose rows.

Skew is about *uneven* work. Next, we look at the *amount* of output. A daily RepoSphere run writes files, and the number of them is decided by the same shuffle partitions we've been staring at. Too many tiny files and every later read pays for it, which links straight back to the compaction we did in Post 17.

👉 **[Post 21: Small Files and Partitioning](content/data-engineering/21-small-files-and-partitioning.md)**

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
