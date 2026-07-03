"use client";

import useSWR from "swr";
import { useState } from "react";

/**
 * components/RegistryTable.tsx
 *
 * Polls GET /servers every 5 seconds.
 * Columns: domain, status, port, scope, allowed_roles, kong_route, updated_at.
 * Row expand: fetches GET /servers/{id}/health for latency + error detail.
 */

interface MCPServer {
  server_id: number;
  server_name: string;
  domain: string;
  status: string;
  kong_route: string;
  port: number;
  scope?: string;
  allowed_roles: string[];
  updated_at: string;
}

interface HealthDetail {
  status: string;
  checked_at: string;
  latency_ms?: number;
  error_msg?: string;
}

const DOMAIN_COLORS: Record<string, string> = {
  vitals_trends: "text-blue-400",
  labs_diagnoses: "text-teal-400",
  medications_interactions: "text-purple-400",
  clinical_notes_search: "text-amber-400",
  radiology_reports: "text-orange-400",
};

const ROLE_LABELS: Record<string, { label: string; color: string }> = {
  "grp-physician": { label: "Physician", color: "bg-green-900/40 text-green-300" },
  "grp-clinical-viewer": { label: "Clinical Viewer", color: "bg-blue-900/40 text-blue-300" },
  "grp-case-manager": { label: "Case Manager", color: "bg-amber-900/40 text-amber-300" },
};

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  return `${Math.floor(m / 60)}h ago`;
}

function HealthBar({ pct }: { pct: number }) {
  const color = pct >= 99 ? "bg-green-500" : pct >= 95 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 bg-[#1F2937] rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-400">{pct}%</span>
    </div>
  );
}

export function RegistryTable() {
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [healthDetails, setHealthDetails] = useState<Record<number, HealthDetail>>({});
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());

  const { data: servers = [], isLoading, mutate, error } = useSWR<MCPServer[]>(
    "/api/registry/servers",
    async (url: string) => {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`${res.status}`);
      setLastRefresh(new Date());
      return res.json();
    },
    { refreshInterval: 5000 }
  );

  async function expandRow(server: MCPServer) {
    if (expandedId === server.server_id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(server.server_id);
    if (!healthDetails[server.server_id]) {
      try {
        const res = await fetch(`/api/registry/servers/${server.server_id}/health`);
        if (res.ok) {
          const data = await res.json();
          setHealthDetails((prev) => ({ ...prev, [server.server_id]: data }));
        }
      } catch {}
    }
  }

  if (isLoading) {
    return (
      <div className="space-y-2">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="h-12 bg-[#111827] rounded-lg animate-pulse" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <p className="text-sm text-amber-400">
        Could not load server registry ({error.message}). Sign out and sign back in.
      </p>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500">
            Live status from registry · Last updated {lastRefresh.toLocaleTimeString()}
          </span>
          <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
        </div>
        <button
          onClick={() => mutate()}
          className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors"
        >
          ↻ Refresh
        </button>
      </div>

      <div className="border border-[#1F2937] rounded-xl overflow-hidden">
        {/* Header */}
        <div className="grid grid-cols-[2fr_1fr_1fr_1fr_2fr_1fr_1fr] gap-3 px-4 py-2.5 bg-[#0D1625] border-b border-[#1F2937] text-xs font-medium text-gray-500">
          <span>Domain</span>
          <span>Status</span>
          <span>Health</span>
          <span>Port</span>
          <span>Kong Route</span>
          <span>Roles</span>
          <span>Updated</span>
        </div>

        {servers.map((s) => (
          <div key={s.server_id}>
            <button
              onClick={() => expandRow(s)}
              className="w-full grid grid-cols-[2fr_1fr_1fr_1fr_2fr_1fr_1fr] gap-3 px-4 py-3 border-b border-[#1F2937] hover:bg-[#111827] transition-colors text-left"
            >
              {/* Domain */}
              <div className="flex items-center gap-2">
                <span className={`font-mono text-sm font-medium ${DOMAIN_COLORS[s.domain] || "text-gray-300"}`}>
                  {s.domain}
                </span>
              </div>

              {/* Status */}
              <div className="flex items-center gap-1.5">
                <span
                  className={`w-2 h-2 rounded-full ${
                    s.status === "healthy"
                      ? "bg-green-400"
                      : s.status === "pending"
                      ? "bg-amber-400"
                      : "bg-red-400"
                  }`}
                />
                <span
                  className={`text-xs font-medium capitalize ${
                    s.status === "healthy"
                      ? "text-green-400"
                      : s.status === "pending"
                      ? "text-amber-400"
                      : "text-red-400"
                  }`}
                >
                  {s.status}
                </span>
              </div>

              {/* Health bar */}
              <div>
                <HealthBar pct={s.status === "healthy" ? 99 : 0} />
              </div>

              {/* Port */}
              <span className="font-mono text-sm text-gray-400">{s.port}</span>

              {/* Kong route */}
              <span className="font-mono text-xs text-gray-500 truncate">{s.kong_route}</span>

              {/* Roles */}
              <div className="flex flex-wrap gap-1">
                {s.allowed_roles.slice(0, 2).map((r) => {
                  const rl = ROLE_LABELS[r];
                  return rl ? (
                    <span key={r} className={`text-xs px-1.5 py-0.5 rounded ${rl.color}`}>
                      {rl.label.split(" ")[0]}
                    </span>
                  ) : null;
                })}
              </div>

              {/* Updated */}
              <span className="text-xs text-gray-600">{timeAgo(s.updated_at)}</span>
            </button>

            {/* Expanded health detail */}
            {expandedId === s.server_id && (
              <div className="px-4 py-3 bg-[#0D1625] border-b border-[#1F2937] text-xs">
                {healthDetails[s.server_id] ? (
                  <div className="flex items-center gap-6 text-gray-400">
                    <span>
                      Checked:{" "}
                      <span className="text-gray-300">
                        {new Date(healthDetails[s.server_id].checked_at).toLocaleTimeString()}
                      </span>
                    </span>
                    {healthDetails[s.server_id].latency_ms != null && (
                      <span>
                        Latency:{" "}
                        <span className="text-gray-300 font-mono">
                          {healthDetails[s.server_id].latency_ms}ms
                        </span>
                      </span>
                    )}
                    {healthDetails[s.server_id].error_msg && (
                      <span className="text-red-400">
                        Error: {healthDetails[s.server_id].error_msg}
                      </span>
                    )}
                    <span>
                      Scope:{" "}
                      <span className="font-mono text-gray-300">{s.scope || "—"}</span>
                    </span>
                  </div>
                ) : (
                  <span className="text-gray-600">Loading health detail…</span>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
