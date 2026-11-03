---
title: "Measure Before You Tune — Caching, AQE & the Knobs Worth Touching"
date: 2026-11-03
tags: [data-engineering, pyspark, performance, benchmarking, caching, aqe, spark-ui, first-principles]
description: Part 3, final post. Every tip in this series is a hypothesis until you measure it. Learn why timing RepoSphere's nine-event sample proves nothing, how to benchmark honestly on a generated million-event dataset, when cache() helps and when it hurts, what AQE already does for you, and the short list of Spark settings that deserve your attention.
---

# The Stopwatch Problem ⏱️

In [Post 21](content/data-engineering/21-small-files-and-partitioning.md), we learned to predict how many files a run writes. Across Part 3 you have collected a lot of advice: broadcast the small side, salt the hot key, repartition before the write, read the plan.

Here's the uncomfortable truth: **every one of those is a hypothesis.** A rule of thumb tells you where to *look*. It never tells you the change *worked* on your data, on your cluster.

So the last post in the series is about the question that comes before all the others: **how do you know RepoSphere got faster?**

> **A note on honesty:** I couldn't run Spark while writing this post, so there are **no timings** in it. The one script that actually ran (the data generator below) is plain Python, and its output is real. Everything about Spark is reasoning plus a harness for **you** to run. The measurements are still owed, and I'd rather say so than invent a "42 seconds down to 9" story.

---

## The Dyno Test 🏎️

A mechanic who retunes an engine doesn't judge the result by listening in the driveway. They put the car on a **dynamometer**, run it the same way before and after, and compare the readings. They change **one thing** at a time, because two changes at once tell you nothing about which one helped.

They also don't test the engine at idle and promise you it's faster on the motorway.

| Mechanic | Spark |
|---|---|
| The dyno | A **benchmark harness** you can re-run |
| Same road conditions each time | **Same data, same machine, same config** apart from the one change |
| Idle versus full load | Nine rows versus a realistic dataset |
| Warm the engine first | **Warm-up run**, then measure |
| A log of every tweak | A table of change, prediction, result |

---

## Why Nine Rows Tell You Nothing 🔬

Any Spark run costs roughly:

```
total time  =  fixed cost  +  (rows ÷ throughput)
```

The **fixed cost** is everything that happens no matter how little data there is: building and optimising the plan, generating code, launching the job and its tasks, warming up the JVM, listing files. The second term is the part your tuning can change.

![Schematic: for nine events almost all time is fixed cost, for a billion events almost all time is work that grows with the rows](content/data-engineering/images/fixed_vs_scaling_cost.svg)

On our nine-event sample, the second term is close to zero, so **every run measures the first term**. That gives you two kinds of wrong answer:

| What the sample shows | What's really true |
|---|---|
| "Adding `broadcast()` made it slower" | You added a little planning work. On a billion rows, it removes a whole shuffle |
| "The new version is 20% faster" | You saved noise. A real 20% gain on the scalable part is invisible here |
| "200 shuffle partitions vs 8: no difference" | Of course. Almost all 200 tasks had nothing to do ([Post 19](content/data-engineering/19-reading-the-spark-plan.md)) |

> **Key insight:** A benchmark is only as meaningful as its **data shape**. Skew, file count, key cardinality and total size all change what Spark does. A nine-row dataset has none of the properties that cause slowness.

---

## Build a Dataset That Can Hurt 🏗️

So we need data with RepoSphere's *shape*, but much more of it. This is the generator from [Post 20](content/data-engineering/20-joins-and-skew.md), extended to spread events over **seven days** and to match the real event schema. It's plain Python, the seed is fixed, and you'll get the same output:

```python
import json, random, itertools
from collections import Counter

random.seed(42)
N, DAYS = 1_000_000, 7
actors = ["dave"] + [f"user{i:03d}" for i in range(1, 200)]
cum = list(itertools.accumulate([0.60] + [0.40 / 199] * 199))      # dave = 60% of traffic
repos = [(101, "alpha-api"), (202, "beta-web"), (999, "ghost")]
types = ["PushEvent", "PullRequestEvent", "IssuesEvent"]

per_actor, per_day = Counter(), Counter()
with open("big_events.jsonl", "w") as f:
    for i in range(1, N + 1):
        a = random.choices(range(200), cum_weights=cum)[0]
        day = random.randrange(DAYS)
        sec = random.randrange(86_400)
        ts = f"2024-03-{1 + day:02d}T{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}Z"
        rid, rname = repos[i % 3]
        per_actor[actors[a]] += 1
        per_day[ts[:10]] += 1
        f.write(json.dumps({"event_id": f"x{i:07d}", "event_type": types[i % 3],
                            "created_at": ts, "repo": {"id": rid, "name": rname},
                            "actor": {"id": a + 1, "login": actors[a]}},
                           separators=(",", ":")) + "\n")

print("rows:", sum(per_day.values()), "| actors:", len(per_actor), "| days:", len(per_day))
print("dave:", per_actor["dave"], "| next:", per_actor.most_common(2)[1])
print("busiest day:", per_day.most_common(1)[0], "| quietest day:", min(per_day.items(), key=lambda kv: kv[1]))
```

