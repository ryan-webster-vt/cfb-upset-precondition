## 1. Title

**Upset Radar: Precondition Profiler for College Football**

*Finding the games where the better team is most at risk.*

Ryan Webster, ADS 5984 Agentic AI in Practice, Virginia Tech.

Status: (planned) Design-only repo; everything below is the specified design.

## 2. The problem

The user is a college football analyst or reporter researching dozens of FBS matchups on deadline. Today, upset risk means manually checking advanced stats, travel, rest, revenge spots, and look-ahead traps, often undone. This system screens the slate against validated preconditions and returns a ranked, cited shortlist.

## 3. Agent personas

1.  **Data-Orchestrator** — historical corpus builder. In: seasons, weeks. Out: deduplicated validated games, coverage, quarantine logs. Tools: ESPN API via workers, Pydantic, SQLite. Hands to: Historical-Stats Workers; corpus feeds Research-Orchestrator.
2.  **Historical-Stats Worker 1** — parallel ESPN retrieval. In: game-ID batch. Out: game_id-keyed records (schedule, box scores, stats, venue, rankings). Tools: ESPN API. Hands to: Data-Orchestrator.
3.  **Historical-Stats Worker 2** — same contract.
4.  **Research-Orchestrator** — turns research into validated rules. In: \~20 preconditions. Out: validated_preconditions, labeled_games, citations. Tools: Research Workers, Pydantic, Spec Store, Labeler, Statistical Tools, Brave+Fetch, ChromaDB. Hands to: Research Workers; publishes rules for Monitor-Orchestrator.
5.  **Research Worker 1** — per-precondition research. In: precondition batch. Out: report, citations, effect sizes, operational rule when possible. Tools: Deep Research MCP. Hands to: Research-Orchestrator.
6.  **Research Worker 2** — same contract.
7.  **Monitor-Orchestrator** — daily slate screener. In: selected game IDs. Out: confirmed flags with rationale, citations, or no-alert. Tools: SQLite rules, Rule Screen, Monitor Workers, Upset-Scorer. Hands to: Monitor Workers, Upset-Scorer, UI.
8.  **Monitor Worker 1** — confirms or drops flags. In: games, matched rules. Out: decision, evidence, citations, progress. Tools: game data, Brave Search MCP, Fetch MCP. Hands to: Monitor-Orchestrator.
9.  **Monitor Worker 2** — same contract.
10. **Upset-Scorer** — turns flags into risk. In: flags, rationale, evidence. Out: probabilities, 1-to-n ranking, evidence. Tools: VT ARC d3-mini. Hands to: Monitor-Orchestrator; UI displays.

## 4. Knowledge stores and tools

All planned; no graph database or separate memory store is specified.

1.  **SQLite corpus** — games plus precondition_spec/spec_store/labeled_games/validated_preconditions; orchestrators, labeler, rule screen.
2.  **Spec Store** — versioned PreconditionSpecs; Research-Orchestrator.
3.  **ChromaDB** — citation vectors, metadata; Research-Orchestrator.
4.  **qwen3-embedding:8b** — embeds citations for Research-Orchestrator.
5.  **ESPN API** — historical data, daily slate, odds; stats workers, UI.
6.  **Deep Research MCP** — definitions, thresholds, moderators, counter-evidence, citations; Research Workers.
7.  **Brave Search MCP** — web search; Research-Orchestrator, Monitor Workers.
8.  **Fetch MCP** — page retrieval; same users.
9.  **VT ARC d3-mini** — upset probabilities; Upset-Scorer.
10. **Deterministic Labeler** — applies specs, emits evidence; Research-Orchestrator.
11. **Statistical Validation Tools** — effect sizes, CIs, FDR, out-of-sample; Research-Orchestrator.
12. **Deterministic Rule Screen** — structured screening; Monitor-Orchestrator.
13. **Pydantic Validator** — schema gate; both orchestrators.
14. **Cache** — analyzed results; UI.
15. **Streamlit UI** — slate, selection, progress, results.

## 5. How the agents interact

Orchestrator-worker with pipeline stages; workers report only to their orchestrator.

1.  Phase 1: Data-Orchestrator fans batches to two Historical-Stats Workers, then aggregates, validates, stores.
2.  Phase 2: Research-Orchestrator fans preconditions to two Research Workers, gates, labels, tests, spot-checks.
3.  Phase 3: Monitor-Orchestrator loads rules, screens, fans the shortlist to two Monitor Workers.
4.  Confirmed flags go to Upset-Scorer; rankings return to the UI.
5.  Phases run in order; Phase 3 repeats per run.

## 6. The agentic loop(s)

Main daily loop, triggered by Analyze: (planned)

1.  User selects games, clicks Analyze; UI submits IDs and Monitor-Orchestrator loads rules.
2.  Rule Screen checks every rule against structured data; empty shortlist ends with "no upset alerts."
3.  Otherwise two Monitor Workers take the shortlist; per game: Brave search, Fetch, confirm/drop, attach citations, stream progress.
4.  Orchestrator aggregates; all dropped ends with "no qualifying upset alerts."
5.  Confirmed flags go to Upset-Scorer; d3-mini estimates probabilities and ranks risk.
6.  UI caches and shows rankings, reasoning, citations; run ends, can rerun.

Human: analyst sets scope, triggers, watches progress, judges citations; no approval gate.

Phase 2 reflection loop:

1.  One Deep Research pass per precondition.
2.  Schema gate rejects non-operational rules with reasons.
3.  Rules label the corpus; statistics filter by effect size, CI, FDR, out-of-sample validity.
4.  Brave+Fetch spot-checks labels; precision/recall tune rules.
5.  Changed rules trigger re-label, re-test, threshold updates, then citation embedding.

Only retry loop; Phase 3 single-pass; Phase 1 failures quarantined.

## 7. Guardrails

1.  Pydantic schemas at every handoff; invalid records/specs rejected.
2.  Deterministic rules, citations, confirm-or-drop, whitelisted sources (ESPN.com, Sports-Reference.com, credible local media).
3.  known_at on fields, report_time on fetches; missing or post-kickoff data discarded.
4.  Effect sizes, CIs, FDR, out-of-sample tests; probabilities validated 2021-23 train, 2024 validation, 2025 test via log loss, Brier, calibration.
5.  d3-mini probability scoring; repeat runs cached.
6.  Wrapped API/LLM/MCP calls; explicit empty results; .env excluded; no automated betting.
7.  Batched contexts limit hallucination and overflow.

## 8. Why multi-agent

One prompt would mix ingestion, research, screening, scoring, causing overflow and weaker output. Separate workers parallelize preconditions and games, and each handoff becomes a small, auditable schema. Orchestrators keep the plan fixed.

## 9. Example run

Request: analyst opens the app on a Saturday, keeps all FBS games selected, clicks Analyze.

1.  UI loads slate; Monitor-Orchestrator screens all games.
2.  A ranked favorite on short rest after travel trips two rules; a Monitor Worker searches, fetches, confirms, cites.
3.  Upset-Scorer assigns a probability and ranks it.
4.  Analyst gets score, rationale, evidence; empty result stated explicitly.