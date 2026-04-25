---
title: "The Jira-to-Code Workflow — From Story to Implementation Plan"
date: 2026-04-22
tags: [github-copilot, jira, workflow, requirements, implementation-plan, agent-mode, devops, python]
description: The complete developer loop from Jira story to implementation plan — pull requirements via Atlassian MCP, decompose with prompt templates, generate technical plans, and scaffold code structure using Agent mode.
---

# The Jira-to-Code Workflow — From Story to Implementation Plan 📋

This is **Post 6 of 10** in the Efficient AI Handbook.

This post covers the **first half** of the developer loop: taking a Jira story and transforming it into a concrete implementation plan — entirely within VS Code using Copilot and MCP servers. [Post 7](content/efficient-ai/07-coding-and-validation.md) covers the second half: coding, testing, PR creation, and closing the loop.

---

## The Complete Developer Loop 🔄

Here's the end-to-end flow we're building across Posts 6 and 7:

| Step | What Happens | Tool |
|---|---|---|
| **1. Pull requirements** | Fetch Jira story into Copilot Chat | Atlassian MCP |
| **2. Analyze requirements** | Decompose into scope, criteria, edge cases | Copilot Chat (Sonnet) |
| **3. Generate plan** | Create technical implementation plan | Agent mode (Sonnet/Opus) |
| **4. Scaffold** | Create branch, generate file structure | Agent mode + GitHub MCP |
| **5. Implement** | Write code (Python, YAML) | Agent/Edit mode |
| **6. Test** | Write and run tests | Agent mode |
| **7. Create PR** | Open PR with description | GitHub MCP |
| **8. Close the loop** | Transition Jira, add comments | Atlassian MCP |

This post covers Steps 1–4. Let's begin.

---

## Step 1 — Pull Requirements from Jira 📥

Instead of switching to the Jira web UI, copying text, and pasting into chat, use the Atlassian MCP server to fetch the story directly.

### The Prompt

```
Switch to Agent mode, then:

"Using Atlassian MCP, get the full details of Jira story DEVOPS-142.
Include the description, acceptance criteria, sub-tasks, labels,
priority, and any comments from the team."
```

Copilot calls the Atlassian MCP tool, fetches the issue, and presents the full story context in chat — title, description, AC, comments, priority, and labels.

> **Why MCP instead of copy-paste?** Three reasons: (1) the MCP tool fetches structured data the model can parse better than raw pasted text, (2) you keep your entire workflow in VS Code — no context-switching, (3) you can follow up with questions about the story without re-fetching.

---

## Step 2 — Analyze and Decompose Requirements 📐

Raw Jira stories are often ambiguous or incomplete. Before writing a single line of code, decompose the story into actionable components.

### The Prompt Template

```
Based on the Jira story DEVOPS-142 you just fetched, analyze the
requirements and produce:

1. **Scope** — What exactly needs to be built? List each deliverable.
2. **Acceptance Criteria** — Rewrite the AC as testable assertions
   (Given/When/Then format).
3. **Edge Cases** — What scenarios are NOT covered in the story but
   need handling? (error states, empty inputs, timeouts, permissions)
4. **Out of Scope** — What should explicitly NOT be built in this story?
5. **Dependencies** — What existing code, services, or APIs does this
   depend on?
6. **Open Questions** — What's ambiguous? List questions I should
   clarify with the PM before starting.
```

### Why Each Section Matters

| Section | Why It Prevents Problems |
|---|---|
| **Scope** | Prevents scope creep — defines the boundary |
| **Acceptance Criteria** | Each AC becomes a test case — validates completeness |
| **Edge Cases** | Catches bugs before they're written |
| **Out of Scope** | Prevents gold-plating — you build what's needed, nothing more |
| **Dependencies** | Surfaces blockers early |
| **Open Questions** | Saves hours of rework from bad assumptions |

> **Model choice:** Use **Sonnet (1x)** for this step. Requirements decomposition is structured analysis — it doesn't need Opus-level reasoning.

### Handling Ambiguous Stories

If the Jira story is sparse (one-liner descriptions with no AC), prompt Copilot to generate the missing structure:

```
"The Jira story only has a title: 'Add retry logic to deploy script.'
Based on typical DevOps patterns, generate:
- A detailed description of what this likely means
- 5 acceptance criteria in Given/When/Then format
- 3 edge cases to handle
Flag anything that needs PM clarification."
```

This is where Copilot adds the most value early in the loop — it turns a one-line ticket into a structured requirements document in seconds.

---

## Step 3 — Generate the Implementation Plan 📝

Now that requirements are clear, generate a technical plan that maps each requirement to specific code changes.

### The Prompt Template

```
Based on the requirements analysis above, generate an implementation
plan for a Python + GitHub Actions codebase. Include:

1. **Files to create/modify** — List each file with its purpose
2. **Architecture decisions** — Any patterns or libraries to use (with
   justification)
3. **Implementation order** — Which files to build first (dependencies
   flow)
4. **Test strategy** — What tests are needed (unit, integration) and
   which file they go in
5. **Estimated complexity** — Simple / Medium / Complex for each file

Format as a markdown checklist I can use as a task tracker.
```

### Example Output (Condensed)

For a story like "Create a GitHub Action that checks for stale PRs and posts a Slack notification":

