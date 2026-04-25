---
title: "Prompt Engineering Foundations — Why Good Prompts Work"
date: 2026-04-22
tags: [github-copilot, prompt-engineering, pctf, persona, context, task-decomposition, anti-patterns, prompt-files, skills, reusable-prompts, custom-agents]
description: The principles behind effective Copilot prompts — the PCTF framework (Persona, Context, Task, Format), task decomposition, iterative refinement, anti-patterns that waste tokens, and how to make prompts reusable with .prompt.md files, SKILL.md agent skills, custom instructions hierarchy (org/repo/path/user), and .agent.md custom agents.
---

# Prompt Engineering Foundations — Why Good Prompts Work 🧠

This is **Post 8 of 10** in the Efficient AI Handbook.

Everything in this handbook — model selection, context control, MCP workflows — converges on one thing: the prompt. A well-structured prompt on Sonnet outperforms a vague prompt on Opus every time. This post teaches the principles. [Post 9](content/efficient-ai/09-prompt-templates-python-and-actions.md) provides the copy-paste templates.

---

## The PCTF Framework 📐

Structure every non-trivial prompt with four components: **Persona, Context, Task, Format.**

### P — Persona

Tell the model *who it is*. This shapes its vocabulary, depth, and decision-making patterns.

```
"Act as a Staff SRE at a company that runs Python microservices on Kubernetes."
"Act as a Python security reviewer specializing in OWASP Top 10."
"Act as a senior DevOps engineer who writes GitHub Actions workflows."
```

**Why it works:** LLMs are trained on text written by people in specific roles. Activating a persona biases the model toward the patterns, depth, and vocabulary associated with that role. A "senior DevOps engineer" persona produces different (and more production-appropriate) output than a "beginner Python developer" persona.

> **Default persona for this handbook:** "Act as a Staff AI Engineer working with Python and GitHub Actions for DevOps automation." Use this as your starting point and adjust based on the specific task.

### C — Context

Provide the information the model needs to reason correctly. Don't assume it knows your codebase, your conventions, or your constraints.

**Types of context to provide:**

| Context Type | Example |
|---|---|
| **Technical stack** | "We use Python 3.11, pytest, and httpx" |
| **Architecture** | "This is a monorepo with src/ for code and .github/actions/ for custom actions" |
| **Constraints** | "The function must be async and handle timeouts" |
| **File references** | `#file:src/deploy.py` — let the model read the actual code |
| **Error context** | "This test fails with AssertionError on line 42" |
| **Organizational** | "Our team standard requires Google-style docstrings" |

**Why it works:** Context reduces ambiguity. Without context, the model guesses — and guesses burn tokens in correction cycles. With context, the model produces targeted output on the first attempt.

### T — Task

Describe exactly what you want done. Be specific, be decomposed, be goal-oriented.

**❌ Vague tasks:**
```
"Write some code for deploying"
"Help me with this workflow"
"Fix this"
```

**✅ Specific tasks:**
```
"Write a function `deploy_to_staging(image_tag: str) -> bool` that calls
the Kubernetes API to update the deployment image, waits for rollout
completion, and returns True if successful."

"Add a `paths` filter to this workflow so it only triggers on changes
to files in the `src/` and `tests/` directories."

"The test on line 42 fails because the mock doesn't match the actual
API response format. Fix the mock to include the 'metadata' key."
```

**Why it works:** Specificity constrains the output space. "Write some code for deploying" has millions of valid interpretations. "Write `deploy_to_staging(image_tag: str) -> bool`" has one — and the model can nail it.

### F — Format

Tell the model exactly how to present the output.

```
"Return only the function body — no imports, no usage examples."
"Format the output as a markdown table with columns: File, Change, Reason."
"Provide the fix as a unified diff."
"Return a YAML workflow file, no explanations."
"List the issues as a numbered checklist."
```

**Why it works:** Without format instructions, the model defaults to conversational prose with code blocks — often including unnecessary explanations, imports, and usage examples that you'll delete anyway. Specifying format eliminates noise.

---

## PCTF in Practice — A Complete Example 🎯

