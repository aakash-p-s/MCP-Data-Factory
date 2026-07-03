import { NextAuthOptions } from "next-auth";
import KeycloakProvider from "next-auth/providers/keycloak";
import type { JWT } from "next-auth/jwt";

async function refreshAccessToken(token: JWT): Promise<JWT> {
  try {
    const issuer = process.env.KEYCLOAK_ISSUER!;
    const res = await fetch(`${issuer}/protocol/openid-connect/token`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        client_id: process.env.KEYCLOAK_CLIENT_ID!,
        client_secret: process.env.KEYCLOAK_CLIENT_SECRET!,
        grant_type: "refresh_token",
        refresh_token: token.refreshToken as string,
      }),
    });
    const refreshed = await res.json();
    if (!res.ok) {
      throw new Error(refreshed.error_description || "Token refresh failed");
    }
    return {
      ...token,
      accessToken: refreshed.access_token,
      accessTokenExpires: Date.now() + refreshed.expires_in * 1000,
      refreshToken: refreshed.refresh_token ?? token.refreshToken,
      error: undefined,
    };
  } catch {
    return { ...token, error: "RefreshAccessTokenError" };
  }
}

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
      if (account) {
        token.accessToken = account.access_token;
        token.idToken = account.id_token;
        token.refreshToken = account.refresh_token;
        token.accessTokenExpires = (account.expires_at ?? 0) * 1000;
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
        return token;
      }

      if (token.accessTokenExpires && Date.now() < token.accessTokenExpires) {
        return token;
      }

      if (token.refreshToken) {
        return refreshAccessToken(token);
      }

      return token;
    },
    async session({ session, token }) {
      session.accessToken = token.accessToken as string;
      session.idToken = token.idToken as string;
      session.groups = (token.groups as string[]) || [];
      session.error = token.error as string | undefined;
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
