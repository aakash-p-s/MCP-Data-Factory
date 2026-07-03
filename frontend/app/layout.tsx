"use client";

import "./globals.css";
import { SessionProvider, useSession, signOut } from "next-auth/react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

function Nav() {
  const { data: session } = useSession();
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  const isLogin = pathname === "/" || pathname === "/login";
  if (isLogin || !session) return null;

  const groups = session.groups || [];
  const roleLabel = groups.includes("grp-physician")
    ? "Physician"
    : groups.includes("grp-clinical-viewer")
    ? "Clinical Viewer"
    : groups.includes("grp-case-manager")
    ? "Case Manager"
    : "User";

  const roleBadgeColor = groups.includes("grp-physician")
    ? "bg-green-900 text-green-300"
    : groups.includes("grp-clinical-viewer")
    ? "bg-blue-900 text-blue-300"
    : "bg-amber-900 text-amber-300";

  return (
    <header className="fixed top-0 left-0 right-0 z-50 border-b border-[#1F2937] bg-[#0A0F1E]/95 backdrop-blur-sm">
      <div className="mx-auto max-w-screen-xl px-4 h-14 flex items-center justify-between">
        {/* Logo */}
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-blue-600 flex items-center justify-center text-white text-sm font-bold">
            ⚕
          </div>
          <span className="text-sm font-semibold text-white hidden sm:block">
            Patient Risk AI
          </span>
        </div>

        {/* Nav links */}
        <nav className="flex items-center gap-1">
          <Link
            href="/chat"
            className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
              pathname === "/chat"
                ? "bg-blue-600/20 text-blue-400"
                : "text-gray-400 hover:text-white hover:bg-white/5"
            }`}
          >
            Chat
          </Link>
          <Link
            href="/dashboard"
            className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
              pathname === "/dashboard"
                ? "bg-blue-600/20 text-blue-400"
                : "text-gray-400 hover:text-white hover:bg-white/5"
            }`}
          >
            Dashboard
          </Link>
        </nav>

        {/* User menu */}
        <div className="relative">
          <button
            onClick={() => setMenuOpen(!menuOpen)}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-[#1F2937] hover:border-[#374151] transition-colors"
          >
            <div className="w-6 h-6 rounded-full bg-blue-600/20 flex items-center justify-center text-blue-400 text-xs">
              {(session.user?.name || "U")[0].toUpperCase()}
            </div>
            <span className="text-sm text-gray-300 max-w-[100px] truncate hidden sm:block">
              {session.user?.name || "User"}
            </span>
            <span className={`text-xs px-1.5 py-0.5 rounded font-medium hidden sm:block ${roleBadgeColor}`}>
              {roleLabel}
            </span>
            <svg className="w-3 h-3 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {menuOpen && (
            <div className="absolute right-0 top-full mt-1 w-48 bg-[#111827] border border-[#1F2937] rounded-lg shadow-xl z-50 overflow-hidden">
              <div className="px-3 py-2 border-b border-[#1F2937]">
                <p className="text-xs text-gray-500">Signed in as</p>
                <p className="text-sm text-white font-medium truncate">
                  {session.user?.name}
                </p>
              </div>
              <button
                onClick={async () => {
                  const keycloakIssuer = process.env.NEXT_PUBLIC_KEYCLOAK_ISSUER || "http://localhost:8080/realms/patient-risk";
                  await signOut({ redirect: false });
                  window.location.href = `${keycloakIssuer}/protocol/openid-connect/logout?post_logout_redirect_uri=${encodeURIComponent("http://localhost:3000")}&client_id=patient-risk-agent`;
                }}
                className="w-full text-left px-3 py-2 text-sm text-red-400 hover:bg-red-500/10 transition-colors"
              >
                Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <SessionProvider>
          <Nav />
          <main className="pt-14">{children}</main>
        </SessionProvider>
      </body>
    </html>
  );
}
