# IMPLEMENTATION PLAN — NCAA D-I FBS Upset Condition Profiler

**Project:** 34.4.13 Sports: Upset Condition Profiler (ADS 5984, Agentic AI in Practice)
**Repo:** `cfb-upset-precondition`
**Plan version:** 1.3 — 2026-11-22
**Revision history:** 1.0 initial plan · 1.1 embedding provider/space policy · 1.2 CFBD odds/venues
+ weather provenance · 1.3 captured `systemone` contract, measured embedding widths, Ollama 8B as
primary embedder (AD-023/AD-024/AD-025 in `PROGRESS.md`).
**Target events:** feature freeze **Tue 2026-12-01**, Agentic AI Showcase **Thu 2026-12-03 17:00–19:00**, Canvas submission at showcase start.

> **Plan-mode note.** This document was produced in OpenCode Plan mode, which restricts writes to
> `/home/ryanw07/.opencode/plan`. When the plan is approved, copy `IMPLEMENTATION_PLAN.md` and
> `PROGRESS.md` to the repository root unchanged. No application code has been written.

---

## 0. How to use this document

1. Read §1–§4 once, end to end. They contain every decision that later phases depend on.
2. Execute phases **in order** (`P0` … `P12`). Each phase section is self-contained: objective,
   prerequisites, tasks, files, deliverables, acceptance criteria, tests, and requirement coverage.
3. `PROGRESS.md` is the live state. Update it at the start and end of every work session and after
   every phase gate. If this plan and `PROGRESS.md` disagree, **stop and reconcile** — do not guess.
4. Never mark a phase complete with a failing test, a stubbed acceptance criterion, or an
   unrecorded deviation. Deviations go in `PROGRESS.md` → "Decisions log" before code lands.
5. Anything labelled **[GATE]** requires either a green acceptance check or explicit human sign-off.

---

## 1. Executive summary

### 1.1 What is being built

A multi-agent system that (a) ingests historical FBS-vs-FBS games, (b) discovers candidate
pre-kickoff "upset preconditions" from literature and converts them into deterministic rules,
(c) validates those rules statistically on held-out seasons, and (d) each day screens a live slate
against validated rules, confirms or drops flags with cited web evidence, and ranks games by upset
risk in a Streamlit UI that shows agent activity.

Three pipelines, preserved from the design document:

| Pipeline | Cadence | Owner agents |
| --- | --- | --- |
| Structured corpus ingestion | one-time / on demand | `Data-Orchestrator` + 2 `Historical-Stats Workers` |
| Precondition discovery & validation | one-time / on demand | `Research-Orchestrator` + 2 `Research Workers` + labeler + stats |
| Daily monitoring & ranking | per user run | `Monitor-Orchestrator` + 2 `Monitor Workers` + `Upset-Scorer` |

### 1.2 MVP definition (the vertical slice that must exist by end of Day 3)

A single command starts Streamlit; the app shows a real slate from ESPN; the user clicks
**Analyze**; the app runs a **deterministic rule screen** using at least three preconditions loaded
from SQLite; a stub-but-real `Upset-Scorer` produces probabilities and a 1..n ranking; the result
renders with a per-agent activity timeline and at least one citation. No LLM is required for this
slice. Every later phase replaces a simplified component without changing the interfaces.

### 1.3 Timeline reality

Eleven calendar days remain. Full scope (§9) is an estimated **15–17 person-days**. That is only
achievable because (a) phases are executed by an autonomous coding agent that can run long
sessions, and (b) evaluation and UML generation are built early as **living artifacts** and run in
the background. The plan therefore has a hard **scope ladder** (§10.3) and an early demoable slice.
If schedule pressure appears, cut from the bottom of the ladder — never from reliability, leakage
control, or deliverable artifacts.

### 1.4 Non-negotiable engineering rules

These apply to every phase and are enforced by tests:

1. **Deterministic core.** Rules, labels, screening, statistics, caching keys, and final scores are
   pure functions of stored inputs. LLM text may explain, never decide, where a deterministic
   check exists.
2. **No post-kickoff data.** Every stored field carries `known_at`; the admission rule is
   `known_at < kickoff_time`. Violations are dropped, not "fixed" by an LLM.
3. **Provenance or it did not happen.** Every claim shown to the user links to an `evidence_id`
   with URL, publication time, fetch time, and content hash.
4. **Contracts at every handoff.** All inter-agent payloads are Pydantic models; invalid payloads
   are rejected with a reason and never coerced silently.
5. **Bounded work.** Every run has a wall-clock budget, per-provider concurrency, max retries,
   max pages fetched, and max tokens. Exhaustion produces a partial result marked `degraded`.
6. **Fail isolated, never crash.** Provider failures degrade the run with visible status.
7. **Tests are the verifier.** Agents may not edit `tests/`, fixtures, or acceptance thresholds to
   make a run pass.

---

## 2. Source documents and precedence

| Document | Role |
| --- | --- |
| `reference_documents/final_project_specifications.md` | Course spec, required showcase sections, rubric, submission mechanics |
| `reference_documents/final_project_reqs_and_arch.qmd` | Requirements R1–R32, LLM/RAG issues, architecture, actors, phase sequence diagrams, mitigations |
| `reference_documents/ten_principles_for_reliable_multi_agent_systems.md` | Reliability doctrine (referenced as **Pr1–Pr10**) |
| `README.md` | Author's consolidated design restatement (already in repo) |
| `other_media/showcase_summary.md` | Personas and interaction summary; used for demo narrative |

**Precedence when documents conflict:** course spec (grading/deliverables) → numbered requirements
R1–R32 → architecture diagrams → README prose → this plan's proposals. Conflicts are itemised in
§4.2 and resolved by deviations in §4.3; nothing is changed silently.

---

## 3. Requirements analysis

### 3.1 Functional and non-functional requirements (original numbers preserved)

Legend: **Type** F = functional, N = non-functional/reliability. **Phase** = where it is first
satisfied. **Verification** = the objective check that it works.

| # | Requirement (condensed; see source for full text) | Type | Phase | Verification |
|---|---|---|---|---|
| R1 | Usable, responsive Streamlit UI that exposes the solution and shows agent activity | F | P0/P9 | `AppTest` e2e: slate, Analyze, ranked results, agent timeline rendered |
| R2 | Sort/filter today's games; select games for analysis | F | P7/P9 | UI test: filter by team/rank/odds; selection persisted into run request |
| R3 | Rerun process any number of times with any game combination | F | P9/P7 | e2e: 3 consecutive runs, different subsets, no state leakage |
| R4 | Orchestrator-worker historical ingestion; `Data-Orchestrator` + two workers batch ESPN API | F | P2 | Integration: ≥2 batches, 2 workers, dedupe by `game_id`, persisted rows |
| R5 | Research workers use Deep Research; Monitor workers use Brave + Fetch | F | P4/P7 | Adapter tests + live smoke; provenance shows provider per evidence item |
| R6 | Parallelize orchestrator work to cut latency | N | P2/P4/P7 | Timing test: 2 workers < 1.5× single-worker wall clock on fixed batch |
| R7 | Research-Orchestrator aggregates findings; enforces and validates Pydantic JSON | F | P4 | Unit: invalid/partial reports rejected with reason, valid ones aggregated |
| R8 | SQLite stores corpus, specs, `labeled_games`, `validated_preconditions`; ChromaDB holds accepted citations | F | P1/P6 | Schema test + Chroma round-trip with measured `EMBED_DIM`; retrieval returns stored chunk |
| R9 | Deterministic labeler + statistical tools decide which researched preconditions are real signal | F | P5/P6 | Planted-signal corpus: known effect discovered; noise rejected |
| R10 | Batch pipeline for the day's slate from ESPN (and CFBD for lines/venues): FBS-vs-FBS only, teams, location, stats, weather, odds/favorite | F | P3/P7 | Fixture + live test: FCS filtered out; all six field groups present or explicitly `unavailable` |
| R11 | Retrieve daily matchups for Monitor-Orchestrator and the UI slate | F | P7 | Integration: UI and orchestrator consume the same `SlateGame` records |
| R12 | Monitor-Orchestrator assigns only selected games to parallel workers; Brave+Fetch confirm/drop + citations; return confirmed flags | F | P7 | Integration with mocked search: only selected games processed; flags carry evidence |
| R13 | Rationale for every confirmed flag | F | P7 | Contract test: every `ConfirmedFlag` has non-empty rationale + ≥1 evidence ref |
| R14 | Upset-Scorer consumes Monitor output and uses VT ARC d3-mini to score/rank | F | P8 | `noul` answer → calibrated probability on 2024; `score` answer recorded; contract tests; fallback documented |
| R15 | Research pipeline writes `precondition_spec`, `spec_store`, `labeled_games`, `validated_preconditions` | F | P1/P4/P5/P6 | Table existence + row counts after Phase-2 build |
| R16 | Well-structured code with descriptive comments and run instructions | N | all/P12 | Ruff/format clean, docstrings on public modules, README run-through on clean venv |
| R17 | Two Monitor Workers run in parallel | F | P7 | Concurrency test asserts two distinct worker ids interleaved |
| R18 | Cited rationale/evidence + decision-model score shown together | F | P8/P9 | UI snapshot contains score, rationale, and clickable citations |
| R19 | High reliability; repeated ranking of same matchups is materially consistent | N | P8/P11 | Repeatability harness: 5 runs, Jaccard ≥ 0.9, Kendall τ ≥ 0.8, prob SD ≤ 0.03 |
| R20 | Use `.env` out of Git; `.env.example` boilerplate | N | P0/P12 | `.gitignore` check; `git check-ignore .env`; no secrets in example |
| R21 | Standardized JSON via Pydantic to prevent broken handoffs | N | P1 | Contract tests for every model; rejection path tested |
| R22 | Handle API failures, LLM timeouts, MCP failures without crashing | N | P1/P11 | Fault-injection suite: timeout/429/500/malformed/empty → degraded result |
| R23 | Cache already-analyzed matchups | F | P7/P9 | Second identical run: cache hit, no provider calls, same result |
| R24 | No post-kickoff data influences label, spec, or score; filter `known_at < kickoff_time` | N | P1/P3/P5/P11 | Leakage suite: injected sentinel post-kickoff field changes nothing |
| R25 | Validate scorer probabilities: 2021–23 train, 2024 val, 2025 test | F | P8/P10 | `reports/eval_*/metrics.json` with Brier, log loss, calibration, baselines |
| R26 | Deep Research once per precondition candidate, not per game | F | P4 | Test: 20 candidates → ≤20 research calls regardless of corpus size |
| R27 | Store `PreconditionSpec` (rule, required fields, thresholds) with versioning in SQLite | F | P4 | Version increment test; superseded versions retained and immutable |
| R28 | Deterministic labeler applied to every spec/game pair, emits `labeled_games` with evidence trails | F | P5 | Determinism test: identical output hash across 3 runs |
| R29 | Deterministic screening of the slate; only matches get web research | F | P7 | Test: zero-match slate triggers zero search/fetch calls |
| R30 | Sample fixed number of labeled games; use Brave+Fetch for precision/recall | F | P6 | Audit report with precision, recall, CIs, adjudication counts |
| R31 | FDR-corrected statistical testing on out-of-sample observations | F | P6 | BH q-values verified against `statsmodels`; null simulation false-positive rate ≤ α |
| R32 | Non-null percentages for every field, team, and attribute | F | P2/P10 | `coverage_report` artifact: per-column, per-season, per-team null rates |

### 3.2 Course deliverables (rubric-aligned)

| Deliverable | Rubric weight | Where satisfied |
| --- | --- | --- |
| Problem definition & motivation | 100 | `README.md` (exists), `docs/DEMO_SCRIPT.md` narrative |
| Multi-agent design justification | 150 | `docs/ARCHITECTURE.md` with measured parallelism/fault-isolation evidence |
| UML class diagrams | 100 | `docs/uml/class.mmd` + PDF; consistency test against code |
| Sequence diagram(s) | 100 | `docs/uml/seq_phase{1,2,3}.mmd` (from design doc) + PDF |
| Functional multi-agent solution | 200 | Phases P2–P8, e2e test |
| Streamlit front-end | 100 | Phase P9 |
| Code quality & in-line comments | 100 | Cross-cutting standards §7, docstring coverage |
| Showcase demo | 75 | `docs/DEMO_SCRIPT.md`, offline demo mode, rehearsal P12 |
| Q&A / depth of understanding | 75 | `docs/ARCHITECTURE.md` decision records + `PROGRESS.md` decisions log |
| `.zip` source + README + UML PDF | required | `make package` in P12 |

### 3.3 Mandatory vs. proposed implementation choices

**Mandatory (from requirements/spec):** three pipelines; named agents and orchestrator/worker
topology; Streamlit; SQLite tables and ChromaDB; Pydantic; deterministic labeler and rule screen;
FDR + out-of-sample stats; chronological 2021–23/2024/2025 splits; Brier/log loss/calibration;
`known_at < kickoff_time`; `.env.example`; UML class + sequence diagrams; tests; caching; fault
tolerance; repeatability.

**Proposed by this plan (not mandated):** plain-`asyncio` orchestration instead of a graph
framework; rule DSL design; specific statistical estimators and thresholds; the deterministic
scorer fallback; the seed literature catalog; open-meteo weather; the blinded adjudicator; the
`provisional` promotion tier; repository layout. Each is justified in §4.3 or §5.

---

## 4. Architecture assessment

### 4.1 As documented

**Agents.** `Data-Orchestrator` → 2 `Historical-Stats Workers`; `Research-Orchestrator` → 2
`Research Workers`; `Monitor-Orchestrator` → 2 `Monitor Workers`; `Upset-Scorer` (leaf). Workers
talk only to their orchestrator; orchestrators are the validation and persistence boundary.

**Deterministic collaborators.** `Pydantic Validator`, `Spec Store`, `Deterministic Labeler`,
`Deterministic Rule Screen`, `Statistical Validation Tools`, `Cache`, `qwen3-embedding:8b`
(local Ollama `POST /v1/embeddings`; ARC `Qwen3-Embedding-4B` is the optional 2560-d space; see
D8/D16 and §4.9.2).

**Tools.** ESPN API (historical + daily slate + odds), Deep Research MCP, Brave Search MCP,
Fetch MCP, VT ARC d3-mini.

**Stores.** SQLite (`precondition_spec`, `spec_store`, `labeled_games`, `validated_preconditions`,
plus corpus), ChromaDB (accepted citations).

**Interactions.** Phase 1 loop/par fan-out then validate/store or quarantine. Phase 2 loop/par
research, schema gate, label, test, `opt` re-label on tuning, embed citations. Phase 3 per-run
loop with deterministic screen, `par` monitor workers, `alt` empty/confirmed branches, cache write.

### 4.2 Findings: contradictions, gaps, ambiguities, and feasibility issues

