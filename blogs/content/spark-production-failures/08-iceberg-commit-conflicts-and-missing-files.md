---
title: "Iceberg Commit Conflicts and Missing Files — Two Writers, One Table"
date: 2026-11-06
tags: [spark, apache-iceberg, debugging, concurrency, maintenance, lakehouse, production-failures]
description: Final post of the series. Read CommitFailedException, ValidationException and FileNotFoundException like a triage nurse. Reproduce RepoSphere incidents where a double-fired scheduler, a compaction job and an over-eager remove_orphan_files hit the same Iceberg table, learn which writers really conflict, how to recover with rollback_to_snapshot, and the settings that prevent a repeat.
---

# 3 a.m., Two Jobs, One Table 🚨

In [Post 07](content/spark-production-failures/07-silent-wrong-answers.md), the danger was a job that **succeeded** and was wrong. Today's failures are the loud kind, and they arrive in a very specific way. Two things touch the RepoSphere `events` table at once:

- the nightly `daily_load` (the `MERGE` from [Post 13 of the first series](content/data-engineering/13-merge-into-in-depth.md)), and
- something else: a compaction, a manual re-run, a cleanup job.

One of them dies with a Java exception whose name you half recognise. The table is **either fine** or **quietly broken**, and the exception name is how you tell which.

This post is the last in the series, so it ties the earlier ones together: read the error (Post 01), find the real cause, change one thing, and **verify**. We'll do that for four Iceberg incidents, in order of how scary they are.

---

## The Shared Register Analogy 📒

Picture a paper register in an office. To change it, a clerk **photocopies** the current page, edits the copy, and walks back to swap it in. Nobody locks the register while they edit, because most edits don't clash.

At the swap, the clerk checks the page's **version stamp**. If it's still the one she copied, she swaps. If someone else swapped first, she has to take a fresh copy and redo her edit on top.

Now add a **cleaning crew** that throws away any loose papers lying on the floor that are older than some cutoff. Papers still in a clerk's hands are safe. Papers a clerk **put down for a minute** on the way to the register are not.

| Office | Iceberg |
|---|---|
| The register page | The table's current **metadata file** |
| The version stamp | The base snapshot a writer started from |
| Photocopy, edit, swap | Write data files, then **atomically swap** the pointer |
| "Someone swapped first, redo it" | **Commit retry** |
| "Your edit clashes with theirs" | `ValidationException` |
| Papers on the floor | **Orphan files** |
| The cleaning crew | `remove_orphan_files` |

If you read [Post 10 of the first series](content/data-engineering/10-why-table-formats-iceberg.md), this is its optimistic concurrency story again. Today we watch it fail.

---

## Read the Exception Name First 🏷️

Four exception families cover almost every Iceberg incident. The name tells you what kind of problem you have before you read a single line of the message.

![Exception triage: CommitFailedException means the pointer moved and retries ran out; ValidationException means a real conflict; NotFoundException means a file is missing; Cannot find snapshot means time travel to an expired snapshot](content/spark-production-failures/images/iceberg_exception_triage.svg)

| Exception | What it means | Is the table damaged? | First move |
|---|---|---|---|
| `CommitFailedException` | The pointer moved under you and the **retries ran out** | No. Your commit simply didn't happen | Look at what else committed; re-run |
| `ValidationException` | Another writer's change **conflicts** with what yours assumed | No. Iceberg refused to merge them | Read the message; re-run on fresh state |
| `CommitStateUnknownException` | The catalog **may or may not** have applied your commit | Unknown | Check `.snapshots` **before** retrying |
| `NotFoundException` / `FileNotFoundException` | The metadata points to a file that **isn't there** | **Yes**, or a reader raced a delete | Find which file, and who deleted it |
| `IllegalArgumentException: Cannot find snapshot ...` | You asked to time-travel to an **expired** snapshot | No | Pick a snapshot that still exists |

> **Key insight:** The first two rows are Iceberg **protecting** you. The commit failed so that your data would stay correct. The `NotFoundException` row is the one that means something already went wrong. Spend your adrenaline accordingly.

---

## How a Commit Actually Races 🏁

A short refresher, because every incident below is a variation on it. A write does this:

1. Read the table's current snapshot. Call it `S1` (the **base**).
2. Write new data files and a new metadata file that says "`S2` = `S1` plus my change".
3. **Swap** the pointer from `S1` to `S2`, atomically, only if it still says `S1`.

