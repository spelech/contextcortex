# Vite Live Theme Editor Plugin (`vite-plugin-theme-editor`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a standalone, reusable, framework-agnostic Vite plugin (`vite-plugin-theme-editor`) in a new GitHub repository at `/containers/dev/vite-plugin-theme-editor` that auto-discovers `:root` CSS custom properties across project stylesheets, provides an isolated Shadow DOM live tweaking drawer with smart controls (colors, sliders, text), and performs comment-preserving AST disk writes with diff verification.

**Architecture:** A TypeScript library packaged with `tsup` and tested with `vitest`. The server component attaches Connect middleware to Vite's dev server (`configureServer`) using PostCSS for AST-preserving `:root` variable extraction and file mutation. The client component is an encapsulated Web Component (`<theme-editor-overlay>`) injected via `transformIndexHtml` during `apply: 'serve'` that mutates `document.documentElement.style` for sub-millisecond live visual feedback.

**Tech Stack:** TypeScript, Node.js (fs/path), Vite (dev server & plugin API), PostCSS (AST parser & stringifier), fast-glob, diff / fast-diff, Vitest.

## Global Constraints
- Target repository: `/containers/dev/vite-plugin-theme-editor` created via `gh repo create`.
- Plugin must only run during dev mode (`apply: 'serve'`) with 0KB production footprint.
- PostCSS modifications must preserve exact source formatting, indentation, and comments.
- Client UI must live completely inside Shadow DOM with 0 styling bleed into or from the host web app.
- Zero external runtime framework dependencies for the client (Vanilla TS / Web Components).

---

### Task 1: Scaffolding GitHub Repository & Project Structure

**Files:**
- Create: `/containers/dev/vite-plugin-theme-editor/package.json`
- Create: `/containers/dev/vite-plugin-theme-editor/tsconfig.json`
- Create: `/containers/dev/vite-plugin-theme-editor/tsup.config.ts`
- Create: `/containers/dev/vite-plugin-theme-editor/vitest.config.ts`
- Create: `/containers/dev/vite-plugin-theme-editor/src/types.ts`

**Interfaces:**
- Produces: Project build pipeline, test runner, and shared `ThemeVariable`, `FileThemeMap`, `ThemeEditorOptions`, `SavePayload`, and `DiffResult` interfaces.

- [ ] **Step 1: Create GitHub repository and initialize directory**

```bash
cd /containers/dev
gh repo create vite-plugin-theme-editor --public --clone || mkdir -p /containers/dev/vite-plugin-theme-editor
cd /containers/dev/vite-plugin-theme-editor
git init
```

- [ ] **Step 2: Create `package.json` and configure dependencies**

```json
{
  "name": "vite-plugin-theme-editor",
  "version": "1.0.0",
  "description": "Live in-browser CSS variable theme editor with AST-preserving disk sync for Vite",
  "main": "./dist/index.js",
  "module": "./dist/index.mjs",
  "types": "./dist/index.d.ts",
  "exports": {
    ".": {
      "types": "./dist/index.d.ts",
      "import": "./dist/index.mjs",
      "require": "./dist/index.js"
    }
  },
  "files": [
    "dist"
  ],
  "scripts": {
    "build": "tsup",
    "dev": "tsup --watch",
    "test": "vitest run"
  },
  "keywords": [
    "vite",
    "vite-plugin",
    "theme",
    "css-variables",
    "devtools",
    "theme-editor"
  ],
  "author": "",
  "license": "MIT",
  "peerDependencies": {
    "vite": "^5.0.0 || ^6.0.0"
  },
  "dependencies": {
    "diff": "^7.0.0",
    "fast-glob": "^3.3.2",
    "postcss": "^8.4.38"
  },
  "devDependencies": {
    "@types/diff": "^7.0.0",
    "@types/node": "^20.11.0",
    "tsup": "^8.0.2",
    "typescript": "^5.4.0",
    "vite": "^6.0.0",
    "vitest": "^2.0.0"
  }
}
```

