import { useState } from "react";
import { Link } from "react-router-dom";

import { useCategories, useComponents } from "../api/hooks";
import type { CategoryKind } from "../api/types";
import { CategoryIcon } from "../components/icons";
import { MarketBadges, MarketInfo, PartImage } from "../components/PartMedia";
import { Empty, ErrorMessage, SkeletonGrid } from "../components/ui";
import { useI18n } from "../i18n/context";
import { specSummary } from "../lib/format";
import { useMoney } from "../lib/useMoney";

export function CatalogPage() {
  const { t, lang } = useI18n();
  const money = useMoney();
  const categories = useCategories();
  const [category, setCategory] = useState<CategoryKind | "">("");
  const [search, setSearch] = useState("");
  const [maxPrice, setMaxPrice] = useState("");
  // Like the aggregator: what people actually buy first, not the cheapest no-name.
  const [ordering, setOrdering] = useState("-popularity");
  const [buildableOnly, setBuildableOnly] = useState(false);
  const [page, setPage] = useState(1);

  const components = useComponents({
    category: category || undefined,
    search: search || undefined,
    max_price: maxPrice ? money.toUsd(Number(maxPrice)) : undefined,
    ordering,
    buildable: buildableOnly || undefined,
    page,
  });

  const resetPage =
    <T,>(setter: (v: T) => void) =>
    (v: T) => {
      setter(v);
      setPage(1);
    };

  const pageCount = components.data ? Math.max(1, Math.ceil(components.data.count / 20)) : 1;

  return (
    <div>
      <div className="page-title">
        <span className="eyebrow">
          {components.data ? t("catalog.count", { count: components.data.count }) : "…"}
        </span>
        <h1>{t("catalog.title")}</h1>
      </div>
      <div className="category-pills" role="tablist" aria-label="Category">
        <button
          role="tab"
          aria-selected={category === ""}
          className={`pill ${category === "" ? "active" : ""}`}
          onClick={() => resetPage(setCategory)("")}
        >
          {t("catalog.all")}
        </button>
        {categories.data?.map((c) => (
          <button
            key={c.kind}
            role="tab"
            aria-selected={category === c.kind}
            className={`pill ${category === c.kind ? "active" : ""}`}
            onClick={() => resetPage(setCategory)(c.kind)}
          >
            <CategoryIcon kind={c.kind} size={16} />
            {t(`kinds.${c.kind}`)}
          </button>
        ))}
      </div>
      <div className="filters">
        <input
          type="search"
          placeholder={t("catalog.search")}
          value={search}
          onChange={(e) => resetPage(setSearch)(e.target.value)}
        />
        <input
          type="number"
          min={0}
          placeholder={t("catalog.maxPrice", { symbol: money.symbol })}
          value={maxPrice}
          onChange={(e) => resetPage(setMaxPrice)(e.target.value)}
        />
        <select value={ordering} onChange={(e) => setOrdering(e.target.value)} aria-label="Sort">
          <option value="-popularity">{t("catalog.sort.popular")}</option>
          <option value="price_change_30d">{t("catalog.sort.drops")}</option>
          <option value="price">{t("catalog.sort.cheap")}</option>
          <option value="-price">{t("catalog.sort.expensive")}</option>
          <option value="name">{t("catalog.sort.name")}</option>
          <option value="-updated_at">{t("catalog.sort.updated")}</option>
        </select>
        <label className="check">
          <input
            type="checkbox"
            checked={buildableOnly}
            onChange={(e) => resetPage(setBuildableOnly)(e.target.checked)}
          />
          {t("catalog.buildableOnly")}
        </label>
      </div>

      <ErrorMessage error={components.error} />
      {components.isLoading ? (
        <SkeletonGrid />
      ) : !components.data?.results.length ? (
        <Empty>{t("catalog.empty")}</Empty>
      ) : (
        <>
          <div className="grid">
            {components.data.results.map((c, i) => (
              <article
                key={c.id}
                className="card part-card"
                style={{ "--i": i } as React.CSSProperties}
              >
                <PartImage src={c.image} kind={c.category.kind} alt={c.name} size="lg" />
                <div className="card-top">
                  <span className="tag">{t(`kind.${c.category.kind}`)}</span>
                  <MarketBadges part={c} kind={c.category.kind} />
                  {!c.specs_complete && (
                    <span className="tag tag-muted" title={t("catalog.catalogOnlyHint")}>
                      {t("catalog.catalogOnly")}
                    </span>
                  )}
                </div>
                <span className="muted small card-brand">{c.manufacturer.name}</span>
                <h3>
                  {/* Stretched link: the whole card opens the part page. */}
                  <Link to={`/catalog/${c.slug}`} className="stretched-link">
                    {c.name}
                  </Link>
                </h3>
                <ul className="spec-list">
                  {specSummary(c.category.kind, c.specs, lang).map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ul>
                <div className="card-price">
                  <strong>{money.main(c.price)}</strong>
                  <span className="muted small">{money.secondary(c.price)}</span>
                </div>
                <MarketInfo market={c.market} compact />
                {c.market && (
                  <a
                    className="card-source"
                    href={c.market.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {t("market.source", { source: c.market.source })} ↗
                  </a>
                )}
              </article>
            ))}
          </div>
          <div className="pager">
            <button
              className="secondary small"
              disabled={page <= 1}
              onClick={() => setPage(page - 1)}
            >
              {t("common.prev")}
            </button>
            <span className="muted">{t("common.page", { page, pages: pageCount })}</span>
            <button
              className="secondary small"
              disabled={!components.data.next}
              onClick={() => setPage(page + 1)}
            >
              {t("common.next")}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
