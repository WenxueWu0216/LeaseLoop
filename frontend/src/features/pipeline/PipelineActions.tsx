import { useState } from "react";

import { usePipeline, useProperties, useUnits } from "../../api/hooks";
import type { ProspectDetail } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { Badge, humanize } from "../../components/Badge";
import { zonedToUtc } from "../../lib/time";

/** Tour scheduling and the application → lease → signature steps for one prospect. */
export function PipelineActions({ prospect }: { prospect: ProspectDetail }) {
  const { me } = useAuth();
  const isManager = me?.memberships[0]?.role === "PROPERTY_MANAGER";
  const properties = useProperties();
  const propertyId = prospect.interested_property?.id ?? properties.data?.results[0]?.id;
  const property = properties.data?.results.find((p) => p.id === propertyId);
  const units = useUnits(propertyId);
  const open = (units.data ?? []).filter((u) => u.status === "AVAILABLE" || u.status === "NOTICE");
  const actions = usePipeline(prospect.id);
  const [unit, setUnit] = useState<number | "">("");
  const [when, setWhen] = useState("");
  const [leaseStart, setLeaseStart] = useState("");
  const [term, setTerm] = useState(12);
  const [error, setError] = useState("");

  const onError = (e: unknown) => {
    const body = (e as { body?: Record<string, string[]> }).body;
    setError(body ? Object.values(body).flat().join(" ") : "Something went wrong.");
  };

  function scheduleTour(e: React.FormEvent) {
    e.preventDefault();
    if (!unit || !when || !property) return;
    const [date, time] = when.split("T");
    const [y, m, d] = date.split("-").map(Number);
    const [h, min] = time.split(":").map(Number);
    const start = zonedToUtc({ year: y, month: m, day: d, hour: h, minute: min }, property.timezone);
    const end = new Date(start.getTime() + 30 * 60_000);
    setError("");
    actions.scheduleTour.mutate({ unit, start: start.toISOString(), end: end.toISOString() }, { onError });
  }

  const unitLabel = (id: number) => open.find((u) => u.id === id)?.number ?? String(id);

  return (
    <section className="space-y-3 rounded-lg border bg-white p-4" aria-label="Pipeline actions">
      <h2 className="font-medium">Next steps</h2>
      {error && <p role="alert" className="rounded bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>}

      <form onSubmit={scheduleTour} className="flex flex-wrap items-end gap-2 text-sm">
        <label>
          Unit
          <select aria-label="Unit" className="ml-1 rounded border px-2 py-1" value={unit} onChange={(e) => setUnit(Number(e.target.value) || "")}>
            <option value="">Choose…</option>
            {open.map((u) => <option key={u.id} value={u.id}>#{u.number} · {u.beds === 0 ? "studio" : `${u.beds} bd`} · ${Math.round(Number(u.rent))}</option>)}
          </select>
        </label>
        <label>
          Tour time ({property?.timezone ?? "local"})
          <input aria-label="Tour time" type="datetime-local" step={1800} className="ml-1 rounded border px-2 py-1" value={when} onChange={(e) => setWhen(e.target.value)} />
        </label>
        <button type="submit" disabled={!unit || !when} className="rounded bg-sky-600 px-3 py-1.5 font-medium text-white disabled:opacity-50">Schedule tour</button>
        <button
          type="button"
          disabled={!unit}
          onClick={() => unit && actions.startApplication.mutate(unit, { onError })}
          className="rounded border border-sky-600 px-3 py-1.5 font-medium text-sky-700 disabled:opacity-50"
        >
          Start application
        </button>
      </form>

      {prospect.applications.map((a) => {
        const lease = prospect.leases.find((l) => l.application === a.id);
        return (
          <div key={a.id} className="flex flex-wrap items-center gap-2 border-t pt-3 text-sm" data-testid={`application-${a.id}`}>
            <span>Application · unit {unitLabel(a.unit)}</span>
            <Badge tone={a.status === "APPROVED" ? "green" : "sky"}>{humanize(a.status)}</Badge>
            {a.status === "DRAFT" && (
              <button type="button" className="rounded border px-2 py-1" onClick={() => actions.applicationAction.mutate({ id: a.id, action: "submit" }, { onError })}>Submit application</button>
            )}
            {a.status === "SUBMITTED" && isManager && (
              <button type="button" className="rounded border px-2 py-1" onClick={() => actions.applicationAction.mutate({ id: a.id, action: "approve" }, { onError })}>Approve</button>
            )}
            {a.status === "APPROVED" && !lease && (
              <span className="flex items-center gap-1">
                <input aria-label="Lease start" type="date" className="rounded border px-2 py-1" value={leaseStart} onChange={(e) => setLeaseStart(e.target.value)} />
                <select aria-label="Lease term" className="rounded border px-2 py-1" value={term} onChange={(e) => setTerm(Number(e.target.value))}>
                  {[6, 9, 12, 13, 15].map((t) => <option key={t} value={t}>{t} months</option>)}
                </select>
                <button type="button" disabled={!leaseStart} className="rounded border px-2 py-1 disabled:opacity-50" onClick={() => actions.createLease.mutate({ application: a.id, start_date: leaseStart, term_months: term }, { onError })}>Create lease</button>
              </span>
            )}
            {lease && (
              <span className="flex items-center gap-2">
                Lease {lease.start_date} → {lease.end_date} · ${Math.round(Number(lease.monthly_rent)).toLocaleString()}/mo
                <Badge tone={lease.status === "SIGNED" ? "green" : "amber"}>{humanize(lease.status)}</Badge>
                {lease.status !== "SIGNED" && (
                  <button type="button" className="rounded bg-emerald-600 px-2 py-1 text-white" onClick={() => actions.signLease.mutate(lease.id, { onError })}>Mark lease signed</button>
                )}
              </span>
            )}
          </div>
        );
      })}
    </section>
  );
}
