---
title: "Why Table Formats? Apache Iceberg"
date: 2026-10-22
tags: [data-engineering, apache-iceberg, lakehouse, table-formats, acid, first-principles]
description: Part 2 begins. Why a folder of Parquet files is not a table once RepoSphere loads daily batches with replays and late changes, how Iceberg's metadata tree turns files into a table, why a commit is one atomic pointer swap, how optimistic concurrency lets two writers share a table, and how Iceberg compares with Delta Lake. Includes a 40-line toy table format you can run.
---

# A Folder Is Not a Table 🧊

In [Post 09](content/data-engineering/09-aggregates-and-full-pipeline.md), Part 1 came together. Seven functions, one `main()`, and the session summary we promised back in [Post 01](content/data-engineering/01-what-is-data-engineering.md).

But that pipeline has a secret. It's **stateless**. Every run reads *all* the raw files, recomputes *everything*, and forgets it ever ran.

That worked for one small file. Now RepoSphere wants three things:

1. **Daily batches.** Load each day's new files, not the whole history again.
2. **Safe re-runs.** Upstream retries resend rows. Loading the same batch twice must change nothing.
3. **Audit.** "Show me exactly what `repo_dim` said after Monday's load."

The moment you add those, you need somewhere to **keep** data between runs. And the obvious answer, "write Parquet files to a folder", turns out to be the wrong one.

This post is about why. No new pipeline function yet. Just the one idea that the rest of Part 2 stands on: **a table format**.

---

## The Library Catalogue Analogy 📚

Think about how a big library knows what's on its shelves.

Nobody walks the aisles counting books. There's a **catalogue**. If a book is in the catalogue, it's in the collection. If it isn't, it isn't, even if it's physically sitting on a shelf.

When a new batch of books arrives:

- Staff shelve them in a back room first. Visitors can't find them yet.
- They print a **new edition** of the catalogue that includes the new books.
- Then, in one move, they swap the old catalogue on the front desk for the new one.

Anyone who picked up the catalogue before the swap sees the old collection, start to finish. Anyone after sees the new one. Nobody sees half a delivery. And the old editions go in a drawer, so you can always check what the library held last Tuesday.

| Library | Iceberg | RepoSphere |
|---|---|---|
| Books on shelves | **Data files** (Parquet) | The rows of `events` and `repo_dim` |
| A catalogue edition | **Snapshot** (via a metadata file) | "events after batch 1" |
| The catalogue on the front desk | **Catalog pointer** | `local.reposphere.events` → current metadata |
| Swapping the catalogue | **Atomic commit** | Batch 2 becomes visible, all at once |
| Old editions in a drawer | **Time travel** | "What did events say after batch 1?" |
| A book shelved but never catalogued | **Orphan file** | Data written by a load that crashed |

Hold on to that last row. It explains most of this post.

---

## Part 1 Was Stateless. Part 2 Isn't 🔁

Here's what the next two days look like for RepoSphere. These are the two lab batches we'll use for the rest of the series.

| File | Lines | What's inside |
|---|---|---|
| `batch_1/events.jsonl` | 6 | e01–e05, with **e03 sent twice** |
| `batch_1/repo_changes.jsonl` | 3 | c1, c3 for repo 101 · c4 for repo 202 |
| `batch_2/events.jsonl` | 7 | **e04, e05 replayed** · e06 at 23:40 on **1 March** (late) · e07–e10 on 2 March, e10 with no login |
| `batch_2/repo_changes.jsonl` | 3 | **c3 replayed** · **c2 late**, landing between c1 and c3 · c6 for a **new repo 303** |

Three new problems fall straight out of that table:

| Problem | RepoSphere example | What a naive append does |
|---|---|---|
| **Duplicates** | e04, e05 and c3 arrive again in batch 2 | Stores them twice |
| **Corrections** | c2 at 10:00 means c1's `valid_to` must change from 11:00 to 10:00 | Can't. The old row is already written |
| **Audit** | "Show `repo_dim` as of batch 1" | The batch-1 state is gone |

Part 1 never had to answer any of these, because it threw everything away after each run. Part 2 can't.

---

## Six Ways a Parquet Folder Lets You Down 💥

The obvious way to store Part 1's output is a folder of Parquet files, one sub-folder per day. Hive-style:

```python
(flat_events
    .write
    .mode("append")
    .partitionBy("event_date")
    .parquet("lake/events"))
```

After two days, the folder looks something like this:

