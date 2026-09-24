import { describe, expect, it } from "vitest";

import { en } from "../i18n/en";
import { uk } from "../i18n/uk";
import { formatUah, formatUsd, specRows, specSummary, sumMoney } from "./format";

describe("money", () => {
  it("sums decimal strings without float drift", () => {
    expect(sumMoney(["0.10", "0.20"])).toBe("0.30");
    expect(sumMoney(["19.99", "0.01", "100.00"])).toBe("120.00");
  });

  it("formats USD and UAH and handles empty values", () => {
    expect(formatUsd("1234.5")).toBe("$1,234.50");
    expect(formatUsd(null)).toBe("—");
    expect(formatUah(19299).replace(/\s/g, " ")).toBe("19 299 ₴");
  });
});

describe("specSummary", () => {
  it("localises labels and values", () => {
    expect(specSummary("cooler", { type: "air", height_mm: 155 }, "uk")).toEqual([
      "Тип: повітряний",
      "Висота, мм: 155",
    ]);
    expect(specSummary("case", { supported_form_factors: ["ATX", "Mini-ITX"] }, "en")).toEqual([
      "Boards: ATX/Mini-ITX",
    ]);
  });
});

describe("specRows", () => {
  it("lists every spec in a stable order with labels, then unknown keys", () => {
    const rows = specRows(
      "gpu",
      { tdp_w: 250, chipset: "GeForce RTX 5070", vram_gb: 12, vendor_note: "x" },
      "uk",
    );
    expect(rows).toEqual([
      ["Чипсет", "GeForce RTX 5070"],
      ["Відеопам'ять, ГБ", "12"],
      ["TDP, Вт", "250"],
      ["vendor_note", "x"],
    ]);
  });

  it("joins lists and translates booleans", () => {
    expect(specRows("cpu", { memory_types: ["DDR4", "DDR5"], integrated_graphics: false })).toEqual([
      ["Integrated graphics", "no"],
      ["Memory types", "DDR4, DDR5"],
    ]);
  });
});

describe("dictionaries", () => {
  it("have the same keys and no empty strings", () => {
    expect(Object.keys(uk).sort()).toEqual(Object.keys(en).sort());
    expect(Object.values(uk).every(Boolean)).toBe(true);
  });
});

describe("plural", () => {
  it("picks Ukrainian and English forms", async () => {
    const { plural } = await import("../i18n/context");
    const uk = "{count} пропозиція|{count} пропозиції|{count} пропозицій";
    expect([1, 3, 5, 11, 21, 22].map((n) => plural(uk, n, "uk"))).toEqual([
      "{count} пропозиція",
      "{count} пропозиції",
      "{count} пропозицій",
      "{count} пропозицій",
      "{count} пропозиція",
      "{count} пропозиції",
    ]);
    expect(plural("{count} offer|{count} offers", 1, "en")).toBe("{count} offer");
    expect(plural("{count} offer|{count} offers", 2, "en")).toBe("{count} offers");
  });
});