- [ ] **Step 3: Create `tsconfig.json`, `tsup.config.ts`, `vitest.config.ts`, and `src/types.ts`**

`src/types.ts`:
```typescript
export type VariableType = 'color' | 'dimension' | 'font' | 'raw';

export interface ThemeVariable {
  name: string;
  value: string;
  inferredType: VariableType;
  unit?: string;
  rawBefore?: string;
  line?: number;
}

export interface FileThemeMap {
  filePath: string;
  relativePath: string;
  variables: ThemeVariable[];
}

export interface ThemeEditorOptions {
  include?: string[];
  exclude?: string[];
  defaultOpen?: boolean;
}

export interface DiffResult {
  filePath: string;
  original: string;
  modified: string;
  unifiedDiff: string;
  changesCount: number;
}

export interface SavePayload {
  filePath: string;
  updates: Record<string, string>;
}
```

- [ ] **Step 4: Install dependencies and verify TypeScript compilation**

```bash
cd /containers/dev/vite-plugin-theme-editor
npm install
npm run build
```
Expected: Build passes and outputs `dist/`.

- [ ] **Step 5: Commit initial repository scaffolding**

```bash
cd /containers/dev/vite-plugin-theme-editor
git add .
git commit -m "chore: scaffold vite-plugin-theme-editor project structure and types"
```

---

### Task 2: CSS Scanner & Variable Parser

**Files:**
- Create: `/containers/dev/vite-plugin-theme-editor/src/server/scanner.ts`
- Test: `/containers/dev/vite-plugin-theme-editor/tests/scanner.test.ts`

**Interfaces:**
- Consumes: `ThemeVariable`, `FileThemeMap`, `VariableType` from `../types`
- Produces: `scanProjectStylesheets(rootDir: string, options?: ThemeEditorOptions): Promise<FileThemeMap[]>` and `inferVariableType(value: string, name?: string): VariableType`

- [ ] **Step 1: Write failing unit tests in `tests/scanner.test.ts`**

```typescript
import { describe, it, expect } from 'vitest';
import { parseCssVariables, inferVariableType } from '../src/server/scanner';

describe('scanner', () => {
  it('infers variable types accurately', () => {
    expect(inferVariableType('#3b82f6', '--primary')).toBe('color');
    expect(inferVariableType('rgba(18, 26, 47, 0.65)', '--bg-card')).toBe('color');
    expect(inferVariableType('12px', '--radius')).toBe('dimension');
    expect(inferVariableType('1.5rem', '--spacing-lg')).toBe('dimension');
    expect(inferVariableType("'Outfit', sans-serif", '--font-body')).toBe('font');
    expect(inferVariableType('0 10px 25px rgba(0,0,0,0.5)', '--shadow')).toBe('raw');
  });

  it('extracts :root variables and values from CSS content', () => {
    const css = `
      :root {
        --bg-base: #0a0f1d;
        --radius: 12px;
        --font-main: 'Outfit', sans-serif;
      }
      .card { color: red; }
    `;
    const vars = parseCssVariables(css);
    expect(vars).toHaveLength(3);
    expect(vars[0]).toMatchObject({ name: '--bg-base', value: '#0a0f1d', inferredType: 'color' });
    expect(vars[1]).toMatchObject({ name: '--radius', value: '12px', inferredType: 'dimension' });
    expect(vars[2]).toMatchObject({ name: '--font-main', value: "'Outfit', sans-serif", inferredType: 'font' });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /containers/dev/vite-plugin-theme-editor && npm test
```
Expected: FAIL with missing `src/server/scanner.ts`.

- [ ] **Step 3: Implement `src/server/scanner.ts`**

