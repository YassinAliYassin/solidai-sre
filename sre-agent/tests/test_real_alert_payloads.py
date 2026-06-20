#!/usr/bin/env python3
"""
Integration tests: Real-world alert payloads through the full LangGraph.

Tests the complete investigation pipeline with realistic SolidAI SRE alerts
— the kinds of alerts the platform is designed to handle in production.

Covers:
1. High error rate on a production service (payment-service OOM)
2. NGINX upstream timeout on solidsolutions.africa
3. Database connection pool exhaustion
4. Cascading failure across multiple services
5. Alert with minimal data (graceful degradation)
6. Alert at max-iteration boundary
7. Planner dispatched agents match alert type

Each test runs the full graph with mocked LLM responses but REAL alert
payloads that mirror what the Telegram bot / AionUI would send.
"""

import json
import os
import sys
import unittest.mock as mock
from unittest.mock import MagicMock, patch

import pytest

from langgraph.checkpoint.memory import MemorySaver

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ---------------------------------------------------------------------------
# Reuse test infrastructure from test_graph_integration.py
# ---------------------------------------------------------------------------

from test_graph_integration import (
    MockAIMessage,
    RoleBasedMockLLM,
    PLANNER_RESPONSE,
    SYNTHESIZER_SUFFICIENT,
    SYNTHESIZER_INSUFFICIENT,
    WRITEUP_RESPONSE,
    WRITEUP_THIN_RESPONSE,
    _build_graph_with_llm,
    _common_patches,
    _mock_load_team_config,
    _stop_patches,
    MOCK_TEAM_CONFIG_RAW,
    MOCK_TEAM_CONFIG_RAW_MAX2,
)

# ---------------------------------------------------------------------------
# Real-world alert payloads (mirror what AionUI / Telegram bot sends)
# ---------------------------------------------------------------------------

ALERT_PAYMENT_OOM = {
    "name": "HighErrorRate",
    "service": "payment-service",
    "namespace": "production",
    "severity": "critical",
    "timestamp": "2026-06-20T14:30:00Z",
    "description": "Payment service error rate above 5% for 10 minutes",
    "labels": {
        "app": "payment-service",
        "env": "production",
        "team": "payments",
    },
    "annotations": {
        "summary": "Payment service experiencing high error rate",
        "runbook": "https://wiki.internal/runbooks/payment-service",
    },
    "metrics": {
        "error_rate": 0.073,
        "p99_latency_ms": 2500,
        "rps": 150,
    },
}

ALERT_NGINX_TIMEOUT = {
    "name": "UpstreamTimeout",
    "service": "solidsolutions.africa",
    "severity": "high",
    "timestamp": "2026-06-20T15:00:00Z",
    "description": "NGINX upstream timed out (110: Connection timed out) connecting to app backend",
    "labels": {
        "host": "solidsolutions.africa",
        "component": "nginx",
    },
    "annotations": {
        "upstream": "127.0.0.1:8080",
        "error_log": "/var/log/nginx/error.log",
    },
}

ALERT_DB_POOL_EXHAUSTED = {
    "name": "DatabaseConnectionPoolExhausted",
    "service": "user-service",
    "namespace": "production",
    "severity": "critical",
    "timestamp": "2026-06-20T16:45:00Z",
    "description": "All 50 database connections in use, requests waiting > 30s",
    "labels": {
        "app": "user-service",
        "database": "postgres-primary",
    },
    "metrics": {
        "active_connections": 50,
        "max_connections": 50,
        "waiting_requests": 120,
        "avg_wait_seconds": 35.2,
    },
}

ALERT_CASCADING_FAILURE = {
    "name": "CascadingFailure",
    "service": "order-service",
    "namespace": "production",
    "severity": "critical",
    "timestamp": "2026-06-20T17:00:00Z",
    "description": (
        "Multiple services reporting errors: order-service (40% error rate), "
        "inventory-service (timeout), payment-service (circuit breaker open)"
    ),
    "labels": {
        "app": "order-service",
        "env": "production",
        "blast_radius": "3-services",
    },
    "affected_services": ["order-service", "inventory-service", "payment-service"],
}

ALERT_MINIMAL = {
    "name": "ServiceDown",
    "service": "solidai-gateway",
    "severity": "critical",
}

