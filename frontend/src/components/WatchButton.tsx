import { useState } from "react";
import { Link } from "react-router-dom";

import { useDeleteWatch, useSaveWatch, useTelegram, useWatches } from "../api/hooks";
import { useAuth } from "../auth/useAuth";
import { useI18n } from "../i18n/context";
import { useMoney } from "../lib/useMoney";
import { BellIcon } from "./icons";
import { ErrorMessage } from "./ui";

const THRESHOLDS = [3, 5, 10, 15, 20];

/**
 * "Watch price" for a part or a build: a toggle with a small panel for the
 * conditions (move by N % either way, and/or reach a target price). Alerts go
 * to Telegram; the panel says so when the account is not connected yet.
 */
export function WatchButton({ component, build }: { component?: number; build?: number }) {
  const { user } = useAuth();
  const { t } = useI18n();
  const money = useMoney();
  const target = component ? { component } : { build };
  const watches = useWatches(target, Boolean(user));
  const telegram = useTelegram(Boolean(user));
  const save = useSaveWatch();
  const remove = useDeleteWatch();
  const [open, setOpen] = useState(false);
  const watch = watches.data?.[0];
  const [threshold, setThreshold] = useState<number | null>(null);
  const [targetPrice, setTargetPrice] = useState<string | null>(null);

  if (!user) {
    return (
      <Link to="/login" className="button secondary watch-button">
        <BellIcon size={16} /> {t("watch.add")}
      </Link>
    );
  }

  // Shown in the main currency; stored in USD.
  const shownTarget =
    targetPrice ??
    (watch?.target_price
      ? String(money.currency === "UAH" ? Math.round(Number(watch.target_price) * money.rate) : watch.target_price)
      : "");
  const shownThreshold = threshold ?? watch?.threshold_percent ?? 5;

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const amount = Number(shownTarget.replace(",", "."));
    save.mutate(
      {
        id: watch?.id,
        body: {
          ...(watch ? {} : target),
          threshold_percent: shownThreshold,
          target_price: shownTarget && amount > 0 ? money.toUsd(amount).toFixed(2) : null,
        },
      },
      { onSuccess: () => setOpen(false) },
    );
  }

  return (
    <div className="watch">
      <button
        type="button"
        className={`watch-button ${watch ? "active" : "secondary"}`}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <BellIcon size={16} /> {watch ? t("watch.active") : t("watch.add")}
      </button>
      {open && (
        <form className="watch-panel panel" onSubmit={submit}>
          <label>
            {t("watch.threshold")}
            <select value={shownThreshold} onChange={(e) => setThreshold(Number(e.target.value))}>
              {THRESHOLDS.map((n) => (
                <option key={n} value={n}>
                  ±{n}%
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("watch.target")}
            <input
              type="number"
              min={0}
              inputMode="decimal"
              placeholder={t("watch.targetPlaceholder", { symbol: money.symbol })}
              value={shownTarget}
              onChange={(e) => setTargetPrice(e.target.value)}
            />
          </label>
          {telegram.data && !telegram.data.linked && (
            <p className="notice small">
              {t("watch.needTelegram")} <Link to="/profile">{t("watch.goProfile")}</Link>
            </p>
          )}
          <div className="watch-actions">
            <button type="submit" className="small" disabled={save.isPending}>
              {watch ? t("common.save") : t("watch.add")}
            </button>
            {watch && (
              <button
                type="button"
                className="small secondary danger"
                disabled={remove.isPending}
                onClick={() => remove.mutate(watch.id, { onSuccess: () => setOpen(false) })}
              >
                {t("watch.remove")}
              </button>
            )}
          </div>
          <ErrorMessage error={save.error ?? remove.error} />
        </form>
      )}
    </div>
  );
}
