# Plan: Learn page, favicon, scroll animations, skeletons, Vercel redeploy

Status: **planned, not started** (2026-11-24).

## On "continue"

1. Work on branch **`vercel-deploy`**, not `main`. This branch has public mode (visitors supply their own API keys), security headers, visitor-key tests and react-router 7. `main` has none of these.
2. Clone or fetch through the personal SSH host: `git@github-personal:Aakif9866/AI-Engineering-Lab.git`. Commit as `Aakif9866`.
3. Run steps 1–7 below in order. Commit on `vercel-deploy` and push it. Merging into `main` waits until the owner asks.
4. Leave `main` alone for now. It has one stray commit, `84cd090`, which adds a weaker duplicate of this branch's Vercel config plus an older copy of this plan. Resolve it only when the owner decides how to merge (revert it, or reset `main` to `6f54d0e`).

## Vercel deployments to delete and replace

There are currently **two** live Vercel projects for this app. Delete both, then replace them with **one main deployment** under the project name `ai-engineering-lab`.

| Project | URL | Deployed | Notes |
|---|---|---|---|
| `ai-engineering-lab` | https://ai-engineering-lab-flax.vercel.app | 2026-11-01 | Old deploy of this branch (`vercel-deploy`) from Nov 1. |
| `repo` | https://repo-one-sable.vercel.app | 2026-11-24 | Throwaway test deploy of `main`. |

Delete commands (both approved by the owner):

```
vercel project rm repo --confirm-name repo
vercel project rm ai-engineering-lab --confirm-name ai-engineering-lab
```

The replacement goes up in step 6 and becomes the only deployment.

## Context

AI Engineering Lab is a React/Vite frontend plus a FastAPI backend with 7 LLM design-pattern workspaces. The goals:

1. A new lab-wide **Learn** page in the sidebar, right below Overview, covering project structure, the application, and high-level design. It stays at the architecture and use-case level, never code level, and leans heavily on real-life applications.
2. A favicon.
3. Scroll-reveal animations and a loading skeleton for every page, plus smoother animations overall.
4. A full check, a fresh Vercel deploy, deletion of the 2 old projects, and a push to a branch with a PR.

Decisions already made:
- Build on the `vercel-deploy` branch.
- Add only the new Learn page. The per-workspace Learn tabs stay as they are.
- Deploy with this branch's existing Vercel config. Don't replace it.
  - `vercel.json`: `framework: null`, frontend built to `frontend/dist`, `/api/*` → `api/index.py`, plus security headers.
  - `api/index.py`, a core-deps-only `requirements.txt` (no torch), and `.vercelignore`.
- **CSP caveat:** the strict CSP in `vercel.json` pins the sha256 of the inline theme script in `frontend/index.html`. Don't edit that script. If it must change, update the hash. Adding `<link rel="icon">` and `<meta>` tags is safe, and so are inline `style` attributes from React; check the browser console for CSP violations after deploying anyway.
- The Learn page's "Design decisions" section should also explain public mode: visitor-supplied keys, no prompt text stored, and shared state that resets.

## 1. Learn page (`frontend/src/pages/Learn.tsx`, new)
- Route `/learn` in `frontend/src/App.tsx`. A NavLink "Learn" goes directly under "Overview" in the `nav` block of `frontend/src/components/Layout.tsx`, styled like the Overview link.
- Layout: a sticky in-page table of contents on `lg+`, with the sections stacked. Reuse `.card`, `Badge`, `Link`, and `ProjectIcon` and the `PROJECTS` list from `frontend/src/projects.ts`, so pattern names, icons and hues stay consistent.
- Sections, in order:
  1. **What this application is**: the gap between an LLM demo and a production feature, and how the lab gives one workspace to each of the 7 things that fill that gap. Includes the quality vs cost/risk axes.
  2. **One real product, end to end**: the centrepiece. A running story follows a SaaS customer-support assistant ("a customer asks about a refund"). It walks one request through cache check → input guardrails → hybrid retrieval with citations → model call → output checks and approval → trace → thumbs-down and correction → curated dataset → fine-tune and release gate → agent eval regression. Each step names and links the workspace that demonstrates it.
  3. **Real-world use cases per pattern**: one block for each of the 7 patterns, with 3–4 concrete industry scenarios (banking, healthcare, legal, e-commerce, insurance, devtools, public services). Each block covers what breaks without the pattern, the metric that matters, and the workspace's own scenario, taken from the `pdf` and `problem` fields.
  4. **High-level design**: an inline SVG diagram drawn with Tailwind colour classes so it works in both light and dark mode. It shows Browser UI → `/api` → FastAPI with 7 routers → shared core (providers, tracing and redaction, SQLite, embeddings, jobs) → committed fixtures, runtime state, and the external LLMs (DeepSeek, Groq), with short notes on each box's responsibility.
  5. **Lifecycle of a request**: a numbered flow plus the span tree it produces. Every module wraps its work in spans, which is why TraceLens sees everything.
  6. **Project structure**: an annotated folder tree with each folder's purpose, not code: `frontend/`, `backend/lab/core`, `p01`–`p07`, `backend/data`, `backend/var`, `docs/`, `mini_rag/` (read its README before describing it).
  7. **How the patterns connect**: the data flywheel (feedback → dataset → fine-tune → frozen eval → release gate), traces → eval replay, and caching and guardrails in front of every model call.
  8. **Design decisions and trade-offs**: why there's no vector DB, no LangChain, no Redis, and why the app runs offline first (from the README Architecture section), plus the local vs Vercel differences (no torch on Vercel, so it uses the hash embedder; `/tmp` state is ephemeral).
  9. **How to study it**: the ordered workspace path, self-check questions and the interview drill, condensed from `docs/LEARNING_PATH.md`.
