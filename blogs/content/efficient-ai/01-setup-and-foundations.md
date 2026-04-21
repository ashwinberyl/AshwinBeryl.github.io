---
title: "Setup & Foundations — Your Copilot Enterprise Environment"
date: 2026-04-22
tags: [github-copilot, vscode, claude, setup, agent-mode, custom-instructions, devops, python]
description: A from-scratch guide to setting up GitHub Copilot Enterprise with Claude models in VS Code — covering extension installation, admin policies, model picker, chat modes, custom instructions, agent configuration, and workspace indexing. Tailored for Python and GitHub Actions workflows.
---

# Setup & Foundations — Your Copilot Enterprise Environment 🛠️

This is **Post 1 of 10** in the Efficient AI Handbook — a practical guide to mastering GitHub Copilot Enterprise with Claude models for Python and GitHub Actions development.

Before you can leverage any advanced workflow, the foundation must be solid. A misconfigured environment silently degrades every interaction — models you can't access, context the AI never sees, instructions it ignores. This post walks you through every step from a fresh VS Code install to a fully optimized Copilot Enterprise setup.

---

## Prerequisites Checklist ✅

Confirm each of these before proceeding:

| Requirement | Minimum Version | Why |
|---|---|---|
| **VS Code** | 1.101+ | MCP support, Agent mode, latest Copilot features |
| **GitHub Copilot license** | Enterprise or Business | Claude model access requires admin-enabled policies |
| **Node.js** | v18+ | Required for MCP server proxies (covered in Post 4) |
| **Docker Desktop** | Latest stable | Required for Postgres MCP server (covered in Post 5) |
| **Python** | 3.10+ | Your primary development runtime |
| **Git** | 2.40+ | Source control integration |

> **Why Enterprise/Business?** Individual Copilot plans have limited model selection. Claude Opus and Sonnet models are only available when your organization's admin explicitly enables the Claude policy. If you're on a Free or Pro plan, you won't see these models in the picker.

---

## Step 1 — Install the Extensions 📦

Open VS Code and install two extensions from the Marketplace:

1. **GitHub Copilot** (`GitHub.copilot`) — powers inline code completions
2. **GitHub Copilot Chat** (`GitHub.copilot-chat`) — powers the chat panel, Agent mode, and Edit mode

```
# Via the command line:
code --install-extension GitHub.copilot
code --install-extension GitHub.copilot-chat
```

After installation, sign in with your GitHub account when prompted. VS Code will validate your Copilot license automatically.

> **Verify your license:** Open the Command Palette (`Ctrl+Shift+P`) → type `GitHub Copilot: Status`. You should see your plan type (Enterprise/Business) and the models available to you.

---

## Step 2 — Verify Admin Policies for Claude Models 🔐

Claude models are **not enabled by default.** Your organization's GitHub admin must explicitly enable them.

**For admins — where to enable:**

1. Navigate to `github.com` → Organization Settings → Copilot → Policies
2. Under **Model Selection**, enable the Claude model family
3. Save changes — models propagate to users within minutes

**For developers — how to verify:**

1. Open the Copilot Chat panel in VS Code
2. Click the **model picker** dropdown (bottom of the chat input area)
3. You should see entries like:
   - `Claude Sonnet 4.6`
   - `Claude Opus 4.5`
   - `Claude Opus 4.6`
   - `Auto` (routes to the best model automatically)

If Claude models don't appear: update both extensions, restart VS Code, and contact your org admin to confirm the policy is enabled for your user group.

---

## Step 3 — Understanding the Model Picker 🎛️

The model picker sits at the bottom of the Copilot Chat input box. It determines which LLM processes your request.

| Model | Best For | Premium Multiplier |
|---|---|---|
| **GPT-4.1** | Quick completions, simple questions | 0x (included free) |
| **Claude Sonnet 4.6** | Day-to-day coding, refactoring, explanations | 1x |
| **Claude Opus 4.5 / 4.6** | Complex reasoning, multi-file refactors, debugging | 3x |
| **Claude Opus 4.7** | Hardest problems, deep architectural analysis | 7.5x |
| **Auto** | Let GitHub route to the optimal model (10% discount) | Varies |

