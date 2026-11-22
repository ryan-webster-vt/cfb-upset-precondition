"""End-to-end AppTest: fixture slate -> Analyze -> ranked alert + timeline."""

from __future__ import annotations

import re
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).parents[2] / "app.py"
AGENT_LINE = re.compile(r"\*\*(?P<agent>[^*]+)\*\* · `")


def run_app() -> AppTest:
    app = AppTest.from_file(str(APP), default_timeout=30)
    app.run()
    return app


def test_fixture_slate_renders_before_any_run() -> None:
    app = run_app()

    assert not app.exception
    assert [subheader.value for subheader in app.subheader] == ["Today's fixture slate"]
    assert app.button[0].label == "Analyze"
    assert app.multiselect[0].value == ["401700001", "401700002", "401700003"]
    assert len(app.dataframe) == 1
    assert list(app.dataframe[0].value["Matchup"]) == [
        "Miami at Virginia Tech",
        "Penn State at Ohio State",
        "Florida at Georgia",
    ]


def test_analyze_renders_ranked_alerts_and_three_agent_timeline() -> None:
    app = run_app()
    app.button[0].click().run()

    assert not app.exception
    subheaders = [subheader.value for subheader in app.subheader]
    assert "Ranked upset alerts (2)" in subheaders
    assert "Agent activity" in subheaders

    markdown = "\n".join(element.value for element in app.markdown)
    assert "### #1 — Miami at Virginia Tech" in markdown
    assert "### #2 — Florida at Georgia" in markdown
    assert "spec-away-short-rest" in markdown
    assert "spec-home-lookahead" not in markdown.split("### #2")[1]
    assert "https://www.espn.com/college-football/story/_/id/rest-recovery" in markdown

    agents = {match.group("agent") for match in AGENT_LINE.finditer(markdown)}
    assert len(agents) >= 3
    assert {
        "Monitor-Orchestrator",
        "Deterministic-Rule-Screen",
        "Upset-Scorer",
    } <= agents

    captions = [caption.value for caption in app.caption]
    assert any("Upset probability 38.0%" in caption for caption in captions)
    assert any("Upset probability 32.0%" in caption for caption in captions)
    assert any("status `completed`" in caption for caption in captions)


def test_analyze_with_no_selection_shows_a_warning() -> None:
    app = run_app()
    app.multiselect[0].set_value([]).run()
    app.button[0].click().run()

    assert not app.exception
    assert [warning.value for warning in app.warning] == [
        "Select at least one game before analyzing."
    ]
    assert "Ranked upset alerts" not in [subheader.value for subheader in app.subheader]
