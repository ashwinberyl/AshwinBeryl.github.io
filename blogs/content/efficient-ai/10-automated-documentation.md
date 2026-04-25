---
title: "Automated Documentation — Every Change Ships with Updated Docs"
date: 2026-04-22
tags: [github-copilot, documentation, docstrings, readme, changelog, confluence, github-actions, skills, automation]
description: Build an AI-driven documentation workflow — generate Python docstrings, update READMEs, create changelog entries, sync with Confluence via MCP, document GitHub Actions workflows, and enforce doc quality in CI.
---

# Automated Documentation — Every Change Ships with Updated Docs 📖

This is **Post 10 of 10** in the Efficient AI Handbook.

Documentation is the first casualty of velocity. Teams ship features fast, docs fall behind, new engineers struggle to onboard, and production runbooks describe a system that no longer exists. The fix isn't discipline — it's automation. This post shows how to make documentation a byproduct of coding, not a separate task.

---

## The Documentation Debt Problem 💸

In DevOps teams, documentation debt compounds faster than tech debt:

| Symptom | Impact |
|---|---|
| Missing docstrings | New engineers can't understand function contracts |
| Stale README | Setup instructions reference old configs/dependencies |
| No changelog | Teams can't trace what changed between releases |
| Outdated Confluence runbooks | On-call engineers follow wrong procedures |
| Undocumented GitHub Actions | Contributors can't use or modify workflows |

The root cause: documentation is treated as a separate task done "after" coding. It's always deprioritized because there's always another Jira story.

> **The fix:** Make documentation generation part of the coding workflow itself — using the same Copilot tools you already use for implementation.

---

## Strategy: Doc-as-Code 📝

Treat documentation exactly like code:

1. **Version it** — Docs live in Git alongside the code they describe
2. **Review it** — PR diffs include doc changes for review
3. **Test it** — CI validates doc coverage and freshness
4. **Generate it** — AI produces first drafts; humans review and refine

This means every PR that changes code also includes doc updates. Copilot handles the generation; you handle the review.

---

## Inline Docstrings — Automated Generation 📋

### Prompt: Generate Docstrings for a Module

```
Act as a Python documentation specialist.
Context: #file:[path] — Python 3.11, we use Google-style docstrings.
Task: Add Google-style docstrings to every public function, class,
and method in this file. Include:
- One-line summary
- Args with types and descriptions
- Returns with type and description
- Raises with exception types and conditions
- Example usage for complex functions
Format: Return the complete file with docstrings added. Don't change
any code — only add docstrings.
```

### Prompt: Update Docstrings After a Code Change

```
Context: I just modified the function `deploy_to_staging` in
#file:src/deploy.py to accept a new parameter `timeout_seconds`.
Task: Update the docstring to reflect:
- The new parameter (type: int, default: 300)
- Updated return type (now returns a DeployResult dataclass, not bool)
Format: Show only the updated docstring.
```

### Add to `copilot-instructions.md`

To make docstring generation automatic, add this to your repo instructions:

```markdown
## Documentation Standard
- Every new public function MUST have a Google-style docstring
- When modifying a function's signature, update its docstring
- Docstrings should describe WHAT and WHY, not HOW
```

With this instruction, Copilot will include docstrings in every code generation — you won't need to ask separately.

---

## README Generation and Updates 📄

### Prompt: Generate a README Section from Code

```
Act as a technical writer.
Context: #file:src/stale_pr_checker.py and
#file:.github/actions/stale-pr-check/action.yml
Task: Generate a README section documenting this feature:
- What it does (one paragraph)
- How to use the action (YAML usage example with all inputs)
- Environment variables / secrets required
- Example output
Format: Markdown section with ## heading, ready to paste into README.md.
```

### Prompt: Update README After a Change

```
Context: I added a new CLI flag `--dry-run` to the deploy script.
#file:src/deploy.py has the updated code.
#file:README.md has the current documentation.
Task: Update the README.md usage section to include the new --dry-run
flag with a description and example.
Format: Show only the modified README section.
```

---

## Changelog Generation 📰

### Prompt: Generate Changelog Entry from Git Diff

```
Act as a release engineer.
Context: Here are the commits since the last release:
[PASTE OUTPUT OF: git log --oneline v1.2.0..HEAD]
Task: Generate a CHANGELOG.md entry in Keep a Changelog format:
- Categorize changes: Added, Changed, Fixed, Removed
- Write user-facing descriptions (not commit messages)
- Include the Jira story IDs where applicable
Format: Markdown section for version [Unreleased] in Keep a Changelog format.
```

### Prompt: Changelog from Jira Context