ALERT_GATEWAY_UNREACHABLE = {
    "name": "GatewayUnreachable",
    "service": "solidai-gateway",
    "severity": "critical",
    "timestamp": "2026-06-20T18:00:00Z",
    "description": "SolidAI Gateway at localhost:18789 not responding to health checks",
    "labels": {
        "host": "localhost",
        "port": "18789",
        "component": "gateway",
    },
}

# ---------------------------------------------------------------------------
# Subagent findings for different alert types
# ---------------------------------------------------------------------------

FINDINGS_K8S_OOM = (
    "Found pod payment-service-7b8f9c6d4-xk2lm in OOMKilled state. "
    "Container memory limit 512Mi, usage peaked at 508Mi before kill. "
    "Restart count: 15 in last hour. Node memory pressure: 85%. "
    "Recommendation: Increase memory limit to 1Gi or add horizontal pod autoscaler."
)

FINDINGS_METRICS_ERROR_SPIKE = (
    "Error rate spike started at 14:20 UTC, correlating with deployment v2.3.1. "
    "P99 latency increased from 200ms to 2.5s. "
    "CPU throttling detected on payment-service pods (cpu limit: 500m). "
    "Rollback to v2.2.9 recommended."
)

FINDINGS_LOG_ANALYSIS_NGINX = (
    "NGINX error log shows 502/504 errors from upstream 127.0.0.1:8080. "
    "Pattern: timeouts spike every 5 minutes, lasting 30-60 seconds. "
    "Upstream app (config-service) shows high GC pauses (2-4s) during these windows. "
    "JVM heap at 92% capacity. Recommend increasing heap or tuning GC."
)

FINDINGS_DB_CONNECTIONS = (
    "PostgreSQL primary shows 50/50 active connections. "
    "Longest-running query: 45s (SELECT ... FROM orders JOIN payments ...). "
    "Connection pool (HikariCP) exhausted — all threads waiting on connection.acquire. "
    "Slow query log shows unindexed query on orders.created_at. "
    "Recommend: add index, increase pool size, kill long-running query."
)

FINDINGS_CASCADING = (
    "Root cause analysis: order-service v3.0.0 deployed at 16:55 UTC introduced "
    "a bug in inventory check logic (infinite retry loop). "
    "This caused inventory-service thread pool exhaustion, which cascaded to "
    "payment-service circuit breaker opening. "
    "Rollback order-service to v2.9.3 to resolve all three services."
)

FINDINGS_GATEWAY_DOWN = (
    "SolidAI Gateway process not running on port 18789. "
    "PM2 status: errored (restarted 10 times). "
    "Last error: 'Error: listen EADDRINUSE: address already in use :::18789'. "
    "Stale process found (PID 12345). Kill stale process and restart gateway."
)

# ---------------------------------------------------------------------------
# Writeup responses for different alert types
# ---------------------------------------------------------------------------

WRITEUP_NGINX = (
    "# Incident Report: NGINX Upstream Timeout on solidsolutions.africa\n\n"
    "Root cause: config-service JVM GC pauses causing NGINX upstream timeouts.\n\n"
    "```json\n"
    + json.dumps({
        "title": "NGINX Upstream Timeout — solidsolutions.africa",
        "severity": "high",
        "services": ["solidsolutions.africa", "config-service"],
        "root_cause": "JVM GC pauses in config-service",
        "findings": [
            {
                "category": "NGINX",
                "detail": "502/504 errors from upstream",
                "evidence": "error_log analysis",
            },
        ],
        "action_items": [
            {
                "priority": "high",
                "action": "Increase JVM heap or tune GC",
                "owner": "platform",
            },
        ],
        "resolution_status": "mitigated",
    })
    + "\n```"
)

WRITEUP_DB = (
    "# Incident Report: Database Connection Pool Exhausted\n\n"
    "Root cause: Unindexed slow query exhausting HikariCP connection pool.\n\n"
    "```json\n"
    + json.dumps({
        "title": "DB Pool Exhausted — user-service",
        "severity": "critical",
        "services": ["user-service", "postgres-primary"],
        "root_cause": "Unindexed query on orders.created_at",
        "action_items": [
            {"priority": "critical", "action": "Add index on orders.created_at", "owner": "backend"},
            {"priority": "high", "action": "Increase HikariCP pool size", "owner": "backend"},
        ],
        "resolution_status": "identified",
    })
    + "\n```"
)