```typescript
import postcss, { Declaration } from 'postcss';
import fg from 'fast-glob';
import fs from 'fs/promises';
import path from 'path';
import type { ThemeVariable, FileThemeMap, VariableType, ThemeEditorOptions } from '../types';

export function inferVariableType(value: string, name: string = ''): VariableType {
  const trimmed = value.trim().toLowerCase();
  const lowerName = name.toLowerCase();

  // Color matching
  if (
    trimmed.startsWith('#') ||
    trimmed.startsWith('rgb(') ||
    trimmed.startsWith('rgba(') ||
    trimmed.startsWith('hsl(') ||
    trimmed.startsWith('hsla(') ||
    trimmed.startsWith('oklch(') ||
    lowerName.includes('color') ||
    lowerName.includes('bg') ||
    lowerName.includes('border') ||
    lowerName.includes('text') ||
    lowerName.includes('accent') ||
    lowerName.includes('primary')
  ) {
    if (!trimmed.includes('px') && !trimmed.includes('rem') && !trimmed.includes('calc(')) {
      return 'color';
    }
  }

  // Dimension matching
  if (/^-?\d+(\.\d+)?(px|rem|em|%|vh|vw|pt)$/.test(trimmed) || 
      lowerName.includes('radius') || 
      lowerName.includes('spacing') || 
      lowerName.includes('gap') || 
      lowerName.includes('padding') || 
      lowerName.includes('margin') || 
      lowerName.includes('size')) {
    return 'dimension';
  }

  // Font matching
  if (lowerName.includes('font') || trimmed.includes('sans-serif') || trimmed.includes('monospace') || trimmed.includes('serif')) {
    return 'font';
  }

  return 'raw';
}

export function parseCssVariables(cssContent: string): ThemeVariable[] {
  const root = postcss.parse(cssContent);
  const variables: ThemeVariable[] = [];

  root.walkRules((rule) => {
    if (rule.selector.includes(':root') || rule.selector.includes('html') || rule.selector.includes('body')) {
      rule.walkDecls((decl: Declaration) => {
        if (decl.prop.startsWith('--')) {
          variables.push({
            name: decl.prop,
            value: decl.value,
            inferredType: inferVariableType(decl.value, decl.prop),
            line: decl.source?.start?.line,
            rawBefore: decl.raws.before
          });
        }
      });
    }
  });

  return variables;
}

export async function scanProjectStylesheets(rootDir: string, options: ThemeEditorOptions = {}): Promise<FileThemeMap[]> {
  const include = options.include || ['src/**/*.{css,scss,pcss,postcss,less}', '*.{css,scss}'];
  const exclude = options.exclude || ['**/node_modules/**', '**/dist/**', '**/.git/**', '**/coverage/**'];

  const files = await fg(include, {
    cwd: rootDir,
    ignore: exclude,
    absolute: true
  });

  const results: FileThemeMap[] = [];

  for (const file of files) {
    try {
      const content = await fs.readFile(file, 'utf-8');
      const variables = parseCssVariables(content);
      if (variables.length > 0) {
        results.push({
          filePath: file,
          relativePath: path.relative(rootDir, file),
          variables
        });
      }
    } catch {
      // Ignore unparseable files
    }
  }

  return results;
}
```

- [ ] **Step 4: Run tests and verify they pass**

```bash
cd /containers/dev/vite-plugin-theme-editor && npm test
```
Expected: PASS with 2 passed test cases.

- [ ] **Step 5: Commit scanner component**

```bash
cd /containers/dev/vite-plugin-theme-editor
git add src/server/scanner.ts tests/scanner.test.ts
git commit -m "feat: implement CSS scanner and variable type inference"
```

---

### Task 3: AST-Preserving Rewriter & Diff Engine

**Files:**
- Create: `/containers/dev/vite-plugin-theme-editor/src/server/rewriter.ts`
- Create: `/containers/dev/vite-plugin-theme-editor/src/server/diff.ts`
- Test: `/containers/dev/vite-plugin-theme-editor/tests/rewriter.test.ts`
- Test: `/containers/dev/vite-plugin-theme-editor/tests/diff.test.ts`

**Interfaces:**
- Consumes: `SavePayload`, `DiffResult` from `../types`
- Produces: `updateCssVariables(originalCss: string, updates: Record<string, string>): string`, `generateDiff(filePath: string, originalContent: string, newContent: string): DiffResult`, and `saveCssChanges(payload: SavePayload): Promise<void>`

