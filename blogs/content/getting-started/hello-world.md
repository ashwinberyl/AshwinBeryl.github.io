---
title: Hello World — My First Blog Post
date: 2026-03-13
tags: [welcome, meta]
description: A quick intro to this blog and what you can expect to find here.
---

# Welcome!

This is my first blog post on [ashwinberyl.github.io/blogs](https://ashwinberyl.github.io/blogs). I built this space to share what I learn day-to-day as a **DevSecOps Platform Engineer** — from Kubernetes deep dives to CI/CD optimization tricks.

## What to expect

- **DevOps & Cloud** — Real-world lessons from running production Kubernetes clusters, managing AWS infrastructure, and automating everything.
- **Security** — Shift-left security patterns, SonarQube/BlackDuck integrations, and supply chain security.
- **Tooling & Automation** — Python scripts, GitHub Actions workflows, MCP servers, and AI-powered developer tools.
- **Career & Learning** — Notes from certifications, conferences, and the continuous learning journey.

## How this blog works

This blog is **100% static** — no build step, no CMS, no database. Here's the flow:

1. I write posts as **Markdown files** (`.md`) with YAML front-matter
2. I organize them into **folders and subfolders** in the repo
3. I push to GitHub — **that's it**

The sidebar you see on the left mirrors the folder structure. Each post is rendered client-side using [marked.js](https://marked.js.org/) with syntax highlighting powered by [highlight.js](https://highlightjs.org/).

## A code example

Here's a simple Kubernetes command I run daily:

```bash
kubectl get pods -n platform -o wide
```

And a Python snippet:

```python
def calculate_reading_time(text: str) -> int:
    """Estimate reading time in minutes."""
    words = len(text.split())
    return max(1, round(words / 200))
```

## Stay tuned

More posts coming soon. If you have topic suggestions, feel free to reach out via the [contact form](https://ashwinberyl.github.io/#contact)!

---

*— Ashwin*