WRITEUP_CASCADING = (
    "# Incident Report: Cascading Failure — Order Service\n\n"
    "Root cause: Bug in order-service v3.0.0 causing cascading failure.\n\n"
    "```json\n"
    + json.dumps({
        "title": "Cascading Failure — order-service v3.0.0",
        "severity": "critical",
        "services": ["order-service", "inventory-service", "payment-service"],
        "root_cause": "Infinite retry loop in inventory check logic",
        "action_items": [
            {"priority": "critical", "action": "Rollback order-service to v2.9.3", "owner": "payments-team"},
        ],
        "resolution_status": "identified",
    })
    + "\n```"
)

WRITEUP_GATEWAY = (
    "# Incident Report: SolidAI Gateway Unreachable\n\n"
    "Root cause: Stale process holding port 18789, PM2 in error loop.\n\n"
    "```json\n"
    + json.dumps({
        "title": "Gateway Unreachable — port 18789",
        "severity": "critical",
        "services": ["solidai-gateway"],
        "root_cause": "Stale process (PID 12345) holding port",
        "action_items": [
            {"priority": "critical", "action": "Kill PID 12345 and restart gateway via PM2", "owner": "sre"},
        ],
        "resolution_status": "identified",
    })
    + "\n```"
)

# Planner responses for different alert types
PLANNER_NGINX_RESPONSE = json.dumps({
    "hypotheses": [
        {
            "hypothesis": "NGINX upstream timeout caused by slow backend response",
            "priority": "high",
            "agents_to_test": ["log_analysis", "metrics"],
        }
    ],
    "selected_agents": ["log_analysis", "metrics"],
    "reasoning": "NGINX timeout — need log analysis and metrics investigation",
})

PLANNER_DB_RESPONSE = json.dumps({
    "hypotheses": [
        {
            "hypothesis": "Database connection pool exhausted by slow queries",
            "priority": "high",
            "agents_to_test": ["log_analysis", "metrics"],
        }
    ],
    "selected_agents": ["log_analysis", "metrics"],
    "reasoning": "DB pool exhaustion — need log analysis and metrics",
})

PLANNER_CASCADING_RESPONSE = json.dumps({
    "hypotheses": [
        {
            "hypothesis": "Cascading failure from order-service deployment",
            "priority": "high",
            "agents_to_test": ["kubernetes", "log_analysis", "metrics"],
        }
    ],
    "selected_agents": ["kubernetes", "log_analysis", "metrics"],
    "reasoning": "Cascading failure — need k8s, logs, and metrics investigation",
})

PLANNER_GATEWAY_RESPONSE = json.dumps({
    "hypotheses": [
        {
            "hypothesis": "Gateway process crashed or port conflict",
            "priority": "high",
            "agents_to_test": ["log_analysis"],
        }
    ],
    "selected_agents": ["log_analysis"],
    "reasoning": "Gateway unreachable — need log analysis to find root cause",
})

# Team configs with log_analysis enabled for different alert types
MOCK_TEAM_CONFIG_WITH_LOGS = {
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
                "log_analysis": True,
            },
        },
        "writeup": {
            "prompt": {"system": ""},
            "model": {"name": "test-model"},
        },
    },
    "skills": {"enabled": ["*"]},
}

MOCK_TEAM_CONFIG_LOGS_ONLY = {
    "agents": {
        "planner": {
            "prompt": {"system": ""},
            "model": {"name": "test-model"},
            "max_iterations": 3,
        },
        "investigation": {
            "sub_agents": {
                "log_analysis": True,
            },
        },
        "writeup": {
            "prompt": {"system": ""},
            "model": {"name": "test-model"},
        },
    },
    "skills": {"enabled": ["*"]},
}


# ---------------------------------------------------------------------------
# Tests: Real-world alert payloads
# ---------------------------------------------------------------------------