- [ ] **Step 1: Write failing unit tests for rewriter and diff**

`tests/rewriter.test.ts`:
```typescript
import { describe, it, expect } from 'vitest';
import { updateCssVariables } from '../src/server/rewriter';

describe('rewriter', () => {
  it('updates CSS variables while preserving indentation and comments', () => {
    const original = `/* Global Theme */
:root {
    --bg-base: #0a0f1d; /* Main background */
    --radius: 12px;
}
`;
    const updated = updateCssVariables(original, {
      '--bg-base': '#1e293b',
      '--radius': '16px'
    });

    expect(updated).toContain('--bg-base: #1e293b; /* Main background */');
    expect(updated).toContain('--radius: 16px;');
    expect(updated).toContain('/* Global Theme */');
  });
});
```

`tests/diff.test.ts`:
```typescript
import { describe, it, expect } from 'vitest';
import { generateDiff } from '../src/server/diff';

describe('diff', () => {
  it('generates line diffs for modified CSS content', () => {
    const original = ':root {\n  --primary: #3b82f6;\n}\n';
    const modified = ':root {\n  --primary: #2563eb;\n}\n';
    const diff = generateDiff('src/index.css', original, modified);

    expect(diff.changesCount).toBeGreaterThan(0);
    expect(diff.unifiedDiff).toContain('-  --primary: #3b82f6;');
    expect(diff.unifiedDiff).toContain('+  --primary: #2563eb;');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /containers/dev/vite-plugin-theme-editor && npm test
```
Expected: FAIL.

- [ ] **Step 3: Implement `src/server/rewriter.ts` and `src/server/diff.ts`**

`src/server/rewriter.ts`:
```typescript
import postcss, { Declaration } from 'postcss';
import fs from 'fs/promises';
import type { SavePayload } from '../types';

export function updateCssVariables(originalCss: string, updates: Record<string, string>): string {
  const root = postcss.parse(originalCss);

  root.walkRules((rule) => {
    if (rule.selector.includes(':root') || rule.selector.includes('html') || rule.selector.includes('body')) {
      rule.walkDecls((decl: Declaration) => {
        if (decl.prop.startsWith('--') && updates[decl.prop] !== undefined) {
          decl.value = updates[decl.prop];
        }
      });
    }
  });

  return root.toString();
}

export async function saveCssChanges(payload: SavePayload): Promise<void> {
  const currentContent = await fs.readFile(payload.filePath, 'utf-8');
  const updatedContent = updateCssVariables(currentContent, payload.updates);
  await fs.writeFile(payload.filePath, updatedContent, 'utf-8');
}
```

`src/server/diff.ts`:
```typescript
import * as Diff from 'diff';
import type { DiffResult } from '../types';

export function generateDiff(filePath: string, original: string, modified: string): DiffResult {
  const patch = Diff.createPatch(filePath, original, modified, 'disk', 'staged');
  const changes = Diff.diffLines(original, modified);
  const changesCount = changes.filter(c => c.added || c.removed).length;

  return {
    filePath,
    original,
    modified,
    unifiedDiff: patch,
    changesCount
  };
}
```

- [ ] **Step 4: Run tests and verify they pass**

```bash
cd /containers/dev/vite-plugin-theme-editor && npm test
```
Expected: PASS all test suites.

- [ ] **Step 5: Commit rewriter and diff components**

```bash
cd /containers/dev/vite-plugin-theme-editor
git add src/server/rewriter.ts src/server/diff.ts tests/rewriter.test.ts tests/diff.test.ts
git commit -m "feat: implement AST-preserving CSS rewriter and diff generator"
```

---

### Task 4: Connect Dev Middleware & Vite Plugin Definition

**Files:**
- Create: `/containers/dev/vite-plugin-theme-editor/src/server/middleware.ts`
- Create: `/containers/dev/vite-plugin-theme-editor/src/index.ts`
- Test: `/containers/dev/vite-plugin-theme-editor/tests/middleware.test.ts`