```
rows: 1000000 | actors: 200 | days: 7
dave: 599206 | next: ('user125', 2147)
busiest day: ('2024-03-03', 143529) | quietest day: ('2024-03-07', 142443)
```

The file comes out at **157,123,707 bytes** (about 150 MiB). Here is what that shape gives us, all by arithmetic:

| Property | Value | Why it matters |
|---|---|---|
| Rows | 1,000,000 | Enough that the second term of the formula is no longer zero |
| Hot key | `dave`, **599,206 rows** | A real skew test, from [Post 20](content/data-engineering/20-joins-and-skew.md) |
| Days | 7, about 142,000 to 144,000 rows each | Gives `event_date` partitioning something to partition |
| Input splits | At least `ceil(157,123,707 ÷ 134,217,728)` = **2** | Spark reads in chunks of up to 128 MB ([Post 21](content/data-engineering/21-small-files-and-partitioning.md)). With more cores it may cut finer |

It's still small by industry standards. A million rows runs on a laptop, and that's the point: it's the **smallest** dataset that has the right shape. If you can reach a cluster, scale `N` up and keep the ratios.

> **Trap:** Don't generate uniformly random data and call it realistic. A benchmark with no hot key will never show you a skew problem, and a benchmark with a hot key you *invented* proves nothing about **your** key. Copy the shape of production: the top key's share, the number of null keys, the file count.

---

## Five Rules of an Honest Benchmark 📏

| # | Rule | What goes wrong without it |
|---|---|---|
| 1 | **Force the whole plan to run** | `.count()` may let Spark skip columns, and `.show()` computes only enough rows to print |
| 2 | **Throw away a warm-up run** | The first run pays for JVM warm-up and cold file reads. It's not the steady state |
| 3 | **Repeat, and report the median and the spread** | One run is a sample of one. Noise on a shared machine is real |
| 4 | **Change one thing per lap** | Otherwise you can't say which change did what |
| 5 | **Keep everything else identical** | Same data, same session config, same machine, nothing else running |

Rule 1 matters most for Spark specifically. Remember **lazy evaluation** from [Post 02](content/data-engineering/02-spark-from-first-principles.md): nothing happens until an action. And different actions do different amounts of work. Spark has a built-in output format that runs the **entire** plan and writes nothing, called `noop`. It's made for exactly this:

```python
import time, statistics

def run_once(df) -> float:
    t0 = time.perf_counter()
    df.write.format("noop").mode("overwrite").save()      # runs every stage, writes nothing
    return time.perf_counter() - t0

def benchmark(make_df, runs=5, warmup=1) -> dict:
    for _ in range(warmup):
        run_once(make_df())                               # discard
    times = sorted(run_once(make_df()) for _ in range(runs))
    return {"min": times[0],
            "median": statistics.median(times),
            "max": times[-1]}
```

A few details in there are deliberate. `make_df` is a *function* that builds the DataFrame from scratch each time, so no run can reuse another's cached result. The `max` stays in the report, because a median of 10 s with a max of 40 s is a different story from a median of 10 s with a max of 11 s.

Use it on the real pipeline, from the functions in Posts 03 to 09:

```python
def pipeline(spark):
    events    = read_events(spark, "big_events.jsonl")
    changes   = read_repo_changes(spark, "data/repo_changes.jsonl")
    flat      = flatten_events(events)
    repo_scd2 = build_repo_scd2(changes)
    sessions  = sessionize_actor_events(flat)
    enriched  = enrich_with_repo_state(sessions, repo_scd2)
    return compute_session_summary(enriched)

baseline = benchmark(lambda: pipeline(spark))
```

Write down `baseline`. That dictionary is the dyno reading every later change is compared against. I'm not printing one here, because mine would be from a different machine than yours, and a number from my laptop would only invite you to compare it with yours. The comparison that matters is **your baseline against your own change**.

