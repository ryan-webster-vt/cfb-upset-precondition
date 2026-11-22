# PROGRESS — CFB Upset Condition Profiler

**Persistent state for implementation.** Read `IMPLEMENTATION_PLAN.md` first; this file records
what is actually done, what is next, what is blocked, and why decisions were made.
**Plan version:** 1.3 (2026-11-22)
**Status:** `P1 COMPLETE` (2026-11-22) — the full contract catalogue, SQLite schema +
repositories, evidence snapshots, fixture-backed adapters, trace/budget, leakage policy, and
verification tests are implemented. `P0 COMPLETE` (2026-11-22) remains the baseline.
P1 gate: **301 passed · 9 skipped** in the canonical `ads_5984` env (Python 3.12.13,
`chromadb==1.1.1`); `ruff` + `black --check` clean; `store.db --init/--verify` → `status: OK`.
Capability matrix: **36 PASS · 1 PARTIAL · 5 SKIP · 0 FAIL**, regenerated during P0 in the same
env. Pre-flight and live capability capture are recorded in §5; generated evidence is in
`docs/CAPABILITIES.md`.
**Feature freeze:** 2026-12-01 · **Showcase:** 2026-12-03 17:00

> Plan-mode note: this file lives in `/home/ryanw07/.opencode/plan` because Plan mode restricts
> writes. Copy it to the repo root when implementation begins.

---

## 0. Operating rules for every session

1. Open this file first. Find **§3 Resume here**. Do not rely on conversational history.
2. Work only on the current phase. Do not start the next phase with the current one failing.
3. A task is checked only when its acceptance evidence is recorded in §7 Session log
   (command run + result).
4. Never edit `tests/`, fixtures, acceptance thresholds, or this file's gate criteria to make a
   run pass. If a threshold is wrong, raise it in §4 Decisions log and get sign-off.
5. Every deviation from `IMPLEMENTATION_PLAN.md` gets an `AD-###` entry **before** the code lands.
6. End each session: update checkboxes, session log, blockers, and Resume here.

**Status legend:** `[ ]` not started · `[~]` in progress · `[x]` done & verified · `[!]` blocked ·
`[-]` intentionally skipped (decision logged)

---

## 1. Phase status board

| Phase | Scope | Status | Gate evidence |
| --- | --- | --- | --- |
| P0 | Probe, scaffold, walking skeleton | `[x]` | capability matrix + fixture e2e |
| P1 | Contracts, SQLite, adapters, provenance | `[x]` | 0001 schema init/verify + 301 tests + adapter parity |
| P2 | Historical corpus ingestion | `[ ]` | ≥3k games (~700/season), 0 leaked fields, coverage report |
| P3 | Leakage-safe features, favourite, splits | `[ ]` | leakage audit + availability report |
| P4 | Precondition research + spec store | `[ ]` | ≥12 operational specs, 1 call/candidate |
| P5 | Deterministic labeler + screen | `[ ]` | full label table, identical hashes ×3 |
| P6 | Stats validation, audit, Chroma | `[ ]` | FDR table + promotions + precision/recall |
| P7 | Daily slate + monitor pipeline | `[ ]` | cached, parallel, cited run |
| P8 | Upset-Scorer + backtest harness | `[ ]` | model artifact + metrics on 2025 |
| P9 | Streamlit application | `[ ]` | AppTest e2e + offline demo |
| P10 | Evaluation + coverage reports | `[ ]` | `reports/eval_*/report.md` |
| P11 | Reliability hardening + UML + docs | `[ ]` | `make check` green, UML PDF |
| P12 | Freeze, rehearse, package, submit | `[ ]` | zip verified, offline demo <60s |

---

## 2. Current blockers

| ID | Blocker | Impact | Owner action | Status |
| --- | --- | --- | --- | --- |
| B1 | ~~`.env` empty; no VT ARC credentials~~ **Resolved 2026-11-22**: `.env` (untracked, git-ignored) now holds `OPEN_AI_API_KEY`, `OPEN_AI_ENDPOINT`, `OLLAMA_ENDPOINT`, `EMBED_MODEL`, `CFBD_API_KEY`; ARC `/models` and Ollama both return 200 | none for P0.1 | keep `.env` out of git; `Settings` accepts `OPEN_AI_API_KEY`/`OPEN_AI_ENDPOINT` as aliases | `[x]` |
| B2 | ~~`systemone` wire schema/auth not captured~~ **Resolved 2026-11-22**: contract captured for `noul`/`choice`/`score`; identical `noul` ×3 and long payload ×2 deterministic; 400/404/413/429 observed; near-8k input 200 with 6,091 tokens. Residual: live 503 queue-timeout not held (shared window) | P8 can proceed from the §4.9.1 contract and fixtures | P8.2b: exercise 503 retry/degrade with mock transport; one controlled live hold only if the window is idle | `[~]` |
| B3 | No MCP servers configured (Brave/Fetch/Deep Research); Brave endpoint exists but returns 422 without a key | R5/R12/R30 live paths blocked | decide endpoints; otherwise approve D2/D9 seeded fallbacks before P4 | `[!]` |
| B4 | ~~Embedding width/normalisation unknown~~ **Resolved 2026-11-22**: Ollama `qwen3-embedding:8b` = 4096-d/norm 1.0; ARC `Qwen3-Embedding-4B` = 2560-d/norm 1.0; batch 32 OK. `chromadb==1.1.1` is importable in the canonical `ads_5984` env (P0 rerun) | The embedding stack is verified; only the adapter code remains | P1.11: wrap Chroma with width/metadata assertions (no install needed) | `[x]` |
| B5 | Showcase night (2026-12-03) may have no FBS slate | live demo risk | approve D12 + pre-warm a real slate | `[~]` (planned) |
| B6 | ~~CFBD academic key present, but 2021 `spreadOpen` null rate and provider mix are unverified~~ **Resolved 2026-11-22**: 2021 week 1 has 353 lines, **268 (75.9%) `spreadOpen` null**, providers Bovada/Caesars/William Hill/consensus/numberfire/teamrankings; 2025 week 1 is 11.5% null. `/venues` has lat/lon 94.4%, dome 99.6%, elevation 44.4%, timezone 42.6% | The D4 strength-proxy fallback is mandatory for 2021 | P1.4 seeds venues with a CSV fallback for missing geo/altitude/tz | `[x]` |
| B7 | The ARC gateway exposes **no machine-readable schema**: `GET /api/v1/openapi.json` returns the Open WebUI HTML shell (HTTP 200, `text/html`); `/openapi.json` and `/docs` are 404 | Contract discovery costs live calls and cannot be automated from a spec | mitigated by the captured §4.9.1 fixture + golden responses; re-check after any gateway upgrade | `[x]` |