**Interfaces:**
- Consumes: `scanProjectStylesheets`, `updateCssVariables`, `generateDiff`, `saveCssChanges`
- Produces: `createThemeEditorMiddleware(rootDir: string, options?: ThemeEditorOptions)`, `themeEditorPlugin(options?: ThemeEditorOptions): Plugin`

- [ ] **Step 1: Implement `src/server/middleware.ts`**

```typescript
import type { Connect } from 'vite';
import fs from 'fs/promises';
import path from 'path';
import { scanProjectStylesheets } from './scanner';
import { generateDiff } from './diff';
import { updateCssVariables, saveCssChanges } from './rewriter';
import type { ThemeEditorOptions, SavePayload } from '../types';

export function createThemeEditorMiddleware(rootDir: string, options: ThemeEditorOptions = {}): Connect.NextHandleFunction {
  return async (req, res, next) => {
    const url = req.url || '';

    if (!url.startsWith('/__theme_editor/api/')) {
      return next();
    }

    const endpoint = url.replace('/__theme_editor/api/', '').split('?')[0];

    const sendJson = (data: any, status = 200) => {
      res.statusCode = status;
      res.setHeader('Content-Type', 'application/json');
      res.end(JSON.stringify(data));
    };

    const parseBody = async <T>(): Promise<T> => {
      return new Promise((resolve, reject) => {
        let body = '';
        req.on('data', chunk => body += chunk);
        req.on('end', () => {
          try {
            resolve(JSON.parse(body || '{}'));
          } catch (e) {
            reject(e);
          }
        });
      });
    };

    try {
      if (req.method === 'GET' && endpoint === 'scan') {
        const files = await scanProjectStylesheets(rootDir, options);
        return sendJson({ success: true, files });
      }

      if (req.method === 'POST' && endpoint === 'diff') {
        const payload = await parseBody<SavePayload>();
        const fullPath = path.resolve(rootDir, payload.filePath);
        if (!fullPath.startsWith(rootDir)) {
          return sendJson({ success: false, error: 'Path traversal forbidden' }, 403);
        }
        const originalContent = await fs.readFile(fullPath, 'utf-8');
        const modifiedContent = updateCssVariables(originalContent, payload.updates);
        const diff = generateDiff(payload.filePath, originalContent, modifiedContent);
        return sendJson({ success: true, diff });
      }

      if (req.method === 'POST' && endpoint === 'save') {
        const payload = await parseBody<SavePayload>();
        const fullPath = path.resolve(rootDir, payload.filePath);
        if (!fullPath.startsWith(rootDir)) {
          return sendJson({ success: false, error: 'Path traversal forbidden' }, 403);
        }
        await saveCssChanges({ ...payload, filePath: fullPath });
        return sendJson({ success: true, message: 'Styles written to disk' });
      }

      return next();
    } catch (err: any) {
      sendJson({ success: false, error: err.message || 'Internal Server Error' }, 500);
    }
  };
}
```

- [ ] **Step 2: Implement `src/index.ts`**

```typescript
import type { Plugin, ViteDevServer } from 'vite';
import { createThemeEditorMiddleware } from './server/middleware';
import type { ThemeEditorOptions } from './types';
import { CLIENT_SCRIPT_INLINE } from './client/bundle-inline';

export * from './types';

export function themeEditorPlugin(options: ThemeEditorOptions = {}): Plugin {
  return {
    name: 'vite-plugin-theme-editor',
    apply: 'serve', // Dev mode only

    configureServer(server: ViteDevServer) {
      const rootDir = server.config.root;
      server.middlewares.use(createThemeEditorMiddleware(rootDir, options));

      // Serve the client script via virtual module
      server.middlewares.use((req, res, next) => {
        if (req.url === '/@theme-editor-client.js') {
          res.setHeader('Content-Type', 'application/javascript');
          res.end(CLIENT_SCRIPT_INLINE);
          return;
        }
        next();
      });
    },

    transformIndexHtml(html) {
      return {
        html,
        tags: [
          {
            tag: 'script',
            attrs: {
              type: 'module',
              src: '/@theme-editor-client.js'
            },
            injectTo: 'body'
          }
        ]
      };
    }
  };
}

export default themeEditorPlugin;
```

