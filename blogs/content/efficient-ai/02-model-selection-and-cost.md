---
title: "Model Selection & Cost Control — Spend Smart on Claude"
date: 2026-04-22
tags: [github-copilot, claude, opus, sonnet, premium-requests, cost-optimization, token-management]
description: Master the GitHub Copilot premium request multiplier system — understand the true cost of each Claude model, build a task-to-model decision matrix, use Auto mode strategically, and learn practical token budgeting to maximize output quality while minimizing spend.
---

# Model Selection & Cost Control — Spend Smart on Claude 💰

This is **Post 2 of 10** in the Efficient AI Handbook.

Every prompt you send to GitHub Copilot consumes resources. On included models like GPT-4.1, that's free. On Claude Opus 4.7, a single prompt burns 7.5 premium requests. Over a week of active development, the wrong default model choice can exhaust your entire monthly budget — leaving you locked to free-tier models for the rest of the billing cycle.

This post teaches you to match models to tasks systematically, so you get the best output for the least cost.

---

## The Premium Request System 📊

GitHub Copilot uses a **multiplier system** for premium requests. Your plan includes a monthly allowance of premium requests. Each model interaction deducts from this allowance at a different rate.

| Model | Multiplier | What 1 Prompt Costs | Best Suited For |
|---|---|---|---|
| **GPT-4.1 / GPT-5 mini** | 0x | Free (included) | Quick completions, simple Q&A, boilerplate |
| **Claude Sonnet 4.6** | 1x | 1 premium request | Daily coding, refactoring, explanations, test writing |
| **Claude Opus 4.5** | 3x | 3 premium requests | Complex debugging, multi-file reasoning |
| **Claude Opus 4.6** | 3x | 3 premium requests | Deep refactors, architectural analysis, agentic tasks |
| **Claude Opus 4.7** | 7.5x | 7.5 premium requests | Hardest problems only — complex multi-step reasoning |
| **Auto** | Varies (−10%) | 10% discount on whatever model is selected | General-purpose routing |

> **What happens when you run out?** Once your premium requests are exhausted, you fall back to included models (GPT-4.1, GPT-5 mini) for the remainder of the billing period. You can still code — but you lose access to Claude entirely until the cycle resets.

---

## The Model Decision Matrix 🧭

Stop guessing. Use this matrix to pick the right model for every task:

### Tier 1 — Included Models (0x): GPT-4.1 / GPT-5 mini

Use for tasks that don't require deep reasoning:

- Generating boilerplate code (import statements, class scaffolds)
- Simple documentation questions ("What does `subprocess.PIPE` do?")
- Formatting and syntactic transformations
- Inline code completions (Tab-accept suggestions)

### Tier 2 — Claude Sonnet 4.6 (1x): Your Daily Driver

This should be your **default model** for 80%+ of work:

- Writing Python functions, classes, and modules
- Generating pytest test cases
- Writing GitHub Actions workflow YAML
- Code reviews and refactoring suggestions
- Explaining existing code
- Writing docstrings and README sections
- Debugging straightforward errors with a clear traceback

> **Rule of thumb:** If you can describe the task in one sentence, Sonnet can handle it.

### Tier 3 — Claude Opus 4.5 / 4.6 (3x): The Expert

Reserve for tasks where Sonnet's quality is measurably insufficient:

- Multi-file refactors that require understanding cross-file dependencies
- Debugging complex issues where the root cause is non-obvious
- Architectural decisions (e.g., "Should I use a queue or polling for this workflow?")
- Agent mode for multi-step tasks (scaffold → implement → test → iterate)
- Security reviews and vulnerability analysis

### Tier 4 — Claude Opus 4.7 (7.5x): The Specialist

Use sparingly — only for the hardest problems:

- Debugging issues that span 10+ files with no clear traceback
- Performance optimization requiring algorithmic reasoning
- Complex system design discussions
- When Opus 4.5/4.6 produces incorrect or incomplete output

> **Golden rule:** Start with Sonnet. If the output is wrong or shallow, escalate to Opus 4.5/4.6. Only go to 4.7 if 4.5/4.6 also fails. Never start at the top.

---

## Auto Mode — When to Use It ⚡

Setting the model picker to **Auto** lets GitHub route your request to the most efficient model for the task. Benefits:

- **10% discount** on premium request cost (a 1x model costs 0.9x in Auto)
- GitHub's routing is trained to match task complexity to model capability
- Saves you the cognitive load of choosing a model every time

**When to use Auto:**
- General-purpose daily work where you don't have a strong model preference
- Mixed sessions with varying task complexity

**When NOT to use Auto:**
- You specifically need Opus-level reasoning (pin it manually)
- You want to guarantee 0x cost (pin GPT-4.1)
- You're doing cost-sensitive bulk work (pin Sonnet at 1x)

---

## Token Budgeting — Practical Strategies 📋

### Calculate Your Daily Budget

If your plan includes 1,000 premium requests per month:

