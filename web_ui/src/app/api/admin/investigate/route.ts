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

    // Forward to sre-agent /investigate endpoint
    const upstreamUrl = `${AGENT_SERVICE_URL}/investigate`;
    const upstreamRes = await fetch(upstreamUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-SolidAI SRE-Team-Token": token,
        Authorization: `Bearer ${token}`,
        "X-Trigger-Source": "incident-dashboard",
      },
      body: JSON.stringify({
        prompt,
        thread_id: thread_id || `incident-${serviceName}-${Date.now()}`,
        alert,
      }),
    });

    if (!upstreamRes.ok) {
      const errorText = await upstreamRes.text();
      return NextResponse.json(
        { error: errorText || `Upstream error: ${upstreamRes.status}` },
        { status: upstreamRes.status }
      );
    }

    // Return the thread ID so the client can connect to the SSE stream
    const responseBody = await upstreamRes.json().catch(() => ({}));

    return NextResponse.json({
      status: "investigation_started",
      thread_id: thread_id || `incident-${serviceName}-${Date.now()}`,
      serviceName,
      ...responseBody,
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