| ID | Finding | Evidence | Consequence if unaddressed |
|---|---|---|---|
| F1 | **d3-mini is a decision model with its own API surface.** It now appears in `/v1/models`, but `POST /v1/chat/completions` returns 404: *"d3 is a decision model and cannot chat or complete text: use POST /v1/systemone with a state and questions"*. The wire contract is captured in §4.9.1 (`{model, state, questions{name:{type,instructions,criteria}}}` → `answers{name:{…}}`). Residual unknowns are the 429/503 envelopes and determinism on long monitor payloads. | live probe 2026-11-22: `noul`/`choice`/`score` all HTTP 200; identical `noul` request 3× → identical `0.0210483384072851` | R14 is unblocked; P0.1 now confirms a captured fixture instead of discovering a schema; R19's consistency check moves to long payloads |
| F2 | **No MCP servers or provider credentials are configured** in the environment (no Brave/Deep Research/Fetch endpoints; no env keys). | `~/.config/opencode/opencode.json`, `env` scan | R5/R12/R30 blocked; app cannot be demoed or tested deterministically |
| F3 | **Embeddings split across two providers.** Local Ollama serves `qwen3-embedding:8b` at `http://localhost:11434/v1/embeddings` → 200, **4096-d, L2-normalised**; the VT ARC gateway serves `Qwen3-Embedding-4B` at `/api/v1/embeddings` → 200, **2560-d, L2-normalised**, and rejects the Ollama-style id `qwen3-embedding:8b` with **500**. `chromadb` is not installed. | live probes 2026-11-22 (`/v1/models`, Ollama `/api/tags`, both embeddings endpoints) | R8 is unblocked; the primary and fallback are different vector spaces and must never share a Chroma collection |
| F4 | **ESPN historical scoreboards contain no odds and no weather.** Odds exist only in the per-event `core` odds endpoint; `open` lines are present for 2023+ but absent in sampled 2021 games. CFBD `/lines` exposes `spreadOpen`/`overUnderOpen` with a provider for the mandated seasons on the free academic tier (3,000 calls/mo, ~75 calls for five seasons), and `/venues` supplies lat/lon/elevation/dome/timezone that ESPN omits. | probes of `20210904`, `20231118`, `20251115`, `20241109`; core odds for `401281942`, `401628543`; CFBD API docs 2026-11-22 | R10 "weather, betting odds" is not satisfiable from ESPN alone; CFBD is the preferred odds/venue source with ESPN as fallback, and the 2021 open-line null rate must be probed |
| F5 | **Weather post-kickoff observations leak.** Any historical weather source keyed by game time is, by construction, known after kickoff. | by definition | R24 violation if raw observed weather is admitted |
| F6 | **ESPN season-level team statistics are end-of-season.** Using them to describe an in-season game leaks the future. | endpoint semantics | Silent leakage into almost every feature if used naively |
| F7 | **R15's four tables overlap conceptually**: `precondition_spec` and `spec_store` are not distinguished anywhere. | R8, R15, R27 | Schema churn late in the project; ambiguous R27 "versioning" |
| F8 | **R25 implies replaying the full Phase-3 system on 2021–2025, including web research.** Archived pages, fetch budgets, and prompt versions make exact replay expensive and partly impossible. | R25 + Phase-3 design | Either the evaluation is faked (unacceptable) or the claim is overstated |
| F9 | **R25's splits and R31's out-of-sample requirement can conflict with Phase-2 tuning.** Rules are tuned on a spot-check sample, then tested; if tuning uses test seasons the evaluation is contaminated. | R25, R30, R31 | Inflated metrics; a grader question the project cannot answer |
| F10 | **Precondition power is likely low.** ≈3,000–3,700 FBS-vs-FBS games over 2021–2025 (≈700/season), ~20–25% upset base rate, ~20 candidate specs, small effects. FDR may promote very few or none. | arithmetic + design | If zero specs validate, production emits no alerts and the demo is empty |
| F11 | **Two workers are mandated by name** (R4, R17) but R6 asks to parallelize everything. Hard-coding 2 is arbitrary. | R4/R6/R17 | Minor; resolve with configurable count defaulting to 2 |
| F12 | **Streamlit is not an async runtime.** Long fan-out runs inside a script rerun will be cancelled or block the UI. | framework behavior | Broken progress display and duplicate runs |
| F13 | **`report_time` cannot be trusted from HTTP.** Pages published before kickoff may be edited after it; not all sites expose publication metadata. | R24 + web reality | Leakage through fetched evidence |
| F14 | **The showcase date may have no FBS slate.** 2026-12-03 is a Thursday; the FBS calendar may be dark or thin that night. | schedule arithmetic | Live demo failure |
| F15 | **The course spec requires a *PDF* of UML**, but Graphviz and LaTeX are absent; Quarto, Node, and Pandoc are present. | tool probe | Last-minute deliverable scramble |

### 4.3 Proposed deviations (explicit, justified, requirement impact)

> Each deviation keeps the documented agent roles and topology. None removes a required artifact.
> Deviations D1–D4 are **capability-conditional**: implement the documented path when the provider
> exists, and the fallback otherwise. Both paths must be selectable by config and must be visible
> in the UI/README.

| ID | Deviation | Justification | Requirement impact |
| --- | --- | --- | --- |
| **D1** | `Upset-Scorer` uses an adapter with two backends: `d3_mini` via `POST /api/v1/systemone` (primary) and `calibrated_rules` (deterministic logistic/Platt scorer over market probability, matched-rule indicators, strength/rest/travel features). The agent still owns scoring, ranking, and rationale. | F1: d3-mini exists but on a separate API surface, so its contract must be isolated; the deterministic backend is the mandated simple baseline (Pr10) and the outage/mismatch fallback. | R14 satisfied through `systemone`; R19 checked on both backends; fallback used only on contract failure or timeout, and recorded. |
| **D2** | `Deep Research` is accessed through a `ResearchProvider` adapter: `mcp_deep_research` when configured, else `seeded_literature` (a versioned YAML catalog of ~20 preconditions with public citations) plus optional LLM normalisation. Source is stored per spec and surfaced in the UI. | F2; R26 (one pass per candidate) is preserved either way. A seeded catalog is cheaper, auditable, and deterministic. | R5 satisfied when the MCP is configured; otherwise degraded and labelled. R7/R26/R27 unaffected. |
| **D3** | Weather comes from the **Open-Meteo Historical Forecast API** (GFS `gfs_seamless`, archived from 2021-03-23) joined on venue coordinates. That archive is a stitched series with an **effective lead ≤ 6 h**, so `weather_source` and `weather_lead_hours` are recorded and `known_at` is derived from the model cadence — never labelled 24 h. The live slate uses the standard Open-Meteo forecast API at fetch time (`known_at = fetched_at`). IEM archived MOS (MAV/MET, station-based, ~2003+) is an optional strict-24 h robustness check. Observed/reanalysis weather (ERA5) and CFBD "Weather Data" are never admitted. If a spec requires weather, that spec is only promoted when weather coverage is adequate. | F4/F5; the historical-forecast archive is the only keyless source with all variables across 2021–2025, and its real lead must be stated honestly; ERA5/observed data leaks post-kickoff conditions. | R10 gains a real weather field; **R24 preserved** (post-kickoff weather never admitted); provenance is accurate rather than nominal. |
| **D4** | Odds: **CFBD `/lines`** `spreadOpen`/`overUnderOpen` (multi-provider) is primary for 2021–2025; ESPN core-odds `open` is the fallback; a pre-game strength proxy (rolling point differential / Elo) is last. Provider precedence is configurable and recorded per game as `line_provider`; `favorite_source ∈ {cfbd_open, espn_open, strength_proxy}` and `market_prob_source ∈ {moneyline, spread_mapped}` are stored. Closing lines are stored but `known_at = kickoff`, so the strict filter excludes them. | F4; strict `known_at < kickoff` cannot admit closing lines, R10 needs a favorite, and ESPN alone has 2021 gaps. One definition across seasons avoids feature drift. | R10 satisfied with explicit provenance; R24 fully preserved. R25 baseline uses the same favorite definition. |
| **D5** | Tables (names preserved): `precondition_spec` = immutable research report + proposed rule (raw candidates, all versions); `spec_store` = active-spec registry (`spec_id`, `version`, `is_active`, `promoted_at`); plus side tables `label_audits`, `stat_results`, `evidence`, `evidence_links`, `analysis_runs`, `analysis_cache`, `agent_events`, `game_fields`, `quarantine`. | F7; separates immutable history from mutable state, which R27's versioning needs. | R8/R15/R27 clarified; no table removed. |
| **D6** | R25 evaluation replays the **structured-feature path** of the system (screen → scorer) for all games; the evidence-confirmation stage is evaluated separately on a subset with archived evidence. The report states both numbers and never claims the full pipeline was replayed. | F8/F9; honest and reproducible. The conservative claim is defensible at Q&A and is stronger than an inflated synthetic number. | R25 partially satisfied by construction; report contains Brier/log loss/calibration on 2025 for the shipped scorer. |
| **D7** | Promotion has three states — `validated`, `provisional`, `rejected` — and the rule screen uses `validated`; if fewer than three specs validate, it uses the strongest `provisional` specs with a visible banner and a `provisional` flag on every alert. | F10; otherwise the product can legitimately produce no output. Thresholds stay pre-registered. | R9/R29 preserved; UI and README disclose status. |
| **D8** | Embeddings: **local Ollama `qwen3-embedding:8b`** via `POST http://localhost:11434/v1/embeddings` is primary (**4096-d**, L2-normalised, keyless, offline-capable). VT ARC `Qwen3-Embedding-4B` is an optional secondary space (**2560-d**); a deterministic hashing embedder exists for tests only. One Chroma collection per embedding space; the active width is pinned and asserted. If the embedder is unavailable at query time, retrieval degrades to each spec's direct citations and the run is flagged — a collection is never queried with a different model. | F3; Ollama removes the network/credential dependency and matches the design's named `qwen3-embedding:8b`; the ARC space keeps a portable option for a grading machine without Ollama. | R8 satisfied; the offline demo needs only cached query embeddings; no mixed-space risk. |
| **D9** | "MCP tools" are implemented as **runtime tool adapters** (HTTP JSON-RPC/MCP client with mock transport), not as OpenCode-host MCP servers. Workers call these adapters; tests use recorded fixtures. | F2; the application must run standalone (`streamlit run app.py`) and be testable offline. Harness-level MCP would make grading and CI depend on the developer's editor. | R5/R12 satisfied at the tool-contract level; the MCP transport is preserved. |
| **D10** | Add a blinded `Adjudicator` (separate model, fresh context, no access to worker reasoning) for R30 label audits. The `Research-Orchestrator` still computes precision/recall and owns the tuning gate. | Pr3/Pr6/Pr7; a worker grading its own labels is exactly the failure mode the doctrine warns about. | R30 strengthened; "orchestrator computes" preserved. |
| **D11** | UI runs orchestration in a background thread with an event queue (`agent_events`), polled by a Streamlit fragment; runs are cancellable and resumable from cache. | F12. | R1/R3 satisfied without duplicated runs. |
| **D12** | UI adds a **date selector** (default: today) and a pre-warmed offline demo slate. | F14. | R11 unaffected (today is the default); demo risk removed. |
| **D13** | Corpus may optionally extend to 2016–2020 for descriptive/power purposes, but promotion, tuning, and evaluation use only the mandated 2021–2025 window. | F10. | R25/R31 unaffected; increases power without contaminating splits. **Open question — default off.** |
| **D14** | R25 full-corpus replay uses `calibrated_rules`. `d3_mini` is calibrated on **all 2024 candidate games** and evaluated on **all 2025 candidate games** (expected a few hundred requests); if the service is saturated, degrade to a stratified sample and report the reduced n. | Sub-second decisions at 4 concurrency make candidate-set scoring practical, but the service is shared; scoring every historical game (including non-candidates) would be wasteful and unfair. | R25 satisfied with a faithful candidate-set evaluation and an explicit population definition. |
| **D15** | Primary probability = calibrated `noul` `P(yes)`; a 5-level `score` question is a secondary signal; the monitor worker uses a `choice` question with `{confirmed, contradicted, insufficient}`. | The API provides probabilities directly for `noul`; `score`/`choice` add graded and categorical decisions without inventing a mapping. Calibration on 2024 addresses the provider's own advice to fit cutoffs empirically. | R14 satisfied; consistency improved (distribution scoring, not token sampling); R30's labelled sample sets the thresholds. |
| **D16** | Embedding spaces are measured, not assumed: Ollama `qwen3-embedding:8b` = **4096-d**, ARC `Qwen3-Embedding-4B` = **2560-d**, both L2-normalised. `EMBED_MODEL`/`EMBED_DIM` and collection metadata name the exact space, and the adapter rejects a response of the wrong width. Embeddings are citation-retrieval only — never chat, rationale, monitor confirmation, or scoring. | Live probes 2026-11-22; the two available models differ in width and the ARC gateway 500s on the Ollama-style id, so the space must be pinned per collection. | R8 satisfied; the design's named model is preserved via Ollama; the ARC 4B option is explicit and separate. |
| **D17** | **CFBD** is a secondary structured source through `adapters/cfbd.py`: historical lines (`/lines`) and venue geodata (`/venues`: lat/lon, elevation, dome, timezone). It requires a free academic API key (3,000 calls/mo); responses are cached and fixtures recorded. Without the key the app degrades to ESPN + strength proxy, and the offline demo never calls CFBD. | F4 plus ESPN's missing venue coordinates; CFBD is the only free source that supplies both open lines and stadium coordinates for the mandated window. | R10/R24 satisfied with better coverage; R8 unaffected; adds one optional credential (B6). |

### 4.4 Layered runtime architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│ Presentation      Streamlit pages, components, progress, audit views │
├──────────────────────────────────────────────────────────────────────┤
│ Agents            Data / Research / Monitor orchestrators, workers,  │
│                   Upset-Scorer, Adjudicator (LLM only where marked)  │
├──────────────────────────────────────────────────────────────────────┤
│ Domain (pure)     rule DSL + evaluator, labeler, screen, features,   │
│                   stats, calibration, scorer, cache keys             │
├──────────────────────────────────────────────────────────────────────┤
│ Adapters          espn, weather, search, fetch, deep_research, llm,  │
│                   embeddings, chroma, sqlite                          │
├──────────────────────────────────────────────────────────────────────┤
│ Platform          config, logging/tracing, retry/circuit/budget,     │
│                   clock, ids, hashing, migrations                    │
└──────────────────────────────────────────────────────────────────────┘
```

Rule: **domain never imports adapters or Streamlit**; agents orchestrate domain + adapters;
adapters never import agents. This is enforced by an import-linter test.

### 4.5 Agent boundary contracts

| Agent | Inputs | Outputs | Tools | LLM? | Determinism |
| --- | --- | --- | --- | --- | --- |
| `Data-Orchestrator` | seasons, weeks, batch size | `IngestReport`, coverage, quarantine | worker pool, validator, repo | no | fully deterministic |
| `Historical-Stats Worker` | `GameIdBatch` | `HistoricalGameRecord[]` | ESPN adapter | no | deterministic |
| `Research-Orchestrator` | candidate catalog, corpus | `SpecStoreState`, `StatsReport`, `AuditReport` | workers, validator, labeler, stats, search, embeddings | no (summarisation only) | deterministic control flow |
| `Research Worker` | `ResearchBrief` | `ResearchReport` (+proposed rule) | research provider, LLM extractor | **yes** | stochastic input, validated output |
| `Monitor-Orchestrator` | game ids, spec set | `RunResult` (alerts or empty reason) | screen, workers, scorer, cache, trace | rationale templating only | deterministic control flow |
| `Monitor Worker` | `MonitorTask` (game + matched specs) | `MonitorDecision` | search, fetch, d3-mini `choice` question | **yes** (decision model) | deterministic given input; thresholds calibrated on labelled audits |
| `Upset-Scorer` | confirmed flags + context | `RankedAlert[]` | `/api/v1/systemone` **or** calibrated model | rationale only | score deterministic given inputs |
| `Adjudicator` | anonymised evidence + claim | `HOLD` / `NOT_HOLD` / `UNKNOWN` | none | **yes** (chat model, distinct family) | blinded, separate model from the monitor worker, fixed rubric |

### 4.6 Pydantic contract catalogue (all in `cfb_upset/contracts/`)

`Provenance` (`source`, `source_url`, `fetched_at`, `published_at`, `known_at`, `content_hash`,
`confidence`), `HistoricalGameRecord`, `GameIdBatch`, `IngestReport`, `QuarantineRecord`,
`SlateGame`, `TeamInfo`, `VenueInfo`, `OddsInfo`, `WeatherInfo`, `ResearchBrief`, `ResearchReport`,
`RuleSpec` (`field`, `op`, `value`, `value2`, `units`, `missing_policy`), `PreconditionSpec`
(`spec_id`, `version`, `candidate_key`, `title`, `rationale`, `rule`, `required_fields`, `scope`,
`min_support`, `citations`), `SpecPromotion`, `LabelEvidence`, `LabeledGame`, `StatResult`,
`ValidatedPrecondition`, `ScreenMatch`, `MonitorTask`, `MonitorDecision`, `ConfirmedFlag`,
`ScoreRequest`, `UpsetScore`, `RankedAlert`, `AgentEvent`, `RunResult`, `CacheEntry`.

Conventions: `model_config = ConfigDict(extra="forbid")` everywhere; enums for statuses; UTC
datetimes; `Decimal` or `float` documented per field; JSON Schema exported to `docs/contracts/` for
the UML appendix.

### 4.7 Data model (SQLite)

```
teams(team_id PK, school, nickname, conference_id, is_fbs, color, alt_color, logo_url, venue_id, updated_at)
venues(venue_id PK, name, city, state, country, indoor, grass, lat, lon, altitude_m, tz, source)
games(game_id PK, season, week, season_type, kickoff_utc, home_team_id, away_team_id,
      neutral_site, conference_game, venue_id, status, home_score, away_score, winner_team_id,
      is_fbs_vs_fbs, ingested_at, source)