```
Monthly budget:    1,000 premium requests
Working days:      ~22
Daily budget:      ~45 premium requests

If 80% on Sonnet (1x) + 20% on Opus (3x):
  Sonnet: 36 prompts × 1x = 36 requests
  Opus:    9 prompts × 3x = 27 requests
  Total:   63 requests → over budget!

Adjusted to 90% Sonnet + 10% Opus:
  Sonnet: 40 prompts × 1x = 40 requests
  Opus:    4 prompts × 3x = 12 requests
  Total:   52 requests → still over budget

Actual sustainable split (with buffer):
  Sonnet: 35 prompts × 1x = 35 requests
  Opus:    3 prompts × 3x =  9 requests
  Total:   44 requests → within budget ✅
```

> **Key insight:** Just 3 Opus prompts per day consume 20% of your daily budget. This is why Sonnet-first is non-negotiable.

### Track Your Usage

- **VS Code:** The Copilot status bar shows remaining premium requests
- **GitHub.com:** Navigate to Settings → Copilot → Usage to see detailed consumption
- **Set a mental alarm:** If you're past 50% of your monthly budget before mid-month, switch to GPT-4.1 for routine tasks

---

## Real Cost Scenarios 💡

### Scenario 1: Writing a GitHub Actions Workflow (Good)

```
Prompt 1 (Sonnet): "Create a CI workflow that runs pytest on push to main"    → 1x
Prompt 2 (Sonnet): "Add matrix testing for Python 3.10, 3.11, and 3.12"     → 1x
Prompt 3 (Sonnet): "Add pip caching to speed up installs"                    → 1x
Total: 3 premium requests
```

### Scenario 2: Same Task, Wasteful Approach (Bad)

```
Prompt 1 (Opus 4.6): "Create a complete CI/CD pipeline with testing,
caching, matrix, deployment, notifications, and Slack integration"           → 3x
Prompt 2 (Opus 4.6): "That's not quite right, fix the caching step"         → 3x
Prompt 3 (Opus 4.6): "Remove the Slack part, I don't need it"               → 3x
Total: 9 premium requests (3× more for the same result!)
```

**What went wrong:** Used Opus for a Sonnet-appropriate task, asked for everything in one overloaded prompt (got a messy result), then spent more Opus prompts fixing it.

### Scenario 3: Debugging a Complex Issue (Justified Escalation)

```
Prompt 1 (Sonnet): "Why does this workflow fail with exit code 2?"           → 1x
Prompt 2 (Sonnet): (Answer is generic, not helpful)                          → 1x
Prompt 3 (Opus 4.6): "Here's the full error log [truncated]. The failure
is in the matrix step for Python 3.10 only. Analyze the root cause."         → 3x
Total: 5 premium requests — justified escalation after Sonnet failed
```

---

## The "Refine, Don't Repeat" Principle 🔄

One of the biggest token wasters is restarting a conversation when the output isn't right. Instead:

**❌ Don't do this:**
```
Prompt 1: "Write a function to parse YAML config"
→ Output is mostly right but uses PyYAML instead of ruamel
Prompt 2: "Write a function to parse YAML config using ruamel.yaml"
→ Entire prompt re-processed from scratch
```

**✅ Do this:**
```
Prompt 1: "Write a function to parse YAML config"
→ Output uses PyYAML
Follow-up: "Use ruamel.yaml instead of PyYAML, keep everything else"
→ Targeted refinement, less input tokens, better result
```

The follow-up approach consumes fewer tokens because the model already has the context. You're refining, not restarting.

---

## Model Selection Cheat Sheet 📝

| Task | Model | Multiplier | Why |
|---|---|---|---|
| Inline code completions | GPT-4.1 | 0x | Fast, free, good enough for autocomplete |
| "What does this function do?" | Sonnet | 1x | Explanations don't need deep reasoning |
| Write a pytest fixture | Sonnet | 1x | Straightforward code generation |
| Write a GitHub Actions workflow | Sonnet | 1x | Structured YAML is Sonnet's sweet spot |
| Refactor across 5 files | Opus 4.5/4.6 | 3x | Cross-file reasoning needed |
| Debug a race condition | Opus 4.5/4.6 | 3x | Non-obvious root cause analysis |
| "Design a plugin architecture" | Opus 4.6 | 3x | Architectural reasoning |
| Agent mode: scaffold + test + iterate | Opus 4.5/4.6 | 3x | Multi-step autonomy justified |
| Nothing else worked | Opus 4.7 | 7.5x | Last resort only |

---

## What's Next? 🚀

You know *which* model to pick. But the model is only as good as the context you feed it. Open tabs, lingering chat history, and verbose log dumps silently degrade quality and inflate token usage.

👉 **[Post 3 — Context & Token Optimization](content/efficient-ai/03-context-and-token-optimization.md)** — Learn to control exactly what the model sees, minimize noise, and keep sessions clean.

---

*— Ashwin*
