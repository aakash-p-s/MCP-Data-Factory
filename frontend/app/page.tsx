"use client";

import { useSession, signIn } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

/**
 * app/page.tsx — Root route
 *
 * If authenticated → redirect to /chat
 * If not → show the login card (matches image reference: split layout)
 */
export default function HomePage() {
  const { data: session, status } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (status === "authenticated") {
      router.replace("/chat");
    }
  }, [status, router]);

  if (status === "loading") {
    return (
      <div className="min-h-screen bg-[#0A0F1E] flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (status === "authenticated") return null;

  return (
    <div className="min-h-screen bg-[#0A0F1E] flex">
      {/* Left panel — branding */}
      <div className="hidden lg:flex lg:w-5/12 bg-gradient-to-br from-[#0D1B3E] to-[#0A0F1E] flex-col justify-between p-10 border-r border-[#1F2937]">
        <div>
          <div className="flex items-center gap-3 mb-12">
            <div className="w-10 h-10 rounded-xl bg-blue-600 flex items-center justify-center text-white text-lg font-bold">
              ⚕
            </div>
            <div>
              <p className="text-white font-semibold text-lg leading-tight">Patient Risk</p>
              <p className="text-blue-400 text-sm">AI Platform</p>
            </div>
          </div>

          <h1 className="text-3xl font-bold text-white leading-tight mb-3">
            Enterprise-Grade<br />Clinical Intelligence
          </h1>
          <div className="w-12 h-0.5 bg-blue-500 mb-6" />
          <p className="text-gray-400 text-sm leading-relaxed mb-10">
            Secure, explainable, and compliant AI-powered insights for better patient outcomes.
          </p>

          <div className="space-y-5">
            {[
              {
                icon: "🔒",
                title: "Enterprise Security",
                desc: "Keycloak SSO, RBAC, and PHI protection",
              },
              {
                icon: "⚡",
                title: "Unified Data Access",
                desc: "5 clinical domains via MCP servers",
              },
              {
                icon: "🧠",
                title: "AI-Powered Insights",
                desc: "LangGraph agent with FHIR-compliant responses",
              },
              {
                icon: "📋",
                title: "Audit & Compliance",
                desc: "Complete audit trail and anomaly detection",
              },
            ].map((f) => (
              <div key={f.title} className="flex items-start gap-3">
                <div className="w-9 h-9 rounded-lg bg-blue-600/10 border border-blue-600/20 flex items-center justify-center text-base flex-shrink-0">
                  {f.icon}
                </div>
                <div>
                  <p className="text-white text-sm font-medium">{f.title}</p>
                  <p className="text-gray-500 text-xs mt-0.5">{f.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="border border-blue-600/20 rounded-xl p-4 bg-blue-600/5">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-blue-400 text-sm">🛡</span>
            <p className="text-blue-300 text-sm font-medium">HIPAA Compliant</p>
          </div>
          <p className="text-gray-500 text-xs">Built with privacy and security by design</p>
        </div>
      </div>

      {/* Right panel — login form */}
      <div className="flex-1 flex flex-col">
        {/* System status bar */}
        <div className="flex justify-end px-6 py-3 border-b border-[#1F2937]">
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <span>⚙ System Status</span>
            <span className="flex items-center gap-1 text-green-400">
              <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
              Operational
            </span>
          </div>
        </div>

        <div className="flex-1 flex items-center justify-center p-8">
          <div className="w-full max-w-md">
            <div className="bg-[#111827] border border-[#1F2937] rounded-2xl p-8 shadow-2xl">
              <div className="text-center mb-8">
                <div className="w-12 h-12 rounded-xl bg-blue-600/10 border border-blue-600/20 flex items-center justify-center text-2xl mx-auto mb-4">
                  🔐
                </div>
                <h2 className="text-xl font-bold text-white">Welcome Back</h2>
                <p className="text-gray-400 text-sm mt-1">Sign in to your clinical workspace</p>
              </div>

              {/* SSO Button — primary action */}
              <button
                onClick={() => signIn("keycloak", {
                  callbackUrl: "/chat",
                  prompt: "login",
                })}
                className="w-full h-11 bg-blue-600 hover:bg-blue-500 active:bg-blue-700 text-white font-medium text-sm rounded-lg flex items-center justify-center gap-2 transition-colors mb-4"
              >
                <span>🔑</span>
                Sign in with Keycloak SSO
                <span className="ml-auto">→</span>
              </button>

              <div className="relative my-5">
                <div className="absolute inset-0 flex items-center">
                  <div className="w-full border-t border-[#1F2937]" />
                </div>
                <div className="relative flex justify-center">
                  <span className="bg-[#111827] px-3 text-xs text-gray-600">Demo accounts</span>
                </div>
              </div>

              {/* Demo user list */}
              <div className="space-y-2">
                {[
                  { user: "doctor-test", role: "Physician", color: "text-green-400" },
                  { user: "nurse-test", role: "Clinical Viewer", color: "text-blue-400" },
                  { user: "casemanager-test", role: "Case Manager", color: "text-amber-400" },
                ].map((u) => (
                  <div
                    key={u.user}
                    className="flex items-center justify-between px-3 py-2 rounded-lg border border-[#1F2937] hover:border-[#374151] transition-colors"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-gray-500 text-sm">👤</span>
                      <span className="font-mono text-xs text-gray-300">{u.user}</span>
                      <span className="text-gray-600 text-xs">/ test123</span>
                    </div>
                    <span className={`text-xs font-medium ${u.color}`}>{u.role}</span>
                  </div>
                ))}
              </div>

              <p className="text-center text-xs text-gray-600 mt-6">
                By signing in, you agree to the{" "}
                <span className="text-blue-500 cursor-pointer">Terms of Service</span>
                {" "}and{" "}
                <span className="text-blue-500 cursor-pointer">Privacy Policy</span>
              </p>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="border-t border-[#1F2937] px-6 py-3 flex items-center justify-between text-xs text-gray-600">
          <span>Patient Risk AI Platform © 2026 All rights reserved.</span>
          <span>Platform Version: 1.0.0 · Build: 2026.07.1</span>
          <span className="text-blue-500 cursor-pointer">Need help?</span>
        </div>
      </div>
    </div>
  );
}
