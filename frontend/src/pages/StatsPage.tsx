import { useState } from "react";

import {
  useCategories,
  useCategoryStats,
  usePopularComponents,
  usePricePosition,
  useTopPerCategory,
} from "../api/hooks";
import type { CategoryKind } from "../api/types";
import { ErrorMessage, Loading } from "../components/ui";
import { useI18n } from "../i18n/context";
import { useMoney } from "../lib/useMoney";

export function StatsPage() {
  const { t } = useI18n();
  const money = useMoney();
  const stats = useCategoryStats();
  const popular = usePopularComponents(10);
  const top = useTopPerCategory(3);
  const categories = useCategories();
  const [kind, setKind] = useState<CategoryKind>("gpu");
  const ladder = usePricePosition(kind);

  const maxBuilds = Math.max(1, ...(popular.data?.map((p) => p.build_count) ?? [1]));

  return (
    <div className="stats">
      <div className="page-title">
        <span className="eyebrow">{t("stats.eyebrow")}</span>
        <h1>{t("stats.title")}</h1>
        <p className="muted lead">{t("stats.lead")}</p>
      </div>

      <section>
        <h2>{t("stats.byCategory")}</h2>
        {stats.isLoading ? (
          <Loading />
        ) : (
          <table className="parts">
            <thead>
              <tr>
                <th>{t("stats.category")}</th>
                <th className="num">{t("stats.items")}</th>
                <th className="num">{t("stats.min")}</th>
                <th className="num">{t("stats.avg")}</th>
                <th className="num">{t("stats.max")}</th>
              </tr>
            </thead>
            <tbody>
              {stats.data?.map((row) => (
                <tr key={row.kind}>
                  <td>{t(`kinds.${row.kind as CategoryKind}`)}</td>
                  <td className="num">{row.components}</td>
                  <td className="num">{money.main(row.min_price)}</td>
                  <td className="num">{money.main(row.avg_price)}</td>
                  <td className="num">{money.main(row.max_price)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <ErrorMessage error={stats.error} />
      </section>

      <div className="two-col even">
        <section>
          <h2>{t("stats.top10")}</h2>
          <ol className="bars">
            {popular.data?.map((p) => (
              <li key={p.id}>
                <span className="bar-label">
                  {p.manufacturer} {p.name}
                </span>
                <span className="bar-track">
                  <span className="bar" style={{ width: `${(p.build_count / maxBuilds) * 100}%` }} />
                </span>
                <span className="bar-value">{p.build_count}</span>
              </li>
            ))}
          </ol>
        </section>

        <section>
          <h2>{t("stats.top3")}</h2>
          <table className="parts compact">
            <tbody>
              {top.data?.map((p) => (
                <tr key={p.id}>
                  <td className="muted small">{t(`kind.${p.kind as CategoryKind}`)}</td>
                  <td>#{p.rank}</td>
                  <td>
                    {p.manufacturer} {p.name}
                  </td>
                  <td className="num">{p.build_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>

      <section>
        <div className="page-head">
          <h2>{t("stats.ladder")}</h2>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as CategoryKind)}
            aria-label={t("stats.category")}
          >
            {categories.data?.map((c) => (
              <option key={c.kind} value={c.kind}>
                {t(`kinds.${c.kind}`)}
              </option>
            ))}
          </select>
        </div>
        <table className="parts compact">
          <thead>
            <tr>
              <th>{t("stats.rank")}</th>
              <th>{t("stats.component")}</th>
              <th className="num">{t("common.price")}</th>
              <th className="num">{t("stats.percentile")}</th>
            </tr>
          </thead>
          <tbody>
            {ladder.data?.map((row) => (
              <tr key={row.id}>
                <td>{row.price_rank}</td>
                <td>{row.name}</td>
                <td className="num">{money.main(row.price)}</td>
                <td className="num">{Math.round(row.percentile * 100)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