> **Key insight:** Seconds depend on your machine. **Counts** don't. Shuffle bytes, spill, number of tasks, number of files, and the *ratio* of the slowest task to the median stay the same across machines. When you can, argue from those first and from seconds second.

---

## What to Read Besides the Clock 📟

The wall-clock time tells you *whether* something changed. The Spark UI ([Post 19](content/data-engineering/19-reading-the-spark-plan.md)) tells you *why*:

| Metric (Stages tab) | A good sign | A warning sign |
|---|---|---|
| **Task duration**, max vs median | Max is close to the median | Max is many times the median (skew, [Post 20](content/data-engineering/20-joins-and-skew.md)) |
| **Shuffle Read / Write size** | Small relative to input | Larger than the input itself |
| **Spill (memory / disk)** | None | Appears on some or all tasks: partitions too big for memory |
| **GC time** | A small slice of task time | A large slice: memory pressure |
| **Tasks per stage** | Roughly a few times your cores | Hundreds of tiny tasks, or a handful of huge ones |
| **Files written** ([Post 21](content/data-engineering/21-small-files-and-partitioning.md)) | A few, each reasonably large | Many tiny files |

The most useful number in that table is a *ratio*, max task time over median task time. It is the **skew fingerprint**: it works on a laptop and on a thousand-core cluster.

---

## `cache()`: The Most Over-Prescribed Fix 🧊

Because of lazy evaluation, a DataFrame is a **recipe**, not a pile of rows. Use it in two actions, and Spark cooks it twice, reading the file again each time.

`cache()` tells Spark: *keep the result in memory the first time you compute it, and serve the next action from there.* (It spills to disk if memory runs short.)

Here's a case where RepoSphere really does reuse a DataFrame: a data-quality check on the flattened events, then the actual pipeline.

```python
from pyspark.sql import functions as F

flat = flatten_events(read_events(spark, "big_events.jsonl"))

flat.cache()                                                  # lazy: only marks it
print(flat.filter(F.col("actor_login").isNull()).count())     # action 1: reads the file, fills the cache
print(flat.count())                                           # action 2: served from the cache
flat.unpersist()                                              # give the memory back
```

```
0
1000000
```

Zero null actors, because the generator never makes one. The real nine-event sample has one (e09, [Post 07](content/data-engineering/07-sessionization-gaps-and-islands.md)), which is why the check exists.

Without the cache, the second line would read and parse the 157 MB file **a second time**. With it, only the first action pays.

| Cache it when | Don't cache it when |
|---|---|
| The same DataFrame feeds **two or more actions** or branches | It's used **once**. You pay to store it and never get it back |
| It's **expensive to recompute** (a big join, a heavy window) | It's cheap to recompute, such as a plain read plus a `select` |
| It **fits** in memory (or you accept spilling) | It's bigger than memory. Caching to disk is often no faster than re-reading the source |
| You'll `unpersist()` when done | It would sit in memory for the rest of the job |

Three traps to know before you reach for it:

> **Trap 1:** `cache()` is **lazy**. Calling it does nothing until an action runs. If you call `cache()` and your very next step is the *only* action, you stored a copy for no reason.

> **Trap 2:** The cache is a **snapshot**. If the source file changes after the first action, your cached DataFrame still holds the old rows. Re-run the read to get fresh ones.

> **Trap 3:** Cached data takes memory away from the shuffles and joins that also need it. Caching a huge DataFrame can make the *rest* of the job slower.

You can verify it worked in the **Storage** tab of the Spark UI: the cached DataFrame appears there with its size and the fraction held in memory. And in the plan, look for an `InMemoryTableScan` node where the read used to be.

---

## AQE Already Does Some of Your Job 🪄

Half the tuning guides on the internet were written before **Adaptive Query Execution**. AQE is on by default in modern Spark, and it re-plans *during* the run, using the real size of each shuffle partition:

| What AQE does | Setting (all default to on) | Which earlier post |
|---|---|---|
| **Merges** many tiny shuffle partitions into fewer, healthier ones | `spark.sql.adaptive.coalescePartitions.enabled` | [19](content/data-engineering/19-reading-the-spark-plan.md): why 200 isn't a problem |
| **Splits** a skewed partition in a shuffle join | `spark.sql.adaptive.skewJoin.enabled` | [20](content/data-engineering/20-joins-and-skew.md), with its three limits |
| **Switches** a sort-merge join to a broadcast join once it sees one side is small | `spark.sql.adaptive.enabled` | [20](content/data-engineering/20-joins-and-skew.md) |