```
lake/events/
├── event_date=2024-03-01/
│   ├── part-00000-<uuid>.c000.snappy.parquet
│   └── part-00001-<uuid>.c000.snappy.parquet
└── event_date=2024-03-02/
    └── part-00000-<uuid>.c000.snappy.parquet
```

Any engine can read it. So what's wrong? The definition of "the table" is: **whatever files happen to be in the folder right now.** Every problem below comes from that one rule.

| # | Problem | RepoSphere moment | What a reader sees |
|---|---|---|---|
| 1 | **Partial writes** | Batch 2's job writes 2 of its 3 files, then the cluster dies | Half of batch 2. No error, just wrong counts |
| 2 | **No in-place updates** | c2 arrives late. c1's `valid_to` must become 10:00 | Parquet files can't be edited. You rewrite the file, and readers mid-rewrite see c1 missing or twice |
| 3 | **No history** | Auditors ask for `repo_dim` as of batch 1 | Overwritten. It's gone |
| 4 | **Uncoordinated writers** | The daily load and a backfill write to the same folder at once | Whatever mix of files survives. Nobody is told |
| 5 | **Slow file discovery** | Two years of daily folders on S3 | Every query starts by listing thousands of prefixes |
| 6 | **Schema drift** | Batch 2 adds `actor_id`; batch 1's files don't have it | Engines disagree on the columns unless you remember `mergeSchema` |

> **Key insight:** None of these are Parquet's fault. Parquet is an excellent **file** format. The problem is that a folder is a terrible **table**. It has no way to say "these exact files, as of this exact moment".

There's a seventh, subtler one, which we'll fix in [Post 11](content/data-engineering/11-catalogs-and-hidden-partitioning.md). Hive-style partitioning puts `event_date` in the folder name, so a query filtering on `created_ts` (the real timestamp) can't skip any folders. Your users have to know the trick.

---

## What a Table Format Actually Is 🧊

A **table format** is a small set of metadata files that sits next to your data files and answers one question precisely:

> **Which data files make up this table, as of which moment?**

That's all. The data stays in plain Parquet. Iceberg, Delta Lake and Hudi are all table formats. They differ in *how* they record that list.

**Apache Iceberg** (born at Netflix, now an Apache project) records it as a tree. Here's our `events` table after both batches:

![The Iceberg metadata tree](content/data-engineering/images/iceberg_metadata_tree.svg)

Read it top to bottom. Each level has one job:

| Level | What it holds | How many | RepoSphere |
|---|---|---|---|
| **Catalog** | Table name → path of the current metadata file | One entry per table | `local.reposphere.events` |
| **Metadata file** (`*.metadata.json`) | Schema, partition spec, properties, the list of all snapshots, which one is current | A new one per commit | 6 columns, `days(created_ts)`, S1 and S2 |
| **Manifest list** | The manifests that make up one snapshot | One per snapshot | S2 → M1 + M2 |
| **Manifest** | Data file paths, plus per-file stats: row count, min/max per column, partition value | One or more per commit | M2 → files C and D |
| **Data file** | The rows, as Parquet | Many | e01 … e10 |

Two details in that picture do a lot of work.

**S2 reuses M1.** Batch 2 didn't rewrite anything batch 1 wrote. It added a new manifest (M2) and a new manifest list that points at **both** old and new. Appends are cheap.

**Manifests carry min/max stats.** A query for `created_ts >= '2024-03-02'` reads the manifests, sees that files A, B and C all max out on 1 March, and opens only file D. No folder listing, and a lot of files never opened.

> **Key insight:** In a folder, a file is in the table because it's **in the folder**. In Iceberg, a file is in the table because the **current snapshot lists it**. Everything else in this post follows from that switch.

On disk, with the local `hadoop` catalog we'll configure in Post 11, the same table looks roughly like this:

```
warehouse/reposphere/events/
├── data/
│   ├── created_ts_day=2024-03-01/
│   │   └── 00000-<task>-<uuid>-00001.parquet
│   └── created_ts_day=2024-03-02/
│       └── 00000-<task>-<uuid>-00001.parquet
└── metadata/
    ├── v1.metadata.json          ← table created, no snapshots
    ├── v2.metadata.json          ← snapshot S1 (batch 1)
    ├── v3.metadata.json          ← snapshot S2 (batch 2)
    ├── version-hint.text         ← "3": the pointer
    ├── snap-<id>-1-<uuid>.avro   ← manifest lists
    └── <uuid>-m0.avro            ← manifests
```

