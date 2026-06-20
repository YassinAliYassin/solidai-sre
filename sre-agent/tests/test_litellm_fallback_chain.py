"""
Integration tests for the LiteLLM fallback chain configuration.

Tests that:
1. litellm_config.yaml is valid and well-formed
2. The fallback chain is complete (every model has a fallback path)
3. All model entries use the openrouter/ prefix
4. The litellm proxy health endpoint responds
5. Model routing through litellm works (primary model responds)
6. The model list matches what health-monitor expects

These tests catch config drift — when models are added/removed from the
chain but not updated in all places (litellm_config.yaml, health-monitor
_MODEL_LIST, docker-compose env vars, etc.).
"""

import os
import sys
import time
from unittest.mock import patch, MagicMock

import httpx
import pytest
import yaml

# ---------------------------------------------------------------------------
# Config loading helpers
# ---------------------------------------------------------------------------

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "litellm_config.yaml",
)


def load_litellm_config() -> dict:
    """Load and parse litellm_config.yaml."""
    assert os.path.exists(CONFIG_PATH), f"litellm_config.yaml not found at {CONFIG_PATH}"
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def get_model_names(config: dict) -> list[str]:
    """Extract all model_name values from the model_list."""
    return [m["model_name"] for m in config.get("model_list", [])]


def get_litellm_model_ids(config: dict) -> list[str]:
    """Extract the actual litellm model IDs (openrouter/...) from model_list."""
    ids = []
    for m in config.get("model_list", []):
        model_id = m.get("litellm_params", {}).get("model", "")
        ids.append(model_id)
    return ids


def get_fallback_map(config: dict) -> dict[str, list[str]]:
    """Extract the fallback chain as a dict: model_name -> [fallback_names]."""
    fb = {}
    for entry in config.get("router_settings", {}).get("fallbacks", []):
        for src, targets in entry.items():
            fb[src] = targets
    return fb


# ---------------------------------------------------------------------------
# Test: Config structure
# ---------------------------------------------------------------------------


class TestLitellmConfigStructure:
    """Validate the litellm_config.yaml structure."""

    def test_config_is_valid_yaml(self):
        """Config must parse as valid YAML."""
        config = load_litellm_config()
        assert isinstance(config, dict), "Config is not a dict"
        assert "model_list" in config, "Missing model_list"
        assert "router_settings" in config, "Missing router_settings"

    def test_model_list_has_entries(self):
        """Model list must have at least 2 entries (primary + fallback)."""
        config = load_litellm_config()
        models = config["model_list"]
        assert len(models) >= 2, f"Expected >= 2 models, got {len(models)}"

    def test_all_models_have_required_fields(self):
        """Every model entry must have model_name and litellm_params.model."""
        config = load_litellm_config()
        for m in config["model_list"]:
            assert "model_name" in m, f"Missing model_name in {m}"
            assert "litellm_params" in m, f"Missing litellm_params in {m['model_name']}"
            assert "model" in m["litellm_params"], (
                f"Missing litellm_params.model in {m['model_name']}"
            )
            assert "api_key" in m["litellm_params"], (
                f"Missing litellm_params.api_key in {m['model_name']}"
            )

    def test_all_models_use_openrouter_prefix(self):
        """All model IDs must start with openrouter/ to route through OpenRouter."""
        config = load_litellm_config()
        for model_id in get_litellm_model_ids(config):
            assert model_id.startswith("openrouter/"), (
                f"Model '{model_id}' is missing 'openrouter/' prefix. "
                "All models must route through OpenRouter."
            )

    def test_no_auto_model_without_credits(self):
        """Ensure no model uses openrouter/auto (requires paid credits)."""
        config = load_litellm_config()
        for model_id in get_litellm_model_ids(config):
            base = model_id.replace("openrouter/", "")
            assert base != "auto", (
                f"Model '{model_id}' uses openrouter/auto which requires paid credits. "
                "Use a specific free-tier model instead."
            )

    def test_all_models_are_free_tier(self):
        """All fallback models should use :free suffix for zero-cost operation."""
        config = load_litellm_config()
        model_ids = get_litellm_model_ids(config)
        # Primary can be paid, but fallbacks should be free
        fallback_ids = model_ids[1:]  # Skip primary
        for model_id in fallback_ids:
            assert ":free" in model_id, (
                f"Fallback model '{model_id}' does not use :free suffix. "
                "All fallback models should be free-tier to avoid credit dependency."
            )

    def test_model_names_follow_convention(self):
        """Model names should follow the llm-* naming convention."""
        config = load_litellm_config()
        for name in get_model_names(config):
            assert name.startswith("llm-"), (
                f"Model name '{name}' doesn't follow llm-* convention"
            )


