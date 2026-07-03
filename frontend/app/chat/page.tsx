"use client";

import { useSession, signIn } from "next-auth/react";
import { useState, useRef, useEffect } from "react";
import { PurposeSelector } from "@/components/PurposeSelector";
import { PatientPicker } from "@/components/PatientPicker";
import { AnswerBubble } from "@/components/AnswerBubble";

/**
 * app/chat/page.tsx
 *
 * Clinician chat — asks a natural-language clinical question, receives
 * one fused cited answer from all permitted MCP servers.
 *
 * Data flow:
 *   User submits → POST http://localhost:8500/ask (Bearer JWT)
 *   Runtime agent → registry-api (service token) → MCP servers via Kong
 *   Answer returned with servers_called[] → rendered with AnswerBubble
 *
 * The frontend NEVER calls Kong or MCP servers directly.
 * Only agent :8500 and registry-api :8600 are called from the browser.
 */

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  serversCALLED?: string[];
  serversAvailable?: string[];
  patientId?: string;
  purpose?: string;
  traceId?: string;
  timestamp: Date;
  isLoading?: boolean;
}

interface AskResponse {
  answer: string;
  patient_id: string;
  patient_uuid: string;
  purpose_of_access: string;
  servers_called: string[];
  servers_available?: string[];
  trace_id?: string;
}


function SystemStatusBadge() {
  const [status, setStatus] = useState<"checking" | "ok" | "error">("checking");

  useEffect(() => {
    fetch("/api/agent/health")
      .then((r) => setStatus(r.ok ? "ok" : "error"))
      .catch(() => setStatus("error"));
  }, []);

  return (
    <div className="flex items-center gap-1.5 text-xs">
      <span
        className={`w-1.5 h-1.5 rounded-full ${
          status === "ok"
            ? "bg-green-400 animate-pulse"
            : status === "error"
            ? "bg-red-400"
            : "bg-amber-400"
        }`}
      />
      <span className="text-gray-500">
        {status === "ok" ? "Agent online" : status === "error" ? "Agent offline" : "Checking…"}
      </span>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex items-center gap-1 px-4 py-2">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-bounce"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
      <span className="text-xs text-gray-500 ml-1">Querying clinical data sources…</span>
    </div>
  );
}

