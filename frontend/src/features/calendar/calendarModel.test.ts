import type { Tour } from "../../api/types";
import { mondayOf, wallTime, zonedToUtc } from "../../lib/time";
import { SLOTS, rescheduleTarget, tourCell, weekDates } from "./calendarModel";

const tour = (start: string, end: string, timezone = "America/New_York"): Tour => ({
  id: 1, prospect: 1, unit: 1, agent: null, start, end, status: "SCHEDULED", booked_by: "AGENT",
  notes: "", prospect_name: "Ana", unit_number: "204", property_id: 1, property_name: "Maple",
  timezone, agent_name: null,
});

test("week grid is Monday to Saturday, 9:00 to 16:30", () => {
  expect(weekDates("2026-11-02")).toEqual([
    "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-07",
  ]);
  expect(SLOTS[0]).toBe("09:00");
  expect(SLOTS[SLOTS.length - 1]).toBe("16:30");
  expect(mondayOf("2026-11-05")).toBe("2026-11-02");
  expect(mondayOf("2026-11-08")).toBe("2026-11-02"); // Sunday belongs to the prior week
});

test("tours are placed by the property's local time, not UTC", () => {
  // 19:00Z on Nov 4 is 2 PM in New York (EST) and 1 PM in Chicago.
  expect(tourCell(tour("2026-11-04T19:00:00Z", "2026-11-04T19:30:00Z"))).toBe("2026-11-04T14:00");
  expect(tourCell(tour("2026-11-04T19:00:00Z", "2026-11-04T19:30:00Z", "America/Chicago"))).toBe("2026-11-04T13:00");
});

test("dropping keeps the duration and converts the wall time back to UTC", () => {
  const t = tour("2026-11-04T19:00:00Z", "2026-11-04T20:00:00Z"); // 60 minutes
  expect(rescheduleTarget(t, "2026-11-06T09:30")).toEqual({
    start: "2026-11-06T14:30:00.000Z", end: "2026-11-06T15:30:00.000Z",
  });
  expect(rescheduleTarget(t, "not-a-cell")).toBeNull();
});

test("conversion handles the DST change (EDT before Nov 1, EST after)", () => {
  expect(zonedToUtc({ year: 2026, month: 10, day: 30, hour: 10, minute: 0 }, "America/New_York").toISOString())
    .toBe("2026-10-30T14:00:00.000Z");
  expect(zonedToUtc({ year: 2026, month: 11, day: 2, hour: 10, minute: 0 }, "America/New_York").toISOString())
    .toBe("2026-11-02T15:00:00.000Z");
  expect(wallTime("2026-11-02T15:00:00Z", "America/New_York")).toMatchObject({ day: 2, hour: 10, minute: 0 });
});