**Without PCTF:**
```
"Write a retry decorator"
```

**With PCTF:**
```
[P] Act as a senior Python engineer specializing in resilient systems.
[C] We use Python 3.11 with type hints. Our codebase uses the
    `logging` module with `structlog` formatting. All HTTP calls go
    through `httpx.AsyncClient`.
[T] Write a retry decorator that:
    - Accepts max_retries (default 3) and base_delay (default 1.0)
    - Uses exponential backoff with jitter
    - Catches httpx.HTTPStatusError for 5xx codes and httpx.ConnectTimeout
    - Logs each retry attempt with structured fields: attempt, max_retries,
      delay, exception_type
    - Re-raises the exception after all retries are exhausted
[F] Return only the decorator function with full type hints and a
    Google-style docstring. No usage example.
```

The PCTF version produces a production-ready decorator on the first attempt. The vague version produces a generic `time.sleep` retry loop that you'll spend three follow-ups fixing.

---

## Task Decomposition — Single-Responsibility Prompts 🔨

Complex tasks produce poor results in a single prompt. Decompose into steps.

**❌ Overloaded prompt:**
```
"Create a complete CI/CD pipeline with testing, linting, building,
deploying to staging, running integration tests, deploying to
production with approval, sending Slack notifications, and
rolling back on failure."
```

This will produce a bloated, 300-line YAML file with errors in at least 3 sections.

**✅ Decomposed prompts:**
```
Prompt 1: "Create a CI workflow that runs pytest and ruff on push to main."
Prompt 2: "Add a build job that creates a Docker image and pushes to ECR."
Prompt 3: "Add a staging deployment job that depends on the build job."
Prompt 4: "Add Slack notification on job failure using rtCamp/action-slack-notify."
```

Each prompt produces a focused, correct output. You review and iterate on each step before moving to the next.

> **Rule of thumb:** If your prompt has more than 3 bullet points of requirements or the word "and" appears more than twice, decompose it.

---

## Iterative Refinement — The Edit-Follow-Up Pattern 🔄

The most efficient prompting pattern is: **generate → refine → refine** — not **generate → restart → restart.**

### Technique 1: Edit Your Last Message

If the model's response is off-base, edit your original prompt to be more specific — don't type a new message. This re-processes with better instructions without losing context.

### Technique 2: Additive Follow-Ups

When the output is mostly right, add constraints:

```
Prompt 1: "Write a function to parse YAML config files"
→ Good, but uses PyYAML

Follow-up: "Use ruamel.yaml instead — we need to preserve comments"
→ Targeted fix, preserves everything else

Follow-up: "Add type hints and a docstring"
→ Layered improvement
```

### Technique 3: Anchored Modification

When you want to change specific parts without affecting the rest:

```
"Keep the function signature and docstring as-is.
Change only the retry logic: use tenacity instead of manual loop.
Don't change anything else."
```

The phrase "don't change anything else" is surprisingly effective at preventing the model from "helpfully" refactoring unrelated code.

---

## Anti-Patterns — What Wastes Your Tokens 🚫

### 1. The Vague Prompt

```
❌ "Help me with this code"
❌ "Write something for deployment"
❌ "Fix my workflow"
```

These produce generic output that requires multiple correction rounds.

### 2. The Kitchen-Sink Prompt

```
❌ "Write a complete application with authentication, database,
API endpoints, tests, documentation, CI/CD, monitoring, and alerting"
```

Too many requirements = hallucinated architecture + errors in every section.

### 3. The Identical Re-Ask

```
❌ Prompt 1: "Write a deploy script"
❌ Prompt 2: "Write a deploy script"  ← identical!
```

Sends the same tokens again. Edit the original or follow up instead.

### 4. The Untruncated Log Dump

```
❌ *pastes 500 lines of npm install output + traceback*
   "What's wrong?"
```

Find the 5 relevant lines and paste only those.

### 5. The Wrong Mode

```
❌ Using Agent mode to ask "What does this function do?"
   (Agent mode has higher overhead — Ask mode is cheaper and faster)

❌ Using Ask mode when you need file modifications
   (Ask mode can't edit files — you'll copy-paste and lose formatting)
```

