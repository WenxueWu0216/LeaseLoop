import { useState } from "react";
import { Navigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";

export function LoginPage() {
  const { me, login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (me) return <Navigate to="/inbox" replace />;

  return (
    <div className="flex min-h-screen items-center justify-center">
      <form
        className="w-80 space-y-3 rounded-lg border bg-white p-6 shadow-sm"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError("");
          try {
            await login(email, password);
          } catch {
            setError("Email or password is incorrect.");
          } finally {
            setBusy(false);
          }
        }}
      >
        <h1 className="text-lg font-semibold">Sign in to LeaseLoop</h1>
        <label className="block text-sm">
          Email
          <input className="mt-1 w-full rounded border px-2 py-1.5" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label className="block text-sm">
          Password
          <input className="mt-1 w-full rounded border px-2 py-1.5" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </label>
        {error && <p role="alert" className="text-sm text-rose-600">{error}</p>}
        <button type="submit" disabled={busy} className="w-full rounded bg-sky-600 py-2 text-sm font-medium text-white disabled:opacity-50">
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <p className="text-xs text-slate-500">Demo: manager@org1.demo / demo1234!</p>
      </form>
    </div>
  );
}
