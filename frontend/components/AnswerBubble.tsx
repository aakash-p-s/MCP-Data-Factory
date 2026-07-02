"use client";

/**
 * components/AnswerBubble.tsx
 *
 * Renders the agent's cited answer with inline coloured server pills.
 * The synthesis prompt in agent/prompts.py instructs the LLM to cite sources
 * as "(server_name)" — we parse and replace those with coloured badges.
 */

const SERVER_COLORS: Record<string, { bg: string; text: string; dot: string }> = {
  vitals_trends: {
    bg: "bg-blue-900/40",
    text: "text-blue-300",
    dot: "bg-blue-400",
  },
  labs_diagnoses: {
    bg: "bg-teal-900/40",
    text: "text-teal-300",
    dot: "bg-teal-400",
  },
  medications_interactions: {
    bg: "bg-purple-900/40",
    text: "text-purple-300",
    dot: "bg-purple-400",
  },
  clinical_notes_search: {
    bg: "bg-amber-900/40",
    text: "text-amber-300",
    dot: "bg-amber-400",
  },
  radiology_reports: {
    bg: "bg-orange-900/40",
    text: "text-orange-300",
    dot: "bg-orange-400",
  },
};

const ALL_SERVERS = [
  "vitals_trends",
  "labs_diagnoses",
  "medications_interactions",
  "clinical_notes_search",
  "radiology_reports",
];

const CITATION_REGEX =
  /\((vitals_trends|labs_diagnoses|medications_interactions|clinical_notes_search|radiology_reports(?:_[a-z]+)?)\)/g;

function CitationPill({ server }: { server: string }) {
  const colors = SERVER_COLORS[server] || {
    bg: "bg-gray-900/40",
    text: "text-gray-300",
    dot: "bg-gray-400",
  };
  return (
    <span
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-mono font-medium mx-0.5 ${colors.bg} ${colors.text}`}
    >
      <span className={`w-1 h-1 rounded-full ${colors.dot}`} />
      {server.replace(/_/g, "_")}
    </span>
  );
}

function renderAnswerWithCitations(text: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match;

  const regex = new RegExp(CITATION_REGEX.source, "g");
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    parts.push(<CitationPill key={match.index} server={match[1]} />);
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }
  return parts;
}

interface AnswerBubbleProps {
  answer: string;
  serversCALLED: string[];
  patientId: string;
  purpose: string;
  traceId?: string;
  responseTimeMs?: number;
}

export function AnswerBubble({
  answer,
  serversCALLED,
  patientId,
  purpose,
  traceId,
  responseTimeMs,
}: AnswerBubbleProps) {
  const jaegerUrl = process.env.NEXT_PUBLIC_JAEGER_URL || "http://localhost:16686";
  const missedServers = ALL_SERVERS.filter((s) => !serversCALLED.includes(s));

  return (
    <div className="message-enter">
      {/* Answer header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-gray-400">AI Response</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-green-900/40 text-green-400 font-medium">
            Complete
          </span>
        </div>
        {responseTimeMs && (
          <span className="text-xs text-gray-600">
            {(responseTimeMs / 1000).toFixed(2)}s
          </span>
        )}
      </div>

      {/* Answer text with inline citations */}
      <div className="text-sm text-gray-200 leading-relaxed whitespace-pre-wrap">
        {renderAnswerWithCitations(answer)}
      </div>

      {/* Servers called */}
      <div className="mt-4 pt-3 border-t border-[#1F2937]">
        <p className="text-xs text-gray-500 mb-2">
          Servers called ({serversCALLED.length}) →
        </p>
        <div className="flex flex-wrap gap-1.5">
          {serversCALLED.map((s) => {
            const c = SERVER_COLORS[s];
            return (
              <span
                key={s}
                className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium ${
                  c ? `${c.bg} ${c.text}` : "bg-gray-800 text-gray-400"
                }`}
              >
                <span className={`w-1.5 h-1.5 rounded-full ${c?.dot || "bg-gray-500"}`} />
                {s}
              </span>
            );
          })}
          {missedServers.map((s) => (
            <span
              key={s}
              className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-gray-900/50 text-gray-600"
              title="Not accessible for your role"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-gray-700" />
              {s}
              <span className="text-gray-700">—</span>
            </span>
          ))}
        </div>

        {/* Role-aware message */}
        {missedServers.length > 0 && (
          <p className="mt-2 text-xs text-amber-500/80">
            ℹ You have access to {serversCALLED.length} of {ALL_SERVERS.length} servers.
            Physician role required for full access.
          </p>
        )}
      </div>

      {/* Trace ID + metadata footer */}
      <div className="mt-2 flex items-center justify-between text-xs text-gray-600">
        <span>
          {patientId} · {purpose.replace(/_/g, " ")}
        </span>
        {traceId && (
          <a
            href={`${jaegerUrl}/trace/${traceId}`}
            target="_blank"
            rel="noopener noreferrer"
            className="font-mono text-blue-500/70 hover:text-blue-400 transition-colors"
          >
            {traceId.slice(0, 12)}… ↗
          </a>
        )}
      </div>
    </div>
  );
}