game_fields(game_id, field_name, value_json, known_at_utc, source, source_url, fetched_at_utc,
            confidence, PK(game_id, field_name, source))          -- per-field provenance
game_features(game_id, feature_name, value, known_at_utc, feature_version)
precondition_spec(spec_id, version, candidate_key, title, research_report_json, rule_json,
                  required_fields_json, scope, min_support, citations_json, source,
                  created_at, rejection_reason, PK(spec_id, version))
spec_store(spec_id, version, is_active, promoted_at, notes, PK(spec_id, version))
labeled_games(label_id PK, game_id, spec_id, spec_version, label, evaluable, evidence_json,
              labeler_version, labeled_at, UNIQUE(game_id, spec_id, spec_version))
label_audits(audit_id PK, spec_id, spec_version, game_id, sampled, adjudication,
             evidence_ids_json, auditor, created_at)
stat_results(stat_id PK, spec_id, spec_version, split, n, positives, risk_diff, ci_low, ci_high,
             odds_ratio, p_value, q_value, method, diagnostics_json, computed_at)
validated_preconditions(spec_id PK, spec_version, status, acceptance_json, effect_json,
                        citations_json, valid_from, reason, updated_at)
evidence(evidence_id PK, source_url, domain, title, published_at, fetched_at, content_hash,
         snapshot_path, kind, created_at)
evidence_links(evidence_id, ref_type, ref_id, supports, quote, created_at)
analysis_runs(run_id PK, slate_date, games_json, spec_set_hash, config_hash, status,
              started_at, finished_at, budget_seconds, trace_path)
analysis_cache(cache_key PK, game_id, spec_set_hash, evidence_hash, scorer_version,
               embedding_version, result_json, created_at, expires_at)
agent_events(event_id PK, run_id, agent, phase, event_type, payload_json, ts)
quarantine(record_id PK, payload_json, errors_json, created_at)
schema_migrations(version PK, applied_at)
```

Raw evidence snapshots live in `data/evidence/<hash>.txt.gz`; SQLite stores the pointer and hash.
Chroma collections are created **per embedding space** (`citation_chunks__<model>__<dim>__<instr_hash>`)
and store `{chunk_text, embedding}` with metadata
`{spec_id, evidence_id, domain, published_at, known_at}`; collection metadata records
`{model, dim, instruction_template, normalized}`. `analysis_cache.cache_key` hashes the game,
`spec_set_hash`, `evidence_hash`, `scorer_version`, `embedding_version`, and retrieval config, so a
model/dimension/chunking change invalidates cached rationale instead of silently reusing it.

### 4.8 Provenance and leakage model

`known_at` assignment policy (enforced in one module, `domain/leakage.py`):

| Field group | `known_at` |
| --- | --- |
| schedule, kickoff, venue, neutral site, conference, team identity | `kickoff − 7d` |
| weekly poll/ranking for game week | earliest kickoff of that week `− 1h` |
| opening odds | `kickoff − 72h` (or provider-reported open time if available) |
| closing odds | `kickoff` → **excluded** by strict `<` |
| weather | `kickoff − 24h` (forecast issue convention) |
| rolling team stats / records / rest / travel | computed only from games with `kickoff < this kickoff` |
| box score, final score, post-game win probability | **never admitted as features** (labels only) |
| fetched article/depth chart/injury note | `published_at` if present and `< kickoff`; else `UNKNOWN` → not admitted |

Enforcement points: (1) ingestion validator drops fields whose `known_at >= kickoff` and records
the drop; (2) feature builder asserts every input `known_at < kickoff`; (3) labeler refuses specs
that reference non-admitted fields; (4) monitor payload builder strips any evidence with
`published_at >= kickoff`; (5) a CI test injects a sentinel field (`kickoff+1s`) and asserts zero
downstream change.

### 4.9 Decision model design

`UpsetScorer.score(request) -> UpsetScore` with `backend ∈ {d3_mini, calibrated_rules}`. `d3_mini`
is reached through a dedicated `SystemOneClient` (`POST {VT_ARC_BASE_URL}/systemone`), **not** the
chat-completions path:

1. **Candidate definition.** A game is scoreable if it is FBS-vs-FBS, has a favorite, and trips ≥1
   active spec. Non-candidates receive the slate base rate (they are still scored so evaluation can
   cover the full slate).
2. **`d3_mini` backend (preferred).** Model id `decision.vllm-sr/d3-mini`. `SystemOneClient`
   sends **one HTTP request per candidate game** — a bounded text `input` (market context, matched
   specs with observed values, up to three short quotes) plus named questions:
   - `upset_likely` (`noul`): "Will the underdog win outright?" → the answer is `P(yes)`, which is
     the primary `UpsetScore.probability`.
   - `risk_level` (`score`, optional, budget-gated): 5 ordered level descriptions from
     *very unlikely* to *very likely* → a probability-weighted value in `[0, 4]`, used as a
     secondary ranking/explanation signal.
   The response supplies probabilities, `confidence`, and per-level legends; it is parsed into
   `UpsetScore` (`probability`, `confidence`, `key_signals`, `citations`, `raw_answers`,
   `request_hash`). Each question re-reads the full input, so the payload budgeter caps questions
   and total tokens (§4.9.1). Routine runs issue one request per game; repeat sampling is reserved
   for R19 (§8.4).
3. **`calibrated_rules` backend (fallback/baseline).** Logistic regression on
   `[logit(market_prob), strength_diff, matched_spec_count, each validated spec indicator,
   rest_diff, travel_km, altitude, neutral_site]`, fit on 2021–23, calibrated on 2024 (Platt or
   isotonic, chosen by validation log loss), applied to 2025. Coefficients and calibration curve
   are versioned artifacts. This is *also* the mandatory simple baseline for Pr10.
4. **Ranking.** Sort by probability desc, tie-break by (matched spec count desc, kickoff, `game_id`)
   so ordering is total and stable. Rank 1..n over confirmed candidates only.
5. **Rationale.** Deterministic template composed from matched specs, observed values, and cited
   evidence; an LLM may rewrite prose but the numeric score and citation set are immutable and
   verified after rewriting.

**Shadow mode.** When `d3_mini` is reachable, the calibrated backend always runs too; the run
record stores both scores. This gives the "measure honestly" comparison and protects the demo.

#### 4.9.1 `systemone` API semantics and operating envelope (owner-provided, 2026-11-22)

| Element | Contract |
| --- | --- |
| Model | `decision.vllm-sr/d3-mini` — a decision model, not a chat model; unavailable in the web UI |
| Request | `{"model": "decision.vllm-sr/d3-mini", "state": "<text>", "questions": {"<name>": {"type": "…", "instructions": "…", "criteria": …}}}` where `type` is one of `noul`, `choice`, `score`; optional `images` as data URLs. `questions` must be a **JSON object**, not a list |
| `noul` question | `instructions` is a yes/no question; the answer is `P(yes) = P(true)` |
| `choice` question | `instructions` + `criteria` (option name → description, description may be null); answer = most likely option, probabilities for every option, confidence |
| `score` question | `instructions` + `criteria` (2–10 level descriptions, lowest first); answer = probability-weighted level in `[0, n−1]`, per-level probabilities, legend, confidence |
| `confidence` | 0 when all options are equally likely → 1 when one option holds all probability |
| Invalid request | HTTP 400 with a specific message (unknown type, malformed criteria, …); validate locally first |
| Cost | every question re-reads the whole input: cost ∝ input length × number of questions |
| Latency | short requests under a second; larger inputs slower |

**Captured wire example (live probe, 2026-11-22).**

```json
{"model":"decision.vllm-sr/d3-mini",
 "state":"Virginia Tech hosts Miami on Saturday. Miami is a 7-point favorite.",
 "questions":{
   "upset_likely":{"type":"noul","instructions":"Will the home team win outright?"},
   "confirm":{"type":"choice","instructions":"Does the evidence confirm Miami is overvalued?",
              "criteria":{"confirmed":"…","contradicted":"…","insufficient":"…"}},
   "risk":{"type":"score","instructions":"How likely is an upset?",
           "criteria":["very unlikely","unlikely","possible","likely","very likely"]}}}
```

```json
{"model":"vllm-sr/d3-mini",
 "answers":{
   "upset_likely":{"type":"noul","noul":0.0210483384072851},
   "confirm":{"type":"choice","choice":"insufficient",
              "probabilities":{"confirmed":0.002,"contradicted":0.089,"insufficient":0.909},
              "confidence":0.7138},
   "risk":{"type":"score","score":1.5178,
           "legend":{"0":"very unlikely","1":"unlikely","2":"possible","3":"likely","4":"very likely"},
           "probabilities":{"0":0.055,"1":0.418,"2":0.487,"3":0.035,"4":0.005},
           "confidence":0.3677}},
 "usage":{"input_tokens":126,"output_tokens":0}}
```

Required fields: `model`, `state`, and a non-empty `questions` object. Missing `model` → 400
`"Body must be a JSON object with a \"model\""`; missing `state` → 400 `"\"state\" must be
provided"`; empty `questions` → 400 `"\"questions\" must be a non-empty object"`. Identical
requests are stable at the tested length (3× identical `noul` = `0.0210483384072851`).

Operating limits:

| Limit | Value | Consequence for this system |
| --- | --- | --- |
| Queued or running decision requests per user | **4** | Hard **process-wide** semaphore of 4; a fifth request returns 429 `user_concurrent` |
| Queue wait before start | 30 s | Unstarted requests return 503 `queue_timeout`; honour `error.retry_after_s` |
| Input per question | 8,192 tokens (~35 KB English) | Deterministic payload budgeter truncates evidence before sending; hard check |
| Request body size | 8 MiB | Byte check; HTTP 413 is permanent, never blind-retry |
| Images | ≤8, ≤1,700 tokens each | Unused — this system is text-only |
| Fair share | one request per waiting user per round | Concurrency above 4 gains nothing; the cap is a constant, not a tuning knob |

**Error handling.** 429 → wait `retry_after_s` (body first, then header), retry ≤2; 502
`replica_unavailable` → exponential retry ≤2; 503 `queue_timeout` → wait `retry_after_s`, retry ≤2,
then mark the game `scoring_degraded`; 413 → shrink the payload and retry once, else degrade;
500 (input limit) → validate the token budget, never blind-retry. Every attempt is recorded with
attempt number, reason, wait time, and final outcome.

**Throughput.** A slate of N candidates takes ⌈N/4⌉ waves. Under nominal latency this is fast, but
one 30 s queue timeout consumes most of a 300 s run budget. The orchestrator therefore scores in
screened-priority order, stops issuing new decision requests at `RUN_BUDGET_SECONDS −
SCORE_TIMEOUT_S`, and scores any remainder with `calibrated_rules`, flagged
`score_source=fallback_budget`. `MAX_SCORED_GAMES` bounds the work; the UI shows
scored / queued / dropped counts.

**Mapping answers to a calibrated probability.** `noul` already returns a probability, so
`UpsetScore.probability` is its raw `P(yes)` **after** isotonic/Platt calibration fit on the 2024
validation season (versioned artifact, reported in `docs/EVALUATION.md`). The raw value is always
stored alongside the calibrated one. The optional `score` answer is not converted into a competing
probability; it is a secondary ordering/explanation signal, and ties in the ranking break on the
calibrated probability, then matched-spec count, then `game_id` so 1..n stays total and stable.
Before sending, `SystemOneClient` validates the request against a local Pydantic model to avoid
spending quota on a 400. An unknown response shape raises `ContractError` and degrades the game —
the adapter never guesses.

#### 4.9.2 Embeddings API envelope (R8)

| Element | Primary — local Ollama | Secondary — VT ARC |
| --- | --- | --- |
| Endpoint | `POST {OLLAMA_BASE_URL}/embeddings`, default `http://localhost:11434/v1` | `POST {VT_ARC_BASE_URL}/embeddings` |
| Auth | none (localhost) | `Authorization: Bearer $VT_ARC_API_KEY` |
| Model id | `qwen3-embedding:8b` | `Qwen3-Embedding-4B` (ARC 500s on the Ollama-style id) |
| Measured width | **4096** | **2560** |
| Norm | **1.0** (already L2-normalised) | **1.0** |
| Response | OpenAI-style `data[i].embedding`, `usage` | same |
| Request | `{model, input}`; `input` is a string or list of strings | same |
| Context | native 32k; keep chunks ≤2k tokens to avoid Ollama context truncation | native 8,192-token gateway cap |
| Similarity | cosine | cosine |
| Instruction format | Qwen3 cards use `Instruct: {task}\nQuery: {query}` for queries and raw text for documents; the template is stored in collection metadata | same |
| Batching | probe list-input support; default batch 8 | probe cap |
| Use | citation retrieval only (`citation_chunks`); never chat, rationale, monitor confirmation, or scoring | optional portable space |
| Failure | Ollama down at query time → use each spec's **direct citations**, flag `retrieval_degraded`; do not query a 4096 collection with 2560 | only valid if the collection was built in the 2560 space |
| Versioning | collection name/metadata carries `{model, dim, instruction_template, normalized}`; the active embedding version is part of `analysis_cache.cache_key` | separate collection per space |

**Chunking.** Accepted citations are split into ~512–1,000-token chunks with a small overlap. The
adapter token-counts before send and keeps every input well under the provider context, so neither
Ollama nor the gateway can truncate silently. Vector width is asserted on every response.

**Demo safety.** Query embeddings for the pre-warmed demo runs are cached, so the offline demo works
even if Ollama is stopped. Any fresh run requires the Ollama service, which the app health-checks at
startup and reports in the UI.

### 4.10 Concurrency model

`asyncio` + `httpx.AsyncClient`; one semaphore per provider (`ESPN_MAX_CONCURRENCY=6`,
`SEARCH_MAX_CONCURRENCY=4`, `LLM_MAX_CONCURRENCY=4`, `EMBED_MAX_CONCURRENCY=2`); `anyio` task groups with
`return_exceptions=True`; each task writes `AgentEvent`s and returns a typed result or a typed
failure. Orchestrators never `await` inside a loop without gathering batches. Wall-clock budget
propagates as a deadline; tasks past the deadline are cancelled and reported as `skipped_budget`.

**`systemone` is a shared per-user resource.** Enforce a semaphore of 4 for the whole process (not
per run), and allow only one active analysis run per process; the UI disables **Analyze** while a
run is live and queues additional requests. Fair-share scheduling means extra concurrency buys
nothing, so 4 is a hard constant (`SYSTEMONE_MAX_CONCURRENCY`) and any configured value above 4 is
rejected at startup. Monitor confirmation and scoring share the same four slots, but the phases are
sequential (confirm → score), so contention is bounded: at most two monitor workers and at most
four scorer requests in flight.

---

## 5. Technology stack and rationale

