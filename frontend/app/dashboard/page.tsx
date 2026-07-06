"use client";

import { useSession, signIn } from "next-auth/react";
import useSWR from "swr";
import { RegistryTable } from "@/components/RegistryTable";
import { AnomalyPanel } from "@/components/AnomalyPanel";

/**
 * app/dashboard/page.tsx
 *
 * Control-plane overview:
 * - 4 KPI cards derived from GET /audit
 * - RegistryTable — polls GET /servers every 5s
 * - Charts — questions by purpose, access overview
 * - AnomalyPanel — 5 heuristics from GET /audit
 *
 * Auth: Bearer token from session.accessToken on all calls.
 * Jaeger links: trace_id → http://localhost:16686/trace/{trace_id}
 */

interface AuditEvent {
  who: string;
  what: string;
  when: string;
  outcome: string;
  purpose_of_access?: string;
  trace_id?: string;
  server_name?: string;
}

interface MCPServer {
  server_id: number;
  server_name: string;
  status: string;
}

const REGISTRY_API = "/api/registry";
const JAEGER_URL = process.env.NEXT_PUBLIC_JAEGER_URL || "http://localhost:16686";

const PURPOSE_COLORS: Record<string, string> = {
  deterioration_review: "bg-blue-500",
  medication_reconciliation: "bg-purple-500",
  discharge_planning: "bg-teal-500",
  care_coordination: "bg-amber-500",
  routine_review: "bg-gray-500",
};

function KpiCard({
  title,
  value,
  sub,
  icon,
  trend,
  color,
}: {
  title: string;
  value: string | number;
  sub?: string;
  icon: string;
  trend?: string;
  color: string;
}) {
  return (
    <div className="bg-[#111827] border border-[#1F2937] rounded-xl p-5">
      <div className="flex items-start justify-between mb-3">
        <div className={`w-10 h-10 rounded-lg ${color} flex items-center justify-center text-lg`}>
          {icon}
        </div>
        {trend && (
          <span
            className={`text-xs font-medium ${
              trend.startsWith("+") ? "text-green-400" : "text-red-400"
            }`}
          >
            {trend}
          </span>
        )}
      </div>
      <p className="text-2xl font-bold text-white">{value}</p>
      <p className="text-sm text-gray-500 mt-0.5">{title}</p>
      {sub && <p className="text-xs text-gray-600 mt-1">{sub}</p>}
    </div>
  );
}

