import { NextResponse } from "next/server";

const AGENT_URL = process.env.NEXT_PUBLIC_AGENT_URL || "http://localhost:8500";

export async function GET() {
  try {
    const res = await fetch(`${AGENT_URL}/health`);
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ status: "error" }, { status: 503 });
  }
}