---

## Context Loading Strategy — Match to Task 📊

| Task Complexity | Context Strategy | Operators |
|---|---|---|
| **Simple** (one function) | Active file + selection | `#selection` or `#file` |
| **Medium** (one module) | Active file + related files | `#file` × 2-3 |
| **Complex** (cross-module) | Folder-level context | `#folder` |
| **Exploratory** (find things) | Workspace search | `@workspace` |
| **Exhaustive** (audit) | Full codebase scan | `#codebase` |

> **Cost scales with context.** Loading `#codebase` for a simple function refactor wastes tokens. Loading only `#selection` for a cross-module change gives the model insufficient information. Match the context breadth to the task scope.

---

## Reusable Prompt Components — Stop Retyping the Same PCTF Prompts ♻️

Typing a full PCTF prompt every time is time-consuming. The good news: GitHub Copilot provides mechanisms to save and reuse prompt components at **five different levels** — from one-shot templates to organization-wide rules.

### Level 1: Prompt Files (`.prompt.md`) — Reusable Slash Commands

Prompt files are the single most useful feature for avoiding repetition. A `.prompt.md` file packages a complex prompt into a **slash command** you invoke with one keystroke.

**How to create one:**

1. Create a file with the `.prompt.md` extension in `.github/prompts/` (shared with your team) or your user-level prompts directory (personal)
2. Add YAML frontmatter with a description
3. Write your prompt instructions in Markdown

**Example — `.github/prompts/generate-tests.prompt.md`:**

```markdown
---
description: "Generate pytest tests for a Python module"
---
Act as a test engineer specializing in Python.
Context: We use Python 3.11, pytest, and unittest.mock. Follow
Google-style docstrings. Tests go in tests/ mirroring src/.

Generate comprehensive tests for ${input:file}:
- Happy path with typical input
- Edge cases: empty input, None, boundary values
- Error handling: verify correct exceptions are raised
- Use @pytest.fixture for common setup
- Use @pytest.mark.parametrize for input variations

Return a complete test file with imports, fixtures, and test functions.
```

**How to use it:** In Copilot Chat, type `/generate-tests` → it invokes the full prompt with the `${input:file}` placeholder prompting you for the target file.

> **`${input:name}` variables** let you create dynamic prompts. The user fills in values at invocation time — so one prompt file works for any module.

**Workspace vs User scope:**

| Scope | Location | Shared With | Best For |
|---|---|---|---|
| **Workspace** | `.github/prompts/` in your repo | Entire team (committed to Git) | Team-standard workflows: test generation, code review, PR creation |
| **User** | VS Code user prompts directory | Only you (synced via Settings Sync) | Personal workflows: your debugging pattern, your refactoring style |

**Quick ways to create prompt files:**

- **From the Command Palette:** `Ctrl+Shift+P` → "Chat: New Prompt File"
- **From a chat session:** After a productive conversation, ask: "Save this workflow as a .prompt.md file" — Copilot generalizes the conversation into a reusable prompt
- **From the Chat gear icon:** Click ⚙️ → Prompts tab → manage all your prompt files

### Level 2: Agent Skills (`SKILL.md`) — Bundled Multi-Step Procedures

While prompt files are one-shot templates, **Agent Skills** are multi-step procedural workflows bundled with supporting resources. A Skill is a folder containing a `SKILL.md` instruction file plus optional scripts, templates, and reference docs.

**The key difference from prompt files:**

| Feature | Prompt Files (`.prompt.md`) | Agent Skills (`SKILL.md`) |
|---|---|---|
| **Structure** | Single markdown file | Folder with `SKILL.md` + bundled assets |
| **Trigger** | Manual (`/command`) only | Auto-detected from prompt **or** manual (`/command`) |
| **Complexity** | Single-step tasks | Multi-step workflows with branching logic |
| **Assets** | None — instructions only | Can include scripts, templates, reference docs |
| **Best for** | "Generate tests for this file" | "Scaffold a new service with tests, config, CI, and docs" |

**How to create a Skill:**

Create a folder under `.github/skills/` with a `SKILL.md` file:

