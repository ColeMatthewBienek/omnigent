"""E2E coverage for smart-routing tool advertisement across runner isolation.

Starts real server and runner subprocesses, uploads a spawn-capable agent,
drives one mock-LLM turn, and inspects the tool schemas received by the model.
The parameter rows cover routing enabled/disabled and bundled-child creation.
"""

from __future__ import annotations

import json
import os
import secrets
import signal
import subprocess
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
import yaml

from omnigent.runner.identity import OMNIGENT_INTERNAL_WS_ORIGIN, token_bound_runner_id
from tests._helpers.compat import (
    apply_runner_env,
    apply_server_env,
    compat_runner_cwd,
    compat_runner_python,
    compat_server_cwd,
    compat_server_python,
    runner_executable,
    server_executable,
)
from tests.e2e.conftest import (
    build_agent_bundle,
    configure_mock_llm,
    create_runner_bound_session,
    find_free_port,
    get_mock_requests,
    poll_session_until_terminal,
    register_inline_agent,
    reset_mock_llm,
    send_user_message_to_session,
)
from tests.e2e.helpers import HEALTH_TIMEOUT_S, POLL_INTERVAL_S

_REPO_ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def _server_runner_pair(
    tmp_path: Path,
    *,
    mock_llm_server_url: str,
    smart_routing_available: bool,
) -> Iterator[tuple[str, str]]:
    """Run a real server and runner with optional server-side routing.

    :param tmp_path: Per-row directory for config, database, artifacts, and logs.
    :param mock_llm_server_url: Mock LLM base URL without the ``/v1`` suffix.
    :param smart_routing_available: Whether to give the server an ``llm:`` block.
    :returns: ``(base_url, runner_id)`` for the live pair.
    """
    port = find_free_port()
    base_url = f"http://127.0.0.1:{port}"
    binding_token = secrets.token_urlsafe(32)
    runner_id = token_bound_runner_id(binding_token)
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    server_log = tmp_path / "server.log"
    runner_log = tmp_path / "runner.log"

    env = {
        **os.environ,
        "OPENAI_API_KEY": "mock-key",
        "OPENAI_BASE_URL": f"{mock_llm_server_url}/v1",
        "OMNIGENT_SKIP_ONBOARD": "1",
        "OMNIGENT_NO_UPDATE_CHECK": "1",
    }
    apply_server_env(env, _REPO_ROOT)

    server_args = [
        server_executable(),
        "-m",
        "omnigent.cli",
        "server",
        "--port",
        str(port),
        "--database-uri",
        f"sqlite:///{tmp_path / 'e2e.db'}",
        "--artifact-location",
        str(artifact_dir),
    ]
    if smart_routing_available:
        server_config = tmp_path / "server.yaml"
        server_config.write_text(
            yaml.safe_dump(
                {
                    "llm": {
                        "model": "_policy_llm_",
                        "connection": {
                            "base_url": f"{mock_llm_server_url}/v1",
                            "api_key": "mock-key",
                        },
                    }
                }
            )
        )
        server_args.extend(["--config", str(server_config)])

    server_log_handle = open(server_log, "w")  # noqa: SIM115
    server_proc = subprocess.Popen(
        server_args,
        env={**env, "OMNIGENT_RUNNER_TUNNEL_TOKEN": binding_token},
        cwd=compat_server_cwd(),
        stdout=server_log_handle,
        stderr=subprocess.STDOUT,
    )

    runner_env = apply_runner_env(
        {
            **env,
            "OMNIGENT_RUNNER_ID": runner_id,
            "OMNIGENT_RUNNER_TUNNEL_BINDING_TOKEN": binding_token,
            "OMNIGENT_RUNNER_PARENT_PID": str(os.getpid()),
            "RUNNER_SERVER_URL": base_url,
        }
    )
    runner_log_handle = open(runner_log, "w")  # noqa: SIM115
    runner_proc = subprocess.Popen(
        [runner_executable(), "-m", "omnigent.runner._entry"],
        env=runner_env,
        cwd=compat_runner_cwd(),
        stdout=runner_log_handle,
        stderr=subprocess.STDOUT,
    )

    try:
        deadline = time.monotonic() + HEALTH_TIMEOUT_S
        while time.monotonic() < deadline:
            if server_proc.poll() is not None or runner_proc.poll() is not None:
                break
            try:
                health = httpx.get(f"{base_url}/health", timeout=2)
                status = httpx.get(f"{base_url}/v1/runners/{runner_id}/status", timeout=2)
                if (
                    health.status_code == 200
                    and status.status_code == 200
                    and status.json().get("online") is True
                ):
                    yield base_url, runner_id
                    return
            except httpx.HTTPError:
                pass
            time.sleep(POLL_INTERVAL_S)

        server_tail = server_log.read_text()[-3000:] if server_log.exists() else ""
        runner_tail = runner_log.read_text()[-3000:] if runner_log.exists() else ""
        pytest.fail(
            f"server/runner pair did not become ready\n"
            f"server log:\n{server_tail}\nrunner log:\n{runner_tail}"
        )
    finally:
        for proc in (runner_proc, server_proc):
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
        runner_log_handle.close()
        server_log_handle.close()


