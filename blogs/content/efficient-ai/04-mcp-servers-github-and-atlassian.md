---
title: "MCP Servers: GitHub & Atlassian — Connect Copilot to Your Tools"
date: 2026-04-22
tags: [github-copilot, mcp, model-context-protocol, github-api, jira, confluence, atlassian, agent-mode]
description: Set up Model Context Protocol servers to connect GitHub Copilot to GitHub and Atlassian (Jira + Confluence) — covering configuration, authentication, capabilities, practical examples, and troubleshooting.
---

# MCP Servers: GitHub & Atlassian — Connect Copilot to Your Tools 🔌

This is **Post 4 of 10** in the Efficient AI Handbook.

Without MCP servers, Copilot is limited to what it can see in your editor — local files and your conversation. With MCP, Copilot can reach into external systems: pull a Jira story, create a GitHub PR, search Confluence documentation — all from the chat panel, without switching windows.

This post covers the setup of two MCP servers: **GitHub** and **Atlassian (Jira + Confluence)**.

---

## What Is MCP? 🧩

The **Model Context Protocol (MCP)** is an open standard that lets AI assistants interact with external tools and data sources. Think of it as a plugin system — each MCP server exposes a set of "tools" (functions) that the AI can call.

**How it works in VS Code:**

1. You configure MCP servers in a JSON file
2. When you use **Agent mode**, Copilot discovers the tools each server provides
3. During a conversation, the agent decides which tools to call based on your prompt
4. Tool results are injected into the conversation as additional context

> **Agent mode is required.** MCP tools are only available in Agent mode — they don't work in Ask or Edit mode. If you're not seeing MCP tools in your chat, make sure you've switched to Agent mode.

---

## Configuration File 📁

MCP servers are configured in one of two places:

| Scope | File Location | Applies To |
|---|---|---|
| **Workspace-level** | `.vscode/mcp.json` in your project root | This project only (recommended for team sharing) |
| **User-level** | VS Code Settings → MCP configuration | All projects on your machine |

**To create workspace-level config:**

1. Create `.vscode/mcp.json` in your project root
2. Add server definitions in the format below

**Basic structure:**

```json
{
  "mcpServers": {
    "server-name": {
      "command": "executable-or-npx",
      "args": ["arg1", "arg2"],
      "env": {
        "OPTIONAL_ENV_VAR": "value"
      }
    }
  }
}
```

> **Team sharing:** Adding `.vscode/mcp.json` to your repository means every team member gets the same MCP configuration when they clone the repo. Commit the structure but use environment variables for credentials — never hardcode tokens.

---

## GitHub MCP Server 🐙

The GitHub MCP server gives Copilot access to your GitHub repositories, issues, pull requests, and more — directly from chat.

### Setup

