"""Public contract catalogue.

Import from ``cfb_upset.contracts`` rather than from the individual modules so
that a later refactor cannot silently change an agent handoff.
"""

from cfb_upset.contracts.common import Citation, Provenance, StrictModel, UTCDateTime
from cfb_upset.contracts.history import (
    GameIdBatch,
    HistoricalGameRecord,
    IngestReport,
    QuarantineRecord,
)
from cfb_upset.contracts.labels import (
    Adjudication,
    DatasetSplit,
    LabelAudit,
    LabeledGame,
    LabelEvidence,
    StatResult,
)
from cfb_upset.contracts.monitor import (
    AgentEvent,
    ConfirmedFlag,
    MatchedSpec,
    MonitorDecision,
    MonitorDecisionType,
    MonitorTask,
    RuleEvidence,
    ScreenMatch,
    ScreenState,
)
from cfb_upset.contracts.research import (
    ResearchBrief,
    ResearchReport,
    SpecPromotion,
    UpsetDefinition,
    ValidatedPrecondition,
)
from cfb_upset.contracts.scoring import (
    CacheEntry,
    RankedAlert,
    RunResult,
    RunStatus,
    ScoreBackend,
    ScoreRequest,
    UpsetScore,
)
from cfb_upset.contracts.slate import (
    FavoriteSource,
    GameStatus,
    MarketProbSource,
    OddsInfo,
    SlateGame,
    TeamInfo,
    VenueInfo,
    WeatherInfo,
)
from cfb_upset.contracts.spec import (
    MissingPolicy,
    PreconditionSpec,
    PreconditionStatus,
    RuleOp,
    RuleSpec,
)
from cfb_upset.contracts.tools import FetchedPage, SearchHit

__all__ = [
    "Adjudication",
    "AgentEvent",
    "CacheEntry",
    "Citation",
    "ConfirmedFlag",
    "DatasetSplit",
    "FavoriteSource",
    "FetchedPage",
    "GameIdBatch",
    "GameStatus",
    "HistoricalGameRecord",
    "IngestReport",
    "LabelAudit",
    "LabelEvidence",
    "LabeledGame",
    "MarketProbSource",
    "MatchedSpec",
    "MissingPolicy",
    "MonitorDecision",
    "MonitorDecisionType",
    "MonitorTask",
    "OddsInfo",
    "PreconditionSpec",
    "PreconditionStatus",
    "Provenance",
    "QuarantineRecord",
    "RankedAlert",
    "ResearchBrief",
    "ResearchReport",
    "RuleEvidence",
    "RuleOp",
    "RuleSpec",
    "RunResult",
    "RunStatus",
    "ScoreBackend",
    "ScoreRequest",
    "ScreenMatch",
    "ScreenState",
    "SearchHit",
    "SlateGame",
    "SpecPromotion",
    "StatResult",
    "StrictModel",
    "TeamInfo",
    "UTCDateTime",
    "UpsetDefinition",
    "UpsetScore",
    "ValidatedPrecondition",
    "VenueInfo",
    "WeatherInfo",
]