export default function ChatPage() {
  const { data: session, status } = useSession();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [patient, setPatient] = useState("demo-patient-1");
  const [purpose, setPurpose] = useState("routine_review");
  const [purposeOpen, setPurposeOpen] = useState(false);
  const [patientOpen, setPatientOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const threadRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

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
        <div className="text-center">
          <p className="text-gray-400 mb-4">You need to sign in to access the chat.</p>
          <button
            onClick={() => signIn("keycloak")}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm"
          >
            Sign in
          </button>
        </div>
      </div>
    );
  }

  async function handleSend() {
    const question = input.trim();
    if (!question || loading || !session?.accessToken) return;

    const userMsg: Message = {
      id: Date.now().toString(),
      role: "user",
      content: question,
      timestamp: new Date(),
    };
    const loadingMsg: Message = {
      id: Date.now().toString() + "-loading",
      role: "assistant",
      content: "",
      timestamp: new Date(),
      isLoading: true,
    };

    setMessages((prev) => [...prev, userMsg, loadingMsg]);
    setInput("");
    setLoading(true);

    try {
      const t0 = Date.now();
      const res = await fetch("/api/agent/ask", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          question,
          patient_id: patient,
          purpose_of_access: purpose,
        }),
      });

      const elapsed = Date.now() - t0;

      if (res.status === 401) {
        setMessages((prev) =>
          prev
            .filter((m) => !m.isLoading)
            .concat({
              id: Date.now().toString(),
              role: "assistant",
              content: "Session expired. Please sign out and sign back in.",
              timestamp: new Date(),
            })
        );
        return;
      }
      if (res.status === 422) {
        setMessages((prev) =>
          prev
            .filter((m) => !m.isLoading)
            .concat({
              id: Date.now().toString(),
              role: "assistant",
              content: "Invalid purpose of access selected. Please choose a valid option.",
              timestamp: new Date(),
            })
        );
        return;
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err?.detail || `HTTP ${res.status}`);
      }

      const data: AskResponse = await res.json();

      setMessages((prev) =>
        prev
          .filter((m) => !m.isLoading)
          .concat({
            id: Date.now().toString(),
            role: "assistant",
            content: data.answer,
            serversCALLED: data.servers_called,
            serversAvailable: data.servers_available,
            patientId: data.patient_id,
            purpose: data.purpose_of_access,
            traceId: data.trace_id,
            timestamp: new Date(),
          })
      );
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setMessages((prev) =>
        prev
          .filter((m) => !m.isLoading)
          .concat({
            id: Date.now().toString(),
            role: "assistant",
            content: msg.includes("fetch failed") || msg.includes("Failed to fetch")
              ? "Cannot reach the runtime agent. Make sure it is running on port 8500."
              : `Error: ${msg}`,
            timestamp: new Date(),
          })
      );
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  const groups = session.groups || [];
  const isPhysician = groups.includes("grp-physician");

  return (
    <div className="flex min-h-[calc(100vh-56px)] bg-[#0A0F1E]">
      {/* Sidebar */}
      <aside className="hidden lg:flex lg:flex-col w-72 border-r border-[#1F2937] bg-[#0D1120] overflow-y-auto">
        <div className="p-4 space-y-4">
          {/* Step 1 — Patient */}
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="w-5 h-5 rounded-full bg-blue-600 text-white text-xs flex items-center justify-center font-bold">
                1
              </span>
              <span className="text-xs font-medium text-gray-400 uppercase tracking-wider">
                Select Patient
              </span>
            </div>
            <PatientPicker
              value={patient}
              onChange={setPatient}
              open={patientOpen}
              onToggle={() => setPatientOpen(!patientOpen)}
            />
          </div>

          {/* Step 2 — Purpose */}
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="w-5 h-5 rounded-full bg-blue-600 text-white text-xs flex items-center justify-center font-bold">
                2
              </span>
              <span className="text-xs font-medium text-gray-400 uppercase tracking-wider">
                Purpose of Access
              </span>
            </div>
            <PurposeSelector
              value={purpose}
              onChange={setPurpose}
              open={purposeOpen}
              onToggle={() => setPurposeOpen(!purposeOpen)}
            />
          </div>

          {/* PHI notice */}
          <div className="rounded-lg border border-blue-900/30 bg-blue-600/5 p-3">
            <div className="flex items-start gap-2">
              <span className="text-blue-400 text-sm">🛡</span>
              <div>
                <p className="text-xs font-medium text-blue-300">Your Access is Monitored</p>
                <p className="text-xs text-gray-500 mt-0.5">
                  All access is logged and audited for compliance and patient safety.
                </p>
              </div>
            </div>
          </div>

          {/* System status */}
          <div className="space-y-1.5 pt-2 border-t border-[#1F2937]">
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">
              System Status
            </p>
            <SystemStatusBadge />
            {[
              { label: "Registry API", port: 8600 },
              { label: "Kong Gateway", port: 8000 },
            ].map((s) => (
              <div key={s.label} className="flex items-center gap-1.5 text-xs">
                <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
                <span className="text-gray-500">{s.label}</span>
              </div>
            ))}
          </div>

          {/* Recent conversations */}
          {messages.filter((m) => m.role === "user").length > 0 && (
            <div className="pt-2 border-t border-[#1F2937]">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Recent
                </p>
                <button className="text-xs text-blue-400">View all</button>
              </div>
              {messages
                .filter((m) => m.role === "user")
                .slice(-3)
                .reverse()
                .map((m) => (
                  <div
                    key={m.id}
                    className="py-2 border-b border-[#1F2937] last:border-0 cursor-pointer hover:bg-[#111827] rounded px-2 transition-colors"
                    onClick={() => setInput(m.content)}
                  >
                    <p className="text-xs text-gray-400 truncate">{m.content}</p>
                    <p className="text-xs text-gray-600 mt-0.5">
                      {m.timestamp.toLocaleTimeString()} · {patient}
                    </p>
                  </div>
                ))}
            </div>
          )}
        </div>
      </aside>

      {/* Main chat area */}
      <div className="flex-1 flex flex-col max-w-4xl mx-auto w-full px-4">
        {/* Header */}
        <div className="py-4 border-b border-[#1F2937]">
          <h1 className="text-lg font-semibold text-white">Chat</h1>
          <p className="text-sm text-gray-500">
            Ask a clinical question across all permitted data sources
          </p>
        </div>

        {/* Thread */}
        <div
          ref={threadRef}
          className="flex-1 overflow-y-auto py-6 space-y-6 min-h-0"
          style={{ maxHeight: "calc(100vh - 260px)" }}
        >
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-64 gap-4">
              <div className="w-16 h-16 rounded-2xl bg-blue-600/10 border border-blue-600/20 flex items-center justify-center text-3xl">
                🩺
              </div>
              <div className="text-center">
                <h3 className="text-white font-medium">
                  What would you like to know about {patient}?
                </h3>
                <p className="text-gray-500 text-sm mt-1">
                  Include vitals, labs, medications, and clinical notes.
                </p>
              </div>
              {/* Suggested questions */}
              <div className="flex flex-wrap gap-2 justify-center max-w-lg">
                {[
                  "What is this patient's overall risk picture?",
                  "Are there any drug interactions I should know about?",
                  "Summarise the latest clinical notes for this patient.",
                  "What does the radiology report show?",
                ].map((q) => (
                  <button
                    key={q}
                    onClick={() => setInput(q)}
                    className="text-xs px-3 py-1.5 rounded-full border border-[#1F2937] text-gray-400 hover:border-blue-600/40 hover:text-blue-400 transition-colors"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg) => (
            <div key={msg.id} className="message-enter">
              {msg.role === "user" ? (
                <div className="flex justify-end">
                  <div className="max-w-2xl">
                    <div className="bg-blue-600 text-white text-sm rounded-2xl rounded-tr-sm px-4 py-3 leading-relaxed">
                      {msg.content}
                    </div>
                    <p className="text-xs text-gray-600 mt-1 text-right">
                      {msg.timestamp.toLocaleTimeString()}
                    </p>
                  </div>
                </div>
              ) : msg.isLoading ? (
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 rounded-full bg-blue-600/10 border border-blue-600/20 flex items-center justify-center text-blue-400 flex-shrink-0">
                    ⚕
                  </div>
                  <div className="bg-[#111827] border border-[#1F2937] rounded-2xl rounded-tl-sm px-4 py-3">
                    <TypingIndicator />
                  </div>
                </div>
              ) : (
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 rounded-full bg-blue-600/10 border border-blue-600/20 flex items-center justify-center text-blue-400 flex-shrink-0 mt-0.5">
                    ⚕
                  </div>
                  <div className="flex-1 bg-[#111827] border border-[#1F2937] rounded-2xl rounded-tl-sm px-4 py-4">
                    {msg.serversCALLED ? (
                      <AnswerBubble
                        answer={msg.content}
                        serversCALLED={msg.serversCALLED}
                        serversAvailable={msg.serversAvailable}
                        patientId={msg.patientId || patient}
                        purpose={msg.purpose || purpose}
                        traceId={msg.traceId}
                      />
                    ) : (
                      <p className="text-sm text-gray-300 leading-relaxed">{msg.content}</p>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Input area */}
        <div className="py-4 border-t border-[#1F2937]">
          {/* Mobile controls */}
          <div className="flex gap-2 mb-3 lg:hidden">
            <div className="flex-1">
              <PatientPicker
                value={patient}
                onChange={setPatient}
                open={patientOpen}
                onToggle={() => setPatientOpen(!patientOpen)}
              />
            </div>
            <div className="flex-1">
              <PurposeSelector
                value={purpose}
                onChange={setPurpose}
                open={purposeOpen}
                onToggle={() => setPurposeOpen(!purposeOpen)}
              />
            </div>
          </div>

          <div className="relative bg-[#111827] border border-[#1F2937] focus-within:border-blue-600/50 rounded-xl overflow-hidden transition-colors">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask your clinical question…"
              rows={2}
              disabled={loading}
              className="w-full bg-transparent px-4 py-3 text-sm text-white placeholder-gray-600 resize-none focus:outline-none disabled:opacity-50"
            />
            <div className="flex items-center justify-between px-3 pb-2.5">
              <p className="text-xs text-gray-600">
                Press Enter to send · Shift + Enter for new line
              </p>
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-600">{input.length}/2000</span>
                <button
                  onClick={handleSend}
                  disabled={loading || !input.trim() || !purpose}
                  className="w-8 h-8 bg-blue-600 hover:bg-blue-500 disabled:bg-[#1F2937] disabled:cursor-not-allowed rounded-lg flex items-center justify-center text-white transition-colors"
                  title={!purpose ? "Select a purpose first" : "Send"}
                >
                  {loading ? (
                    <span className="w-3 h-3 border border-white border-t-transparent rounded-full animate-spin" />
                  ) : (
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                    </svg>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
