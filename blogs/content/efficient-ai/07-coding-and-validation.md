---
title: "Coding & Validation — From Plan to Merged PR"
date: 2026-04-22
tags: [github-copilot, coding, testing, pytest, github-actions, pull-request, validation, agent-mode, jira]
description: The second half of the developer loop — implement code using Agent and Edit modes, generate pytest tests, validate GitHub Actions locally, create PRs via GitHub MCP, and close the Jira loop with Atlassian MCP.
---

# Coding & Validation — From Plan to Merged PR ✅

This is **Post 7 of 10** in the Efficient AI Handbook.

In [Post 6](content/efficient-ai/06-jira-to-code-workflow.md), we took a Jira story and turned it into a branch with scaffolded files and a clear implementation plan. This post covers the second half: writing the code, generating tests, validating workflows, creating a PR, and closing the Jira story.

---

## Step 5 — Code Generation 💻

### Agent Mode for Multi-File Implementation

When implementing a full feature (multiple files, new modules), Agent mode is the right choice. It can create files, write code, run commands, and iterate on errors.

**Prompt template for Python implementation:**

```
Agent mode (Sonnet):
"Implement the stale PR checker based on the plan. Start with
src/stale_pr_checker.py:
- Function `find_stale_prs(repo: str, days: int) -> list[dict]`
- Use the `requests` library to call the GitHub API
- Filter PRs older than `days` parameter
- Return a list of dicts with keys: number, title, author, created_at, url
- Add type hints and Google-style docstrings
- Handle API errors with proper exception handling and logging"
```

> **One function per prompt.** Don't ask for the entire module in one shot. Build function by function — the output quality is dramatically better, and you can review incrementally.

### Edit Mode for Targeted Changes

When you need to modify existing code — add error handling, refactor a function, change a library — Edit mode is more efficient than Agent mode.

**Example:**

```
Edit mode (Sonnet):
"In src/stale_pr_checker.py, add exponential backoff retry logic
to the find_stale_prs function. Use tenacity with max 3 retries
and 2-second base delay."
```

Edit mode shows a diff you can accept or reject — giving you granular control over changes.

### Inline Completions for Boilerplate

For repetitive patterns (import blocks, class scaffolds, dictionary structures), let inline completions do the work:

1. Type a comment describing what you want
2. Let Copilot suggest the completion
3. Tab to accept

```python
# Create a dataclass for PR details with number, title, author, created_at, url
# → Copilot auto-completes the @dataclass definition
```

### Iterating on Agent Output

Agent mode doesn't always get it right on the first try. Here's how to iterate effectively:

| Situation | What to Do |
|---|---|
| Output is 90% correct | Follow up: "Keep everything but change X to Y" |
| One function is wrong | Follow up referencing just that function |
| Tests fail | Paste the error (truncated) and ask for a fix |
| Wrong library used | "Replace `requests` with `httpx` in the function you just wrote" |
| Missing error handling | "Add try/except for HTTP errors and network timeouts" |

**Do NOT restart the conversation.** Every follow-up builds on the existing context — the model remembers what it wrote and can modify it precisely.

---

## Step 6 — Testing 🧪

### Generate Unit Tests

```
Agent mode (Sonnet):
"Write pytest tests for src/stale_pr_checker.py:
- Test find_stale_prs with a mocked GitHub API response containing
  3 PRs (2 stale, 1 not stale)
- Test the retry logic by mocking a transient 503 error followed
  by success
- Test handling of invalid repository names
- Use pytest fixtures for common test data
- Use responses or unittest.mock for HTTP mocking"
```

### Generate Integration Tests for GitHub Actions

```
Agent mode (Sonnet):
"Write a test for the composite action in
.github/actions/stale-pr-check/action.yml:
- Verify the action.yml is valid YAML with required keys
  (name, description, inputs, outputs, runs)
- Verify all input parameters have descriptions
- Verify the runs.steps reference existing scripts"
```

### Running Tests from Agent Mode

Agent mode can execute terminal commands. Ask it to run your tests:

```
"Run pytest tests/ -v --tb=short and analyze any failures"
```

The agent will execute pytest, read the output, and either confirm all tests pass or diagnose failures — often fixing the code automatically.

> **Model choice for testing:** Stick with **Sonnet (1x)**. Test generation is structured and pattern-based — exactly what Sonnet excels at. Reserve Opus for debugging test failures that Sonnet can't resolve.

---

