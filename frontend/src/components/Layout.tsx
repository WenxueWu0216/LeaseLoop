import { NavLink, Navigate, Outlet } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";

const LINKS = [
  ["/inbox", "Inbox"],
  ["/prospects", "Prospects"],
  ["/calendar", "Tours"],
  ["/units", "Availability"],
] as const;

export function Layout() {
  const { me, loading, logout } = useAuth();
  if (loading) return <p className="p-6 text-slate-500">Loading…</p>;
  if (!me) return <Navigate to="/login" replace />;
  const membership = me.memberships[0];
  return (
    <div className="flex h-screen flex-col">
      <nav className="flex items-center gap-1 border-b bg-white px-4 py-2">
        <span className="mr-4 font-bold text-sky-700">LeaseLoop</span>
        {LINKS.map(([to, label]) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `rounded px-3 py-1.5 text-sm ${isActive ? "bg-sky-100 text-sky-800" : "text-slate-600 hover:bg-slate-100"}`
            }
          >
            {label}
          </NavLink>
        ))}
        <span className="ml-auto text-sm text-slate-500">
          {membership?.organization.name} · {membership?.role === "PROPERTY_MANAGER" ? "Manager" : "Agent"}
        </span>
        <button type="button" onClick={logout} className="ml-3 text-sm text-slate-600 hover:underline">
          Sign out
        </button>
      </nav>
      <main className="min-h-0 flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
