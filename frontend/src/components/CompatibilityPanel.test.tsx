import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CompatibilityReport } from "../api/types";
import { renderWithProviders } from "../test/render";
import { CompatibilityPanel } from "./CompatibilityPanel";

const base: CompatibilityReport = {
  is_compatible: true,
  is_complete: true,
  errors: [],
  warnings: [],
  missing: [],
  estimated_wattage: 400,
  recommended_psu_wattage: 550,
};

const socketError = {
  code: "CPU_SOCKET_MISMATCH",
  severity: "error" as const,
  message: "English fallback",
  component_ids: [1, 2],
  params: { cpu: "Ryzen 7 9800X3D", cpu_socket: "AM5", board: "B450M Pro4", board_socket: "AM4" },
};

describe("CompatibilityPanel", () => {
  it("renders issues from code + params in English", () => {
    renderWithProviders(<CompatibilityPanel report={{ ...base, is_compatible: false, errors: [socketError] }} />);
    expect(screen.getByText("Incompatible")).toBeInTheDocument();
    expect(
      screen.getByText("Ryzen 7 9800X3D uses socket AM5, but B450M Pro4 has socket AM4."),
    ).toBeInTheDocument();
  });

  it("renders the same issue in Ukrainian", () => {
    renderWithProviders(
      <CompatibilityPanel report={{ ...base, is_compatible: false, errors: [socketError] }} />,
      "uk",
    );
    expect(screen.getByText("Несумісна")).toBeInTheDocument();
    expect(screen.getByText("НЕ ТОЙ СОКЕТ")).toBeInTheDocument();
    expect(screen.getByText("Ryzen 7 9800X3D має сокет AM5, а B450M Pro4 — AM4.")).toBeInTheDocument();
  });

  it("falls back to the server message for unknown codes", () => {
    const unknown = { ...socketError, code: "SOMETHING_NEW", message: "Server says hi" };
    renderWithProviders(<CompatibilityPanel report={{ ...base, warnings: [{ ...unknown, severity: "warning" }] }} />);
    expect(screen.getByText("Server says hi")).toBeInTheDocument();
  });

  it("lists missing parts with localised labels", () => {
    renderWithProviders(<CompatibilityPanel report={{ ...base, is_complete: false, missing: ["psu", "ram"] }} />, "uk");
    expect(screen.getByText("Блок живлення")).toBeInTheDocument();
    expect(screen.getByText("Пам'ять")).toBeInTheDocument();
  });

  it("computes PSU load against the selected PSU", () => {
    renderWithProviders(<CompatibilityPanel report={base} psuWattage={800} />);
    expect(screen.getByText("50%")).toBeInTheDocument();
  });
});
