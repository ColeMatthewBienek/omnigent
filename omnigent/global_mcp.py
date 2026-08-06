"""Trusted server-wide MCP defaults applied to every resolved agent spec."""

from __future__ import annotations

import dataclasses
import json

from omnigent.spec.types import AgentSpec, MCPServerConfig

GLOBAL_MCP_SERVERS_HEADER = "X-Omnigent-Global-Mcp-Servers"


def parse_global_mcp_servers(value: object) -> list[MCPServerConfig]:
    """Parse an operator-owned ``global_mcp_servers`` config value.

    Invalid declarations fail closed because a malformed default must not make
    every agent session unusable.
    """
    if not isinstance(value, list):
        return []
    servers: list[MCPServerConfig] = []
    for raw in value:
        if not isinstance(raw, dict):
            return []
        name = raw.get("name")
        transport = raw.get("transport", "stdio")
        command = raw.get("command")
        args = raw.get("args", [])
        if (
            not isinstance(name, str)
            or not name
            or transport != "stdio"
            or not isinstance(command, str)
            or not command
            or not isinstance(args, list)
            or not all(isinstance(arg, str) for arg in args)
        ):
            return []
        servers.append(
            MCPServerConfig(name=name, transport="stdio", command=command, args=list(args))
        )
    if len({server.name for server in servers}) != len(servers):
        return []
    return servers


def global_mcp_servers_header(servers: list[MCPServerConfig]) -> str:
    """Serialize trusted global server declarations for a runner response."""
    return json.dumps(
        [
            {
                "name": server.name,
                "transport": server.transport,
                "command": server.command,
                "args": server.args,
            }
            for server in servers
        ],
        separators=(",", ":"),
    )


def global_mcp_servers_from_header(value: str | None) -> list[MCPServerConfig]:
    """Parse a server response header without trusting malformed payloads."""
    if not value:
        return []
    try:
        return parse_global_mcp_servers(json.loads(value))
    except json.JSONDecodeError:
        return []


def apply_global_mcp_servers(spec: AgentSpec, servers: list[MCPServerConfig]) -> AgentSpec:
    """Merge server defaults into an agent and each declared sub-agent.

    A server-wide declaration wins on a name collision so an untrusted agent
    bundle cannot replace an administrator-provided MCP endpoint.
    """
    if not servers:
        return spec
    global_names = {server.name for server in servers}
    merged_servers = [
        *servers,
        *(server for server in spec.mcp_servers if server.name not in global_names),
    ]
    sub_agents = [apply_global_mcp_servers(sub_agent, servers) for sub_agent in spec.sub_agents]
    return dataclasses.replace(spec, mcp_servers=merged_servers, sub_agents=sub_agents)
