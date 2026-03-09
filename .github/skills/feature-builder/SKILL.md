---
name: feature-builder
description: "**WORKFLOW SKILL** — Implement features end-to-end following a structured workflow. USE FOR: building new pages, adding API endpoints, creating UI components, implementing business logic, wiring frontend to backend. DO NOT USE FOR: planning only (use project-planner), deployment (use deployer agent). INVOKES: specialized agents (architect, frontend, backend, QA), file system tools, terminal."
argument-hint: "Describe the feature to implement"
---

# Feature Builder

Implement features end-to-end by orchestrating specialized agents through a structured workflow.

## When to Use
- Implementing a new feature that spans backend + frontend
- Adding a new page or API endpoint
- Building a new app module (e.g., Alt Investments Tracker)
- Any implementation task that touches multiple layers

## Procedure

### 1. Understand the Feature
- Read the plan if one exists (check `.github/plans/`)
- Explore related code with a subagent
- Identify all files that need to change

### 2. Architecture Phase
Delegate to the **Architect** agent:
- Define data models and schemas
- Design API contracts (endpoints, request/response shapes)
- Identify integration points with existing code
- Document decisions

### 3. Backend Phase
Delegate to the **Backend** agent:
- Implement Flask routes and API endpoints
- Add database models or queries
- Wire up business logic
- Add CSRF protection, rate limiting, auth decorators as needed

### 4. Frontend Phase
Delegate to the **Frontend** agent:
- Create or update Jinja2 templates
- Apply pastel theme using CSS custom properties from `landing.css`
- Add client-side JavaScript for interactivity
- Ensure dark mode support via `prefers-color-scheme`
- Verify responsive design

### 5. Integration
- Wire frontend forms/buttons to backend endpoints
- Test the full flow manually or with curl
- Verify error handling and edge cases

### 6. Quality Phase
Delegate to the **QA** agent:
- Review code for security (OWASP Top 10)
- Validate HTML structure and accessibility
- Check for missing error handling
- Verify CSRF tokens on forms
- Test edge cases

### 7. Finalize
- Run the dev server and verify: `python -m options_monitor_agent.dashboard.app`
- Check for errors with diagnostics tools
- Commit with a descriptive message

## Agent Workflow Diagram

```
Feature Request
      │
      ▼
  [Architect] ──→ Design & contracts
      │
      ▼
  [Backend]   ──→ Routes, APIs, data
      │
      ▼
  [Frontend]  ──→ Templates, CSS, JS
      │
      ▼
  [QA]        ──→ Review & validation
      │
      ▼
  [Deployer]  ──→ Config updates (if needed)
```

## Output Format
After each phase, report:
1. What was implemented
2. Files created or modified
3. Any decisions made or trade-offs
4. Ready for next phase / blocked by [issue]

## References
- [Workspace instructions](../../../.github/copilot-instructions.md)
- [Project structure](../../../README.txt)
