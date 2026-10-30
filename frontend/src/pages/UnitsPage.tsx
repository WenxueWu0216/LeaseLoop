import { useState } from "react";

import { useProperties, useUnits } from "../api/hooks";
import { AvailabilityGrid } from "../features/units/AvailabilityGrid";

export function UnitsPage() {
  const properties = useProperties();
  const [propertyId, setPropertyId] = useState<number | undefined>();
  const property = propertyId ?? properties.data?.results[0]?.id;
  const units = useUnits(property);
  const [beds, setBeds] = useState<number | null>(null);

  return (
    <div className="space-y-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label="Property" className="rounded border px-2 py-1.5 text-sm" value={property ?? ""} onChange={(e) => setPropertyId(Number(e.target.value))}>
          {properties.data?.results.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <select aria-label="Bedrooms" className="rounded border px-2 py-1.5 text-sm" value={beds ?? ""} onChange={(e) => setBeds(e.target.value === "" ? null : Number(e.target.value))}>
          <option value="">All bedrooms</option>
          <option value="0">Studio</option><option value="1">1 bed</option><option value="2">2 bed</option><option value="3">3 bed</option>
        </select>
      </div>
      {units.isLoading ? <p className="text-sm text-slate-500">Loading…</p> : <AvailabilityGrid units={units.data ?? []} bedsFilter={beds} />}
    </div>
  );
}
