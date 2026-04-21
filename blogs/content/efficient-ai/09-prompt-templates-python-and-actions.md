---
title: "Prompt Templates — Python & GitHub Actions Ready-to-Use"
date: 2026-04-22
tags: [github-copilot, prompt-templates, python, github-actions, pytest, devops, automation, cli]
description: 20+ copy-paste prompt templates for daily DevOps work — writing Python CLIs, refactoring, debugging, testing, creating GitHub Actions workflows, composite actions, matrix strategies, caching, and OIDC authentication.
---

# Prompt Templates — Python & GitHub Actions Ready-to-Use 📝

This is **Post 9 of 10** in the Efficient AI Handbook.

This post is a **reference document** — organized by category, ready to copy-paste. Each template follows the PCTF framework from [Post 8](content/efficient-ai/08-prompt-engineering-foundations.md). All templates assume **Sonnet (1x)** unless noted otherwise.

> **Don't just copy-paste — save as `.prompt.md` files.** Every template below can be saved to `.github/prompts/` as a reusable slash command (e.g., `/generate-tests`, `/debug-workflow`). This way you type `/` instead of the full prompt every time. See the [Reusable Prompt Components](content/efficient-ai/08-prompt-engineering-foundations.md) section in Post 8 for setup details.

---

## Python Templates 🐍

### 1. Write a CLI Tool

```
Act as a senior Python developer.
Context: Python 3.11, we use `click` for CLIs, `structlog` for logging.
Task: Write a CLI tool that [DESCRIBE FUNCTION].
- Accept arguments: [LIST ARGS]
- Add --verbose flag for debug logging
- Exit with code 0 on success, 1 on error
- Handle exceptions gracefully with user-friendly error messages
Format: Complete script with Click decorators, type hints, and
Google-style docstring. Include the `if __name__` block.
```

### 2. Refactor for Readability

```
Act as a Python code reviewer focused on clean code principles.
Context: #file:[path] — this function works but is hard to read.
Task: Refactor for readability:
- Extract complex conditions into named booleans
- Replace nested if/else with early returns
- Add descriptive variable names
- Keep the same behavior and function signature
Format: Show the refactored function only. No explanation needed.
```

### 3. Debug a Traceback

```
Act as a senior Python debugger.
Context: Python 3.11, using [LIBRARY]. The error occurs in #file:[path].
Task: Debug this error:
[PASTE 5-10 RELEVANT LINES OF TRACEBACK]
- Identify the root cause
- Explain why it happens
- Provide the fix
Format: Brief explanation (3 sentences max) + fixed code block.
```

### 4. Add Type Hints

```
Act as a Python type safety specialist.
Context: #file:[path] — Python 3.11, we use strict typing.
Task: Add type hints to all functions and variables in this file:
- Use built-in generics (list[str], dict[str, Any])
- Use Optional for nullable parameters
- Use Union only when necessary
- Add return type hints
Format: The complete file with type hints added. No other changes.
```

### 5. Write Google-Style Docstrings

```
Act as a technical writer for Python documentation.
Context: #file:[path] — we use Google-style docstrings.
Task: Add docstrings to all public functions and classes:
- One-line summary
- Args section with types and descriptions
- Returns section with type and description
- Raises section if exceptions are possible
Format: Only the docstrings — show each function signature + docstring.
```

### 6. Generate Pytest Tests

```
Act as a test engineer specializing in Python.
Context: #file:[path] — Python 3.11, pytest, unittest.mock.
Task: Write comprehensive tests:
- Test the happy path with typical input
- Test edge cases: empty input, None, very large input
- Test error handling: verify correct exceptions are raised
- Use @pytest.fixture for common setup
- Use @pytest.mark.parametrize for input variations
Format: Complete test file with imports, fixtures, and test functions.
```

### 7. Review for Security

```
Act as a Python security reviewer (OWASP specialization).
Context: #file:[path] — this code handles [user input / API calls / file operations].
Task: Review for security vulnerabilities:
- Injection risks (SQL, command, path traversal)
- Hardcoded secrets or credentials
- Missing input validation
- Unsafe deserialization
- Missing timeouts on network calls
Format: Numbered list of findings with severity (Critical/High/Medium/Low),
the specific line, and the recommended fix.
```

### 8. Optimize Performance

```
Act as a Python performance engineer.
Context: #file:[path] — this function is called [N] times per [unit] and
is a bottleneck.
Task: Optimize for performance:
- Identify the bottleneck
- Propose optimization (algorithmic, caching, batching, async)
- Implement the optimized version
Format: Brief analysis (what's slow and why) + optimized code.
Use Opus if the function is complex (3x).
```

### 9. Convert Sync to Async

```
Act as a Python async specialist.
Context: #file:[path] — Python 3.11, we use httpx.AsyncClient.
Task: Convert this synchronous function to async:
- Replace requests/urllib calls with httpx async equivalents
- Add proper async context managers
- Handle concurrent operations with asyncio.gather where appropriate
- Preserve all error handling
Format: The converted async function with type hints.
```

### 10. Write a Python-Based GitHub Action Entry Point

```
Act as a DevOps engineer writing custom GitHub Actions in Python.
Context: This is the entry point for a composite action. It reads
inputs from environment variables (INPUT_*) and writes outputs
to $GITHUB_OUTPUT.
Task: Write a Python script that:
- Reads inputs: [LIST INPUTS]
- Performs: [DESCRIBE LOGIC]
- Writes outputs to $GITHUB_OUTPUT in key=value format
- Exits with code 1 on any error
- Uses only standard library (no pip dependencies)
Format: Complete script with shebang, error handling, and comments.
```

