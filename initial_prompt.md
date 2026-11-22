You are a senior software architect and AI systems engineer tasked with planning the implementation of a multi-agent NCAA Division I FBS Upset Condition Profiler.

Thoroughly review all documents in `./reference_documents` before developing the plan. These documents define the project's intended architecture, functional requirements, grading criteria, and multi-agent reliability principles.

Your task is to create a detailed, actionable, dependency-aware implementation plan that an autonomous coding agent can execute incrementally.

## 1. Requirements and Architecture Analysis

- Extract all functional and nonfunctional requirements, preserving their original requirement numbers.
- Identify mandatory deliverables from the course specifications and grading rubric.
- Analyze the proposed architecture, including its three major pipelines:
  1. Historical structured-data ingestion.
  2. Upset precondition discovery and statistical validation.
  3. Daily matchup monitoring and upset-risk ranking.
- Identify agents, tools, data stores, validation mechanisms, and their interactions.
- Distinguish mandatory requirements from proposed implementation choices.
- Identify contradictions, missing dependencies, unnecessary complexity, and feasibility concerns.
- Do not silently change the documented architecture. Explain and justify proposed deviations.

## 2. Implementation Strategy

Design a phased development roadmap that progresses from foundational components to a fully functional system.

For each phase, provide:

- **Objective:** What the phase accomplishes.
- **Prerequisites:** Dependencies on earlier phases.
- **Implementation tasks:** Specific, actionable development steps.
- **Files and modules:** Proposed files, directories, and responsibilities.
- **Deliverables:** Concrete outputs expected upon completion.
- **Acceptance criteria:** Objective conditions that must be satisfied.
- **Testing:** Unit, integration, or end-to-end validation procedures.
- **Requirement coverage:** Original requirement numbers addressed.

Prioritize building a minimal working end-to-end pipeline early, then incrementally replace simplified components with production implementations.

Ensure the plan accounts for asynchronous/parallel agent execution, Pydantic contracts, SQLite and ChromaDB persistence, external APIs, MCP integrations, the decision model, and Streamlit.

## 3. Reliability and Statistical Validation

Incorporate relevant practices from `ten_principles_for_reliable_multi_agent_systems.md`, particularly:

- Deterministic validation instead of relying on LLM agreement.
- Independent verification and falsification where appropriate.
- Evidence provenance and traceable citations.
- Strict agent boundaries and structured handoffs.
- Failure handling, retries, caching, and bounded execution.
- Human intervention at consequential decision points.
- Evaluation against simpler baselines.

Preserve the project's statistical requirements, including:

- Deterministic precondition labeling.
- Effect sizes, confidence intervals, and FDR correction.
- Out-of-sample evaluation.
- Chronological train/validation/test splits.
- Prevention of post-kickoff data leakage.
- Brier score, log loss, and calibration analysis.
- Repeatability and consistency of upset rankings.

Clearly distinguish between validating the statistical significance of preconditions and evaluating the predictive performance of the complete system.

## 4. Feasibility and Scope Management

Evaluate the feasibility of the proposed technologies and data sources before scheduling their implementation.

Pay particular attention to:

- Availability of historical pre-kickoff data.
- ESPN API data coverage and limitations.
- Web research costs and scalability.
- Availability and suitability of Deep Research, Brave, Fetch, and d3-mini.
- Historical evidence collection and potential data leakage.
- Runtime and computational constraints.

Recommend cost-effective alternatives when necessary, but document tradeoffs and requirement implications.

Prioritize a reliable, demonstrable solution over unnecessary sophistication.

## 5. Project Deliverables

Ensure the implementation plan explicitly addresses all course deliverables, including:

- Fully functional multi-agent system.
- Streamlit interface exposing agent activity.
- UML class and sequence diagrams consistent with the implementation.
- Documented Python source code.
- README with reproducible setup and execution instructions.
- `.env.example` without exposed credentials.
- Automated testing and evaluation results.
- Live showcase demonstration.
- Submission-ready project archive and UML PDF.

## 6. Planning and Progress Tracking

Create two files in the project root:

**`IMPLEMENTATION_PLAN.md`**

Include the architecture assessment, proposed repository structure, numbered implementation phases, dependencies, tasks, acceptance criteria, requirement traceability, testing strategy, and final completion checklist.

**`PROGRESS.md`**

Create a phase-by-phase checklist for tracking implementation progress, completed tasks, remaining work, blockers, and architectural decisions.

Design each phase to be executable in a separate coding session without requiring conversational history. The files should serve as the persistent source of truth for implementation.

## 7. Final Instructions

- Do not write or modify application code.
- Do not begin implementing any phases.
- Do not fabricate API capabilities, available data, or model performance.
- Prefer deterministic implementations where LLM reasoning is unnecessary.
- Preserve the intended multi-agent architecture unless a deviation is explicitly justified.
- Keep the implementation plan sufficiently detailed to guide development without becoming unnecessarily verbose.
- Prioritize requirements that contribute to the grading rubric and successful end-to-end functionality.

After creating the planning documents, provide a concise summary of the proposed phases, the most significant technical risks, and any recommended architectural changes.

**Your only task is to analyze, evaluate, and plan the implementation.**