class TestRealAlertPaymentOOM:
    """Test: High error rate on payment-service (OOM scenario)."""

    def test_payment_oom_alert_completes(self):
        """Full graph run with payment-service OOM alert payload."""
        mock_llm = RoleBasedMockLLM({
            "Planner": [PLANNER_RESPONSE],
            "Synthesizer": [SYNTHESIZER_SUFFICIENT],
            "Writeup": [WRITEUP_RESPONSE],
            "investigation agent": [FINDINGS_K8S_OOM, FINDINGS_METRICS_ERROR_SPIKE],
        })

        graph, all_patches = _build_graph_with_llm(mock_llm)
        try:
            config = {"configurable": {"thread_id": "test-payment-oom"}}
            result = graph.invoke({
                "alert": ALERT_PAYMENT_OOM,
                "thread_id": "test-payment-oom",
                "images": [],
            }, config=config)

            assert result is not None
            assert result.get("status") == "completed"
            assert len(result.get("conclusion", "")) > 0
            assert "structured_report" in result

            # Verify alert data propagated
            assert result.get("alert", {}).get("service") == "payment-service"
            assert result.get("alert", {}).get("severity") == "critical"

            # Verify subagent states
            agent_states = result.get("agent_states", {})
            assert "kubernetes" in agent_states
            assert "metrics" in agent_states

            # Verify structured report has expected fields
            report = result["structured_report"]
            assert "title" in report
            assert "severity" in report
        finally:
            _stop_patches(all_patches)


class TestRealAlertNginxTimeout:
    """Test: NGINX upstream timeout on solidsolutions.africa."""

    def test_nginx_timeout_alert_completes(self):
        """Full graph run with NGINX timeout alert payload."""
        mock_llm = RoleBasedMockLLM({
            "Planner": [PLANNER_NGINX_RESPONSE],
            "Synthesizer": [SYNTHESIZER_SUFFICIENT],
            "Writeup": [WRITEUP_NGINX],
            "investigation agent": [FINDINGS_LOG_ANALYSIS_NGINX, FINDINGS_METRICS_ERROR_SPIKE],
        })

        graph, all_patches = _build_graph_with_llm(
            mock_llm, raw_config=MOCK_TEAM_CONFIG_WITH_LOGS
        )
        try:
            config = {"configurable": {"thread_id": "test-nginx-timeout"}}
            result = graph.invoke({
                "alert": ALERT_NGINX_TIMEOUT,
                "thread_id": "test-nginx-timeout",
                "images": [],
            }, config=config)

            assert result is not None
            assert result.get("status") == "completed"
            assert "structured_report" in result

            # Verify alert data propagated
            assert result.get("alert", {}).get("service") == "solidsolutions.africa"

            # Verify log_analysis agent was dispatched (NGINX-specific)
            agent_states = result.get("agent_states", {})
            assert "log_analysis" in agent_states
        finally:
            _stop_patches(all_patches)


class TestRealAlertDBPoolExhausted:
    """Test: Database connection pool exhaustion."""

    def test_db_pool_alert_completes(self):
        """Full graph run with DB connection pool exhaustion alert."""
        mock_llm = RoleBasedMockLLM({
            "Planner": [PLANNER_DB_RESPONSE],
            "Synthesizer": [SYNTHESIZER_SUFFICIENT],
            "Writeup": [WRITEUP_DB],
            "investigation agent": [FINDINGS_DB_CONNECTIONS, FINDINGS_METRICS_ERROR_SPIKE],
        })

        graph, all_patches = _build_graph_with_llm(
            mock_llm, raw_config=MOCK_TEAM_CONFIG_WITH_LOGS
        )
        try:
            config = {"configurable": {"thread_id": "test-db-pool"}}
            result = graph.invoke({
                "alert": ALERT_DB_POOL_EXHAUSTED,
                "thread_id": "test-db-pool",
                "images": [],
            }, config=config)

            assert result is not None
            assert result.get("status") == "completed"
            assert "structured_report" in result

            # Verify metrics propagated from alert
            alert = result.get("alert", {})
            assert alert.get("service") == "user-service"
            assert alert.get("metrics", {}).get("active_connections") == 50
        finally:
            _stop_patches(all_patches)


class TestRealAlertCascadingFailure:
    """Test: Cascading failure across multiple services."""

    def test_cascading_failure_completes(self):
        """Full graph run with cascading failure alert (3 services affected)."""
        mock_llm = RoleBasedMockLLM({
            "Planner": [PLANNER_CASCADING_RESPONSE],
            "Synthesizer": [SYNTHESIZER_SUFFICIENT],
            "Writeup": [WRITEUP_CASCADING],
            "investigation agent": [
                FINDINGS_CASCADING,
                FINDINGS_LOG_ANALYSIS_NGINX,
                FINDINGS_METRICS_ERROR_SPIKE,
            ],
        })

        graph, all_patches = _build_graph_with_llm(
            mock_llm, raw_config=MOCK_TEAM_CONFIG_WITH_LOGS
        )
        try:
            config = {"configurable": {"thread_id": "test-cascading"}}
            result = graph.invoke({
                "alert": ALERT_CASCADING_FAILURE,
                "thread_id": "test-cascading",
                "images": [],
            }, config=config)

            assert result is not None
            assert result.get("status") == "completed"
            assert "structured_report" in result

            # Verify all 3 subagents were dispatched
            agent_states = result.get("agent_states", {})
            assert "kubernetes" in agent_states
            assert "log_analysis" in agent_states
            assert "metrics" in agent_states

            # Verify affected services in alert
            alert = result.get("alert", {})
            assert "order-service" in alert.get("affected_services", [])
        finally:
            _stop_patches(all_patches)


