import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAdvisor } from "../api/hooks";
import type { AdvisorRequest } from "../api/types";
import { CompatibilityPanel } from "../components/CompatibilityPanel";
import { SparkIcon } from "../components/icons";
import { MarketInfo, PartImage } from "../components/PartMedia";
import { ErrorMessage } from "../components/ui";
import { AutoTextarea } from "../components/AutoTextarea";
import { useI18n } from "../i18n/context";
import { specSummary } from "../lib/format";
import { useMoney } from "../lib/useMoney";
import type { Currency } from "../lib/useMoney";

const USE_CASES: AdvisorRequest["use_case"][] = ["gaming", "streaming", "workstation", "office"];
// Same limits as the API ($300–$20 000); the hryvnia step keeps round numbers.
const LIMITS: Record<Currency, { min: number; max: number; step: number; start: number }> = {
  USD: { min: 300, max: 20000, step: 50, start: 2000 },
  UAH: { min: 12000, max: 800000, step: 1000, start: 80000 },
};

export function AdvisorPage() {
  const navigate = useNavigate();
  const { t, lang } = useI18n();
  const money = useMoney();
  const advisor = useAdvisor();
  // Hryvnias for the Ukrainian interface once the NBU rate is known (it loads
  // after the first render), unless the user picked a currency or typed a sum.
  const [chosenCurrency, setCurrency] = useState<Currency | null>(null);
  const [typedBudget, setBudget] = useState<string | null>(null);
  const currency = chosenCurrency ?? money.currency;
  const budget = typedBudget ?? String(LIMITS[currency].start);
  const [useCase, setUseCase] = useState<AdvisorRequest["use_case"]>("gaming");
  const [preferences, setPreferences] = useState("");

  const result = advisor.data;
  const psu = result?.components.find((c) => c.kind === "psu")?.specs.wattage as number | undefined;

  return (
    <div className="advisor">
      <div className="page-title">
        <span className="eyebrow">
          <SparkIcon size={14} /> {t("advisor.eyebrow")}
        </span>
        <h1>{t("advisor.title")}</h1>
        <p className="muted lead">{t("advisor.lead")}</p>
      </div>

      <form
        className="panel advisor-form"
        onSubmit={(e) => {
          e.preventDefault();
          advisor.mutate({ budget, currency, use_case: useCase, preferences, language: lang });
        }}
      >
        <label>
          {t("advisor.budget")}
          <span className="input-with-unit">
            <input
              type="number"
              min={LIMITS[currency].min}
              max={LIMITS[currency].max}
              step={LIMITS[currency].step}
              value={budget}
              onChange={(e) => setBudget(e.target.value)}
              required
            />
            {money.rate > 0 && (
              <span className="segmented small" role="group" aria-label={t("advisor.currency")}>
                {(["UAH", "USD"] as const).map((cur) => (
                  <button
                    key={cur}
                    type="button"
                    className={currency === cur ? "active" : ""}
                    aria-pressed={currency === cur}
                    onClick={() => {
                      if (cur === currency) return;
                      const amount = Number(budget) || 0;
                      const converted = cur === "UAH" ? amount * money.rate : amount / money.rate;
                      const step = LIMITS[cur].step;
                      setBudget(String(Math.max(LIMITS[cur].min, Math.round(converted / step) * step)));
                      setCurrency(cur);
                    }}
                  >
                    {cur === "UAH" ? "₴" : "$"}
                  </button>
                ))}
              </span>
            )}
          </span>
        </label>
        <label>
          {t("advisor.use")}
          <select value={useCase} onChange={(e) => setUseCase(e.target.value as typeof useCase)}>
            {USE_CASES.map((u) => (
              <option key={u} value={u}>
                {t(`advisor.use.${u}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="wide">
          {t("advisor.prefs")}
          <AutoTextarea
            rows={2}
            maxLength={1000}
            placeholder={t("advisor.prefsPlaceholder")}
            value={preferences}
            onChange={(e) => setPreferences(e.target.value)}
          />
        </label>
        <button type="submit" disabled={advisor.isPending}>
          {advisor.isPending ? (
            <>
              <span className="thinking" aria-hidden="true">
                <i />
                <i />
                <i />
              </span>
              {t("advisor.thinking")}
            </>
          ) : (
            <>
              <SparkIcon size={16} /> {t("advisor.submit")}
            </>
          )}
        </button>
      </form>
      <ErrorMessage error={advisor.error} />

      {result && (
        <section className="two-col advisor-result">
          <div>
            <div className="page-head">
              <h2>{t("advisor.result", { total: money.main(result.total_price) })}</h2>
              <span className="badge info">
                {result.source === "claude"
                  ? t("advisor.sourceClaude", { model: result.model })
                  : t("advisor.sourceRules")}
              </span>
            </div>
            <p className="summary-text">{result.summary}</p>
            {result.notes.length > 0 && (
              <ul className="notes">
                {result.notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            )}
            <div className="part-rows">
              {result.components.map((c, i) => (
                <div key={c.id} className="part-row" style={{ "--i": i } as React.CSSProperties}>
                  <PartImage src={c.image} kind={c.kind} alt={c.name} />
                  <div className="part-row-body">
                    <span className="tag">{t(`kind.${c.kind}`)}</span>
                    <div className="part-name">
                      {c.manufacturer} {c.name}
                    </div>
                    <div className="specs">{specSummary(c.kind, c.specs, lang).join(" · ")}</div>
                    <MarketInfo market={c.market} compact />
                  </div>
                  <div className="part-row-price">
                    <strong className="price">{money.main(c.price)}</strong>
                    <span className="muted small">{money.secondary(c.price)}</span>
                  </div>
                </div>
              ))}
            </div>
            <button
              onClick={() => navigate("/configurator", { state: { preset: result.components } })}
            >
              {t("advisor.open")}
            </button>
          </div>
          <aside>
            <CompatibilityPanel report={result.compatibility} psuWattage={psu} />
          </aside>
        </section>
      )}
    </div>
  );
}