| Concern | Choice | Rationale |
| --- | --- | --- |
| Language | Python 3.11+ (3.13 present) | course standard; all deps available |
| Contracts | Pydantic v2 | R21/R7; JSON Schema export for UML/QA |
| Config | `pydantic-settings` + `.env` | R20; typed config, no scattered `os.getenv` |
| HTTP | `httpx` (async) + `tenacity` | timeouts, retries, connection pooling |
| Storage | SQLite via stdlib `sqlite3` + SQL migrations | R8/R15; zero-ops, auditable |
| Vectors | ChromaDB (persistent client) | R8; metadata filtering for spec citations |
| Embeddings | **Ollama `qwen3-embedding:8b`** at `http://localhost:11434/v1/embeddings` (4096-d, normalised, keyless) primary; ARC `Qwen3-Embedding-4B` (2560-d) optional secondary; hashing for tests only | D8/D16; matches the design's named model, removes the network dependency, and keeps spaces strictly separated |
| Secondary data | CFBD REST (`/lines`, `/venues`) via `adapters/cfbd.py` | historical open lines plus stadium lat/lon/elevation/indoor; free academic key; optional, cached, fixture-tested |
| Stats | `numpy`, `pandas`, `scipy`, `statsmodels`, `scikit-learn` | effect sizes, CIs, BH-FDR, calibration, logistic model |
| UI | Streamlit 1.45+ (`st.fragment`, `AppTest`) | R1; testable |
| Orchestration | plain `asyncio` classes | fewer moving parts, explicit contracts, easy to audit; a graph framework adds opacity for no requirement |
| LLM client | `httpx` against VT ARC OpenAI-compatible endpoint | avoids extra SDK; full control of timeouts/JSON |
| Decision model | `decision.vllm-sr/d3-mini` via `SystemOneClient` → `POST /api/v1/systemone` | Served outside the OpenAI-compatible surface; returns option probabilities (`noul`/`choice`/`score`), which are more repeatable than token sampling; isolate the contract behind one adapter |
| Diagrams | Mermaid (`.mmd`) + Quarto/Typst → PDF | F15; no LaTeX/Graphviz needed |
| Tests | `pytest`, `pytest-asyncio`, `respx` (HTTP mocking), `streamlit.testing` | offline determinism |
| Quality | `ruff`, `black`, `mypy` (advisory) | R16 |
| Packaging | `make` targets + `zip` script | submission artifact |

Dependency additions required: `chromadb`, `respx` (dev). No OpenAI or embedding SDK — chat,
`systemone`, and `/embeddings` all use `httpx` and share retry/trace/snapshot plumbing.

---

## 6. Repository structure

```
cfb-upset-precondition/
├── app.py                          # Streamlit entry point (thin: page router only)
├── Makefile                        # setup, test, lint, ingest, build-preconditions, eval, uml, package
├── requirements.txt
├── requirements-dev.txt
├── .env.example                    # keys only, no values
├── IMPLEMENTATION_PLAN.md
├── PROGRESS.md
├── README.md
├── configs/
│   ├── default.yaml                # worker counts, budgets, feature flags
│   ├── eval.yaml                   # splits, metrics, bootstrap settings
│   └── preconditions/candidates.yaml
├── cfb_upset/
│   ├── config.py                   # Settings (pydantic-settings), feature flags
│   ├── logging_setup.py
│   ├── ids.py                      # deterministic ids/hashes, UTC clock
│   ├── contracts/                  # §4.6, one module per handoff + __init__ re-exports
│   ├── domain/
│   │   ├── rules.py                # DSL, evaluator, missing-value semantics
│   │   ├── labeler.py
│   │   ├── screen.py
│   │   ├── features.py             # rolling/leakage-safe feature derivation
│   │   ├── leakage.py              # known_at policy + admission checks
│   │   ├── scoring.py              # calibrated scorer, ranking, tie-breaks
│   │   ├── calibration.py
│   │   ├── stats.py                # effects, bootstrap CIs, BH-FDR, splits
│   │   └── cache_keys.py
│   ├── adapters/
│   │   ├── http.py                 # retry, timeout, circuit breaker, budget, response cache
│   │   ├── espn.py                 # scoreboard, summary, odds, rankings, teams, venues
│   │   ├── cfbd.py                 # optional: historical lines + venue geodata
│   │   ├── weather.py              # open-meteo historical (2021+) + live forecast
│   │   ├── geocode.py              # CFBD venue coordinates + CSV fallback
│   │   ├── search.py               # Brave adapter + mock/fixture transport
│   │   ├── fetch.py                # fetch adapter, domain whitelist, extraction, snapshots
│   │   ├── deep_research.py        # MCP client + seeded-literature provider
│   │   ├── llm.py                  # VT ARC chat client, JSON mode, retries, token ledger
│   │   ├── embeddings.py           # Ollama qwen3-embedding:8b (4096) / ARC 4B (2560) / hashing
│   │   └── chroma.py               # one collection per embedding space
│   ├── agents/
│   │   ├── base.py                 # AgentContext (trace, budget, repos), AgentResult
│   │   ├── data_orchestrator.py
│   │   ├── historical_stats_worker.py
│   │   ├── research_orchestrator.py
│   │   ├── research_worker.py
│   │   ├── monitor_orchestrator.py
│   │   ├── monitor_worker.py
│   │   ├── upset_scorer.py
│   │   └── adjudicator.py
│   ├── store/
│   │   ├── db.py                   # connection, migrations runner
│   │   ├── migrations/0001_init.sql, 0002_*.sql ...
│   │   ├── repositories.py         # typed CRUD per aggregate
│   │   ├── evidence.py             # snapshot store
│   │   └── cache.py                # analysis_cache
│   ├── research/
│   │   ├── seed_preconditions.yaml # ~20 candidates w/ citations, thresholds, rationale
│   │   └── catalog.py
│   ├── pipelines/
│   │   ├── ingest_corpus.py        # python -m cfb_upset.pipelines.ingest_corpus
│   │   ├── build_preconditions.py
│   │   ├── run_monitor.py
│   │   ├── backtest.py
│   │   └── capabilities.py         # probe (also scripts/probe.py)
│   ├── observability/
│   │   ├── trace.py                # JSONL + agent_events
│   │   └── budget.py
│   └── ui/
│       ├── pages/1_Slate.py, 2_Run.py, 3_Audit.py, 4_Preconditions.py, 5_Evaluation.py
│       ├── components.py           # slate table, alert cards, citation chips
│       └── progress.py             # run controller (thread + queue) and timeline renderer
├── scripts/
│   ├── probe.py
│   ├── build_uml.sh
│   ├── package.sh
│   └── seed_demo.py
├── data/                           # gitignored: cfb.db, chroma/, evidence/, traces/, cache/
├── docs/
│   ├── ARCHITECTURE.md             # design + measured parallelism + decisions
│   ├── DEMO_SCRIPT.md
│   ├── EVALUATION.md               # generated report summary + link to reports/
│   ├── CAPABILITIES.md             # probe matrix (generated)
│   ├── contracts/*.schema.json     # generated
│   └── uml/{class,seq_phase1,seq_phase2,seq_phase3}.mmd + cfb_upset_uml.pdf
├── reports/                        # gitignored: eval_<ts>/{metrics.json,calibration.png,report.md}
└── tests/
    ├── unit/ integration/ e2e/ live/
    ├── fixtures/{espn,search,fetch,research,corpus}/
    └── conftest.py
```

---

## 7. Cross-cutting engineering standards

- **Config.** All tunables in `Settings`; `.env.example` is the canonical key list (Appendix B). No
  module reads `os.environ` directly. `Settings` validates at startup and prints a redacted summary.
- **IDs and time.** ULIDs for run/event ids; SHA-256 for content/cache keys; UTC everywhere
  (`datetime.now(timezone.utc)` behind a `Clock` protocol so tests are time-travelable).
- **Error taxonomy.** `TransientProviderError`, `PermanentProviderError`, `ContractError`,
  `BudgetExhausted`, `LeakageError`, plus `SystemOneThrottled` (429/503 with `retry_after_s`),
  `SystemOneOverloaded` (502), `SystemOnePayloadTooLarge` (413), `SystemOneInputLimit` (500).
  Adapters raise; agents translate into typed degraded results.
- **Retry policy.** 3 attempts, exponential backoff with jitter, `Retry-After` honoured; circuit
  breaker opens per provider after 5 consecutive failures for 60 s; every retry emits an event.
  `systemone` retries are capped separately and always respect the owner-provided limits (§4.9.1).
- **Caching.** HTTP response cache (URL + params hash, TTL per provider); evidence snapshot store
  (content hash); analysis cache (§4.7). All keys deterministic and versioned.
- **Prompt injection.** Fetched content is untrusted: strip HTML to text, cap length, wrap in a
  delimited block, never include tool instructions from content, whitelist domains
  (`espn.com`, `sports-reference.com`, `cbssports.com`, `si.com`, plus an operator-extendable
  local-media list), and log the domain for every quote.
- **Cost controls.** `RUN_BUDGET_SECONDS`, `MAX_GAMES_PER_RUN`, `MAX_FETCHES_PER_GAME`,
  `MAX_PAGES_PER_RUN`, token ceiling per run; the UI shows spend so far.
- **Logging.** Structured JSON logs + JSONL run traces; never log secrets or raw LLM prompts above
  `LOG_LEVEL=DEBUG`; redact keys.
- **Comments/docstrings.** Every module has a purpose docstring; every public function documents
  inputs, outputs, and failure modes; non-obvious math cites the formula. This is a graded item.

---

## 8. Reliability and statistical validation

### 8.1 Ten principles → concrete mechanisms

| Principle | Mechanism in this system | Test |
| --- | --- | --- |
| Pr1 Deterministic validation decides | Pydantic gates, rule evaluator, FDR/stats, recomputed cache keys; LLM never overrides a computed label/score | Contract + property tests; label determinism hash |
| Pr2 Draft independently | Monitor workers receive tasks independently and never see each other's output; research workers own disjoint precondition batches | Integration test: worker payloads contain no peer data |
| Pr3 Strip identities | Label audit evidence is anonymised (no agent name, no model name, shuffled ids) before adjudication | Unit test on prompt builder |
| Pr4 Real diversity | Two model families where available (`GLM-5.3` for extraction, `gpt-oss-120b`/`MiniMax` for adjudication); otherwise different prompts **plus** different evidence retrieval | Config test asserts distinct `extractor_model`/`adjudicator_model` |
| Pr5 Ask critics to falsify | The monitor worker's `choice` criteria include an explicit `contradicted` option defined as "the strongest evidence says this flag is false"; a `contradicted` answer requires the quoted passage. The adjudicator must cite a contradicting passage to return `NOT_HOLD`. | Criteria snapshot test; audit report includes falsification attempts |
| Pr6 Separate judge | `Adjudicator` is a different model, fresh context, no access to worker reasoning; stats are computed by code | Test asserts adjudicator input excludes `MonitorDecision.rationale` |
| Pr7 Hard-to-game verifier | Tests and thresholds are not agent-writable; held-out 2025 season never used for tuning; planted-error suite validates the validator | `tests/eval/test_detects_planted_errors.py` |
| Pr8 Provenance | `evidence` + `evidence_links`; every alert renders citations; unsourced flags dropped | E2E: every alert has ≥1 resolvable `evidence_id` |
| Pr9 Preserve dissent, limit interaction | Worker disagreement recorded (`dissent` list, confidence); 3-sample scoring dispersion reported; no agent debate rounds | Result schema requires `dissent`; repeatability report includes dispersion |
| Pr10 Measure honestly, humans at hinges | Baselines (base rate, market, rules-only) + Brier skill; human approval gate for spec promotion and rule tuning | `reports/eval_*/metrics.json` includes all baselines; CLI `--approve` required when `REQUIRE_APPROVAL=1` |

### 8.2 Precondition validation protocol (statistical claim — **not** system performance)

Pre-registered before any result is inspected (committed in `configs/eval.yaml`):

- **Unit of analysis:** game. **Outcome:** upset (favorite loses; favorite from `favorite_source`).
- **Support:** a spec is evaluable on a game if all required fields are admitted and non-null.
  Minimums: ≥300 evaluable games in dev, ≥30 label positives.
- **Effect:** risk difference (RD) = P(upset | spec holds) − P(upset | spec does not hold);
  odds ratio from 2×2 and from a logistic model controlling for `logit(market_prob)` and a
  strength differential. Bootstrap 95% CI (2,000 resamples, clustered by season) for RD; Wald CI
  for the adjusted OR.
- **Multiplicity:** Benjamini–Hochberg across **all** specs tested in the phase, per split,
  `q = 0.10`. Raw p-values and q-values both stored.
- **Out-of-sample:** fit thresholds/coefficients on 2021–2023; evaluate on 2024; the **2025**
  season is untouched until the final report. Spot-check tuning uses only 2021–2023 games.
- **Acceptance:** RD ≥ +5 pp, CI lower bound > 0, adjusted OR ≥ 1.25, q < 0.10, sign stable in
  ≥2 of 3 dev seasons, and RD > 0 on 2024. Specs meeting all → `validated`; meeting effect but
  missing support/stability → `provisional`; otherwise `rejected` with a reason.
- **Sensitivity:** repeat with upset definitions of favourite-by-≥7 and ≥14; report all three.
- **Baseline comparison for a spec:** does it add predictive value beyond the market? Report the
  likelihood-ratio test for the spec indicator in the market+strength model.

### 8.3 System predictive evaluation protocol (R25)

- **Splits:** fit 2021–2023, calibrate/select on 2024, report on 2025. No exception. For
  `d3_mini`, which is pre-trained and has no fit step, the 2021–2023 window is used only for
  descriptive comparisons; **2024 is the calibration set** and **2025 is the untouched test set**.
- **Population:** every FBS-vs-FBS game in the split, not only flagged games. Unflagged games get
  the base-rate probability. This prevents the classic "score only the candidates" inflation.
- **Metrics:** Brier score (primary), log loss, 10-bin reliability curve + ECE, AUC (secondary),
  precision@5/@10 for the ranking use case, and Brier skill score versus the best baseline.
- **Baselines:** (a) constant 2021–23 base rate; (b) market-implied probability from the admitted
  favorite line; (c) logistic model on market + strength only; (d) matched-rule count only;
  (e) full system. Report all five.
- **Uncertainty:** bootstrap 95% CIs over games (2,000 resamples) for Brier and log loss
  differences versus the market baseline.
- **Honesty clause:** if the full system does not beat the market baseline, the report says so.
  Beating the market is not a requirement; producing calibrated, auditable, ranked upset risk is.
- **R25 scope statement (deviation D6):** the 2021–2025 replay covers the structured path
  (features → screen → scorer). The evidence-confirmation stage is evaluated on 2025 only, using
  archived evidence, and reported separately as "full-pipeline subset."
- **Decision-model evaluation (deviation D14).** The full 2021–2025 replay uses
  `calibrated_rules` (local, deterministic, free). `d3_mini` is calibrated on **all 2024 candidate
  games** and evaluated on **all 2025 candidate games**; non-candidates receive the slate base rate
  in both backends, so the population definition is identical. Expected volume is a few hundred
  requests (sub-second each at 4 concurrency). Report Brier/log loss with bootstrap CIs,
  calibration, raw-vs-calibrated probability, and agreement with the calibrated backend. If the
  service is saturated or rate-limited, degrade to a stratified sample, report the reduced n, and
  state it; never imply full coverage that did not happen.

### 8.4 Repeatability protocol (R19)

5 identical runs on a frozen slate + frozen spec set + frozen cache state; metrics:
flag-set Jaccard, Kendall τ and Spearman ρ of rankings, max-min probability spread, and
decision-flip count. Pass: Jaccard ≥ 0.90, τ ≥ 0.80, spread ≤ 0.03 for ≥90% of games, zero
non-deterministic label differences. `calibrated_rules` is tested on the full frozen slate.
`d3_mini` is tested on an **8-game frozen subset with 3 repeats** and one decision request per game
per repeat, staying inside the 4-request per-user limit; report dispersion, flips, and any
`queue_timeout` losses. Probe determinism first: if the same input reproduces the same
probabilities, 2 repeats suffice; if not, report the observed spread. If the decision path is
unstable, alerts are flagged `unstable=true` and the report says so rather than hiding it.

### 8.5 Label-quality protocol (R30)

Sample: 50 spec-game pairs stratified by spec and label, fixed seed, recorded in `label_audits`.
For each pair: fetch up to 3 whitelisted pages published before kickoff, extract the relevant
passage, anonymise, and ask the `Adjudicator` for `HOLD`/`NOT_HOLD`/`UNKNOWN` with a required
quote. Orchestrator computes precision, recall (using planted positives to estimate recall —
natural positives are selected deliberately), Wilson CIs, and per-spec disagreement rates.
Any spec with precision < 0.80 is ineligible for `validated` regardless of statistics. At most
**one** tuning round is allowed; the new thresholds are re-tested on dev and logged.