If the pointer already says `S2` (somebody else got there first), step 3 fails. Iceberg then **re-reads** the table, checks that the other change doesn't clash with yours, re-applies your change on top, and tries again.

The number of tries is a table property:

```sql
ALTER TABLE local.reposphere.events
SET TBLPROPERTIES ('commit.retry.num-retries' = '10')
```

`commit.retry.num-retries` defaults to **4**. There are sibling settings for the wait between tries (`commit.retry.min-wait-ms`, `commit.retry.max-wait-ms`) and a total time limit (`commit.retry.total-timeout-ms`). Check your Iceberg version's documentation for their defaults.

Whether the retry **succeeds** depends on one question: *do the two changes clash?*

| Writer 1 | Writer 2 | Clash? | Outcome |
|---|---|---|---|
| Append | Append | No | Both commit, one after a retry |
| Append | `MERGE` that updates rows | Possibly | Depends on whether the new files could match the merge condition |
| `MERGE` / `UPDATE` / `DELETE` | Another one touching the **same file** | Yes | One gets `ValidationException` |
| `rewrite_data_files` (compaction) | `MERGE` rewriting a file the compaction also rewrites | Yes | One gets `ValidationException` |
| Any writer | `expire_snapshots` / `remove_orphan_files` | Not a commit race at all | See Incident 4 |

---

## Incident 1: `CommitFailedException` From a Busy Table 🚦

**Symptom.** A load that always works fails with a commit error. Re-running it succeeds.

**What you see.** *Illustrative log excerpt.* The exact message text varies by catalog and version:

```
org.apache.iceberg.exceptions.CommitFailedException: Cannot commit: stale table metadata
```

**Root cause.** The writer lost the pointer swap so many times in a row that it ran out of retries. Two appends never clash, so every retry was *legal*. There were just too many writers swapping at once.

**First, find out who else was writing.** The `snapshots` metadata table from [Post 15 of the first series](content/data-engineering/15-snapshots-and-time-travel.md) lists every commit:

```python
(spark.table("local.reposphere.events.snapshots")
      .select("committed_at", "snapshot_id", "operation")
      .orderBy("committed_at")
      .show(truncate=False))
```

Read it as a timeline. Several `append` rows within seconds of each other is your answer: a crowd, not a clash.

**Fix, in order of preference:**

| Fix | Why it works |
|---|---|
| Fewer, bigger commits | One write per batch instead of one per partition or per micro-batch |
| Stagger the schedules | Two jobs that both start at 02:00 will meet at 02:05 |
| Raise `commit.retry.num-retries` | Buys headroom, but treats the symptom |

**How to verify.** After the change, the failing job should commit on the **first or second** attempt. If you need to keep raising the retry count, you have a scheduling problem, not a retry problem.

> **Trap:** `CommitStateUnknownException` looks like the same family but is not. It means a network error left the outcome unknown. **Do not** blindly re-run and do not delete files. Look at `.snapshots` first: if your snapshot is there, your commit succeeded, and a second run would be a duplicate unless the load is idempotent.

---

## Incident 2: `ValidationException` and the Double-Fired Scheduler 🔔

**Symptom.** The nightly `merge_repo_scd2` fails, and a second run of the **same** job was already in progress.

This one is common because it needs no bug in your code. A scheduler retried a job that looked hung, so now two copies of batch 2 are merging into `repo_dim` (the history table from [Post 14 of the first series](content/data-engineering/14-incremental-scd2.md)). Both want to update `c1`'s `valid_to` from 11:00 to 10:00.

**What you see.** *Illustrative log excerpt.* Two common wordings:

```
org.apache.iceberg.exceptions.ValidationException: Found conflicting files that can contain records matching <expression>: [<path>]
```

```
org.apache.iceberg.exceptions.ValidationException: Missing required files to delete: <path>
```

The first means: "while you worked, someone added data that **could** match your merge condition." The second means: "the file you meant to rewrite was already replaced."

**Root cause.** Both writers rewrote the file holding `c1`. Whoever commits second discovers that the file it started from is gone. Iceberg's default isolation for row-level writes is **serializable**: it refuses to commit if the result couldn't have come from running the two writes one after the other.

Isolation is a table property, one per operation:

