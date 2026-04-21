---
title: "Context & Token Optimization — Control What the Model Sees"
date: 2026-04-22
tags: [github-copilot, context-management, token-optimization, workspace-indexing, session-hygiene, vscode]
description: Master context control in GitHub Copilot — understand how context is gathered from open tabs, semantic indexing, and chat history. Learn to use context operators efficiently, minimize noise, maintain session hygiene, and avoid repetitive prompts that waste tokens.
---

# Context & Token Optimization — Control What the Model Sees 🎯

This is **Post 3 of 10** in the Efficient AI Handbook.

The model only knows what you show it. Every open tab, every line of chat history, every file reference contributes to the **context payload** — the total information sent with each prompt. A bloated context means more tokens consumed, slower responses, and diluted attention. A precise context means sharper output and lower cost.

This post teaches you to control exactly what Copilot sees.

---

## How Copilot Gathers Context 🔬

When you send a prompt, Copilot assembles context from multiple sources — automatically, without asking you. Understanding these sources is the first step to controlling them.

| Source | What It Includes | You Control It By |
|---|---|---|
| **Active file** | The file currently open and focused in the editor | Switching tabs before prompting |
| **Open tabs** | Content from other open editor tabs (neighboring files) | Closing irrelevant tabs |
| **Selected text** | Any highlighted text in the editor | Highlighting precisely what you want |
| **Chat history** | All previous messages in the current chat session | Using `/clear` or starting a new session |
| **Semantic index** | Repository-wide code search results (`@workspace`, `#codebase`) | `.gitignore`, `files.exclude` settings |
| **Custom instructions** | `.github/copilot-instructions.md` and `.instructions.md` files | Editing these files directly |
| **MCP tool results** | Data returned by MCP servers (Jira, GitHub, Postgres) | Choosing which tools to invoke |

> **Key insight:** You pay for ALL of this context — not just your prompt text. Ten open tabs of unrelated files plus a long chat history can easily double the tokens consumed per request.

---

## Context Operators — When to Use Each 🏷️

Copilot Chat provides specific operators to reference context explicitly. Using the right one for the task avoids over-fetching.

### `#file` — Reference a Specific File

```
#file:src/deploy.py — What does the deploy_to_staging function do?
```

**When to use:** You need the model to analyze a specific file. You know which file matters.

**Token cost:** Low — only that file's content is included.

### `#folder` — Reference a Directory

```
#folder:src/actions/ — List all the custom GitHub Actions in this folder
```

**When to use:** You need awareness of multiple related files in a directory.

**Token cost:** Medium — all files in the folder are scanned.

### `#selection` — Reference Selected Text

```
#selection — Refactor this function to use async/await
```

**When to use:** You've highlighted exactly what needs to change. Most precise operator.

**Token cost:** Minimal — only the selected lines are included.

### `@workspace` — Semantic Search Across the Project

```
@workspace — Where is the database connection string configured?
```

**When to use:** You don't know which file contains what you need. The semantic index searches your entire repository.

**Token cost:** High — retrieves multiple relevant code chunks across the codebase.

### `#codebase` — Deep Codebase Search

```
#codebase — Find all places where we handle authentication errors
```

**When to use:** You need exhaustive, cross-file search results. Similar to `@workspace` but optimized for broader queries.

**Token cost:** Highest — scans the full index.

### Decision Table

| You Know... | Use | Token Cost |
|---|---|---|
| The exact code block | `#selection` | ★☆☆☆☆ |
| The exact file | `#file` | ★★☆☆☆ |
| The folder but not the file | `#folder` | ★★★☆☆ |
| Roughly what you need, not where | `@workspace` | ★★★★☆ |
| Need exhaustive cross-file search | `#codebase` | ★★★★★ |

> **Default to the most specific operator.** If you know the file, don't use `@workspace`. The less you load, the better the output quality and the lower the token cost.

---

## Open Tabs — The Silent Context Tax 📑

This is the single most underappreciated source of token waste.

**How it works:** Copilot scans your open editor tabs to gather "neighboring file" context. This helps it understand your project structure, naming conventions, and patterns. But it means every open tab contributes to the context payload — whether relevant or not.

**The problem:** Developers commonly have 15–30 tabs open. If you're working on a GitHub Actions workflow but have `models/user.py`, `frontend/app.tsx`, and `tests/conftest.py` open from a previous task, those files are injected as context — diluting attention and consuming tokens for zero benefit.

**The fix:**

```
Before starting a new task:
1. Close all tabs (Ctrl+K, Ctrl+W)
2. Open ONLY the files relevant to your current task
3. Then start prompting
```

> **Pro tip:** VS Code's "Close All Editor Tabs" shortcut (`Ctrl+K, Ctrl+W`) should become muscle memory. Use it every time you switch tasks.

