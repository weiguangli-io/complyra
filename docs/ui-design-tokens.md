# UI Design Tokens Specification

Token source of truth for `comlyra/web/src/styles.css`.

## Usage Rules

- Prefer CSS custom properties under `:root`.
- Add new token only when existing token cannot represent the new use case.
- Never hardcode colors in component markup.

## Typography Tokens

- `--font-body`: primary reading font
- `--font-display`: headline/metric font

Recommended scale:
- Body small: `12px`
- Body: `14px`
- Body large: `15px`
- Heading section: `19px`-`21px`
- Hero heading: `clamp(27px, 3.1vw, 46px)`

## Color Tokens

Surface/background:
- `--bg-1`, `--bg-2`
- `--panel`, `--panel-strong`

Text:
- `--ink`
- `--ink-soft`

Interactive:
- `--mint`, `--mint-strong`
- semantic chips: `.status-good`, `.status-warn`, `.status-neutral`, `.status-muted`

Borders and elevation:
- `--border`
- `--shadow-1`, `--shadow-2`

## Spacing and Radius

Spacing rhythm:
- Container gaps: `14px`, `16px`, `22px`
- Control gaps: `6px`-`10px`
- Panel padding: `16px`-`30px`

Corner radius:
- Primary panels: `20px`-`22px`
- Sub-cards: `12px`-`16px`
- Pills/chips: `999px`

## Motion

- Entry animation: `fade-up`
- Duration: `0.35s`-`0.5s`
- Use only transform/opacity transitions for performance

## Accessibility Constraints

- Maintain WCAG AA contrast for text and key controls.
- Ensure focus states are visible and tokenized (no default outline suppression without replacement).
- Keep minimum touch target ~40px for key actions.

## Change Management

When introducing token changes:
1. Update token definitions in CSS.
2. Update this spec if semantics change.
3. Run Playwright E2E + axe to detect regressions.
