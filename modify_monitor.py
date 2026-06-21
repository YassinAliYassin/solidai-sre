import sys
import os

def insert_after(text, target, insert_block):
    """Insert insert_block after the first occurrence of target in text."""
    idx = text.find(target)
    if idx == -1:
        raise ValueError(f"Target not found: {target}")
    # Insert after the target string
    return text[:idx + len(target)] + insert_block + text[idx + len(target):]

def main():
    filepath = "/home/yassin/solidai-sre/health-monitor/monitor.py"
    with open(filepath, "r") as f:
        content = f.read()

    # 1. Insert get_incidents function after get_error_rate function.
    # Find the end of get_error_rate function (look for the closing brace at its indentation level).
    # We'll insert after the line that ends with "    }" and then a blank line? Actually we saw the function ends at line 487.
    # Let's just insert after the specific pattern: "    }\n\n"
    # We'll search for the end of get_error_rate: look for "\n    }\n\n" (two newlines after the closing brace)
    # But to be safe, we'll insert after the line that is exactly "    }" followed by newline and then maybe blank line.
    # We'll use a marker: after the closing brace of get_error_rate and the blank line after it.
    # Actually we can insert after the line: "    }\n\n" (the blank line after the function).
    # Let's find the index of "    }\n\n" after the get_error_rate function.
    # We'll search for "    }\n\n" starting from the end of the get_error_rate definition.
    # Simpler: insert after the string "    }\n\n" that appears after the error rate function.
    # We'll locate the get_error_rate function by its definition.
    target1 = "def get_error_rate(history: dict, service_name: str, window_hours: int = None) -> dict:"
    # Find the end of the function by scanning for the return statement and then the closing brace.
    # Instead, we'll insert after the line that is exactly "    }\n\n" that comes after the error rate function.
    # We'll just insert after the following known snippet: "    }\n\n"
    # But there are many such snippets. We'll use a more unique marker: after the error rate function's closing brace and the blank line before the next function.
    # Let's look at the original lines around that area from memory:
    # ... 
    #    }
    #
    # def check_latency_degradation(history: dict, service_name: str, threshold_ms: int = None) -> dict:
    # So pattern: "    }\n\n\ndef"
    # We'll insert between the "    }\n\n" and the "def".
    # We'll replace "    }\n\n\ndef" with "    }\n\n" + insert_block + "\n\ndef"
    marker = "    }\n\n\ndef"
    insert_block1 = '''def get_incidents(history: dict, window_hours: int = 24) -> list:
    """
    Detect incidents (periods of down/degraded status) from service history.
    Returns a list of incident objects sorted by start time descending.
    Each incident: {
        service_name: str,
        status: str,  # worst status during incident ('down' or 'degraded')
        start_time: str,  # ISO timestamp
        end_time: str | None,  # ISO timestamp or None if ongoing
        duration_seconds: float | None,  # None if ongoing
    }
    """
    incidents = []
    cutoff = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(hours=window_hours)
    ).isoformat()

    for name, entries in history.items():
        if not entries:
            continue
        # Ensure entries are sorted by timestamp ascending
        sorted_entries = sorted(entries, key=lambda e: e["timestamp"])
        # Filter entries within window
        windowed = [e for e in sorted_entries if e["timestamp"] >= cutoff]
        if not windowed:
            continue

        incident_start = None
        incident_statuses = []  # collect statuses during incident to determine worst

        for entry in windowed:
            status = entry["status"]
            is_non_healthy = status in ("down", "degraded")
            ts = entry["timestamp"]

            if is_non_healthy and incident_start is None:
                # Start new incident
                incident_start = ts
                incident_statuses = [status]
            elif not is_non_healthy and incident_start is not None:
                # End incident
                incident_end = ts
                # Determine worst status: down > degraded
                worst_status = "down" if "down" in incident_statuses else "degraded"
                duration = (
                    datetime.datetime.fromisoformat(incident_end)
                    - datetime.datetime.fromisoformat(incident_start)
                ).total_seconds()
                incidents.append(
                    {
                        "service_name": name,
                        "status": worst_status,
                        "start_time": incident_start,
                        "end_time": incident_end,
                        "duration_seconds": duration,
                    }
                )
                incident_start = None
                incident_statuses = []
            elif is_non_healthy and incident_start is not None:
                # Continue incident
                incident_statuses.append(status)

        # If incident still open at end of windowed entries
        if incident_start is not None:
            # Incident ongoing at the end of the window
            incident_end = None  # ongoing
            worst_status = "down" if "down" in incident_statuses else "degraded"
            incidents.append(
                {
                    "service_name": name,
                    "status": worst_status,
                    "start_time": incident_start,
                    "end_time": None,
                    "duration_seconds": None,
                }
            )

    # Sort by start_time descending (most recent first)
    incidents.sort(
        key=lambda i: i["start_time"],
        reverse=True,
    )
    return incidents'''

    # Replace the first occurrence of marker
    if marker in content:
        content = content.replace(marker, f"    }}\n\n{insert_block1}\n\n(def", 1)
    else:
        # Fallback: try to insert after the get_error_rate function by finding its end.
        # We'll just append the function before the next function definition.
        # Find the line where check_latency_degradation starts.
        lines = content.splitlines(keepends=True)
        # Find index of line that starts with "def check_latency_degradation"
        for i, line in enumerate(lines):
            if line.strip().startswith("def check_latency_degradation"):
                # Insert before this line
                lines.insert(i, insert_block1 + "\n\n")
                content = ''.join(lines)
                break
        else:
            raise RuntimeError("Could not find place to insert get_incidents function")

    # 2. Insert the incidents API endpoint after get_model_health endpoint.
    # Find the line after the get_model_health function.
    # Look for the pattern after the get_model_health function: after the closing brace and blank line before _run_api_server.
    # We'll insert after the line: "    return _JSONResponse(_model_health_cache)\n\n"
    # Actually the get_model_health function ends at line 1236? Let's find.
    # We'll replace "    return _JSONResponse(_model_health_cache)\n\n\nasync def _run_api_server():" with 
    # "    return _JSONResponse(_model_health_cache)\n\n" + endpoint_block + "\n\nasync def _run_api_server():"
    endpoint_block = '''@_api_app.get("/api/incidents")
async def get_incidents_endpoint(window_hours: int = 24):
    """Get incident timeline for all services.

    Returns a list of incident objects (downtime/degradation periods) for all
    monitored services within the specified time window (default 24 hours).
    Each incident includes service name, status, start/end times, and duration.
    """
    history = _load_history()
    incidents = get_incidents(history, window_hours)
    return _JSONResponse(incidents)'''

    marker2 = "    return _JSONResponse(_model_health_cache)\n\n\nasync def _run_api_server():"
    if marker2 in content:
        content = content.replace(marker2, f"    return _JSONResponse(_model_health_cache)\n\n{endpoint_block}\n\n\nasync def _run_api_server():", 1)
    else:
        # Fallback: insert before _run_api_server
        lines = content.splitlines(keepends=True)
        for i, line in enumerate(lines):
            if line.strip().startswith("async def _run_api_server():"):
                lines.insert(i, endpoint_block + "\n\n")
                content = ''.join(lines)
                break
        else:
            raise RuntimeError("Could not find place to insert incidents endpoint")

    with open(filepath, "w") as f:
        f.write(content)

if __name__ == "__main__":
    main()