class TestRealAlertMinimalPayload:
    """Test: Alert with minimal data (graceful degradation)."""

    def test_minimal_alert_completes(self):
        """Graph handles alert with only name, service, severity — no extras."""
        mock_llm = RoleBasedMockLLM({
            "Planner": [PLANNER_RESPONSE],
            "Synthesizer": [SYNTHESIZER_SUFFICIENT],
            "Writeup": [WRITEUP_RESPONSE],
            "investigation agent": [FINDINGS_K8S_OOM, FINDINGS_METRICS_ERROR_SPIKE],
        })

        graph, all_patches = _build_graph_with_llm(mock_llm)
        try:
            config = {"configurable": {"thread_id": "test-minimal"}}
            result = graph.invoke({
                "alert": ALERT_MINIMAL,
                "thread_id": "test-minimal",
                "images": [],
            }, config=config)

            assert result is not None
            assert result.get("status") == "completed"
            assert "structured_report" in result

            # Verify minimal alert data propagated
            alert = result.get("alert", {})
            assert alert.get("name") == "ServiceDown"
            assert alert.get("service") == "solidai-gateway"
            assert alert.get("severity") == "critical"
        finally:
            _stop_patches(all_patches)


class TestRealAlertGatewayUnreachable:
    """Test: SolidAI Gateway unreachable (localhost:18789)."""

    def test_gateway_unreachable_completes(self):
        """Full graph run with SolidAI Gateway unreachable alert."""
        mock_llm = RoleBasedMockLLM({
            "Planner": [PLANNER_GATEWAY_RESPONSE],
            "Synthesizer": [SYNTHESIZER_SUFFICIENT],
            "Writeup": [WRITEUP_GATEWAY],
            "investigation agent": [FINDINGS_GATEWAY_DOWN],
        })

        graph, all_patches = _build_graph_with_llm(
            mock_llm, raw_config=MOCK_TEAM_CONFIG_LOGS_ONLY
        )
        try:
            config = {"configurable": {"thread_id": "test-gateway-down"}}
            result = graph.invoke({
                "alert": ALERT_GATEWAY_UNREACHABLE,
                "thread_id": "test-gateway-down",
                "images": [],
            }, config=config)

            assert result is not None
            assert result.get("status") == "completed"
            assert "structured_report" in result

            # Verify gateway-specific alert data
            alert = result.get("alert", {})
            assert alert.get("service") == "solidai-gateway"
            assert alert.get("labels", {}).get("port") == "18789"
        finally:
            _stop_patches(all_patches)


class TestRealAlertWithLoop:
    """Test: Real alert that requires multiple investigation iterations."""

    def test_payment_oom_with_two_iterations(self):
        """Payment OOM alert loops once before concluding."""
        mock_llm = RoleBasedMockLLM({
            "Planner": [PLANNER_RESPONSE, PLANNER_RESPONSE],
            "Synthesizer": [SYNTHESIZER_INSUFFICIENT, SYNTHESIZER_SUFFICIENT],
            "Writeup": [WRITEUP_RESPONSE],
            "investigation agent": [
                FINDINGS_K8S_OOM,
                FINDINGS_METRICS_ERROR_SPIKE,
                FINDINGS_K8S_OOM,
                FINDINGS_METRICS_ERROR_SPIKE,
            ],
        })

        graph, all_patches = _build_graph_with_llm(mock_llm)
        try:
            config = {"configurable": {"thread_id": "test-payment-loop"}}
            result = graph.invoke({
                "alert": ALERT_PAYMENT_OOM,
                "thread_id": "test-payment-loop",
                "images": [],
            }, config=config)

            assert result is not None
            assert result.get("status") == "completed"
            assert result.get("iteration", 0) >= 1

            # Verify synthesizer feedback was generated
            messages = result.get("messages", [])
            has_synthesizer = any(
                isinstance(m, dict) and m.get("role") == "synthesizer"
                for m in messages
            )
            assert has_synthesizer
        finally:
            _stop_patches(all_patches)


