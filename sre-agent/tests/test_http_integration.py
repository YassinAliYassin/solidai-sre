#!/usr/bin/env python3
"""
End-to-end HTTP integration test for the /investigate endpoint.

Hits the actual running sre-agent server (port 8001) and validates:
1. Real alert payload (JSON) produces valid SSE stream
2. Plain text alert produces valid SSE stream
3. Follow-up investigation (same thread_id) works
4. All events are well-formed with required fields
5. Result event contains investigation output
6. Thread IDs are unique across separate investigations

Requires: sre-agent running in Docker (port 8001)
"""

import json
import sys
import time
import urllib.request
import urllib.error

AGENT_URL = "http://localhost:8001"


def _parse_sse(raw: str) -> list[dict]:
    """Parse raw SSE text into list of event dicts."""
    events = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            payload = line[6:]
            try:
                events.append(json.loads(payload))
            except json.JSONDecodeError as e:
                print(f"  ⚠️  Non-JSON SSE event: {payload[:80]}... ({e})")
    return events


def _validate_events(events: list[dict], context: str) -> bool:
    """Validate that all events have required fields."""
    if not events:
        print(f"  ❌ {context}: No events received")
        return False

    required = {"type", "data", "thread_id", "timestamp"}
    for i, ev in enumerate(events):
        missing = required - set(ev.keys())
        if missing:
            print(f"  ❌ {context}: Event {i} missing fields: {missing}")
            return False
    print(f"  ✅ {context}: {len(events)} events, all well-formed")
    return True


def test_health() -> bool:
    """Verify agent is reachable and healthy."""
    print("Test 0: Health Check")
    try:
        req = urllib.request.Request(f"{AGENT_URL}/health")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            if data.get("status") == "healthy":
                print(f"  ✅ Agent healthy (mode={data.get('mode')})")
                return True
            print(f"  ❌ Unhealthy: {data}")
            return False
    except Exception as e:
        print(f"  ❌ Cannot reach agent: {e}")
        return False


def test_investigate_json_alert() -> bool:
    """Test 1: POST a real JSON alert payload."""
    print("\nTest 1: JSON Alert Payload")
    alert = json.dumps({
        "name": "HighLatencyAPI",
        "service": "api-gateway",
        "severity": "warning",
        "description": "API response times exceeding 5s p95 on /api/v2/users endpoint",
        "source": "prometheus",
        "timestamp": "2026-06-20T10:30:00Z",
    })

    req = urllib.request.Request(
        f"{AGENT_URL}/investigate",
        data=json.dumps({"prompt": alert}).encode(),
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            if resp.status != 200:
                print(f"  ❌ HTTP {resp.status}")
                return False

            content_type = resp.headers.get("Content-Type", "")
            if "text/event-stream" not in content_type:
                print(f"  ❌ Wrong content-type: {content_type}")
                return False

            raw = resp.read().decode("utf-8", errors="replace")
            events = _parse_sse(raw)

            if not _validate_events(events, "JSON alert"):
                return False

            # Check thread_id consistency
            thread_ids = {e["thread_id"] for e in events}
            if len(thread_ids) != 1:
                print(f"  ❌ Multiple thread IDs: {thread_ids}")
                return False

            # Check result event exists
            result_events = [e for e in events if e["type"] == "result"]
            if not result_events:
                types = [e["type"] for e in events]
                print(f"  ❌ No result event. Types seen: {types}")
                return False

            result_text = result_events[0]["data"].get("text", "")
            if not result_text:
                print("  ❌ Result text is empty")
                return False

            print(f"  ✅ Thread: {thread_ids.pop()}")
            print(f"  ✅ Result: {result_text[:120]}...")
            return True

    except urllib.error.URLError as e:
        print(f"  ❌ Request failed: {e}")
        return False
    except Exception as e:
        print(f"  ❌ Unexpected error: {e}")
        return False


def test_investigate_plain_text() -> bool:
    """Test 2: POST a plain text alert (wrapped as alert by server)."""
    print("\nTest 2: Plain Text Alert")
    prompt = "The payment service is returning 503 errors intermittently since 14:00 UTC"

    req = urllib.request.Request(
        f"{AGENT_URL}/investigate",
        data=json.dumps({"prompt": prompt}).encode(),
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            events = _parse_sse(raw)

            if not _validate_events(events, "Plain text"):
                return False

            result_events = [e for e in events if e["type"] == "result"]
            if not result_events:
                print("  ❌ No result event")
                return False

            print(f"  ✅ Investigation completed with result")
            return True

    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False


def test_follow_up_thread() -> bool:
    """Test 3: Start an investigation, then continue with same thread_id."""
    print("\nTest 3: Follow-up Investigation (Thread Continuity)")

    # Start new investigation
    prompt = "Database connection pool exhaustion detected on postgres-primary"
    req = urllib.request.Request(
        f"{AGENT_URL}/investigate",
        data=json.dumps({"prompt": prompt}).encode(),
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            events = _parse_sse(raw)

            if not events:
                print("  ❌ No events from initial investigation")
                return False

            thread_id = events[0]["thread_id"]
            print(f"  📝 Thread ID: {thread_id}")

        # Wait briefly between requests
        time.sleep(1)

        # Send follow-up
        follow_up = "What connection pool settings are currently configured?"
        req2 = urllib.request.Request(
            f"{AGENT_URL}/investigate",
            data=json.dumps({"prompt": follow_up, "thread_id": thread_id}).encode(),
            headers={"Content-Type": "application/json"},
        )

        with urllib.request.urlopen(req2, timeout=120) as resp:
            raw2 = resp.read().decode("utf-8", errors="replace")
            events2 = _parse_sse(raw2)

            if not events2:
                print("  ❌ No events from follow-up")
                return False

            thread_ids2 = {e["thread_id"] for e in events2}
            if thread_ids2 != {thread_id}:
                print(f"  ❌ Follow-up used different thread: {thread_ids2}")
                return False

            result2 = [e for e in events2 if e["type"] == "result"]
            if not result2:
                print("  ❌ No result from follow-up")
                return False

            print(f"  ✅ Follow-up on same thread succeeded")
            return True

    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False


def test_concurrent_unique_threads() -> bool:
    """Test 4: Two separate investigations get unique thread IDs."""
    print("\nTest 4: Concurrent Investigations Get Unique Threads")

    results = []
    for i in range(2):
        prompt = f"Service health check for service-{i}"
        req = urllib.request.Request(
            f"{AGENT_URL}/investigate",
            data=json.dumps({"prompt": prompt}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                events = _parse_sse(raw)
                if events:
                    results.append(events[0]["thread_id"])
                else:
                    results.append(None)
        except Exception as e:
            print(f"  ❌ Investigation {i} failed: {e}")
            results.append(None)

    if None in results:
        print(f"  ❌ Some investigations failed: {results}")
        return False

    if len(set(results)) != 2:
        print(f"  ❌ Thread IDs not unique: {results}")
        return False

    print(f"  ✅ Unique threads: {results}")
    return True


def main():
    print("=" * 60)
    print("SolidAI SRE — /investigate HTTP Integration Tests")
    print(f"Target: {AGENT_URL}")
    print("=" * 60)

    if not test_health():
        print("\n❌ Agent not reachable. Aborting.")
        sys.exit(1)

    results = {
        "JSON Alert": test_investigate_json_alert(),
        "Plain Text": test_investigate_plain_text(),
        "Follow-up Thread": test_follow_up_thread(),
        "Concurrent Unique": test_concurrent_unique_threads(),
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
        print("🎉 All integration tests PASSED!")
        sys.exit(0)
    else:
        print("💥 Some tests FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
