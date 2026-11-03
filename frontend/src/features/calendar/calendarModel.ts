import type { Tour } from "../../api/types";
import { addDays, hhmm, isoDate, wallTime, zonedToUtc } from "../../lib/time";

export const DAYS = 6; // Monday to Saturday; the office is closed on Sundays
export const SLOTS = Array.from({ length: 16 }, (_, i) => {
  const minutes = 9 * 60 + i * 30; // 9:00 to 16:30
  return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
});

export const cellId = (date: string, slot: string) => `${date}T${slot}`;

export function weekDates(monday: string): string[] {
  return Array.from({ length: DAYS }, (_, i) => addDays(monday, i));
}

/** Calendar cell a tour starts in, in the property's timezone. */
export function tourCell(tour: Tour): string {
  const w = wallTime(tour.start, tour.timezone);
  return cellId(isoDate(w), hhmm(w));
}

/** New UTC start/end when `tour` is dropped on `cell`, keeping its duration. */
export function rescheduleTarget(tour: Tour, cell: string): { start: string; end: string } | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(cell);
  if (!m) return null;
  const [, y, mo, d, h, mi] = m.map(Number);
  const start = zonedToUtc({ year: y, month: mo, day: d, hour: h, minute: mi }, tour.timezone);
  const duration = new Date(tour.end).getTime() - new Date(tour.start).getTime();
  return { start: start.toISOString(), end: new Date(start.getTime() + duration).toISOString() };
}
