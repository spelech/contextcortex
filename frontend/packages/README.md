# Bundled Internal Packages

This directory contains pre-packed, offline-compatible tarballs for internal packages required by ContextCortex frontend tooling. They enable building within air-gapped enterprise environments and private npm mirrors without requiring external network access to public npm registries.

## Package Inventory

### 1. `@spelech/playwright-layout-inspector` (v1.0.0)
- **Tarball:** `spelech-playwright-layout-inspector-1.0.0.tgz`
- **Origin Repo:** `https://github.com/spelech/playwright-layout-inspector`
- **Provenance / Build Command:**
  ```bash
  git clone https://github.com/spelech/playwright-layout-inspector.git
  cd playwright-layout-inspector
  npm ci
  npm run build
  npm pack
  ```

### 2. `@spelech/vite-plugin-theme-editor` (v1.0.0)
- **Tarball:** `spelech-vite-plugin-theme-editor-1.0.0.tgz`
- **Origin Repo:** `https://github.com/spelech/vite-plugin-theme-editor`
- **Provenance / Build Command:**
  ```bash
  git clone https://github.com/spelech/vite-plugin-theme-editor.git
  cd vite-plugin-theme-editor
  npm ci
  npm run build
  npm pack
  ```

## Enterprise Installation
Packages are consumed via local file references in `frontend/package.json`:
```json
"@spelech/playwright-layout-inspector": "file:./packages/spelech-playwright-layout-inspector-1.0.0.tgz",
"@spelech/vite-plugin-theme-editor": "file:./packages/spelech-vite-plugin-theme-editor-1.0.0.tgz"
```
