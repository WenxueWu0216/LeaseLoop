import { useState } from "react";
import { Link } from "react-router-dom";

import { type ProspectFilters, useProspects } from "../api/hooks";
import { Badge, humanize } from "../components/Badge";

const STATUSES = ["", "NEW", "CONTACTED", "TOUR_SCHEDULED", "TOURED", "APPLIED", "APPROVED", "LEASED", "LOST"];
const SOURCES = ["", "WEBSITE", "EMAIL", "SMS", "CHAT", "ZILLOW", "APARTMENTS_COM", "WALK_IN", "REFERRAL"];

export function ProspectsPage() {
  const [filters, setFilters] = useState<ProspectFilters>({ page: 1 });
  const [search, setSearch] = useState("");
  const prospects = useProspects(filters);
  const data = prospects.data;
  const set = (patch: Partial<ProspectFilters>) => setFilters((f) => ({ ...f, ...patch, page: patch.page ?? 1 }));

  return (
    <div className="p-4">
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <form onSubmit={(e) => { e.preventDefault(); set({ q: search }); }}>
          <input aria-label="Search prospects" placeholder="Name, email or phone" className="rounded border px-2 py-1.5 text-sm" value={search} onChange={(e) => setSearch(e.target.value)} />
        </form>
        <select aria-label="Status" className="rounded border px-2 py-1.5 text-sm" value={filters.status ?? ""} onChange={(e) => set({ status: e.target.value })}>
          {STATUSES.map((s) => <option key={s} value={s}>{s ? humanize(s) : "Any status"}</option>)}
        </select>
        <select aria-label="Source" className="rounded border px-2 py-1.5 text-sm" value={filters.source ?? ""} onChange={(e) => set({ source: e.target.value })}>
          {SOURCES.map((s) => <option key={s} value={s}>{s ? humanize(s) : "Any source"}</option>)}
        </select>
        <label className="flex items-center gap-1 text-sm">
          <input type="checkbox" checked={Boolean(filters.unassigned)} onChange={(e) => set({ unassigned: e.target.checked || undefined })} />
          Unassigned only
        </label>
        <span className="ml-auto text-sm text-slate-500">{data ? `${data.count.toLocaleString()} prospects` : ""}</span>
      </div>

      <div className="overflow-x-auto rounded-lg border bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-slate-600">
            <tr>
              <th className="px-3 py-2">Name</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Source</th>
              <th className="px-3 py-2">Agent</th><th className="px-3 py-2">Property</th><th className="px-3 py-2">Next tour</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {data?.results.map((p) => (
              <tr key={p.id} className="hover:bg-slate-50">
                <td className="px-3 py-2">
                  <Link to={`/prospects/${p.id}`} className="font-medium text-sky-700 hover:underline">
                    {`${p.first_name} ${p.last_name}`.trim() || p.email || p.phone}
                  </Link>
                </td>
                <td className="px-3 py-2"><Badge tone="sky">{humanize(p.status)}</Badge></td>
                <td className="px-3 py-2 text-slate-600">{humanize(p.source)}</td>
                <td className="px-3 py-2 text-slate-600">{p.assigned_agent ? `${p.assigned_agent.first_name} ${p.assigned_agent.last_name}` : <Badge tone="amber">unassigned</Badge>}</td>
                <td className="px-3 py-2 text-slate-600">{p.interested_property?.name ?? "—"}</td>
                <td className="px-3 py-2 text-slate-600">{p.next_tour ? `${new Date(p.next_tour.start).toLocaleString()} · #${p.next_tour.unit_number}` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex items-center gap-2 text-sm">
        <button type="button" disabled={!data?.previous} onClick={() => set({ page: (filters.page ?? 1) - 1 })} className="rounded border px-3 py-1 disabled:opacity-40">Previous</button>
        <span>Page {filters.page ?? 1}</span>
        <button type="button" disabled={!data?.next} onClick={() => set({ page: (filters.page ?? 1) + 1 })} className="rounded border px-3 py-1 disabled:opacity-40">Next</button>
      </div>
    </div>
  );
}
