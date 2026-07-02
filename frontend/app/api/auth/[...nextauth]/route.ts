import NextAuth, { NextAuthOptions } from "next-auth";
import KeycloakProvider from "next-auth/providers/keycloak";

/**
 * app/api/auth/[...nextauth]/route.ts
 *
 * NextAuth handler wired to Keycloak OIDC.
 * Stores the raw access_token in the session so every page can attach it
 * as `Authorization: Bearer` to agent and registry-api calls.
 *
 * The access token contains the groups[] and scp claims the backend expects:
 *   groups: ["grp-physician"|"grp-clinical-viewer"|"grp-case-manager"]
 *   scp: "mcp.vitals.read mcp.labs.read ..."
 */
export const authOptions: NextAuthOptions = {
  providers: [
    KeycloakProvider({
      clientId: process.env.KEYCLOAK_CLIENT_ID!,
      clientSecret: process.env.KEYCLOAK_CLIENT_SECRET!,
      issuer: process.env.KEYCLOAK_ISSUER!,
      authorization: {
        params: {
          scope: "openid",
        },
      },
    }),
  ],
  callbacks: {
    async jwt({ token, account }) {
      // Persist the access_token from Keycloak into the JWT on first sign-in
      if (account) {
        token.accessToken = account.access_token;
        token.idToken = account.id_token;
        token.refreshToken = account.refresh_token;
        // Decode groups from the access token
        if (account.access_token) {
          try {
            const payload = JSON.parse(
              Buffer.from(account.access_token.split(".")[1], "base64").toString()
            );
            token.groups = payload.groups || [];
            token.name = payload.name || payload.preferred_username;
            token.sub = payload.sub;
          } catch {
            token.groups = [];
          }
        }
      }
      return token;
    },
    async session({ session, token }) {
      // Expose the access token and groups in the session object
      session.accessToken = token.accessToken as string;
      session.idToken = token.idToken as string;
      session.groups = (token.groups as string[]) || [];
      session.user = {
        ...session.user,
        name: token.name as string,
        id: token.sub as string,
      };
      return session;
    },
  },
  events: {
    async signOut({ token }: { token: Record<string, unknown> }) {
      // End the Keycloak SSO session so the login form shows on next sign-in
      const idToken = token.idToken as string | undefined;
      if (idToken && process.env.KEYCLOAK_ISSUER) {
        const params = new URLSearchParams({
          id_token_hint: idToken,
          post_logout_redirect_uri: process.env.NEXTAUTH_URL || "http://localhost:3000",
        });
        await fetch(
          `${process.env.KEYCLOAK_ISSUER}/protocol/openid-connect/logout?${params}`,
          { method: "GET" }
        ).catch(() => {});
      }
    },
  },
  pages: {
    signIn: "/",
  },
  session: {
    strategy: "jwt",
  },
};

const handler = NextAuth(authOptions);
export { handler as GET, handler as POST };
