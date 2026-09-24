import { Link } from "react-router-dom";

import { useBuild, useBuilds } from "../api/hooks";
import type { CategoryKind } from "../api/types";
import { CategoryIcon, CheckIcon, SparkIcon } from "../components/icons";
import { PartImage } from "../components/PartMedia";
import { useI18n } from "../i18n/context";
import type { MessageKey } from "../i18n/en";
import { useMoney } from "../lib/useMoney";

const RULES: CategoryKind[] = ["cpu", "ram", "case", "psu", "storage", "gpu"];

/** The hero card shows a real public build from the API, not a mock-up. */
function HeroBuild() {
  const { t, lang } = useI18n();
  const money = useMoney();
  const list = useBuilds({ is_public: true, search: "1440p high refresh", page_size: 1 });
  const build = useBuild(list.data?.results[0]?.id);
  const b = build.data;
  const ok = b?.compatibility.is_compatible && b.compatibility.is_complete;
  const psu = b?.items.find((i) => i.component.kind === "psu")?.component.specs.wattage as
    | number
    | undefined;
  const load = b && psu ? Math.round((b.compatibility.estimated_wattage / psu) * 100) : 70;
  const unit = lang === "uk" ? "Вт" : "W";

  return (
    <div className="demo-build">
      <div className="demo-head">
        <div>
          <div className="muted small">{b?.name ?? t("home.demoTitle")}</div>
          <strong className="demo-total">{b ? money.main(b.total_price) : "…"}</strong>
        </div>
        {ok && (
          <span className="badge ok demo-badge">
            <CheckIcon size={13} /> {t("home.demoOk")}
          </span>
        )}
      </div>
      <ul>
        {(b?.items ?? []).slice(0, 6).map((item, i) => (
          <li key={item.id} style={{ "--i": i } as React.CSSProperties}>
            <PartImage
              src={item.component.image}
              kind={item.component.kind}
              alt={item.component.name}
              size="sm"
            />
            <span className="demo-name">
              {item.component.manufacturer} {item.component.name}
              <span className="muted small">{t(`kind.${item.component.kind}`)}</span>
            </span>
            <span className="demo-check">
              <CheckIcon size={13} />
            </span>
          </li>
        ))}
        {!b &&
          Array.from({ length: 6 }, (_, i) => (
            <li key={i} className="demo-skeleton">
              <span className="skeleton" style={{ width: "70%" }} />
            </li>
          ))}
      </ul>
      <div className="demo-meter">
        <span className="muted small">
          {t("compat.psuLoad")} ·{" "}
          {b ? `${b.compatibility.estimated_wattage} ${unit} / ${psu ?? "—"} ${unit}` : "…"}
        </span>
        <div className="meter">
          <div className="meter-fill ok demo-fill" style={{ "--to": `${load}%` } as React.CSSProperties} />
        </div>
      </div>
    </div>
  );
}

export function HomePage() {
  const { t } = useI18n();
  const money = useMoney();
  const builds = useBuilds({ is_public: true, ordering: "total_price", page_size: 3 });

  return (
    <div className="home">
      <section className="hero">
        <div className="hero-copy">
          <span className="eyebrow">
            <SparkIcon size={14} /> {t("home.eyebrow")}
          </span>
          <h1>
            {t("home.title1")} <span className="accent-text">{t("home.title2")}</span>
          </h1>
          <p>{t("home.lead")}</p>
          <div className="actions">
            <Link to="/configurator" className="button large">
              {t("home.start")} →
            </Link>
            <Link to="/advisor" className="button secondary large">
              <SparkIcon size={16} /> {t("home.askAi")}
            </Link>
          </div>
          <dl className="hero-stats">
            <div>
              <dt>{t("home.statRules")}</dt>
              <dd>13</dd>
            </div>
            <div>
              <dt>{t("home.statParts")}</dt>
              <dd>65</dd>
            </div>
            <div>
              <dt>{t("home.statSource")}</dt>
              <dd>hotline.ua</dd>
            </div>
          </dl>
        </div>

        <div className="hero-visual">
          <HeroBuild />
        </div>
      </section>

      <section>
        <div className="section-head">
          <span className="eyebrow">{t("home.checksEyebrow")}</span>
          <h2>{t("home.checksTitle")}</h2>
        </div>
        <div className="grid">
          {RULES.map((kind, i) => (
            <div key={kind} className="card feature" style={{ "--i": i } as React.CSSProperties}>
              <span className="slot-icon large">
                <CategoryIcon kind={kind} size={24} />
              </span>
              <h3>{t(`home.rule.${kind}.title` as MessageKey)}</h3>
              <p className="muted">{t(`home.rule.${kind}.text` as MessageKey)}</p>
            </div>
          ))}
        </div>
      </section>

      {builds.data?.results.length ? (
        <section>
          <div className="section-head">
            <span className="eyebrow">{t("home.communityEyebrow")}</span>
            <h2>{t("home.communityTitle")}</h2>
          </div>
          <div className="grid">
            {builds.data.results.map((b, i) => (
              <Link
                key={b.id}
                to={`/builds/${b.id}`}
                className="card card-link build-card"
                style={{ "--i": i } as React.CSSProperties}
              >
                <h3>{b.name}</h3>
                <p className="muted clamp">{b.description}</p>
                <div className="card-price">
                  <strong>{money.main(b.total_price)}</strong>
                  <span className="muted small">{t("common.parts", { count: b.parts_count })} →</span>
                </div>
              </Link>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