The same labelled audit set is used, following the decision-model provider's guidance, to choose
the monitor worker's `CONFIRM_THRESHOLD` and `DROP_THRESHOLD` (and the optional alert cutoff) by
maximising agreement with human labels on 2024-derived data. The chosen cutoffs, the curve, and the
sample size are stored in `label_audits`/`validated_preconditions` metadata and reported in
`docs/EVALUATION.md`.

### 8.6 Human gates

1. **Spec promotion** — `REQUIRE_APPROVAL=1` blocks `validated` status until a human reviews the
   `docs/EVALUATION.md` summary (or uses the UI Preconditions page). Demo mode may pre-approve a
   recorded decision, which is logged.
2. **Rule tuning** — the one tuning round requires explicit approval.
3. **Showcase** — no code changes on 2026-12-03; only the frozen tagged build is demoed.

---

## 9. Implementation phases

Effort estimates are in focused person-days for an autonomous agent. Every phase ends with a
commit, an updated `PROGRESS.md`, and a green `make test`.

---

### P0 — Capability probe, scaffold, and walking skeleton

**Objective.** Resolve every external dependency uncertainty before designing around it, stand up
the repo, and prove one end-to-end path from fixture data to a ranked Streamlit alert.

**Prerequisites.** None.

**Tasks.**
1. `scripts/probe.py` + `cfb_upset/pipelines/capabilities.py`: probe ESPN scoreboard/summary/odds/
   rankings/teams/groups; VT ARC `/v1/models` + one chat completion with JSON-only instruction;
   **confirm the captured `systemone` contract** (`{model,state,questions{}}`, §4.9.1) and write
   golden fixtures for one `noul`, one `choice`, and one `score` question; re-verify determinism on
   a long payload; **limit probes**: 5 simultaneous requests → 429 `user_concurrent`, oversized
   body → 413, a request held past the queue window → 503 with `retry_after_s`, and confirm the
   `Retry-After` header and body field agree; **embeddings probe** (local Ollama
   `qwen3-embedding:8b` and ARC `Qwen3-Embedding-4B`): capture request/response fixtures, confirm
   **4096** vs **2560** widths and norm 1.0, test list input + batch cap, force an over-context
   input to learn truncation-vs-error, compare raw vs `Instruct: …\nQuery: …` prefixes, record
   latency; **CFBD probe** (`/lines` for 2021 week 1: `spreadOpen` null rate and provider mix;
   `/venues`: lat/lon/elevation/dome/timezone; no key → SKIP); **weather probe** (Open-Meteo
   Historical Forecast for one 2021 and one 2025 venue-date: variable coverage, actual lead/run
   cadence; compare Previous Runs `_previous_day1`); Brave/Fetch/Deep
   Research endpoints or MCP handshake; `import chromadb`; disk space. Emit
   `docs/CAPABILITIES.md` with PASS/FAIL/SKIP + timestamp + redacted evidence.
2. Scaffold the repository tree, `requirements*.txt`, `.env.example`, `Makefile`, `ruff`/`black`/
   `pytest` config, `.gitignore` (append `data/`, `reports/`, `.venv/`, `*.db`, `*.log`).
3. Implement `Settings`, logging, `Clock`, hashing, error taxonomy, and `adapters/http.py`
   (timeouts, retries, circuit breaker) with tests.
4. Define the six core contracts (`SlateGame`, `PreconditionSpec`, `RuleSpec`, `ScreenMatch`,
   `UpsetScore`, `RankedAlert`) and export JSON Schemas.
5. Walking skeleton: fixture slate (3 games) + fixture specs (2 rules) → `domain/rules.py` +
   `domain/screen.py` → `domain/scoring.py` (rule-count + base rate) → `app.py` Streamlit table.
   Wire `agent_events` to an in-memory trace for the timeline.
6. Record the capability matrix outcome in `PROGRESS.md` → Decisions log (which backends are in
   play: D1/D2/D3/D8, plus the measured `EMBED_DIM`).

**Files.** `scripts/probe.py`, `cfb_upset/{config.py,logging_setup.py,ids.py}`, `cfb_upset/contracts/
{__init__,slate,spec,monitor,scoring}.py`, `cfb_upset/domain/{rules,screen,scoring}.py`,
`cfb_upset/adapters/http.py`, `app.py`, `Makefile`, `.env.example`, `tests/unit/test_rules.py`,
`tests/e2e/test_walking_skeleton.py`, `docs/CAPABILITIES.md`.

**Deliverables.** Probe report; installable repo (`pip install -r requirements.txt` succeeds);
`streamlit run app.py` renders a fixture slate and a ranked alert; `make test` green.

**Acceptance criteria.**
- `docs/CAPABILITIES.md` exists and every external dependency is marked PASS/FAIL with a chosen
  backend recorded, including a captured `systemone` request/response contract and a fixture
  under `tests/fixtures/systemone/`.
- The `systemone` probe is repeatable: the same request twice yields the same decision payload
  (or the observed dispersion is documented).
- The probe records the 4-request cap, 30 s queue window, 8,192-token input limit, 8 MiB body limit,
  and the exact `400/429/502/503` payloads, plus golden fixtures for all three question types and
  the measured determinism/latency of `decision.vllm-sr/d3-mini`.
- `pytest` passes with ≥90% coverage on `domain/rules.py` and `domain/screen.py`.
- The Streamlit app renders the fixture slate, accepts an Analyze click, and shows a ranked game
  with a timeline containing at least three `agent` values.
- No secrets in the repo; `git check-ignore .env` succeeds.

**Testing.** Unit: rule evaluation (all operators, missing values, type coercion). E2E:
`streamlit.testing.v1.AppTest` drives the app with fixtures. Manual: run the probe with and
without credentials to confirm graceful SKIP.

**Requirement coverage.** R1 (skeleton), R20, R21 (initial), R24 (admission policy stub),
R19 (harness stub), course deliverable scaffolding.

**Effort.** 1.5 d. **Gate:** capability matrix reviewed before P1 begins.

---

### P1 — Foundations: contracts, persistence, provenance, tool adapters

**Objective.** Turn the skeleton into a contract-first platform: every handoff typed, every field
provenanced, every provider behind a fault-tolerant adapter with fixtures.

**Prerequisites.** P0.

**Tasks.**
1. Full contract catalogue (§4.6) with `extra="forbid"`, enums, UTC validators, and JSON Schema
   export to `docs/contracts/`.
2. SQLite schema + migration runner implementing §4.7 (all tables, indexes on `game_id`,
   `(spec_id, version)`, `analysis_cache.cache_key`, `agent_events.run_id`). Seed `teams`, `venues`
   (lat/lon/altitude/dome/timezone from CFBD `/venues`, with a checked-in CSV fallback).
3. Repositories with typed methods per aggregate; forbid raw SQL outside `store/`.
4. `evidence.py`: snapshot writer (gzip + sha256), `evidence_links` writer.
5. Adapters with fixture transports: `espn.py` (typed parse of scoreboard, summary, core odds,
   weekly rankings, groups/FBS), `cfbd.py` (lines + venues, optional key), `weather.py`, `geocode.py`, `search.py`, `fetch.py` (whitelist +
   text extraction + snapshot), `deep_research.py` (MCP client + seeded provider), `llm.py`
   (JSON-only, retries, token ledger), `embeddings.py`, `chroma.py`.
6. `observability/trace.py`: JSONL trace + `agent_events` writer; `budget.py` with deadlines.
7. `domain/leakage.py`: `known_at` policy table as data, `admit(field)` function, violation logging.
8. Contract rejection tests: every model rejects extra keys, wrong enums, naive datetimes.

**Files.** `cfb_upset/contracts/*`, `cfb_upset/store/*`, `cfb_upset/adapters/*`,
`cfb_upset/observability/*`, `cfb_upset/domain/leakage.py`, migrations, fixtures, tests.

**Deliverables.** Migrated DB (`data/cfb.db`); adapters usable offline via fixtures; schema JSON;
`make test` green.

**Acceptance criteria.**
- `python -m cfb_upset.store.db --init` creates all tables; `--verify` prints table + row counts.
- Each adapter has a fixture-backed test and a `live`-marked smoke test that skips without keys.
- `LeakageError` is raised for any field with `known_at >= kickoff` in a unit test.
- Trace records contain `run_id`, `agent`, `phase`, `event_type`, `ts` for a scripted run.
- Chroma round-trip test passes with the hashing embedder (CI has no Ollama) and skips cleanly if
  `chromadb` is unavailable; the real 4096-d space is exercised in P6.9.

**Testing.** Unit: contracts, repositories, leakage policy, retry/circuit breaker, cache keys.
Integration: adapter fixture parity (parsed record fields match expectations).

**Requirement coverage.** R8 (schema/Chroma), R15 (tables), R21, R22 (retry/budget), R24
(admission), R16 (structure).

**Effort.** 1.5 d.

---

### P2 — Historical corpus ingestion (Pipeline 1)

**Objective.** Populate a validated, deduplicated, provenance-complete 2021–2025 FBS-vs-FBS corpus
using the `Data-Orchestrator` and two parallel `Historical-Stats Workers`.

**Prerequisites.** P1.

**Tasks.**
1. `Data-Orchestrator`: enumerate seasons/types/weeks via ESPN scoreboard; filter to FBS-vs-FBS
   using group 80 membership; partition `game_id` batches across `WORKER_COUNT` (default 2)
   workers; aggregate; dedupe by `game_id`; validate; store; emit `IngestReport`.
2. `Historical-Stats Worker`: per game, fetch summary (box score, venue, competitors, status),
   weekly rankings, core odds; return `HistoricalGameRecord` with per-field `known_at`.
3. Pydantic validation of aggregated records; quarantine invalid records with `errors_json`
   (alt branch); continue on partial failure.
4. Compute `games`, `game_fields`, `teams`, `venues` rows. **Box scores are stored for label/future
   feature use only** and are explicitly marked post-game so they can never be admitted as
   features for that game.
5. Coverage report: games per season/week, FBS-vs-FBS counts, fields non-null % per season/team
   (R32), favorite source distribution, and a list of unsupported fields.
6. CLI: `python -m cfb_upset.pipelines.ingest_corpus --seasons 2021 2022 2023 2024 2025 [--weeks]
   [--resume]`. Idempotent; `--resume` skips `game_id`s already stored.

**Files.** `agents/data_orchestrator.py`, `agents/historical_stats_worker.py`,
`pipelines/ingest_corpus.py`, `domain/coverage.py`, tests + fixtures (1 week per season, 5 games).

**Deliverables.** `data/cfb.db` with ≈3,000+ FBS-vs-FBS games (≈700/season, subject to coverage report); `reports/coverage_<ts>.md`/`.json`;
quarantine table populated only for genuinely bad records.

**Acceptance criteria.**
- Corpus contains only FBS-vs-FBS games (spot-check: no FCS opponent rows); count within ±5% of
  the independently derived per-season FBS-vs-FBS count (recomputed from the team-group cache).
- Every stored field has `known_at`, `source`, and `fetched_at`; zero fields with
  `known_at >= kickoff` in `game_fields`.
- Dedupe: `COUNT(*) = COUNT(DISTINCT game_id)`.
- Two-worker run is < 1.5× the wall clock of a one-worker run on the same 40-game batch (R6).
- Coverage report lists non-null % for every column, season, and team (R32).

**Testing.** Integration with recorded fixtures (week scoreboard + 5 summaries + odds + rankings):
exact expected row counts. Live smoke (marked): 1 week, assert >0 games and no exceptions.
Fault injection: summary 500 for one game → record quarantined, rest succeed. Resume test:
re-run does not duplicate rows and performs no duplicate fetches.

**Requirement coverage.** R4, R6, R8 (corpus), R10 (historical field groups), R22, R24, R32.

**Effort.** 1.5 d. **Gate:** corpus + coverage accepted before any labeling.

---

### P3 — Leakage-safe features, favorite determination, and chronological splits

**Objective.** Turn the corpus into a modelling table in which every value was knowable before
kickoff, with explicit provenance and the mandated splits.

**Prerequisites.** P2.

**Tasks.**
1. `domain/features.py`: rolling pre-game features computed only from earlier kickoffs — wins,
   point differential, offensive/defensive scoring rates, SOS proxy, last-3 form, rest days,
   travel distance (venue lat/lon haversine), time-zone delta, altitude, neutral site, conference
   game, poll rank, rank delta, home/away, short-week flag, look-ahead flag (next opponent rank),
   and season-to-date pace. All with `feature_version` and `known_at`.
2. Favorite/odds: CFBD `spreadOpen` → favorite, then ESPN `open`, then strength proxy
   (`elo_diff` / rolling margin); open lines → implied probability (moneyline when present, else a
   fixed spread→probability mapping); record `favorite_source`, `line_provider`,
   `market_prob_source`; store `market_prob` only when admitted.
3. Label definition: `upset = favorite_loses`; store `upset` and `margin` for evaluation only.
4. `domain/stats.py` split helper: `dev=2021–2023`, `val=2024`, `test=2025`; assert no overlap and
   no post-cutoff rows. Write `game_features` and a modelling view/parquet
   (`data/features_v1.parquet`).
5. Missing-data audit by feature/season/team, and an explicit `feature_availability` report used
   later to reject specs whose required fields are too sparse.
6. Leakage tests: sentinel injection; recompute features with post-kickoff rows deleted and assert
   bit-identical output.

**Files.** `domain/features.py`, `domain/splits.py`, `pipelines/build_features.py`,
`configs/features.yaml`, tests, `reports/features_<ts>.md`.

**Deliverables.** Feature table + availability report + leakage audit; documented favourite
policy.

**Acceptance criteria.**
- Zero rows in the modelling table have a feature with `known_at >= kickoff` (SQL + code audit).
- Deleting all games after a cutoff and recomputing does not change features for games before it.
- `market_prob` coverage reported; for seasons without open lines, `favorite_source=strength_proxy`
  and `market_prob_source=unavailable` are recorded on every affected game; `line_provider` is set
  whenever a book quote was used.
- Split assertions pass: 2021–23 / 2024 / 2025 disjoint and ordered.
- Feature availability report lists non-null % by feature × season.

**Testing.** Unit: rolling windows exclude the current game; rest/travel math on synthetic
schedules; vig removal; Elo update ordering. Property: permuting input row order does not change
features (after sorting by kickoff).

**Requirement coverage.** R10, R24, R25 (split infrastructure), R31 (dev/val/test), R32.

**Effort.** 1.0 d.

---

### P4 — Precondition discovery and spec store (Pipeline 2a)

**Objective.** Produce a versioned set of operationalizable `PreconditionSpec`s from literature,
one research pass per candidate, with rejections reasoned and stored.

**Prerequisites.** P1 (contracts), P3 (field availability).

**Tasks.**
1. `configs/preconditions/candidates.yaml`: ~20 candidates (rest/short week, travel distance and
   time zones, look-ahead spot, letdown after ranked win, revenge game, new coach, quarterback
   change, turnover-luck regression, close-game luck, advanced-efficiency mismatch vs. market,
   conference underdog, night game, altitude, weather, rival game, post-bye, Thursday short week,
   blue-blood letdown, transitive strength, motivation/bowl eligibility). Each with a research
   brief (definition, plausible thresholds, moderators, counter-evidence).
2. `Research Worker`: one research call per candidate via `ResearchProvider`, then an LLM
   extraction step constrained to `ResearchReport` + optional `RuleSpec`. Prompts require citations
   with URLs and reported effect sizes; output validated; one repair attempt; then drop.
3. `deep_research.py`: MCP client (JSON-RPC over HTTP with timeout) and `seeded_literature`
   provider that returns the catalog entry + curated citations. Provider recorded per report.
4. `Research-Orchestrator`: partition candidates across `WORKER_COUNT` (default 2) in `par`;
   validate each report; operationalizability gate (`field ∈ allowed set`, `op ∈ allowed ops`,
   threshold numeric with units, required fields available in `features` coverage); write
   `precondition_spec` (immutable, version 1) and activate in `spec_store`; log rejection reasons.
5. Deduplicate semantically similar candidates by canonical rule hash; keep the better-supported
   one, log the merge.
6. CLI: `python -m cfb_upset.pipelines.build_preconditions --stage research [--provider auto]
   [--only candidate_key]`.

