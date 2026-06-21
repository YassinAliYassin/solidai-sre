import { NextRequest, NextResponse } from "next/server";
import { requireAdminSession } from "@/app/api/_utils/upstream";

function getSreAgentBaseUrl() {
  const baseUrl = process.env.SRE_AGENT_URL || "http://sre-agent:8000";
  return baseUrl;
}

// GET /api/admin/memory-health - Proxy to sre-agent memory health endpoint
export async function GET(req: NextRequest) {
  try {
    await requireAdminSession(req);

    const baseUrl = getSreAgentBaseUrl();
    const res = await fetch(`${baseUrl}/memory/health`, {
      method: "GET",
      cache: "no-store",
      signal: AbortSignal.timeout(15000),
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err: any) {
    const status = err?.status || 502;
    return NextResponse.json(
      {
        error: "Failed to fetch memory health",
        details: err?.message || String(err),
      },
      { status }
    );
  }
}