| Property | Controls | Values |
|---|---|---|
| `write.merge.isolation-level` | `MERGE INTO` | `serializable` (default), `snapshot` |
| `write.update.isolation-level` | `UPDATE` | same |
| `write.delete.isolation-level` | `DELETE` | same |

**Fix.** The safe, boring sequence:

1. Confirm what committed in between (`.snapshots`, as above, and look at `operation` and `summary`).
2. **Re-run** the failed job. It starts from the fresh state, sees `c1` already corrected, finds nothing to change, and finishes. That works because the load is **idempotent**, the property [Post 12](content/data-engineering/12-idempotent-loads.md) and [Post 13](content/data-engineering/13-merge-into-in-depth.md) of the first series were built for.
3. Prevent the double-fire: one writer per table at a time, enforced by your scheduler's concurrency limit, not by hope.

> **Trap:** Don't "fix" this by switching `write.merge.isolation-level` to `snapshot`. Snapshot isolation lets two writers commit as long as they don't touch the same **files**, which means conflicts that serializable would have caught can now commit silently. You've turned a loud failure into a Post 07 failure.

**A related risk worth testing.** An insert-only `MERGE`, like `upsert_events`, is in effect an append guarded by an anti join that was evaluated against the snapshot it started from. If two copies of the **same batch** run at the same instant, both can read a snapshot that doesn't contain `e04`, and both can add it. Whether your Iceberg version catches that depends on how it plans insert-only merges, so **test it on a copy**. Either way, guard it with the check from Post 07:

```python
events = spark.table("local.reposphere.events")
events.count() == events.select("event_id").distinct().count()      # must be True
```

---

## Incident 3: Compaction Versus the Nightly Load 🧹

**Symptom.** Either `compact_events` or `daily_load` fails, depending on who commits second, when both run in the same hour. The error is a `ValidationException`.

[Post 17 of the first series](content/data-engineering/17-compaction-and-maintenance.md) warned about this. Compaction rewrites files into one bigger file. If the `MERGE` was updating a row in one of those same files, the two plans disagree about which file is the truth.

**Root cause.** Both writers replaced the same data file. This is the same clash as Incident 2, but between two **different kinds** of job.

**Fix.** Keep them apart in space or in time.

In space, compact only the partitions the load isn't touching. `rewrite_data_files` accepts a `where` filter:

```python
spark.sql("""
    CALL local.system.rewrite_data_files(
        table   => 'reposphere.events',
        where   => "created_ts < TIMESTAMP '2024-03-02 00:00:00'",
        options => map('min-input-files', '2', 'partial-progress.enabled', 'true')
    )
""")
```

That compacts 1 March and leaves 2 March, today's busy partition, alone. `partial-progress.enabled` commits the work in smaller pieces, so one conflict costs you one piece instead of the whole run.

In time, give the jobs separate windows and let your scheduler enforce them.

**How to verify.** Re-run the file count from Post 17:

```python
spark.table("local.reposphere.events.files").filter("content = 0").count()
```

The count should fall for the compacted day, and both jobs should finish in their windows without a `ValidationException`.

---

## Incident 4: The File That Vanished 👻

This is the one to be afraid of.

**Symptom.** Every read of `events` fails, not just the job that ran last. The table, which worked yesterday, is now unreadable.

**What you see.** *Illustrative log excerpt.* Remember to read to the **last** `Caused by`:

```
org.apache.iceberg.exceptions.NotFoundException: Failed to open input stream for file: <warehouse>/reposphere/events/data/<file>.parquet
Caused by: java.io.FileNotFoundException: File <warehouse>/reposphere/events/data/<file>.parquet does not exist
```

The metadata says the file belongs to the table. The storage says it doesn't exist. That's a **missing file**, and there are two ways to get there.

### Cause A: `remove_orphan_files` ate an in-flight write 🗑️

Recall from [Post 17](content/data-engineering/17-compaction-and-maintenance.md) that an **orphan** is a data file no snapshot mentions. A writer creates its data files **before** it commits. Until the commit lands, those files are, by definition, orphans.

An *illustrative* timeline for one night:

![A writer starts at 02:00 and writes data files; remove_orphan_files runs at 02:10 with older_than set to now and deletes those not-yet-committed files; the writer commits at 02:20 to a snapshot that references files that no longer exist](content/spark-production-failures/images/orphan_files_race.svg)

The cleanup job did exactly what it was told. The writer committed exactly what it wrote. And the result is a snapshot that points at nothing.