> **Default recommendation:** Set your default to **Claude Sonnet 4.6** for daily work. Escalate to Opus only when Sonnet's output quality is insufficient. This is covered in depth in [Post 2 — Model Selection & Cost Control](content/efficient-ai/02-model-selection-and-cost.md).

---

## Step 4 — Chat Modes: Ask, Edit, Agent 💬

VS Code Copilot Chat offers three distinct interaction modes. Choosing the right one matters:

### Ask Mode
**What it does:** Answers questions, explains code, generates snippets in the chat panel. Does NOT modify your files.

**Use when:** You need an explanation, want to explore options, or need a code snippet to copy manually.

```
Example: "Explain how this GitHub Actions matrix strategy works"
Example: "What's the difference between subprocess.run and subprocess.Popen?"
```

### Edit Mode
**What it does:** Proposes targeted changes to specific files. Shows a diff you can accept or reject.

**Use when:** You need a focused change to one or a few files — rename a variable, refactor a function, add error handling.

```
Example: "Add retry logic with exponential backoff to this API call"
Example: "Convert this function to use async/await"
```

### Agent Mode
**What it does:** Autonomously plans and executes multi-step tasks. Can read files, run terminal commands, create/modify multiple files, and iterate based on errors.

**Use when:** You need a complex, multi-file task executed end-to-end — scaffolding a new module, implementing a feature, debugging across files.

```
Example: "Create a Python CLI tool that reads a YAML config and generates GitHub Actions workflow files"
Example: "Debug why the test_deploy workflow fails on the matrix step"
```

> **Agent Mode is your power tool for DevOps.** When building GitHub Actions workflows, Agent mode can scaffold YAML files, write Python entry points, run `act` for local testing, and iterate on failures — all in one session. But it consumes more tokens per interaction, so reserve it for tasks that genuinely need multi-step autonomy.

---

## Step 5 — Custom Instructions 📋

Custom instructions tell Copilot *how* to behave in your repository — coding standards, preferred libraries, patterns to follow or avoid. Without them, every prompt starts from zero context.

### Repository-Wide Instructions (`.github/copilot-instructions.md`)

Create this file at the root of your repo. It applies to **every** Copilot Chat request in this repository.

```markdown
# Copilot Instructions — Python DevOps Repository

## Language & Runtime
- Python 3.11+ with type hints on all public functions
- Use `pathlib.Path` instead of `os.path` for all file operations
- Prefer `subprocess.run()` over `os.system()` — always capture stderr

## Code Style
- Follow PEP 8 strictly
- Use Google-style docstrings for all public functions and classes
- Maximum line length: 120 characters
- Use f-strings over .format() or % formatting

## Testing
- Use pytest with fixtures and parametrize for all tests
- Test files go in `tests/` mirroring the `src/` structure
- Minimum coverage target: 80%

## GitHub Actions
- All workflows use `ubuntu-latest` runner
- Pin all actions to full SHA, never use `@latest` or `@v1`
- Always define explicit `permissions` blocks — default to `contents: read`
- Use composite actions for reusable logic, not reusable workflows

## Error Handling
- Never catch bare `except:` — always specify the exception type
- Log errors with `logging` module, never `print()`
- All CLI tools must exit with appropriate exit codes (0 = success, 1 = error)

## Security
- Never log secrets, tokens, or credentials
- Use environment variables for all sensitive configuration
- All API calls must use timeouts
```

> **Why this matters:** Without these instructions, Copilot might generate `os.path.join()` when you want `pathlib`, or `print()` when you want `logging`. The instructions file eliminates repetitive correction prompts — saving tokens and time.

### Path-Specific Instructions

For different rules in different parts of your codebase, create files in `.github/instructions/`:

```
.github/instructions/
├── workflows.instructions.md    ← Rules for .github/workflows/
└── scripts.instructions.md     ← Rules for scripts/ and src/
```

Each file should specify an `applyTo` path glob in its frontmatter. This lets you enforce different standards for GitHub Actions YAML versus Python source code.