This changes the order of operations for tuning. **Don't start by hand-setting `spark.sql.shuffle.partitions`.** Start by looking at what AQE did, in the final plan after an action, and in the UI. Only intervene where you can show it missed something.

You can also *test* what AQE is worth, which makes a good first experiment:

```python
spark.conf.set("spark.sql.adaptive.enabled", "false")
off = benchmark(lambda: pipeline(spark))

spark.conf.set("spark.sql.adaptive.enabled", "true")
on = benchmark(lambda: pipeline(spark))
```

One setting, same data, same machine. What you do with the two dictionaries is up to your data.

---

## The Knobs Worth Touching 🎛️

Spark has hundreds of settings. Most are either for a cluster admin or for a problem you don't have. These are the ones that map directly to what you learned in this series:

| Setting | Default | Touch it when |
|---|---|---|
| `spark.sql.shuffle.partitions` | 200 | The UI shows shuffle partitions **spilling**: raise it. Or a **huge** number of tiny tasks that AQE didn't merge: lower it |
| `spark.sql.autoBroadcastJoinThreshold` | 10 MB | A dimension is small but just over the line. The better fix is often an explicit `F.broadcast()` ([Post 08](content/data-engineering/08-point-in-time-joins.md)) |
| `spark.sql.adaptive.advisoryPartitionSizeInBytes` | 64 MB | You want AQE to aim for bigger or smaller partitions after a shuffle |
| `spark.sql.files.maxPartitionBytes` | 128 MB | Input has far too many tiny splits, or too few splits for your cores |
| `write.target-file-size-bytes` (Iceberg table property) | 512 MB | Compaction keeps finding files below your target ([Post 17](content/data-engineering/17-compaction-and-maintenance.md), [Post 21](content/data-engineering/21-small-files-and-partitioning.md)) |
| Executor memory and cores | cluster-specific | The UI shows spill or high GC **after** the data layout is sorted out |

And a short list of things that feel like tuning but are really **design**, which is why they come *before* any setting:

| Better than a setting | Why |
|---|---|
| Use built-in functions, not Python UDFs | Spark can optimise `F.col(...)` expressions. A Python UDF is a black box that also moves every row between the JVM and Python |
| Filter and `select` early | Fewer columns and rows travel through every later shuffle |
| Fix skew by design | A salted key ([Post 20](content/data-engineering/20-joins-and-skew.md)) beats any memory setting |
| Write the right number of files | Cheaper than compacting later ([Post 21](content/data-engineering/21-small-files-and-partitioning.md)) |

> **Why so few knobs?** Because each setting is a bet on a data shape. Defaults are good for an *average* workload. You change one only when you can point at the metric that shows RepoSphere isn't average.

---

## Folklore to Ignore 🧙

| Claim | Reality |
|---|---|
| "Always `cache()` your DataFrames" | Only when reused, and only if it fits. See the table above |
| "`coalesce(1)` gives you one file" | Not on a partitioned table ([Post 21](content/data-engineering/21-small-files-and-partitioning.md)) |
| "More executors fix everything" | Not for one skewed task. Adding workers doesn't split Dave's key |
| "Set shuffle partitions to some magic number" | The right number depends on data size, and AQE adjusts it for you at run time |
| "It ran fast on my sample, ship it" | See the first half of this post |

---

## Your Experiment Plan for RepoSphere 🧪

Here's how I'd use this series to improve the pipeline on the million-event file. Every row is a **prediction first**. You run it, and the measurement settles it.

| Lap | Change (one at a time) | Prediction to write down first | What to read |
|---|---|---|---|
| 1 | Baseline: run `pipeline` as is | "The stage after the `actor_login` shuffle has one task far longer than the rest" | Task max vs median |
| 2 | AQE off, then on | "AQE changes the partition count and little else, since no join is skewed past its 256 MB threshold" | Tasks per stage, final plan |
| 3 | Salt `dave` ([Post 20](content/data-engineering/20-joins-and-skew.md)) | "The max task time drops toward the median" | Task max vs median, wall clock |
| 4 | Cache `flat` when two actions use it | "Second action no longer re-reads the 157 MB file" | Storage tab, wall clock of action 2 |
| 5 | Cluster the write by `event_date` ([Post 21](content/data-engineering/21-small-files-and-partitioning.md)) | "Files per day drops to about one" | Files per partition folder |

![The tuning loop: measure the baseline, find the bottleneck, change one thing after a prediction, re-measure on the same data and machine, then keep or revert the change](content/data-engineering/images/tuning_loop.svg)