---

## 3. Resume here

**Next action:** start **P2.1** — build the `Data-Orchestrator` season/week enumeration and
`Historical-Stats Worker` summary path on the existing ESPN/CFBD adapters, repositories, and
leakage policy. Do not start P3 until the P2 corpus gate passes.

**P1 close-out facts to carry forward:**
- `python -m cfb_upset.store.db --init` applies `0001`; `--verify` prints every §4.7 table count
  and `status: OK`. All DB access goes through `cfb_upset.store.repositories`.
- `cfb_upset.adapters.transport.Transport` has `HttpTransport` (P0 retry/breaker) and
  `FixtureTransport` (offline replay). Every adapter test is fixture-backed; live tests live in
  `tests/live/` and skip unless `RUN_LIVE=1`.
- `domain.leakage` is the only admission gate: `admit` / `is_admitted` / `derive_known_at`.
  Strict comparison means a closing line stamped exactly at kickoff is excluded.
- Evidence snapshots are gzip + SHA-256 under `data/evidence/<hash>.txt.gz`; SQLite stores the
  hash and relative pointer and `EvidenceStore.verify` re-hashes the decompressed bytes.
- Chroma collections are tagged `{model, dim, instruction_template, normalized}` and every
  vector width is asserted; Chroma tests skip cleanly when `chromadb` is absent.
- Weather historical runs record a conservative lead upper bound (≤ `WEATHER_LEAD_HOURS_MAX`,
  hard-clamped to 6 h) because the stitched archive exposes no issue time (AD-032).
- `precondition_spec.rationale` is an additive column beyond the §4.7 list, so a `PreconditionSpec`
  round-trips without dropping its explanation (AD-031).

**P0 facts to carry forward:**
- The app runs fully offline from `cfb_upset.fixtures.demo`; `streamlit run app.py` → Analyze
  shows 2 ranked alerts and a 3-agent timeline.
- `systemone` is decision-only (`/chat/completions` → 404). Use `POST {base}/systemone`, keep the
  process semaphore at 4, and parse `answers.<name>.{noul|choice|score}`.
- `noul` is deterministic for an identical payload; it is **not** a validated upset model.
- Ollama `qwen3-embedding:8b` is the primary 4096-d space; never mix it with ARC 2560-d.
- Run everything with `conda activate ads_5984` (Python 3.12.13). The base env also runs the
  offline tests but lacks `chromadb`; use the course env for probes and the app. See
  `docs/ENVIRONMENT.md` and `make doctor`.
- `docs/CAPABILITIES.md` is the generated matrix; `docs/capabilities.json` is its machine view.
- `.env` is populated and git-ignored. Never print or commit it.

**Working state:** P1 code and tests are complete but not yet committed; P0 remains the last
committed baseline (`64de1e2` plus the environment-correction follow-up). `docs/contracts/` holds
34 exported schemas. `data/cfb.db` is created on demand; no corpus, real specs, or live research
provider exists yet. B3 (no MCP endpoint) still applies to live Deep Research; the seeded provider
is the offline path.

---

## 4. Decisions log (append-only)

