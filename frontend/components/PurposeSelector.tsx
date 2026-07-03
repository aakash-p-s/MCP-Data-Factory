"use client";

/**
 * components/PurposeSelector.tsx
 *
 * Fixed 5-value purpose_of_access dropdown.
 * These values are frozen in the PRD (§6.4) and validated by the runtime
 * agent. The Send button in the chat page is disabled until one is selected.
 */

const PURPOSES = [
  {
    value: "deterioration_review",
    label: "Deterioration Review",
    desc: "Assess clinical decline or change in condition",
    icon: "📉",
  },
  {
    value: "medication_reconciliation",
    label: "Medication Reconciliation",
    desc: "Review and reconcile medications",
    icon: "💊",
  },
  {
    value: "discharge_planning",
    label: "Discharge Planning",
    desc: "Plan safe transition from care setting",
    icon: "🏥",
  },
  {
    value: "care_coordination",
    label: "Care Coordination",
    desc: "Coordinate care across departments",
    icon: "🤝",
  },
  {
    value: "routine_review",
    label: "Routine Review",
    desc: "Standard clinical assessment",
    icon: "📋",
  },
];

interface PurposeSelectorProps {
  value: string;
  onChange: (value: string) => void;
  open: boolean;
  onToggle: () => void;
}

export function PurposeSelector({
  value,
  onChange,
  open,
  onToggle,
}: PurposeSelectorProps) {
  const selected = PURPOSES.find((p) => p.value === value);

  return (
    <div className="relative">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between gap-2 px-3 py-2 bg-[#111827] border border-[#1F2937] rounded-lg hover:border-[#374151] transition-colors"
      >
        <div className="flex items-center gap-2">
          {selected ? (
            <>
              <span>{selected.icon}</span>
              <span className="text-sm text-white font-medium">{selected.label}</span>
            </>
          ) : (
            <span className="text-sm text-gray-500">Select purpose of access</span>
          )}
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
          {PURPOSES.map((p) => (
            <button
              key={p.value}
              onClick={() => {
                onChange(p.value);
                onToggle();
              }}
              className={`w-full flex items-start gap-3 px-4 py-3 hover:bg-[#1F2937] transition-colors text-left ${
                value === p.value ? "bg-blue-600/10 border-l-2 border-blue-500" : ""
              }`}
            >
              <span className="text-base mt-0.5">{p.icon}</span>
              <div>
                <p className="text-sm font-medium text-white">{p.label}</p>
                <p className="text-xs text-gray-500 mt-0.5">{p.desc}</p>
              </div>
              {value === p.value && (
                <span className="ml-auto text-blue-400 text-sm">✓</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export { PURPOSES };
