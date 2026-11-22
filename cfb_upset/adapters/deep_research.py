"""Deep Research adapter: MCP JSON-RPC client plus a deterministic seed mode.

No MCP server is configured in this environment (blocker B3). ``auto`` therefore
uses the checked-in/seeded provider unless an endpoint is supplied. The MCP path
is a thin, testable JSON-RPC client; the result parser accepts either
``structuredContent`` or a JSON text content block.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from cfb_upset.adapters.transport import HttpTransport, Transport
from cfb_upset.config import get_settings
from cfb_upset.contracts import ResearchBrief, ResearchReport
from cfb_upset.errors import ContractError, PermanentProviderError
from cfb_upset.ids import Clock, SystemClock


class ResearchProvider(Protocol):
    mode: str

    async def research(self, brief: ResearchBrief) -> ResearchReport: ...


class SeededResearchProvider:
    """Deterministic provider backed by reports supplied by the caller."""

    mode = "seeded"

    def __init__(self, reports: dict[str, ResearchReport] | None = None) -> None:
        self.reports = reports or {}

    @classmethod
    def from_directory(cls, path: str | Path) -> SeededResearchProvider:
        reports: dict[str, ResearchReport] = {}
        for file_path in sorted(Path(path).glob("*.json")):
            report = ResearchReport.model_validate(
                json.loads(file_path.read_text(encoding="utf-8"))
            )
            reports[report.candidate_key] = report
        return cls(reports)

    async def research(self, brief: ResearchBrief) -> ResearchReport:
        report = self.reports.get(brief.candidate_key)
        if report is None:
            raise PermanentProviderError(
                f"no seeded research report for candidate {brief.candidate_key!r}",
                provider="seeded_research",
            )
        if report.candidate_key != brief.candidate_key:
            raise ContractError("seeded report candidate_key does not match the brief")
        return report


class McpClient:
    """Minimal MCP JSON-RPC 2.0 client over an HTTP transport."""

    def __init__(
        self,
        transport: Transport,
        endpoint: str,
        *,
        clock: Clock | None = None,
        client_name: str = "cfb-upset",
        client_version: str = "0.1",
    ) -> None:
        self.transport = transport
        self.endpoint = endpoint
        self.clock = clock or SystemClock()
        self.client_name = client_name
        self.client_version = client_version
        self._request_id = 0

    async def rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params or {},
        }
        response = await self.transport.post(self.endpoint, payload=payload)
        if response.status_code != 200:
            raise PermanentProviderError(
                f"MCP {method} returned HTTP {response.status_code}",
                status_code=response.status_code,
                provider="mcp",
            )
        body = response.json()
        if isinstance(body, dict) and body.get("error"):
            error = body["error"]
            raise PermanentProviderError(
                f"MCP {method} error: {error.get('message', error)}",
                provider="mcp",
            )
        return body.get("result") if isinstance(body, dict) else body

    async def initialize(self) -> Any:
        return await self.rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": self.client_name, "version": self.client_version},
            },
        )

    async def list_tools(self) -> Any:
        return await self.rpc("tools/list")

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        return await self.rpc("tools/call", {"name": name, "arguments": arguments})


class DeepResearchAdapter:
    def __init__(
        self,
        *,
        provider: str | None = None,
        seeded: SeededResearchProvider | None = None,
        mcp: McpClient | None = None,
        transport: Transport | None = None,
        endpoint: str | None = None,
        tool_name: str = "deep_research",
        clock: Clock | None = None,
    ) -> None:
        settings = get_settings()
        self.provider_mode = (provider or settings.research_provider or "auto").lower()
        self.seeded = seeded
        self.mcp = mcp
        self.tool_name = tool_name
        self.clock = clock or SystemClock()
        if self.mcp is None and endpoint:
            self.mcp = McpClient(
                transport or HttpTransport(provider="mcp"), endpoint, clock=self.clock
            )
        if self.seeded is None:
            self.seeded = SeededResearchProvider()

    @property
    def mode(self) -> str:
        if self.provider_mode in {"seeded", "seeded_literature"}:
            return "seeded"
        if self.provider_mode == "mcp":
            return "mcp"
        return "mcp" if self.mcp is not None else "seeded"

    async def research(self, brief: ResearchBrief) -> ResearchReport:
        if self.mode == "seeded":
            assert self.seeded is not None
            return await self.seeded.research(brief)
        if self.mcp is None:
            raise PermanentProviderError(
                "deep research MCP endpoint is not configured", provider="mcp"
            )
        result = await self.mcp.call_tool(self.tool_name, {"query": brief.query})
        return parse_mcp_report(result, brief)


def parse_mcp_report(result: Any, brief: ResearchBrief) -> ResearchReport:
    payload: Any = result
    if isinstance(result, dict):
        if result.get("structuredContent") is not None:
            payload = result["structuredContent"]
        elif result.get("content"):
            text_parts = [
                item.get("text", "")
                for item in result["content"]
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            text = "\n".join(part for part in text_parts if part).strip()
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ContractError("MCP research text is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ContractError("MCP research result is not a JSON object")
    try:
        report = ResearchReport.model_validate(payload)
    except Exception as exc:  # pydantic ValidationError -> typed contract error
        raise ContractError(f"invalid research report from MCP: {exc}") from exc
    if report.candidate_key != brief.candidate_key:
        raise ContractError("MCP report candidate_key does not match the brief")
    return report


__all__ = ["DeepResearchAdapter", "McpClient", "ResearchProvider", "SeededResearchProvider"]