The folder names under `data/` are a convenience for humans. Iceberg never reads them to decide what's in the table.

---

## Build a Toy Table Format in 40 Lines 🛠️

The fastest way to *get* this is to build a tiny version. Standard-library Python only, no Spark. It keeps JSON-lines data files, a metadata file per commit, and a `CURRENT` file as the catalog pointer.

```python
import json, os, uuid

T = "toy/events"
os.makedirs(f"{T}/data", exist_ok=True)
os.makedirs(f"{T}/metadata", exist_ok=True)

class CommitFailed(Exception):
    pass

def current():
    """The catalog: which metadata file is live right now?"""
    if not os.path.exists(f"{T}/CURRENT"):
        return None
    return open(f"{T}/CURRENT").read()

def live_files(meta):
    return json.load(open(meta))["files"] if meta else []

def read(meta="latest"):
    meta = current() if meta == "latest" else meta
    return sorted(json.loads(line)["event_id"]
                  for f in live_files(meta) for line in open(f))

def write_data_file(rows):
    """Step 1: write data. Nothing points at this file yet."""
    path = f"{T}/data/{uuid.uuid4().hex[:6]}.jsonl"
    with open(path, "w") as fh:
        fh.writelines(json.dumps(r) + "\n" for r in rows)
    return path

def commit(base, new_files):
    """Step 2: write new metadata. Step 3: swap the pointer, only if nobody beat us."""
    meta = f"{T}/metadata/{uuid.uuid4().hex[:6]}.metadata.json"
    with open(meta, "w") as fh:
        json.dump({"parent": base, "files": live_files(base) + new_files}, fh)
    if current() != base:          # a real catalog does this check-and-swap atomically
        raise CommitFailed("someone else committed first")
    with open(f"{T}/CURRENT.tmp", "w") as fh:
        fh.write(meta)
    os.replace(f"{T}/CURRENT.tmp", f"{T}/CURRENT")   # the one atomic step
    return meta
```

Notice what `read` does. It never lists `data/`. It asks the pointer for the current metadata, and reads exactly the files that metadata names.

### Scenario 1: a crash in the middle of batch 2

Batch 1 lands (deduplicated to five events), then batch 2 starts writing and the cluster dies before it commits:

```python
# Batch 1: five distinct events land as two files, then ONE commit
f1 = write_data_file([{"event_id": "e01", "actor_login": "dave"},
                      {"event_id": "e02", "actor_login": "dave"},
                      {"event_id": "e03", "actor_login": "dave"}])
f2 = write_data_file([{"event_id": "e04", "actor_login": "dave"},
                      {"event_id": "e05", "actor_login": "jim"}])
snap1 = commit(None, [f1, f2])
print("after batch 1:", read())

# Batch 2, attempt 1: data written... then the cluster dies before commit()
f3 = write_data_file([{"event_id": "e06", "actor_login": "jim"},
                      {"event_id": "e07", "actor_login": "jim"}])
print("after crash:  ", read())
print("files on disk:", len(os.listdir(f"{T}/data")), "| files in table:", len(live_files(current())))
```

```
after batch 1: ['e01', 'e02', 'e03', 'e04', 'e05']
after crash:   ['e01', 'e02', 'e03', 'e04', 'e05']
files on disk: 3 | files in table: 2
```

Three files on disk, two in the table. The third is an **orphan**: a book on the shelf that never made the catalogue. Readers can't see it, so there's no "half of batch 2". The orphan just wastes space until a cleanup job removes it ([Post 17](content/data-engineering/17-compaction-and-maintenance.md)).

With a plain folder, that same crash would have left e06 and e07 visible to every reader.

### Scenario 2: two writers at once

Now batch 2 runs again, and at the same moment a small "late arrivals" job wants to add e06. Both start from the same snapshot:

```python
snap1 = current()

# Two jobs start at the same time. Both read the same base snapshot.
base_a = current()                       # daily load (batch 2)
base_b = current()                       # late-arrivals job

fa = write_data_file([{"event_id": e, "actor_login": a} for e, a in
                      [("e07", "jim"), ("e08", "meera"), ("e09", "dave"), ("e10", None)]])
fb = write_data_file([{"event_id": "e06", "actor_login": "jim"}])

commit(base_a, [fa])                     # A wins the race
try:
    commit(base_b, [fb])                 # B's base is stale
except CommitFailed as err:
    print("B:", err)
    commit(current(), [fb])              # retry on top of A's snapshot
    print("B: retried and committed")

print("latest:      ", read())
print("as of snap 1:", read(snap1))
```

