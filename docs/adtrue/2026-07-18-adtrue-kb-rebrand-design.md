# AdTrue KB — Rebrand & Deploy Design (2026-07-18)

## Goal

Light-touch rebrand of the WeKnora fork as **AdTrue KB**, deployed at
https://kb.adtrue.io (OVH2, `/opt/weknora`), with CI/CD auto-deploy.
Keep the diff vs `upstream/main` (Tencent/WeKnora) minimal so upstream
updates merge cleanly.

## Branching model

- `main` — mirrors upstream, never carries AdTrue commits.
- `adtrue-brand` — deploy branch; all branding + CI commits live here.
- Upstream update: `git fetch upstream && git merge upstream/main` into
  `adtrue-brand` (or rebase), resolve small conflicts, push → auto-deploy.

## Changes (all under `frontend/` unless noted)

| Touchpoint | Change |
|---|---|
| `index.html` | Title/meta → "AdTrue KB", English description |
| `src/i18n/index.ts` | Default locale `zh-CN` → `en-US` |
| Locale files (×4) | Only the 6 high-visibility product-name strings per locale (welcome, onboarding, login, chat title) → "AdTrue KB". **Not** renamed: "WeKnora Cloud" (Tencent service), technical identifiers (`X-WeKnora-Signature`, `aud=weknora`), localStorage keys |
| `src/assets/img/weknora.png` | Bytes replaced with AdTrue wordmark (dark text + red dot, from adtrue.com; dark mode auto-inverts via existing CSS filter) |
| `public/favicon.ico` | AdTrue "a" icon |
| `src/assets/theme/brand-adtrue.css` (new) | Overrides TDesign `--td-brand-color-1..10` green ramp with AdTrue red `#fc4d59` ramp, light + dark. Imported after `theme.css` in `main.ts` / `embed-main.ts` |
| `src/views/auth/Login.vue` | Header logo link → adtrue.com |
| `.github/workflows/deploy-adtrue.yml` (new) | Auto-deploy, see below |

## Deployment

- Stack: docker compose at `/opt/weknora` on OVH2, `.env` pins backend
  images to upstream `v0.7.0`; only the **frontend** image is built from
  source (`Dockerfile` copies prebuilt `dist/`).
- Host nginx vhost `kb.adtrue.io` → 127.0.0.1:8085 (frontend container,
  which proxies `/api/` → app:8080). TLS terminated at Cloudflare.

## CI/CD

Push to `adtrue-brand` → GitHub Actions (`deploy-adtrue.yml`) SSHes into
OVH2 (secrets `OVH2_HOST/USER/PORT/SSH_KEY`, dedicated deploy key):
`git reset --hard origin/adtrue-brand` → build `dist` in a `node:22`
container (as uid ubuntu) → `docker compose build frontend && up -d
frontend` → curl smoke check. Mirrors `ads-op-internal/deploy.yml`.

Upstream workflows only trigger on `main`/tags/PRs, so they stay inert
on this branch.