- [ ] **Step 3: Commit middleware and plugin entry**

```bash
cd /containers/dev/vite-plugin-theme-editor
git add src/server/middleware.ts src/index.ts
git commit -m "feat: implement dev middleware and Vite plugin definition"
```

---

### Task 5: Shadow DOM Client Overlay, Smart Inputs & Diff Modal

**Files:**
- Create: `/containers/dev/vite-plugin-theme-editor/src/client/styles.ts`
- Create: `/containers/dev/vite-plugin-theme-editor/src/client/controls.ts`
- Create: `/containers/dev/vite-plugin-theme-editor/src/client/diff-modal.ts`
- Create: `/containers/dev/vite-plugin-theme-editor/src/client/overlay.ts`
- Create: `/containers/dev/vite-plugin-theme-editor/src/client/bundle-inline.ts`

**Interfaces:**
- Produces: Encapsulated Shadow DOM client UI with real-time `setProperty` updates, file switching, and diff dialog.

- [ ] **Step 1: Implement `src/client/styles.ts`**

Isolated CSS rules for drawer, floating toggle button, inputs, badges, color pickers, and diff modal inside the Shadow Root.

- [ ] **Step 2: Implement `src/client/controls.ts`**

Renders color swatches + `<input type="color">`, range sliders with unit badges, and text inputs with reset buttons.

- [ ] **Step 3: Implement `src/client/diff-modal.ts` and `src/client/overlay.ts`**

Builds the Web Component `<theme-editor-overlay>`, attaches open `ShadowRoot`, connects to `/__theme_editor/api/scan`, applies `document.documentElement.style.setProperty(...)` live, and handles diff review & save.

- [ ] **Step 4: Verify build bundling with `npm run build`**

```bash
cd /containers/dev/vite-plugin-theme-editor
npm run build
```
Expected: `dist/` contains clean ES and CJS outputs with d.ts definitions.

- [ ] **Step 5: Commit client overlay implementation**

```bash
cd /containers/dev/vite-plugin-theme-editor
git add src/client/
git commit -m "feat: implement Shadow DOM client overlay, controls, and diff modal"
```

---

### Task 6: Verification on Knowledge RAG Dashboard (`notes-rag-mcp/frontend`)

**Files:**
- Modify: `/containers/dev/notes-rag-mcp/frontend/vite.config.ts`
- Modify: `/containers/dev/notes-rag-mcp/frontend/package.json` (add local file link or link via npm)

**Interfaces:**
- Consumes: `themeEditorPlugin` from `/containers/dev/vite-plugin-theme-editor`

- [ ] **Step 1: Link plugin into `notes-rag-mcp/frontend`**

```bash
cd /containers/dev/notes-rag-mcp/frontend
npm install /containers/dev/vite-plugin-theme-editor
```

- [ ] **Step 2: Add `themeEditorPlugin()` to `frontend/vite.config.ts`**

```typescript
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { themeEditorPlugin } from 'vite-plugin-theme-editor';

export default defineConfig({
  plugins: [
    react(),
    themeEditorPlugin()
  ],
  server: {
    port: 5173
  }
});
```

- [ ] **Step 3: Run dev server and test live editing & disk save**

```bash
cd /containers/dev/notes-rag-mcp/frontend
npm run build
```
Verify production build passes with zero bundle pollution.

- [ ] **Step 4: Run Playwright and Vitest test suites in `frontend`**

```bash
cd /containers/dev/notes-rag-mcp/frontend
npm test
```
Verify that existing unit tests continue to pass seamlessly.

- [ ] **Step 5: Commit plugin integration into `notes-rag-mcp`**

```bash
cd /containers/dev/notes-rag-mcp
git add frontend/
git commit -m "feat: integrate vite-plugin-theme-editor into dev environment"
```