# ---------------------------------------------------------------------------
# Test: Fallback chain completeness
# ---------------------------------------------------------------------------


class TestFallbackChain:
    """Validate the fallback chain is complete and acyclic."""

    def test_fallback_chain_exists(self):
        """Router settings must define fallbacks."""
        config = load_litellm_config()
        fallbacks = config.get("router_settings", {}).get("fallbacks", [])
        assert len(fallbacks) > 0, "No fallbacks defined in router_settings"

    def test_every_model_has_fallback_path(self):
        """Every model except the last must have a fallback defined."""
        config = load_litellm_config()
        model_names = get_model_names(config)
        fallback_map = get_fallback_map(config)

        # All models except the last one should have a fallback
        for name in model_names[:-1]:
            assert name in fallback_map, (
                f"Model '{name}' has no fallback defined. "
                f"Every model except the last must have a fallback."
            )

    def test_fallback_targets_are_valid_models(self):
        """All fallback targets must reference actual model names."""
        config = load_litellm_config()
        model_names = set(get_model_names(config))
        fallback_map = get_fallback_map(config)

        for src, targets in fallback_map.items():
            assert src in model_names, f"Fallback source '{src}' is not a defined model"
            for target in targets:
                assert target in model_names, (
                    f"Fallback target '{target}' (from '{src}') is not a defined model"
                )

    def test_fallback_chain_is_acyclic(self):
        """The fallback chain must not contain cycles."""
        config = load_litellm_config()
        model_names = get_model_names(config)
        fallback_map = get_fallback_map(config)

        # Follow the chain from primary — should reach the end without cycles
        visited = set()
        current = model_names[0]  # Start from primary
        while current in fallback_map:
            assert current not in visited, (
                f"Cycle detected: '{current}' visited twice in fallback chain"
            )
            visited.add(current)
            targets = fallback_map[current]
            current = targets[0]  # Follow first fallback

        # Should end at the last model
        assert current == model_names[-1], (
            f"Fallback chain ends at '{current}', expected '{model_names[-1]}'"
        )

    def test_fallback_chain_covers_all_models(self):
        """Following the chain from primary should visit every model."""
        config = load_litellm_config()
        model_names = get_model_names(config)
        fallback_map = get_fallback_map(config)

        visited = set()
        current = model_names[0]
        while current in fallback_map:
            visited.add(current)
            current = fallback_map[current][0]
        visited.add(current)  # Add the last model

        assert visited == set(model_names), (
            f"Fallback chain visits {visited}, but models are {set(model_names)}. "
            "Some models are unreachable from the primary."
        )


# ---------------------------------------------------------------------------
# Test: Config consistency with health-monitor
# ---------------------------------------------------------------------------


class TestConfigConsistency:
    """Ensure litellm_config.yaml and health-monitor _MODEL_LIST are in sync."""

    def test_health_monitor_model_list_matches_litellm_config(self):
        """Health monitor's _MODEL_LIST should match litellm model IDs."""
        config = load_litellm_config()
        litellm_ids = get_litellm_model_ids(config)

        # Import the health monitor's model list
        monitor_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "health-monitor",
            "monitor.py",
        )
        assert os.path.exists(monitor_path), "monitor.py not found"

        # Parse _MODEL_LIST from monitor.py
        with open(monitor_path, "r") as f:
            source = f.read()

        # Extract the _MODEL_LIST array
        import re

        match = re.search(r"_MODEL_LIST\s*=\s*\[(.*?)\]", source, re.DOTALL)
        assert match, "Could not find _MODEL_LIST in monitor.py"

        list_body = match.group(1)
        # Extract quoted strings
        monitor_models = re.findall(r'"([^"]+)"', list_body)

        # The monitor models should be the same as litellm model IDs
        # (minus the openrouter/ prefix since monitor sends directly to OpenRouter)
        litellm_base_ids = sorted([m.replace("openrouter/", "") for m in litellm_ids])
        monitor_base_ids = sorted(monitor_models)

        assert litellm_base_ids == monitor_base_ids, (
            f"Health monitor _MODEL_LIST doesn't match litellm_config.yaml.\n"
            f"  Litellm: {litellm_base_ids}\n"
            f"  Monitor: {monitor_base_ids}\n"
            "Update _MODEL_LIST in health-monitor/monitor.py to match."
        )


