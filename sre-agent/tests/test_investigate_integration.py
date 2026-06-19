#!/usr/bin/env python3
"""
Integration tests for the /investigate endpoint.

Tests the full HTTP → SSE stream → agent run recording pipeline
using FastAPI TestClient with mocked LLM dependencies.

Covers:
1. POST /investigate returns valid SSE stream
2. SSE events are well-formed JSON with expected fields
3. Stream ends with a 'result' event containing investigation output
4. Plain-text prompts are wrapped as alerts
5. JSON prompts are parsed as alert dicts
6. Multiple concurrent investigations get unique thread IDs
7. /status endpoint reports correct service health
8. Memory, health, and root endpoints work correctly
"""

import json
import os
import sys
import unittest.mock as mock

import pytest

# Add sre-agent root to path for imports
SRE_AGENT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SRE_AGENT_ROOT not in sys.path:
    sys.path.insert(0, SRE_AGENT_ROOT)

# ---------------------------------------------------------------------------
# Mock LLM and node functions
# ---------------------------------------------------------------------------

class MockAIMessage:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


PLANNER_RESPONSE = json.dumps(
    {
        "hypotheses": [
            {
                "hypothesis": "Service down due to pod crash",
                "priority": "high",
                "agents_to_test": ["kubernetes"],
            }
        ],
        "selected_agents": ["kubernetes"],
        "reasoning": "Kubernetes investigation needed",
    }
)

SUBAGENT_FINDINGS = (
    "Found pod web-service-abc123 in CrashLoopBackOff. "
    "Container exits with code 1 on startup."
)

SYNTHESIZER_SUFFICIENT = json.dumps(
    {
        "sufficient_evidence": True,
        "confidence": 0.9,
        "summary": "Root cause: CrashLoopBackOff in web-service",
        "gaps": [],
        "feedback": "",
    }
)

WRITEUP_RESPONSE = (
    "# Incident Report: Web Service CrashLoop\n\n"
    "Root cause: web-service pods in CrashLoopBackOff.\n\n"
    "```json\n"
    + json.dumps(
        {
            "title": "Web Service CrashLoopBackOff",
            "severity": "critical",
            "services": ["web-service"],
            "root_cause": "Container exits with code 1",
            "findings": [
                {
                    "category": "Kubernetes",
                    "detail": "CrashLoopBackOff",
                    "evidence": "kubectl get pods",
                }
            ],
            "action_items": [
                {
                    "priority": "high",
                    "action": "Fix container startup command",
                    "owner": "dev-team",
                }
            ],
            "resolution_status": "ongoing",
        }
    )
    + "\n```"
)


class MockLLM:
    def invoke(self, messages, **kwargs):
        system = ""
        for msg in messages:
            if hasattr(msg, "content"):
                system += msg.content + " "

        if "Planner" in system and "hypotheses" in system.lower():
            return MockAIMessage(content=PLANNER_RESPONSE)
        elif "Writeup" in system and "JSON Report Schema" in system:
            return MockAIMessage(content=WRITEUP_RESPONSE)
        elif "Synthesizer" in system and "sufficient_evidence" in system.lower():
            return MockAIMessage(content=SYNTHESIZER_SUFFICIENT)
        elif "investigation agent" in system.lower():
            return MockAIMessage(content=SUBAGENT_FINDINGS)
        elif "Planner" in system:
            return MockAIMessage(content=PLANNER_RESPONSE)
        elif "Writeup" in system:
            return MockAIMessage(content=WRITEUP_RESPONSE)
        elif "Synthesizer" in system:
            return MockAIMessage(content=SYNTHESIZER_SUFFICIENT)
        return MockAIMessage(content="OK")

    def bind_tools(self, tools):
        return self

    def with_structured_output(self, schema):
        """Return self — mock handles structured output via invoke() fallback."""
        return self