```
B: someone else committed first
B: retried and committed
latest:       ['e01', 'e02', 'e03', 'e04', 'e05', 'e06', 'e07', 'e08', 'e09', 'e10']
as of snap 1: ['e01', 'e02', 'e03', 'e04', 'e05']
```

Three things just happened, and they're the three headline features of Iceberg:

| What you saw | The feature | Where we use it |
|---|---|---|
| The crash changed nothing readers could see | **Atomic commits** | Every write in Part 2 |
| B's stale commit was refused, then retried safely | **Optimistic concurrency** | Daily loads next to compaction |
| `read(snap1)` still returns batch 1 | **Time travel** | [Post 15](content/data-engineering/15-snapshots-and-time-travel.md) |

> **Trap:** The toy's `if current() != base` check and the swap after it are two separate steps. Another process could sneak in between them. A real catalog does the check and the swap as **one** indivisible operation. That's the entire job of a catalog, and it's why you can't just point Iceberg at any shared folder (more on that below).

---

## How a Real Commit Works ⚛️

Real Iceberg does exactly what the toy does, with sturdier parts:

![One Iceberg commit](content/data-engineering/images/iceberg_atomic_commit.svg)

1. **Write data files.** New Parquet files for e06 … e10. No metadata mentions them, so no reader can see them.
2. **Write new metadata.** A manifest for the new files, a manifest list for snapshot S2 (pointing at the new manifest *and* the old ones), and a new `metadata.json` that lists S2 as current.
3. **Swap the pointer.** Ask the catalog: "if the table's current metadata is still S1's, point it at S2's." This is the **commit**. It either happens completely or not at all.

The bottom row of that diagram is the whole value of the design. A crash after step 1 or step 2 leaves the table **exactly** as it was. A crash after step 3 means the commit succeeded. There's no fourth state.

And look at the last box: queries that started before the swap keep reading S1's files until they finish. They don't suddenly see new rows half-way through a scan. That's **snapshot isolation**, and you get it for free, because nothing in S1 was ever changed. It was only *replaced* as "current".

Who performs that swap depends on the catalog:

| Catalog | How "swap the pointer" is made atomic | Use it for |
|---|---|---|
| `hadoop` | An atomic file **rename** to `v<N+1>.metadata.json` in the warehouse | Local learning, HDFS |
| `hive` | A lock-protected update in the Hive Metastore | Existing Hadoop estates |
| `glue` | A conditional update of the table entry in AWS Glue | AWS |
| `rest` (incl. Polaris, Unity, Nessie-backed) | The catalog service does the compare-and-swap | Most new platforms |

> **Trap:** The `hadoop` catalog relies on the file system's rename being atomic. Local disk and HDFS give you that. Object stores like S3 don't, so two writers could both "win". It's perfect for this series, which runs locally. In production on S3, use a real catalog.

---

## Optimistic Concurrency 🤝

There are two ways to stop two writers from trampling each other.

**Pessimistic:** lock the table, do your work, unlock. Safe, but every writer waits for every other writer, even when they'd never have clashed. A two-hour compaction would block your daily load for two hours.

**Optimistic:** don't lock anything. Do all your work against the snapshot you started from. At the very end, try the swap. If someone else committed in the meantime, the swap fails, and you sort it out then.

![Optimistic concurrency](content/data-engineering/images/optimistic_concurrency.svg)

| | Pessimistic (locks) | Optimistic (Iceberg) |
|---|---|---|
| When is the table checked? | Before you start | Once, at commit |
| Cost when writers don't clash | Waiting anyway | None |
| Cost when they do | Waiting | One failed swap, then a retry or an error |
| A crashed writer | Can leave a stale lock behind | Leaves orphan files, never a broken table |
| Best when | Clashes are common | Clashes are rare, which is most lakehouses |

"Sort it out" has two outcomes in real Iceberg:

- **No real conflict.** Writer A appended files; writer B appended other files. Those changes don't touch each other. Iceberg refreshes to the new snapshot, re-applies B's change on top, and tries the swap again, without rewriting B's data files. This is automatic, up to `commit.retry.num-retries` times (default 4).
- **A real conflict.** Both writers tried to change the **same rows**. Say two jobs both update c1's `valid_to`, or compaction rewrote the very file B's MERGE was updating. Iceberg's validation spots that B's work was based on data that no longer exists, and B's commit **fails with an error**. Nobody's update is silently lost. You re-run B against the new state.