Lap 2 is a prediction I'd *expect* to be dull, and that's useful. The most valuable result of a tuning exercise is often learning that a change doesn't matter, so you stop worrying about it.

> **Key insight:** Write the prediction down **before** you run. If you only look afterwards, you'll explain any result as a win.

---

## Your Measure-First Checklist ✅

1. **Never time the nine-row sample.** It measures fixed cost only.
2. **Generate data with production's shape**: size, hot keys, nulls, file count.
3. **Force the whole plan** with the `noop` writer, not `.show()` or a lazy count.
4. **Discard a warm-up run, repeat, and report median and spread.**
5. **Change one thing per lap**, and write the prediction down first.
6. **Read the UI, not just the clock**: task max vs median, shuffle size, spill, files written.
7. **Check what AQE did** before hand-setting partition counts.
8. **Cache only what's reused**, and `unpersist()` it.
9. **Keep the change only if the measurement says so.** Revert everything else.

---

## Quick Quiz 🧠

**Q1.** A colleague times the nine-event RepoSphere sample before and after adding `F.broadcast()` to the enrichment join. The new version is a hair slower. What should you conclude?

<details>
<summary>Show answer</summary>

**Nothing.** Nine rows means the run time is almost entirely fixed cost: planning, scheduling, warm-up. A broadcast adds a small amount of work to that fixed cost, so a tiny slowdown is expected and irrelevant. What the broadcast removes is a **shuffle of the large side**, and that only shows up when the large side is large. Benchmark on the generated million-event file instead.

</details>

**Q2.** Why does the harness write to the `noop` format, rather than calling `.count()` or `.show()`?

<details>
<summary>Show answer</summary>

Because `.show()` computes only enough rows to print, and `.count()` can let Spark skip columns it doesn't need. Both can do **less work than the real job**. The `noop` writer drives the **entire** plan to completion, including every shuffle and the final projection, and then discards the output, so you time the work without paying for disk writes.

</details>

**Q3.** Your harness reports a median of 10 s and a max of 38 s over five runs. Why does it keep the max, and what might it mean?

<details>
<summary>Show answer</summary>

A big spread means the measurement is **noisy**, so a later "improvement" of a couple of seconds could be luck. Typical causes: another process on the machine, cold file cache on some runs, garbage collection, or a run that hit a spill. Fix the noise (or take more runs) before trusting small differences. A median alone would have hidden the problem.

</details>

**Q4.** You `cache()` the flattened events and then run the pipeline **once**. Did that help?

<details>
<summary>Show answer</summary>

No, it made things slightly worse. `cache()` is lazy, so the first (and only) action both computes the DataFrame **and** stores a copy in memory. Nothing ever reads that copy, and it uses memory that the shuffles and joins could have used. Cache only a DataFrame that feeds **two or more** actions or branches, and `unpersist()` it afterwards.

</details>

**Q5.** The Spark UI shows 200 shuffle tasks, but AQE's final plan merged them into a handful. You're tempted to set `spark.sql.shuffle.partitions` to 8. What should you do first?

<details>
<summary>Show answer</summary>

**Measure what AQE already did.** The final plan, after an action has run, shows that the merge happened, so the 200 is a ceiling AQE already works under. Setting 8 by hand may change nothing, or may hurt when a bigger day's data arrives and 8 partitions are too few. Change it only if the UI shows a real problem, like spill from partitions that are too large, and compare against your baseline.

</details>

---

## What's Next? 🚀

That's the series. Over twenty-two posts you went from "what is data engineering" to a RepoSphere pipeline you can **trust** (Part 1), keep **correct on a lakehouse** (Part 2), and now reason about **fast** (Part 3). The thread through all of it is the same: **write down what you expect, run it, and let the output decide.**

| Part | Posts | You can now |
|---|---|---|
| **1. The pipeline** | 01 to 09 | Turn raw JSON events into sessions, history and summaries, and prove each step with a known answer |
| **2. The lakehouse** | 10 to 18 | Load idempotently, merge, track history incrementally, time-travel, evolve schemas and compact |
| **3. Performance** | 19 to 22 | Read a plan, find skew, control file counts, and measure before you tune |

If you only keep one habit from twenty-two posts, keep the nine-event sample and its **answer key**. It's small enough to verify by hand, and every optimisation in this part had to leave its output unchanged.

👉 **[Start again at Post 01](content/data-engineering/01-what-is-data-engineering.md)**

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
