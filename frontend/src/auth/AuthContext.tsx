import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useState } from "react";

import { api, session } from "../api/client";
import { useMe } from "../api/hooks";
import type { Me } from "../api/types";

type Auth = {
  me: Me | undefined;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient();
  const [token, setToken] = useState(session.token);
  const me = useMe(Boolean(token));

  async function login(email: string, password: string) {
    const { token: t } = await api<{ token: string }>("/auth/login/", {
      method: "POST", json: { username: email, password },
    });
    session.token = t;
    const profile = await api<Me>("/auth/me/");
    // Users in several orgs work in their first one; the header picks it on every call.
    session.org = profile.memberships.length > 1 ? String(profile.memberships[0].organization.id) : null;
    qc.setQueryData(["me"], profile);
    setToken(t);
  }

  function logout() {
    session.token = null;
    session.org = null;
    qc.clear();
    setToken(null);
  }

  return (
    <AuthContext.Provider value={{ me: me.data, loading: Boolean(token) && me.isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): Auth {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