function PurposeChart({ events }: { events: AuditEvent[] }) {
  const counts: Record<string, number> = {};
  events.forEach((e) => {
    const p = e.purpose_of_access || "other";
    counts[p] = (counts[p] || 0) + 1;
  });
  const total = events.length || 1;
  const sorted = Object.entries(counts).sort(([, a], [, b]) => b - a);

  return (
    <div className="bg-[#111827] border border-[#1F2937] rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-white">Questions by Purpose</h3>
        <span className="text-xs text-gray-500">Last 7 days</span>
      </div>
      {sorted.length === 0 ? (
        <p className="text-xs text-gray-600 text-center py-6">No data yet</p>
      ) : (
        <div className="space-y-2.5">
          {sorted.map(([purpose, count]) => {
            const pct = Math.round((count / total) * 100);
            const color = PURPOSE_COLORS[purpose] || "bg-gray-500";
            return (
              <div key={purpose}>
                <div className="flex items-center justify-between text-xs mb-1">
                  <div className="flex items-center gap-1.5">
                    <span className={`w-2 h-2 rounded-full ${color}`} />
                    <span className="text-gray-400">{purpose.replace(/_/g, " ")}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-gray-500">{count}</span>
                    <span className="text-gray-600">{pct}%</span>
                  </div>
                </div>
                <div className="w-full h-1.5 bg-[#1F2937] rounded-full overflow-hidden">
                  <div
                    className={`h-full ${color} rounded-full transition-all duration-500`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function AccessOverview({ events }: { events: AuditEvent[] }) {
  const last7days = Array.from({ length: 7 }, (_, i) => {
    const d = new Date();
    d.setDate(d.getDate() - (6 - i));
    return {
      label: d.toLocaleDateString("en", { weekday: "short", month: "numeric", day: "numeric" }),
      date: d.toISOString().slice(0, 10),
    };
  });

  const byDay: Record<string, { allowed: number; denied: number }> = {};
  events.forEach((e) => {
    const day = e.when.slice(0, 10);
    if (!byDay[day]) byDay[day] = { allowed: 0, denied: 0 };
    if (e.outcome === "403") byDay[day].denied++;
    else byDay[day].allowed++;
  });

  const maxVal = Math.max(...last7days.map((d) => (byDay[d.date]?.allowed || 0) + (byDay[d.date]?.denied || 0)), 1);

  return (
    <div className="bg-[#111827] border border-[#1F2937] rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-white">Access Overview</h3>
        <span className="text-xs text-gray-500">Last 7 days</span>
      </div>
      <div className="flex items-end gap-1 h-24">
        {last7days.map((d) => {
          const allowed = byDay[d.date]?.allowed || 0;
          const denied = byDay[d.date]?.denied || 0;
          const total = allowed + denied;
          const heightPct = (total / maxVal) * 100;
          return (
            <div key={d.date} className="flex-1 flex flex-col items-center justify-end gap-1 h-full" title={`${d.label}: ${allowed} allowed, ${denied} denied`}>
              <div className="w-full flex flex-col-reverse rounded-t overflow-hidden" style={{ height: `${Math.max(heightPct, 4)}%`, maxHeight: "80px", minHeight: "4px" }}>
                {denied > 0 && <div className="bg-red-500/70" style={{ height: `${(denied / Math.max(total, 1)) * 100}%` }} />}
                {allowed > 0 && <div className="bg-blue-500/70" style={{ height: `${(allowed / Math.max(total, 1)) * 100}%` }} />}
              </div>
            </div>
          );
        })}
      </div>
      <div className="flex justify-between text-xs text-gray-600 mt-1">
        {last7days.map((d, i) => i % 2 === 0 && <span key={d.date}>{d.label.split(" ")[0]}</span>)}
      </div>
      <div className="flex items-center gap-4 mt-3 text-xs">
        <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-blue-500" />Successful</div>
        <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-red-500" />Denied (403)</div>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const { data: session, status } = useSession();

  const { data: servers = [], error: serversError } = useSWR<MCPServer[]>(
    status === "authenticated" ? `${REGISTRY_API}/servers` : null,
    async (url: string) => {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`Registry servers: ${res.status}`);
      return res.json();
    },
    { refreshInterval: 5000 }
  );

  const { data: audit = [], error: auditError } = useSWR<AuditEvent[]>(
    status === "authenticated" ? `${REGISTRY_API}/audit?limit=500` : null,
    async (url: string) => {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`Registry audit: ${res.status}`);
      return res.json();
    },
    { refreshInterval: 30000 }
  );

  if (status === "loading") {
    return (
      <div className="min-h-screen bg-[#0A0F1E] flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!session) {
    return (
      <div className="min-h-screen bg-[#0A0F1E] flex items-center justify-center">
        <button onClick={() => signIn("keycloak")} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm">
          Sign in
        </button>
      </div>
    );
  }

  if (session.error === "RefreshAccessTokenError") {
    return (
      <div className="min-h-screen bg-[#0A0F1E] flex flex-col items-center justify-center gap-3">
        <p className="text-sm text-gray-400">Session expired — sign in again to load dashboard metrics.</p>
        <button onClick={() => signIn("keycloak")} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm">
          Sign in
        </button>
      </div>
    );
  }

  const now = Date.now();
  const last24h = audit.filter((e) => new Date(e.when).getTime() > now - 86400000);
  const phiTouches = last24h.length;
  const denials = last24h.filter((e) => e.outcome === "403").length;
  const activeServers = servers.filter((s) => s.status === "healthy").length;
  const purposes = last24h.reduce<Record<string, number>>((acc, e) => {
    const p = e.purpose_of_access || "other";
    acc[p] = (acc[p] || 0) + 1;
    return acc;
  }, {});
  const topPurpose = Object.entries(purposes).sort(([, a], [, b]) => b - a)[0];

  return (
    <div className="min-h-[calc(100vh-56px)] bg-[#0A0F1E]">
      <div className="mx-auto max-w-screen-xl px-4 py-6">
        {/* Page header */}
        <div className="mb-6">
          <h1 className="text-xl font-bold text-white">Dashboard</h1>
          <p className="text-sm text-gray-500">Control plane overview and platform analytics</p>
        </div>

        {/* KPI cards */}
        {(auditError || serversError) && (
          <div className="mb-4 px-4 py-3 rounded-lg border border-amber-500/30 bg-amber-500/10 text-sm text-amber-300">
            Could not load registry metrics
            {auditError ? ` (audit: ${auditError.message})` : ""}
            {serversError ? ` (servers: ${serversError.message})` : ""}
            . Sign out and sign back in if this persists.
          </div>
        )}
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
          <KpiCard
            title="Access Denials (403)"
            value={denials}
            sub="vs last 24 hours"
            icon="🚫"
            color="bg-red-600/20"
          />
          <KpiCard
            title="Questions by Purpose"
            value={last24h.length}
            sub={topPurpose ? `${topPurpose[0].replace(/_/g, " ")} (${Math.round((topPurpose[1] / Math.max(last24h.length, 1)) * 100)}%)` : "No data yet"}
            icon="💬"
            color="bg-purple-600/20"
          />
          <KpiCard
            title="Active MCP Servers"
            value={`${activeServers}/${servers.length}`}
            sub={activeServers === servers.length ? "All servers healthy" : `${servers.length - activeServers} degraded`}
            icon="🖥"
            color="bg-green-600/20"
          />
        </div>

        {/* Registry table */}
        <div className="bg-[#0D1120] border border-[#1F2937] rounded-xl p-5 mb-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold text-white">Registered MCP Servers</h2>
          </div>
          <RegistryTable />
        </div>

        {/* Charts row */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
          <PurposeChart events={audit} />
          <AccessOverview events={audit} />
        </div>

        {/* Anomaly panel */}
        <div className="bg-[#0D1120] border border-[#1F2937] rounded-xl p-5">
          <AnomalyPanel events={audit} />
        </div>
      </div>
    </div>
  );
}