> **Why optimistic?** Analytics tables have few writers and long-running jobs. Clashes are rare, and when they happen, failing loudly and re-running is far cheaper than making every job queue behind a lock.

Remember this when we get to [Post 12](content/data-engineering/12-idempotent-loads.md). A re-run is only safe if the load is **idempotent**. Optimistic concurrency and idempotent loads are a team: the first guarantees a failed attempt leaves no trace, the second guarantees the retry doesn't double anything.

---

## Time Travel Falls Out for Free ⏳

Look back at the metadata tree. When batch 2 committed, nothing about S1 was deleted. Its manifest list still exists, its manifest (M1) still exists, its data files still exist. The metadata file simply lists S1 as an older snapshot.

So "what did `events` look like after batch 1?" is just: read the table, but start from S1's manifest list instead of S2's.

```sql
SELECT * FROM local.reposphere.events VERSION AS OF <batch_1_snapshot_id>
ORDER BY created_ts
```

```
+--------+----------------+-------------------+----------+-------+-----------+
|event_id|event_type      |created_ts         |event_date|repo_id|actor_login|
+--------+----------------+-------------------+----------+-------+-----------+
|e01     |pushevent       |2024-03-01 09:50:00|2024-03-01|101    |dave       |
|e02     |pullrequestevent|2024-03-01 10:10:00|2024-03-01|202    |dave       |
|e05     |pushevent       |2024-03-01 10:15:00|2024-03-01|202    |jim        |
|e03     |issuesevent     |2024-03-01 10:40:00|2024-03-01|101    |dave       |
|e04     |pushevent       |2024-03-01 11:20:00|2024-03-01|101    |dave       |
+--------+----------------+-------------------+----------+-------+-----------+
```

Five rows, even though e03 appeared twice in the batch-1 file, because the real load dedupes first ([Post 12](content/data-engineering/12-idempotent-loads.md)). Six columns, even after we add `actor_id` in [Post 16](content/data-engineering/16-schema-evolution.md), because each snapshot remembers the schema it was written with.

> **Trap:** Time travel is not free forever. Every old snapshot pins its data files on disk. That's why Iceberg has **snapshot expiry**: you choose how much history to keep, and older snapshots (and the files only they used) get cleaned up. We'll do that in [Post 17](content/data-engineering/17-compaction-and-maintenance.md).

---

## Iceberg vs Delta Lake (and Hudi) ⚖️

You'll hear three names. All three are table formats over Parquet, and all three give you atomic commits, time travel and `MERGE INTO`. The difference is how they track the file list, and which ecosystem grew up around them.

| | **Apache Iceberg** | **Delta Lake** | **Apache Hudi** |
|---|---|---|---|
| Started at | Netflix | Databricks | Uber |
| Tracks files with | Metadata tree: `metadata.json` → manifest list → manifests | Transaction log: numbered JSON commits in `_delta_log/`, plus Parquet checkpoints (every 10 commits by default) | Timeline of commits in `.hoodie/`, plus record-level indexes |
| Commit point | Catalog swaps the metadata pointer | Writing the next numbered log file, which must not already exist | Completing an instant on the timeline |
| Partitioning | **Hidden**, via transforms like `days(ts)`; spec can evolve | Explicit partition columns, or liquid clustering | Explicit partition path fields |
| Time travel | `VERSION AS OF <snapshot_id>` or `TIMESTAMP AS OF` | `VERSION AS OF <version number>` or `TIMESTAMP AS OF` | Point-in-time and incremental queries on the timeline |
| Compaction | `CALL … rewrite_data_files` | `OPTIMIZE` | Built-in table services |
| Upsert | `MERGE INTO` | `MERGE INTO`, nearly identical syntax | Upsert is the core write path |
| Strongest at | Many engines on one table (Spark, Flink, Trino, cloud warehouses) | Tight integration with Databricks and Spark | High-frequency, record-level upserts and CDC |

> **Key insight:** The formats have been converging for years. Delta's UniForm can write Iceberg metadata alongside its own, and most cloud warehouses now read Iceberg directly. Pick by **ecosystem** first: which engines and catalog your team already runs. The concepts in this series (snapshots, atomic commits, MERGE, compaction) carry over to all three.

We use Iceberg because RepoSphere's brief asks for it, and because its design (a pointer to an immutable tree) makes the ideas easy to see.

---

## Where Part 2 Goes From Here 🗺️

