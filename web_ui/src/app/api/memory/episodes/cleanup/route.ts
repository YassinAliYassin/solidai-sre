import { NextRequest, NextResponse } from "next/server";

const AGENT_URL = process.env.AGENT_SERVICE_URL || 'http://localhost:8000';

export async function POST(req: NextRequest) {
  try {
    const body = await req.json().catch(() => ({}));
    const { older_than_hours, alert_type, dry_run } = body;

    const res = await fetch(`${AGENT_URL}/memory/episodes/cleanup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        older_than_hours: older_than_hours ?? 24,
        alert_type: alert_type ?? "health_check",
        dry_run: dry_run ?? false,
      }),
    });

    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (e: any) {
    return NextResponse.json(
      { error: "Failed to reach sre-agent", details: e?.message || String(e) },
      { status: 502 }
    );
  }
}
