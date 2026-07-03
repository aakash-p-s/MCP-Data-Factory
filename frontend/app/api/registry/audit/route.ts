import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { NextResponse } from "next/server";

const REGISTRY_URL = process.env.NEXT_PUBLIC_REGISTRY_URL || "http://localhost:8600";

export async function GET(request: Request) {
  const session = await getServerSession(authOptions);
  if (!session?.accessToken) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const { searchParams } = new URL(request.url);
  const limit = searchParams.get("limit") || "500";
  const res = await fetch(`${REGISTRY_URL}/audit?limit=${limit}`, {
    headers: { Authorization: `Bearer ${session.accessToken}` },
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