**Example — `.github/skills/debug-workflow/SKILL.md`:**

```markdown
---
name: debug-workflow
description: "Debug a failing GitHub Actions workflow by analyzing logs, identifying root cause, and proposing a fix"
---
# Debug a Failing GitHub Actions Workflow

## Steps
1. Read the workflow YAML file to understand the pipeline structure
2. Analyze the provided error log (ask user if not provided)
3. Identify the failing step and narrow down to the root cause
4. Check for common issues:
   - Incorrect action version or SHA pinning
   - Missing permissions block
   - Incorrect secret references
   - Runner compatibility issues
   - Path or shell escaping problems
5. Propose a targeted fix with a diff
6. Suggest a test command to validate locally (e.g., `act -j <job_name>`)

## Rules
- Prefer minimal changes over rewrites
- Always verify action references use SHA pinning
- Follow the standards in `.github/copilot-instructions.md`

## References
- See `./references/common-workflow-errors.md` for known failure patterns
```

**Example — `.github/skills/generate-migration/SKILL.md`:**

```markdown
---
name: generate-migration
description: "Generate an Alembic database migration from current schema changes"
---
# Generate an Alembic Migration

## Steps
1. Read the current SQLAlchemy models from `src/models/`
2. Query the current database schema via Postgres MCP (if available)
3. Identify the diff between models and current schema
4. Generate an Alembic migration file using `alembic revision --autogenerate`
5. Review the generated migration for:
   - Correct upgrade() and downgrade() functions
   - No destructive operations without explicit confirmation
   - Proper index and constraint naming
6. Run `alembic check` to validate the migration chain

## Rules
- Never auto-approve DROP TABLE or DROP COLUMN — flag for human review
- Use the helper script in `./scripts/diff_schema.py` for schema comparison
```

**How Skills are triggered:**

- **Automatic discovery:** Type a request like *"scaffold a new service"* — Copilot matches it against skill descriptions and loads the matching skill's instructions into context, without you referencing it
- **Explicit invocation:** Type `/debug-workflow` or `/generate-migration` in Copilot Chat
- **Quick creation via `/create-skill`:** In Copilot Chat, type `/create-skill` and describe what you want — Copilot generates the folder structure and `SKILL.md` for you
- **Extract from conversation:** After a productive multi-step session, ask: *"Create a skill from how we just did this"* — Copilot generalizes the procedure into a reusable skill

> **Workspace vs User scope:** Just like prompt files, skills in `.github/skills/` are committed to Git (team-shared), while skills in `~/.copilot/skills/` are personal.

**When to upgrade a Prompt File to a Skill:**

- Your workflow involves **3+ sequential steps** that must execute in order
- You need **bundled assets** (scripts, templates, checklists) alongside the instructions
- You want **automatic discovery** — the skill triggers when Copilot recognizes a matching request
- Multiple team members need **consistent execution** of the same complex procedure

### Level 3: Custom Instructions — Always-On Context

Unlike prompt files (which you invoke manually), custom instructions are **injected automatically** into every request. Use them for context that applies to ALL prompts — your tech stack, coding standards, and conventions.

This is the hierarchy from most specific to broadest:

| Level | File | Scope | What to Put Here |
|---|---|---|---|
| **Path-specific** | `.github/instructions/workflows.instructions.md` | Files matching `applyTo` glob | "Pin all actions to SHA", "Use composite actions" |
| **Repository** | `.github/copilot-instructions.md` | All requests in this repo | Tech stack, coding standards, naming conventions |
| **Organization** | GitHub.com → Org Settings → Copilot | All repos in the org | Company-wide: "Use Google-style docstrings", "Never log PII" |
| **User** | VS Code Settings → Copilot instructions | All your projects | Personal preferences: "I prefer pathlib over os.path" |

> **The key insight:** Move your **Persona** and **Context** from individual prompts into custom instructions. If you're always "a Staff AI Engineer working with Python 3.11 and GitHub Actions," put that in `copilot-instructions.md` once — then your slash commands only need to specify the **Task** and **Format**.

