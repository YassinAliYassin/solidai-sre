import { NextRequest, NextResponse } from "next/server";
import { requireAdminSession } from "@/app/api/_utils/upstream";

const AGENT_SERVICE_URL =
  process.env.AGENT_SERVICE_URL ||
  process.env.ORCHESTRATOR_URL ||
  "http://localhost:8000";

/**
 * POST /api/admin/investigate
 *
 * Trigger an SRE agent investigation for a detected health incident.
 * Accepts incident details and constructs an investigation prompt.
 *
 * Fire-and-forget: the sre-agent uses SSE streaming, so we kick off the
 * request and return immediately with the thread_id. The agent run is
 * recorded server-side and appears on the Agent Runs page.
 */
export async function POST(req: NextRequest) {
  try {
    await requireAdminSession(req);

    const token = req.cookies.get("solidai-sre_session_token")?.value;
    if (!token) {
      return NextResponse.json({ error: "Unauthenticated" }, { status: 401 });
    }

    const body = await req.json();
    const {
      serviceName,
      incidentType,
      timestamp,
      error,
      latency_ms,
      thread_id,
    } = body;

    if (!serviceName) {
      return NextResponse.json(
        { error: "Missing serviceName" },
        { status: 400 }
      );
    }

    const resolvedThreadId =
      thread_id || `incident-${serviceName}-${Date.now()}`;

    // Construct an investigation prompt from the incident details
    const alert: Record<string, string> = {
      name: incidentType === "down" ? "ServiceDown" : "ServiceDegraded",
      service: serviceName,
      severity: incidentType === "down" ? "critical" : "high",
      timestamp: timestamp || new Date().toISOString(),
      description:
        error ||
        `${serviceName} is ${incidentType}${
          latency_ms ? ` (${latency_ms}ms latency)` : ""
        }`,
    };

    const prompt = `Investigate this production alert:

Service: ${serviceName}
Status: ${incidentType}
Severity: ${alert.severity}
Time: ${alert.timestamp}
${error ? `Error: ${error}` : ""}
${latency_ms ? `Latency: ${latency_ms}ms` : ""}

Please investigate the root cause, check related services in the knowledge graph, and provide a structured report with remediation steps.`;

    // Fire-and-forget to sre-agent SSE endpoint.
    // We do NOT await the response body because the agent streams via SSE
    // and the connection stays open until the investigation completes.
    // The agent run is recorded server-side and visible on Agent Runs page.
    const upstreamUrl = `${AGENT_SERVICE_URL}/investigate`;
    fetch(upstreamUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-SolidAI SRE-Team-Token": token,
        Authorization: `Bearer ${token}`,
        "X-Trigger-Source": "incident-dashboard",
      },
      body: JSON.stringify({
        prompt,
        thread_id: resolvedThreadId,
        alert,
      }),
    }).catch((fetchErr) => {
      // Log but don't fail — the investigation may still start
      console.error("[investigate] Failed to reach sre-agent:", fetchErr);
    });

    // Return immediately with the thread ID
    return NextResponse.json({
      status: "investigation_started",
      thread_id: resolvedThreadId,
      serviceName,
    });
  } catch (err: any) {
    const status = err?.status || 502;
    return NextResponse.json(
      {
        error: "Failed to start investigation",
        details: err?.message || String(err),
      },
      { status }
    );
  }
}
