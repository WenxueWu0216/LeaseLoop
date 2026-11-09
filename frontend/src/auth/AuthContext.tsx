import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useState } from "react";

import { api, refreshAccess, session } from "../api/client";
import { useMe } from "../api/hooks";
import type { Me } from "../api/types";

type Status = "checking" | "signed-out" | "signed-in";

type Auth = {
  me: Me | undefined;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient();
  const [status, setStatus] = useState<Status>("checking");
  const me = useMe(status === "signed-in");

  useEffect(() => {
    // The access token doesn't survive a reload; the refresh cookie restores the session.
    let live = true;
    refreshAccess().then((ok) => live && setStatus(ok ? "signed-in" : "signed-out"));
    const stop = session.onExpired(() => {
      qc.clear();
      setStatus("signed-out");
    });
    return () => {
      live = false;
      stop();
    };
  }, [qc]);

  async function login(email: string, password: string) {
    const { access } = await api<{ access: string }>("/auth/login/", {
      method: "POST", json: { email, password },
    });
    session.access = access;
    const profile = await api<Me>("/auth/me/");
    // Users in several orgs work in their first one; the header picks it on every call.
    session.org = profile.memberships.length > 1 ? String(profile.memberships[0].organization.id) : null;
    qc.setQueryData(["me"], profile);
    setStatus("signed-in");
  }

  async function logout() {
    try {
      await api("/auth/logout/", { method: "POST" }); // revokes the refresh token server-side
    } finally {
      session.access = null;
      session.org = null;
      qc.clear();
      setStatus("signed-out");
    }
  }

  const loading = status === "checking" || (status === "signed-in" && me.isLoading);
  return <AuthContext.Provider value={{ me: me.data, loading, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): Auth {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
