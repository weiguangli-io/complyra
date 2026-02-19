# complyra-web

Frontend console for `Complyra`.

## Features

- Governed AI workbench (ingest + ask + approval result refresh)
- Approval queue and decision actions
- Audit trail table
- Admin tenant/user management panel
- Runtime i18n (`en` / `zh`)
- Keyboard/ARIA accessibility baseline
- Playwright E2E + axe accessibility audit

## Run

```bash
npm install
cp .env.example .env
npm run dev
```

Default URL: [http://127.0.0.1:4173](http://127.0.0.1:4173)

## Build

```bash
npm run build
npm run preview -- --host 127.0.0.1 --port 4173
```

## E2E + A11y Audit

```bash
npm run test:e2e
```

## Environment

- `VITE_API_BASE`: backend API base URL, defaults to `http://localhost:8000/api`.