def _advertised_tool_names(request_body: dict[str, object]) -> set[str]:
    """Return function names from an OpenAI Responses request's tool schemas."""
    tools = request_body.get("tools")
    if not isinstance(tools, list):
        return set()
    return {
        name
        for tool in tools
        if isinstance(tool, dict) and isinstance(name := tool.get("name"), str)
    }


@pytest.mark.flaky(reruns=2, reruns_delay=5)
@pytest.mark.parametrize(
    ("smart_routing_available", "bundled_child"),
    [(True, False), (False, False), (True, True)],
    ids=["routing-configured", "routing-disabled", "routing-configured-bundled-child"],
)
def test_runner_advertises_advise_models_only_when_server_can_route(
    tmp_path: Path,
    mock_llm_server_url: str,
    smart_routing_available: bool,
    bundled_child: bool,
) -> None:
    """The model sees ``sys_advise_models`` exactly when the server can route."""
    if compat_server_python() is not None or compat_runner_python() is not None:
        pytest.skip("smart-routing session-init E2E requires the current server and runner")

    model = f"mock-routing-tools-{uuid.uuid4().hex[:8]}"
    reset_mock_llm(mock_llm_server_url)
    configure_mock_llm(mock_llm_server_url, [{"text": "done"}], key=model)

    with _server_runner_pair(
        tmp_path,
        mock_llm_server_url=mock_llm_server_url,
        smart_routing_available=smart_routing_available,
    ) as (base_url, runner_id):
        with httpx.Client(
            base_url=base_url,
            headers={"Origin": OMNIGENT_INTERNAL_WS_ORIGIN},
            timeout=30,
        ) as client:
            info = client.get("/v1/info")
            info.raise_for_status()
            assert info.json()["smart_routing_enabled"] is smart_routing_available
            agent_name = register_inline_agent(
                client,
                name=f"routing-tools-{uuid.uuid4().hex[:8]}",
                harness="openai-agents",
                model=model,
                profile="",
                prompt="Reply briefly without calling tools.",
                mock_llm_base_url=f"{mock_llm_server_url}/v1",
                extra_config={"spawn": True},
            )
            session_id = create_runner_bound_session(
                client,
                agent_name=agent_name,
                runner_id=runner_id,
            )
            if bundled_child:
                child_agent_dir = tmp_path / "bundled-child-agent"
                child_agent_dir.mkdir()
                (child_agent_dir / "config.yaml").write_text(
                    yaml.safe_dump(
                        {
                            "spec_version": 1,
                            "name": f"bundled-routing-tools-{uuid.uuid4().hex[:8]}",
                            "prompt": "Reply briefly without calling tools.",
                            "spawn": True,
                            "executor": {
                                "type": "omnigent",
                                "config": {"harness": "openai-agents"},
                            },
                            "llm": {
                                "model": model,
                                "connection": {
                                    "api_key": "mock-key",
                                    "base_url": f"{mock_llm_server_url}/v1",
                                },
                            },
                        }
                    )
                )
                child_response = client.post(
                    "/v1/sessions",
                    data={"metadata": json.dumps({"parent_session_id": session_id})},
                    files={
                        "bundle": (
                            "agent.tar.gz",
                            build_agent_bundle(child_agent_dir),
                            "application/gzip",
                        )
                    },
                )
                assert child_response.status_code == 201, child_response.text
                session_id = str(child_response.json()["session_id"])
            response_id = send_user_message_to_session(
                client,
                session_id=session_id,
                content="Reply with done and do not call any tools.",
            )
            body = poll_session_until_terminal(
                client,
                session_id=session_id,
                response_id=response_id,
                timeout=120,
            )
            assert body["status"] == "completed", body

    requests = get_mock_requests(mock_llm_server_url, key=model)
    assert requests, "runner-hosted turn never reached the mock LLM"
    tool_names = _advertised_tool_names(requests[-1])
    assert "sys_list_models" in tool_names
    assert ("sys_advise_models" in tool_names) is smart_routing_available
