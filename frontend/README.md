# Hermes Finance Frontend

Minimal React, TypeScript and Vite interface for Hermes Finance.

## Requirements

- Node.js 22.22+
- npm
- backend running at `http://127.0.0.1:8000`

## Install and run

```bash
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` requests to the local backend.

## Test and build

```bash
npm test
npm run build
```

## Synthetic visual audit

Run the repeatable UI audit without a backend, owner database, `.env`, or live provider data:

```bash
npm run audit:visual
```

The workflow visits every routed page at 1366×768, 1440×900, and 1920×1080,
uses deterministic synthetic long-content responses, checks page-level horizontal overflow and
visible technical-field leakage, and writes screenshots to the ignored
`frontend/.visual-audit/<viewport>/` directory. Tables may scroll inside their own `.table-wrap`;
the document itself must not scroll horizontally.

On GitHub Actions, the audit runs automatically for pull requests that change
frontend source, UI assets, the visual-audit harness, its locked dependencies,
or the CI workflow. Backend-only and documentation-only pull requests run the
lightweight path filter but skip the Playwright audit. Every push to `main`
runs the audit as part of `ci.yml`; the guarded release flow requires that
exact-main CI run to succeed before publication is allowed.

For a manual local run, install the locked dependencies and browser once, then
run the same command:

```bash
npm ci
npx playwright install chromium
npm run audit:visual
```

The audit must be run from `frontend/`. It does not start the backend, use
Preview or production runtime, read `.env`, or access owner/provider data.

The repository root [README](../README.md) contains the full development and privacy notes.
