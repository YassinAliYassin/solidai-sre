#!/usr/bin/env python3
"""
HTTP integration tests for sre-agent knowledge graph endpoints.

Tests the live running server (port 8001) for:
1. /knowledge-graph/service/{name} — service topology from Neo4j
2. /knowledge-graph/status/{name} — Kubernetes status from Neo4j
3. /knowledge-graph/service/{name} with unknown service
4. /knowledge-graph/status/{name} with unknown service
5. Response structure validation — all required fields present
6. Blast radius structure validation
7. Concurrent load — multiple KG queries in parallel

Requires: sre-agent running in Docker (port 8001), Neo4j running (port 7687)
"""

import json
import sys
import time
import urllib.request
import urllib.error
import concurrent.futures

AGENT_URL = "http://localhost:8001"


def _get(path: str) -> dict:
    """GET a JSON endpoint and return parsed dict."""
    req = urllib.request.Request(f"{AGENT_URL}{path}")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def test_kg_service_endpoint():
    """Test /knowledge-graph/service/{name} returns valid topology data."""
    result = _get("/knowledge-graph/service/test")
    assert result["success"] is True, f"Expected success=True, got {result}"
    assert "result" in result, "Missing 'result' field"
    res = result["result"]
    assert "resolved_name" in res, f"Missing 'resolved_name' in result: {res}"
    assert "upstream_dependents" in res, "Missing 'upstream_dependents'"
    assert "downstream_dependencies" in res, "Missing 'downstream_dependencies'"
    assert "configmaps" in res, "Missing 'configmaps'"
    assert "blast_radius" in res, "Missing 'blast_radius'"
    print("  PASS: /knowledge-graph/service/test returns valid topology")


def test_kg_service_blast_radius_structure():
    """Validate blast_radius structure in service response."""
    result = _get("/knowledge-graph/service/test")
    br = result["result"]["blast_radius"]
    assert "upstream_count" in br, "Missing upstream_count in blast_radius"
    assert "downstream_count" in br, "Missing downstream_count in blast_radius"
    assert "affected_services" in br, "Missing affected_services in blast_radius"
    assert isinstance(br["upstream_count"], int), "upstream_count should be int"
    assert isinstance(br["affected_services"], list), "affected_services should be list"
    print("  PASS: blast_radius structure validated")


def test_kg_status_endpoint():
    """Test /knowledge-graph/status/{name} returns valid K8s status."""
    result = _get("/knowledge-graph/status/test")
    assert result["success"] is True, f"Expected success=True, got {result}"
    assert "result" in result, "Missing 'result' field"
    res = result["result"]
    # Status endpoint may return empty dict if no K8s data, but structure should be valid
    assert isinstance(res, dict), f"Expected dict result, got {type(res)}"
    print("  PASS: /knowledge-graph/status/test returns valid K8s status")


def test_kg_service_unknown_name():
    """Test /knowledge-graph/service/{name} with a non-existent service."""
    result = _get("/knowledge-graph/service/nonexistent-service-xyz")
    # Should still return success=True with empty topology (resolved_name matches input)
    assert result["success"] is True, f"Expected success=True, got {result}"
    assert result["result"]["resolved_name"] == "nonexistent-service-xyz"
    assert result["result"]["blast_radius"]["upstream_count"] == 0
    print("  PASS: unknown service returns empty topology (not error)")


def test_kg_status_unknown_name():
    """Test /knowledge-graph/status/{name} with a non-existent service."""
    result = _get("/knowledge-graph/status/nonexistent-service-xyz")
    assert result["success"] is True, f"Expected success=True, got {result}"
    print("  PASS: unknown service status returns valid response")


def test_kg_service_response_format():
    """Validate exact response format matches API contract."""
    result = _get("/knowledge-graph/service/test")
    # Must have exactly these top-level keys
    assert set(result.keys()) == {"success", "result"}, (
        f"Unexpected keys: {set(result.keys())}"
    )
    assert isinstance(result["success"], bool)
    # Result must be a dict
    assert isinstance(result["result"], dict)
    print("  PASS: response format matches API contract")


def test_kg_concurrent_load():
    """Test knowledge graph handles concurrent queries."""
    def query_service(i):
        return _get(f"/knowledge-graph/service/test")

    start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(query_service, i) for i in range(5)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
    elapsed = time.time() - start

    assert len(results) == 5, f"Expected 5 results, got {len(results)}"
    for r in results:
        assert r["success"] is True
        assert "result" in r

    avg_time = elapsed / 5
    print(f"  PASS: 5 concurrent KG queries completed in {elapsed:.2f}s (avg {avg_time:.2f}s)")


def run_all():
    """Run all knowledge graph integration tests."""
    tests = [
        test_kg_service_endpoint,
        test_kg_service_blast_radius_structure,
        test_kg_status_endpoint,
        test_kg_service_unknown_name,
        test_kg_status_unknown_name,
        test_kg_service_response_format,
        test_kg_concurrent_load,
    ]

    passed = 0
    failed = 0
    errors = []

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            errors.append((test.__name__, str(e)))
            print(f"  FAIL: {test.__name__}: {e}")

    print(f"\n{'=' * 60}")
    print(f"Knowledge Graph Integration Tests: {passed} passed, {failed} failed")
    print(f"{'=' * 60}")

    if errors:
        print("\nFailed tests:")
        for name, err in errors:
            print(f"  - {name}: {err}")
        sys.exit(1)
    else:
        print("All tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    run_all()
