import { useExchangeRate } from "../api/hooks";
import { useI18n } from "../i18n/context";
import { formatUah, formatUsd } from "./format";

export type Currency = "UAH" | "USD";

/**
 * Prices are stored in USD. Ukrainian users see hryvnias first (NBU rate),
 * English users see dollars first; the other currency is the secondary line.
 * Amounts the user types (budgets, price filters) are in the main currency and
 * go to the API in USD via `toUsd`.
 */
export function useMoney() {
  const { lang, locale } = useI18n();
  const rate = Number(useExchangeRate().data?.rate ?? 0);
  const currency: Currency = lang === "uk" && rate ? "UAH" : "USD";

  const toUah = (usd: string | number) => Math.round(Number(usd) * rate);

  return {
    currency,
    rate,
    symbol: currency === "UAH" ? "₴" : "$",
    main(usd: string | number | null | undefined): string {
      if (usd === null || usd === undefined || usd === "") return "—";
      return currency === "UAH" ? formatUah(toUah(usd), locale) : formatUsd(usd, locale);
    },
    secondary(usd: string | number | null | undefined): string {
      if (usd === null || usd === undefined || usd === "" || !rate) return "";
      return currency === "UAH" ? formatUsd(usd, locale) : formatUah(toUah(usd), "uk-UA");
    },
    /** An amount in the main currency, converted to USD for the API. */
    toUsd(amount: number): number {
      return currency === "UAH" ? Math.round((amount / rate) * 100) / 100 : amount;
    },
    uah: (value: string | number | null | undefined) => formatUah(value, locale),
    usd: (value: string | number | null | undefined) => formatUsd(value, locale),
  };
}
