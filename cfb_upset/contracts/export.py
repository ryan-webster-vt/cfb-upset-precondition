"""Export Pydantic JSON Schemas for the docs/UML appendix.

Run with ``make schemas`` or ``python -m cfb_upset.contracts.export``.
"""

from __future__ import annotations

import json
from pathlib import Path

from cfb_upset.contracts import (
    AgentEvent,
    CacheEntry,
    Citation,
    ConfirmedFlag,
    FetchedPage,
    GameIdBatch,
    HistoricalGameRecord,
    IngestReport,
    LabelAudit,
    LabeledGame,
    LabelEvidence,
    MonitorDecision,
    MonitorTask,
    OddsInfo,
    PreconditionSpec,
    Provenance,
    QuarantineRecord,
    RankedAlert,
    ResearchBrief,
    ResearchReport,
    RuleEvidence,
    RuleSpec,
    RunResult,
    ScoreRequest,
    ScreenMatch,
    SearchHit,
    SlateGame,
    SpecPromotion,
    StatResult,
    TeamInfo,
    UpsetScore,
    ValidatedPrecondition,
    VenueInfo,
    WeatherInfo,
)

OUTPUT_DIR = Path("docs/contracts")

MODELS = {
    "AgentEvent": AgentEvent,
    "CacheEntry": CacheEntry,
    "Citation": Citation,
    "ConfirmedFlag": ConfirmedFlag,
    "FetchedPage": FetchedPage,
    "GameIdBatch": GameIdBatch,
    "HistoricalGameRecord": HistoricalGameRecord,
    "IngestReport": IngestReport,
    "LabelAudit": LabelAudit,
    "LabelEvidence": LabelEvidence,
    "LabeledGame": LabeledGame,
    "MonitorDecision": MonitorDecision,
    "MonitorTask": MonitorTask,
    "OddsInfo": OddsInfo,
    "PreconditionSpec": PreconditionSpec,
    "Provenance": Provenance,
    "QuarantineRecord": QuarantineRecord,
    "RankedAlert": RankedAlert,
    "ResearchBrief": ResearchBrief,
    "ResearchReport": ResearchReport,
    "RuleEvidence": RuleEvidence,
    "RuleSpec": RuleSpec,
    "RunResult": RunResult,
    "ScoreRequest": ScoreRequest,
    "ScreenMatch": ScreenMatch,
    "SearchHit": SearchHit,
    "SlateGame": SlateGame,
    "SpecPromotion": SpecPromotion,
    "StatResult": StatResult,
    "TeamInfo": TeamInfo,
    "UpsetScore": UpsetScore,
    "ValidatedPrecondition": ValidatedPrecondition,
    "VenueInfo": VenueInfo,
    "WeatherInfo": WeatherInfo,
}


def export_schemas(output_dir: Path = OUTPUT_DIR) -> list[Path]:
    """Write one schema file per contract and return the written paths."""

    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, model in MODELS.items():
        path = output_dir / f"{name}.schema.json"
        path.write_text(
            json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written


def main() -> None:
    for path in export_schemas():
        print(path)


if __name__ == "__main__":
    main()
