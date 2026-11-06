---
title: "The Debugging Loop — How to Read a Failed Spark Job"
date: 2026-11-06
tags: [spark, pyspark, debugging, troubleshooting, production, spark-ui, first-principles]
description: The first post in the Spark in Production series. A calm, repeatable method for any failed Spark job. Read the stack trace top-down, decide whether the driver or an executor failed, find the right Spark UI tab, shrink the problem on RepoSphere's nine-event sample, change one thing at a time, and use a triage table to jump to the right post.
---

# 3 a.m., Red Job, Blank Mind 🚨

In [Post 22 of the Data Engineering series](content/data-engineering/22-measure-before-tuning.md) we learned to measure before we tune. That was about making a *working* pipeline faster.

This series is about the other night. The one where the RepoSphere daily job that has run green for months turns **red at 3 a.m.**, a wall of Java stack trace scrolls past, and somebody asks "so, what broke?"

Here's the good news: **Spark failures are not random.** There are only a handful of families (memory, skew, shuffle, bad data, silent wrong answers, table-format conflicts), and each one leaves **distinct fingerprints**. Over eight posts we will meet each family with a RepoSphere scenario, and for every one we'll follow the same shape:

**Symptom → What you see → Root cause → Fix → How to verify.**

But before the scenarios, you need the method. Without it, you will do what most of us did at first: paste the error into a search box, double `spark.executor.memory`, and hope.

---

## The Emergency Room Analogy 🏥

Picture an emergency room. A patient arrives and says "I feel terrible." A good doctor does not start with surgery. She follows a loop:

1. **Read the chart** (what exactly happened?)
2. **Locate the problem** (which organ?)
3. **Form a hypothesis** (what would explain *all* of this?)
4. **Run a cheap test** (one change, one result)
5. **Check the patient responded**

| Hospital | Spark job |
|---|---|
| Patient says "I feel terrible" | "The job failed" |
| The chart | The error message and stack trace |
| Which organ? | Driver, executor, or a specific stage and task |
| Cheap test | Re-run on a tiny slice of data |
| Prescribing five drugs at once | Changing six configs at once |

That last row is the classic mistake. If you change six things and the job passes, you have learned **nothing** about which one mattered, and it will fail again next month.

![The five-step debugging loop](content/spark-production-failures/images/debugging_loop.svg)

---

## Step 1: Read the Error Top-Down 📖

Spark errors are long because they are **wrapped**. Python wraps a Java error. Java wraps a Spark scheduler error. The scheduler error wraps the real one. Here is an **illustrative log excerpt** (shortened, details vary by version) for a RepoSphere job that calls a Python function on every row:

```
py4j.protocol.Py4JJavaError: An error occurred while calling o95.showString.
: org.apache.spark.SparkException: Job aborted due to stage failure:
  Task 0 in stage 3.0 failed 4 times, most recent failure:
  Lost task 0.3 in stage 3.0 (TID 12) (10.0.0.5 executor 2):
  org.apache.spark.api.python.PythonException: Traceback (most recent call last):
    File "reposphere_job.py", line 41, in normalise_login
      return login.lower()
  AttributeError: 'NoneType' object has no attribute 'lower'
```

Read it in three passes:

| Pass | Look for | Here it tells you |
|---|---|---|
| **Top** | The outer wrapper | `Job aborted due to stage failure`: a task failed, and Spark gave up |
| **Middle** | *Where* | `Task 0 in stage 3.0 ... failed 4 times ... executor 2`: an **executor** task, not the driver |
| **Bottom** | The root cause | `AttributeError: 'NoneType' object has no attribute 'lower'`: our own Python code met a null |

> **Key insight:** The outer lines are Spark telling you *that* something failed. The **last `Caused by:` line** (or the last exception in a Python traceback) tells you *why*. Always scroll to the bottom first, then read upwards for context.

Notice also **"failed 4 times"**. That number comes from `spark.task.maxFailures` (default 4). Spark retried the task three times before giving up. A job that fails *after retries* tells you the problem is **repeatable**. Hold that thought, because it comes back in [Post 5](content/spark-production-failures/05-fetch-failed-and-shuffle-errors.md), where retries mask a very different story.

---

## Step 2: Driver or Executor? 🧭

Spark has two kinds of processes, as we saw in [Post 2 of the Data Engineering series](content/data-engineering/02-spark-from-first-principles.md): one **driver** (the head chef) and many **executors** (the cooks). Which one died changes everything.