MOCK_TEAM_CONFIG_RAW = {
    "agents": {
        "planner": {
            "prompt": {"system": ""},
            "model": {"name": "test-model"},
            "max_iterations": 3,
        },
        "investigation": {
            "sub_agents": {"kubernetes": True, "metrics": True},
        },
        "writeup": {
            "prompt": {"system": ""},
            "model": {"name": "test-model"},
        },
    },
    "skills": {"enabled": ["*"]},
}


def _mock_load_team_config():
    m = mock.MagicMock()
    m.raw_config = MOCK_TEAM_CONFIG_RAW
    return m


def _common_patches():
    """Return list of patch context managers for all external deps."""
    return [
        mock.patch("nodes.init_context.load_team_config", side_effect=_mock_load_team_config),
        mock.patch("nodes.planner.build_llm", return_value=MockLLM()),
        mock.patch("nodes.synthesizer.build_llm", return_value=MockLLM()),
        mock.patch("nodes.writeup.build_llm", return_value=MockLLM()),
        mock.patch("nodes.subagent_executor.build_llm", return_value=MockLLM()),
        mock.patch("nodes.subagent_executor.resolve_tools", return_value=[]),
        mock.patch("nodes.subagent_executor.get_skill_catalog", return_value="No skills loaded."),
        mock.patch("nodes.subagent_executor.get_skills_for_agent", return_value=["*"]),
        mock.patch(
            "nodes.memory_lookup.enhance_investigation_with_memory",
            side_effect=lambda prompt, **kw: prompt,
        ),
        mock.patch(
            "tools.neo4j_semantic_layer.KubernetesGraphTools",
            side_effect=ImportError("Neo4j not available"),
        ),
        mock.patch("nodes.memory_store.store_investigation_result", return_value=None),
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_env(monkeypatch):
    """Set environment variables needed by server.py."""
    monkeypatch.setenv("CONFIG_SERVICE_URL", "http://localhost:8081")
    monkeypatch.setenv("LITELLM_BASE_URL", "http://localhost:4001")
    monkeypatch.setenv("NEO4J_URI", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("SOLIDAI_SRE_TENANT_ID", "test-tenant")
    monkeypatch.setenv("SOLIDAI_SRE_TEAM_ID", "test-team")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")


@pytest.fixture
def app():
    """Create the FastAPI app with all mocks applied."""
    patches = _common_patches()
    for p in patches:
        p.start()

    try:
        import importlib
        import server as server_mod
        importlib.reload(server_mod)

        # Clear any leftover background tasks/queues from previous tests
        server_mod._background_tasks.clear()
        server_mod._message_queues.clear()
        server_mod._response_queues.clear()

        yield server_mod.app
    finally:
        for p in patches:
            p.stop()


# ---------------------------------------------------------------------------
# Helper: parse SSE stream into list of events
# ---------------------------------------------------------------------------

def _parse_sse_events(response_text):
    """Parse raw SSE response text into list of event dicts."""
    events = []
    for line in response_text.strip().split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            payload = line[6:]
            try:
                events.append(json.loads(payload))
            except json.JSONDecodeError:
                pass
    return events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInvestigateEndpoint:
    """Tests for POST /investigate."""

    def test_investigate_returns_sse_stream(self, app):
        """POST /investigate returns 200 with text/event-stream content type."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        response = client.post("/investigate", json={"prompt": "Check service health"})

        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

    def test_investigate_sse_events_are_well_formed(self, app):
        """All SSE events in the response are valid JSON with expected fields."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        response = client.post("/investigate", json={"prompt": "Check service health"})

        events = _parse_sse_events(response.text)
        assert len(events) > 0, "No SSE events received"

        for event in events:
            assert "type" in event, f"Event missing 'type' field: {event}"
            assert "data" in event, f"Event missing 'data' field: {event}"
            assert "thread_id" in event, f"Event missing 'thread_id' field: {event}"
            assert "timestamp" in event, f"Event missing 'timestamp' field: {event}"

    def test_investigate_ends_with_result_event(self, app):
        """The SSE stream ends with a 'result' event containing investigation output."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        response = client.post("/investigate", json={"prompt": "Check service health"})

        events = _parse_sse_events(response.text)
        result_events = [e for e in events if e.get("type") == "result"]
        assert len(result_events) >= 1, (
            f"No 'result' event found. Event types: {[e.get('type') for e in events]}"
        )

        result = result_events[0]
        assert "text" in result["data"], "Result event missing 'text' field"
        assert len(result["data"]["text"]) > 0, "Result text is empty"

    def test_investigate_generates_thread_id(self, app):
        """Events contain a valid thread_id."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        response = client.post("/investigate", json={"prompt": "Check service health"})

        events = _parse_sse_events(response.text)
        thread_ids = {e.get("thread_id") for e in events}
        assert len(thread_ids) == 1, f"Multiple thread IDs found: {thread_ids}"
        tid = thread_ids.pop()
        assert tid.startswith("thread-"), f"Thread ID doesn't start with 'thread-': {tid}"

    def test_investigate_with_explicit_thread_id(self, app):
        """When thread_id is provided, it's used in all events."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        custom_tid = "my-custom-thread-123"
        response = client.post(
            "/investigate",
            json={"prompt": "Check service health", "thread_id": custom_tid},
        )

        events = _parse_sse_events(response.text)
        for event in events:
            assert event.get("thread_id") == custom_tid

    def test_investigate_plain_text_prompt(self, app):
        """Plain text prompts produce a valid investigation stream."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        prompt = "The web service is returning 500 errors"
        response = client.post("/investigate", json={"prompt": prompt})

        events = _parse_sse_events(response.text)
        assert len(events) > 0
        result_events = [e for e in events if e.get("type") == "result"]
        assert len(result_events) >= 1

    def test_investigate_json_prompt_parsed_as_alert(self, app):
        """JSON dict prompts are parsed as alert objects."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        alert = {
            "name": "HighCPU",
            "service": "api-gateway",
            "severity": "warning",
            "description": "CPU usage above 90%",
        }
        response = client.post("/investigate", json={"prompt": json.dumps(alert)})

        events = _parse_sse_events(response.text)
        assert len(events) > 0
        result_events = [e for e in events if e.get("type") == "result"]
        assert len(result_events) >= 1

    def test_investigate_includes_thought_events(self, app):
        """The SSE stream includes 'thought' events from agent reasoning."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        response = client.post("/investigate", json={"prompt": "Investigate high latency"})

        events = _parse_sse_events(response.text)
        thought_events = [e for e in events if e.get("type") == "thought"]
        assert len(thought_events) > 0, "No thought events in stream"

        for te in thought_events:
            assert "text" in te["data"], "Thought event missing text"
            assert "agent_name" in te["data"], "Thought event missing agent_name"

    def test_investigate_includes_tool_events(self, app):
        """Tool events, when present, are well-formed."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        response = client.post("/investigate", json={"prompt": "Investigate pod crashes"})

        events = _parse_sse_events(response.text)
        tool_start_events = [e for e in events if e.get("type") == "tool_start"]
        tool_end_events = [e for e in events if e.get("type") == "tool_end"]

        for te in tool_start_events:
            assert "name" in te["data"], "tool_start missing 'name'"
            assert "tool_use_id" in te["data"], "tool_start missing 'tool_use_id'"

        for te in tool_end_events:
            assert "name" in te["data"], "tool_end missing 'name'"
            assert "success" in te["data"], "tool_end missing 'success'"

    def test_investigate_result_has_structured_report(self, app):
        """The result event includes a structured_report when writeup produces JSON."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        response = client.post("/investigate", json={"prompt": "Investigate incident"})

        events = _parse_sse_events(response.text)
        result_events = [e for e in events if e.get("type") == "result"]
        assert len(result_events) >= 1

        result_data = result_events[0]["data"]
        if "structured_report" in result_data:
            report = result_data["structured_report"]
            assert isinstance(report, dict)
            assert "title" in report
            assert "severity" in report

    def test_investigate_concurrent_threads(self, app):
        """Two concurrent investigations get different thread IDs."""
        from starlette.testclient import TestClient

        client = TestClient(app)

        response1 = client.post("/investigate", json={"prompt": "Check service A"})
        response2 = client.post("/investigate", json={"prompt": "Check service B"})

        events1 = _parse_sse_events(response1.text)
        events2 = _parse_sse_events(response2.text)

        tids1 = {e.get("thread_id") for e in events1}
        tids2 = {e.get("thread_id") for e in events2}

        assert len(tids1) == 1
        assert len(tids2) == 1
        assert tids1 != tids2, "Both investigations got the same thread ID"


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_returns_healthy(self, app):
        """GET /health returns 200 with healthy status."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["mode"] == "langgraph"

    def test_health_reports_active_sessions(self, app):
        """GET /health reports the number of active sessions."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        response = client.get("/health")

        data = response.json()
        assert "active_sessions" in data
        assert isinstance(data["active_sessions"], int)


class TestStatusEndpoint:
    """Tests for GET /status."""

    def test_status_returns_service_health(self, app):
        """GET /status returns health info for all dependent services."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        response = client.get("/status")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "services" in data
        assert "timestamp" in data

    def test_status_includes_config_service(self, app):
        """Status includes config_service health check."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        response = client.get("/status")

        data = response.json()
        assert "config_service" in data["services"]

    def test_status_includes_litellm(self, app):
        """Status includes litellm health check."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        response = client.get("/status")

        data = response.json()
        assert "litellm" in data["services"]


class TestMemoryEndpoints:
    """Tests for memory API endpoints."""

    def test_memory_stats(self, app):
        """GET /memory/stats returns memory statistics."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        response = client.get("/memory/stats")
        assert response.status_code == 200

    def test_memory_episodes(self, app):
        """GET /memory/episodes returns list of episodes."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        response = client.get("/memory/episodes")

        assert response.status_code == 200
        data = response.json()
        assert "episodes" in data

    def test_memory_search(self, app):
        """POST /memory/search returns search results."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        response = client.post(
            "/memory/search",
            json={"prompt": "high latency investigation"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "results" in data


class TestRootEndpoint:
    """Tests for GET /."""

    def test_root_returns_service_info(self, app):
        """GET / returns service metadata."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "SolidAI SRE Investigation Server"
        assert data["mode"] == "langgraph"
        assert data["version"] == "0.4.0"


class TestParseAlertFromPrompt:
    """Tests for the _parse_alert_from_prompt helper."""

    def _get_fn(self):
        """Import _parse_alert_from_prompt from server."""
        from server import _parse_alert_from_prompt
        return _parse_alert_from_prompt

    def test_json_dict_parsed_directly(self):
        fn = self._get_fn()
        prompt = json.dumps({"name": "Test", "severity": "critical"})
        result = fn(prompt)
        assert result["name"] == "Test"
        assert result["severity"] == "critical"

    def test_plain_text_wrapped(self):
        fn = self._get_fn()
        result = fn("Something is broken")
        assert result["name"] == "Investigation"
        assert result["description"] == "Something is broken"
        assert result["severity"] == "info"

    def test_empty_string(self):
        fn = self._get_fn()
        result = fn("")
        assert result["name"] == "Investigation"
        assert result["description"] == ""

    def test_json_array_falls_back(self):
        fn = self._get_fn()
        result = fn("[1, 2, 3]")
        assert result["name"] == "Investigation"

    def test_invalid_json_falls_back(self):
        fn = self._get_fn()
        result = fn("{not valid json")
        assert result["name"] == "Investigation"
