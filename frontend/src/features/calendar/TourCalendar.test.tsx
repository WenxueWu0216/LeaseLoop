import { act, renderHook, screen, waitFor, within, render } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";

import { useRescheduleTour } from "../../api/hooks";
import type { Paginated, Tour } from "../../api/types";
import { mockFetch, newQueryClient } from "../../test/render";
import { TourCalendar } from "./TourCalendar";

const base: Tour = {
  id: 7, prospect: 3, unit: 9, agent: null, start: "2026-11-04T19:00:00Z", end: "2026-11-04T19:30:00Z",
  status: "SCHEDULED", booked_by: "ASSISTANT", notes: "", prospect_name: "Dana Cruz", unit_number: "204",
  property_id: 1, property_name: "Maple Court", timezone: "America/New_York", agent_name: null,
};

test("renders each tour in its local-time cell with booking source", () => {
  render(<TourCalendar monday="2026-11-02" tours={[base]} onReschedule={jest.fn()} />);
  const cell = screen.getByTestId("cell-2026-11-04T14:00");
  expect(within(cell).getByText("Dana Cruz")).toBeInTheDocument();
  expect(within(cell).getByText(/assistant/)).toBeInTheDocument();
  expect(screen.getAllByRole("columnheader")).toHaveLength(7); // time column + Mon..Sat
  expect(screen.getAllByRole("rowheader")).toHaveLength(16); // 9:00..16:30
});

describe("optimistic reschedule", () => {
  const range = { start: "2026-11-01T00:00:00Z", end: "2026-11-10T00:00:00Z", property: 1 };
  const page: Paginated<Tour> = { count: 1, next: null, previous: null, results: [base] };
  const moved = { id: 7, start: "2026-11-06T14:30:00.000Z", end: "2026-11-06T15:00:00.000Z" };

  function setup(status: number) {
    const client = newQueryClient();
    client.setQueryData(["tours", range], page);
    const calls = mockFetch([
      { method: "PATCH", path: "/api/tours/7/", status, body: status === 200 ? { ...base, ...moved } : { start: ["Another tour of this unit overlaps that time."] } },
      { path: /\/api\/tours\/\?/, body: status === 200 ? { ...page, results: [{ ...base, ...moved }] } : page },
    ]);
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useRescheduleTour(range), { wrapper });
    return { client, calls, result };
  }

  test("moves the tour in the cache before the server answers", async () => {
    const { client, calls, result } = setup(200);
    act(() => result.current.mutate(moved));
    await waitFor(() =>
      expect(client.getQueryData<Paginated<Tour>>(["tours", range])?.results[0].start).toBe(moved.start),
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(calls[0]).toMatchObject({ method: "PATCH", body: { start: moved.start, end: moved.end } });
  });

  test("rolls back when the server rejects the new time", async () => {
    const { client, result } = setup(400);
    act(() => result.current.mutate(moved));
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(client.getQueryData<Paginated<Tour>>(["tours", range])?.results[0].start).toBe(base.start);
  });
});
