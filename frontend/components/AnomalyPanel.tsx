"use client";

import useSWR from "swr";

/**
 * components/AnomalyPanel.tsx
 *
 * Computes 5 anomaly heuristics client-side from GET /audit.
 * All detection logic is purely a client-side computation over the audit array —
 * no new backend endpoint required.
 *
 * Heuristics (from PERSON_B_FRONTEND.md):
 * 1. Denial spike     — > 5 403s in the last hour
 * 2. Off-hours access — events between 22:00–06:00
 * 3. Purpose mismatch — e.g. medication_reconciliation querying vitals tools
 * 4. Repeat denials   — same user with 3+ consecutive 403s
 * 5. Cross-role probe — one user hitting multiple denied servers
 */

interface AuditEvent {
  who: string;
  what: string;
  when: string;
  outcome: string;
  reason?: string;
  purpose_of_access?: string;
  trace_id?: string;
  server_name?: string;
}

interface Anomaly {
  id: string;
  severity: "high" | "medium" | "low";
  type: string;
  description: string;
  user?: string;
  time?: string;
  traceId?: string;
}

const SEVERITY_STYLES = {
  high: "bg-red-500/20 text-red-400 border-red-500/30",
  medium: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  low: "bg-blue-500/20 text-blue-400 border-blue-500/30",
};

const SEVERITY_DOT = {
  high: "bg-red-500",
  medium: "bg-amber-500",
  low: "bg-blue-500",
};

const PURPOSE_MISMATCH: Record<string, string[]> = {
  medication_reconciliation: ["get_vitals_trend", "compute_news2_score", "list_abnormal_vitals"],
  deterioration_review: ["get_active_medications", "check_drug_interactions"],
  discharge_planning: ["semantic_search_notes"],
};

function detectAnomalies(events: AuditEvent[]): Anomaly[] {
  const anomalies: Anomaly[] = [];
  const now = Date.now();
  const oneHourAgo = now - 3600000;

  // 1. Denial spike
  const recentDenials = events.filter(
    (e) => e.outcome === "403" && new Date(e.when).getTime() > oneHourAgo
  );
  if (recentDenials.length > 5) {
    anomalies.push({
      id: "denial-spike",
      severity: "high",
      type: "Denial Spike",
      description: `${recentDenials.length} denials in the last hour (threshold: 5)`,
      user: recentDenials[0]?.who?.slice(0, 8) + "…",
      time: new Date(recentDenials[0]?.when).toLocaleTimeString(),
      traceId: recentDenials[0]?.trace_id,
    });
  }

  // 2. Off-hours access
  const offHours = events.filter((e) => {
    const h = new Date(e.when).getHours();
    return h >= 22 || h < 6;
  });
  if (offHours.length > 0) {
    anomalies.push({
      id: "off-hours",
      severity: "medium",
      type: "Off-hours Access",
      description: `${offHours.length} event${offHours.length > 1 ? "s" : ""} outside normal hours (22:00–06:00)`,
      user: offHours[0]?.who?.slice(0, 8) + "…",
      time: new Date(offHours[0]?.when).toLocaleTimeString(),
      traceId: offHours[0]?.trace_id,
    });
  }

  // 3. Purpose mismatch
  const mismatches = events.filter((e) => {
    if (!e.purpose_of_access || !e.what) return false;
    const banned = PURPOSE_MISMATCH[e.purpose_of_access] || [];
    return banned.some((tool) => e.what.startsWith(tool));
  });
  if (mismatches.length > 0) {
    anomalies.push({
      id: "purpose-mismatch",
      severity: "medium",
      type: "Purpose Mismatch",
      description: `${mismatches[0].purpose_of_access?.replace(/_/g, " ")} → ${mismatches[0].what?.split(":")[0]}`,
      user: mismatches[0]?.who?.slice(0, 8) + "…",
      time: new Date(mismatches[0]?.when).toLocaleTimeString(),
      traceId: mismatches[0]?.trace_id,
    });
  }

  // 4. Repeat denials by same user
  const denialsByUser: Record<string, AuditEvent[]> = {};
  events
    .filter((e) => e.outcome === "403")
    .forEach((e) => {
      denialsByUser[e.who] = denialsByUser[e.who] || [];
      denialsByUser[e.who].push(e);
    });
  const repeatDeniers = Object.entries(denialsByUser).filter(
    ([, evs]) => evs.length >= 3
  );
  if (repeatDeniers.length > 0) {
    const [user, evs] = repeatDeniers[0];
    anomalies.push({
      id: "repeat-denials",
      severity: "low",
      type: "Repeat Denials",
      description: `${evs.length} consecutive 403 responses`,
      user: user.slice(0, 8) + "…",
      time: new Date(evs[0].when).toLocaleTimeString(),
      traceId: evs[0]?.trace_id,
    });
  }

  // 5. Cross-role probing
  const crossRole = Object.entries(denialsByUser).filter(([, evs]) => {
    const servers = new Set(evs.map((e) => e.server_name));
    return servers.size >= 2;
  });
  if (crossRole.length > 0) {
    const [user, evs] = crossRole[0];
    const servers = [...new Set(evs.map((e) => e.server_name))];
    anomalies.push({
      id: "cross-role",
      severity: "high",
      type: "Cross-role Probing",
      description: `Denied across ${servers.length} servers: ${servers.join(", ")}`,
      user: user.slice(0, 8) + "…",
      time: new Date(evs[0].when).toLocaleTimeString(),
      traceId: evs[0]?.trace_id,
    });
  }

  return anomalies;
}

