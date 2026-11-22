# PROGRESS — CFB Upset Condition Profiler

**Persistent state for implementation.** Read `IMPLEMENTATION_PLAN.md` first; this file records
what is actually done, what is next, what is blocked, and why decisions were made.
**Plan version:** 1.2 (2026-11-22)
**Status:** `P0 NOT STARTED` — no application code exists yet (design-only repo).
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
| P0 | Probe, scaffold, walking skeleton | `[ ]` | capability matrix + fixture e2e |
| P1 | Contracts, SQLite, adapters, provenance | `[ ]` | migrations + contract tests |
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
| B1 | `.env` is empty; no VT ARC / Brave / Deep Research credentials present | P0 probe will SKIP live checks; P4/P7 live modes unavailable | obtain keys; run `python scripts/probe.py --live` | `[!]` |
| B2 | `systemone` wire schema/auth not yet captured (semantics + limits confirmed: `d3-mini`, `noul`/`choice`/`score`, 4 concurrent, 30 s queue, 8,192 tokens, 8 MiB) | P8 cannot start without golden fixtures; scoring throughput is capped at 4 | P0.1: capture field names + golden responses for all three question types, 400/429/413/503 probes, determinism/latency | `[~]` |
| B3 | No MCP servers configured (Brave/Fetch/Deep Research) | R5/R12/R30 live paths blocked | decide endpoints; otherwise approve D2/D9 | `[!]` |
| B4 | Embedding endpoint known (`POST /api/v1/embeddings`, same VT ARC key/base, model id `qwen3-embedding:8b`) but the returned width, batch cap, overflow behaviour, and normalisation are unverified; `chromadb` not installed | Cannot create the Chroma collection with a safe dimension | P0.1: capture wire fixture, **measure `EMBED_DIM`** (catalogue says 2560, `:8b` is natively 4096), test batch/overflow/norm/instruction prefix; add `chromadb` in P1 | `[~]` |
| B5 | Showcase night (2026-12-03) may have no FBS slate | live demo risk | approve D12 + pre-warm a real slate | `[~]` (planned) |
| B6 | No CFBD academic API key; 2021 `spreadOpen` null rate and provider mix unverified | Odds coverage falls back to ESPN + strength proxy; venue lat/lon falls back to CSV | register .edu key (3,000 calls/mo); P0.1 CFBD probe | `[!]` |

---

## 3. Resume here

**Next action:** execute **P0.1** — write `scripts/probe.py`, run it, and commit
`docs/CAPABILITIES.md`. Then **P0.2** scaffold, **P0.5** walking skeleton.

**Do not start** P1 until the capability matrix records a chosen backend for:
scorer (D1: `systemone` contract captured + fixture), research provider (D2), weather (D3:
`WEATHER_LEAD_HOURS_MAX` recorded), embeddings (D8: `EMBED_DIM` measured + golden fixture), odds/venues
(D17: CFBD key probed, or ESPN+proxy approved), and MCP transport (D9).

**Working state:** no DB, no corpus, no specs, no UI. Fresh start.

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
| AD-020 | 2026-11-22 | Embeddings use `qwen3-embedding:8b` at `POST /api/v1/embeddings` with the VT ARC chat credential; the width is measured and pinned (`EMBED_DIM`), never inferred (catalogue says 2560, `:8b` is natively 4096); embeddings are citation-retrieval only, never chat/scoring | Endpoint owner-confirmed; the model card describes an instruction-aware, non-chat embedding model; measuring once prevents a corrupted Chroma collection and makes re-embedding caches invalidate deterministically | R8 | owner (endpoint/model id) / plan (dimension policy) |
| AD-021 | 2026-11-22 | Historical odds prefer CFBD `/lines` `spreadOpen`, then ESPN `open`, then strength proxy; CFBD `/venues` replaces the seeded stadium CSV (CSV kept as fallback); `favorite_source`, `line_provider`, `market_prob_source` recorded per game (D4/D17) | CFBD is the only free source with open lines and stadium coordinates across 2021–2025; ESPN alone has 2021 gaps; one favourite definition across seasons avoids feature drift | R10, R24, R25 | plan (owner to obtain academic key) |
| AD-022 | 2026-11-22 | Historical weather uses Open-Meteo Historical Forecast (GFS, 2021+) and records the **actual** effective lead (≤6 h), not a nominal 24 h; live weather uses the forecast API at fetch time; ERA5/reanalysis and CFBD observed weather are never admitted (D3) | The stitched archive has no 24 h lead; labelling it 24 h would be false provenance, while ERA5/observed data leaks post-kickoff conditions | R10, R24 | plan |

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
| CFBD lines | `/lines` exposes `spreadOpen`/`overUnderOpen`/moneylines/provider; academic 3,000 calls/mo | D4/D17 primary odds; probe 2021 |
| CFBD venues | `/venues` exposes lat/lon/elevation/dome/timezone | replaces seeded stadium CSV |
| VT ARC model list | 4 chat models, no decision/embedding model listed (both served outside `/v1/models`) | D8 risk removed; probe the contract |
| VT ARC embeddings | owner-confirmed 2026-11-22: `POST /api/v1/embeddings`, model id `qwen3-embedding:8b`, same key/base as chat; catalogue says 2560-d, 8,192-token inputs, instruction-aware, not chat-capable | D8 primary path; measure `EMBED_DIM` in P0.1 |
| VT ARC decision models | `POST /api/v1/systemone` (API only; owner-confirmed); schema pending P0 probe | D1 primary path; capture contract |
| `systemone` limits | 4 concurrent/user, 30 s queue, 8,192 input tokens, 8 MiB body, ≤8 images; 429/502/503 + `retry_after_s` | hard concurrency cap; D14 evaluation; budget fallback |
| `systemone` semantics | `decision.vllm-sr/d3-mini`; `noul`→P(yes), `choice`→option probabilities, `score`→0..n−1 weighted level; confidence; 400 malformed; cost ∝ input × questions | scorer `probability`; monitor confirm/drop; thresholds from audits |
| MCP config | none | D2/D9 |
| chromadb | not installed; PyPI reachable | add dependency in P1 |
| quarto/npx/pandoc | present; no LaTeX/Graphviz | UML PDF via Quarto/Typst |

