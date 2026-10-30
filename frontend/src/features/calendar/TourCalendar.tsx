import {
  DndContext, type DragEndEvent, KeyboardSensor, PointerSensor, useDraggable, useDroppable,
  useSensor, useSensors,
} from "@dnd-kit/core";

import type { Tour } from "../../api/types";
import { formatTime } from "../../lib/time";
import { SLOTS, cellId, rescheduleTarget, tourCell, weekDates } from "./calendarModel";

type Props = {
  monday: string;
  tours: Tour[];
  onReschedule: (tour: Tour, start: string, end: string) => void;
};

function TourCard({ tour }: { tour: Tour }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: tour.id, data: { tour },
  });
  const style = transform ? { transform: `translate(${transform.x}px, ${transform.y}px)` } : undefined;
  return (
    <div
      ref={setNodeRef}
      style={style}
      {...listeners}
      {...attributes}
      data-testid={`tour-${tour.id}`}
      className={`cursor-grab rounded border px-1.5 py-1 text-xs shadow-sm ${
        tour.booked_by === "ASSISTANT" ? "border-violet-300 bg-violet-50" : "border-sky-300 bg-sky-50"
      } ${isDragging ? "z-10 opacity-80 ring-2 ring-sky-400" : ""}`}
    >
      <div className="truncate font-medium">{tour.prospect_name || "Prospect"}</div>
      <div className="truncate text-slate-500">
        Unit {tour.unit_number}
        {tour.booked_by === "ASSISTANT" && <span className="ml-1 text-violet-600">· assistant</span>}
      </div>
    </div>
  );
}

function Cell({ id, children }: { id: string; children?: React.ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id });
  return (
    <td
      ref={setNodeRef}
      data-testid={`cell-${id}`}
      className={`h-12 min-w-28 border border-slate-100 p-0.5 align-top ${isOver ? "bg-sky-100" : ""}`}
    >
      <div className="flex flex-col gap-0.5">{children}</div>
    </td>
  );
}

export function TourCalendar({ monday, tours, onReschedule }: Props) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor),
  );
  const days = weekDates(monday);
  const byCell = new Map<string, Tour[]>();
  for (const t of tours) {
    const key = tourCell(t);
    byCell.set(key, [...(byCell.get(key) ?? []), t]);
  }

  function handleDragEnd(e: DragEndEvent) {
    const tour = e.active.data.current?.tour as Tour | undefined;
    if (!tour || !e.over || e.over.id === tourCell(tour)) return;
    const target = rescheduleTarget(tour, String(e.over.id));
    if (target) onReschedule(tour, target.start, target.end);
  }

  return (
    <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
      <div className="overflow-x-auto rounded-lg border bg-white">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr>
              <th scope="col" className="w-16"><span className="sr-only">Time</span></th>
              {days.map((d) => (
                <th key={d} scope="col" className="border-b px-2 py-2 text-left font-medium text-slate-600">
                  {new Date(`${d}T12:00:00Z`).toLocaleDateString("en-US", {
                    weekday: "short", month: "short", day: "numeric", timeZone: "UTC",
                  })}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {SLOTS.map((slot) => (
              <tr key={slot}>
                <th scope="row" className="pr-2 text-right align-top text-xs font-normal text-slate-400">
                  {formatTime(slot)}
                </th>
                {days.map((d) => {
                  const id = cellId(d, slot);
                  return (
                    <Cell key={id} id={id}>
                      {(byCell.get(id) ?? []).map((t) => <TourCard key={t.id} tour={t} />)}
                    </Cell>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </DndContext>
  );
}
