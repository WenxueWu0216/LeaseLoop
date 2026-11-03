/** Wall-clock helpers for a named IANA timezone (tours are shown in the property's zone). */

export type WallTime = { year: number; month: number; day: number; hour: number; minute: number };

const formatters = new Map<string, Intl.DateTimeFormat>();

function formatter(tz: string): Intl.DateTimeFormat {
  let f = formatters.get(tz);
  if (!f) {
    f = new Intl.DateTimeFormat("en-US", {
      timeZone: tz, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit",
    });
    formatters.set(tz, f);
  }
  return f;
}

export function wallTime(instant: string | Date, tz: string): WallTime {
  const parts = Object.fromEntries(
    formatter(tz).formatToParts(new Date(instant)).map((p) => [p.type, p.value]),
  );
  return {
    year: Number(parts.year), month: Number(parts.month), day: Number(parts.day),
    hour: Number(parts.hour), minute: Number(parts.minute),
  };
}

function offsetMs(utcMs: number, tz: string): number {
  const w = wallTime(new Date(utcMs), tz);
  return Date.UTC(w.year, w.month - 1, w.day, w.hour, w.minute) - utcMs;
}

/** UTC instant for a wall-clock time in `tz` (handles DST by re-checking the offset). */
export function zonedToUtc(w: WallTime, tz: string): Date {
  const guess = Date.UTC(w.year, w.month - 1, w.day, w.hour, w.minute);
  let utc = guess - offsetMs(guess, tz);
  utc = guess - offsetMs(utc, tz);
  return new Date(utc);
}

export const isoDate = (w: Pick<WallTime, "year" | "month" | "day">) =>
  `${w.year}-${String(w.month).padStart(2, "0")}-${String(w.day).padStart(2, "0")}`;

export const hhmm = (w: Pick<WallTime, "hour" | "minute">) =>
  `${String(w.hour).padStart(2, "0")}:${String(w.minute).padStart(2, "0")}`;

export function addDays(date: string, days: number): string {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** Monday of the week containing `date` (YYYY-MM-DD). */
export function mondayOf(date: string): string {
  const d = new Date(`${date}T00:00:00Z`);
  return addDays(date, -((d.getUTCDay() + 6) % 7));
}

export function formatTime(t: string) {
  const [h, m] = t.split(":").map(Number);
  return `${((h + 11) % 12) + 1}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
}

export function relative(iso: string | null): string {
  if (!iso) return "";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  if (mins < 1440) return `${Math.round(mins / 60)}h`;
  return `${Math.round(mins / 1440)}d`;
}