| ID | Date | Decision | Rationale | Requirements affected | Approved by |
| --- | --- | --- | --- | --- | --- |
| AD-001 | 2026-11-22 | Plan produced; three pipelines, agents, and stores preserved from the design doc | Requirements are explicit about topology | all | pending |
| AD-002 | 2026-11-22 | Use plain `asyncio` orchestration, not a graph framework | Reliability, auditability, fewer dependencies; no requirement mandates a framework | R6, R22 | plan |
| AD-003 | 2026-11-22 | `d3_mini` is the primary scorer backend, reached via `POST /api/v1/systemone`; `calibrated_rules` is the deterministic baseline and outage/mismatch fallback (D1) | Owner confirmed decision models are API-only at `/api/v1/systemone`; R19 needs a consistency check and Pr10 needs a simple baseline | R14, R19, R25 | owner (endpoint) / plan (fallback) |
| AD-004 | 2026-11-22 | `ResearchProvider` adapter with seeded-literature fallback (D2) | No MCP configured; one pass per candidate preserved | R5, R26 | **needs sign-off if MCP absent** |
| AD-005 | 2026-11-22 | Weather from archived forecast, `known_at = kickoff − 24h` (D3) | ESPN has no weather; observed weather leaks | R10, R24 | plan |
| AD-006 | 2026-11-22 | Prefer open odds; fall back to strength proxy, record `favorite_source` (D4) | Open lines missing in sampled 2021; closing lines violate strict `<` | R10, R24, R25 | plan |
| AD-007 | 2026-11-22 | Four mandated table names kept; side tables added (D5) | Separates immutable candidates from active versions | R8, R15, R27 | plan |
| AD-008 | 2026-11-22 | R25 replay covers the structured path; evidence stage evaluated on a subset (D6) | Full web-evidence replay is not reproducible | R25 | plan |
| AD-009 | 2026-11-22 | Three promotion states incl. `provisional` (D7) | Prevents an empty product if FDR promotes nothing | R9, R29 | plan |
| AD-010 | 2026-11-22 | Blinded `Adjudicator` for label audits (D10) | Independent judge; avoids self-grading | R30 | plan |
| AD-011 | 2026-11-22 | Background-thread run controller for Streamlit (D11) | Streamlit reruns cancel async work | R1, R3 | plan |
| AD-012 | 2026-11-22 | Date selector + offline demo slate (D12) | Showcase-night slate risk | R11 (default unchanged) | plan |
| AD-013 | 2026-11-22 | Corpus extension to 2016–2020 disabled by default (D13) | Power vs. split cleanliness; keep mandated window | R25, R31 | open question |
| AD-014 | 2026-11-22 | Process-wide semaphore of 4 for `systemone`; one active analysis run per process; hard constant | Owner limits: 4 queued/running per user, fair-share scheduling; excess concurrency returns 429 | R1, R14, R19, R22 | plan |
| AD-015 | 2026-11-22 | R25 full replay uses `calibrated_rules`; `d3_mini` evaluated on a stratified 100–150-game 2025 sample (D14) | Shared 4-request service; thousands of historical decisions are neither fair nor necessary | R25 | plan |
| AD-016 | 2026-11-22 | Primary probability = calibrated `noul` `P(yes)`; 5-level `score` is a secondary signal; raw + calibrated values both stored (D15) | `noul` returns a probability directly; calibration on 2024 follows the provider's guidance to fit cutoffs empirically | R14, R19, R25 | plan (confirm field names in P0) |
| AD-017 | 2026-11-22 | Monitor worker confirm/drop uses one d3-mini `choice` question with `{confirmed, contradicted, insufficient}`; thresholds fitted on labelled audits | Distribution scoring is more repeatable than token sampling and reuses one API contract; `contradicted` preserves falsification framing | R12, R13, R19, R30 | plan |
| AD-018 | 2026-11-22 | R30's 50-pair labelled audit also sets `CONFIRM_THRESHOLD`, `DROP_THRESHOLD`, and the optional alert cutoff | Provider guidance: choose cutoffs from labelled examples rather than guessing | R19, R30 | plan |
| AD-019 | 2026-11-22 | Adjudicator uses a chat model from a different family than the monitor worker's decision model | Pr6: the judge must be separate from the author | R30 | plan |
| AD-020 | 2026-11-22 | Embeddings use `qwen3-embedding:8b` at `POST /api/v1/embeddings` with the VT ARC chat credential; the width is measured and pinned (`EMBED_DIM`), never inferred (catalogue says 2560, `:8b` is natively 4096); embeddings are citation-retrieval only, never chat/scoring | Endpoint owner-confirmed; the model card describes an instruction-aware, non-chat embedding model; measuring once prevents a corrupted Chroma collection and makes re-embedding caches invalidate deterministically | R8 | owner (endpoint/model id) / plan (dimension policy) — **provider superseded by AD-023; the measure-and-pin policy stands** |
| AD-021 | 2026-11-22 | Historical odds prefer CFBD `/lines` `spreadOpen`, then ESPN `open`, then strength proxy; CFBD `/venues` replaces the seeded stadium CSV (CSV kept as fallback); `favorite_source`, `line_provider`, `market_prob_source` recorded per game (D4/D17) | CFBD is the only free source with open lines and stadium coordinates across 2021–2025; ESPN alone has 2021 gaps; one favourite definition across seasons avoids feature drift | R10, R24, R25 | plan (owner to obtain academic key) |
| AD-022 | 2026-11-22 | Historical weather uses Open-Meteo Historical Forecast (GFS, 2021+) and records the **actual** effective lead (≤6 h), not a nominal 24 h; live weather uses the forecast API at fetch time; ERA5/reanalysis and CFBD observed weather are never admitted (D3) | The stitched archive has no 24 h lead; labelling it 24 h would be false provenance, while ERA5/observed data leaks post-kickoff conditions | R10, R24 | plan |
| AD-023 | 2026-11-22 | **Primary embedding provider is local Ollama `qwen3-embedding:8b`** (`http://localhost:11434/v1/embeddings`, **4096-d**, L2-normalised, keyless). VT ARC `Qwen3-Embedding-4B` (**2560-d**) is an optional secondary space; the hashing embedder is tests-only. `EMBED_BACKEND` selects exactly one space; each Chroma collection is tagged `{model, dim, instruction_template, normalized}` and the width is asserted on every response. Supersedes AD-020's provider. | Live probe: ARC serves only `Qwen3-Embedding-4B` (200) and 500s on the Ollama-style id; Ollama serves the design's named model at 4096-d. Ollama matches the docs, removes a credential/network dependency, and keeps the demo offline-capable via cached query embeddings. | R8 | owner (chose Ollama 8B 2026-11-22) |
| AD-024 | 2026-11-22 | **`systemone` contract captured and frozen** for P8: `POST {base}/systemone` with `{model, state, questions{<name>:{type,instructions,criteria}}}`, `questions` an object; responses `answers.<name>.{noul\|choice+probabilities+confidence\|score+legend+probabilities+confidence}` + `usage`. `decision.vllm-sr/d3-mini` is listed in `/models` but `/chat/completions` returns 404. Same request 3× → identical `noul`. | Removes the plan's largest schedule risk; P0.1 now verifies fixtures instead of discovering a schema. The gateway has no OpenAPI document (`/api/v1/openapi.json` is the Web UI HTML), so the fixture is the contract of record. | R14, R19 | plan |
| AD-025 | 2026-11-22 | `Settings` accepts the existing `.env` names as aliases: `OPEN_AI_API_KEY` → `VT_ARC_API_KEY`, `OPEN_AI_ENDPOINT` → `VT_ARC_BASE_URL`; canonical names are used everywhere else. `VT_ARC_DECISION_ENDPOINT` is **relative** (`/systemone`) because the base URL already ends in `/api/v1`. `.env` stays untracked and is never committed or printed. | The working credential file uses OpenAI-style names; renaming it risks breaking the user's other tooling. Relative endpoint paths prevent `/api/v1/api/v1` duplication. | R1, R22 | plan |
| AD-026 | 2026-11-22 | **P0.8 chosen backends recorded:** scorer = `d3_mini` via `POST /systemone` with `calibrated_rules` fallback (D1); research = `seeded_literature` until an MCP endpoint exists (D2); weather = Open-Meteo historical forecast with `WEATHER_LEAD_HOURS_MAX=6` and the measured lead recorded (D3); embeddings = Ollama `qwen3-embedding:8b`, `EMBED_BACKEND=ollama`, `EMBED_DIM=4096`, ARC 2560-d optional (D8); odds/venues = CFBD `/lines` + `/venues` primary, ESPN open + strength proxy fallback (D17); MCP = runtime HTTP adapters, no harness-level MCP (D9). | These are the backends that passed the live probe and have fixtures under `tests/fixtures/`; every choice names its fallback so an outage degrades rather than fails. | R5, R8, R10, R14, R19, R24, R25 | plan |
| AD-027 | 2026-11-22 | **The live 503 queue-timeout probe is skipped in P0.** A 5-way burst produced `429 user_concurrent` in two of three runs (the middle run accepted all five); a 4-held-request probe would occupy the shared window for up to 30 s. P0 records 503 as SKIP and P8.2b tests the `503`/`retry_after_s` retry-then-degrade path with a mock transport. The 4-request semaphore is a hard constant regardless. | The shared service is not a load-test target; the failure envelope is already documented and can be exercised deterministically offline. This avoids harming other users while preserving the P8 acceptance path. | R1, R14, R19, R22 | plan |
| AD-028 | 2026-11-22 | **P0 scorer is an explicit stub:** `probability = min(0.95, base_rate + 0.06 × matched_count)`, `confidence = min(0.90, 0.35 + 0.12 × matched_count)`, `model_version = "stub-p0-rule-count"`, backend recorded as `calibrated_rules`. The rationale says it is not a trained probability. P8 replaces the internals, not the `UpsetScore`/`RankedAlert` contract. | The walking skeleton needs a deterministic, testable score to prove the vertical slice; a train/validate claim without calibration would violate R19 and the project's provenance rules. | R14, R19 | plan |
| AD-029 | 2026-11-22 | **Probe and fixture redaction masks only exact secret keys and secret-shaped suffixes**, never usage counters. No `Authorization` header is written to any fixture; `docs/CAPABILITIES.md` and `docs/capabilities.json` carry status codes, counts, field names, widths, and model ids only. | The first redaction pass masked `input_tokens`/`output_tokens`, which destroys the P8 budget evidence. The corrected predicate keeps `input_tokens`/`output_tokens`/`token_ids` while masking `api_key`, `authorization`, `access_token`, `*_api_key`, and `*_secret`. A key scan over `docs/`, `tests/`, `cfb_upset/`, `scripts/`, and `README.md` found no credential. | R1, R22 | plan |
| AD-030 | 2026-11-22 | **Canonical development environment is the `ads_5984` conda env** (`/opt/anaconda3/envs/ads_5984/bin/python`, Python 3.12.13). It already contains `chromadb==1.1.1`, Streamlit 1.60, and every P0 dependency. The base Anaconda Python 3.13.5 also runs the offline tests but lacks `chromadb`; using it produced a false P0 FAIL. All final probe/test evidence is regenerated under `ads_5984`. | The Midterm project used the same env and `chromadb`; the P0 probe must inspect the interpreter that will run the app. Hard-coding an absolute path in `Makefile` would not travel, so the documented workflow is `conda activate ads_5984` before `make check`/`make probe`. | R1, R8, R22 | owner (env) / plan |
| AD-031 | 2026-11-22 | **Additive `precondition_spec.rationale` column.** The §4.7 table list is preserved; one nullable/defaulted text column is added so a `PreconditionSpec` stored and reloaded by `SpecsRepository` keeps its rationale. | `PreconditionSpec.rationale` is required by the P1 contract but absent from the §4.7 column list; dropping it on write would make the repository lossy and break a contract round-trip. | R8, R9, R27 | plan |
| AD-032 | 2026-11-22 | **Historical weather lead is recorded as an upper bound.** `WeatherAdapter.fetch_historical` sets `known_at = kickoff − lead_hours` with `lead_hours = min(requested, WEATHER_LEAD_HOURS_MAX, 6)`. The stitched Open-Meteo historical-forecast archive exposes no forecast issue time, so the adapter never claims a smaller lead than it can prove. Indoor venues short-circuit with `unavailable_reason` instead of inventing weather. | Preserves the AD-022 decision while making the provenance conservative: any admitted historical weather was knowable no later than the recorded `known_at`, and observed/reanalysis weather is never fetched. | R10, R24 | plan |
| AD-033 | 2026-11-22 | **Adapters depend on a tiny `Transport` protocol.** `HttpTransport` wraps the P0 `HttpClient` (timeouts, retries, breaker); `FixtureTransport` replays captured JSON/HTML and records calls, returning a synthetic 404 for unmatched routes. Tests never touch the network; `tests/live/` is opt-in via `RUN_LIVE=1`. | Fixture parity is an explicit P1 acceptance criterion. One transport seam keeps retry logic in one place and makes an adapter test fail at the parse boundary rather than hang. | R1, R22, R25 | plan |

