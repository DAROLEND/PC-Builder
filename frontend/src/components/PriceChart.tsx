import { useMemo, useState } from "react";

import { usePriceHistory } from "../api/hooks";
import type { MessageKey } from "../i18n/en";
import { useI18n } from "../i18n/context";
import { useMoney } from "../lib/useMoney";
import { Loading } from "./ui";

const PERIODS = [
  { days: 30, label: "part.period.30" },
  { days: 90, label: "part.period.90" },
  { days: 180, label: "part.period.180" },
  { days: 365, label: "part.period.365" },
  { days: 0, label: "part.period.all" },
] as const satisfies readonly { days: number; label: MessageKey }[];

type Point = { at: number; price: number; low: number | null; high: number | null };

const W = 640;
const H = 220;
const PAD = { top: 12, right: 12, bottom: 26, left: 12 };

/**
 * Price history: the source's daily average price as a line, the day's
 * cheapest–dearest offers as a band, with a period switcher and a hover readout.
 * Points come from hotline.ua's own chart where available, otherwise from our
 * daily checks (see backend apps/catalog/price_history.py).
 */
export function PriceChart({ slug }: { slug: string }) {
  const { t, locale } = useI18n();
  const money = useMoney();
  const [days, setDays] = useState<number>(30);
  const [hover, setHover] = useState<number | null>(null);
  const history = usePriceHistory(slug, days || undefined);
  const all = usePriceHistory(slug); // for "tracked since", cached after first load

  const points: Point[] = useMemo(
    () =>
      (history.data ?? []).map((p) => ({
        at: new Date(p.recorded_at).getTime(),
        price: Number(p.price),
        low: p.low_price === null || p.low_price === undefined ? null : Number(p.low_price),
        high: p.high_price === null || p.high_price === undefined ? null : Number(p.high_price),
      })),
    [history.data],
  );
  const since = all.data?.[0]?.recorded_at;
  const thisYear = new Date().getFullYear();
  // The year is shown only when it is not the current one ("3 вер. 2023").
  const day = (at: number | string) => {
    const date = new Date(at);
    return date.toLocaleDateString(locale, {
      day: "numeric",
      month: "short",
      ...(date.getFullYear() !== thisYear ? { year: "numeric" } : {}),
    });
  };

  const switcher = (
    <div className="segmented" role="group" aria-label={t("part.priceHistory")}>
      {PERIODS.map((p) => (
        <button
          key={p.days}
          type="button"
          className={days === p.days ? "active" : ""}
          aria-pressed={days === p.days}
          onClick={() => {
            setDays(p.days);
            setHover(null);
          }}
        >
          {t(p.label)}
        </button>
      ))}
    </div>
  );

  if (history.isLoading) {
    return (
      <>
        {switcher}
        <Loading rows={3} />
      </>
    );
  }
  if (points.length < 2) {
    return (
      <>
        {switcher}
        {points.length === 1 && (
          <p className="price-now">
            <strong>{money.main(points[0].price)}</strong>
            <span className="muted small"> · {day(points[0].at)}</span>
          </p>
        )}
        <p className="muted">
          {since ? t("part.historyFew", { date: day(since) }) : t("part.historyNone")}
        </p>
      </>
    );
  }

  // --- scales (the offer range counts only when it is drawn)
  const banded = points.filter((p) => p.low !== null && p.high !== null);
  const values = points.flatMap((p) =>
    banded.length > 1 ? [p.price, p.low ?? p.price, p.high ?? p.price] : [p.price],
  );
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (max === min) {
    min *= 0.95;
    max *= 1.05;
  }
  const pad = (max - min) * 0.08;
  min -= pad;
  max += pad;
  const t0 = points[0].at;
  const t1 = points[points.length - 1].at;
  const x = (at: number) => PAD.left + ((at - t0) / (t1 - t0 || 1)) * (W - PAD.left - PAD.right);
  const y = (v: number) => PAD.top + (1 - (v - min) / (max - min)) * (H - PAD.top - PAD.bottom);

  const line = points.map((p, i) => `${i ? "L" : "M"}${x(p.at)},${y(p.price)}`).join(" ");
  const band =
    banded.length > 1
      ? `M${banded.map((p) => `${x(p.at)},${y(p.high!)}`).join(" L")} L${[...banded]
          .reverse()
          .map((p) => `${x(p.at)},${y(p.low!)}`)
          .join(" L")} Z`
      : null;

  const prices = points.map((p) => p.price);
  const avg = prices.reduce((a, b) => a + b, 0) / prices.length;
  const change = ((prices[prices.length - 1] - prices[0]) / prices[0]) * 100;
  const active = hover === null ? null : points[hover];

  const onMove = (event: React.MouseEvent<SVGSVGElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const at = t0 + (((event.clientX - box.left) / box.width) * W - PAD.left) /
      (W - PAD.left - PAD.right) * (t1 - t0);
    let best = 0;
    points.forEach((p, i) => {
      if (Math.abs(p.at - at) < Math.abs(points[best].at - at)) best = i;
    });
    setHover(best);
  };

  const ticks = [max - pad, (max + min) / 2, min + pad];

  return (
    <>
      {switcher}
      <dl className="price-stats">
        <div>
          <dt>{t("part.stat.min")}</dt>
          <dd>{money.main(Math.min(...prices))}</dd>
        </div>
        <div>
          <dt>{t("part.stat.avg")}</dt>
          <dd>{money.main(avg)}</dd>
        </div>
        <div>
          <dt>{t("part.stat.max")}</dt>
          <dd>{money.main(Math.max(...prices))}</dd>
        </div>
        <div>
          <dt>{t("part.stat.change")}</dt>
          <dd className={change > 0.05 ? "up" : change < -0.05 ? "down" : ""}>
            {change > 0 ? "+" : ""}
            {change.toFixed(1)}%
          </dd>
        </div>
      </dl>
      <figure className="price-chart">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label={t("part.priceHistory")}
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
        >
          {ticks.map((v) => (
            <g key={v}>
              <line x1={PAD.left} x2={W - PAD.right} y1={y(v)} y2={y(v)} className="grid-line" />
              <text x={W - PAD.right} y={y(v) - 4} textAnchor="end" className="axis-label">
                {money.main(v)}
              </text>
            </g>
          ))}
          {band && <path d={band} className="price-band" />}
          <path d={line} className="price-line" />
          {points.length <= 45 &&
            points.map((p) => (
              <circle key={p.at} cx={x(p.at)} cy={y(p.price)} r={2.6} className="price-dot" />
            ))}
          {active && (
            <g>
              <line
                x1={x(active.at)}
                x2={x(active.at)}
                y1={PAD.top}
                y2={H - PAD.bottom}
                className="hover-line"
              />
              <circle cx={x(active.at)} cy={y(active.price)} r={5} className="hover-dot" />
            </g>
          )}
          <text x={PAD.left} y={H - 6} className="axis-label">
            {day(t0)}
          </text>
          {points.length > 2 && (
            <text x={W / 2} y={H - 6} textAnchor="middle" className="axis-label">
              {day((t0 + t1) / 2)}
            </text>
          )}
          <text x={W - PAD.right} y={H - 6} textAnchor="end" className="axis-label">
            {day(t1)}
          </text>
        </svg>
        {active && (
          <div
            className="chart-tip"
            // Kept inside the chart so it never covers the stats or leaves the card.
            style={{ left: `${Math.min(84, Math.max(16, (x(active.at) / W) * 100))}%` }}
            role="status"
          >
            <strong>{money.main(active.price)}</strong>
            <span>{day(active.at)}</span>
            {active.low !== null && active.high !== null && (
              <span className="muted">
                {money.main(active.low)} – {money.main(active.high)}
              </span>
            )}
          </div>
        )}
        <figcaption className="chart-legend muted small">
          <span className="legend-line" /> {t("part.legend.typical")}
          {band && (
            <>
              <span className="legend-band" /> {t("part.legend.range")}
            </>
          )}
        </figcaption>
      </figure>
      {since && <p className="muted small">{t("part.historySince", { date: day(since) })}</p>}
    </>
  );
}