Add to your `.vscode/mcp.json`:

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${env:GITHUB_TOKEN}"
      }
    }
  }
}
```

**Authentication:**

1. Create a GitHub Personal Access Token (PAT) at `github.com/settings/tokens`
2. Grant scopes: `repo`, `read:org`, `read:user`, `workflow`
3. Set the token as an environment variable:

```bash
# Add to your shell profile (.bashrc, .zshrc, or PowerShell $PROFILE):
export GITHUB_TOKEN="ghp_your_token_here"
```

> **Why `${env:GITHUB_TOKEN}`?** This syntax tells VS Code to read the value from your system environment variables at runtime. The actual token never appears in `mcp.json` — so the file is safe to commit.

### Capabilities

Once configured, the GitHub MCP server provides these tools in Agent mode:

| Tool | What It Does | Example Prompt |
|---|---|---|
| **Search repos** | Find repositories by name or topic | "Find our team's infrastructure repos" |
| **Get issues** | Fetch issue details, comments, labels | "Get the details of issue #142" |
| **Create issues** | Open new issues with title, body, labels | "Create an issue for the failing deploy workflow" |
| **Get PRs** | Fetch PR details, diff, review status | "Show me the changes in PR #87" |
| **Create PRs** | Open new pull requests | "Create a PR from `feat/deploy` to `main` with this description" |
| **Read files** | Fetch file content from a repo | "Show me the CI workflow from the infra repo" |
| **Search code** | Search across repositories | "Find all files that import `boto3` in our org" |

### Practical Example

```
Agent mode prompt:
"Using the GitHub MCP, get the details of issue #23 in the
ashwinberyl/automation repo. Summarize the requirements and
suggest an implementation plan."
```

Copilot will call the GitHub MCP tool to fetch the issue, read its body and comments, and then use that context to generate an implementation plan.

---

## Atlassian MCP Server (Jira + Confluence) 🔷

The Atlassian MCP server connects Copilot to your Jira boards and Confluence spaces — pull stories, search documentation, and update pages.

### Setup

Add to your `.vscode/mcp.json`:

```json
{
  "mcpServers": {
    "atlassian": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://mcp.atlassian.com/v1/mcp"]
    }
  }
}
```

> **No API keys in config.** The Atlassian MCP server uses **OAuth 2.1** for authentication — it will open a browser window for you to authorize on first use. No tokens to manage manually.

### Authentication Flow

1. After adding the config, restart VS Code
2. Open Copilot Chat in Agent mode
3. Ask a question that requires Jira data (e.g., "Get my open Jira tickets")
4. A browser window opens → log in to your Atlassian account → authorize the MCP server
5. Credentials are cached locally for future sessions

**If authentication fails:**

- Revoke the existing authorization at `id.atlassian.com/manage-profile/apps`
- Restart VS Code and trigger the auth flow again
- If using a headless environment, ask your admin to enable API token auth in Rovo MCP settings

### Version Pinning

If you encounter compatibility issues, pin a specific version of the MCP proxy:

```json
{
  "mcpServers": {
    "atlassian": {
      "command": "npx",
      "args": ["-y", "mcp-remote@0.1.13", "https://mcp.atlassian.com/v1/mcp"]
    }
  }
}
```

### Capabilities

| Tool | What It Does | Example Prompt |
|---|---|---|
| **Search Jira issues** | Find issues by JQL, project, or text | "Find all open bugs in the INFRA project" |
| **Get issue details** | Fetch a specific Jira issue with full context | "Get the acceptance criteria for INFRA-456" |
| **Transition issues** | Move an issue to a new status | "Move INFRA-456 to In Review" |
| **Add comments** | Post a comment on a Jira issue | "Add a comment to INFRA-456: 'Implementation complete, PR #87 created'" |
| **Search Confluence** | Find Confluence pages by title or content | "Find the deployment runbook in Confluence" |
| **Read Confluence pages** | Fetch full page content | "Get the content of the 'Production Checklist' page" |
| **Create/Update pages** | Write or update Confluence documentation | "Update the deployment runbook with the new staging steps" |

### Practical Example

```
Agent mode prompt:
"Using Atlassian MCP, find all Jira stories assigned to me in the
current sprint of the DEVOPS project. List them with their status
and story points."
```

Copilot calls the Atlassian MCP's Jira search tool, retrieves your sprint items, and formats them in a readable list.

---

## Verifying MCP Tools ✅

After configuring servers, verify they're working:

1. **Output panel:** Open `View → Output` → select **MCP** from the dropdown. You'll see server startup logs and any errors.

2. **Agent mode discovery:** In the Copilot Chat panel (Agent mode), type `@` — you should see the MCP tools listed alongside built-in tools.

3. **Test with a simple prompt:**

```
"List the MCP tools available to you right now"
```

The agent should enumerate the tools from both GitHub and Atlassian servers.

### Common Issues

| Problem | Solution |
|---|---|
| MCP tools not appearing | Ensure you're in **Agent mode**, not Ask/Edit mode |
| "Server failed to start" | Check the Output panel → MCP for error details |
| GitHub: "Bad credentials" | Verify your `GITHUB_TOKEN` env var is set and the PAT hasn't expired |
| Atlassian: "Invalid access token" | Revoke auth at `id.atlassian.com/manage-profile/apps` and re-authorize |
| Node.js not found | Ensure Node.js v18+ is installed and on your PATH |
| Timeout errors | Check your network connection and any proxy/firewall settings |

---

## Complete MCP Configuration File 📄

Here's a workspace-level `.vscode/mcp.json` with both servers configured:

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${env:GITHUB_TOKEN}"
      }
    },
    "atlassian": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://mcp.atlassian.com/v1/mcp"]
    }
  }
}
```

Commit this file to your repository so your entire team has the same MCP configuration. Each developer will need to set their own `GITHUB_TOKEN` environment variable and complete the Atlassian OAuth flow individually.

---

## What's Next? 🚀

You've connected Copilot to GitHub and Jira/Confluence. The next post adds the third integration — Postgres — and covers the critical security practices that apply to ALL MCP servers.

👉 **[Post 5 — MCP Servers: Postgres & Security](content/efficient-ai/05-mcp-servers-postgres-and-security.md)** — Query databases from chat and lock down every MCP connection.

---

*— Ashwin*
