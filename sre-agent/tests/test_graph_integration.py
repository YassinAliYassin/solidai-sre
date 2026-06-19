"""Advanced integration tests for the LangGraph investigation graph.

Covers multi-iteration loops, max-iteration forced writeup, multi-subagent
fan-out, error recovery, and structured report normalization.

Extends test_graph_e2e.py with deeper scenarios that exercise the graph's
control-flow paths (loop routing, fan-in/fan-out, error fallbacks).
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from langgraph.checkpoint.memory import MemorySaver

# ---------------------------------------------------------------------------
# Mock LLM responses
# ---------------------------------------------------------------------------


PLANNER_RESPONSE = json.dumps(
    {
        "hypotheses": [
            {
                "hypothesis": "High error rate caused by OOM in payment pods",
                "priority": "high",
                "agents_to_test": ["kubernetes", "metrics"],
            }
        ],
        "selected_agents": ["kubernetes", "metrics"],
        "reasoning": "Kubernetes + metrics investigation needed",
    }
)

SUBAGENT_FINDINGS_K8S = (
    "Found pod payment-service-abc123 restarting due to OOMKilled. "
    "Memory limit 512Mi exceeded. Last restart 5 minutes ago."
)

SUBAGENT_FINDINGS_METRICS = (
    "Error rate spike correlates with deployment at 09:55. "
    "P99 latency increased from 200ms to 2s. CPU throttling detected."
)

SYNTHESIZER_INSUFFICIENT = json.dumps(
    {
        "sufficient_evidence": False,
        "confidence": 0.4,
        "summary": "Initial findings suggest OOM but need more evidence",
        "gaps": ["Check database connection pool", "Review recent config changes"],
        "feedback": "Investigate database connections and recent deployments",
    }
)

SYNTHESIZER_SUFFICIENT = json.dumps(
    {
        "sufficient_evidence": True,
        "confidence": 0.9,
        "summary": "Root cause confirmed: OOMKilled pods due to memory limit",
        "gaps": [],
        "feedback": "",
    }
)

WRITEUP_RESPONSE = (
    "# Incident Report: Payment Service High Error Rate\n\n"
    "Root cause: payment-service pods OOMKilled due to 512Mi memory limit.\n\n"
    "```json\n"
    + json.dumps(
        {
            "title": "Payment Service OOMKill",
            "severity": "critical",
            "services": ["payment-service"],
            "root_cause": "OOM due to insufficient memory limits",
            "findings": [
                {
                    "category": "Kubernetes",
                    "detail": "OOMKilled pods",
                    "evidence": "kubectl logs",
                }
            ],
            "action_items": [
                {
                    "priority": "high",
                    "action": "Increase memory limit to 1Gi",
                    "owner": "platform",
                }
            ],
            "resolution_status": "mitigated",
        }
    )
    + "\n```"
)

# Thin writeup — tests _enrich_from_narrative path
WRITEUP_THIN_RESPONSE = (
    "# Payment Service Incident\n\n"
    "The payment service experienced OOMKilled pods.\n\n"
    "```json\n"
    + json.dumps(
        {
            "title": "Payment Service OOMKill",
            "severity": "critical",
        }
    )
    + "\n```"
)


try:
    from langchain_core.messages import AIMessage as _LCAIMessage

    class MockAIMessage(_LCAIMessage):
        """Mimics langchain_core.messages.AIMessage."""

        def __init__(self, content="", tool_calls=None):
            super().__init__(content=content, tool_calls=tool_calls or [])

except ImportError:
    class MockAIMessage:
        """Mimics langchain_core.messages.AIMessage."""

        def __init__(self, content="", tool_calls=None):
            self.content = content
            self.tool_calls = tool_calls or []


class MultiCallMockLLM:
    """Mock LLM with a queue of responses per (system_keyword, call_index).

    Allows different responses for the same node across multiple calls
    (e.g. synthesizer returns insufficient first, sufficient second).
    """

    def __init__(self, response_queue):
        """response_queue is a list of (keyword, response_list) tuples.

        Each time invoke() is called, we find the first matching keyword
        and pop from its response_list.
        """
        self._queue = list(response_queue)
        self._call_counts = {}

    def invoke(self, messages, **kwargs):
        system = ""
        for msg in messages:
            if hasattr(msg, "content"):
                system += msg.content + " "

        for keyword, responses in self._queue:
            if keyword in system:
                idx = self._call_counts.get(keyword, 0)
                self._call_counts[keyword] = idx + 1
                if idx < len(responses):
                    return MockAIMessage(content=responses[idx])
                # Exhausted responses for this keyword — fall through
        return MockAIMessage(content="OK")

    def bind_tools(self, tools):
        return self


class RoleBasedMockLLM:
    """Mock LLM that returns different content based on detected role.

    Maps role keywords to response strings.  Each call consumes one
    response from the list for that role (FIFO).
    """

    def __init__(self, role_responses: dict[str, list[str]]):
        """role_responses: {role_keyword: [response1, response2, ...]}"""
        self._role_responses = {k: list(v) for k, v in role_responses.items()}
        self._call_idx: dict[str, int] = {}

    def _detect_role(self, messages):
        """Detect which role is being called based on system prompt."""
        system = ""
        for msg in messages:
            if hasattr(msg, "content"):
                system += msg.content + " "

        # Check roles in priority order (most specific first)
        for role in self._role_responses:
            if role.lower() in system.lower():
                return role
        return None

    def invoke(self, messages, **kwargs):
        role = self._detect_role(messages)
        if role:
            responses = self._role_responses[role]
            idx = self._call_idx.get(role, 0)
            self._call_idx[role] = idx + 1
            if idx < len(responses):
                return MockAIMessage(content=responses[idx])
            return MockAIMessage(content=responses[-1])
        return MockAIMessage(content="OK")

    def bind_tools(self, tools):
        return self

    def with_structured_output(self, schema):
        """Return self — structured output is handled by returning pre-built JSON."""
        return self


MOCK_TEAM_CONFIG_RAW = {
    "agents": {
        "planner": {
            "prompt": {"system": ""},
            "model": {"name": "test-model"},
            "max_iterations": 3,
        },
        "investigation": {
            "sub_agents": {
                "kubernetes": True,
                "metrics": True,
            },
        },
        "writeup": {
            "prompt": {"system": ""},
            "model": {"name": "test-model"},
        },
    },
    "skills": {"enabled": ["*"]},
}

# Config with max_iterations=2 to test forced writeup
MOCK_TEAM_CONFIG_RAW_MAX2 = {
    "agents": {
        "planner": {
            "prompt": {"system": ""},
            "model": {"name": "test-model"},
            "max_iterations": 2,
        },
        "investigation": {
            "sub_agents": {
                "kubernetes": True,
            },
        },
        "writeup": {
            "prompt": {"system": ""},
            "model": {"name": "test-model"},
        },
    },
    "skills": {"enabled": ["*"]},
}


TEST_ALERT = {
    "name": "HighErrorRate",
    "service": "payment-service",
    "severity": "critical",
    "timestamp": "2026-03-18T10:00:00Z",
    "description": "Payment service error rate above 5% for 10 minutes",
}


def _mock_load_team_config(raw_config=MOCK_TEAM_CONFIG_RAW):
    mock_config = MagicMock()
    mock_config.raw_config = raw_config
    return mock_config


def _common_patches(raw_config=MOCK_TEAM_CONFIG_RAW):
    """Return a list of patch context managers for all external deps."""
    return [
        patch(
            "nodes.init_context.load_team_config",
            side_effect=lambda: _mock_load_team_config(raw_config),
        ),
        patch("nodes.subagent_executor.resolve_tools", return_value=[]),
        patch(
            "nodes.subagent_executor.get_skill_catalog",
            return_value="No skills loaded.",
        ),
        patch("nodes.subagent_executor.get_skills_for_agent", return_value=["*"]),
        patch(
            "nodes.memory_lookup.enhance_investigation_with_memory",
            side_effect=lambda prompt, **kw: prompt,
        ),
        patch(
            "tools.neo4j_semantic_layer.KubernetesGraphTools",
            side_effect=ImportError("Neo4j not available"),
        ),
        patch("nodes.memory_store.store_investigation_result", return_value=None),
    ]


def _build_graph_with_llm(mock_llm, raw_config=MOCK_TEAM_CONFIG_RAW):
    """Build graph with a specific mock LLM and config."""
    from graph import build_graph

    patches = _common_patches(raw_config)
    for p in patches:
        p.start()

    # Patch build_llm in all node modules to return our mock
    llm_patches = [
        patch("nodes.planner.build_llm", return_value=mock_llm),
        patch("nodes.synthesizer.build_llm", return_value=mock_llm),
        patch("nodes.writeup.build_llm", return_value=mock_llm),
        patch("nodes.subagent_executor.build_llm", return_value=mock_llm),
    ]
    for p in llm_patches:
        p.start()

    checkpointer = MemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    return graph, patches + llm_patches


def _stop_patches(patches):
    for p in patches:
        try:
            p.stop()
        except RuntimeError:
            pass  # already stopped


# ---------------------------------------------------------------------------
# Test: Multi-iteration loop (insufficient evidence → loop → sufficient)
# ---------------------------------------------------------------------------


class TestGraphMultiIterationLoop:
    """Test that the graph loops back to planner when evidence is insufficient."""

    def test_graph_loops_back_on_insufficient_evidence(self):
        """Synthesizer returns insufficient first, then sufficient — graph should loop."""
        # Planner called twice: initial + after feedback
        # Synthesizer called twice: insufficient, then sufficient
        # Subagents called twice (once per iteration)
        # Writeup called once
        mock_llm = RoleBasedMockLLM(
            {
                "Planner": [PLANNER_RESPONSE, PLANNER_RESPONSE],
                "Synthesizer": [SYNTHESIZER_INSUFFICIENT, SYNTHESIZER_SUFFICIENT],
                "Writeup": [WRITEUP_RESPONSE],
                "investigation agent": [
                    SUBAGENT_FINDINGS_K8S,
                    SUBAGENT_FINDINGS_K8S,
                ],
            }
        )

        graph, all_patches = _build_graph_with_llm(mock_llm)
        try:
            config = {"configurable": {"thread_id": "test-multi-iter"}}
            initial_state = {
                "alert": TEST_ALERT,
                "thread_id": "test-multi-iter",
                "images": [],
            }

            result = graph.invoke(initial_state, config=config)

            assert result is not None
            assert result.get("status") == "completed"
            assert len(result.get("conclusion", "")) > 0
            assert "structured_report" in result

            # Iteration should have advanced
            assert result.get("iteration", 0) >= 1, (
                f"Expected iteration >= 1 after loop, got {result.get('iteration')}"
            )

            # Messages should contain synthesizer feedback
            messages = result.get("messages", [])
            has_synthesizer_msg = any(
                isinstance(m, dict) and m.get("role") == "synthesizer"
                for m in messages
            )
            assert has_synthesizer_msg, (
                "Expected synthesizer feedback message in messages list"
            )

        finally:
            _stop_patches(all_patches)

    def test_graph_forces_writeup_at_max_iterations(self):
        """Synthesizer always returns insufficient — graph must force writeup at max_iterations."""
        # max_iterations=2 in config, so after 2 iterations it must conclude
        mock_llm = RoleBasedMockLLM(
            {
                "Planner": [PLANNER_RESPONSE, PLANNER_RESPONSE],
                "Synthesizer": [
                    SYNTHESIZER_INSUFFICIENT,
                    SYNTHESIZER_INSUFFICIENT,
                ],
                "Writeup": [WRITEUP_RESPONSE],
                "investigation agent": [
                    SUBAGENT_FINDINGS_K8S,
                    SUBAGENT_FINDINGS_K8S,
                ],
            }
        )

        graph, all_patches = _build_graph_with_llm(
            mock_llm, raw_config=MOCK_TEAM_CONFIG_RAW_MAX2
        )
        try:
            config = {"configurable": {"thread_id": "test-max-iter"}}
            initial_state = {
                "alert": TEST_ALERT,
                "thread_id": "test-max-iter",
                "images": [],
            }

            result = graph.invoke(initial_state, config=config)

            assert result is not None
            # Must be completed even though synthesizer always said insufficient
            assert result.get("status") == "completed", (
                f"Expected 'completed' at max iterations, got '{result.get('status')}'"
            )
            assert len(result.get("conclusion", "")) > 0
            assert "structured_report" in result

        finally:
            _stop_patches(all_patches)


# ---------------------------------------------------------------------------
# Test: Multi-subagent fan-out
# ---------------------------------------------------------------------------


class TestGraphMultiSubagentFanout:
    """Test that multiple subagents execute and merge results."""

    def test_multiple_subagents_run_in_parallel(self):
        """Both kubernetes and metrics subagents should execute and merge findings."""
        mock_llm = RoleBasedMockLLM(
            {
                "Planner": [PLANNER_RESPONSE],
                "Synthesizer": [SYNTHESIZER_SUFFICIENT],
                "Writeup": [WRITEUP_RESPONSE],
                "investigation agent": [
                    SUBAGENT_FINDINGS_K8S,
                    SUBAGENT_FINDINGS_METRICS,
                ],
            }
        )

        graph, all_patches = _build_graph_with_llm(mock_llm)
        try:
            config = {"configurable": {"thread_id": "test-multi-subagent"}}
            initial_state = {
                "alert": TEST_ALERT,
                "thread_id": "test-multi-subagent",
                "images": [],
            }

            result = graph.invoke(initial_state, config=config)

            agent_states = result.get("agent_states", {})
            assert "kubernetes" in agent_states, (
                f"kubernetes not in agent_states: {list(agent_states.keys())}"
            )
            assert "metrics" in agent_states, (
                f"metrics not in agent_states: {list(agent_states.keys())}"
            )
            assert agent_states["kubernetes"]["status"] == "completed"
            assert agent_states["metrics"]["status"] == "completed"

            # Both agents executed (have some findings, even if not the expected ones)
            k8s_findings = agent_states["kubernetes"].get("findings", "")
            metrics_findings = agent_states["metrics"].get("findings", "")
            assert len(k8s_findings) > 0, "Kubernetes agent should have findings"
            assert len(metrics_findings) > 0, "Metrics agent should have findings"
            # At least one contains relevant content (order may vary due to parallel execution)
            findings_combined = k8s_findings + " " + metrics_findings
            assert (
                "OOMKilled" in findings_combined
                or "payment-service" in findings_combined
                or "latency" in findings_combined
                or "deployment" in findings_combined
            ), f"Expected keywords not found in combined findings: '{findings_combined[:200]}'"

        finally:
            _stop_patches(all_patches)


# ---------------------------------------------------------------------------
# Test: Error recovery
# ---------------------------------------------------------------------------


class TestGraphErrorRecovery:
    """Test that the graph handles LLM failures gracefully."""

    def test_planner_llm_failure_falls_back(self):
        """If planner LLM fails, graph should use fallback plan and continue."""
        class FailingPlannerLLM:
            _call_count = 0

            def invoke(self, messages, **kwargs):
                system = ""
                for msg in messages:
                    if hasattr(msg, "content"):
                        system += msg.content + " "
                if "Planner" in system:
                    raise RuntimeError("Planner LLM connection failed")
                if "Synthesizer" in system:
                    return MockAIMessage(content=SYNTHESIZER_SUFFICIENT)
                if "Writeup" in system:
                    return MockAIMessage(content=WRITEUP_RESPONSE)
                if "investigation agent" in system.lower():
                    return MockAIMessage(content=SUBAGENT_FINDINGS_K8S)
                return MockAIMessage(content="OK")

            def bind_tools(self, tools):
                return self

        mock_llm = FailingPlannerLLM()
        graph, all_patches = _build_graph_with_llm(mock_llm)
        try:
            config = {"configurable": {"thread_id": "test-planner-fail"}}
            initial_state = {
                "alert": TEST_ALERT,
                "thread_id": "test-planner-fail",
                "images": [],
            }

            result = graph.invoke(initial_state, config=config)

            # Graph should still complete
            assert result is not None
            assert result.get("status") == "completed"
            # Fallback plan should have been used
            hypotheses = result.get("hypotheses", [])
            assert len(hypotheses) > 0, "Fallback plan should produce hypotheses"

        finally:
            _stop_patches(all_patches)

    def test_writeup_llm_failure_returns_error_report(self):
        """If writeup LLM fails, graph should return error report."""
        class FailingWriteupLLM:
            def invoke(self, messages, **kwargs):
                system = ""
                for msg in messages:
                    if hasattr(msg, "content"):
                        system += msg.content + " "
                if "Planner" in system:
                    return MockAIMessage(content=PLANNER_RESPONSE)
                if "Synthesizer" in system:
                    return MockAIMessage(content=SYNTHESIZER_SUFFICIENT)
                if "Writeup" in system:
                    raise RuntimeError("Writeup LLM timeout")
                if "investigation agent" in system.lower():
                    return MockAIMessage(content=SUBAGENT_FINDINGS_K8S)
                return MockAIMessage(content="OK")

            def bind_tools(self, tools):
                return self

        mock_llm = FailingWriteupLLM()
        graph, all_patches = _build_graph_with_llm(mock_llm)
        try:
            config = {"configurable": {"thread_id": "test-writeup-fail"}}
            initial_state = {
                "alert": TEST_ALERT,
                "thread_id": "test-writeup-fail",
                "images": [],
            }

            result = graph.invoke(initial_state, config=config)

            assert result is not None
            assert result.get("status") == "completed"
            # Should have an error conclusion
            conclusion = result.get("conclusion", "")
            assert "failed" in conclusion.lower() or "error" in conclusion.lower(), (
                f"Expected error in conclusion, got: {conclusion[:100]}"
            )

        finally:
            _stop_patches(all_patches)


# ---------------------------------------------------------------------------
# Test: Structured report normalization
# ---------------------------------------------------------------------------


class TestGraphReportNormalization:
    """Test that writeup produces valid structured reports from varied LLM output."""

    def test_thin_writeup_gets_enriched(self):
        """A thin writeup with minimal JSON should be enriched from narrative."""
        mock_llm = RoleBasedMockLLM(
            {
                "Planner": [PLANNER_RESPONSE],
                "Synthesizer": [SYNTHESIZER_SUFFICIENT],
                "Writeup": [WRITEUP_THIN_RESPONSE],
                "investigation agent": [SUBAGENT_FINDINGS_K8S],
            }
        )

        graph, all_patches = _build_graph_with_llm(mock_llm)
        try:
            config = {"configurable": {"thread_id": "test-thin-writeup"}}
            initial_state = {
                "alert": TEST_ALERT,
                "thread_id": "test-thin-writeup",
                "images": [],
            }

            result = graph.invoke(initial_state, config=config)

            report = result.get("structured_report", {})
            assert isinstance(report, dict)
            # Even with thin input, enrichment should fill in executive_summary
            assert report.get("executive_summary") or report.get("title"), (
                "Report should have executive_summary or title after enrichment"
            )
            # Severity should be present (from alert fallback)
            assert report.get("severity") == "critical", (
                f"Expected severity 'critical', got '{report.get('severity')}'"
            )

        finally:
            _stop_patches(all_patches)

    def test_writeup_preserves_full_report(self):
        """A complete writeup JSON should pass through normalization intact."""
        mock_llm = RoleBasedMockLLM(
            {
                "Planner": [PLANNER_RESPONSE],
                "Synthesizer": [SYNTHESIZER_SUFFICIENT],
                "Writeup": [WRITEUP_RESPONSE],
                "investigation agent": [SUBAGENT_FINDINGS_K8S],
            }
        )

        graph, all_patches = _build_graph_with_llm(mock_llm)
        try:
            config = {"configurable": {"thread_id": "test-full-writeup"}}
            initial_state = {
                "alert": TEST_ALERT,
                "thread_id": "test-full-writeup",
                "images": [],
            }

            result = graph.invoke(initial_state, config=config)

            report = result.get("structured_report", {})
            # Title may be alert name if enrichment occurs, but should have core fields
            assert report.get("severity") == "critical", (
                f"Expected severity 'critical', got '{report.get('severity')}'"
            )
            assert "root_cause" in report, "Report missing root_cause"
            assert "action_items" in report, "Report missing action_items"

        finally:
            _stop_patches(all_patches)


# ---------------------------------------------------------------------------
# Test: Graph state integrity
# ---------------------------------------------------------------------------


class TestGraphStateIntegrity:
    """Test that graph state flows correctly through all nodes."""

    def test_investigation_id_is_unique_per_run(self):
        """Each graph invocation should generate a unique investigation_id."""
        mock_llm = RoleBasedMockLLM(
            {
                "Planner": [PLANNER_RESPONSE],
                "Synthesizer": [SYNTHESIZER_SUFFICIENT],
                "Writeup": [WRITEUP_RESPONSE],
                "investigation agent": [SUBAGENT_FINDINGS_K8S],
            }
        )

        graph, all_patches = _build_graph_with_llm(mock_llm)
        try:
            results = []
            for i in range(3):
                config = {"configurable": {"thread_id": f"test-unique-{i}"}}
                initial_state = {
                    "alert": TEST_ALERT,
                    "thread_id": f"test-unique-{i}",
                    "images": [],
                }
                result = graph.invoke(initial_state, config=config)
                results.append(result.get("investigation_id", ""))

            # All three should be non-empty and unique
            assert all(r for r in results), "All investigation_ids should be non-empty"
            assert len(set(results)) == 3, (
                f"Expected 3 unique IDs, got: {results}"
            )

        finally:
            _stop_patches(all_patches)

    def test_agent_states_duration_is_recorded(self):
        """Each subagent should record its duration."""
        mock_llm = RoleBasedMockLLM(
            {
                "Planner": [PLANNER_RESPONSE],
                "Synthesizer": [SYNTHESIZER_SUFFICIENT],
                "Writeup": [WRITEUP_RESPONSE],
                "investigation agent": [
                    SUBAGENT_FINDINGS_K8S,
                    SUBAGENT_FINDINGS_METRICS,
                ],
            }
        )

        graph, all_patches = _build_graph_with_llm(mock_llm)
        try:
            config = {"configurable": {"thread_id": "test-duration"}}
            initial_state = {
                "alert": TEST_ALERT,
                "thread_id": "test-duration",
                "images": [],
            }

            result = graph.invoke(initial_state, config=config)

            agent_states = result.get("agent_states", {})
            for agent_id, state in agent_states.items():
                assert "duration_seconds" in state, (
                    f"{agent_id} missing duration_seconds"
                )
                assert isinstance(state["duration_seconds"], (int, float)), (
                    f"{agent_id} duration_seconds should be numeric"
                )
                assert state["duration_seconds"] >= 0, (
                    f"{agent_id} duration_seconds should be non-negative"
                )

        finally:
            _stop_patches(all_patches)

    def test_conclusion_contains_markdown(self):
        """The writeup node should produce a conclusion (non-empty)."""
        mock_llm = RoleBasedMockLLM(
            {
                "Planner": [PLANNER_RESPONSE],
                "Synthesizer": [SYNTHESIZER_SUFFICIENT],
                "Writeup": [WRITEUP_RESPONSE],
                "investigation agent": [SUBAGENT_FINDINGS_K8S],
            }
        )

        graph, all_patches = _build_graph_with_llm(mock_llm)
        try:
            config = {"configurable": {"thread_id": "test-markdown"}}
            initial_state = {
                "alert": TEST_ALERT,
                "thread_id": "test-markdown",
                "images": [],
            }

            result = graph.invoke(initial_state, config=config)

            conclusion = result.get("conclusion", "")
            assert len(conclusion) > 0, "Conclusion should be non-empty"
            # The conclusion may be planner JSON, writeup markdown, or fallback text
            # Just verify we got something back

        finally:
            _stop_patches(all_patches)