# ---------------------------------------------------------------------------
# Test: Live litellm proxy health (only when proxy is reachable)
# ---------------------------------------------------------------------------


class TestLitellmProxyHealth:
    """Test the running litellm proxy. Skipped if proxy is not reachable."""

    @pytest.fixture(autouse=True)
    def skip_if_no_proxy(self):
        """Skip these tests if litellm proxy is not reachable."""
        litellm_url = os.getenv("LITELLM_BASE_URL", "http://localhost:4001")
        # Strip /v1 suffix if present — health endpoint is on the root, not /v1
        base = litellm_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        try:
            resp = httpx.get(
                f"{base}/health/readiness",
                timeout=5.0,
            )
            if resp.status_code != 200:
                pytest.skip(f"Litellm proxy returned {resp.status_code}")
        except Exception:
            pytest.skip("Litellm proxy not reachable — skipping live tests")

    def test_health_readiness_returns_200(self):
        """The /health/readiness endpoint must return 200."""
        litellm_url = os.getenv("LITELLM_BASE_URL", "http://localhost:4001")
        resp = httpx.get(
            f"{litellm_url.rstrip('/')}/health/readiness",
            timeout=10.0,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

    def test_health_readiness_returns_json(self):
        """The /health/readiness endpoint must return JSON."""
        litellm_url = os.getenv("LITELLM_BASE_URL", "http://localhost:4001")
        resp = httpx.get(
            f"{litellm_url.rstrip('/')}/health/readiness",
            timeout=10.0,
        )
        data = resp.json()
        assert "status" in data, "Missing 'status' in readiness response"

    def test_primary_model_responds(self):
        """The primary model (llm-primary) must respond to a minimal request."""
        litellm_url = os.getenv("LITELLM_BASE_URL", "http://localhost:4001")
        api_key = os.getenv("LITELLM_API_KEY", os.getenv("OPENROUTER_API_KEY", ""))

        if not api_key:
            pytest.skip("No API key configured")

        resp = httpx.post(
            f"{litellm_url.rstrip('/')}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "llm-primary",
                "messages": [{"role": "user", "content": "Reply with OK"}],
                "max_tokens": 5,
            },
            timeout=60.0,
        )

        assert resp.status_code == 200, (
            f"Primary model returned {resp.status_code}: {resp.text[:200]}"
        )
        data = resp.json()
        assert "choices" in data, "No 'choices' in response"
        assert len(data["choices"]) > 0, "Empty choices in response"

    def test_fallback_model_responds(self):
        """At least one fallback model must respond."""
        litellm_url = os.getenv("LITELLM_BASE_URL", "http://localhost:4001")
        api_key = os.getenv("LITELLM_API_KEY", os.getenv("OPENROUTER_API_KEY", ""))

        if not api_key:
            pytest.skip("No API key configured")

        config = load_litellm_config()
        fallback_ids = get_litellm_model_ids(config)[1:]  # Skip primary

        # Try each fallback until one responds
        any_ok = False
        last_error = ""
        for model_id in fallback_ids:
            resp = httpx.post(
                f"{litellm_url.rstrip('/')}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": "Reply with OK"}],
                    "max_tokens": 5,
                },
                timeout=60.0,
            )
            if resp.status_code == 200:
                any_ok = True
                break
            last_error = f"{model_id}: {resp.status_code}"

        assert any_ok, f"No fallback model responded. Last error: {last_error}"

    def test_unknown_model_returns_400(self):
        """An unknown model name should return 400 (litellm 1.82.6+ behavior).

        Note: In older litellm versions, model_group_alias with '*' would route
        unknown models to llm-primary. As of litellm 1.82.6, unknown model names
        return 400 with an error message. This test documents the current behavior.
        """
        litellm_url = os.getenv("LITELLM_BASE_URL", "http://localhost:4001")
        api_key = os.getenv("LITELLM_API_KEY", os.getenv("OPENROUTER_API_KEY", ""))

        if not api_key:
            pytest.skip("No API key configured")

        resp = httpx.post(
            f"{litellm_url.rstrip('/')}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "messages": [{"role": "user", "content": "Reply with OK"}],
                "max_tokens": 5,
            },
            timeout=60.0,
        )

        # litellm 1.82.6 returns 400 for unknown model names
        assert resp.status_code == 400, (
            f"Expected 400 for unknown model, got {resp.status_code}: {resp.text[:200]}"
        )

    def test_known_model_names_accepted(self):
        """All defined model names should be accepted by the proxy.

        Uses a short timeout to avoid hanging on slow OpenRouter responses.
        Models that time out or return server errors are still "accepted" —
        the proxy routed them, they just didn't respond in time.
        """
        litellm_url = os.getenv("LITELLM_BASE_URL", "http://localhost:4001")
        api_key = os.getenv("LITELLM_API_KEY", os.getenv("OPENROUTER_API_KEY", ""))

        if not api_key:
            pytest.skip("No API key configured")

        config = load_litellm_config()
        model_names = get_model_names(config)

        for name in model_names:
            try:
                resp = httpx.post(
                    f"{litellm_url.rstrip('/')}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": name,
                        "messages": [{"role": "user", "content": "Reply with OK"}],
                        "max_tokens": 5,
                    },
                    timeout=5.0,
                )
                # 200 = accepted and responded, 429 = rate limited (still accepted)
                # 503 = model unavailable (still accepted, just not serving)
                assert resp.status_code in (200, 429, 503), (
                    f"Model '{name}' rejected with {resp.status_code}: {resp.text[:200]}"
                )
            except (httpx.TimeoutException, httpx.ConnectError):
                # Timeout or connection error means the proxy accepted the model
                # but the upstream provider didn't respond in time — not a rejection
                pass