```
Agent mode:
"Using Atlassian MCP, fetch all Jira stories resolved in sprint 14
of the DEVOPS project. Generate a CHANGELOG entry:
- Group by: Added, Changed, Fixed
- Include story ID and one-line summary for each
- Format as Keep a Changelog markdown"
```

This combines MCP data (what was planned) with git data (what was shipped) for accurate release notes.

---

## Confluence Integration via MCP 🔷

### Search Existing Docs Before Writing

```
Agent mode:
"Using Atlassian MCP, search Confluence for pages about 'deployment
process' in the DevOps space. List the top 5 results with titles
and last-modified dates."
```

This prevents creating duplicate documentation. If a page exists, update it instead of creating a new one.

### Update an Existing Confluence Page

```
Agent mode:
"Using Atlassian MCP, get the content of the 'Staging Deployment
Runbook' page in Confluence. I've added a new pre-deployment check
for database migrations. Update the runbook by adding a new step
between 'Run smoke tests' and 'Enable traffic' that says:
'Run pending Alembic migrations: alembic upgrade head'. Keep
all existing content intact."
```

### Create a New Confluence Page

```
Agent mode:
"Using Atlassian MCP, create a new Confluence page in the DevOps
space titled 'Stale PR Checker — Operations Guide'. Include:
- What the workflow does
- How to configure it (inputs, secrets)
- How to troubleshoot common failures
- Link to the GitHub repository
Base the content on #file:.github/workflows/stale-pr-check.yml
and #file:src/stale_pr_checker.py"
```

---

## GitHub Actions Workflow Documentation ⚡

Workflows are notoriously undocumented. Use this template to generate docs for any workflow:

### Prompt: Document a Workflow

```
Act as a DevOps technical writer.
Context: #file:.github/workflows/[name].yml
Task: Generate documentation for this workflow:
- **Purpose:** What it does in one sentence
- **Trigger:** What events trigger it
- **Inputs:** Table of all inputs with types, defaults, descriptions
- **Secrets:** Table of required secrets
- **Jobs:** Numbered list of jobs with brief description
- **Outputs/Artifacts:** What the workflow produces
- **Usage example:** How to call it (for reusable workflows)
Format: Markdown section ready to add to docs/workflows.md
```

### Prompt: Generate Action Input/Output Table

```
Context: #file:.github/actions/[name]/action.yml
Task: Generate a markdown table documenting all inputs and outputs:
- Inputs: name, required?, type, default, description
- Outputs: name, description
Format: Two markdown tables, one for inputs, one for outputs.
```

---

## Automated Doc CI — Enforce in the Pipeline 🔧

Create a GitHub Action that validates documentation on every PR:

### Prompt: Create a Doc Validation Workflow

```
Agent mode:
"Create a GitHub Actions workflow that runs on pull_request and
validates documentation:
1. Check that all Python files in src/ have module-level docstrings
2. Check that all public functions have docstrings (use pydocstyle
   or interrogate)
3. Check that README.md was modified if any files in src/ were changed
4. Post a PR comment with the validation results
The workflow should not block merge but should add a 'docs-missing'
label if checks fail."
```

### Simple Docstring Coverage Check

Add `interrogate` to your CI pipeline:

```yaml
- name: Check docstring coverage
  run: |
    pip install interrogate
    interrogate src/ --fail-under 80 --verbose
```

`interrogate` checks that at least 80% of your public functions have docstrings and fails the job if coverage drops below the threshold.

---

## The Complete Documentation Flow 🔄

Here's how documentation fits into the developer loop from Posts 6–7:

| Step | Documentation Task | Tool |
|---|---|---|
| After code generation | Verify docstrings are present | Review Agent output |
| Before creating PR | Update README if needed | Copilot Chat + Edit mode |
| Before creating PR | Generate CHANGELOG entry | Copilot Chat prompt |
| After PR merge | Update Confluence runbook | Agent mode + Atlassian MCP |
| In CI | Validate docstring coverage | interrogate + GitHub Actions |

### End-to-End Example Session

```
1. [Agent mode, Sonnet] Implement feature (from Post 7 flow)
   → Code includes docstrings (copilot-instructions.md enforces this)

2. [Ask mode, Sonnet] "Generate a CHANGELOG entry for the changes
   in this branch"
   → Copy into CHANGELOG.md

3. [Edit mode, Sonnet] "Update README.md to document the new
   stale PR checker action"
   → Accept the diff

4. [PR created] → CI runs interrogate → docstring coverage: 92% ✅

5. [After merge, Agent mode] "Using Atlassian MCP, update the
   'Automation Inventory' Confluence page to include the new
   stale PR checker workflow"
   → Confluence updated without leaving VS Code
```

---