**Files.** `agents/research_orchestrator.py`, `agents/research_worker.py`,
`research/{catalog.py,seed_preconditions.yaml}`, `adapters/deep_research.py`,
`pipelines/build_preconditions.py`, tests + fixtures.

**Deliverables.** ≥12 operational specs (target 20 candidates, expect 12–16 encodable);
`reports/research_<ts>.md` with per-candidate status and citations; populated tables.

**Acceptance criteria.**
- Exactly one research call per candidate (R26), asserted by a counting fake provider.
- Every candidate ends in `precondition_spec` with either an active spec or a rejection reason;
  no silent drops.
- All specs validate against `RuleSpec`; no `eval`, no arbitrary code, no unknown fields; a spec
  referencing an unavailable field is rejected with that reason.
- Versioning: re-running with `--bump` creates version 2 and leaves version 1 intact and readable.
- Both provider modes produce the same contract shape; the mode is stored and visible.

**Testing.** Unit: extractor repair path, gate rejections (prose rule, unknown field, missing unit,
non-numeric threshold), canonical hash dedupe. Integration: 4 candidates end-to-end with a fake
provider. Live (marked): one real Deep Research call if configured.

**Requirement coverage.** R5, R6 (parallel research), R7, R21, R26, R27.

**Effort.** 1.5 d.

---

### P5 — Deterministic labeler and rule screen

**Objective.** Apply every spec to every game deterministically, with an evidence trail, and
expose the same evaluator as the pre-research screen.

**Prerequisites.** P3, P4.

**Tasks.**
1. `domain/rules.py`: whitelisted field registry with types/units; operators `gt, ge, lt, le, eq,
   ne, in, not_in, between, is_true, is_false`; `missing_policy ∈ {UNKNOWN, FALSE}`; returns
   `(state ∈ {TRUE, FALSE, UNKNOWN}, evidence)` where evidence records field, observed value,
   threshold, and source `known_at`.
2. `domain/labeler.py`: for each `(game, active spec)` produce `LabeledGame` with `label ∈ {0,1,
   UNKNOWN}`, `evaluable`, evidence JSON, `labeler_version`. Never crash on missing fields; count
   UNKNOWN. Batch and stream to SQLite with `INSERT OR REPLACE` keyed on the unique constraint.
3. Guard: labeler asserts each referenced field is admitted (`known_at < kickoff`) and raises
   `LeakageError` otherwise.
4. `domain/screen.py`: same evaluator over `SlateGame` + `match_context`, returning `ScreenMatch`
   per game with matched specs and observed values; short-circuits when no active specs.
5. Determinism: canonical JSON (sorted keys, fixed float formatting) for evidence; a golden-hash
   test over a fixed corpus.
6. CLI: `build_preconditions --stage label`.

**Files.** `domain/{rules,labeler,screen}.py`, `pipelines/build_preconditions.py` (stage),
`tests/unit/test_rules_matrix.py`, `tests/unit/test_labeler_determinism.py`.

**Deliverables.** `labeled_games` populated for all active specs; label coverage report
(evaluable %, UNKNOWN %, positives per spec); golden hashes.

**Acceptance criteria.**
- Every (game, active spec) pair has exactly one row; `COUNT = games × active_specs`.
- Running the labeler 3× yields identical content hashes (R28).
- A spec referencing a post-kickoff field is rejected before labeling.
- Zero exceptions across the full corpus; UNKNOWN rate reported per spec.
- Screen and labeler share the same evaluator (import-level test) and agree on a fixture slate.

**Testing.** Operator truth table (14 cases/operator), missing/None/NaN handling, type coercion
(string "7" vs 7), determinism hash, full-corpus smoke (must finish under 2 minutes).

**Requirement coverage.** R8 (labeled_games), R9 (labeler half), R24, R28, R29 (shared engine).

**Effort.** 1.0 d.

---

### P6 — Statistical validation, label audit, promotion, citation index

**Objective.** Decide which preconditions are real signal and which labels are trustworthy, with
FDR control and out-of-sample checks; promote only what survives.

**Prerequisites.** P5.

**Tasks.**
1. `domain/stats.py`: contingency tables; RD with cluster-bootstrap CI; OR (raw + adjusted
   logistic with `logit(market_prob)` and strength); BH-FDR via `statsmodels.stats.multitest.
   multipletests` (cross-checked against a hand implementation); per-split results; stability
   across dev seasons; likelihood-ratio test for incremental value.
2. Promotion engine: apply §8.2 acceptance; write `stat_results` for every spec/split and
   `validated_preconditions` with `validated|provisional|rejected`, reasons, effect JSON,
   citations. Never overwrite history; new runs append with timestamp.
3. Label audit (R30): stratified sample of 50 pairs; fetch ≤3 whitelisted pages published
   `< kickoff`; snapshot; extract candidate passages; anonymise; `Adjudicator` returns
   HOLD/NOT_HOLD/UNKNOWN + quote; compute precision, recall (planted positives), Wilson CIs;
   write `label_audits` and `reports/label_audit_<ts>.md`.
4. One tuning round: adjust thresholds for specs with precision < 0.80; re-label; re-test; log
   before/after. Requires `--approve` when `REQUIRE_APPROVAL=1`.
5. Citation index: embed accepted citations with the active Ollama space (`qwen3-embedding:8b`,
   4096) and upsert into that collection with model/dim/instruction metadata; if Ollama is down,
   fail loudly rather than mixing spaces; verify by retrieving top-3 for each spec.
6. CLI: `build_preconditions --stage validate [--approve]`.

**Files.** `domain/stats.py`, `domain/calibration.py` (shared), `domain/promotion.py`,
`agents/adjudicator.py`, `pipelines/build_preconditions.py`, `adapters/{embeddings,chroma}.py`,
`reports/`.

**Deliverables.** `stat_results` for all specs; `validated_preconditions` with statuses;
label-audit report; Chroma collection; `docs/EVALUATION.md` (validation section).

**Acceptance criteria.**
- BH implementation matches `statsmodels` on 1,000 random p-vectors (max abs diff < 1e-12).
- Null simulation (2,000 synthetic corpora with no effect, 20 specs) keeps the family-wise false
  discovery proportion ≤ 0.10 at q=0.10 (allow Monte-Carlo tolerance).
- Planted-effect corpus: a spec with a true +12 pp effect is promoted; a null spec is not.
- Every `validated` spec has ≥1 citation, an effect JSON, a split, and a reason field.
- Audit report states sample size, precision/recall with CIs, and UNKNOWN count; precision <0.80
  specs cannot be `validated`.
- Chroma retrieval returns the correct `spec_id` in the top 3 for ≥80% of queries.

**Testing.** Unit: RD/OR/CI math against hand-computed values; BH; Wilson CI; promotion truth
table. Integration: synthetic corpus (planted signal) through label→stats→promotion. Fault:
empty dev split, zero positives, all-UNKNOWN spec → rejected with a clear reason, no crash.

**Requirement coverage.** R9, R30, R31, R24 (audit evidence timestamps), R8 (Chroma), R5 (Brave+
Fetch for audit).

**Effort.** 1.5 d. **Gate:** promotion results reviewed and approved before the monitor pipeline
uses them.

---

### P7 — Daily slate, rule screen, and monitor pipeline (Pipeline 3a)

**Objective.** From a real slate, deterministically shortlist games, confirm or drop flags with
cited evidence in parallel workers, and return a typed, cached result — no LLM required to
demonstrate the flow.

**Prerequisites.** P5 (screen), P6 (active specs), P1 (adapters, cache).

**Tasks.**
1. `adapters/espn.py` slate reader: scoreboard for date (default today) → filter FBS-vs-FBS →
   `SlateGame` with teams, records, venue, kickoff, odds (pre-kickoff only, ESPN scoreboard),
   broadcast, logo, color; live weather via Open-Meteo forecast with `known_at = fetched_at`; mark
   `unavailable` explicitly rather than omitting. CFBD is not required at runtime.
2. `Monitor-Orchestrator`: load active specs; build per-game context from features/slate; run
   `screen`; emit events; handle empty shortlist; partition shortlist across workers; aggregate
   and dedupe; then hand confirmed flags to the scorer.
3. `Monitor Worker`: per game — seed query from matched specs + Chroma similar citations, Brave
   search (whitelist), fetch ≤`MAX_FETCHES_PER_GAME` pages, snapshot evidence, build an anonymised
   evidence bundle, and ask `decision.vllm-sr/d3-mini` one `choice` question with criteria
   `{confirmed, contradicted, insufficient}`; `confirmed` requires `P ≥ CONFIRM_THRESHOLD`,
   `contradicted` requires `P ≥ DROP_THRESHOLD`, otherwise `insufficient`. The criteria frame
   `contradicted` as "the strongest evidence says this flag is false" (Pr5). Return
   `MonitorDecision` with probabilities, confidence, quotes, and `dissent`; `LLM_MODE=off` confirms
   only when a whitelisted source explicitly contains the required predicate phrase.
4. Rationale builder: template with matched specs, observed values, quotes, URLs; LLM rewrite
   optional and verified against the citation set.
5. `analysis_cache`: key = hash(game, active spec versions, context hash, scorer version, prompt
   version); replay returns identical `RankedAlert` and skips providers.
6. Failure handling: per-game isolation; worker crash → game marked `not_evaluated` with reason;
   budget exhaustion → partial result `degraded=true`.
7. `pipelines/run_monitor.py` CLI for CI/demo: `--date`, `--games`, `--offline`.

**Files.** `agents/monitor_orchestrator.py`, `agents/monitor_worker.py`,
`pipelines/run_monitor.py`, `store/cache.py`, `ui/progress.py` (event writer), tests + fixtures.

**Deliverables.** A runnable monitor pipeline returning `RunResult`; events for UI; cache;
`reports/run_<id>.json` trace.

**Acceptance criteria.**
- Zero-match slate: zero search/fetch calls, result reason `no_preconditions_matched` (R29).
- Only selected games are processed; assert provider call count equals selected shortlist size
  (R12).
- Two workers active concurrently; events show interleaved worker ids (R17).
- Every confirmed flag has a rationale and ≥1 `evidence_id` resolvable to a snapshot (R13/R18).
- All-dropped case returns `no_qualifying_flags` without calling the scorer.
- Second identical run: 100% cache hits, zero provider calls, byte-identical result JSON (R23).
- With `LLM_MODE=off`, the pipeline completes end-to-end using the deterministic fallback.

**Testing.** Integration with mocked Brave/Fetch fixtures: confirmed, dropped, and unreachable
cases. Fault suite: 429, timeout, empty results, malformed JSON, 10MB page, non-whitelisted domain,
prompt-injection payload in page text (assert it is treated as data and no tool/rules change).
Concurrency: 6 games, 2 workers, assert both progress streams.

**Requirement coverage.** R2 (selection input), R5, R10, R11, R12, R13, R17, R18 (evidence),
R22, R23, R29, R6.

**Effort.** 1.5 d.

---

### P8 — Upset-Scorer, ranking, and the evaluation harness

**Objective.** Turn confirmed flags into calibrated probabilities and a stable 1..n ranking, and
build the backtest harness that will produce R25 evidence.

**Prerequisites.** P7, P3 (splits/features), P6 (validated/provisional specs).

**Tasks.**
1. `agents/upset_scorer.py`: backend selection per probe/`SCORER_BACKEND`; build `ScoreRequest`
   with market probability, matched specs + observed values, evidence refs, context; validate
   `UpsetScore`; force `probability ∈ [0,1]`, `confidence`, `key_signals`, `citations`,
   `backend`, `model_version`, `unstable`.
2. `adapters/systemone.py` + `d3_mini_backend.py`: `SystemOneClient` with a process-wide semaphore of
   4, local Pydantic request validation (avoid 400s), strict builder for `noul`/`choice`/`score`
   questions, deterministic payload budgeter (≤8,192 tokens per question, ≤8 MiB body, question cap),
   raw + calibrated probability, request/response snapshots, and the §4.9.1 retry matrix; fallback
   to `calibrated_rules` on repeated failure (flagged).
3. `calibrated_rules` backend: feature matrix builder; logistic fit on 2021–23; model selection
   (Platt vs isotonic) on 2024 by log loss; artifact persistence (`data/models/scorer_v1.json`
   with coefficients, feature list, calibration knots, training window, git SHA).
4. Ranking: total order with tie-breaks; `rank` assigned over candidates; non-candidates excluded
   from the alert list but scored for evaluation.
5. `pipelines/backtest.py`: replay the structured path for 2021–2025 with `calibrated_rules`, compute
   all §8.3 metrics and baselines, bootstrap CIs, calibration plot, confusion at thresholds,
   precision@k; run the stratified `d3_mini` sample (D14) separately; write
   `reports/eval_<ts>/{metrics.json,calibration.png,report.md}`.
6. Repeatability harness: `pipelines/repeatability.py` runs N=5 on a frozen slate and reports
   Jaccard/τ/spread.
7. Wire scorer into `Monitor-Orchestrator` (confirmed flags → ranked alerts → `RunResult`).

**Files.** `agents/upset_scorer.py`, `agents/scoring_backends/{d3_mini,calibrated}.py`, `adapters/systemone.py`,
`domain/scoring.py`, `pipelines/{backtest,repeatability}.py`, `configs/eval.yaml`, tests.

**Deliverables.** Scoring + ranking + rationale; fitted model artifact; evaluation harness
runnable in < 5 minutes on cached features; repeatability report.

**Acceptance criteria.**
- `probability ∈ [0,1]` for every scored game; ranks are unique and contiguous 1..n (R14/R18).
- Backend is recorded per score; a `systemone` contract mismatch or repeated timeout degrades to
  `backend=calibrated_rules` with `degraded_reason` set and is surfaced in the UI (R22).
- A recorded `systemone` golden fixture parses into a valid `UpsetScore`; a schema change fails the
  test rather than silently producing a score.
- Concurrency test: 20 queued games never exceed 4 in-flight `systemone` requests; a simulated 429
  waits exactly `retry_after_s` and retries; 413 shrinks the payload once; 503 after two retries
  degrades that game only.
- Payload budgeter test: a maximal evidence bundle is truncated deterministically below 8,192
  tokens and the truncation is recorded (`truncated=true`, dropped evidence ids).
- Question-type tests: `noul` maps to `probability = calibrated P(yes)`; `choice` maps to an enum
  with probabilities and confidence; `score` maps to a finite value in `[0, n−1]` with a legend; a
  malformed criteria payload raises before any network call.
- Baseline metrics exist for all five baselines on 2025; the market baseline uses only admitted
  odds (R25).
- Repeatability with the deterministic backend: τ = 1.0 and probability spread = 0 by construction;
  with `d3_mini`: meets §8.4 thresholds or games are flagged `unstable` (R19).
- Model artifact contains training window, feature list, coefficients, calibration, git SHA; a
  test asserts no test-season data in the fit (R24/R25).

**Testing.** Unit: ranking tie-breaks, probability clamping, calibration math, metric functions
against `sklearn` references. Integration: synthetic slate through scorer. Statistical: planted
effect recovered; baseline computation correct on a tiny hand-checked dataset.

**Requirement coverage.** R14, R18, R19, R22, R25, R6 (parallel scoring optional).

**Effort.** 1.5 d (harness can be built in P8 while P9 proceeds).

---

### P9 — Streamlit application

**Objective.** Deliver the graded front-end: browse and filter the slate, select games, run the
agents, watch activity live, read ranked alerts with citations, rerun freely, and audit artifacts.

**Prerequisites.** P7, P8.

**Tasks.**
1. `app.py` shell + pages: **Slate**, **Run**, **Audit**, **Preconditions**, **Evaluation**.
2. Slate page: date selector (default today, D12), table with team logos/colors, rank, record,
   kickoff, venue, favourite, spread, weather (or `unavailable`); sortable columns and filters
   (conference, ranked only, favourite margin ≥ N, team search); multiselect default all.
3. Run page: Analyze button → `RunController` (background thread + queue, D11) → live timeline by
   agent (screen, worker 1, worker 2, scorer) with elapsed time, status, retries, cache hits;
   cancel button; budget indicator; partial/degraded banners.
