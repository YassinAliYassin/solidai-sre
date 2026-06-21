import { NextRequest, NextResponse } from "next/server";

const HEALTH_MONITOR_URL =
  process.env.HEALTH_MONITOR_URL || "http://localhost:8090";

/**
 * GET /api/status/badge.json
 * Returns a JSON object suitable for shields.io-style badge consumption.
 * https://shields.io/endpoint
 */
export async function GET(req: NextRequest) {
  try {
    const res = await fetch(`${HEALTH_MONITOR_URL}/api/health-summary`, {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });

    if (!res.ok) {
      return NextResponse.json(
        {
          schemaVersion: 1,
          label: "status",
          message: "error",
          color: "red",
          isError: true,
        },
        {
          headers: {
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Access-Control-Allow-Origin": "*",
          },
        }
      );
    }

    const data = await res.json();
    const status = data.status || "unknown";
    const services = data.services || [];

    // Count internal services only
    const internalServices = services.filter(
      (s: any) =>
        !s.name.toLowerCase().includes("solid") &&
        !s.name.toLowerCase().includes("fresh people")
    );

    const internalDown = internalServices.filter(
      (s: any) => s.status === "down"
    ).length;
    const internalDegraded = internalServices.filter(
      (s: any) => s.status === "degraded"
    ).length;

    let message: string;
    let color: string;

    if (internalDown > 0) {
      message = `${internalDown} down`;
      color = "red";
    } else if (internalDegraded > 0) {
      message = `${internalDegraded} degraded`;
      color = "orange";
    } else {
      message = "operational";
      color = "brightgreen";
    }

    return NextResponse.json(
      {
        schemaVersion: 1,
        label: "status",
        message,
        color,
      },
      {
        headers: {
          "Cache-Control": "no-store, no-cache, must-revalidate",
          "Access-Control-Allow-Origin": "*",
        },
      }
    );
  } catch (err: any) {
    return NextResponse.json(
      {
        schemaVersion: 1,
        label: "status",
        message: "error",
        color: "red",
        isError: true,
      },
      {
        headers: {
          "Cache-Control": "no-store, no-cache, must-revalidate",
          "Access-Control-Allow-Origin": "*",
        },
      }
    );
  }
}
