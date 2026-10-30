import { render, screen, within } from "@testing-library/react";

import type { Unit } from "../../api/types";
import { AvailabilityGrid } from "./AvailabilityGrid";

const unit = (number: string, floor: number, beds: number, status: Unit["status"], available_from: string | null = null): Unit => ({
  id: Number(number), property: 1, property_name: "Maple", number, floor, beds, baths: "1.0", sqft: 700,
  rent: "1725.00", available_from, status,
});

const units = [
  unit("101", 1, 0, "AVAILABLE", "2026-11-02"),
  unit("102", 1, 1, "OCCUPIED"),
  unit("203", 2, 1, "NOTICE", "2026-12-01"),
  unit("204", 2, 2, "OFFLINE"),
];

test("legend counts each status and floors are listed top-down", () => {
  render(<AvailabilityGrid units={units} bedsFilter={null} />);
  const legend = screen.getByLabelText("Legend");
  expect(legend).toHaveTextContent("Available: 1");
  expect(legend).toHaveTextContent("On notice: 1");
  expect(legend).toHaveTextContent("Occupied: 1");
  expect(legend).toHaveTextContent("Offline: 1");
  const floors = screen.getAllByText(/^Floor \d$/).map((el) => el.textContent);
  expect(floors).toEqual(["Floor 2", "Floor 1"]);
});

test("cards show rent and move-in date, hiding dates for occupied units", () => {
  render(<AvailabilityGrid units={units} bedsFilter={null} />);
  const studio = screen.getByTestId("unit-101");
  expect(within(studio).getByText("Studio · $1,725")).toBeInTheDocument();
  expect(within(studio).getByText("2026-11-02")).toBeInTheDocument();
  expect(screen.getByTestId("unit-102")).not.toHaveTextContent("2026");
});

test("bedroom filter narrows units and counts", () => {
  render(<AvailabilityGrid units={units} bedsFilter={1} />);
  expect(screen.queryByTestId("unit-101")).not.toBeInTheDocument();
  expect(screen.getByTestId("unit-203")).toBeInTheDocument();
  expect(screen.getByLabelText("Legend")).toHaveTextContent("Available: 0");
});

test("empty state", () => {
  render(<AvailabilityGrid units={units} bedsFilter={3} />);
  expect(screen.getByText("No units match.")).toBeInTheDocument();
});