Here's how each problem from the folder maps onto Iceberg, and the post where we'll write the code:

| Problem | Iceberg answer | Function | Post |
|---|---|---|---|
| Where does the table live? | Catalog + `CREATE TABLE IF NOT EXISTS`, hidden `days(created_ts)` | `init_spark_session`, `create_tables` | 11 |
| Replays (e04, e05) | Dedupe + anti join, align columns by name | `upsert_events` | 12 |
| Insert only what's new | Insert-only `MERGE INTO`, null-safe updates | `upsert_events` | 13 |
| Late change c2 | Rebuild affected repos, diff, `MERGE INTO` | `merge_repo_scd2` | 14 |
| "As of batch 1" | Snapshots metadata table, `VERSION AS OF` | `list_snapshots`, `read_events_as_of` | 15 |
| New column `actor_id` | Metadata-only schema change | `evolve_events_schema` | 16 |
| Small files, old snapshots, orphans | `rewrite_data_files`, expiry, orphan cleanup | `compact_events` | 17 |
| All of it, twice in a row | A full idempotent daily run | `main()` | 18 |

---

## Quick Quiz 🧠

**Q1.** RepoSphere's batch-2 load writes its Parquet files and its new manifests, then the cluster dies before the catalog swap. What does a reader see, and is it safe to just re-run the load?

<details>
<summary>Show answer</summary>

The reader sees **snapshot S1**, exactly as before: the 5 batch-1 events. The new data files and manifests are **orphans**, because no metadata the catalog points at mentions them. Re-running is safe: the re-run starts from S1 again and commits a fresh S2. The orphans just waste disk space until orphan cleanup removes them.

</details>

**Q2.** A teammate copies a Parquet file containing e11 straight into `warehouse/reposphere/events/data/created_ts_day=2024-03-02/`. Does e11 show up in `SELECT * FROM local.reposphere.events`?

<details>
<summary>Show answer</summary>

**No.** Iceberg never lists the data folders. A file is part of the table only if a manifest in the **current snapshot** lists it, and no commit ever added this one. To Iceberg it's just another orphan. (With a plain Hive-style folder, it *would* appear. That's exactly the problem.)

</details>

**Q3.** In the toy's Scenario 2, how many files end up in `toy/events/metadata/`, and why is the extra one harmless?

<details>
<summary>Show answer</summary>

**Four:** batch 1's commit, writer A's commit, writer B's **failed** first attempt, and B's successful retry. The failed attempt's metadata file was written in step 2, but its pointer swap was refused, so nothing points at it. Like an orphan data file, it's invisible to readers and only costs a little disk space.

</details>

**Q4.** Two jobs run at once. Job A updates c1's `valid_to` to 10:00. Job B, started from the same snapshot, also rewrites the data file that holds c1. A commits first. What happens to B under optimistic concurrency?

<details>
<summary>Show answer</summary>

B's swap fails because the current snapshot is no longer the one it started from. This time Iceberg's conflict check finds that B's work depends on a file A's commit **replaced**, so it can't simply re-apply B on top. B's commit **fails with an error** instead of quietly overwriting A's update. You re-run B against the new state. Compare that with two appends, which don't conflict and are retried automatically.

</details>

**Q5.** Your team runs everything on Databricks. A colleague asks: "Should we use Iceberg or Delta for the RepoSphere tables?" What's a good answer?

<details>
<summary>Show answer</summary>

Both give you atomic commits, snapshots/time travel, `MERGE INTO` and compaction, so either can meet RepoSphere's requirements. Decide by **ecosystem**: Delta is native to Databricks. Iceberg shines when several engines (Trino, Flink, a cloud warehouse) must share the same tables through one catalog, and its hidden partitioning and partition evolution are nicer to live with. Delta UniForm can also expose Delta tables as Iceberg, so it's not a one-way door.

</details>

---

## What's Next? 🚀

You now know *why* a lakehouse needs a table format, and what Iceberg keeps on disk to make a folder of Parquet files behave like a table. Time to create one.

Next, we wire Iceberg into Spark, configure the local `hadoop` catalog, and create both RepoSphere tables, safely re-runnable and partitioned by `days(created_ts)` without a partition column in sight.

👉 **[Post 11 — Catalogs and Hidden Partitioning](content/data-engineering/11-catalogs-and-hidden-partitioning.md)** — `init_spark_session`, `create_tables`, the `local` catalog with a `warehouse/` folder, `IF NOT EXISTS`, format version 2, and `days(created_ts)`.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
