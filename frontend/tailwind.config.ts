import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./node_modules/@tremor/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        "surface-base": "#0A0F1E",
        "surface-card": "#111827",
        "surface-border": "#1F2937",
        "accent-primary": "#3B82F6",
        "accent-success": "#10B981",
        "accent-warning": "#F59E0B",
        "accent-danger": "#EF4444",
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
    },
  },
  plugins: [],
};
export default config;