---

## 5. Capability evidence (re-verify in P0)

| Capability | Observed 2026-11-22 | Consequence |
| --- | --- | --- |
| ESPN historical scoreboard | 200, 25–64 events, **no odds/weather** | odds via core endpoint; weather via D3 |
| ESPN future scoreboard | odds present (DraftKings) | daily slate favourite available pre-kickoff |
| ESPN core odds | spread + providers; `open` missing in sampled 2021 | D4 |
| ESPN summary | boxscore/venue/header; no weather | indoor/venue only from ESPN |
| ESPN groups | `80`=FBS, `81`=FCS | FBS filter is deterministic |
| ESPN venue geo | no lat/lon | CFBD `/venues` supplies them (CSV fallback) |
| Open-Meteo forecast archive | keyless, hourly, past dates; GFS from 2021-03-23; stitched lead ≤6 h; Previous Runs full variables only 2024+ | D3 revised: record actual lead |
| CFBD lines | `/lines` exposes `spreadOpen`/`overUnderOpen`/moneylines/provider; academic 3,000 calls/mo; **key present** | D4/D17 primary odds; P0.1 measures the 2021 null rate |
| CFBD venues | `/venues` exposes lat/lon/elevation/dome/timezone; **key present** | replaces seeded stadium CSV |
| VT ARC model list | 14 ids incl. `GLM-5.3`, `gpt-oss-120b`, `claude-on-arc`, `DeepSeek-V4.1-Flash`, `Qwen3-Embedding-4B`, `decision.vllm-sr/d3-mini` | `GET /api/v1/models` 200 with `OPEN_AI_API_KEY`; D1/D8 resolvable |
| VT ARC embeddings | `POST /api/v1/embeddings` `Qwen3-Embedding-4B` → 200, **2560-d**, norm 1.0; `qwen3-embedding:8b` → **500** | optional 2560-d space only (AD-023) |
| Local Ollama embeddings | `qwen3-embedding:8b` at `http://localhost:11434/v1/embeddings` → 200, **4096-d**, norm 1.0 | **primary** embedding space (AD-023) |
| VT ARC decision models | `POST /api/v1/systemone` `{model,state,questions{}}`; `noul`/`choice`/`score` all 200; deterministic ×3; `/chat/completions` → 404 | D1 primary path; contract captured (AD-024) |
| ARC schema discovery | `GET /api/v1/openapi.json` → **HTTP 200 `text/html`** (Open WebUI shell); `/openapi.json` and `/docs` → 404 | fixtures are the contract of record; no automated schema |
| `systemone` limits | 4 concurrent/user, 30 s queue, 8,192 input tokens, 8 MiB body, ≤8 images; 429/502/503 + `retry_after_s` | hard concurrency cap; D14 evaluation; budget fallback |
| `systemone` semantics | `decision.vllm-sr/d3-mini`; `noul`→P(yes), `choice`→option probabilities, `score`→0..n−1 weighted level + legend; confidence; 400 malformed; cost ∝ input × questions | scorer `probability`; monitor confirm/drop; thresholds from audits |
| MCP config | none; Brave endpoint exists but 422 without a key | D2/D9 |
| chromadb | **1.1.1 importable** in the canonical `ads_5984` env (Python 3.12.13); base Anaconda 3.13.5 lacks it | adapter in P1.11; no install needed |
| Consumer Windows PC / demo host | Ollama serves `qwen3-embedding:8b` locally; app health-checks it at startup | demo needs Ollama for fresh runs; caches cover offline |
| Python/toolchain | canonical `ads_5984`: Python 3.12.13, pydantic 2.12.5, streamlit 1.60.0, httpx 0.28.1, pytest 8.4.2, chromadb 1.1.1, ruff 0.17.2, black 25.12; base Anaconda is 3.13.5 and lacks chromadb; 2.8 TB free | use `conda activate ads_5984`; `make doctor` verifies |
| Secret hygiene | `.env` is git-ignored and untracked; no key appears in the repo | never print `Authorization`; redact fixtures |
| quarto/npx/pandoc | present; no LaTeX/Graphviz | UML PDF via Quarto/Typst |