| | Driver failed | Executor failed |
|---|---|---|
| **Typical message** | `java.lang.OutOfMemoryError` in the driver log, or your Python script crashes | `ExecutorLostFailure`, `Lost task ...`, `Container killed by ...` |
| **Job state** | The **whole application** dies | One task fails and is **retried**; the job dies only after repeated failure |
| **Usual causes** | `collect()`, huge broadcast, too many files to list, a bug in driver-side code | Giant partitions, skew, memory overhead, bad rows, lost nodes |
| **Where to look** | Driver log, the terminal or the orchestrator's task log | Executor logs, the **Executors** and **Stages** tabs |

A quick rule: **if the whole application disappears, suspect the driver. If tasks fail and retry, suspect an executor.**

### Where the logs actually live

| Cluster type | Driver log | Executor logs |
|---|---|---|
| **Local mode** (`local[*]`) | Your terminal | Same terminal (everything is one process) |
| **YARN** | `yarn logs -applicationId <id>` (the first container is usually the driver) | Same command, other containers |
| **Kubernetes** | `kubectl logs <driver-pod>` | `kubectl logs <executor-pod>` |
| **Managed platforms** (EMR, Databricks, Dataproc) | The platform's driver log page | The platform's executor log page |

> **Trap:** A pod or container that was **killed by the cluster** often has *no* Java error in its own log. The process was removed from outside, so there was no chance to print anything. The evidence is in the **resource manager** (YARN) or the **pod status** (Kubernetes), not in your application log. [Post 3](content/spark-production-failures/03-executor-oom-and-container-killed.md) covers this.

---

## Step 3: Pick the Right Spark UI Tab 🖥️

The Spark UI is the instrument panel. You met it in [Post 19](content/data-engineering/19-reading-the-spark-plan.md). In an incident, each tab answers one question:

| Tab | Question it answers | Red flag |
|---|---|---|
| **Jobs** | Which job failed? Did earlier jobs succeed? | A red job; a long gap between jobs (driver busy) |
| **Stages** | Which stage, and what do the tasks look like? | **Max** task time far above **median**; large spill; failed tasks |
| **Storage** | What is cached, and how big? | A cached dataset far larger than expected |
| **Executors** | Are executors healthy and evenly loaded? | Dead executors; one executor with huge GC time; one doing all the work |
| **SQL / DataFrame** | Which plan ran? Where did rows blow up? | A join whose output row count is *far* larger than its inputs |

Two views earn their keep in almost every incident:

1. **Stage detail → Summary Metrics.** It shows min, 25th percentile, median, 75th percentile and max for task duration and for shuffle read. If **max ≫ median**, one task is carrying the stage, which is the skew fingerprint from [Post 4](content/spark-production-failures/04-the-straggler-skew-stuck-stage.md).
2. **SQL tab → the plan graph.** Every box shows the number of output rows. You can walk the plan and see exactly where RepoSphere's 9 events became 12, or 4.

> **Key insight:** The UI answers **where**. The logs answer **what**. You need both. The UI tells you stage 3 is the problem; the log tells you it was an `AttributeError`.

---

## Step 4: Reproduce Small 🔬

The most valuable debugging move is **making the problem small enough to see**. This is why this whole blog uses a nine-event sample with a known answer key.

Suppose a job fails on production data, and the error says a value in the `actor` field is unexpected. You can bisect with the sample's shape in mind. RepoSphere's `e09` is the famous edge case: an event with an actor `id` but **no `login`**.

```python
from pyspark.sql import functions as F

events = spark.read.json("content/data-engineering/data/events.jsonl")

(events
    .select("event_id", F.col("actor.login").alias("actor_login"))
    .filter(F.col("actor_login").isNull())
    .show())
```

```
+--------+-----------+
|event_id|actor_login|
+--------+-----------+
|     e09|       null|
+--------+-----------+
```

One row out of nine. If your function assumes `login` is always a string, **this** row is what breaks it, and now you can prove it on a laptop in seconds instead of re-running a four-hour job.

The reproduction toolkit:

| Technique | What it does | Caveat |
|---|---|---|
| `df.limit(1000)` | Takes a few rows | **Not representative**: may miss the bad row entirely |
| `df.sample(0.01, seed=42)` | Random slice, repeatable with a seed | Can still miss rare bad rows |
| **Filter to the failing key** | `filter(F.col("repo.id") == 101)` | Best when you know which key hurts |
| **Process one input file/partition** | Read just the file named in the failing task | Best for bad-data failures |
| **Hand-built fixture** | A tiny DataFrame with the suspect rows | Best for a regression test afterwards |

> **Why a fixture?** Once you have found the bad row, **add it to your test data**. RepoSphere's sample already contains `e09` for exactly this reason: a bug that has bitten once should never bite twice.

---

## Step 5: Change One Thing, Then Verify ✅

Now you have a hypothesis ("`login` can be null, and `normalise_login` does not handle it") and a tiny reproduction. Test it:

1. **Change exactly one thing**: handle the null.
2. Re-run the **small** case. The error should vanish *and* the answer should match what you expect by hand.
3. Re-run on **production-sized** data and check the same.
4. Write down what you found, in one line, where your team will find it.

```python
@F.udf("string")
def normalise_login(login):
    if login is None:          # the one-line fix: e09 has no login
        return None
    return login.lower()
```

A fix is only a fix if you can say **how you verified it**. "It stopped failing" is not verification. "The nine-event run returns nine rows with `e09` carrying a null, and the production row count matches the source" is.

> **Trap:** A job that passes after you changed three configs. You do not know which one helped, which one hurt, or whether it just got lucky. Revert and bisect: put changes back one at a time.

---

## The Triage Table 🗺️

Print this one. It maps what you *see* to the post that explains it.

| What you see | Likely family | Go to |
|---|---|---|
| `java.lang.OutOfMemoryError` in the **driver** log; app dies | Driver memory | [Post 2](content/spark-production-failures/02-driver-oom-collect-and-broadcast.md) |
| `Total size of serialized results ... is bigger than spark.driver.maxResultSize` | Driver memory | [Post 2](content/spark-production-failures/02-driver-oom-collect-and-broadcast.md) |
| `OutOfMemoryError: Java heap space` in an executor, or exit code 137 / "container killed" | Executor memory | [Post 3](content/spark-production-failures/03-executor-oom-and-container-killed.md) |
| One task running far longer than its siblings | Skew | [Post 4](content/spark-production-failures/04-the-straggler-skew-stuck-stage.md) |
| `FetchFailedException`, `ExecutorLostFailure`, stages re-running | Shuffle and lost nodes | [Post 5](content/spark-production-failures/05-fetch-failed-and-shuffle-errors.md) |
| Failure naming a field, a type, or `_corrupt_record` | Bad data, schema drift | [Post 6](content/spark-production-failures/06-bad-data-and-schema-drift.md) |
| **No error at all**, but the numbers are wrong | Silent wrong answers | [Post 7](content/spark-production-failures/07-silent-wrong-answers.md) |
| `CommitFailedException`, `FileNotFoundException` on an Iceberg table | Table-format conflicts | [Post 8](content/spark-production-failures/08-iceberg-commit-conflicts-and-missing-files.md) |

---

## Quick Quiz 🧠

**Q1.** A stack trace has five nested exceptions. Which one do you read first, and why?

<details>
<summary>Show answer</summary>

The **last** `Caused by:` (or the last exception in a Python traceback). The outer ones are wrappers, such as `Py4JJavaError` and `SparkException: Job aborted`. They tell you that *something* failed. The innermost one tells you *why*. Then read upwards to learn where it happened.

</details>

**Q2.** A RepoSphere job fails with `Lost task 0.3 in stage 3.0 ... failed 4 times`. Did the driver or an executor fail, and what does "4 times" tell you?

<details>
<summary>Show answer</summary>

An **executor task** failed. The driver survived long enough to report it. "4 times" is the default `spark.task.maxFailures`: the task was **retried three times** and failed every time, so the problem is **repeatable** and tied to that task's data or code, not a one-off blip.

</details>

**Q3.** In the Stage detail page, the median task time is short but the max is enormous. Which UI view showed you that, and what does it suggest?

<details>
<summary>Show answer</summary>

**Summary Metrics** in the Stage detail page (min, 25th, median, 75th, max). Max far above median means **one task is doing far more work** than the others, which is the signature of **data skew**. That is [Post 4](content/spark-production-failures/04-the-straggler-skew-stuck-stage.md).

</details>

**Q4.** You changed `spark.executor.memory`, `spark.sql.shuffle.partitions` and a join hint at once, and the job passed. What is wrong with that?

<details>
<summary>Show answer</summary>

You can't tell **which change fixed it**, whether one made things *worse*, or whether the job just got lucky with this day's data. Revert and re-apply **one change at a time**, verifying against a known answer each time.

</details>

**Q5.** A Kubernetes executor pod vanished and its own application log shows **no error**. Why might that be?

<details>
<summary>Show answer</summary>

The pod was probably **killed from outside** (for example, for exceeding its memory limit), so the process had no chance to log anything. The evidence lives in the **pod status** and cluster events, not the application log. We look at this in [Post 3](content/spark-production-failures/03-executor-oom-and-container-killed.md).

</details>

---

## What's Next? 🚀

You now have the loop: **read, locate, hypothesise, reproduce, verify.** And you know where the clues live.

Next we meet the most common production failure of all, the one where the **driver itself runs out of memory**, usually because somebody wrote `.collect()` on a table that was bigger than they thought.

👉 **[Post 2: Driver OOM — collect(), toPandas() and Oversized Broadcasts](content/spark-production-failures/02-driver-oom-collect-and-broadcast.md)**

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