---

## Step 6 — Agent Configuration (`AGENTS.md`) 🤖

The `AGENTS.md` file tells the coding agent (Agent mode) how to operate in your repository — what commands it can run, how to validate its work, and what "done" looks like.

Create `AGENTS.md` in your repository root:

```markdown
# Agent Instructions

## Environment
- Python 3.11+ is available
- Use `pip install -r requirements.txt` to install dependencies
- Use `pip install -r requirements-dev.txt` for dev dependencies

## Validation
- After making code changes, always run:
  - `ruff check .` for linting
  - `black --check .` for formatting
  - `pytest tests/ -v --tb=short` for tests
- Fix any failures before considering the task complete

## GitHub Actions
- Validate workflow syntax with `actionlint` if available
- For local workflow testing, use `act` with the `-j <job_name>` flag

## Definition of Done
- All linting passes
- All existing tests pass
- New code has corresponding tests
- Docstrings are present on all new public functions
- Changes are committed with a descriptive message
```

> **Why `AGENTS.md` separately from `copilot-instructions.md`?** The instructions file shapes *what* Copilot generates (style, patterns). The `AGENTS.md` file shapes *how the agent operates* (which commands to run, validation gates). They serve different purposes and are consumed at different stages.

---

## Step 7 — Workspace Indexing 🔍

Copilot builds a **semantic index** of your workspace to power `@workspace` and `#codebase` queries. Understanding how this works prevents frustration.

**How it works:**
- VS Code indexes your project files for semantic search
- The index powers context-aware responses when you reference `@workspace`
- Files in `.gitignore` and `files.exclude` are excluded from the index

**Monitor indexing status:**
- Click the Copilot icon in the VS Code Status Bar
- Look for indexing status: "Building," "Indexed," or "Not indexed"

**Best practices:**
- Keep `.gitignore` accurate — exclude `node_modules/`, `__pycache__/`, `.venv/`, build artifacts
- Use VS Code's `files.exclude` setting for large generated files that aren't in `.gitignore`
- If your project has very large files (>1MB), they may not be indexed — this is expected

---

## Step 8 — Pre-Configure the Agent Environment (`copilot-setup-steps.yml`) ⚙️

When using the Copilot coding agent (the cloud-based agent that can be assigned to GitHub Issues), it runs in a sandboxed environment. The `copilot-setup-steps.yml` file ensures that environment has your dependencies pre-installed.

Create `.github/copilot-setup-steps.yml`:

```yaml
steps:
  - name: Set up Python
    uses: actions/setup-python@v5
    with:
      python-version: "3.11"

  - name: Install dependencies
    run: |
      pip install -r requirements.txt
      pip install -r requirements-dev.txt

  - name: Install linting tools
    run: |
      pip install ruff black pytest
```

> **Why pre-configure?** Without this file, the agent wastes tokens (and your premium requests) installing dependencies on every run. Moving deterministic setup out of the LLM turn is one of the most effective token optimization strategies — covered in depth in [Post 3](content/efficient-ai/03-context-and-token-optimization.md).

---

## Quick Reference — File Checklist 📝

After completing this setup, your repository should contain:

| File | Purpose |
|---|---|
| `.github/copilot-instructions.md` | Repository-wide coding standards for Copilot |
| `.github/instructions/*.instructions.md` | Path-specific instructions (optional) |
| `AGENTS.md` | Agent behavior: commands, validation, definition of done |
| `.github/copilot-setup-steps.yml` | Pre-install dependencies for the coding agent |
| `.gitignore` | Controls what files are indexed by Copilot |

---

## What's Next? 🚀

Your environment is configured. Copilot can see your code, understands your standards, and has access to Claude models. But not all models are equal — and using Opus when Sonnet suffices will drain your premium request budget fast.

👉 **[Post 2 — Model Selection & Cost Control](content/efficient-ai/02-model-selection-and-cost.md)** — Learn the premium request multiplier system and build a model selection strategy that maximizes output quality while minimizing cost.

---

*— Ashwin*
