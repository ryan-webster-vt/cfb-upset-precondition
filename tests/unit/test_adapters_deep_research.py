"""Deep Research: seeded replay, MCP JSON-RPC, and result parsing."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cfb_upset.adapters.deep_research import (
    DeepResearchAdapter,
    McpClient,
    SeededResearchProvider,
    parse_mcp_report,
)
from cfb_upset.adapters.transport import FixtureTransport
from cfb_upset.contracts import Citation, ResearchBrief, ResearchReport
from cfb_upset.errors import ContractError, PermanentProviderError
from cfb_upset.fixtures.demo import demo_specs

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def _brief() -> ResearchBrief:
    spec = demo_specs()[0]
    return ResearchBrief(
        candidate_key=spec.candidate_key,
        title=spec.title,
        definition="Away team has at most five days between games.",
        query="Does short rest increase upset risk?",
    )


def _report(*, candidate_key: str | None = None) -> ResearchReport:
    spec = demo_specs()[0]
    return ResearchReport(
        report_id="report-1",
        candidate_key=candidate_key or spec.candidate_key,
        provider="seeded_literature",
        title=spec.title,
        summary=spec.rationale,
        proposed_rule=spec.rule,
        required_fields=spec.required_fields,
        citations=[
            Citation(
                title="Short rest and upset risk",
                url="https://www.espn.com/college-football/story/1",
                published_at=NOW,
            )
        ],
        created_at=NOW,
    )


async def test_seeded_provider_returns_the_matching_report() -> None:
    report = _report()
    brief = _brief()
    provider = SeededResearchProvider({brief.candidate_key: report})
    assert await provider.research(brief) == report


async def test_seeded_provider_fails_closed_on_a_missing_candidate() -> None:
    provider = SeededResearchProvider({})
    with pytest.raises(PermanentProviderError, match="no seeded research report"):
        await provider.research(_brief())


async def test_seeded_provider_loads_a_directory(tmp_path: Path) -> None:
    path = tmp_path / "reports"
    path.mkdir()
    report = _report()
    (path / "report.json").write_text(report.model_dump_json(), encoding="utf-8")
    provider = SeededResearchProvider.from_directory(path)
    assert await provider.research(_brief()) == report


async def test_auto_mode_uses_the_seeded_provider_by_default() -> None:
    report = _report()
    adapter = DeepResearchAdapter(
        provider="auto", seeded=SeededResearchProvider({_brief().candidate_key: report})
    )
    assert adapter.mode == "seeded"
    assert await adapter.research(_brief()) == report


async def test_explicit_mcp_without_a_client_fails_closed() -> None:
    adapter = DeepResearchAdapter(provider="mcp", seeded=SeededResearchProvider({}))
    assert adapter.mode == "mcp"
    with pytest.raises(PermanentProviderError, match="not configured"):
        await adapter.research(_brief())


async def test_mcp_client_sends_json_rpc_and_parses_structured_content() -> None:
    report = _report()
    transport = FixtureTransport().add(
        "/mcp",
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"structuredContent": report.model_dump(mode="json")},
        },
    )
    client = McpClient(transport, "https://mcp.example/rpc")
    adapter = DeepResearchAdapter(provider="mcp", mcp=client, seeded=SeededResearchProvider({}))
    result = await adapter.research(_brief())

    assert result == report
    assert transport.calls[0].method == "POST"
    assert transport.calls[0].payload == {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "deep_research", "arguments": {"query": _brief().query}},
    }


async def test_mcp_initialize_and_list_tools_round_trip() -> None:
    transport = FixtureTransport()
    transport.add(
        lambda _method, _url, payload: payload["method"] == "initialize",
        {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}},
    )
    transport.add(
        lambda _method, _url, payload: payload["method"] == "tools/list",
        {"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "deep_research"}]}},
    )
    client = McpClient(transport, "https://mcp.example/rpc")
    assert await client.initialize() == {"protocolVersion": "2024-11-05"}
    tools = await client.list_tools()
    assert tools["tools"][0]["name"] == "deep_research"


async def test_mcp_rpc_errors_are_typed() -> None:
    transport = FixtureTransport().add(
        "/mcp", {"jsonrpc": "2.0", "id": 1, "error": {"message": "tool unavailable"}}
    )
    client = McpClient(transport, "https://mcp.example/rpc")
    with pytest.raises(PermanentProviderError, match="tool unavailable"):
        await client.list_tools()

    transport = FixtureTransport().add("/mcp", "down", status_code=503)
    client = McpClient(transport, "https://mcp.example/rpc")
    with pytest.raises(PermanentProviderError) as excinfo:
        await client.list_tools()
    assert excinfo.value.status_code == 503


def test_parse_mcp_report_accepts_a_json_text_block() -> None:
    report = _report()
    result = {"content": [{"type": "text", "text": json.dumps(report.model_dump(mode="json"))}]}
    assert parse_mcp_report(result, _brief()) == report


def test_parse_mcp_report_rejects_bad_shapes() -> None:
    with pytest.raises(ContractError, match="not valid JSON"):
        parse_mcp_report({"content": [{"type": "text", "text": "not json"}]}, _brief())
    with pytest.raises(ContractError, match="not a JSON object"):
        parse_mcp_report("plain", _brief())
    with pytest.raises(ContractError, match="candidate_key"):
        parse_mcp_report(
            {"structuredContent": _report(candidate_key="other").model_dump(mode="json")},
            _brief(),
        )
    with pytest.raises(ContractError, match="invalid research report"):
        parse_mcp_report({"structuredContent": {"report_id": "only"}}, _brief())