> **Why a margin?** `older_than` is the safety margin that separates "abandoned by a crashed writer" from "still being written". Iceberg's own default is three days. Setting it to `now` throws away the margin, and the longest write you have is now fair game.

### Cause B: `expire_snapshots` under a running reader 📖

A long query, or a time-travel read of an old snapshot, plans against the table's state at the start. If `expire_snapshots` runs in the middle and deletes files only that old snapshot used, the reader fails partway through with the same file-not-found error. Time travel to an already-expired snapshot fails earlier, at planning:

```
java.lang.IllegalArgumentException: Cannot find snapshot with ID <snapshot_id>
```

That second form harms nobody. It's the retention policy working.

### Triage, step by step 🔎

**1. Which file, and is it in the current table?**

```python
files = spark.table("local.reposphere.events.files")
files.filter(F.col("file_path").contains("<file>.parquet")).select("file_path", "record_count").show(truncate=False)
```

If the missing file is listed, **the current snapshot is broken** (Cause A). If it isn't, only an **old** snapshot or a running reader needed it (Cause B).

**2. When did the table last work?** List the snapshots and note the one **before** the suspect commit:

```python
spark.table("local.reposphere.events.snapshots").select("committed_at", "snapshot_id", "operation").orderBy("committed_at").show(truncate=False)
```

**3. Prove that snapshot is readable** before you trust it:

```python
spark.sql("SELECT count(*) FROM local.reposphere.events VERSION AS OF <good_snapshot_id>").show()
```

If that count succeeds, every file that snapshot needs is present.

**4. Roll the table back** to it:

```python
spark.sql("""
    CALL local.system.rollback_to_snapshot(
        table       => 'reposphere.events',
        snapshot_id => <good_snapshot_id>
    )
""")
```

**5. Re-run the load that was lost.** Because `upsert_events` is idempotent, replaying batch 2 inserts exactly the events that aren't there. That's the payoff of the whole of Part 2.

**How to verify.** `spark.table("local.reposphere.events").count()` completes without an exception, and for the ten-event lab data it returns `10` after both batches have been replayed.

> **Trap:** Rollback restores the table to the old state. It does **not** bring the deleted files back, and any commit made after the good snapshot is gone from the current state. Only roll back to a snapshot you proved readable in step 3, and expect to replay what came after it.

### Prevention checklist 🛡️

| Rule | Why |
|---|---|
| `older_than` for `remove_orphan_files` is **days**, not minutes | Must be longer than your slowest writer |
| Always `dry_run => true` first and **read the list** | It's free, and it names exactly what dies |
| Never run cleanup while a writer is running | Same table, same files |
| Agree retention before `expire_snapshots` | Time travel stops at the cutoff |
| Don't point one warehouse path at two catalogs | Each catalog's cleanup sees the other's files as orphans |

---

## Incident 5: The Small-File Slow Burn 🐌

Not every incident has a stack trace. Sometimes a job that took minutes last month takes an hour now, and the Spark UI shows a long **gap before the first task starts**.

**Symptom.** Slow planning, a huge number of tiny tasks, and a table that has never been compacted.

**Root cause.** Every commit adds files and a snapshot. A load that commits once a minute, or a shuffle that produces hundreds of tiny partitions per run ([Post 05](content/spark-production-failures/05-fetch-failed-and-shuffle-errors.md) of this series covers sizing them), creates thousands of small files. Every file costs a file open and a metadata entry on **every** read.

**Triage.** Two counts tell the story:

```python
spark.table("local.reposphere.events.files").filter("content = 0").count()   # data files now
spark.table("local.reposphere.events.snapshots").count()                     # commits so far
```

**Fix.** Compact ([Post 17](content/data-engineering/17-compaction-and-maintenance.md)), then fix the cause: commit less often, write bigger batches, and set the distribution so each task writes to few partitions:

```sql
ALTER TABLE local.reposphere.events
SET TBLPROPERTIES ('write.distribution-mode' = 'hash')
```

**How to verify.** The file count per partition drops, and the gap before the first task shrinks. Compare before and after on the **same** query. A gut feeling is not a measurement, and as [Post 22 of the first series](content/data-engineering/22-measure-before-tuning.md) argued, neither is one run.

---

## The Incident Pre-Flight Checklist ✅