```markdown
## Implementation Plan — DEVOPS-142

### Files to Create
- [ ] `src/stale_pr_checker.py` — Core logic: query GitHub API for PRs
      older than N days (Simple)
- [ ] `src/slack_notifier.py` — Format and send Slack messages (Simple)
- [ ] `.github/actions/stale-pr-check/action.yml` — Composite action
      definition with inputs/outputs (Medium)
- [ ] `.github/workflows/stale-pr-check.yml` — Scheduled workflow
      triggering the action (Simple)

### Files to Modify
- [ ] `requirements.txt` — Add `requests` for Slack webhook (Simple)
- [ ] `README.md` — Document the new action (Simple)

### Architecture Decisions
- Use `requests` library (already in the codebase) over `httpx`
- Use composite action (not JavaScript action) — aligns with our
  Python-first standard from copilot-instructions.md
- Slack webhook URL stored as repository secret `SLACK_WEBHOOK_URL`

### Test Strategy
- [ ] `tests/test_stale_pr_checker.py` — Unit tests with mocked
      GitHub API responses
- [ ] `tests/test_slack_notifier.py` — Unit tests with mocked webhook

### Implementation Order
1. `stale_pr_checker.py` (no dependencies)
2. `slack_notifier.py` (no dependencies)
3. Tests for both
4. `action.yml` (depends on both Python files)
5. `stale-pr-check.yml` (depends on action.yml)
6. README update
```

> **When to escalate to Opus:** If the story involves complex cross-file refactoring, new architectural patterns, or multiple service interactions, switch to **Opus 4.5/4.6 (3x)** for the plan generation. For straightforward feature additions, Sonnet produces excellent plans.

---

## Step 4 — Branch and Scaffold 🌿

With the plan in hand, create a working branch and scaffold the file structure.

### Using Agent Mode

```
Agent mode prompt:
"Create a new git branch named 'feat/DEVOPS-142-stale-pr-check' from
main. Then create the following empty files with appropriate module
docstrings:
- src/stale_pr_checker.py
- src/slack_notifier.py
- tests/test_stale_pr_checker.py
- tests/test_slack_notifier.py
- .github/actions/stale-pr-check/action.yml
- .github/workflows/stale-pr-check.yml"
```

Agent mode will run `git checkout -b`, create the files, and add initial docstrings — giving you a clean starting point for implementation.

> **💡 Make this a Skill:** Scaffolding is the most repeatable step in the developer loop. Instead of typing this prompt every time, save it as a `SKILL.md` in `.github/skills/scaffold-feature/`. Bundle a module template, test template, and your team's naming conventions as assets — then just type *"scaffold a new feature for DEVOPS-142"* and Copilot auto-detects the skill and executes the full procedure consistently. See [Post 8 — Skills](content/efficient-ai/08-prompt-engineering-foundations.md) for setup details.

### Branch Naming Convention

Use a consistent pattern that links to Jira:

```
feat/DEVOPS-142-short-description    ← Feature work
fix/DEVOPS-143-fix-deploy-timeout    ← Bug fix
chore/DEVOPS-144-update-deps         ← Maintenance
```

> **Why include the Jira ID?** It creates traceability between branches, PRs, and Jira stories. Many teams configure Jira to auto-link PRs when the story key appears in the branch name.

---

## Choosing the Right Mode for Each Step 🎛️

Not every step needs Agent mode. Here's a decision guide:

| Step | Recommended Mode | Why |
|---|---|---|
| Pull Jira story | Agent mode | MCP tools require Agent mode |
| Analyze requirements | Ask mode | You want analysis, not file changes |
| Generate implementation plan | Ask mode | Produces a plan in chat (no file changes yet) |
| Create branch + scaffold files | Agent mode | Needs terminal access + file creation |
| Write implementation code | Agent or Edit mode | Depends on scope (see Post 7) |
| Write tests | Agent mode | Creates test files + may run pytest |
| Create PR | Agent mode | MCP tools require Agent mode |
| Update Jira status | Agent mode | MCP tools require Agent mode |

---

## End-to-End Walkthrough — Putting It Together 🎬

Here's the full flow for DEVOPS-142 in one session:

```
1. [Agent mode, Sonnet] "Using Atlassian MCP, get the details of DEVOPS-142"
   → Copilot fetches the story

2. [Ask mode, Sonnet] "Analyze the requirements: scope, AC, edge cases,
   out of scope, dependencies, open questions"
   → Copilot produces structured analysis

3. [Ask mode, Sonnet] "Generate an implementation plan with files,
   architecture decisions, test strategy, and order"
   → Copilot produces the plan as a markdown checklist

4. [Agent mode, Sonnet] "Create branch feat/DEVOPS-142-stale-pr-check
   and scaffold the files from the plan"
   → Copilot creates branch and empty files

5. → Continue to Post 7 for implementation, testing, PR, and close
```

**Total premium requests consumed:** ~5 (all on Sonnet at 1x = 5 premium requests)

---

## What's Next? 🚀

You have a branch, scaffolded files, and a clear implementation plan. Now it's time to write the actual code, generate tests, create a PR, and close the Jira loop.

👉 **[Post 7 — Coding & Validation](content/efficient-ai/07-coding-and-validation.md)** — From implementation plan to validated, merged PR.

---

*— Ashwin*