---

## 6. Phase checklists

### P0 — Probe, scaffold, walking skeleton
- [ ] P0.1 `scripts/probe.py` + `docs/CAPABILITIES.md` (ESPN, VT ARC models/chat, **`POST /api/v1/systemone` field names + `noul`/`choice`/`score` golden fixtures, 400/429/413/503 probes, determinism/latency**, **`POST /api/v1/embeddings`: auth, request/response fixture, measured `EMBED_DIM`, batch cap, 8,192-token overflow, L2 norm, instruction-prefix effect, 429/latency**, **CFBD `/lines` 2021 `spreadOpen` null rate + `/venues` fields**, **Open-Meteo historical lead/coverage**, Brave/Fetch/Deep Research, chromadb, disk)
- [ ] P0.2 Repo scaffold: package tree, `requirements*.txt`, `.env.example`, `Makefile`, lint/test config, `.gitignore` additions
- [ ] P0.3 `Settings`, logging, `Clock`, hashing, error taxonomy
- [ ] P0.4 `adapters/http.py` (timeout, retry+jitter, circuit breaker) + unit tests
- [ ] P0.5 Core contracts (`SlateGame`, `RuleSpec`, `PreconditionSpec`, `ScreenMatch`, `UpsetScore`, `RankedAlert`) + JSON Schema export
- [ ] P0.6 Walking skeleton: fixture slate+specs → screen → stub score → Streamlit ranked table + in-memory timeline
- [ ] P0.7 `AppTest` e2e for the skeleton
- [ ] P0.8 Record chosen backends for D1/D2/D3/D8/D9 in AD log, including the measured `EMBED_DIM`
- [ ] P0 GATE: capability matrix complete; `make test` green; no secrets; reproducibility check

### P1 — Foundations
- [ ] P1.1 Full Pydantic contract catalogue, `extra="forbid"`, enums, timezone validators
- [ ] P1.2 SQLite migrations implementing §4.7 (all tables + indexes)
- [ ] P1.3 Repositories per aggregate; no raw SQL outside `store/`
- [ ] P1.4 `teams`/`venues` seed from CFBD `/venues` (lat/lon/altitude/dome/tz) with a checked-in CSV fallback
- [ ] P1.5 Evidence snapshot store (gzip + sha256) and `evidence_links`
- [ ] P1.6 ESPN adapter (scoreboard, summary, core odds, rankings, groups) + CFBD adapter (`/lines`, `/venues`) with fixtures
- [ ] P1.7 Weather + geocode adapters with fixtures (record actual forecast lead)
- [ ] P1.8 Search + Fetch adapters: whitelist, text extraction, snapshot, mock transport
- [ ] P1.9 Deep Research adapter (MCP JSON-RPC + seeded provider)
- [ ] P1.10 LLM adapter: JSON-only, retries, token ledger, redaction
- [ ] P1.11 Embeddings + Chroma adapters with fallback embedder; assert width == `EMBED_DIM`; tag collection metadata `{model, dim, instruction_template, normalized}`; never mix embedding spaces
- [ ] P1.12 `trace.py` (JSONL + `agent_events`) and `budget.py`
- [ ] P1.13 `domain/leakage.py` admission policy as data + violation logging
- [ ] P1.14 Contract rejection + adapter parity tests
- [ ] P1 GATE: migrations verified; adapters pass offline tests; leakage unit test raises

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
- [ ] P6.9 Embed accepted citations with the real embedder → Chroma (hashing fallback only on endpoint failure, disclosed); top-3 retrieval check
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
- [ ] Four mandated SQLite tables populated; Chroma collection tagged with model/dim/instruction version; `EMBED_DIM` asserted on every response; retrieval verified
- [ ] Every scored game records `favorite_source`, `line_provider`, `market_prob_source`; weather rows record the actual forecast lead
- [ ] Real slate → ranked alerts in UI with visible agent activity; rerun consistent + cached
- [ ] UML class + sequence PDF consistent with code (test-enforced)
- [ ] README reproducible on clean venv; `.env` absent; `.env.example` complete
- [ ] Submission zip < 25 MB verified; Canvas upload done