**P0 re-verification (2026-11-22 20:29 UTC, then corrected in `ads_5984`):**
`python scripts/probe.py --write` produced **36 PASS · 1 PARTIAL · 5 SKIP · 0 FAIL** in
`docs/CAPABILITIES.md` / `docs/capabilities.json` when run with the canonical
`/opt/anaconda3/envs/ads_5984/bin/python` (Python 3.12.13). The PARTIAL is ARC 4B over-context
(HTTP 400; Ollama returns 200, likely truncating). The 5-way burst reproduced `429
user_concurrent` in two of three probes; the live 503 hold is still intentionally skipped
(AD-027). ESPN rankings use the site endpoint (`2` poll collections); ARC chat JSON mode returns
`{"ok": true}` with `finish_reason=stop` at `max_tokens=256`.

---

## 6. Phase checklists

### P0 — Probe, scaffold, walking skeleton
- [x] P0.1 `scripts/probe.py` + `docs/CAPABILITIES.md` (re-verify ESPN; ARC `/models`; ARC chat JSON-mode; **`systemone` golden fixtures for `noul`/`choice`/`score` + 400 + 404, 429/413/503 limit probes, long-payload determinism/latency**; **Ollama 4096-d and ARC 2560-d embeddings: batch cap, over-context behaviour, norm ≈ 1.0, instruction prefix**; **CFBD `/lines` 2021 `spreadOpen` null rate + `/venues` fields**; **Open-Meteo historical lead/coverage**; Brave/Fetch/Deep Research, `import chromadb`, disk; PASS/FAIL/SKIP + timestamp + redacted evidence)
- [x] P0.2 Repo scaffold: package tree, `requirements*.txt`, `.env.example`, `Makefile`, lint/test config, `.gitignore` additions
- [x] P0.3 `Settings`, logging, `Clock`, hashing, error taxonomy
- [x] P0.4 `adapters/http.py` (timeout, retry+jitter, circuit breaker) + unit tests
- [x] P0.5 Core contracts (`SlateGame`, `RuleSpec`, `PreconditionSpec`, `ScreenMatch`, `UpsetScore`, `RankedAlert`) + JSON Schema export
- [x] P0.6 Walking skeleton: fixture slate+specs → screen → stub score → Streamlit ranked table + in-memory timeline
- [x] P0.7 `AppTest` e2e for the skeleton
- [x] P0.8 Record chosen backends for D1/D2/D3/D8/D9 in AD log (D1/D8 already captured as AD-024/AD-023); confirm `EMBED_BACKEND=ollama`, `EMBED_DIM=4096`, and `WEATHER_LEAD_HOURS_MAX`
- [x] P0 GATE: capability matrix complete; `make test` green; no secrets; reproducibility check

