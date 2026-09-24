import type { CategoryKind, CompatibilityReport } from "../api/types";
import { useI18n } from "../i18n/context";
import { issueText, issueTitle } from "../i18n/issues";
import { useAnimatedNumber } from "../lib/useAnimatedNumber";
import { CategoryIcon, CheckIcon } from "./icons";

interface Props {
  report: CompatibilityReport | undefined;
  isFetching?: boolean;
  psuWattage?: number;
}

export function CompatibilityPanel({ report, isFetching, psuWattage }: Props) {
  const { t, lang } = useI18n();
  const watts = useAnimatedNumber(report?.estimated_wattage ?? 0);
  const load = psuWattage && report ? (report.estimated_wattage / psuWattage) * 100 : null;
  const animatedLoad = useAnimatedNumber(load ?? 0);
  const unit = lang === "uk" ? "Вт" : "W";

  if (!report) return null;

  const status = !report.is_compatible
    ? { cls: "error", text: t("compat.incompatible") }
    : !report.is_complete
      ? { cls: "info", text: t("compat.incomplete") }
      : report.warnings.length
        ? { cls: "warning", text: t("compat.warnings") }
        : { cls: "ok", text: t("compat.ok") };

  return (
    <section className={`compat compat-${status.cls} ${isFetching ? "stale" : ""}`} aria-live="polite">
      <div className="compat-head">
        <span className={`status-dot ${status.cls}`} aria-hidden="true" />
        <span className={`badge ${status.cls}`}>
          {status.cls === "ok" && <CheckIcon size={13} />} {status.text}
        </span>
      </div>

      <dl className="power">
        <div>
          <dt>{t("compat.load")}</dt>
          <dd>
            {Math.round(watts)} {unit}
          </dd>
        </div>
        <div>
          <dt>{t("compat.recommended")}</dt>
          <dd>
            {report.recommended_psu_wattage ? `${report.recommended_psu_wattage} ${unit}` : "—"}
          </dd>
        </div>
        <div>
          <dt>{t("compat.psuLoad")}</dt>
          <dd>{load !== null ? `${Math.round(animatedLoad)}%` : "—"}</dd>
        </div>
      </dl>
      <div
        className="meter"
        role="meter"
        aria-valuenow={Math.round(load ?? 0)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={t("compat.psuLoad")}
      >
        <div
          className={`meter-fill ${load === null ? "" : load > 100 ? "error" : load > 77 ? "warning" : "ok"}`}
          style={{ width: `${Math.min(load ?? 0, 100)}%` }}
        />
      </div>

      {(report.errors.length > 0 || report.warnings.length > 0) && (
        <ul className="issues">
          {[...report.errors, ...report.warnings].map((issue, i) => (
            <li
              key={issue.code + issue.message}
              className={`issue ${issue.severity}`}
              style={{ "--i": i } as React.CSSProperties}
            >
              <strong>{issueTitle(issue, lang)}</strong>
              {issueText(issue, lang)}
            </li>
          ))}
        </ul>
      )}

      {report.missing.length > 0 && (
        <div className="missing">
          <span className="muted small">{t("compat.missing")}</span>
          <div className="chips">
            {report.missing.map((kind) => (
              <span key={kind} className="chip">
                <CategoryIcon kind={kind as CategoryKind} size={14} />
                {t(`kind.${kind}` as `kind.${CategoryKind}`)}
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
