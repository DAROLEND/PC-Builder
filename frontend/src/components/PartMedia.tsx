import { useState } from "react";

import type { CategoryKind, Component, ComponentBrief } from "../api/types";
import { useI18n } from "../i18n/context";
import { formatDate } from "../lib/format";
import { useMoney } from "../lib/useMoney";
import { CategoryIcon } from "./icons";

type Market = ComponentBrief["market"];

/**
 * Product photo: our own WebP copy under /media once mirrored, the source URL
 * until then (loaded without a Referer). The category icon is the placeholder
 * while loading and the fallback when there is no photo or it fails to load.
 */
type ImageProps = {
  src: string | null | undefined;
  kind: CategoryKind;
  alt: string;
  size?: "sm" | "md" | "lg" | "xl";
};

// Remount when the photo changes, so the loading state starts over.
export function PartImage(props: ImageProps) {
  return <PartImageInner key={props.src ?? "none"} {...props} />;
}

function PartImageInner({
  src,
  kind,
  alt,
  size = "md",
}: ImageProps) {
  const [state, setState] = useState<"loading" | "ok" | "failed">(src ? "loading" : "failed");
  return (
    <div className={`part-image ${size} ${state}`}>
      {state !== "ok" && (
        <span className="part-image-fallback">
          <CategoryIcon kind={kind} size={size === "sm" ? 18 : size === "xl" ? 56 : 30} />
        </span>
      )}
      {src && state !== "failed" && (
        <img
          src={src}
          alt={alt}
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          onLoad={() => setState("ok")}
          onError={() => setState("failed")}
        />
      )}
    </div>
  );
}

/** "from 19 299 ₴ · 67 offers · In stock", linking to the source page. */
export function MarketInfo({ market, compact = false }: { market: Market; compact?: boolean }) {
  const { t, locale } = useI18n();
  const money = useMoney();
  if (!market) return null;

  const fmt = (value: string) => (market.currency === "USD" ? money.usd(value) : money.uah(value));
  const low = market.low_price ? fmt(market.low_price) : null;
  const high = market.high_price && market.high_price !== market.low_price ? fmt(market.high_price) : null;
  const price = !low
    ? null
    : !compact && high
      ? t("market.range", { low, high })
      : t("market.from", { price: low });
  const stock =
    market.status === "no_offers"
      ? { cls: "none", text: t("market.noOffers") }
      : market.in_stock === false
        ? { cls: "out", text: t("market.outOfStock") }
        : { cls: "in", text: t("market.inStock") };

  return (
    <div className={`market ${compact ? "compact" : ""}`}>
      <span className={`stock-dot ${stock.cls}`} title={stock.text} />
      {price && <span className="market-price">{price}</span>}
      {market.offer_count ? (
        <span className="muted">· {t("market.offers", { count: market.offer_count })}</span>
      ) : null}
      {!compact && (
        <>
          <span className="muted">· {stock.text}</span>
          <a
            className="market-source"
            href={market.url}
            target="_blank"
            rel="noopener noreferrer"
            title={
              market.checked_at
                ? t("market.updated", { date: formatDate(market.checked_at, locale) })
                : undefined
            }
          >
            {t("market.source", { source: market.source })} ↗
          </a>
        </>
      )}
    </div>
  );
}

/** Most popular parts of a category get a "hit" badge, like the aggregator's top list. */
export const HIT_RANK = 3;
/** Price moves smaller than this are day-to-day noise, not news. */
const DROP_PERCENT = -3;

type Signals = Pick<Component, "popularity_rank" | "price_change_30d" | "at_year_low">;

/** "Хіт №1", "−8% за місяць", "Мінімум за рік" — computed on the server from market data. */
export function MarketBadges({ part, kind }: { part: Signals; kind: CategoryKind }) {
  const { t, locale } = useI18n();
  const change = part.price_change_30d === null ? null : Number(part.price_change_30d);
  const percent = (v: number) =>
    new Intl.NumberFormat(locale, { maximumFractionDigits: 0, signDisplay: "always" })
      .format(v)
      .replace("-", "−");
  return (
    <>
      {part.popularity_rank !== null && part.popularity_rank <= HIT_RANK && (
        <span
          className="tag badge-hit"
          title={t("badge.hitHint", { rank: part.popularity_rank, kind: t(`kinds.${kind}`) })}
        >
          {t("badge.hit", { rank: part.popularity_rank })}
        </span>
      )}
      {change !== null && change <= DROP_PERCENT && (
        <span className="tag badge-drop" title={t("badge.dropHint", { value: percent(change) })}>
          {t("badge.drop", { value: percent(change) })}
        </span>
      )}
      {part.at_year_low && (
        <span className="tag badge-low" title={t("badge.yearLowHint")}>
          {t("badge.yearLow")}
        </span>
      )}
    </>
  );
}
