# Frontend Contributing Guide

This guide defines the baseline engineering bar for `comlyra/web`.

## Scope

- App stack: React + TypeScript + Vite
- Feature areas: auth session, governed chat, approval queue, audit table, admin console
- Quality gates: build, Playwright E2E, accessibility audit

## Local Setup

```bash
cd /Users/liweiguang/aiagent/complyra/web
npm install
cp .env.example .env
npm run dev
```

Default URL: `http://127.0.0.1:4173`

## Required Commands Before PR

```bash
npm run build
npm run test:e2e
```

`test:e2e` includes:
- login flow
- ask/response flow
- admin page flow
- axe accessibility audit (serious/critical violations must be zero)

## Code Standards

- Use strict TypeScript and explicit domain types from `src/types.ts`.
- Keep API access in `src/api.ts`; avoid inline `fetch` inside UI components.
- Add stable `data-testid` for core workflow elements.
- Keep component behavior deterministic; avoid hidden implicit global state.

## I18n Policy

- All user-facing UI copy should be translatable.
- Add keys in `src/i18n.ts` for both `en` and `zh`.
- Do not hardcode user-visible English in component render paths.

## Accessibility Policy

Minimum requirements for each PR touching UI:
- Keyboard access for main workflow (login, navigation tabs, primary actions)
- Proper form labeling (`label` + `htmlFor`)
- Landmark usage (`header`, `main`, `footer`) and skip link support
- Live region for async status feedback (`aria-live="polite"`)
- No serious/critical axe violations in E2E

## Testing Guidelines

- Prefer route-mocked Playwright tests for deterministic CI.
- For new workflows, add one successful path and one failure/permission path.
- Keep selectors semantic (`role`) first, `data-testid` second.

## Review Checklist

- [ ] UI copy exists in both English and Chinese
- [ ] Keyboard-only flow works for the updated area
- [ ] `npm run build` passes
- [ ] `npm run test:e2e` passes
- [ ] No new design token drift (see `docs/ui-design-tokens.md`)
