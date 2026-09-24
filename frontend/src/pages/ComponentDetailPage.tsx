import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useComponent } from "../api/hooks";
import type { CategoryKind } from "../api/types";
import { MarketBadges, MarketInfo, PartImage } from "../components/PartMedia";
import { PriceChart } from "../components/PriceChart";
import { WatchButton } from "../components/WatchButton";
import { ErrorMessage, Loading } from "../components/ui";
import { useI18n } from "../i18n/context";
import { formatDate, specLabel, specRows } from "../lib/format";
import { fromComponent } from "../lib/picked";
import { useMoney } from "../lib/useMoney";

export function ComponentDetailPage() {
  const { slug } = useParams();
  const { t, lang, locale } = useI18n();
  const money = useMoney();
  const navigate = useNavigate();
  const component = useComponent(slug);

  if (component.isLoading) return <Loading />;
  if (!component.data) return <ErrorMessage error={component.error} />;
  const c = component.data;
  const rows = specRows(c.category.kind, c.specs, lang);

  return (
    <div className="part-page">
      <Link to="/catalog" className="back-link">
        {t("part.back")}
      </Link>

      <div className="part-hero">
        <Gallery
          images={c.images.length ? c.images : c.image ? [c.image] : []}
          kind={c.category.kind}
          alt={c.name}
        />

        <div className="part-summary">
          <div className="card-top">
            <span className="tag">{t(`kind.${c.category.kind}`)}</span>
            <MarketBadges part={c} kind={c.category.kind} />
            {!c.specs_complete && (
              <span className="tag tag-muted" title={t("catalog.catalogOnlyHint")}>
                {t("catalog.catalogOnly")}
              </span>
            )}
          </div>
          <p className="muted part-brand">
            {c.manufacturer.name}
            {c.popularity_rank !== null && (
              <span className="part-rank">
                {" · "}
                {t("part.popularity", {
                  rank: c.popularity_rank,
                  kind: t(`kinds.${c.category.kind}`).toLowerCase(),
                })}
              </span>
            )}
          </p>
          <h1>{c.name}</h1>

          <div className="part-price">
            <strong>{money.main(c.price)}</strong>
            <span className="muted">{money.secondary(c.price)}</span>
          </div>
          {c.market?.median_price && (
            <p className="muted small typical-note" title={t("part.typicalHint")}>
              {t("part.typicalPrice", { count: c.market.offer_count ?? 0 })} ⓘ
            </p>
          )}
          <MarketInfo market={c.market} />

          {!c.listed && (
            <p className="notice warn">{t("part.fewShops", { count: c.shop_count ?? 0 })}</p>
          )}
          {!c.specs_complete && <p className="notice">{t("part.catalogOnlyText")}</p>}
          <div className="part-actions">
            {c.specs_complete && (
              <button
                className="large"
                onClick={() => navigate("/configurator", { state: { parts: [fromComponent(c)] } })}
              >
                {t("part.startBuild")}
              </button>
            )}
            <WatchButton component={c.id} />
          </div>

          <dl className="part-meta">
            <dt>{t("part.manufacturer")}</dt>
            <dd>{c.manufacturer.name}</dd>
            <dt>{t("part.sku")}</dt>
            <dd className="mono">{c.sku}</dd>
          </dl>
        </div>
      </div>

      <div className="part-columns">
        <section className="panel">
          <h3>{t("part.specs")}</h3>
          {rows.length > 0 && (
            <table className="spec-table">
              <tbody>
                {rows.map(([label, value]) => (
                  <tr key={label}>
                    <th scope="row">{label}</th>
                    <td>{value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {c.missing_specs.length > 0 && (
            <p className="muted small">
              {t("part.missing", {
                fields: c.missing_specs.map((key) => specLabel(key, lang)).join(", "),
              })}
            </p>
          )}
        </section>

        <section className="panel">
          <h3>{t("part.priceHistory")}</h3>
          <PriceChart slug={c.slug} />
          {c.market?.checked_at && (
            <p className="muted small">
              {t("market.updated", { date: formatDate(c.market.checked_at, locale) })}
            </p>
          )}
        </section>
      </div>
    </div>
  );
}

function Gallery({ images, kind, alt }: { images: string[]; kind: CategoryKind; alt: string }) {
  const { t } = useI18n();
  const [index, setIndex] = useState(0);
  const current = images[index] ?? null;

  return (
    <div className="gallery">
      <PartImage src={current} kind={kind} alt={alt} size="xl" />
      {images.length > 1 && (
        <div className="gallery-thumbs">
          {images.map((src, i) => (
            <button
              key={src}
              type="button"
              className={`gallery-thumb ${i === index ? "active" : ""}`}
              aria-label={t("part.photo", { n: i + 1 })}
              aria-pressed={i === index}
              onClick={() => setIndex(i)}
            >
              <PartImage src={src} kind={kind} alt="" size="sm" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