### P1 — Foundations
- [x] P1.1 Full Pydantic contract catalogue, `extra="forbid"`, enums, timezone validators
- [x] P1.2 SQLite migrations implementing §4.7 (all tables + indexes)
- [x] P1.3 Repositories per aggregate; no raw SQL outside `store/`
- [x] P1.4 `teams`/`venues` seed from CFBD `/venues` (lat/lon/altitude/dome/tz) with a checked-in CSV fallback
- [x] P1.5 Evidence snapshot store (gzip + sha256) and `evidence_links`
- [x] P1.6 ESPN adapter (scoreboard, summary, core odds, rankings, groups) + CFBD adapter (`/lines`, `/venues`) with fixtures
- [x] P1.7 Weather + geocode adapters with fixtures (record actual forecast lead)
- [x] P1.8 Search + Fetch adapters: whitelist, text extraction, snapshot, mock transport
- [x] P1.9 Deep Research adapter (MCP JSON-RPC + seeded provider)
- [x] P1.10 LLM adapter: JSON-only, retries, token ledger, redaction
- [x] P1.11 Embeddings + Chroma adapters: Ollama `qwen3-embedding:8b` (4096, primary) and ARC `Qwen3-Embedding-4B` (2560, optional); hashing embedder for tests; assert width == `EMBED_DIM`; tag collection metadata `{model, dim, instruction_template, normalized}`; never mix spaces
- [x] P1.12 `trace.py` (JSONL + `agent_events`) and `budget.py`
- [x] P1.13 `domain/leakage.py` admission policy as data + violation logging
- [x] P1.14 Contract rejection + adapter parity tests
- [x] P1 GATE: migrations verified; adapters pass offline tests; leakage unit test raises — `301 passed, 9 skipped`; `ruff`/`black` clean; `0001` init/verify OK

### P2 — Historical corpus ingestion
- [ ] P2.1 FBS-vs-FBS enumeration via scoreboard + group 80
- [ ] P2.2 `Data-Orchestrator` batching/dedupe/aggregate/validate/store
- [ ] P2.3 `Historical-Stats Worker` per-game fetch → `HistoricalGameRecord` with `known_at`
- [ ] P2.4 Quarantine path (alt branch) with error details
- [ ] P2.5 Store `games`, `game_fields`, box scores marked post-game (never admitted)
- [ ] P2.6 Coverage report (season/week/team/field non-null %, favourite sources, unsupported fields)
- [ ] P2.7 Idempotent CLI with `--resume`; dedupe assertion
- [ ] P2.8 Parallelism timing check (1 vs 2 workers)
- [ ] P2 GATE: ≥3k games (≈700/season), dedupe, 0 leaked fields, coverage report, fault isolation test

### P3 — Features, favourite, splits
- [ ] P3.1 Rolling pre-game features (form, rest, travel, altitude, rank, look-ahead, pace…)
- [ ] P3.2 Odds: CFBD `spreadOpen` → ESPN `open` → strength proxy; implied probability (moneyline or fixed spread map); record `favorite_source`, `line_provider`, `market_prob_source`
- [ ] P3.3 Upset label + margin (evaluation only)
- [ ] P3.4 Chronological splits + hard assertions
- [ ] P3.5 `game_features` + `data/features_v1.parquet`
- [ ] P3.6 Feature availability + missing-data report
- [ ] P3.7 Leakage tests (sentinel + delete-after-cutoff recompute)
- [ ] P3 GATE: 0 leaked feature rows; splits disjoint; availability report

### P4 — Research + spec store
- [ ] P4.1 `configs/preconditions/candidates.yaml` (~20 candidates with briefs + citations)
- [ ] P4.2 `Research Worker` one call per candidate; LLM extraction with one repair attempt
- [ ] P4.3 Provider adapter modes recorded per report
- [ ] P4.4 Operationalizability gate (field/op/threshold/units/availability)
- [ ] P4.5 `precondition_spec` + `spec_store` versioning; rejection reasons logged
- [ ] P4.6 Canonical rule hash dedupe with merge log
- [ ] P4.7 CLI `build_preconditions --stage research`
- [ ] P4 GATE: ≥12 operational specs; exactly 1 research call/candidate; versioning intact

### P5 — Labeler + screen
- [ ] P5.1 Rule DSL registry with types/units and missing-value semantics
- [ ] P5.2 Evaluator returning state + evidence (`field`, observed, threshold, `known_at`)
- [ ] P5.3 `domain/labeler.py` writes `labeled_games` for every (game, active spec)
- [ ] P5.4 Leakage guard raises `LeakageError`
- [ ] P5.5 `domain/screen.py` shares evaluator with labeler
- [ ] P5.6 Canonical JSON evidence + golden hash determinism test
- [ ] P5.7 Label coverage report
- [ ] P5 GATE: row count = games × active specs; identical hashes ×3; zero exceptions

### P6 — Stats, audit, promotion, Chroma
- [ ] P6.1 RD + cluster-bootstrap CI; raw and adjusted OR; LR test
- [ ] P6.2 BH-FDR via statsmodels + cross-check
- [ ] P6.3 Per-split `stat_results` + stability check
- [ ] P6.4 Promotion engine (`validated|provisional|rejected`) with reasons
- [ ] P6.5 Label audit sample (n=50, stratified, seeded), whitelisted fetch, snapshots
- [ ] P6.6 Blinded `Adjudicator` (HOLD/NOT_HOLD/UNKNOWN + quote)
- [ ] P6.7 Precision/recall + Wilson CIs; precision<0.80 blocks validation
- [ ] P6.8 Single tuning round with `--approve` and before/after record
- [ ] P6.9 Embed accepted citations in the active Ollama space (`qwen3-embedding:8b`, 4096) and upsert with model/dim/instruction metadata; fail loudly rather than mixing spaces; top-3 retrieval check per spec
- [ ] P6 GATE: BH parity; null simulation controls FDP; planted effect promoted; report written