| Check | Catches |
|---|---|
| One writer per table at a time, enforced by the scheduler? | Incident 2 |
| Compaction and loads in separate windows, or separate partitions? | Incident 3 |
| `older_than` longer than your slowest job, after a `dry_run`? | Incident 4A |
| Retention agreed before `expire_snapshots`? | Incident 4B |
| Loads idempotent, so a re-run is always safe? | Every recovery above |
| `count()` equals `distinct event_id` count after every load? | The silent cousins |

---

## Quick Quiz 🧠

**Q1.** A load fails with `CommitFailedException`. Is the table damaged?

<details>
<summary>Show answer</summary>

No. The exception means the **commit did not happen**: the pointer moved under the writer and its retries ran out. The table still holds the last good snapshot. Check `.snapshots` to see who else was writing, then re-run. `CommitStateUnknownException` is the one where you check `.snapshots` *first*, because your commit may have landed.

</details>

**Q2.** Why is switching `write.merge.isolation-level` to `snapshot` a poor fix for a `ValidationException`?

<details>
<summary>Show answer</summary>

Serializable isolation is what **detected** the conflict. Snapshot isolation only checks that writers didn't touch the same files, so some conflicts that serializable catches would now commit silently. You trade a loud failure for a silent wrong answer. Re-run the job on fresh state and make sure only one writer runs at a time.

</details>

**Q3.** `compact_events` and `daily_load` both run at 02:00 and one fails. Name two ways to stop that.

<details>
<summary>Show answer</summary>

Separate them **in time** (give each its own window in the scheduler) or **in space** (compact only old partitions with the `where` argument of `rewrite_data_files`, leaving today's partition to the load). Adding `partial-progress.enabled` also limits the cost of a conflict to one piece of the compaction.

</details>

**Q4.** After a night of cleanup, every read of `events` fails with a `FileNotFoundException`, and the missing file **is** listed in `events.files`. What probably happened, and what do you do?

<details>
<summary>Show answer</summary>

Most likely `remove_orphan_files` ran with a too-small `older_than` while a writer was still writing, deleted its not-yet-committed files, and the writer then committed a snapshot that references them. The **current snapshot is broken**. Find the last good snapshot in `.snapshots`, prove it with `VERSION AS OF`, roll back with `rollback_to_snapshot`, and replay the load. It is idempotent, so replaying is safe.

</details>

**Q5.** What is the difference between `Cannot find snapshot with ID ...` and a `FileNotFoundException` on a data file?

<details>
<summary>Show answer</summary>

The first is time travel to a snapshot that `expire_snapshots` has already removed. Nothing is broken; that's the retention policy. The second means metadata that **still exists** points at a file that doesn't, which is either a reader racing a cleanup (an old snapshot) or a corrupt current snapshot. Check whether the file appears in `.files` to tell which.

</details>

---

## That's the Series 🏁

Eight posts, one habit: **read the failure, form one hypothesis, change one thing, and verify the output against something you know.**

| Post | When you see... | Go to |
|---|---|---|
| 01 | Any failure, and you don't know where to start | [The Debugging Loop](content/spark-production-failures/01-the-debugging-loop.md) |
| 02 | Driver dies after `collect()`, a broadcast, or a huge listing | [Driver OOM](content/spark-production-failures/02-driver-oom-collect-and-broadcast.md) |
| 03 | Executor lost, exit code 137 or 143 | [Executor OOM and killed containers](content/spark-production-failures/03-executor-oom-and-container-killed.md) |
| 04 | One task runs for hours while the rest finish | [The straggler](content/spark-production-failures/04-the-straggler-skew-stuck-stage.md) |
| 05 | `FetchFailedException`, lost shuffle blocks | [Shuffle errors](content/spark-production-failures/05-fetch-failed-and-shuffle-errors.md) |
| 06 | Corrupt lines, nulls after a schema change | [Bad data and schema drift](content/spark-production-failures/06-bad-data-and-schema-drift.md) |
| 07 | Job succeeds, numbers are wrong | [Silent wrong answers](content/spark-production-failures/07-silent-wrong-answers.md) |
| 08 | Commit errors, vanished files | This post |

And if you haven't built RepoSphere itself yet, the 22-post series that created every table in these incidents starts here: 👉 **[Data Engineering from First Principles](content/data-engineering/01-what-is-data-engineering.md)**. To go back to the start of this series: 👉 **[Post 01, The Debugging Loop](content/spark-production-failures/01-the-debugging-loop.md)**.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
