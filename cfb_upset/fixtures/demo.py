"""Deterministic fixture data for the Phase 0 walking skeleton.

These are hand-authored FBS-vs-FBS games and validated-looking specs. They are
*not* real 2026 results; they exist so the UI, contracts, screen, and scorer can
be exercised offline. The values are internally consistent and every citation
is a public URL.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from cfb_upset.contracts import (
    Citation,
    FavoriteSource,
    GameStatus,
    MarketProbSource,
    MissingPolicy,
    OddsInfo,
    PreconditionSpec,
    PreconditionStatus,
    RuleOp,
    RuleSpec,
    SlateGame,
    TeamInfo,
    VenueInfo,
    WeatherInfo,
)

UTC = UTC


def _citation(title: str, url: str) -> Citation:
    return Citation(
        title=title,
        url=url,
        published_at=datetime(2024, 8, 1, 12, 0, tzinfo=UTC),
        source="seeded_literature",
    )


def demo_specs() -> list[PreconditionSpec]:
    """Three operationalizable preconditions used by the skeleton."""

    return [
        PreconditionSpec(
            spec_id="spec-away-short-rest",
            version=1,
            candidate_key="away_short_rest",
            title="Away team on short rest",
            rationale=(
                "A team playing on fewer than six days of rest may carry more fatigue "
                "and less preparation time into a road game."
            ),
            rule=RuleSpec(
                field="rest_days_away",
                op=RuleOp.LE,
                value=5,
                units="days",
                missing_policy=MissingPolicy.UNKNOWN,
            ),
            required_fields=["rest_days_away"],
            min_support=30,
            citations=[
                _citation(
                    "Rest and recovery in college football",
                    "https://www.espn.com/college-football/story/_/id/rest-recovery",
                )
            ],
            status=PreconditionStatus.VALIDATED,
        ),
        PreconditionSpec(
            spec_id="spec-away-long-travel",
            version=1,
            candidate_key="away_long_travel",
            title="Away team travelling more than 1,500 km",
            rationale=(
                "Long road trips add travel fatigue and time-zone disruption that are "
                "not fully captured by the betting market."
            ),
            rule=RuleSpec(
                field="travel_km_away",
                op=RuleOp.GE,
                value=1500,
                units="km",
                missing_policy=MissingPolicy.UNKNOWN,
            ),
            required_fields=["travel_km_away"],
            min_support=30,
            citations=[
                _citation(
                    "Travel fatigue in college football",
                    "https://www.sports-reference.com/cfb/travel-fatigue.html",
                )
            ],
            status=PreconditionStatus.VALIDATED,
        ),
        PreconditionSpec(
            spec_id="spec-home-lookahead",
            version=1,
            candidate_key="home_lookahead",
            title="Home team looking ahead to a ranked opponent",
            rationale=(
                "A home team with a ranked opponent next week may overlook the current "
                "matchup, especially when it is a heavy favourite."
            ),
            rule=RuleSpec(
                field="lookahead_next_rank",
                op=RuleOp.LE,
                value=10,
                units="rank",
                missing_policy=MissingPolicy.UNKNOWN,
            ),
            required_fields=["lookahead_next_rank"],
            min_support=30,
            citations=[
                _citation(
                    "The look-ahead spot in college football",
                    "https://www.cbssports.com/college-football/look-ahead-spot/",
                )
            ],
            status=PreconditionStatus.VALIDATED,
        ),
    ]


def _weather(hours_before_kickoff: int) -> WeatherInfo:
    return WeatherInfo(
        temperature_c=11.5,
        wind_kph=14.0,
        precipitation_mm=0.0,
        condition="Partly cloudy",
        source="open_meteo",
        known_at=datetime(2026, 11, 28, 6, 0, tzinfo=UTC),
        lead_hours=hours_before_kickoff,
    )


def demo_games() -> list[SlateGame]:
    """Three games: one 3-rule candidate, one 2-rule candidate, one no-match."""

    return [
        SlateGame(
            game_id="401700001",
            slate_date=date(2026, 11, 28),
            kickoff_utc=datetime(2026, 11, 28, 17, 0, tzinfo=UTC),
            home=TeamInfo(
                team_id="259",
                school="Virginia Tech",
                nickname="Hokies",
                abbreviation="VT",
                conference="ACC",
                rank=None,
                record="7-4",
                color="630031",
                alt_color="CF4420",
            ),
            away=TeamInfo(
                team_id="2390",
                school="Miami",
                nickname="Hurricanes",
                abbreviation="MIA",
                conference="ACC",
                rank=8,
                record="10-1",
                color="F47321",
                alt_color="005030",
            ),
            venue=VenueInfo(
                venue_id="3626",
                name="Lane Stadium",
                city="Blacksburg",
                state="VA",
                country="USA",
                indoor=False,
                grass=True,
                lat=37.2197,
                lon=-80.4180,
                altitude_m=641.0,
                tz="America/New_York",
                source="cfbd",
            ),
            neutral_site=False,
            conference_game=True,
            status=GameStatus.SCHEDULED,
            odds=OddsInfo(
                provider="DraftKings",
                favorite_team_id="2390",
                spread=-7.5,
                spread_open=-6.5,
                over_under=51.5,
                market_prob=0.72,
                favorite_source=FavoriteSource.ESPN_OPEN,
                line_provider="DraftKings",
                market_prob_source=MarketProbSource.MONEYLINE,
                known_at=datetime(2026, 11, 25, 17, 0, tzinfo=UTC),
            ),
            weather=_weather(24),
            broadcast="ABC",
        ),
        SlateGame(
            game_id="401700002",
            slate_date=date(2026, 11, 28),
            kickoff_utc=datetime(2026, 11, 28, 19, 30, tzinfo=UTC),
            home=TeamInfo(
                team_id="194",
                school="Ohio State",
                nickname="Buckeyes",
                abbreviation="OSU",
                conference="Big Ten",
                rank=1,
                record="11-0",
                color="BB0000",
                alt_color="666666",
            ),
            away=TeamInfo(
                team_id="213",
                school="Penn State",
                nickname="Nittany Lions",
                abbreviation="PSU",
                conference="Big Ten",
                rank=5,
                record="9-2",
                color="041E42",
                alt_color="FFFFFF",
            ),
            venue=VenueInfo(
                venue_id="3493",
                name="Ohio Stadium",
                city="Columbus",
                state="OH",
                country="USA",
                indoor=False,
                grass=False,
                lat=40.0017,
                lon=-83.0192,
                altitude_m=224.0,
                tz="America/New_York",
                source="cfbd",
            ),
            neutral_site=False,
            conference_game=True,
            status=GameStatus.SCHEDULED,
            odds=OddsInfo(
                provider="DraftKings",
                favorite_team_id="194",
                spread=-10.5,
                spread_open=-9.5,
                over_under=48.0,
                market_prob=0.78,
                favorite_source=FavoriteSource.ESPN_OPEN,
                line_provider="DraftKings",
                market_prob_source=MarketProbSource.MONEYLINE,
                known_at=datetime(2026, 11, 25, 17, 0, tzinfo=UTC),
            ),
            weather=None,
            broadcast="FOX",
        ),
        SlateGame(
            game_id="401700003",
            slate_date=date(2026, 11, 28),
            kickoff_utc=datetime(2026, 11, 28, 20, 0, tzinfo=UTC),
            home=TeamInfo(
                team_id="61",
                school="Georgia",
                nickname="Bulldogs",
                abbreviation="UGA",
                conference="SEC",
                rank=2,
                record="10-1",
                color="BA0C2F",
                alt_color="000000",
            ),
            away=TeamInfo(
                team_id="57",
                school="Florida",
                nickname="Gators",
                abbreviation="FLA",
                conference="SEC",
                rank=None,
                record="6-5",
                color="0021A5",
                alt_color="FA4616",
            ),
            venue=VenueInfo(
                venue_id="3637",
                name="Ben Hill Griffin Stadium",
                city="Gainesville",
                state="FL",
                country="USA",
                indoor=False,
                grass=True,
                lat=29.6499,
                lon=-82.3486,
                altitude_m=25.0,
                tz="America/New_York",
                source="cfbd",
            ),
            neutral_site=True,
            conference_game=True,
            status=GameStatus.SCHEDULED,
            odds=OddsInfo(
                provider="DraftKings",
                favorite_team_id="61",
                spread=-14.0,
                spread_open=-13.5,
                over_under=45.5,
                market_prob=0.82,
                favorite_source=FavoriteSource.ESPN_OPEN,
                line_provider="DraftKings",
                market_prob_source=MarketProbSource.MONEYLINE,
                known_at=datetime(2026, 11, 25, 17, 0, tzinfo=UTC),
            ),
            weather=_weather(24),
            broadcast="CBS",
        ),
    ]


def demo_contexts() -> dict[str, dict[str, object]]:
    """Pre-kickoff feature values for each fixture game.

    Values are illustrative but internally consistent. Game 401700001 matches
    all three specs, 401700003 matches two, and 401700002 matches none.
    """

    return {
        "401700001": {
            "rest_days_away": 4,
            "travel_km_away": 1650.0,
            "lookahead_next_rank": 6,
            "is_night_game": False,
        },
        "401700002": {
            "rest_days_away": 7,
            "travel_km_away": 420.0,
            "lookahead_next_rank": 25,
            "is_night_game": True,
        },
        "401700003": {
            "rest_days_away": 5,
            "travel_km_away": 1600.0,
            "lookahead_next_rank": 20,
            "is_night_game": True,
        },
    }