---

## Session Hygiene — `/clear` Is Your Best Friend 🧹

Chat history accumulates across a session. Each new prompt includes the full conversation history as context. After 10–15 exchanges, you're sending thousands of tokens of old conversation with every new prompt.

### When to `/clear`

| Scenario | Action |
|---|---|
| Switching from one Jira story to another | `/clear` |
| Switching from Python code to YAML workflow | `/clear` |
| The model starts repeating itself or hallucinating | `/clear` |
| You've resolved an issue and are starting a new task | `/clear` |
| The chat feels "sluggish" | `/clear` (bloated context) |

### When NOT to `/clear`

| Scenario | Action |
|---|---|
| You're iterating on the same function | Keep history |
| The model's last response needs refinement | Follow up, don't clear |
| You're in a multi-step Agent mode session | Let it retain context |

> **Rule of thumb:** If your next prompt is unrelated to the last 3–5 messages, clear first. You'll get a better response AND save tokens.

---

## Avoiding Repetitive Prompts ♻️

Restating the same prompt is the most direct form of token waste. Here's how to avoid it:

### Pattern 1: Edit Your Last Message

Most Copilot Chat interfaces let you edit your previous prompt instead of typing a new one. Editing means the model re-processes with the revised prompt — without losing the conversation context or sending a redundant message.

### Pattern 2: Follow Up with Constraints

Instead of re-asking the same question with small changes:

```
❌ Prompt 1: "Write a deploy script"
❌ Prompt 2: "Write a deploy script in Python"
❌ Prompt 3: "Write a deploy script in Python with error handling"
```

Do this:

```
✅ Prompt 1: "Write a deploy script in Python with error handling"
   (Be specific upfront — one prompt, done)
```

Or if you need to iterate:

```
✅ Prompt 1: "Write a deploy script"
✅ Follow-up: "Add error handling with try/except and logging"
✅ Follow-up: "Use pathlib instead of os.path"
```

### Pattern 3: Anchor with "Keep X, Change Y"

When the output is 90% right but needs a tweak:

```
✅ "Keep the overall structure but replace the requests library with httpx"
✅ "This is correct. Now add type hints to all function signatures"
```

This tells the model exactly what to preserve and what to modify — no ambiguity, no wasted regeneration.

---

## Truncate Verbose Output ✂️

When debugging, developers often paste entire log dumps into chat. A 500-line traceback can consume thousands of tokens while the relevant information is in 5 lines.

**Before pasting output into chat, always:**

1. Find the actual error message (usually the last 5–10 lines)
2. Find the relevant stack frame (the line in YOUR code, not library internals)
3. Paste ONLY those lines

```
❌ (Pasting 200 lines of pip install output + traceback)

✅ "The workflow fails at the pytest step with this error:
   tests/test_deploy.py::test_staging_deploy FAILED
   AssertionError: Expected status 200 but got 403
   The deploy function is in src/deploy.py lines 45-60"
```

> **Token savings:** Truncating a 500-line log to the 10 relevant lines can reduce token consumption by 80%+ for that single prompt.

---

## Enterprise Content Exclusion 🏢

If you're on Copilot Enterprise, organization admins can configure **content exclusion** policies that prevent specific files or patterns from being indexed or sent as context.

**Common exclusions for DevOps repositories:**

| Pattern | Why Exclude |
|---|---|
| `**/*.generated.*` | Large auto-generated files inflate context |
| `**/vendor/**` | Third-party code is irrelevant to your logic |
| `**/node_modules/**` | Huge dependency tree — no value as context |
| `**/*.min.js` | Minified code is unreadable context noise |
| `**/terraform.tfstate` | Contains sensitive infrastructure state |
| `**/.env*` | May contain secrets — never send to an LLM |

Contact your org admin to configure these patterns in the Copilot policy settings on GitHub.com.

---

## Quick Reference — Token Optimization Checklist ✅

Before every task:

- [ ] Close irrelevant tabs
- [ ] `/clear` if switching tasks
- [ ] Open only the files relevant to the current task
- [ ] Use the most specific context operator (`#file` > `@workspace`)
- [ ] Truncate any logs or output before pasting
- [ ] Start with Sonnet (1x), escalate only if needed
- [ ] Follow up to refine — don't re-ask from scratch

---

## What's Next? 🚀

Your environment is configured, your model strategy is set, and you know how to keep context lean. Now let's connect Copilot to external tools — so it can pull Jira stories, create GitHub PRs, and query your database without leaving VS Code.

👉 **[Post 4 — MCP Servers: GitHub & Atlassian](content/efficient-ai/04-mcp-servers-github-and-atlassian.md)** — Set up Model Context Protocol servers to give Copilot access to your team's real-world tools.

---

*— Ashwin*