## Validating GitHub Actions Locally 🔧

Before pushing a workflow, validate it locally using `act`:

```
Agent mode:
"Run `act -j check-stale-prs --dryrun` to validate the workflow
syntax. If it fails, fix the issues."
```

If `act` isn't installed, ask the agent:

```
"Install act using the appropriate method for this OS, then
validate the stale-pr-check workflow."
```

### Common Workflow Validation Checks

| Check | Tool | Prompt |
|---|---|---|
| YAML syntax | `yamllint` or `actionlint` | "Run actionlint on the workflow file" |
| Action references | Manual review | "Verify all action references use SHA pinning" |
| Permission blocks | Manual review | "Ensure all workflows have explicit permissions" |
| Secret references | Manual review | "List all secrets referenced in this workflow" |

---

## Step 7 — Create PR via GitHub MCP 🔀

With code written and tests passing, create a pull request without leaving VS Code.

### The Prompt

```
Agent mode (Sonnet):
"Using GitHub MCP, create a pull request:
- From branch: feat/DEVOPS-142-stale-pr-check
- To branch: main
- Title: 'feat(DEVOPS-142): Add stale PR checker with Slack notifications'
- Body: Generate a description that includes:
  - Summary of changes
  - List of files added/modified
  - Testing performed
  - Link to Jira story DEVOPS-142
- Add labels: enhancement, devops
- Request reviewer: @teammate-username"
```

Copilot calls the GitHub MCP tools to create the PR, add labels, and request reviewers — all in one step.

### PR Description Template

For consistent PR descriptions across your team, include this in your `copilot-instructions.md`:

```markdown
## PR Description Standard
When creating PRs, always include:
1. **Summary** — One paragraph explaining the change
2. **Jira Link** — `Resolves: [DEVOPS-XXX](https://team.atlassian.net/browse/DEVOPS-XXX)`
3. **Changes** — Bulleted list of files added/modified with purpose
4. **Testing** — What tests were added and how to run them
5. **Checklist** — [ ] Tests pass, [ ] Docs updated, [ ] No secrets exposed
```

---

## Step 8 — Close the Jira Loop 🔄

After the PR is created (or merged), update the Jira story to reflect the work.

### Transition the Story

```
Agent mode:
"Using Atlassian MCP, transition DEVOPS-142 to 'In Review' status.
Add a comment: 'Implementation complete. PR #87 created:
https://github.com/team/repo/pull/87. Pending code review.'"
```

### After PR is Merged

```
Agent mode:
"Using Atlassian MCP, transition DEVOPS-142 to 'Done' status.
Add a comment with:
- PR merge link
- Summary of what was implemented
- Any follow-up items or tech debt noted"
```

> **Why automate Jira updates?** Manual Jira updates are the first thing developers skip under time pressure. By automating them through MCP, every story stays in sync with the actual work — without adding cognitive burden.

---

## The Complete Flow — Session Summary 📊

Here's the full loop tracked by cost:

| Step | Mode | Model | Prompts | Cost |
|---|---|---|---|---|
| 1. Pull Jira story | Agent | Sonnet | 1 | 1x |
| 2. Analyze requirements | Ask | Sonnet | 1 | 1x |
| 3. Generate plan | Ask | Sonnet | 1 | 1x |
| 4. Scaffold files | Agent | Sonnet | 1 | 1x |
| 5. Implement (3 functions) | Agent | Sonnet | 3 | 3x |
| 6. Generate + run tests | Agent | Sonnet | 2 | 2x |
| 7. Create PR | Agent | Sonnet | 1 | 1x |
| 8. Update Jira | Agent | Sonnet | 1 | 1x |
| **Total** | | | **11 prompts** | **11 premium requests** |

Eleven premium requests for a complete feature — from Jira story to merged PR with tests and documentation. On Sonnet at 1x, that's a fraction of your daily budget.

> **Compare to the Opus-everywhere approach:** If every prompt above used Opus 4.6 (3x), the same workflow would cost **33 premium requests** — 3× more for no quality improvement on these structured tasks.

---

## What's Next? 🚀

You've mastered the complete developer loop. But the quality of every step depends on the quality of your prompts. The next two posts dive deep into prompt engineering — first the principles, then the copy-paste templates.

👉 **[Post 8 — Prompt Engineering Foundations](content/efficient-ai/08-prompt-engineering-foundations.md)** — The principles behind great prompts. Why they work, not just what to type.

---

*— Ashwin*
