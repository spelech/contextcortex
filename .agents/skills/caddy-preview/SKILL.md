---
name: agent-preview
description: Use when generating visual artifacts, interactive HTML/JS apps, web mockups, charts, images, or reports that need to be presented to the user over remote SSH sessions via a live browser preview.
---

# Agent Preview Hub (`agent-preview`)

The **Agent Preview Hub** provides a persistent, zero-friction preview subdomain (`https://preview.wileyriley.com/<id>/` and `http://preview.lan/<id>/`) where agents can instantly host and share visual artifacts, web applications, charts, diagrams, or HTML reports without restarting Caddy.

## When to Use

Use `agent-preview` whenever:
- You create an HTML mockup, single-page app (React/Vue/Vite), or interactive web component for the user to inspect.
- You generate visual diagrams, charts (Chart.js/D3/Plotly), or images that are hard to view over remote SSH terminals.
- You produce test coverage reports, Playwright traces, or benchmark dashboards.
- The user asks to "show me", "preview this", or "render this".

## CLI Commands

The CLI utility is available globally as `agent-preview` (or `publish-preview`):

### 1. Publish a Directory / Built Webapp
```bash
agent-preview publish <slot-id> <source_dir> --title "My App Title" --category "Web App" --tags "React,Vite"
```
*Copies the directory into the preview engine and generates the live URL.*

### 2. Publish Inline HTML / Markdown Text
```bash
agent-preview text <slot-id> "<div class='p-6'><h1>Report Title</h1><p>Status: All checks passed.</p></div>" --title "Status Report"
```
*Instantly creates an `index.html` with Tailwind styling.*

### 3. Publish a Standalone Image / Diagram
```bash
agent-preview publish <slot-id> /path/to/diagram.png --title "Architecture Diagram v2"
```
*Copies the image and generates a viewer wrapper.*

### 4. Register a Live Dev Server / Container Port
```bash
agent-preview port <slot-id> <port_number> --title "FastAPI Live Demo"
```
*Creates a live bridge to `https://p-<port>.wileyriley.com` (or `https://preview.wileyriley.com/port/<port>/`) without modifying Caddy.*

### 5. Pin / Retention Control
By default, preview slots have a **7-day auto-TTL**. Pass `--keep` or run `pin` to make it permanent:
```bash
agent-preview publish <slot-id> <path> --keep
# Or pin existing:
agent-preview pin <slot-id>
```

### 5. List Active Previews
```bash
agent-preview list
```

## Responding to the User

When you publish a preview, always output a clean markdown link in your response:
```markdown
You can inspect the live preview here:
- **Remote HTTPS:** [Open Preview](https://preview.wileyriley.com/<slot-id>/)
- **Local LAN:** [LAN Direct](http://preview.lan/<slot-id>/)
- **Preview Hub Directory:** [All Previews](https://preview.wileyriley.com/)
```