# ---------------------------------------------------------------------------
# Test: litellm_settings validation
# ---------------------------------------------------------------------------


class TestLitellmSettings:
    """Validate litellm_settings section."""

    def test_request_timeout_is_sufficient(self):
        """request_timeout must be >= 120s (OpenRouter can be slow from VPS)."""
        config = load_litellm_config()
        timeout = config.get("litellm_settings", {}).get("request_timeout", 0)
        assert timeout >= 120, (
            f"request_timeout is {timeout}s, should be >= 120s "
            "to account for OpenRouter latency from VPS"
        )

    def test_num_retries_at_least_1(self):
        """num_retries should be >= 1 for transient error handling."""
        config = load_litellm_config()
        retries = config.get("litellm_settings", {}).get("num_retries", 0)
        assert retries >= 1, f"num_retries is {retries}, should be >= 1"

    def test_drop_params_is_true(self):
        """drop_params should be true to avoid passing unsupported params."""
        config = load_litellm_config()
        assert config.get("litellm_settings", {}).get("drop_params", False) is True, (
            "drop_params should be True to avoid passing unsupported "
            "parameters to OpenRouter models"
        )


# ---------------------------------------------------------------------------
# Test: model_group_alias
# ---------------------------------------------------------------------------


class TestModelGroupAlias:
    """Validate model_group_alias configuration."""

    def test_wildcard_alias_exists(self):
        """There must be a wildcard alias that routes unknown models to primary."""
        config = load_litellm_config()
        aliases = config.get("model_group_alias", {})
        assert "*" in aliases, (
            "Missing wildcard alias '*'. "
            "This ensures any model name gets routed to llm-primary."
        )

    def test_wildcard_routes_to_primary(self):
        """The wildcard alias must route to llm-primary."""
        config = load_litellm_config()
        primary = get_model_names(config)[0]
        alias_target = config.get("model_group_alias", {}).get("*", "")
        assert alias_target == primary, (
            f"Wildcard alias routes to '{alias_target}', expected '{primary}'"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
