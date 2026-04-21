---
title: "MCP Servers: Postgres & Security — Query Databases, Lock It All Down"
date: 2026-04-22
tags: [github-copilot, mcp, postgres, database, security, credentials, devops, docker]
description: Set up a Postgres MCP server for database querying from Copilot Chat, then lock down ALL MCP integrations with security best practices — covering read-only access, credential management, network isolation, and auditing.
---

# MCP Servers: Postgres & Security — Query Databases, Lock It All Down 🔒

This is **Post 5 of 10** in the Efficient AI Handbook.

In [Post 4](content/efficient-ai/04-mcp-servers-github-and-atlassian.md), we connected Copilot to GitHub and Atlassian. This post adds the third integration — **Postgres** — and then covers the security practices that apply to every MCP server you run.

---

## Postgres MCP Server 🐘

The Postgres MCP server lets Copilot query your database directly from chat — inspect schemas, run SELECT queries, analyze table structures, and generate migrations.

### Prerequisites

- **Docker Desktop** installed and running
- A **PostgreSQL instance** accessible from your machine (local, staging, or cloud)
- The **connection string** for your database

### Setup

Add to your `.vscode/mcp.json`:

```json
{
  "mcpServers": {
    "postgres": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-e", "DATABASE_URI=${env:POSTGRES_URI}",
        "crystaldba/postgres-mcp"
      ]
    }
  }
}
```

Set the environment variable:

```bash
# Connection string format:
export POSTGRES_URI="postgresql://readonly_user:password@localhost:5432/mydb"
```

> **Why Docker?** The Docker-based approach is the most consistent across operating systems — no Python/pip dependency conflicts, no system-level package management. The container is lightweight and ephemeral (`--rm` removes it after each session).

### Creating a Read-Only Database User

**Never connect Copilot with a read-write database user.** Create a dedicated read-only user:

```sql
-- Connect as your database admin
CREATE USER copilot_readonly WITH PASSWORD 'secure_random_password';
GRANT CONNECT ON DATABASE mydb TO copilot_readonly;
GRANT USAGE ON SCHEMA public TO copilot_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO copilot_readonly;

-- Ensure future tables are also readable:
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT ON TABLES TO copilot_readonly;
```

Then use this user in your connection string:

```bash
export POSTGRES_URI="postgresql://copilot_readonly:secure_random_password@localhost:5432/mydb"
```

> **Why read-only?** An LLM generating and executing SQL is powerful but risky. A read-only user ensures that even a malformed or hallucinated query cannot `DROP TABLE`, `DELETE`, or `UPDATE` your data. This is a non-negotiable safety guardrail.

### Capabilities

| Tool | What It Does | Example Prompt |
|---|---|---|
| **List tables** | Show all tables in the database | "What tables exist in this database?" |
| **Describe table** | Show columns, types, constraints, indexes | "Describe the `deployments` table schema" |
| **Run SELECT** | Execute read-only SQL queries | "Show the 10 most recent deployments" |
| **Explain query** | Analyze query execution plans | "Why is this query slow? Show the execution plan" |

### Practical Examples

**Schema inspection:**
```
Agent mode: "Using Postgres MCP, list all tables and describe the
schema of the 'workflow_runs' table. Include column types and indexes."
```

**Data analysis:**
```
Agent mode: "Query the deployments table for all failed deployments
in the last 7 days. Group by failure reason and show counts."
```

**Migration generation:**
```
Agent mode: "Based on the current schema of the 'users' table,
generate an Alembic migration to add a 'last_login_at' timestamp
column with a default of now()."
```

> **Pro tip:** For migration generation, Copilot inspects the current schema via MCP, then generates the migration code in your editor — no manual schema lookup needed.

---

## Security Best Practices — All MCP Servers 🛡️

These practices apply to **every** MCP server — GitHub, Atlassian, Postgres, and any future integrations.

### 1. Never Hardcode Credentials

**❌ Never do this:**
```json
{
  "mcpServers": {
    "github": {
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_abc123realtoken456"
      }
    }
  }
}
```

**✅ Always do this:**
```json
{
  "mcpServers": {
    "github": {
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${env:GITHUB_TOKEN}"
      }
    }
  }
}
```

> **Why it matters:** If you hardcode a token in `mcp.json` and commit it, the token is in your Git history permanently — even if you remove it later. The `${env:VAR}` syntax reads from system environment variables at runtime. The `mcp.json` file can be safely committed.

### 2. Use `.env` Files for Local Development

For convenience without committing secrets:

```
# .env (add to .gitignore!)
GITHUB_TOKEN=ghp_your_token_here
POSTGRES_URI=postgresql://copilot_readonly:password@localhost:5432/mydb
```

Add to `.gitignore`:
```
.env
.env.local
.env.*.local
```

### 3. Principle of Least Privilege

Grant each MCP server the minimum access it needs:

| Server | Least Privilege Configuration |
|---|---|
| **GitHub** | PAT with only `repo`, `read:org` — skip `admin:org`, `delete_repo` |
| **Atlassian** | OAuth scopes limited to read + search by default |
| **Postgres** | Read-only user — no INSERT, UPDATE, DELETE, DROP |

### 4. Never Connect to Production Databases

```
✅ Connect to: local dev, staging, read replicas
❌ Never connect to: production primary databases
```

Even with a read-only user, running arbitrary SELECT queries against a production database can:
- Impact performance during peak load
- Expose sensitive data (PII, financial records) to the LLM context
- Create compliance issues (GDPR, HIPAA)

If you must query production data, use a **read replica** with an additional row-level security policy that masks sensitive columns.

### 5. Network Isolation

For Docker-based MCP servers (like Postgres), consider network restrictions:

```bash
# Run the MCP container with restricted network access:
docker run -i --rm \
  --network=host \
  -e DATABASE_URI=${POSTGRES_URI} \
  crystaldba/postgres-mcp
```

For production environments, use a dedicated Docker network that only allows connections to the specific database host.

### 6. Token Rotation

Set reminders to rotate credentials:

| Credential | Rotation Frequency |
|---|---|
| GitHub PAT | Every 90 days |
| Postgres password | Every 90 days |
| Atlassian OAuth | Re-authorize if revoked; tokens auto-expire |

### 7. Audit MCP Activity

Monitor what your MCP servers are doing:

- **VS Code Output panel → MCP:** Shows every tool call, including the arguments and responses
- **GitHub audit log:** Shows API calls made with your PAT
- **Postgres query log:** Enable `log_statement = 'all'` in development to see every query the MCP server executes

---

## Complete MCP Configuration 📄

Here's the full `.vscode/mcp.json` with all three servers:

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
    },
    "postgres": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-e", "DATABASE_URI=${env:POSTGRES_URI}",
        "crystaldba/postgres-mcp"
      ]
    }
  }
}
```

### Security Checklist

- [ ] All credentials use `${env:VAR}` — nothing hardcoded
- [ ] `.env` file is in `.gitignore`
- [ ] GitHub PAT has minimal scopes
- [ ] Postgres user is read-only
- [ ] No MCP server connects to production primary DB
- [ ] Token rotation reminders set (90-day cycle)
- [ ] MCP Output panel reviewed after first use

---

## What's Next? 🚀

Your Copilot environment is fully armed — it can access your code, your Jira stories, your Confluence docs, and your database. Now let's put it all together into a real workflow: taking a Jira story from backlog to implementation plan.

👉 **[Post 6 — The Jira-to-Code Workflow](content/efficient-ai/06-jira-to-code-workflow.md)** — The first half of the developer loop: from Jira story to implementation plan.

---

*— Ashwin*