class TestRealAlertMaxIterationBoundary:
    """Test: Real alert at max-iteration boundary."""

    def test_cascading_failure_at_max_iterations(self):
        """Cascading failure forced to conclude at max_iterations=2."""
        cascading_max2 = {
            "agents": {
                "planner": {
                    "prompt": {"system": ""},
                    "model": {"name": "test-model"},
                    "max_iterations": 2,
                },
                "investigation": {
                    "sub_agents": {
                        "kubernetes": True,
                        "log_analysis": True,
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
        mock_llm = RoleBasedMockLLM({
            "Planner": [PLANNER_CASCADING_RESPONSE, PLANNER_CASCADING_RESPONSE],
            "Synthesizer": [SYNTHESIZER_INSUFFICIENT, SYNTHESIZER_INSUFFICIENT],
            "Writeup": [WRITEUP_CASCADING],
            "investigation agent": [
                FINDINGS_CASCADING,
                FINDINGS_LOG_ANALYSIS_NGINX,
                FINDINGS_CASCADING,
                FINDINGS_LOG_ANALYSIS_NGINX,
            ],
        })

        graph, all_patches = _build_graph_with_llm(
            mock_llm, raw_config=cascading_max2
        )
        try:
            config = {"configurable": {"thread_id": "test-cascading-maxiter"}}
            result = graph.invoke({
                "alert": ALERT_CASCADING_FAILURE,
                "thread_id": "test-cascading-maxiter",
                "images": [],
            }, config=config)

            assert result is not None
            assert result.get("status") == "completed"
            assert "structured_report" in result
        finally:
            _stop_patches(all_patches)


class TestRealAlertAgentDispatchMatchesAlert:
    """Test: Verify planner dispatches appropriate agents for alert type."""

    def test_nginx_alert_dispatches_log_analysis(self):
        """NGINX timeout alert should dispatch log_analysis agent."""
        mock_llm = RoleBasedMockLLM({
            "Planner": [PLANNER_NGINX_RESPONSE],
            "Synthesizer": [SYNTHESIZER_SUFFICIENT],
            "Writeup": [WRITEUP_NGINX],
            "investigation agent": [FINDINGS_LOG_ANALYSIS_NGINX, FINDINGS_METRICS_ERROR_SPIKE],
        })

        graph, all_patches = _build_graph_with_llm(
            mock_llm, raw_config=MOCK_TEAM_CONFIG_WITH_LOGS
        )
        try:
            config = {"configurable": {"thread_id": "test-nginx-agents"}}
            result = graph.invoke({
                "alert": ALERT_NGINX_TIMEOUT,
                "thread_id": "test-nginx-agents",
                "images": [],
            }, config=config)

            selected = result.get("selected_agents", [])
            assert "log_analysis" in selected, (
                f"Expected log_analysis for NGINX alert, got {selected}"
            )
        finally:
            _stop_patches(all_patches)

    def test_cascading_alert_dispatches_three_agents(self):
        """Cascading failure should dispatch kubernetes + log_analysis + metrics."""
        mock_llm = RoleBasedMockLLM({
            "Planner": [PLANNER_CASCADING_RESPONSE],
            "Synthesizer": [SYNTHESIZER_SUFFICIENT],
            "Writeup": [WRITEUP_CASCADING],
            "investigation agent": [
                FINDINGS_CASCADING,
                FINDINGS_LOG_ANALYSIS_NGINX,
                FINDINGS_METRICS_ERROR_SPIKE,
            ],
        })

        graph, all_patches = _build_graph_with_llm(
            mock_llm, raw_config=MOCK_TEAM_CONFIG_WITH_LOGS
        )
        try:
            config = {"configurable": {"thread_id": "test-cascading-agents"}}
            result = graph.invoke({
                "alert": ALERT_CASCADING_FAILURE,
                "thread_id": "test-cascading-agents",
                "images": [],
            }, config=config)

            selected = result.get("selected_agents", [])
            assert len(selected) >= 3, (
                f"Expected >= 3 agents for cascading failure, got {selected}"
            )
            assert "kubernetes" in selected
            assert "log_analysis" in selected
            assert "metrics" in selected
        finally:
            _stop_patches(all_patches)
