"use client";

/**
 * components/PatientPicker.tsx
 *
 * Dropdown of demo-patient-1 … demo-patient-31 aliases.
 * The frontend sends the alias directly — the runtime agent resolves it to the
 * real Synthea UUID via demo_patient_aliases.json (see agent/runtime_agent.py).
 */

const PATIENTS = Array.from({ length: 31 }, (_, i) => `demo-patient-${i + 1}`);

// demo-patient-1 is Chester802 Aufderhar910, 59yo — our primary demo patient
const PATIENT_DISPLAY: Record<string, { name: string; age: number; mrn: string }> = {
  "demo-patient-1": { name: "Chester802 Aufderhar910", age: 59, mrn: "DEMO-0001" },
};

interface PatientPickerProps {
  value: string;
  onChange: (value: string) => void;
  open: boolean;
  onToggle: () => void;
}

export function PatientPicker({ value, onChange, open, onToggle }: PatientPickerProps) {
  const detail = PATIENT_DISPLAY[value];

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

      {/* Patient detail card shown below picker when selected */}
      {detail && !open && (
        <div className="mt-2 px-3 py-2.5 bg-[#0D1B3E] border border-blue-900/30 rounded-lg">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-full bg-blue-600/20 flex items-center justify-center text-blue-400 text-sm">
              👤
            </div>
            <div>
              <p className="text-sm font-medium text-white">{detail.name}</p>
              <p className="text-xs text-gray-500">
                {detail.age} yrs · MRN: <span className="font-mono">{detail.mrn}</span>
              </p>
            </div>
          </div>
        </div>
      )}

      {open && (
        <div className="absolute top-full left-0 right-0 mt-1 bg-[#111827] border border-[#1F2937] rounded-xl shadow-2xl z-50 overflow-y-auto max-h-48">
          {PATIENTS.map((p) => (
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
          ))}
        </div>
      )}
    </div>
  );
}
