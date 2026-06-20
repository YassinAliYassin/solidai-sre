#!/usr/bin/env python3
"""
HTTP integration tests for sre-agent auxiliary endpoints.

Tests the live running server (port 8001) for:
1. /status — system health of all dependent services
2. /memory/stats — memory system statistics
3. /memory/episodes — list stored episodes
4. /memory/search — search similar past investigations
5. /memory/strategies — get investigation strategies
6. /memory/search with filters — service_name and alert_type
7. Concurrent load — 5 parallel investigations all complete successfully

Requires: sre-agent running in Docker (port 8001)
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
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _post(path: str, data: dict) -> dict:
    """POST a JSON endpoint and return parsed dict."""
    req = urllib.request.Request(
        f"{AGENT_URL}{path}",
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _parse_sse(raw: str) -> list[dict]:
    """Parse raw SSE text into list of event dicts."""
    events = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            payload = line[6:]
            try:
                events.append(json.loads(payload))
            except json.JSONDecodeError:
                pass
    return events


def test_status_endpoint() -> bool:
    """Test 1: /status returns healthy with all services."""
    print("\nTest 1: /status Endpoint")
    try:
        data = _get("/status")

        # Validate structure
        if data.get("status") != "healthy":
            print(f"  ❌ Status not healthy: {data.get('status')}")
            return False

        if data.get("mode") != "langgraph":
            print(f"  ❌ Mode not langgraph: {data.get('mode')}")
            return False

        services = data.get("services", {})
        if not services:
            print("  ❌ No services in status")
            return False

        # Each service should have a status field
        for name, svc in services.items():
            if "status" not in svc:
                print(f"  ❌ Service {name} missing status field")
                return False
            print(f"  📡 {name}: {svc['status']}", end="")
            if "latency_ms" in svc:
                print(f" ({svc['latency_ms']}ms)")
            else:
                print()

        print(f"  ✅ /status healthy, {len(services)} services checked")
        return True

    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False


def test_memory_stats() -> bool:
    """Test 2: /memory/stats returns episode statistics."""
    print("\nTest 2: /memory/stats Endpoint")
    try:
        data = _get("/memory/stats")

        # Validate structure
        if "total_episodes" not in data:
            print(f"  ❌ Missing total_episodes field")
            return False

        total = data["total_episodes"]
        resolved = data.get("resolved_episodes", 0)
        unresolved = data.get("unresolved_episodes", 0)

        # Consistency check: resolved + unresolved should equal total
        if resolved + unresolved != total:
            print(f"  ⚠️  Inconsistent counts: {resolved}+{unresolved} != {total}")

        print(f"  📊 Total: {total}, Resolved: {resolved}, Unresolved: {unresolved}")
        print(f"  ✅ /memory/stats valid (total_episodes={total})")
        return True

    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False


def test_memory_episodes() -> bool:
    """Test 3: /memory/episodes returns list of episodes."""
    print("\nTest 3: /memory/episodes Endpoint")
    try:
        data = _get("/memory/episodes")

        if "episodes" not in data:
            print(f"  ❌ Missing 'episodes' field")
            return False

        episodes = data["episodes"]
        if not isinstance(episodes, list):
            print(f"  ❌ 'episodes' is not a list")
            return False

        print(f"  📋 {len(episodes)} episodes returned")

        # Validate at least one episode has expected fields
        if episodes:
            ep = episodes[0]
            fields = {"id", "alert_description", "severity", "created_at"}
            missing = fields - set(ep.keys())
            if missing:
                print(f"  ⚠️  Episode missing fields: {missing}")
            else:
                print(f"  📝 First episode: {ep.get('alert_description', '')[:60]}")

        print(f"  ✅ /memory/episodes valid ({len(episodes)} episodes)")
        return True

    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False


def test_memory_search() -> bool:
    """Test 4: /memory/search returns relevant results."""
    print("\nTest 4: /memory/search Endpoint")
    try:
        data = _post("/memory/search", {"prompt": "database connection pool"})

        if "results" not in data:
            print(f"  ❌ Missing 'results' field")
            return False

        results = data["results"]
        if not isinstance(results, list):
            print(f"  ❌ 'results' is not a list")
            return False

        print(f"  🔍 {len(results)} results for 'database connection pool'")

        # Validate result structure
        if results:
            r = results[0]
            required = {"id", "alert_description", "similarity_score"}
            missing = required - set(r.keys())
            if missing:
                print(f"  ⚠️  Result missing fields: {missing}")
            else:
                print(f"  📝 Top result: {r.get('alert_description', '')[:60]}")
                print(f"  📊 Similarity: {r.get('similarity_score', 0)}")

        print(f"  ✅ /memory/search valid ({len(results)} results)")
        return True

    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False


def test_memory_search_with_filters() -> bool:
    """Test 5: /memory/search with service_name and alert_type filters."""
    print("\nTest 5: /memory/search with Filters")
    try:
        data = _post("/memory/search", {
            "prompt": "latency",
            "service_name": "api-gateway",
            "alert_type": "performance",
        })

        if "results" not in data:
            print(f"  ❌ Missing 'results' field")
            return False

        results = data["results"]
        print(f"  🔍 {len(results)} results with filters (service=api-gateway, type=performance)")
        print(f"  ✅ /memory/search with filters valid")
        return True

    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False


def test_memory_strategies() -> bool:
    """Test 6: /memory/strategies returns strategy list."""
    print("\nTest 6: /memory/strategies Endpoint")
    try:
        data = _get("/memory/strategies")

        if "strategies" not in data:
            print(f"  ❌ Missing 'strategies' field")
            return False

        strategies = data["strategies"]
        if not isinstance(strategies, list):
            print(f"  ❌ 'strategies' is not a list")
            return False

        print(f"  📋 {len(strategies)} strategies returned")
        print(f"  ✅ /memory/strategies valid")
        return True

    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False


def _run_single_investigation(idx: int) -> tuple:
    """Run a single investigation and return (idx, success, thread_id, duration)."""
    prompt = f"Integration test load investigation #{idx} — checking service health"
    req = urllib.request.Request(
        f"{AGENT_URL}/investigate",
        data=json.dumps({"prompt": prompt}).encode(),
        headers={"Content-Type": "application/json"},
    )
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            events = _parse_sse(raw)
            duration = time.time() - start

            if not events:
                return (idx, False, None, duration)

            thread_id = events[0].get("thread_id", "")
            result_events = [e for e in events if e.get("type") == "result"]
            success = len(result_events) > 0
            return (idx, success, thread_id, duration)
    except Exception as e:
        duration = time.time() - start
        return (idx, False, None, duration)


def test_concurrent_load() -> bool:
    """Test 7: 5 parallel investigations all complete successfully."""
    print("\nTest 7: Concurrent Load (5 Parallel Investigations)")
    start = time.time()

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_run_single_investigation, i) for i in range(5)]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    total_duration = time.time() - start
    results.sort(key=lambda x: x[0])

    all_ok = True
    success_count = 0
    thread_ids = set()

    for idx, success, thread_id, duration in results:
        status = "✅" if success else "❌"
        print(f"  {status} Investigation {idx}: {duration:.1f}s, thread={thread_id}")
        if success:
            success_count += 1
            thread_ids.add(thread_id)
        else:
            all_ok = False

    # Check all thread IDs are unique
    if len(thread_ids) != success_count:
        print(f"  ⚠️  Thread ID collision detected: {len(thread_ids)} unique from {success_count} successful")
        all_ok = False

    print(f"\n  📊 {success_count}/5 succeeded in {total_duration:.1f}s (parallel)")
    print(f"  ⏱️  Avg duration: {sum(r[3] for r in results)/len(results):.1f}s")

    if all_ok:
        print(f"  ✅ All 5 concurrent investigations succeeded with unique threads")
    else:
        print(f"  ❌ Some investigations failed")

    return all_ok


def main():
    print("=" * 60)
    print("SolidAI SRE — Auxiliary Endpoints Integration Tests")
    print(f"Target: {AGENT_URL}")
    print("=" * 60)

    # Quick health check first
    try:
        req = urllib.request.Request(f"{AGENT_URL}/health")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            print(f"\n🟢 Agent healthy (mode={data.get('mode')}, sessions={data.get('active_sessions')})")
    except Exception as e:
        print(f"\n❌ Agent not reachable: {e}")
        sys.exit(1)

    results = {
        "/status": test_status_endpoint(),
        "/memory/stats": test_memory_stats(),
        "/memory/episodes": test_memory_episodes(),
        "/memory/search": test_memory_search(),
        "/memory/search+filters": test_memory_search_with_filters(),
        "/memory/strategies": test_memory_strategies(),
        "Concurrent Load (5x)": test_concurrent_load(),
    }

    print("\n" + "=" * 60)
    print("Results:")
    all_pass = True
    for name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}  {name}")
        if not passed:
            all_pass = False

    print("=" * 60)
    if all_pass:
        print("🎉 All auxiliary endpoint tests PASSED!")
        sys.exit(0)
    else:
        print("💥 Some tests FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