## Quick Reference — Documentation Checklist ✅

Before every PR:

- [ ] All new public functions have docstrings
- [ ] Modified function signatures have updated docstrings
- [ ] README updated if user-facing behavior changed
- [ ] CHANGELOG entry added for the release
- [ ] Confluence runbook updated (if operational procedure changed)
- [ ] Workflow documentation updated (if workflows changed)

---

## Documentation Skills — Automate the Entire Doc Flow 🧩

The prompts above work great individually, but documentation generation is one of the **strongest use cases for Agent Skills** — multi-step, repeatable, and benefiting from bundled templates.

### Skill: Post-Feature Documentation

```
.github/skills/post-feature-docs/
├── SKILL.md
├── templates/
│   ├── changelog-entry.md.template    ← Keep a Changelog format skeleton
│   ├── readme-section.md.template     ← Standard README feature section
│   └── confluence-page.md.template    ← Operations guide structure
└── references/
    └── doc-standards.md               ← Team documentation conventions
```

**The `SKILL.md`:**

```markdown
---
name: post-feature-docs
description: "Generate all documentation for a completed feature: docstrings, README section, changelog entry, and Confluence page"
---
# Post-Feature Documentation

## Steps
1. Scan all modified/new Python files in the current branch for missing
   or outdated docstrings — add or update them using Google-style format
2. Generate a README.md section for the feature using
   `./templates/readme-section.md.template`
3. Generate a CHANGELOG.md entry using
   `./templates/changelog-entry.md.template` with:
   - Changes categorized as Added/Changed/Fixed/Removed
   - Jira story IDs included where applicable
4. Generate a Confluence operations page using
   `./templates/confluence-page.md.template` with:
   - What the feature does
   - How to configure it
   - Troubleshooting common failures
5. Validate docstring coverage with `interrogate src/ --fail-under 80`
6. Follow conventions in `./references/doc-standards.md`

## Rules
- Docstrings describe WHAT and WHY, not HOW
- README sections include usage examples with all inputs
- CHANGELOG entries are user-facing descriptions, not commit messages
- Confluence pages always link back to the source repository
```

**How to use it:** After implementing a feature (Posts 6–7), simply ask *"generate documentation for this feature"* — Copilot auto-detects the skill, scans your changes, and produces all four documentation outputs in one session.

### Skill: Document a GitHub Actions Workflow

```markdown
---
name: document-workflow
description: "Generate comprehensive documentation for a GitHub Actions workflow file"
---
# Document a GitHub Actions Workflow

## Steps
1. Read the target workflow YAML file
2. Extract: triggers, inputs, secrets, jobs, steps, outputs/artifacts
3. Generate documentation with sections:
   - Purpose (one sentence)
   - Trigger events and conditions
   - Inputs table (name, type, required, default, description)
   - Secrets table (name, description, where to set)
   - Jobs overview (numbered, with dependencies)
   - Usage example (for reusable workflows)
4. Format as a markdown section ready for `docs/workflows.md`

## Rules
- Verify all documented inputs actually exist in the YAML
- Note any missing permission blocks as a warning
- Flag unpinned action references
```

> **The pattern:** Every repeated documentation task in this post — docstrings, READMEs, changelogs, Confluence pages, workflow docs — can be encoded as a `SKILL.md` with bundled templates. Start with the prompts above, and when you find yourself re-using the same one across multiple features, upgrade it to a skill.

---

## Handbook Complete 🎓

You've reached the end of the Efficient AI Handbook. Here's the full reading path:

| Post | Title |
|---|---|
| 1 | [Setup & Foundations](content/efficient-ai/01-setup-and-foundations.md) |
| 2 | [Model Selection & Cost Control](content/efficient-ai/02-model-selection-and-cost.md) |
| 3 | [Context & Token Optimization](content/efficient-ai/03-context-and-token-optimization.md) |
| 4 | [MCP Servers: GitHub & Atlassian](content/efficient-ai/04-mcp-servers-github-and-atlassian.md) |
| 5 | [MCP Servers: Postgres & Security](content/efficient-ai/05-mcp-servers-postgres-and-security.md) |
| 6 | [The Jira-to-Code Workflow](content/efficient-ai/06-jira-to-code-workflow.md) |
| 7 | [Coding & Validation](content/efficient-ai/07-coding-and-validation.md) |
| 8 | [Prompt Engineering Foundations](content/efficient-ai/08-prompt-engineering-foundations.md) |
| 9 | [Prompt Templates: Python & GitHub Actions](content/efficient-ai/09-prompt-templates-python-and-actions.md) |
| 10 | [Automated Documentation](content/efficient-ai/10-automated-documentation.md) |

---

Got questions or suggestions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*
