import { useState } from "react";
import { Link } from "react-router-dom";

import { useBuilds } from "../api/hooks";
import { useAuth } from "../auth/useAuth";
import { Empty, ErrorMessage, SkeletonGrid } from "../components/ui";
import { useI18n } from "../i18n/context";
import { formatDate } from "../lib/format";
import { useMoney } from "../lib/useMoney";

export function BuildsPage() {
  const { user } = useAuth();
  const { t, locale } = useI18n();
  const money = useMoney();
  const [tab, setTab] = useState<"public" | "mine">("public");
  const [ordering, setOrdering] = useState("-updated_at");
  const [search, setSearch] = useState("");

  const builds = useBuilds({
    ordering,
    search: search || undefined,
    ...(tab === "mine" ? { mine: true } : { is_public: true }),
  });

  return (
    <div>
      <div className="page-head">
        <div className="page-title">
          <span className="eyebrow">{t("builds.eyebrow")}</span>
          <h1>{t("builds.title")}</h1>
        </div>
        <Link to="/configurator" className="button">
          {t("builds.new")}
        </Link>
      </div>

      <div className="filters">
        <div className="tabs" role="tablist">
          <button
            role="tab"
            aria-selected={tab === "public"}
            className={tab === "public" ? "tab active" : "tab"}
            onClick={() => setTab("public")}
          >
            {t("builds.community")}
          </button>
          {user && (
            <button
              role="tab"
              aria-selected={tab === "mine"}
              className={tab === "mine" ? "tab active" : "tab"}
              onClick={() => setTab("mine")}
            >
              {t("builds.mine")}
            </button>
          )}
        </div>
        <input
          type="search"
          placeholder={t("builds.search")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select value={ordering} onChange={(e) => setOrdering(e.target.value)} aria-label="Sort">
          <option value="-updated_at">{t("builds.sort.updated")}</option>
          <option value="total_price">{t("builds.sort.cheap")}</option>
          <option value="-total_price">{t("builds.sort.expensive")}</option>
        </select>
      </div>

      <ErrorMessage error={builds.error} />
      {builds.isLoading ? (
        <SkeletonGrid />
      ) : !builds.data?.results.length ? (
        <Empty>{tab === "mine" ? t("builds.emptyMine") : t("builds.emptyPublic")}</Empty>
      ) : (
        <div className="grid">
          {builds.data.results.map((b, i) => (
            <Link
              key={b.id}
              to={`/builds/${b.id}`}
              className="card card-link build-card"
              style={{ "--i": i } as React.CSSProperties}
            >
              <h3>{b.name}</h3>
              {b.description && <p className="muted clamp">{b.description}</p>}
              <div className="muted small">
                {t("common.by", { user: b.owner })} ·{" "}
                {t("common.parts", { count: b.parts_count })} ·{" "}
                {t("builds.comments.count", { count: b.comments_count })}
                {!b.is_public && ` · ${t("common.private")}`}
              </div>
              <div className="card-price">
                <strong>{money.main(b.total_price)}</strong>
                <span className="muted small">{formatDate(b.updated_at, locale)}</span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