**Before (retyping context every time):**
```
"Act as a Staff DevOps engineer. We use Python 3.11, pytest, httpx, structlog.
Our repo has src/ for code and .github/actions/ for custom actions.
Write a function that..."
```

**After (context is in copilot-instructions.md, prompt only needs the task):**
```
"Write a function that..."
```

The persona and tech stack context are automatically injected from your instructions file. You type less, get the same quality.

### Level 4: Custom Agents (`.agent.md`) — Specialized Roles

For recurring complex tasks, define **custom agents** — predefined personas with specific tools and model preferences.

**Example — `.github/agents/security-reviewer.agent.md`:**

```markdown
---
name: "security-reviewer"
description: "Review code for security vulnerabilities (OWASP Top 10)"
model: "claude-sonnet-4.6"
tools: ["filesystem", "terminal"]
---
You are a Python security reviewer specializing in OWASP Top 10.
Review code for: injection, broken auth, sensitive data exposure,
XXE, broken access control, security misconfiguration, XSS, insecure
deserialization, insufficient logging.

Always output findings as a numbered list with severity
(Critical/High/Medium/Low), the specific line, and the recommended fix.
```

**Invoke with:** `@security-reviewer review #file:src/auth.py`

This is more powerful than a prompt file — it lets you pin a specific model, restrict available tools, and define a full persona + format in one reusable package.

### Recommended Setup for a DevOps Team

```
.github/
├── copilot-instructions.md              ← Repo-wide: stack, style, standards
├── instructions/
│   ├── python.instructions.md           ← applyTo: **/*.py
│   └── workflows.instructions.md        ← applyTo: .github/workflows/**
├── prompts/
│   ├── generate-tests.prompt.md         ← /generate-tests
│   ├── review-security.prompt.md        ← /review-security
│   ├── create-action.prompt.md          ← /create-action
│   ├── debug-workflow.prompt.md         ← /debug-workflow
│   └── write-docstrings.prompt.md       ← /write-docstrings
├── skills/
│   ├── scaffold-module/
│   │   ├── SKILL.md                     ← Auto-detected: "scaffold a new module"
│   │   └── templates/
│   │       └── module_template.py
│   ├── debug-workflow/
│   │   ├── SKILL.md                     ← Auto-detected: "debug a failing workflow"
│   │   └── references/
│   │       └── common-workflow-errors.md
│   └── generate-migration/
│       ├── SKILL.md                     ← Auto-detected: "generate a migration"
│       └── scripts/
│           └── diff_schema.py
├── agents/
│   └── security-reviewer.agent.md       ← @security-reviewer
└── ...
```

With this setup: your persona and context live in instructions files (never retyped), your single-step task patterns live in prompt files (invoked with `/`), your multi-step procedures live in skills (auto-detected or invoked with `/`), and your specialized roles live in agent files (invoked with `@`). The templates in [Post 9](content/efficient-ai/09-prompt-templates-python-and-actions.md) can all be saved as `.prompt.md` files for one-keystroke access — or upgraded to `SKILL.md` folders when they grow complex enough to benefit from bundled assets.

---

## Quick Reference — Prompt Checklist ✅

Before sending a non-trivial prompt:

- [ ] Did I set a **Persona**? (Or is it handled by `copilot-instructions.md`?)
- [ ] Did I provide relevant **Context** (stack, constraints, files)?
- [ ] Is the **Task** specific and single-responsibility?
- [ ] Did I specify the **Format** I want?
- [ ] Am I using the right **Mode** (Ask/Edit/Agent)?
- [ ] Am I using the right **Model** (Sonnet for most tasks)?
- [ ] Is this a follow-up to an existing thread, or should I `/clear` first?
- [ ] Should this prompt be saved as a `.prompt.md` for reuse?

---

## What's Next? 🚀

You know the principles. Now let's put them into ready-to-use templates for your daily Python and GitHub Actions work.

👉 **[Post 9 — Prompt Templates: Python & GitHub Actions](content/efficient-ai/09-prompt-templates-python-and-actions.md)** — 20+ copy-paste prompt templates for every common DevOps task.

---

*— Ashwin*