4. Results: ranked alert cards with probability, confidence badge, matched specs + observed values,
   rationale, citation chips (domain + publication date + quote), and a "why not higher?" section
   listing unmatched specs. Empty-state messages exactly as specified: "No upset alerts for this
   slate" / "No qualifying upset alerts."
5. Cache behaviour: show "cached" badge and a "Re-analyze" control that bypasses cache with a
   confirmation.
6. Audit page: run list, per-run events, SQLite table browser (read-only), evidence snapshot viewer,
   trace download.
7. Preconditions page: specs with status, effect sizes, CIs, q-values, citations, approval action
   (human gate).
8. Evaluation page: metrics table + calibration plot + baseline comparison (reads
   `reports/eval_*/metrics.json`).
9. Accessibility/responsiveness: reasonable column widths, no horizontal scrolling at 1280px,
   keyboard-usable controls, `st.session_state` isolation between runs.
10. Demo mode: `DEMO_MODE=offline` loads a pre-warmed slate + cache so the showcase works without
    network.

**Files.** `app.py`, `cfb_upset/ui/{pages/*,components.py,progress.py,state.py}`.

**Deliverables.** Five working pages; screenshots in `docs/`; `AppTest` e2e suite.

**Acceptance criteria.**
- `AppTest` e2e: load slate (fixture), filter to one team, select 2 games, Analyze, see 2 ranked
  alerts, see ≥4 distinct agents in the timeline, see citations, then rerun and see cache badges.
- No unhandled exception when providers fail: user sees a degraded banner and partial results.
- Three consecutive runs with different selections produce no cross-run state bleed (R3).
- Every displayed probability is accompanied by a citation set and a score backend label (R18).
- Audit page can retrieve any `evidence_id` from the last run and show its snapshot.
- Page renders in <2s with cached data on a laptop-sized viewport.

**Testing.** `streamlit.testing.v1.AppTest` scenarios (empty slate, no matches, degraded, cached,
approval required). Manual checklist in `docs/DEMO_SCRIPT.md`.

**Requirement coverage.** R1, R2, R3, R11 (display), R18, R19 (display of stability), R22, R23.

**Effort.** 1.5 d.

---

### P10 — End-to-end evaluation, coverage, and reports

**Objective.** Produce the graded evidence that the system works and is calibrated, and document
what it cannot do.

**Prerequisites.** P8 (harness), P2–P6 (data), P9 (optional).

**Tasks.**
1. Run the full pipeline in order on real data: ingest 2021–2025 → features → research → label →
   validate → fit scorer → backtest. Record wall-clock, token/API usage, and cache hit rates.
2. Generate `reports/eval_<ts>/report.md` containing: dataset description and counts; per-split
   N and base rates; the precondition validation table (RD, CI, OR, p, q, status); label-audit
   precision/recall; system metrics (Brier, log loss, ECE, AUC, precision@k) with bootstrap CIs
   for all five baselines; calibration plot; repeatability results; a limitations section
   (deviation D6, missing fields, weather/odds caveats, class imbalance).
3. **Coverage/data-quality report** (R32): non-null % by field × season × team; list of fields
   marked unsupported; favourite-source distribution; games excluded and why.
4. Copy the summary into `docs/EVALUATION.md` with links to artifacts.
5. Sanity-check numbers against independent hand calculations for one season and one spec.

**Files.** `pipelines/backtest.py`, `docs/EVALUATION.md`, `reports/`, `Makefile` target `make eval`.

**Deliverables.** `metrics.json`, `calibration.png`, `report.md`, `coverage` report, and a one-page
summary suitable for the showcase table.

**Acceptance criteria.**
- All five baselines reported for 2025 with N, Brier, log loss, CIs.
- Calibration plot has 10 bins with counts and a diagonal reference; ECE reported.
- The precondition table lists every candidate with status and reason; no silent exclusions.
- Repeatability report present with the §8.4 thresholds evaluated explicitly.
- Report contains an explicit statement of what was replayed (D6) and what was not.
- Numbers are reproducible: `make eval` twice yields identical metrics within 1e-9 (seeded).

**Testing.** Golden test on metric functions; a regression test that the committed
`metrics.json` schema validates; a test that baseline (a) equals the empirical base rate.

**Requirement coverage.** R25, R31 (reported), R32, R19, R16 (documented results).

**Effort.** 1.0 d (mostly compute + writing).

---

### P11 — Reliability hardening, UML, and documentation

**Objective.** Prove the non-functional requirements, generate the graded diagrams, and make the
project explainable at Q&A.

**Prerequisites.** All prior phases.

**Tasks.**
1. Fault-injection suite: provider timeouts, 429/500, malformed JSON, empty payloads, DNS failure,
   disk full simulation, SQLite lock, Chroma unavailable, LLM refusal, budget exhaustion, oversized
   page. Assert no crash, correct degraded flags, and preserved partial results.
2. Leakage suite: sentinel tests at ingestion, features, labeler, monitor payload; a static test
   that no code path reads `home_score`/`away_score`/`boxscore` for the same game's features.
3. Validator-validation: planted defects (wrong label, fabricated citation, spec with unknown
   field, score out of range, tampered cache entry); assert detection rate = 100% on the suite.
4. Repeatability + consistency report (R19) wired into `make check`.
5. UML: `docs/uml/class.mmd` (agents, contracts, stores, adapters, relationships) and
   `seq_phase{1,2,3}.mmd` (from the design doc, updated to implementation names). Render to
   **`docs/uml/cfb_upset_uml.pdf`** via Quarto/Typst (F15). Add `tests/test_docs_consistency.py`
   asserting every agent class in the class diagram exists in `cfb_upset/agents/`, every table in
   the diagram exists in the migrations, and every env key in `.env.example` is read by
   `Settings` and vice versa.
6. `docs/ARCHITECTURE.md`: component narrative, ADR-style decisions (D1–D13), measured parallelism
   (1 vs 2 workers), measured fault isolation, provenance walkthrough (one alert traced end to end),
   and "why multi-agent" evidence.
7. `README.md` rewrite: quickstart, run order, env keys, architecture summary, evaluation results,
   known limitations, troubleshooting. Verify on a clean venv.
8. Code quality: ruff/black clean, docstrings, no dead code, no secrets, `TODO` inventory.

**Files.** `tests/{unit,integration,e2e,reliability}/`, `docs/uml/*`, `docs/ARCHITECTURE.md`,
`README.md`, `tests/test_docs_consistency.py`.

**Deliverables.** UML PDF; architecture doc; hardening suite; clean README.

**Acceptance criteria.**
- `make check` = lint + tests + leakage + repeatability all green.
- Fault suite: 100% of injected faults produce a typed degraded outcome, 0 uncaught exceptions.
- Planted-defect detection: 100% of the seeded defects caught; the validator is demonstrably not
  gameable by editing tests (tests are read-only for agents).
- UML PDF opens, contains all classes/actors, and the consistency test passes.
- A fresh clone + `pip install` + `make demo-offline` reaches a ranked alert in under 5 minutes.

**Testing.** The suite itself; plus a manual "hostile reviewer" pass: try to find a leakage path,
a crash path, and an unsourced claim.

**Requirement coverage.** R16, R19, R22, R24, R21, R8 (verified), plus rubric deliverables
(UML, code quality, multi-agent justification).

**Effort.** 1.5 d.

---

### P12 — Showcase rehearsal, packaging, and submission

**Objective.** Freeze, rehearse, and submit without last-minute changes.

**Prerequisites.** P11, evaluation complete.

**Tasks.**
1. Tag `v1.0-demo`; freeze code on 2026-12-01.
2. `docs/DEMO_SCRIPT.md`: 7-minute walkthrough (problem → architecture → live run → evidence →
   evaluation → limitations), Q&A crib sheet with the 10 most likely questions and where the code
   answers them.
3. `scripts/seed_demo.py`: pre-warm the showcase slate, spec set, cache, and evidence snapshots;
   verify `DEMO_MODE=offline` completes in <60s with no network.
4. Rehearse twice: once online, once with the network disabled. Fix only demo-blocking issues.
5. `make package`: zip source excluding `data/`, `reports/`, `.venv/`, `.env`, caches; include
   README, `.env.example`, UML PDF, `IMPLEMENTATION_PLAN.md`, `PROGRESS.md`, and a link to where
   evaluation artifacts would live (do not ship multi-GB data).
6. Final checklist per §12; confirm `.env` is not in the archive (`unzip -l | grep -v`).
7. Submit the zip and UML PDF to Canvas before 17:00 on 2026-12-03.

**Deliverables.** `cfb_upset_profiler_submission.zip`, UML PDF, rehearsal notes, demo slate cache.

**Acceptance criteria.**
- Offline demo produces a ranked alert with ≥2 citations in <60s.
- Archive size < 25 MB; contains no secrets; README run instructions verified by a second person or
  fresh shell.
- All §12 checklist items checked.

**Requirement coverage.** Course submission mechanics, R16, R20, showcase demo.

**Effort.** 0.5 d.

---

## 10. Schedule, critical path, and scope ladder

### 10.1 Critical path

`P0 → P1 → P2 → P3 → P4 → P5 → P6 → P7 → P8 → P9 → P10 → P11 → P12`

The statistical path (P3–P6) and the monitoring path (P7–P8) are the long poles. P9 can start once
P7's contract is frozen (page skeleton + fixtures), and P8's backtest harness can run in the
background while P9 is built.

### 10.2 Day plan (aggressive; assumes long autonomous sessions)

| Date | Work | Milestone |
| --- | --- | --- |
| Sun 11-22 | P0 | Probe matrix; walking skeleton on fixtures |
| Mon 11-23 | P1 | Schema + adapters + contracts |
| Tue 11-24 | P2 (+ P3 start) | **Real corpus ingested; demoable screen on a real slate** |
| Wed 11-25 | P3, P4 start | Features + leakage audit + candidate catalog |
| Thu 11-26 | P4, P5 | Specs + labeler |
| Fri 11-27 | P6 | Stats + audit + promotions (**gate**) |
| Sat 11-28 | P7 | Monitor pipeline with citations |
| Sun 11-29 | P8 (+ P10 background) | Scorer + model artifact + backtest run |
| Mon 11-30 | P9 | UI complete |
| Tue 12-01 | P10 close-out, P11 start; **freeze** | Eval report + UML PDF |
| Wed 12-02 | P11/P12 | Hardening, rehearsal, package |
| Thu 12-03 | Showcase | Demo + submit |

### 10.3 Scope ladder (cut from the bottom when behind)

1. Weather features (D3) — keep the column as `unavailable`; no spec requires it.
2. `d3_mini` integration (D1) — ship `calibrated_rules` with shadow logging disabled (only if the
   P0 `systemone` contract cannot be established, or if the service is saturated during the demo;
   saturation is recorded, not hidden).
3. Deep Research live provider (D2) — ship seeded literature with citations.
4. Chroma semantic retrieval — keep storage + display of accepted citations (R8 still satisfied);
   drop "seed queries from similar citations".
5. LLM rationale rewriting — deterministic templates only.
6. Evaluation breadth — report 2025 test + 2024 validation only; keep all baselines.
7. Optional corpus extension (D13) — never enable.
8. **Never cut:** leakage enforcement, provenance, Pydantic gates, FDR stats, cache, repeatability,
   UML PDF, README, `.env.example`.

---

## 11. Testing and evaluation strategy

### 11.1 Pyramid

| Layer | Scope | Tooling | Gate |
| --- | --- | --- | --- |
| Unit | rules, features, leakage, stats math, cache keys, contracts, calibration | pytest | 100% pass, ≥85% coverage on `domain/` |
| Contract | every Pydantic model: valid, invalid, extra keys, enums, timezone | pytest | 100% pass |
| Integration | adapters with recorded fixtures; orchestrator + workers; DB round-trip | pytest + respx | 100% pass |
| Statistical | planted-signal corpora, null simulation, metric parity | pytest (slow marker) | FDR control + power checks |
| E2E | Streamlit via `AppTest`; CLI pipelines | pytest + AppTest | 100% pass |
| Reliability | fault injection, repeatability, leakage sentinels, planted defects | pytest | 100% pass |
| Live | optional provider smoke tests | `pytest -m live` | Run manually before freeze |

Commands: `make test` (offline, <5 min), `make test-slow` (statistical, <20 min),
`make check` (lint + tests + leakage + repeatability), `make eval`, `make demo-offline`.

### 11.2 Required test artifacts in the repo

- `tests/fixtures/espn/`: one week scoreboard per season (2021–2025), 5 summaries, odds, rankings.
- `tests/fixtures/search|fetch/`: 10 canned results/pages including a prompt-injection page.
- `tests/fixtures/corpus/`: synthetic labelled dataset with one strong spec, one null spec, one
  missing-data spec.
- `tests/fixtures/research/`: valid report, prose-only report, report with unknown field.
- `reports/` outputs referenced by README (not committed if large; commit the summary + metrics).

### 11.3 Evaluation as a graded artifact

`docs/EVALUATION.md` must contain: the precondition table (with FDR q-values), the label-audit
precision/recall, the system metrics with all baselines, the calibration plot, the repeatability
table, and the limitations. This is the answer to "are the results meaningful?" at the showcase.

---

## 12. Deliverables checklist

- [ ] Fully functional multi-agent system (three pipelines, named agents, real handoffs)
- [ ] Streamlit UI exposing agent activity, slate filtering, selection, reruns, audit views
- [ ] UML class diagram (`.mmd` + PDF) consistent with code (test-enforced)
- [ ] Three sequence diagrams (`.mmd` + same PDF) matching the implemented loops/par/alt/opt
- [ ] Documented Python source (module docstrings, public API docs, inline comments on math/leakage)
- [ ] `README.md` with reproducible setup, run order, `.env` keys, limitations
- [ ] `.env.example` with every key, no values; `.env` git-ignored and absent from the archive
- [ ] Automated tests: unit, contract, integration, statistical, e2e, reliability
- [ ] Evaluation results: Brier, log loss, calibration, baselines, FDR table, label audit,
      repeatability, coverage/null-rate report
- [ ] Capability matrix (`docs/CAPABILITIES.md`) with fallbacks documented
- [ ] Architecture document with measured multi-agent justification
- [ ] Demo script + offline demo mode + pre-warmed cache
- [ ] Submission zip (<25 MB) and UML PDF uploaded by 2026-12-03 17:00

---

## 13. Risk register

| # | Risk | L | I | Mitigation / trigger | Fallback |
| --- | --- | --- | --- | --- | --- |
| 1 | `systemone` (d3-mini) contract undocumented or unstable | L | H | **Contract captured 2026-11-22 (§4.9.1) and deterministic at tested length**; P0 pins golden fixtures; contract test + shadow mode; dispersion check on long payloads | `calibrated_rules` (D1), degraded flag |
| 2 | Deep Research/Brave/Fetch unavailable or costly | H | H | Provider adapters, fixtures, budgets | Seeded literature (D2); offline evidence |
| 3 | Historical pre-kickoff odds missing (2021) | M | M | CFBD `/lines` backfill + 2021 null-rate probe; record `favorite_source`/`line_provider`; sensitivity analysis | Strength proxy (D4) |
| 4 | Weather leakage or no coverage | M | M | Archived forecast with recorded actual lead (≤6 h) and `known_at`; coverage gate; optional IEM MOS check | Drop weather specs (D3) |
| 5 | No precondition passes FDR | M | H | Power extension option; report honestly | `provisional` tier (D7) |
| 6 | Statistical overfitting via tuning | M | H | One tuning round; dev-only tuning; 2025 held out | Reject tuned specs |
| 7 | Nondeterminism breaks R19 | M | H | Decision-model probabilities replace token sampling; determinism probe in P0; 3-repeat subset; dispersion flag | Deterministic `calibrated_rules` backend |
| 8 | Streamlit long-run UI breakage | M | M | Background thread + events (D11) | CLI run + cached result display |
| 9 | Showcase night has no slate | M | H | Date selector + pre-warmed demo slate | Offline demo (D12) |
| 10 | Leakage sneaks in | M | H | Sentinel tests, admission policy, audit | Block promotion |
| 11 | Time overrun | H | H | Scope ladder, freeze date, living artifacts | Ship MVP + evaluation subset |
| 12 | UML PDF toolchain missing | L | M | Quarto/Typst path identified | Mermaid PNG → PDF via Quarto HTML |
| 13 | ESPN rate limiting / schema drift | M | M | Concurrency caps, fixture parity tests, quarantine | Resume + cached raw |
| 14 | Prompt injection from fetched pages | M | M | Whitelist, delimit, no tool instructions, snapshots | Deterministic fallback |
| 15 | Disk/DB growth (raw summaries) | M | L | Store extracted fields only; compress snapshots | Retention policy |
| 16 | `systemone` saturation or queue timeouts during demo/eval | M | H | Hard cap 4, Retry-After handling, budget + priority ordering, D14 sampling, pre-warmed demo cache | `calibrated_rules` with `scoring_degraded` flag |
| 17 | Ollama not running where the app is graded/run | M | M | Startup health check + visible status; demo uses cached query embeddings; collection metadata pins the space | Re-index in the ARC 2560-d space (separate collection) or use each spec's direct citations with `retrieval_degraded` |