### P7 — Monitor pipeline
- [ ] P7.1 Slate reader (date, FBS filter, ESPN live odds, Open-Meteo live weather, explicit `unavailable`)
- [ ] P7.2 `Monitor-Orchestrator` load specs → screen → empty branch → partition → aggregate
- [ ] P7.3 `Monitor Worker` search/fetch/snapshot/anonymise + d3-mini `choice` confirm/drop with calibrated thresholds + dissent
- [ ] P7.4 Deterministic fallback with `LLM_MODE=off`
- [ ] P7.5 Rationale builder + citation verification
- [ ] P7.6 `analysis_cache` with versioned keys + replay
- [ ] P7.7 Failure isolation, budget exhaustion → `degraded`
- [ ] P7.8 CLI `run_monitor --date/--games/--offline`
- [ ] P7 GATE: 0 calls on empty slate; only selected games; 2 workers interleaved; cache byte-identical

### P8 — Scorer + backtest harness
- [ ] P8.1 `Upset-Scorer` agent + strict `UpsetScore` validation
- [ ] P8.2 `d3_mini` backend via `adapters/systemone.py` (captured contract, semaphore 4, local request validation, `noul`/`choice`/`score` builders, payload budgeter ≤8,192 tokens/8 MiB, raw+calibrated probability, retry matrix, snapshots, fallback)
- [ ] P8.2b Limit/contract tests: >4 in-flight → 429 path, 413 shrink-once, 503 retry-then-degrade, golden fixture parse
- [ ] P8.3 `calibrated_rules` backend (fit 2021–23, calibrate 2024, artifact + SHA)
- [ ] P8.4 Total-order ranking with tie-breaks
- [ ] P8.5 `pipelines/backtest.py`: 5 baselines, Brier, log loss, ECE, AUC, precision@k, bootstrap CIs, calibration plot; full replay on `calibrated_rules`; `d3_mini` on all 2024 (calibration) + 2025 (test) candidates, reduced-n fallback if saturated (D14)
- [ ] P8.6 `pipelines/repeatability.py`: Jaccard, Kendall τ, probability spread
- [ ] P8.7 Wire scorer into `RunResult`
- [ ] P8 GATE: ranks contiguous; backend recorded; baselines all present; no test-season leakage in fit

### P9 — Streamlit
- [ ] P9.1 Page shell + navigation
- [ ] P9.2 Slate page: date selector, logos/colors, sort/filter, multiselect (all default)
- [ ] P9.3 Run controller (thread + queue), live per-agent timeline, cancel, budget
- [ ] P9.4 Ranked alert cards: probability, confidence, specs+values, rationale, citation chips
- [ ] P9.5 Exact empty-state messages; degraded banner
- [ ] P9.6 Cache badge + force re-analyze
- [ ] P9.7 Audit page (runs, events, DB browser, evidence viewer, trace download)
- [ ] P9.8 Preconditions page (effects, CIs, q-values, citations, approval)
- [ ] P9.9 Evaluation page (metrics + calibration plot)
- [ ] P9.10 Demo offline mode + pre-warm script
- [ ] P9 GATE: AppTest e2e; 3 runs no state bleed; every score has citations; <2s cached

### P10 — Evaluation & reports
- [ ] P10.1 Full pipeline run on real data; record runtime/usage/cache stats
- [ ] P10.2 Precondition table (RD, CI, OR, p, q, status, reason)
- [ ] P10.3 System metrics for all 5 baselines + calibration plot + CIs
- [ ] P10.4 Coverage/missing-data report (field × season × team)
- [ ] P10.5 `docs/EVALUATION.md` summary + limitations (incl. D6 scope statement)
- [ ] P10.6 Independent hand-check of one season/spec
- [ ] P10 GATE: `make eval` reproducible to 1e-9; every spec accounted for; no silent exclusions

### P11 — Hardening + UML + docs
- [ ] P11.1 Fault-injection suite (timeouts, 429/500, malformed, empty, DNS, disk, DB lock, Chroma down, refusals, budget)
- [ ] P11.2 Leakage suite (ingestion, features, labeler, monitor payload, static score-column test)
- [ ] P11.3 Planted-defect detection suite (100% caught)
- [ ] P11.4 Repeatability wired into `make check`
- [ ] P11.5 `docs/uml/class.mmd` + `seq_phase{1,2,3}.mmd`; render `cfb_upset_uml.pdf`
- [ ] P11.6 `tests/test_docs_consistency.py` (agent classes, tables, env keys)
- [ ] P11.7 `docs/ARCHITECTURE.md` with measured parallelism, fault isolation, provenance walkthrough, ADRs
- [ ] P11.8 README rewrite + clean-venv verification
- [ ] P11.9 Lint/format/docstring/no-secrets sweep
- [ ] P11 GATE: `make check` green; UML PDF opens; fresh clone → offline demo <5 min

### P12 — Freeze, rehearse, submit
- [ ] P12.1 Tag `v1.0-demo`; code freeze 2026-12-01
- [ ] P12.2 `docs/DEMO_SCRIPT.md` + Q&A crib sheet
- [ ] P12.3 Pre-warm demo slate/specs/cache/evidence; verify offline <60s
- [ ] P12.4 Two rehearsals (online, network off)
- [ ] P12.5 `make package` zip (<25 MB, no `.env`, no data); verify contents
- [ ] P12.6 Submit zip + UML PDF before 2026-12-03 17:00
- [ ] P12 GATE: §8 checklist complete

---

## 7. Session log (append-only)