- All content lives as typed constants at the top of `Learn.tsx`, with no new libraries.

## 2. Favicon
- New file `frontend/public/favicon.svg`: a mark in the brand's indigo→purple→pink gradient, with the signature opposite-rounded-corner square and a simple pulse/node glyph.
- `frontend/index.html` gets `<link rel="icon" type="image/svg+xml" href="/favicon.svg">` and a `<meta name="theme-color">`. The current `/favicon.ico` requests 404.

## 3. Smoother animations and scroll reveal
- `frontend/tailwind.config.js`: change the `rise` keyframe to 12px → 0 using opacity and transform only, timed at `600ms cubic-bezier(0.22,1,0.36,1)`. Add `fade` for tab panels and `shimmer` for skeletons, and a shared `transitionTimingFunction.smooth` with the same curve.
- New `Reveal` component in `frontend/src/components/ui.tsx`. A single shared IntersectionObserver adds an `is-visible` class once, and the reveal itself is pure CSS (`.reveal` / `.reveal.is-visible` in `index.css`). Under `prefers-reduced-motion` or when IntersectionObserver is missing, content renders visible with no transition.
- Apply it once where it reaches every page: `Card` (ui.tsx), the `.card` blocks in `Workspace` (Layout.tsx), the Overview sections and the Learn sections. Delays are staggered by index.
- Polish:
  - The `Tabs` underline becomes a single indicator that slides between tabs, and the active panel fades in.
  - The mobile nav drawer slides in with a fading backdrop.
  - Overview card hover uses `transition-[transform,box-shadow,border-color] duration-300 ease-smooth`.
  - `html { scroll-behavior: smooth }` applies only when the user hasn't asked for reduced motion.

## 4. Skeletons for every page
- `Skeleton` primitive in `ui.tsx`: a shimmer block, `aria-hidden`, plus a `role="status"` "Loading" label for screen readers.
- Page-shaped skeletons: `OverviewSkeleton` (hero plus a 7-card grid), `WorkspaceSkeleton` (icon, title, tab bar, two-column cards) and `LearnSkeleton` (table of contents plus text blocks).
- Route-level: convert the page imports in `App.tsx` to `React.lazy`, each with a `<Suspense>` fallback set to its matching skeleton. The skeleton shows while the page chunk loads, and splitting the code shrinks the first load.
- Data-level: wherever a page shows a bare `Spinner` or `Empty` for an initial GET (`!data` / `loading` from `useApi` in `frontend/src/api.ts`), swap in a sized `Skeleton`. Spinners stay only on user-triggered action buttons (Run, Ask, Ingest). Representative spots: `CacheCraft.tsx` sweep and experiments, `EvidenceAtlas.tsx` experiments, `MissionReplay.tsx` scenario card, and the Overview activity line. Grep every `useApi` use.

## 5. Check
- `cd frontend && npm ci && npm run build` (tsc plus vite) must pass.
- Backend: `cd backend && uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -r requirements.txt && .venv/bin/python -m pytest`. Core deps only, so report any ML-test skips.
- Run `vite preview` and check all 9 routes, including `/learn` and a 404, in a browser. Confirm:
  - the skeletons appear
  - the scroll reveal and tab slide work
  - the favicon shows
  - light and dark mode both look right
  - the 375px mobile width has no horizontal scroll
  - the console has no errors

## 6. Deploy and clean up Vercel
- Delete both old projects (commands above) and confirm with `vercel project ls`.
- Remove `.vercel/`, run `vercel link --yes --project ai-engineering-lab`, then run `vercel deploy --prod --yes`.
- Smoke test the production URL: `/`, `/learn`, `/evidence-atlas`, `/favicon.svg`, `/api/status` and `/api/cache/kb` should all return 200, and the deployment logs should show no function errors.

## 7. Git
- Commit on `vercel-deploy` and push it. Open a PR into `main` only when the owner asks (and handle the stray `84cd090` on `main` first).

## Critical files
- New: `frontend/src/pages/Learn.tsx`, `frontend/public/favicon.svg`
- Edit: `frontend/src/App.tsx`, `frontend/src/components/Layout.tsx`, `frontend/src/components/ui.tsx`, `frontend/src/index.css`, `frontend/tailwind.config.js`, `frontend/index.html`, `frontend/src/pages/*.tsx` (skeleton swaps only)
- Already present: `vercel.json`, `api/index.py`, `requirements.txt`, `.vercelignore`