---

## 14. Assumptions and open questions

**Assumptions.**
- VT ARC credentials are available in `.env` (`OPEN_AI_API_KEY` / `OPEN_AI_ENDPOINT`, accepted as
  aliases for `VT_ARC_API_KEY` / `VT_ARC_BASE_URL`); verified 2026-11-22.
- Local Ollama serves `qwen3-embedding:8b` at `http://localhost:11434/v1` and is running whenever a
  fresh analysis or re-index is performed; the offline demo uses cached query embeddings.
- The VT ARC gateway also serves `Qwen3-Embedding-4B` (2560-d) as an optional secondary space.
- A CFBD academic key is present in `.env`; the app still runs without it.
- Open-Meteo's non-commercial free tier with attribution is acceptable for coursework.
- ESPN public endpoints remain accessible and unauthenticated for scoreboard/summary/odds/rankings.
- Open-Meteo historical-forecast and geocoding endpoints remain keyless and rate-tolerant for
  ≈3,500 games (one request per game-venue-date, cached).
- The 2025 season is complete and stable; 2026 is live for demo purposes.
- A single developer/agent executes the plan; no parallel human team.
- Graders accept documented deviations when they are visible in the README/UI and preserve the
  requirement's intent.

**Open questions (resolve in P0 and record in `PROGRESS.md`).**
1. ~~What are the exact JSON field names for `POST /api/v1/systemone`?~~ **Resolved 2026-11-22**:
   `{model, state, questions{name:{type, instructions, criteria}}}` → `answers{name:{noul | choice
   +probabilities +confidence | score +legend +probabilities +confidence}}` + `usage`; see §4.9.1
   and the golden fixtures P0.1 adds.
2. Is the 4-request-per-user limit shared with other teammates/apps running under the same VT ARC
   identity at showcase time, and should the demo reserve headroom (e.g., run at 2)?
3. Are Brave Search, Fetch, and Deep Research available as MCP endpoints with credentials, and
   what are their quotas?
4. Does the grading/demo machine run Ollama? Default is local `qwen3-embedding:8b` (4096);
   if not, rebuild the citation index in the ARC `Qwen3-Embedding-4B` space (2560). Collections are
   separate and versioned, so switching requires a re-index, not a config flip.
5. May the corpus extend to 2016–2020 for statistical power (D13), given R25's mandated splits?
6. Should closing lines be admitted with `known_at = kickoff` (violates strict `<`) for the market
   baseline, or is the open line / strength proxy the only admissible market signal?
7. Does the instructor require the four SQLite tables to be exactly those names with no side
   tables (D5), or is a superset acceptable?
8. For R30, is a fixed sample of 50 spec-game pairs acceptable, or is a specific n required?
9. When CFBD returns several books, which precedence is canonical (e.g., consensus > DraftKings >
   ESPN BET), and is a spread-derived `market_prob` acceptable when open moneylines are absent?

---

## 15. Definition of done

A phase is done when: tasks complete; acceptance criteria objectively verified; tests green;
`PROGRESS.md` updated; no unrecorded deviation; artifacts committed. The **project** is done when:

1. All P0–P12 gates pass and `make check`, `make eval`, `make demo-offline` succeed from a clean
   clone.
2. The three pipelines run end to end on real data and produce the four SQLite tables plus Chroma
   citations.
3. A real slate produces a ranked, cited upset list in the Streamlit UI with visible agent activity,
   and a rerun is demonstrably consistent and cached.
4. `docs/EVALUATION.md` reports precondition validation (FDR, CIs, out-of-sample) **separately**
   from system predictive performance (Brier, log loss, calibration) against five baselines, with
   limitations stated.
5. UML PDF, README, `.env.example`, tests, and the submission zip exist and are verified.
6. The offline demo completes in under 60 seconds.

---

## Appendix A — Capability probe results (observed 2026-11-22 in this environment)

These are facts gathered during planning; they justify D1–D8 and D16/D17, and must be re-run in P0.

| Capability | Result | Evidence |
| --- | --- | --- |
| ESPN scoreboard (historical) | PASS — 25–64 events/day; no odds, no weather fields | `dates=20210904/20231118/20251115` |
| ESPN scoreboard (future slate) | PASS — odds present (DraftKings), `STATUS_SCHEDULED` | `dates=20261128` |
| ESPN per-event odds | PASS — spreads and providers; `open` present for 2023/2024, absent in sampled 2021 | core `.../odds` for `401281942`, `401628543` |
| ESPN summary | PASS — boxscore, gameInfo/venue, header, standings; **no weather** | `summary?event=401628543` |
| ESPN rankings | PASS — weekly ranking collections exist | `seasons/2024/types/2/weeks/10/rankings` |
| FBS classification | PASS — group `80` = FBS, `81` = FCS | `.../groups/80`, `.../groups/81` |
| Venue coordinates | FAIL — ESPN venue has city/state only | `.../venues/3626` |
| Open-Meteo forecast archive | PASS — keyless hourly forecast for a past date; GFS archive starts 2021-03-23; the stitched series has an effective lead ≤6 h (not 24 h); Previous Runs `_previous_day1` has full-variable coverage only from 2024 | `historical-forecast-api.open-meteo.com`; Open-Meteo docs 2026-11-22 |
| CFBD lines | PASS (documented) — `/lines` returns `spreadOpen`, `overUnderOpen`, `spread`, moneylines, and provider; free academic tier 3,000 calls/mo; 2021 open-line null rate unverified | `api.collegefootballdata.com` docs 2026-11-22 |
| CFBD venues | PASS (documented) — `/venues` returns lat/lon/elevation/dome/timezone | `api.collegefootballdata.com` docs 2026-11-22 |
| VT ARC model list | PASS — ids include `GLM-5.3`, `gpt-oss-120b`, `claude-on-arc`, `DeepSeek-V4.1-Flash`, `Qwen3-Embedding-4B`, `decision.vllm-sr/d3-mini` | `GET /api/v1/models` with `OPEN_AI_API_KEY` 2026-11-22 |
| VT ARC embeddings | PASS — `POST /api/v1/embeddings` with `Qwen3-Embedding-4B` → 200, **2560-d**, norm 1.0; the Ollama-style id `qwen3-embedding:8b` → **500** | live probe 2026-11-22 |
| Local Ollama embeddings | PASS — `qwen3-embedding:8b` via `http://localhost:11434/v1/embeddings` → 200, **4096-d**, norm 1.0; Ollama also lists `gemma4:12b`, `qwen3.8:27b` | live probe 2026-11-22 |
| VT ARC decision models | PASS — `POST /api/v1/systemone` `{model,state,questions{}}`; `noul`/`choice`/`score` all 200; identical request 3× deterministic; `/chat/completions` → 404 with guidance | live probe 2026-11-22; §4.9.1 |
| `systemone` limits | 4 queued/running per user; 30 s queue wait; 8,192 input tokens; 8 MiB body; ≤8 images; 429/502/503 semantics with `retry_after_s` | owner-provided limits 2026-11-22 |
| `systemone` model/API | `decision.vllm-sr/d3-mini`; `state` + object of named questions; `noul` (P yes), `choice` (option + probabilities), `score` (0..n−1 + legend + probabilities); confidence 0..1; 400 on malformed requests; cost ∝ input × questions | owner-provided semantics + captured wire fixture 2026-11-22 |
| Brave endpoint reachable | PARTIAL — HTTP 422 without a key (endpoint exists) | `api.search.brave.com` |
| MCP servers configured | FAIL — none in `opencode.json`; no env keys | config + env scan |
| ChromaDB installed | FAIL — not importable (installable from PyPI; PyPI reachable) | import probe |
| Quarto / Node / Pandoc | PASS — `quarto`, `npx`, `pandoc` present; no Graphviz/LaTeX | tool probe |
| Existing Python deps | PASS — Python 3.13.5 (3.12.3 also), pydantic 2.10.3, streamlit 1.45.1, httpx 0.28.1, statsmodels 0.14.4, sklearn 1.6.1, pytest 8.3.4, respx, tenacity; 2.8 TB free | `python -V`, `pip list`, `df -h` |
| Working credentials | PASS — `.env` holds `OPEN_AI_API_KEY`, `OPEN_AI_ENDPOINT`, `OLLAMA_ENDPOINT`, `EMBED_MODEL`, `CFBD_API_KEY`; file is git-ignored and untracked | `.env` scan (values not printed); `git check-ignore -v .env` |
| ARC schema discovery | FAIL — `GET /api/v1/openapi.json` returns the Open WebUI HTML shell (200 `text/html`); `/openapi.json` and `/docs` are 404 | live probe 2026-11-22; §4.9.1 fixture is the contract of record |

## Appendix B — Environment variables (`.env.example`)

```
# --- VT ARC ---
VT_ARC_API_KEY=                          # alias accepted: OPEN_AI_API_KEY (current .env)
VT_ARC_BASE_URL=https://llm-api.arc.vt.edu/api/v1   # alias accepted: OPEN_AI_ENDPOINT
VT_ARC_MODEL=GLM-5.3
VT_ARC_EXTRACTOR_MODEL=GLM-5.3
VT_ARC_ADJUDICATOR_MODEL=gpt-oss-120b
VT_ARC_DECISION_ENDPOINT=/systemone      # relative to the base URL (already ends in /api/v1)
VT_ARC_DECISION_MODEL=decision.vllm-sr/d3-mini   # listed in /models; /chat/completions returns 404
SCORER_BACKEND=auto                      # auto | d3_mini | calibrated_rules
SYSTEMONE_MAX_CONCURRENCY=4              # hard cap; values >4 are rejected at startup
SYSTEMONE_MAX_INPUT_TOKENS=8192
SYSTEMONE_MAX_REQUEST_BYTES=8388608
SYSTEMONE_QUEUE_WAIT_S=30
SYSTEMONE_SCORE_TIMEOUT_S=45
SYSTEMONE_MAX_QUESTIONS_PER_GAME=2
MAX_SCORED_GAMES=20
CONFIRM_THRESHOLD=0.60                    # monitor worker: P(confirmed) cutoff, fitted on audits
DROP_THRESHOLD=0.40                       # monitor worker: P(contradicted) cutoff
ALERT_THRESHOLD=0.50                      # optional display cutoff; probabilities always shown

# --- Research / web tools ---
BRAVE_API_KEY=
BRAVE_BASE_URL=https://api.search.brave.com/res/v1
FETCH_BASE_URL=
DEEP_RESEARCH_BASE_URL=
RESEARCH_PROVIDER=auto                   # auto | mcp_deep_research | seeded_literature
ALLOWED_DOMAINS=espn.com,sports-reference.com,cbssports.com,si.com

# --- Embeddings / vector store ---
EMBED_BACKEND=ollama                     # ollama | arc | hashing
OLLAMA_BASE_URL=http://localhost:11434/v1   # alias accepted: OLLAMA_ENDPOINT
OLLAMA_EMBED_MODEL=qwen3-embedding:8b    # alias accepted: EMBED_MODEL
OLLAMA_EMBED_DIM=4096                    # measured 2026-11-22; assert on every response
EMBED_BASE_URL=                          # ARC secondary; default: VT_ARC_BASE_URL
EMBED_API_KEY=                           # ARC secondary; default: VT_ARC_API_KEY
ARC_EMBED_MODEL=Qwen3-Embedding-4B
ARC_EMBED_DIM=2560                       # measured 2026-11-22; separate collection only
EMBED_DIM=4096                           # active space; must match EMBED_BACKEND
EMBED_MAX_INPUT_TOKENS=2048              # keep well below Ollama's context; no silent truncation
EMBED_BATCH_SIZE=8
EMBED_MAX_CONCURRENCY=2
EMBED_INSTRUCTION_TEMPLATE=              # query prefix; empty => send raw text
CHROMA_PATH=./data/chroma

# --- Data / storage ---
SQLITE_PATH=./data/cfb.db
CACHE_PATH=./data/cache
EVIDENCE_PATH=./data/evidence
TRACE_PATH=./data/traces
ESPN_API_BASE_URL=https://site.api.espn.com/apis/site/v2/sports/football/college-football
ESPN_CORE_BASE_URL=https://sports.core.api.espn.com/v2/sports/football/leagues/college-football

# --- Secondary structured data (optional) ---
CFBD_API_KEY=                            # free academic key; absent => ESPN + strength proxy
CFBD_BASE_URL=https://api.collegefootballdata.com
CFBD_LINE_PROVIDERS=consensus,DraftKings,ESPN_BET   # precedence; first available wins
CFBD_MAX_CONCURRENCY=2

# --- Weather ---
WEATHER_BACKEND=open_meteo               # open_meteo | unavailable
WEATHER_HIST_BASE_URL=https://historical-forecast-api.open-meteo.com/v1/forecast
WEATHER_FORECAST_BASE_URL=https://api.open-meteo.com/v1/forecast
WEATHER_MODEL=gfs_seamless
WEATHER_LEAD_HOURS_MAX=6                 # recorded provenance for the stitched archive

# --- Runtime ---
WORKER_COUNT=2
RUN_BUDGET_SECONDS=300
MAX_GAMES_PER_RUN=25
MAX_FETCHES_PER_GAME=3
MAX_PAGES_PER_RUN=75
LLM_MODE=required                        # required | off
REQUIRE_APPROVAL=1
DEMO_MODE=live                           # live | offline
LOG_LEVEL=INFO
```

## Appendix C — Demo script outline (7 minutes)

1. **Problem (45s).** Markets are accurate; upsets still happen; analysts lack time to check
   travel/rest/look-ahead/revenge across a 60-game slate.
2. **Why multi-agent (60s).** Show the three pipelines; show the trace proving two monitor workers
   ran concurrently; show that a failed search for one game did not affect others.
3. **Historical validation (90s).** Preconditions page: rule, support, risk difference + CI, FDR
   q-value, label-audit precision, citation.
4. **Live run (150s).** Pick a slate, Analyze, watch the timeline, read a ranked alert with quotes.
5. **Rerun (30s).** Rerun the same slate: cache badge, identical ranking (R19).
6. **Evaluation (60s).** Brier/log loss vs. market and base-rate baselines; calibration plot;
   limitations stated plainly.
7. **Q&A crib (rest).** Point to `docs/ARCHITECTURE.md`, the leakage test, the contract tests, and
   the decisions log for every design choice.

## Appendix D — Phase → requirement coverage summary

| Phase | Requirements |
| --- | --- |
| P0 | R1*, R19*, R20, R21*, R24* |
| P1 | R8, R15, R21, R22, R24, R16 |
| P2 | R4, R6, R8, R10, R22, R24, R32 |
| P3 | R10, R24, R25*, R31*, R32 |
| P4 | R5, R6, R7, R21, R26, R27 |
| P5 | R8, R9, R24, R28, R29* |
| P6 | R5, R8, R9, R30, R31, R24 |
| P7 | R2*, R5, R6, R10, R11, R12, R13, R17, R18*, R22, R23, R29 |
| P8 | R14, R18, R19, R22, R25 |
| P9 | R1, R2, R3, R11, R18, R19, R22, R23 |
| P10 | R25, R31, R32, R19, R16 |
| P11 | R16, R19, R21, R22, R24, R8 |
| P12 | R16, R20 + course submission |

`*` = infrastructure/stub first satisfied here and completed in the phase named in §3.1.
