import type { Unit } from "../../api/types";

const STATUS_STYLE: Record<Unit["status"], string> = {
  AVAILABLE: "border-emerald-300 bg-emerald-50",
  NOTICE: "border-amber-300 bg-amber-50",
  OCCUPIED: "border-slate-200 bg-slate-100 text-slate-500",
  OFFLINE: "border-rose-200 bg-rose-50 text-rose-700",
};
const LABEL: Record<Unit["status"], string> = {
  AVAILABLE: "Available", NOTICE: "On notice", OCCUPIED: "Occupied", OFFLINE: "Offline",
};

const money = (rent: string) => `$${Math.round(Number(rent)).toLocaleString("en-US")}`;
const beds = (n: number) => (n === 0 ? "Studio" : `${n} bd`);

export function AvailabilityGrid({ units, bedsFilter }: { units: Unit[]; bedsFilter: number | null }) {
  const shown = bedsFilter === null ? units : units.filter((u) => u.beds === bedsFilter);
  const floors = [...new Set(shown.map((u) => u.floor))].sort((a, b) => b - a);
  const counts = Object.fromEntries(
    (Object.keys(LABEL) as Unit["status"][]).map((s) => [s, shown.filter((u) => u.status === s).length]),
  );

  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-3 text-sm" aria-label="Legend">
        {(Object.keys(LABEL) as Unit["status"][]).map((s) => (
          <span key={s} className={`rounded border px-2 py-0.5 ${STATUS_STYLE[s]}`}>
            {LABEL[s]}: {counts[s]}
          </span>
        ))}
      </div>
      {floors.length === 0 && <p className="text-sm text-slate-500">No units match.</p>}
      <div className="space-y-2">
        {floors.map((floor) => (
          <div key={floor} className="flex items-start gap-2">
            <div className="w-14 shrink-0 pt-2 text-xs text-slate-500">Floor {floor}</div>
            <div className="flex flex-wrap gap-1.5">
              {shown
                .filter((u) => u.floor === floor)
                .sort((a, b) => a.number.localeCompare(b.number, undefined, { numeric: true }))
                .map((u) => (
                  <div
                    key={u.id}
                    data-testid={`unit-${u.number}`}
                    title={`${LABEL[u.status]}${u.available_from ? ` from ${u.available_from}` : ""}`}
                    className={`w-24 rounded border p-1.5 text-xs ${STATUS_STYLE[u.status]}`}
                  >
                    <div className="font-semibold">#{u.number}</div>
                    <div>{beds(u.beds)} · {money(u.rent)}</div>
                    {u.status !== "OCCUPIED" && u.available_from && <div className="text-slate-500">{u.available_from}</div>}
                  </div>
                ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
