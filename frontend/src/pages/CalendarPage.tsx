import { useState } from "react";

import { useProperties, useRescheduleTour, useTours } from "../api/hooks";
import type { ApiError } from "../api/client";
import { TourCalendar } from "../features/calendar/TourCalendar";
import { addDays, mondayOf } from "../lib/time";

export function CalendarPage() {
  const [monday, setMonday] = useState(() => mondayOf(new Date().toISOString().slice(0, 10)));
  const properties = useProperties();
  const [propertyId, setPropertyId] = useState<number | undefined>();
  const property = propertyId ?? properties.data?.results[0]?.id;
  // Pad the query range by a day on each side; the grid places tours by local time.
  const range = { start: `${addDays(monday, -1)}T00:00:00Z`, end: `${addDays(monday, 8)}T00:00:00Z`, property };
  const tours = useTours(range);
  const reschedule = useRescheduleTour(range);
  const [error, setError] = useState("");

  return (
    <div className="space-y-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label="Property" className="rounded border px-2 py-1.5 text-sm" value={property ?? ""} onChange={(e) => setPropertyId(Number(e.target.value))}>
          {properties.data?.results.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <button type="button" className="rounded border px-3 py-1 text-sm" onClick={() => setMonday(addDays(monday, -7))}>← Prev week</button>
        <button type="button" className="rounded border px-3 py-1 text-sm" onClick={() => setMonday(mondayOf(new Date().toISOString().slice(0, 10)))}>This week</button>
        <button type="button" className="rounded border px-3 py-1 text-sm" onClick={() => setMonday(addDays(monday, 7))}>Next week →</button>
        <span className="text-sm text-slate-500">Drag a tour to reschedule. Times are the property's local time.</span>
      </div>
      {error && <p role="alert" className="rounded bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>}
      <TourCalendar
        monday={monday}
        tours={tours.data?.results ?? []}
        onReschedule={(tour, start, end) => {
          setError("");
          reschedule.mutate({ id: tour.id, start, end }, {
            onError: (e) => {
              const body = (e as ApiError).body as { start?: string[] } | undefined;
              setError(body?.start?.[0] ?? "Couldn't reschedule that tour.");
            },
          });
        }}
      />
    </div>
  );
}
