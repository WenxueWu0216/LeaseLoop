import { Link, useParams } from "react-router-dom";

import { useProspect, useUpdateProspect } from "../api/hooks";
import type { ProspectStatus } from "../api/types";
import { Badge, humanize } from "../components/Badge";
import { PipelineActions } from "../features/pipeline/PipelineActions";

const STATUSES: ProspectStatus[] = ["NEW", "CONTACTED", "TOUR_SCHEDULED", "TOURED", "APPLIED", "APPROVED", "LEASED", "LOST"];

export function ProspectDetailPage() {
  const id = Number(useParams().id);
  const prospect = useProspect(id);
  const update = useUpdateProspect(id);
  const p = prospect.data;
  if (prospect.isLoading) return <p className="p-6 text-slate-500">Loading…</p>;
  if (!p) return <p className="p-6 text-slate-500">Prospect not found.</p>;

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4">
      <Link to="/prospects" className="text-sm text-sky-700 hover:underline">← Prospects</Link>
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">{`${p.first_name} ${p.last_name}`.trim() || p.email}</h1>
        <label className="text-sm">
          <span className="sr-only">Status</span>
          <select aria-label="Pipeline status" value={p.status} onChange={(e) => update.mutate({ status: e.target.value as ProspectStatus })} className="rounded border px-2 py-1">
            {STATUSES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
          </select>
        </label>
        <Badge>{humanize(p.source)}</Badge>
        {p.has_pets && <Badge tone="amber">pets</Badge>}
      </header>

      <section className="grid grid-cols-2 gap-3 rounded-lg border bg-white p-4 text-sm md:grid-cols-4">
        <div><div className="text-slate-500">Email</div>{p.email || "—"}</div>
        <div><div className="text-slate-500">Phone</div>{p.phone || "—"}</div>
        <div><div className="text-slate-500">Property</div>{p.interested_property?.name ?? "—"}</div>
        <div><div className="text-slate-500">Agent</div>{p.assigned_agent ? `${p.assigned_agent.first_name} ${p.assigned_agent.last_name}` : "Unassigned"}</div>
        <div><div className="text-slate-500">Move-in</div>{p.desired_move_in ?? "—"}</div>
        <div><div className="text-slate-500">Bedrooms</div>{p.beds_min ?? "—"}</div>
        <div><div className="text-slate-500">Budget</div>{p.budget_max ? `$${Math.round(Number(p.budget_max)).toLocaleString()}` : "—"}</div>
        <div><div className="text-slate-500">Last contact</div>{p.last_contacted_at ? new Date(p.last_contacted_at).toLocaleDateString() : "—"}</div>
      </section>

      <PipelineActions prospect={p} />

      <section className="rounded-lg border bg-white p-4" aria-label="Tours">
        <h2 className="mb-2 font-medium">Tours</h2>
        {p.tours.length === 0 ? <p className="text-sm text-slate-500">No tours yet.</p> : (
          <ul className="space-y-1 text-sm">
            {p.tours.map((t) => (
              <li key={t.id}>{new Date(t.start).toLocaleString()} · unit {t.unit_number} · <Badge>{humanize(t.status)}</Badge></li>
            ))}
          </ul>
        )}
      </section>

      <section className="rounded-lg border bg-white p-4">
        <h2 className="mb-2 font-medium">Conversations</h2>
        <ul className="space-y-1 text-sm">
          {p.conversations.map((c) => (
            <li key={c.id}>
              <Link to="/inbox" className="text-sky-700 hover:underline">{c.channel.toLowerCase()}</Link>{" "}
              {c.needs_handoff && <Badge tone="red">handoff</Badge>}
            </li>
          ))}
        </ul>
      </section>

    </div>
  );
}
