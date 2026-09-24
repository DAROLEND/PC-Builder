import { useState } from "react";
import { Link } from "react-router-dom";

import {
  useBuilds,
  useDeleteWatch,
  useLinkTelegram,
  useTelegram,
  useUnlinkTelegram,
  useUpdateTelegram,
  useWatches,
} from "../api/hooks";
import type { CategoryKind, TelegramStatus, Watch } from "../api/types";
import { useAuth } from "../auth/useAuth";
import { BellIcon, TelegramIcon } from "../components/icons";
import { PartImage } from "../components/PartMedia";
import { Empty, ErrorMessage, Loading } from "../components/ui";
import { useI18n } from "../i18n/context";
import { formatDate } from "../lib/format";
import { useMoney } from "../lib/useMoney";

export function ProfilePage() {
  const { user } = useAuth();
  const { t, locale } = useI18n();
  if (!user) return null;
  return (
    <div className="profile">
      <div className="page-title profile-head">
        <span className="avatar large" aria-hidden="true">
          {user.username.slice(0, 1).toUpperCase()}
        </span>
        <div>
          <span className="eyebrow">{t("profile.title")}</span>
          <h1>{user.username}</h1>
          <p className="muted">
            {user.email} · {t("profile.since", { date: formatDate(user.date_joined, locale) })}
          </p>
        </div>
      </div>
      <div className="profile-grid">
        <TelegramCard />
        <WatchList />
      </div>
      <MyBuilds />
    </div>
  );
}

function TelegramCard() {
  const { t, lang } = useI18n();
  const [link, setLink] = useState<string | null>(null);
  const status = useTelegram(true, Boolean(link));
  const create = useLinkTelegram();
  const update = useUpdateTelegram();
  const unlink = useUnlinkTelegram();
  const s: TelegramStatus | undefined = status.data;
  const bot = s?.bot_username ? `@${s.bot_username}` : "";
  const waiting = Boolean(link) && !s?.linked;

  function connect() {
    // Open the tab synchronously (popup blockers allow that), then point it at the bot.
    const tab = window.open("", "_blank");
    create.mutate(lang, {
      onSuccess: ({ url }) => {
        setLink(url);
        if (tab) tab.location.href = url;
      },
      onError: () => tab?.close(),
    });
  }

  return (
    <section className="panel telegram-card">
      <h3>
        <TelegramIcon size={20} /> {t("tg.title")}
      </h3>
      {status.isLoading ? (
        <Loading rows={2} />
      ) : !s?.bot_username ? (
        <p className="muted">{t("tg.unavailable")}</p>
      ) : s.linked ? (
        <>
          <p className="tg-linked">
            <span className="stock-dot in" /> {t("tg.linked", { name: s.username ? `@${s.username}` : bot })}
          </p>
          <label className="switch">
            <input
              type="checkbox"
              checked={s.enabled}
              onChange={(e) => update.mutate({ enabled: e.target.checked })}
            />
            {t("tg.enabled")}
          </label>
          <label className="switch">
            <input
              type="checkbox"
              checked={s.quiet_hours}
              onChange={(e) => update.mutate({ quiet_hours: e.target.checked })}
            />
            {t("tg.quiet")}
          </label>
          <label className="inline-select">
            {t("tg.language")}
            <select
              value={s.language}
              onChange={(e) => update.mutate({ language: e.target.value as "uk" | "en" })}
            >
              <option value="uk">Українська</option>
              <option value="en">English</option>
            </select>
          </label>
          <div className="tg-actions">
            {s.bot_url && (
              <a className="button small secondary" href={s.bot_url} target="_blank" rel="noopener noreferrer">
                {t("tg.openBot", { bot })}
              </a>
            )}
            <button
              className="small secondary danger"
              onClick={() => {
                if (confirm(t("tg.confirmDisconnect"))) {
                  setLink(null);
                  unlink.mutate();
                }
              }}
            >
              {t("tg.disconnect")}
            </button>
          </div>
        </>
      ) : waiting ? (
        <>
          <p>{t("tg.waiting", { bot })}</p>
          <p className="tg-waiting muted small">
            <span className="thinking" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
            {t("tg.checking")}
          </p>
          <a className="button small" href={link!} target="_blank" rel="noopener noreferrer">
            {t("tg.openBot", { bot })}
          </a>
        </>
      ) : (
        <>
          <p className="muted">{t("tg.lead")}</p>
          <button onClick={connect} disabled={create.isPending}>
            <TelegramIcon size={16} /> {t("tg.connect")}
          </button>
        </>
      )}
      <ErrorMessage error={create.error ?? update.error ?? unlink.error} />
    </section>
  );
}

function WatchList() {
  const { t } = useI18n();
  const money = useMoney();
  const watches = useWatches();
  const remove = useDeleteWatch();

  return (
    <section className="panel watch-list">
      <h3>
        <BellIcon size={18} /> {t("watch.title")}
        {watches.data && watches.data.length > 0 && <span className="count">{watches.data.length}</span>}
      </h3>
      {watches.isLoading ? (
        <Loading rows={3} />
      ) : !watches.data?.length ? (
        <p className="muted">{t("watch.empty")}</p>
      ) : (
        <ul>
          {watches.data.map((w: Watch) => {
            const change = w.change_percent === null ? null : Number(w.change_percent);
            return (
              <li key={w.id} className="watch-row">
                <PartImage
                  src={w.item.image}
                  kind={(w.item.category ?? "case") as CategoryKind}
                  alt=""
                  size="sm"
                />
                <div className="watch-row-body">
                  <Link to={w.item.path} className="part-name">
                    {w.item.kind === "build" ? `${t("watch.build")} «${w.item.name}»` : w.item.name}
                  </Link>
                  <span className="muted small">
                    ±{w.threshold_percent}%
                    {w.target_price && ` · ${t("watch.targetShort", { price: money.main(w.target_price) })}`}
                  </span>
                </div>
                <div className="watch-row-price">
                  <strong>{money.main(w.current_price)}</strong>
                  {change !== null && Math.abs(change) >= 0.1 && (
                    <span className={`small ${change < 0 ? "down" : "up"}`}>
                      {change > 0 ? "+" : "−"}
                      {Math.abs(change).toFixed(1)}%
                    </span>
                  )}
                </div>
                <button
                  className="link danger small"
                  aria-label={t("watch.remove")}
                  title={t("watch.remove")}
                  onClick={() => remove.mutate(w.id)}
                >
                  ✕
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function MyBuilds() {
  const { t } = useI18n();
  const money = useMoney();
  const builds = useBuilds({ mine: true });
  return (
    <section className="profile-builds">
      <div className="page-head">
        <h2>{t("profile.builds")}</h2>
        <Link to="/configurator" className="button small">
          {t("profile.newBuild")}
        </Link>
      </div>
      <ErrorMessage error={builds.error} />
      {builds.data && !builds.data.results.length ? (
        <Empty>{t("profile.noBuilds")}</Empty>
      ) : (
        <div className="grid">
          {builds.data?.results.map((b, i) => (
            <Link
              key={b.id}
              to={`/builds/${b.id}`}
              className="card card-link build-card"
              style={{ "--i": i } as React.CSSProperties}
            >
              <span className="muted small">
                {b.is_public ? t("common.public") : t("common.private")} · {t("common.parts", { count: b.parts_count })}
              </span>
              <h3>{b.name}</h3>
              <strong className="mono">{money.main(b.total_price)}</strong>
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}