export function AnomalyPanel({ token }: { token: string }) {
  const registryUrl = process.env.NEXT_PUBLIC_REGISTRY_URL || "http://localhost:8600";
  const jaegerUrl = process.env.NEXT_PUBLIC_JAEGER_URL || "http://localhost:16686";

  const { data: events = [], isLoading } = useSWR<AuditEvent[]>(
    token ? `${registryUrl}/audit?limit=500` : null,
    async (url: string) => {
      const res = await fetch(url, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) return [];
      return res.json();
    },
    { refreshInterval: 30000 }
  );

  const anomalies = detectAnomalies(events);

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-white">Recent Anomalies</span>
          {anomalies.length > 0 && (
            <span className="text-xs bg-red-500/20 text-red-400 px-1.5 py-0.5 rounded-full">
              {anomalies.length}
            </span>
          )}
        </div>
        <button className="text-xs text-blue-400 hover:text-blue-300">
          View all anomalies ↗
        </button>
      </div>

      {isLoading && (
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-12 bg-[#111827] rounded-lg animate-pulse" />
          ))}
        </div>
      )}

      {!isLoading && anomalies.length === 0 && (
        <div className="text-center py-8 text-gray-600 text-sm border border-[#1F2937] rounded-xl">
          <span className="text-2xl mb-2 block">✓</span>
          No anomalies detected
          {events.length === 0 && (
            <p className="text-xs mt-1">Audit log empty — anomalies populate as queries run</p>
          )}
        </div>
      )}

      {anomalies.length > 0 && (
        <div className="border border-[#1F2937] rounded-xl overflow-hidden">
          {/* Table header */}
          <div className="grid grid-cols-[80px_1fr_1fr_100px_120px] gap-3 px-4 py-2.5 bg-[#0D1625] border-b border-[#1F2937] text-xs font-medium text-gray-500">
            <span>Severity</span>
            <span>Type</span>
            <span>Description</span>
            <span>User</span>
            <span>Trace ID</span>
          </div>

          {anomalies.map((a) => (
            <div
              key={a.id}
              className="grid grid-cols-[80px_1fr_1fr_100px_120px] gap-3 px-4 py-3 border-b border-[#1F2937] last:border-0 hover:bg-[#111827] transition-colors"
            >
              {/* Severity */}
              <div>
                <span
                  className={`text-xs px-2 py-0.5 rounded-full border font-medium capitalize ${SEVERITY_STYLES[a.severity]}`}
                >
                  {a.severity.charAt(0).toUpperCase() + a.severity.slice(1)}
                </span>
              </div>

              {/* Type */}
              <div className="flex items-center gap-1.5">
                <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${SEVERITY_DOT[a.severity]}`} />
                <span className="text-sm text-white font-medium">{a.type}</span>
              </div>

              {/* Description */}
              <span className="text-sm text-gray-400">{a.description}</span>

              {/* User */}
              <span className="font-mono text-xs text-gray-500">{a.user || "—"}</span>

              {/* Trace ID + time */}
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-600">{a.time}</span>
                {a.traceId && (
                  <a
                    href={`${jaegerUrl}/trace/${a.traceId}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-mono text-xs text-blue-500 hover:text-blue-400 transition-colors"
                    title={a.traceId}
                  >
                    {a.traceId.slice(0, 8)} ↗
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
