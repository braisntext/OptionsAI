---
name: project-planner
description: "**WORKFLOW SKILL** — Plan, structure, and track project work. USE FOR: breaking down features into tasks, creating project roadmaps, defining milestones, estimating scope, writing technical specs, organizing sprints, reviewing progress. DO NOT USE FOR: writing actual code (use feature-builder or specialized agents). INVOKES: todo list, file system tools, subagents for codebase exploration."
argument-hint: "Describe the feature or project goal to plan"
---

# Project Planner

Plan and organize project work into actionable, trackable tasks.

## When to Use
- Starting a new feature or app module
- Breaking a large request into manageable phases
- Creating a technical spec before implementation
- Reviewing progress on an ongoing initiative
- Prioritizing a backlog of tasks

## Procedure

### 1. Gather Context
- Read [workspace instructions](../../../.github/copilot-instructions.md) for project context
- Explore the relevant codebase area using a read-only subagent
- If clarification is needed, ask targeted questions

### 2. Define Scope
Create a structured breakdown with:
- **Goal**: One-sentence description of what success looks like
- **Phases**: Logical groupings (e.g., "Backend API", "Frontend UI", "Integration")
- **Tasks**: Specific, actionable items within each phase
- **Dependencies**: Which tasks block others
- **Risks**: Known unknowns or technical challenges

### 3. Create Task List
Use the todo list tool to create trackable items:
- Each task should be completable in a single focused session
- Include acceptance criteria in task titles when possible
- Order tasks by dependency (blocked tasks last)

### 4. Generate Plan Document
If the project is substantial, create a plan file:

```markdown
# [Feature Name] — Plan

## Goal
[One sentence]

## Phases

### Phase 1: [Name]
- [ ] Task 1 — [description]
- [ ] Task 2 — [description]

### Phase 2: [Name]
- [ ] Task 3 — [description]
- [ ] Task 4 — [description]

## Dependencies
- Task 3 requires Task 1

## Risks
- [Risk and mitigation]

## Timeline
- Phase 1: [estimate]
- Phase 2: [estimate]
```

Save to `.github/plans/[feature-name].md`

### 5. Delegate
Recommend which specialized agent should handle each phase:
- **Architect**: System design, data models, API contracts
- **Frontend**: UI templates, CSS, client JS
- **Backend**: Flask routes, APIs, business logic
- **QA**: Testing, validation, security review
- **Deployer**: Render config, environment, CI/CD

## Output Format
Return:
1. A summary of the plan
2. The todo list (created via tool)
3. Recommended agent assignments per phase
4. Any questions or risks that need user input

## References
- [Workspace instructions](../../../.github/copilot-instructions.md)
- [Project structure](../../../README.txt)
