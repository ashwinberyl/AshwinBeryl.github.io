---
title: "What Data Engineering Actually Is — Facts, Dimensions & the RepoSphere Problem"
date: 2026-10-10
tags: [data-engineering, first-principles, facts, dimensions, pyspark, iceberg, beginner]
description: The first post in the Data Engineering from First Principles series. What a data engineer really does, why raw data is never ready to use, the difference between facts and dimensions, and the RepoSphere case study we'll build end to end with PySpark and Apache Iceberg.
---

# Why This Series Exists 🚰

Most data engineering content starts with a tool. "Here's how to write a Spark job." "Here's how to create an Iceberg table." You copy the code, it runs, and you still couldn't tell someone *why* the pipeline looks the way it does.

This series goes the other way. We start from the problem: **data is produced in one place, in one shape, at one time — and it's needed somewhere else, in a different shape, at a different time.** Every tool we meet will show up only when the problem forces it on us.

And we'll build **one real pipeline, end to end**, across 18 posts:

| Part | Posts | What we build |
|---|---|---|
| **Part 1 — The Pipeline** | 01 – 09 | A PySpark job that turns raw JSON events into work sessions with history-correct details |
| **Part 2 — The Lakehouse** | 10 – 18 | The same pipeline on Apache Iceberg: daily loads, safe re-runs, full audit history |

Every post works on the same small dataset, shows the full answer, and ends with a quick quiz. By the end, you'll be able to explain every line — and every null — in the output.

---

## What a Data Engineer Actually Does 🏗️

Think about the water in your tap.

It didn't start there. It started in a reservoir — mixed with mud, leaves and who knows what. Before it reaches you, someone has to **collect** it, **treat** it, **store** it, and **pipe** it to millions of homes. When it works, nobody thinks about it. When it doesn't, everybody notices.

Data works exactly the same way:

| Water | Data | Example |
|---|---|---|
| Reservoir | **Sources** | App databases, REST APIs, webhooks, log files |
| Intake pipe | **Ingestion** | Pull the raw data in and land it, untouched |
| Treatment plant | **Transformation** | Clean, flatten, deduplicate, join, aggregate |
| Storage tank | **Storage** | Tables that can be queried and trusted |
| Your tap | **Consumers** | Dashboards, ML models, product features |

![The Data Journey](content/data-engineering/images/data_journey.svg)

The data engineer owns the middle: **ingestion, transformation, storage.** Not the dashboard. Not the model. The plumbing that makes them possible.

And "good plumbing" means three specific things:

1. **Correct** — the numbers mean what people think they mean.
2. **Repeatable** — running the job twice gives the same answer, not double the answer.
3. **Cheap** — it scales without the bill scaling faster.

> **Key insight:** Analysts ask questions. Data engineers make sure the answers are *true*. A beautiful dashboard on top of a broken pipeline is just a confident lie.

---

## Why Raw Data Is Never Ready 🤔

If the source already has the data, why not just point the dashboard at it?

Because raw data has problems that only show up when you try to *use* it:

- **It's nested.** An event is a JSON object inside a JSON object. Dashboards want flat columns.
- **It's incomplete.** Some records are missing fields. Not always the same ones.
- **It's inconsistent.** `PushEvent` and `PUSHEVENT` are the same thing, written two ways.
- **It's late.** A record written at 10:00 can arrive *after* one written at 11:00.
- **It changes.** The thing an event points to — a product, a customer, a repo — doesn't stay the same over time.

That last one is the hardest, and it's the heart of this whole series. Let's meet the business that has all five problems at once.

---

## Meet RepoSphere 🌐

**RepoSphere** is a made-up GitHub. Developers — called **actors** — do things to **repositories** (repos): push code, open pull requests, file issues. Every action is recorded as an **event**.

Here's one event, exactly as RepoSphere writes it:

```json
{"event_id":"e01","event_type":"PushEvent","created_at":"2024-03-01T09:50:00Z","repo":{"id":101,"name":"alpha-api"},"actor":{"id":1,"login":"priya"}}
```

One JSON object per line, one line per event. Nested `repo` and `actor` objects. A timestamp in UTC (the `Z`).

Repos also change over time — they get renamed, or flip between public and private. RepoSphere records every change in a second file, and each row is a **full snapshot** of the repo at that moment:

```json
{"change_id":"c2","repo_id":101,"changed_at":"2024-03-01T10:00:00Z","repo_name":"alpha-api","visibility":"private","default_branch":"main"}
```

So we have two inputs:

| File | Contains | Rows in our sample |
|---|---|---|
| `events.jsonl` | What developers *did* | 9 events from 3 actors |
| `repo_changes.jsonl` | What repos *looked like*, and when that changed | 5 changes across 2 repos |