---

## GitHub Actions Templates ⚡

### 11. Create a Reusable Workflow

```
Act as a GitHub Actions expert.
Context: Ubuntu runner, Python 3.11, our repo uses ruff + black + pytest.
Task: Create a reusable workflow (.github/workflows/ci-reusable.yml):
- Trigger: workflow_call with inputs for python-version and test-path
- Jobs: lint (ruff + black), test (pytest with coverage)
- Pin all actions to full SHA
- Add explicit permissions block (contents: read)
- Use pip caching
Format: Complete YAML workflow file.
```

### 12. Write a Composite Action

```
Act as a GitHub Actions expert writing composite actions.
Context: Our composite actions are in .github/actions/[name]/
Task: Create a composite action that [DESCRIBE PURPOSE]:
- Inputs: [LIST WITH DESCRIPTIONS AND DEFAULTS]
- Outputs: [LIST WITH DESCRIPTIONS]
- Steps: Use Python script for the core logic
- Include branding (icon and color)
Format: Two files: action.yml and the Python entry script.
```

### 13. Add Matrix Testing

```
Act as a CI/CD engineer.
Context: #file:[workflow path] — this workflow tests on Python 3.11 only.
Task: Add matrix strategy:
- Python versions: 3.10, 3.11, 3.12
- OS: ubuntu-latest, macos-latest
- Exclude: macos + Python 3.10 (not needed)
- Fail-fast: false (run all combinations)
Format: Show only the modified job section with matrix strategy.
```

### 14. Set Up Dependency Caching

```
Act as a CI/CD performance engineer.
Context: #file:[workflow path] — pip install takes 2 minutes per run.
Task: Add pip caching:
- Use actions/setup-python with built-in pip caching
- Cache key based on requirements.txt hash
- Include restore-keys for partial cache hits
Format: Show only the modified setup steps.
```

### 15. Implement OIDC Authentication

```
Act as a cloud security engineer.
Context: We deploy to AWS from GitHub Actions. Currently using
long-lived IAM access keys stored as secrets.
Task: Replace access key auth with OIDC:
- Add permissions: id-token: write
- Use aws-actions/configure-aws-credentials with OIDC
- Role ARN stored as a repository variable (not secret)
- Region: us-east-1
Format: The complete modified workflow with OIDC auth.
Explain in a comment why OIDC is more secure than access keys.
```

### 16. Add PR Labeling Automation

```
Act as a DevOps automation engineer.
Context: We want PRs auto-labeled by file path.
Task: Create a workflow that labels PRs on open/synchronize:
- src/**/*.py → label: "python"
- .github/workflows/** → label: "ci-cd"
- docs/** → label: "documentation"
- tests/** → label: "testing"
- Use actions/labeler
Format: Two files: .github/workflows/labeler.yml and .github/labeler.yml
```

### 17. Create a Release Workflow

```
Act as a release engineer.
Context: We use semantic versioning. Releases are triggered by tags.
Task: Create a release workflow:
- Trigger: push tags matching v[0-9]+.[0-9]+.[0-9]+
- Generate changelog from commits since last tag
- Create GitHub release with changelog as body
- Upload build artifacts
Format: Complete YAML workflow.
```

### 18. Debug a Failing Workflow

```
Act as a GitHub Actions debugger.
Context: #file:[workflow path] — this workflow fails with:
[PASTE 5-10 LINES OF THE FAILURE OUTPUT]
Task:
- Identify the root cause
- Explain why it fails
- Provide the fix
Format: Brief diagnosis + the corrected YAML section.
Use Opus if the failure spans multiple jobs (3x).
```

### 19. Add Concurrency Controls

```
Act as a CI/CD engineer.
Context: #file:[workflow path] — multiple pushes trigger overlapping runs.
Task: Add concurrency controls:
- Group by: branch name for pushes, PR number for pull requests
- Cancel in-progress runs when a new commit arrives
- Don't cancel the main branch (let it complete)
Format: Show only the concurrency block to add to the workflow.
```

### 20. Write a Custom Action with Inputs/Outputs

```
Act as a GitHub Actions developer.
Context: We need a reusable action for [DESCRIBE PURPOSE].
Task: Create a custom composite action:
- Inputs: [LIST WITH required/optional, types, defaults]
- Outputs: [LIST WITH descriptions]
- Steps:
  1. Validate inputs
  2. Run Python script with inputs passed as env vars
  3. Set outputs from script results
- Include error handling for missing required inputs
Format: action.yml + entrypoint Python script. Both complete files.
```

---

## Inline Completion Tips 💡

These aren't chat prompts — they're code comments that prime inline completions:

```python
# Parse command-line arguments using argparse with:
# --config (required, path to YAML config)
# --environment (optional, default "staging")
# --dry-run (flag, no value)

# Create an httpx.AsyncClient with:
# - 30 second timeout
# - retry on 5xx with exponential backoff
# - custom User-Agent header

# GitHub Actions: Read INPUT_* environment variables
# and validate all required inputs are present
```

Write the comment, press Enter, and let Copilot complete. The more specific the comment, the better the completion.

---

## What's Next? 🚀

You have the principles and the templates. The final post addresses the often-neglected last step: making sure every change ships with updated documentation — automatically.

👉 **[Post 10 — Automated Documentation](content/efficient-ai/10-automated-documentation.md)** — AI-driven doc generation for every code change.

---

*— Ashwin*
