# Sofa Prompt Workbench — Agent Implementation Rules

## Source of truth
- `sofa_prompt_workbench_development_spec_v1_reliable_cn.md` is the authoritative product and architecture specification.
- Read it fully before implementing. Where older examples conflict with its reliability amendment, follow the amendment and invariant sections.
- User-facing UI, errors, README, deployment docs, and API docs use Simplified Chinese.

## Delivery scope
Implement a production-capable V1, not a visual prototype. Required boundaries include:
- Vue 3 + TypeScript + Vite frontend; Element Plus; AG Grid Community; Vue Query; Pinia.
- FastAPI + Pydantic v2 + SQLAlchemy 2 + Alembic backend.
- File-backed SQLite in WAL mode; Redis + RQ with persistent Outbox/Intent dispatch.
- OneImg backend-proxy upload contract and OpenAI-compatible multimodal provider.
- Immutable job snapshots, row revision/fingerprint CAS, stale-result protection, attempts, six-module results, positive/negative prompts, review, version history, selected/latest separation.
- SSE invalidation with polling fallback, auth/CSRF/rate limits/SSRF controls, backup/restore, recycle bin, Docker Compose/Nginx, tests.

## Engineering rules
- Strict TDD for each behavior: write a focused failing test, run it and confirm expected failure, implement minimum code, rerun focused and broader gates.
- Work in vertical slices. Keep the application runnable after each milestone.
- No secrets or real credentials. Do not read `.env`; create placeholder-only `.env.example`.
- Do not commit or push unless explicitly asked.
- Keep functions and modules focused; no god files or drive-by refactors.
- External network calls must be outside SQLite write transactions.
- Never make Redis the sole source of durable job intent.
- Never let an old job update current row pointers when `row_revision` or `input_fingerprint` changed.
- Vision observations only contain directly visible facts. Unknown/off-frame facts remain empty/null. Use a neutral vision fallback, never an opinionated demo preset.
- Provider parsing tolerates wrappers/fences/content parts and then applies strict canonical schemas.

## Canonical gates
Backend:
- `uv sync --project backend --extra dev`
- `uv run --project backend ruff check .`
- `uv run --project backend mypy app`
- `uv run --project backend pytest -q`

Frontend:
- `npm --prefix frontend ci`
- `npm --prefix frontend run lint`
- `npm --prefix frontend run typecheck`
- `npm --prefix frontend run test -- --run`
- `npm --prefix frontend run build`

E2E and containers:
- `npm --prefix e2e ci`
- `npm --prefix e2e run test`
- `docker compose config`
- `docker compose build`

If Docker/Redis are unavailable on the current host, keep compose/tests complete, run all locally available gates, and report the environmental blocker honestly.