| # | Date | Phase | What was done | Commands / evidence | Next |
| --- | --- | --- | --- | --- | --- |
| 1 | 2026-11-22 | planning | Read all reference docs; probed ESPN, Open-Meteo, VT ARC models, MCP/embedding availability, toolchain; wrote plan | see `IMPLEMENTATION_PLAN.md` App. A | start P0.1 |
| 2 | 2026-11-22 | planning | Owner supplied VT ARC embedding capability; updated D8/D16, §4.9.2 envelope, probe scope, Chroma/cache versioning, and `EMBED_*` env schema; no code written | plan v1.1; provider-catalogue + model-card review | start P0.1 probe |
| 3 | 2026-11-22 | planning | Selected CFBD `/lines` + `/venues` for odds/geodata (D4/D17) and corrected weather provenance (D3: stitched archive, actual lead ≤6 h); updated probes, risk register, env schema, blockers | plan v1.2; CFBD tier docs + Open-Meteo coverage docs 2026-11-22 | obtain CFBD key; start P0.1 |
| 4 | 2026-11-22 | planning | **Pre-flight + live contract capture.** `.env` supplied and verified; ARC `/models` (14 ids), `systemone` `noul`/`choice`/`score` captured with fixtures, determinism ×3, `/chat/completions` 404; Ollama 4096-d + ARC 2560-d embeddings; CFBD/Open-Meteo reachable; ARC has no OpenAPI schema; Python/dep/disk inventory; chose Ollama 8B as primary embedder; updated F1/F3, D8/D16, §4.9.1/§4.9.2, P0.1/P1.11/P6.9, Appendix A/B, blockers, AD-023–AD-025 | commands/evidence in `IMPLEMENTATION_PLAN.md` App. A and §5 above; no code written | **switch agents**, then P0.1 |
| 5 | 2026-11-22 | P0 | **Phase 0 implemented and gated.** Scaffold, settings/logging/ids/errors, tolerant HTTP adapter, Pydantic contracts + 11 schemas, deterministic rule DSL/screen, explicit stub scorer + total ranking, in-memory trace, fixture slate, Streamlit skeleton, probe and docs. Fixed probe redaction (`input_tokens` preserved), ESPN rankings (site endpoint → 2 polls), ARC chat (`content=None` + 256-token reasoning budget). Added golden `systemone`/embedding/ESPN/CFBD/weather fixtures and a contract README. Wrote 152 offline tests incl. AppTest e2e. | `python scripts/probe.py --write` → **34 PASS / 2 PARTIAL / 5 SKIP / 1 FAIL (chromadb, P1.11)**; `make test-cov` → **152 passed**, `rules.py` 97%, `screen.py` 100%; `make lint` / `make schemas` green; AppTest → 2 alerts + 3 agents; 3-run deterministic payload hash `c2981f97…`; `git check-ignore .env` exit 0; credential scan clean | **start P1.1**, then P1.2 migrations; no P1 code yet |
| 6 | 2026-11-22 | P0 correction | **Environment correction.** `chromadb` was reported missing only because the probe ran in base Anaconda Python 3.13.5. The canonical `ads_5984` conda env already has `chromadb==1.1.1` (Python 3.12.13, Streamlit 1.60). Installed the missing dev formatter (`black 25.12`) in that env, regenerated the matrix there, and synced docs/requirements/AD-030. | `/opt/anaconda3/envs/ads_5984/bin/python scripts/probe.py --write` → **36 PASS / 1 PARTIAL / 5 SKIP / 0 FAIL**, incl. `chromadb import PASS` and a reproduced `429`; env pytest → **160 passed**; env ruff/black clean; env coverage `rules.py` 97%, `screen.py` 100% | commit correction; start P1.1 |
| 7 | 2026-11-22 | P1 | **Phase 1 implemented and gated.** Added the full contract catalogue (history/research/labels/tools + monitor/scoring extensions; 34 exported schemas); `0001_init.sql` for every §4.7 table/index plus `precondition_spec.rationale`; typed repositories; content-addressed gzip/SHA-256 evidence store; CFBD/ESPN venue and team seed with checked-in fallback CSV; leakage policy as data; fixture-backed ESPN/CFBD/weather/geocode/search/fetch/Deep Research/LLM/embeddings/Chroma adapters behind a `Transport` seam; JSONL + SQLite trace sinks and run budgets; contract-rejection, leakage, trace/budget, adapter, parity, and live-skipped tests. Fixed CFBD provider matching so `ESPN_BET` matches `ESPN Bet`. | `python -m pytest` → **301 passed, 9 skipped** (live suite); `ruff check` clean; `black --check` → 83 files unchanged; `python -m cfb_upset.store.db --init` → `applied migrations: 0001`, `--verify` → all table counts + `status: OK`; `python -m cfb_upset.contracts.export` → **34 schemas**; Chroma round-trip passes with the 256-d hashing embedder in `ads_5984` | commit P1; start P2.1 |

**Template**
```
### Session N — YYYY-MM-DD (phase)
Goal:
Done:
Evidence (command → result):
Tests:
Decisions / deviations:
Blockers:
Next:
```

---

## 8. Final completion checklist

- [ ] P0–P12 gates all pass
- [ ] `make check` green (lint, tests, leakage, repeatability)
- [ ] `systemone` concurrency never exceeds 4 (enforced + tested); 400/413/429/503 paths verified
- [ ] `noul`/`choice`/`score` golden fixtures parse; malformed criteria rejected before a network call
- [ ] `make eval` reproducible; `reports/eval_*/report.md` complete
- [ ] `make demo-offline` < 60s with ≥2 citations
- [ ] Four mandated SQLite tables populated; Chroma collection tagged with `{model, dim, instruction_template, normalized}`; `len(v) == EMBED_DIM` asserted on every response; retrieval verified
- [ ] Embedding space is never mixed: Ollama 4096-d collections are never queried with the 2560-d ARC model, and a backend switch requires a re-index
- [ ] Every scored game records `favorite_source`, `line_provider`, `market_prob_source`; weather rows record the actual forecast lead
- [ ] Real slate → ranked alerts in UI with visible agent activity; rerun consistent + cached
- [ ] UML class + sequence PDF consistent with code (test-enforced)
- [ ] README reproducible on clean venv; `.env` absent; `.env.example` complete
- [ ] Submission zip < 25 MB verified; Canvas upload done
