"use client";

import { useEffect, useState } from "react";

/**
 * components/PatientPicker.tsx
 *
 * Dropdown of demo-patient-1 … demo-patient-31 aliases, with a toggle to switch
 * to a search box (filter by ID) for faster lookup.
 * The frontend sends the alias directly — the runtime agent resolves it to the
 * real Synthea UUID via demo_patient_aliases.json (see agent/runtime_agent.py).
 */

const PATIENTS = Array.from({ length: 31 }, (_, i) => `demo-patient-${i + 1}`);

interface PatientPickerProps {
  value: string;
  onChange: (value: string) => void;
  open: boolean;
  onToggle: () => void;
}

export function PatientPicker({ value, onChange, open, onToggle }: PatientPickerProps) {
  const [mode, setMode] = useState<"list" | "search">("list");
  const [query, setQuery] = useState("");

  // Start fresh each time the picker is opened, rather than keeping the last search.
  useEffect(() => {
    if (open) {
      setMode("list");
      setQuery("");
    }
  }, [open]);

  const q = query.trim().toLowerCase();
  const results =
    mode === "search" && q
      ? PATIENTS.filter((p) => p.toLowerCase().includes(q))
      : PATIENTS;

  return (
    <div className="relative">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between gap-2 px-3 py-2 bg-[#111827] border border-[#1F2937] rounded-lg hover:border-[#374151] transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className="text-sm">👤</span>
          <span className="text-sm text-white font-medium font-mono">{value}</span>
        </div>
        <svg
          className={`w-4 h-4 text-gray-500 transition-transform ${open ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>


      {open && (
        <div className="absolute top-full left-0 right-0 mt-1 bg-[#111827] border border-[#1F2937] rounded-xl shadow-2xl z-50 overflow-hidden">
          {/* Toggle between browsing the list and searching by id/name */}
          <div className="flex items-center gap-1 p-1.5 border-b border-[#1F2937]">
            <button
              onClick={() => setMode("list")}
              className={`flex-1 flex items-center justify-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium transition-colors ${
                mode === "list" ? "bg-blue-600/20 text-blue-400" : "text-gray-500 hover:text-gray-300"
              }`}
            >
              📋 List
            </button>
            <button
              onClick={() => setMode("search")}
              className={`flex-1 flex items-center justify-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium transition-colors ${
                mode === "search" ? "bg-blue-600/20 text-blue-400" : "text-gray-500 hover:text-gray-300"
              }`}
            >
              🔍 Search
            </button>
          </div>

          {mode === "search" && (
            <div className="p-2 border-b border-[#1F2937]">
              <input
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search by patient ID…"
                className="w-full px-3 py-1.5 bg-[#0A0F1E] border border-[#1F2937] rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-600"
              />
            </div>
          )}

          <div className="overflow-y-auto max-h-48">
            {results.length === 0 ? (
              <p className="text-xs text-gray-600 text-center py-4">No matching patients</p>
            ) : (
              results.map((p) => (
                <button
                  key={p}
                  onClick={() => {
                    onChange(p);
                    onToggle();
                  }}
                  className={`w-full flex items-center gap-2 px-4 py-2.5 hover:bg-[#1F2937] transition-colors text-left ${
                    value === p ? "bg-blue-600/10" : ""
                  }`}
                >
                  <span className="text-xs text-gray-500">👤</span>
                  <span className="font-mono text-sm text-gray-300">{p}</span>
                  {p === "demo-patient-1" && (
                    <span className="ml-auto text-xs text-blue-400 bg-blue-600/10 px-1.5 py-0.5 rounded">
                      primary
                    </span>
                  )}
                  {value === p && <span className="ml-auto text-blue-400 text-xs">✓</span>}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
