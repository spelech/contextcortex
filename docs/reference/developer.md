# Developer and Contributor Guide

This document provides developer guidelines for extending, testing, and building ContextCortex.

---

## Architectural Standards

All developers and contributors must adhere to these engineering standards:

1. **Sub-500 LOC Floor**:
   Every backend Python file and frontend TypeScript file must remain under 500 lines of code. If a file approaches this limit, split its logic into cohesive modules or helper services.

2. **ASD-STE100 English Compliance**:
   All technical documentation, code comments, and API error messages must follow ASD-STE100 Simplified Technical English (Issue 9) principles. Use short sentences, active voice, and clear terminology. Avoid contractions.

3. **Test-Driven Development (TDD)**:
   Write automated unit tests before implementing new features or resolving bug reports. Verify that tests fail first, then write minimal implementation code.

---

## Local Development Workflow

### 1. Python Backend Development
Activate your virtual environment and start the development server with auto-reload:

```bash
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 3000 --reload
```

### 2. React 19 Frontend Development
In a separate terminal, navigate to the frontend directory and start the Vite development server:

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server proxies API requests to the backend server at `http://localhost:3000`.

### 3. Documentation Site Development
To preview the VitePress documentation site locally:

```bash
npm run docs:dev
```

Open `http://localhost:5173/contextcortex/` in your web browser.

---

## Running Automated Test Suites

### Backend Unit and Integration Tests
Run the complete Pytest suite:
```bash
pytest -v
```

Generate test coverage reports:
```bash
pytest -v --cov=app --cov-report=term-missing
```

### Frontend Vitest Tests
Run component unit tests:
```bash
npm --prefix frontend run test
```

### End-to-End Layout Inspector Audits
Run Playwright browser audits:
```bash
npm --prefix frontend run test:layout
```

---

## Building Production Bundles

1. Compile the React 19 frontend bundle:
   ```bash
   cd frontend
   npm run build
   cd ..
   ```
   Compiled assets are placed in `frontend/dist`. The FastAPI application serves these assets at `/admin/`.

2. Build the VitePress documentation site:
   ```bash
   npm run docs:build
   ```
   Built HTML, JavaScript, and CSS files are placed in `docs/.vitepress/dist`.
