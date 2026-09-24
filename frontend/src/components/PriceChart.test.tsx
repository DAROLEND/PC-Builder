import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "../test/render";
import { PriceChart } from "./PriceChart";

// Three days of USD history; the exchange rate is not loaded, so amounts show in USD.
const history = [
  { price: "100.00", low_price: "90.00", high_price: "130.00", source: "hotline.ua", recorded_at: "2026-09-01T10:00:00Z" },
  { price: "120.00", low_price: "95.00", high_price: "150.00", source: "hotline.ua", recorded_at: "2026-09-02T10:00:00Z" },
  { price: "110.00", low_price: "92.00", high_price: "140.00", source: "hotline.ua", recorded_at: "2026-09-03T10:00:00Z" },
];
const calls: (number | undefined)[] = [];

vi.mock("../api/hooks", () => ({
  usePriceHistory: (_slug: string, days?: number) => {
    calls.push(days);
    return { data: history, isLoading: false };
  },
  useExchangeRate: () => ({ data: null }),
}));

describe("PriceChart", () => {
  afterEach(cleanup);

  it("shows period stats and a readout on hover", () => {
    renderWithProviders(<PriceChart slug="x" />);
    expect(screen.getByText("Lowest").nextSibling).toHaveTextContent("$100.00");
    expect(screen.getByText("Average").nextSibling).toHaveTextContent("$110.00");
    expect(screen.getByText("Highest").nextSibling).toHaveTextContent("$120.00");
    expect(screen.getByText("Change").nextSibling).toHaveTextContent("+10.0%");
    expect(screen.getByText(/cheapest – dearest offer/)).toBeInTheDocument();

    const svg = screen.getByRole("img", { name: "Price history" });
    svg.getBoundingClientRect = () => ({ left: 0, width: 640, top: 0, height: 220 }) as DOMRect;
    fireEvent.mouseMove(svg, { clientX: 320 }); // the middle day
    expect(screen.getByRole("status")).toHaveTextContent("$120.00");
    expect(screen.getByRole("status")).toHaveTextContent("$95.00 – $150.00");
  });

  it("requests the chosen period", () => {
    renderWithProviders(<PriceChart slug="x" />);
    expect(calls).toContain(30); // default: last 30 days
    fireEvent.click(screen.getByRole("button", { name: "6 months" }));
    expect(calls).toContain(180);
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(calls.at(-2)).toBeUndefined(); // "All" = no limit
  });
});
