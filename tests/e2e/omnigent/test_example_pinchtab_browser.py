"""Structural test for the pinchtab_browser example bundle
(``examples/pinchtab_browser``).

The bundle wires PinchTab — a local browser-control daemon that speaks MCP over
stdio (``pinchtab mcp``) — through the spec parser's ``tools/mcp/*.yaml``
auto-discovery, with no ``tools:`` block and no core-engine changes. Pure
spec-load: no LLM, no live daemon, no real token. Modeled on
``test_deep_research_example.py``.

What breaks if this fails:
- the stdio MCP server stops being discovered from ``tools/mcp/*.yaml`` (the
  agent would load with no browser-control tools at all),
- the launch command drifts from PinchTab's documented ``pinchtab mcp``,
- the daemon target stops being loopback-only, or the token stops coming from
  the ``PINCHTAB_TOKEN`` environment variable (a real token in the YAML would
  ship a secret in the repo),
- PinchTab's ``pinchtab_*`` tool namespace starts colliding with the
  framework-owned ``browser_*`` built-ins,
- an ``os_env`` block is added, which would hand local file and shell tools to
  an agent meant to act only through the browser daemon.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from omnigent.spec import load
from omnigent.spec.types import AgentSpec
from omnigent.tools.builtins.browser import (
    BrowserClickTool,
    BrowserNavigateTool,
    BrowserScreenshotTool,
    BrowserSnapshotTool,
    BrowserTypeTool,
)

# tests/e2e/omnigent/test_example_pinchtab_browser.py -> repo root is 3 parents up.
_BUNDLE = Path(__file__).resolve().parents[3] / "examples" / "pinchtab_browser"
_MCP_YAML = _BUNDLE / "tools" / "mcp" / "pinchtab.yaml"

# Stand-in for an operator's real token. The bundle must resolve its token from
# the environment, so parsing it needs *some* value present.
_TEST_TOKEN = "test-token-not-a-real-credential"


@pytest.fixture
def pinchtab_spec(monkeypatch: pytest.MonkeyPatch) -> AgentSpec:
    """Load the bundle with a stand-in token in the environment."""
    monkeypatch.setenv("PINCHTAB_TOKEN", _TEST_TOKEN)
    return load(_BUNDLE)


def test_pinchtab_mcp_server_is_auto_discovered(pinchtab_spec: AgentSpec) -> None:
    """
    The bundle loads and its only tool source is the auto-discovered PinchTab
    stdio MCP server, launched with PinchTab's documented ``pinchtab mcp``.

    There is no ``tools:`` block — the point is that a ``tools/mcp/<name>.yaml``
    server is discovered and its tools exposed. If discovery regresses, the
    agent loads with nothing to drive a browser with.
    """
    assert pinchtab_spec.name == "pinchtab_browser"
    assert pinchtab_spec.sub_agents == []

    servers = {s.name: s for s in pinchtab_spec.mcp_servers}
    assert list(servers) == ["pinchtab"]
    pinchtab = servers["pinchtab"]
    assert pinchtab.transport == "stdio"
    assert pinchtab.command == "pinchtab"
    assert pinchtab.args == ["mcp"]


def test_pinchtab_targets_loopback_only(pinchtab_spec: AgentSpec) -> None:
    """
    The MCP client is pointed at a loopback daemon on PinchTab's default port.

    PinchTab's HTTP API is explicitly not built for untrusted or multi-tenant
    exposure, so the supported configuration never names a non-loopback host.
    """
    pinchtab = next(s for s in pinchtab_spec.mcp_servers if s.name == "pinchtab")
    assert pinchtab.env["PINCHTAB_SERVER"] == "http://127.0.0.1:9867"


def test_pinchtab_token_comes_from_the_environment(pinchtab_spec: AgentSpec) -> None:
    """
    The token is expanded from ``PINCHTAB_TOKEN`` at parse time, and the YAML
    on disk carries only the reference — never a literal credential.
    """
    pinchtab = next(s for s in pinchtab_spec.mcp_servers if s.name == "pinchtab")
    assert pinchtab.env["PINCHTAB_TOKEN"] == _TEST_TOKEN

    yaml_text = _MCP_YAML.read_text(encoding="utf-8")
    assert "${PINCHTAB_TOKEN}" in yaml_text
    assert _TEST_TOKEN not in yaml_text


def test_pinchtab_tools_do_not_collide_with_browser_builtins(
    pinchtab_spec: AgentSpec,
) -> None:
    """
    PinchTab namespaces every tool it exposes under ``pinchtab_``, so none of
    them shadow the framework-owned ``browser_*`` built-ins that are registered
    for every agent regardless of the spec.
    """
    builtin_names = {
        BrowserNavigateTool.name(),
        BrowserSnapshotTool.name(),
        BrowserClickTool.name(),
        BrowserTypeTool.name(),
        BrowserScreenshotTool.name(),
    }
    assert not any(name.startswith("pinchtab_") for name in builtin_names)

    server_names = {s.name for s in pinchtab_spec.mcp_servers}
    assert server_names.isdisjoint(builtin_names)


def test_pinchtab_bundle_has_no_os_environment(pinchtab_spec: AgentSpec) -> None:
    """The example does not opt into local file or shell tools."""
    assert pinchtab_spec.os_env is None