You can download both: [events.jsonl](https://ashwinberyl.github.io/blogs/content/data-engineering/data/events.jsonl) · [repo_changes.jsonl](https://ashwinberyl.github.io/blogs/content/data-engineering/data/repo_changes.jsonl). They're tiny on purpose — small enough to trace by hand, but built to hit every edge case a real pipeline meets.

---

## Facts vs Dimensions 📊

Those two files aren't just two files. They're two fundamentally different *kinds* of data, and every warehouse in the world is built around the difference.

| | **Facts** | **Dimensions** |
|---|---|---|
| **Record** | Things that *happened* | The things *involved* |
| **RepoSphere** | Events (push, PR, issue) | Repos (name, visibility, branch) |
| **Other examples** | Orders, payments, clicks | Products, customers, stores |
| **Grows by** | Adding new rows, constantly | Changing slowly, occasionally |
| **Question it answers** | "How many? When? Who?" | "What was it like?" |

A fact is a **verb**: *priya pushed to repo 101 at 09:50.* It never changes — it happened.

A dimension is a **noun**: *repo 101 is called alpha-api and it's public.* That can change tomorrow.

> **Why this matters:** Almost every interesting question joins the two. "How many pushes went to *private* repos?" needs the fact (the push) and the dimension (the visibility). And the moment a dimension can change, you have to ask: *visibility as of when?*

---

## The Problem a Simple Count Can't Solve ⏱️

RepoSphere's product team wants two things.

### 1. Work sessions

Not "priya made 5 events today", but:

> *"priya worked from 09:50 to 10:40 and touched 2 repos. Then she came back at 11:20."*

To get that, we have to group each developer's events into **bursts of activity** — splitting wherever there's a long enough pause. That's called **sessionization**, and it's Post 07.

### 2. History-correct repo details

Here's what happened to repo 101 on 1 March:

![Repo 101 history](content/data-engineering/images/repo101_history.svg)

At 10:40, priya filed an issue (event `e03`) on repo 101. **Right now** repo 101 is public and called `alpha-service`. But at 10:40 it was called `alpha-api` and it was **private**.

If the report says "public", it's wrong. Not slightly wrong — it's telling auditors that activity happened on a public repo when it didn't. The report must join each event to the version of the repo that was true **when the event happened**. That's a **point-in-time join**, and it's Post 08.

To even *have* those versions, we first have to keep every past version of each repo, with a start and end time. That's a **Slowly Changing Dimension, Type 2**, and it's Post 06.

---

## Your First Look at the Data 🐍

No Spark yet — just plain Python, to feel the problems with our own hands. Save the two files into a `data/` folder and run:

```python
import json
from collections import Counter

with open("data/events.jsonl") as f:
    events = [json.loads(line) for line in f]           # one JSON object per line

print("Events:", len(events))

# Who did how much?  .get() because not every event has a login
actors = Counter(e["actor"].get("login") for e in events)
print("Per actor:", dict(actors))

# What do the event types look like?
print("Event types:", sorted({e["event_type"] for e in events}))
```

```
Events: 9
Per actor: {'priya': 5, 'rahul': 3, None: 1}
Event types: ['IssuesEvent', 'PUSHEVENT', 'PullRequestEvent', 'PushEvent']
```

Two problems already:

- **One event has no login** (`None`). That's `e09` — its `actor` object has an `id` but no `login`. If we'd written `e["actor"]["login"]`, the whole script would have crashed with a `KeyError`.
- **`PushEvent` and `PUSHEVENT`** are counted as two different types. Any "pushes per day" chart would quietly undercount.

Now the repo changes, for repo 101:

```python
import json

with open("data/repo_changes.jsonl") as f:
    changes = [json.loads(line) for line in f]

repo_101 = [c for c in changes if c["repo_id"] == 101]

print("File order:")
for c in repo_101:
    print(" ", c["change_id"], c["changed_at"], c["repo_name"], c["visibility"])

print("Time order:")
for c in sorted(repo_101, key=lambda c: c["changed_at"]):
    print(" ", c["change_id"], c["changed_at"], c["repo_name"], c["visibility"])
```

```
File order:
  c1 2024-03-01T09:00:00Z alpha-api public
  c3 2024-03-01T11:00:00Z alpha-service public
  c2 2024-03-01T10:00:00Z alpha-api private
Time order:
  c1 2024-03-01T09:00:00Z alpha-api public
  c2 2024-03-01T10:00:00Z alpha-api private
  c3 2024-03-01T11:00:00Z alpha-service public
```

`c2` — the change to private — was written to the file **after** `c3`, even though it happened **before** it. That's **late-arriving data**. Any logic that trusts file order would think the repo went `public → renamed → private` and get the 10:40 event wrong.

> **The lesson of this whole post in one line:** the order rows arrive in is not the order things happened. Every tool we use from here on exists to deal with that, at scale.

---

## The Vocabulary You'll Need 📖

We'll unpack each of these in its own post. For now, just recognise the words:

| Term | Plain meaning | Post |
|---|---|---|
| **JSON Lines** (`.jsonl`) | A text file with one JSON object per line | 03 |
| **Nested field** | A field inside a field, like `actor.login` | 03, 04 |
| **Snapshot** | A change row holds the *whole* state, not just what changed | 06 |
| **Late-arriving data** | A row whose timestamp is earlier than rows already seen | 06 |
| **Dimension** | A table that describes things rather than recording actions | 06 |
| **SCD Type 2** | A dimension that keeps every past version, with valid-from and valid-to | 06 |
| **Sessionize** | Split one person's events wherever there's a long enough pause | 07 |
| **Point-in-time join** | Join each event to the dimension version true *when it happened* | 08 |

---

## The Shape of the Pipeline 🗺️

Here's what we'll build in Part 1. Seven functions, each taking a DataFrame and returning a new one. Two inputs flow through separate lanes and meet at the join:

![The RepoSphere pipeline](content/data-engineering/images/reposphere_pipeline.svg)

| # | Function | What it does | Post |
|---|---|---|---|
| 1 | `read_events` | Read the events file with an explicit schema | 03 |
| 2 | `read_repo_changes` | Read the repo changes file with an explicit schema | 03 |
| 3 | `flatten_events` | Flatten nested fields, parse timestamps, normalise case | 04 |
| 4 | `build_repo_scd2` | Turn change snapshots into versions with valid-from/valid-to | 05, 06 |
| 5 | `sessionize_actor_events` | Number each actor's work sessions | 05, 07 |
| 6 | `enrich_with_repo_state` | Attach the repo version that was true at event time | 08 |
| 7 | `compute_session_summary` | One row per session: start, end, repos touched | 09 |

Because each function is a pure "DataFrame in, DataFrame out" step, we can build and test them **one at a time**. And at the end of Part 1, here's the exact output we'll produce:

```
+-----------+----------+-------------------+-------------------+----------------------+-----------------+-----------------------------+
|actor_login|session_id|session_start      |session_end        |distinct_repos_touched|events_in_session|primary_repo_at_session_start|
+-----------+----------+-------------------+-------------------+----------------------+-----------------+-----------------------------+
|priya      |1         |2024-03-01 09:50:00|2024-03-01 10:40:00|2                     |3                |alpha-api                    |
|priya      |2         |2024-03-01 11:20:00|2024-03-01 11:20:00|2                     |2                |alpha-service                |
|rahul      |1         |2024-03-01 10:15:00|2024-03-01 10:35:00|1                     |2                |null                         |
|rahul      |2         |2024-03-01 12:30:00|2024-03-01 12:30:00|1                     |1                |null                         |
+-----------+----------+-------------------+-------------------+----------------------+-----------------+-----------------------------+
```

Some of those values look odd right now. Why does rahul's first session have a `null` repo, when repo 202 clearly exists? Why is priya's second session `alpha-service` and not `beta-web`? Where did the 9th event go? By Post 09, every one of those will be obvious.

---

## Quick Quiz 🧠

Commit to an answer before you open each one.

**Q1.** RepoSphere also logs *stars*: "rahul starred repo 202 at 14:05". Is a star a fact or a dimension?

<details>
<summary>Show answer</summary>

**A fact.** It's something that *happened*, at a specific time, involving an actor and a repo. It's a verb. The repo it points to is the dimension.

</details>

**Q2.** A repo's description is updated from "API service" to "Payments API". Product says "just overwrite it, nobody needs the old one". What can you no longer answer?

<details>
<summary>Show answer</summary>

Any question about the past: *"What was the description when this event happened?"* Overwriting keeps only today's truth. That's fine for some fields (SCD Type 1) — but for visibility, where auditors care about history, you need every version (SCD Type 2, Post 06).

</details>

**Q3.** Why did `Counter` show `None: 1`, and what would have happened with `e["actor"]["login"]`?

<details>
<summary>Show answer</summary>

Event `e09` has an `actor` object with only an `id` — no `login` key. `.get("login")` returns `None` for a missing key; `["login"]` raises a `KeyError` and crashes the script. Real pipelines must never assume every nested field exists. Post 03 shows how explicit schemas solve this in Spark.

</details>

**Q4.** Change `c2` sits after `c3` in the file. If a pipeline processed changes in file order, what visibility would it give event `e03` at 10:40?

<details>
<summary>Show answer</summary>

In file order the repo's history looks like `c1 (09:00, public) → c3 (11:00, alpha-service) → c2 (10:00, private)` — which doesn't even make sense as a timeline. Depending on the logic, `e03` would get **public** (from `c1`) or a broken interval. The correct answer, using time order, is **private**: at 10:40 the `c2` version `[10:00, 11:00)` was in force.

</details>

**Q5.** Which three properties make a pipeline "good plumbing"?

<details>
<summary>Show answer</summary>

**Correct**, **repeatable**, and **cheap**. Part 1 of this series is mostly about *correct*. Part 2 (Iceberg) is mostly about *repeatable* and *cheap*.

</details>

---

## What's Next? 🚀

We know the problem, the data and the destination. Now we need a tool that can do all this on 9 rows today and 9 billion rows tomorrow — without us changing the code.

👉 **[Post 02 — Spark from First Principles](content/data-engineering/02-spark-from-first-principles.md)** — DataFrames, lazy evaluation, the five verbs you'll use constantly, and the NULL trap that silently deletes your data.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
