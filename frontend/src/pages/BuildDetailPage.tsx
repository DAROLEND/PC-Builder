import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  useAddComment,
  useBuild,
  useCloneBuild,
  useComments,
  useCreateOrder,
  useDeleteBuild,
  useDeleteComment,
} from "../api/hooks";
import { useAuth } from "../auth/useAuth";
import { CompatibilityPanel } from "../components/CompatibilityPanel";
import { MarketInfo, PartImage } from "../components/PartMedia";
import { WatchButton } from "../components/WatchButton";
import { ErrorMessage, Loading } from "../components/ui";
import { AutoTextarea } from "../components/AutoTextarea";
import { useI18n } from "../i18n/context";
import { formatDate, specSummary } from "../lib/format";
import { useMoney } from "../lib/useMoney";

export function BuildDetailPage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const { user } = useAuth();
  const { t, lang, locale } = useI18n();
  const money = useMoney();
  const build = useBuild(id);
  const clone = useCloneBuild();
  const remove = useDeleteBuild();

  if (build.isLoading) return <Loading />;
  if (build.error || !build.data) return <ErrorMessage error={build.error ?? new Error(t("common.notFound"))} />;

  const b = build.data;
  const isOwner = user?.username === b.owner;
  const psu = b.items.find((i) => i.component.kind === "psu")?.component.specs.wattage as
    | number
    | undefined;

  return (
    <div className="detail">
      <div className="page-head">
        <div className="page-title">
          <span className="eyebrow">
            {t("common.by", { user: b.owner })} · {b.is_public ? t("common.public") : t("common.private")}
          </span>
          <h1>{b.name}</h1>
          <p className="muted">{t("builds.updated", { date: formatDate(b.updated_at, locale) })}</p>
        </div>
        <div className="actions">
          <WatchButton build={b.id} />
          {isOwner && (
            <>
              <Link to={`/configurator/${b.id}`} className="button secondary">
                {t("builds.edit")}
              </Link>
              <button
                className="secondary danger"
                onClick={() => {
                  if (confirm(t("builds.confirmDelete", { name: b.name }))) {
                    remove.mutate(b.id, { onSuccess: () => navigate("/builds") });
                  }
                }}
              >
                {t("common.delete")}
              </button>
            </>
          )}
          {user && (
            <button
              className="secondary"
              disabled={clone.isPending}
              onClick={() =>
                clone.mutate(b.id, { onSuccess: (copy) => navigate(`/configurator/${copy.id}`) })
              }
            >
              {t("builds.clone")}
            </button>
          )}
        </div>
      </div>
      <ErrorMessage error={clone.error ?? remove.error} />
      {b.description && <p>{b.description}</p>}

      <div className="two-col">
        <div>
          <div className="part-rows">
            {b.items.map((item, i) => (
              <div key={item.id} className="part-row" style={{ "--i": i } as React.CSSProperties}>
                <PartImage src={item.component.image} kind={item.component.kind} alt={item.component.name} />
                <div className="part-row-body">
                  <span className="tag">{t(`kind.${item.component.kind}`)}</span>
                  <div className="part-name">
                    {item.component.manufacturer} {item.component.name}
                  </div>
                  <div className="specs">
                    {specSummary(item.component.kind, item.component.specs, lang).join(" · ")}
                  </div>
                  <MarketInfo market={item.component.market} />
                </div>
                <div className="part-row-price">
                  {(item.quantity ?? 1) > 1 && <span className="muted small">× {item.quantity}</span>}
                  <strong className="price">{money.main(item.line_total)}</strong>
                  <span className="muted small">{money.secondary(item.line_total)}</span>
                </div>
              </div>
            ))}
            <div className="part-rows-total">
              <span>{t("common.total")}</span>
              <strong>{money.main(b.total_price)}</strong>
            </div>
          </div>

          <Comments buildId={b.id} buildOwner={b.owner} />
        </div>

        <aside>
          <CompatibilityPanel report={b.compatibility} psuWattage={psu} />
          {user && b.compatibility.is_compatible && b.compatibility.is_complete && (
            <OrderForm buildId={b.id} />
          )}
        </aside>
      </div>
    </div>
  );
}

function OrderForm({ buildId }: { buildId: number }) {
  const navigate = useNavigate();
  const { t } = useI18n();
  const create = useCreateOrder();
  const [address, setAddress] = useState("");

  return (
    <form
      className="panel"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate(
          { build: buildId, shipping_address: address },
          { onSuccess: (order) => navigate(`/orders/${order.id}`) },
        );
      }}
    >
      <h3>{t("builds.order")}</h3>
      <label>
        {t("builds.address")}
        <AutoTextarea
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          placeholder={t("builds.addressPlaceholder")}
          autoComplete="shipping street-address"
          maxLength={500}
          required
          rows={3}
        />
      </label>
      <button type="submit" disabled={create.isPending}>
        {create.isPending ? t("builds.placing") : t("builds.placeOrder")}
      </button>
      <ErrorMessage error={create.error} />
    </form>
  );
}

function Comments({ buildId, buildOwner }: { buildId: number; buildOwner: string }) {
  const { user } = useAuth();
  const { t, locale } = useI18n();
  const comments = useComments(buildId);
  const add = useAddComment(buildId);
  const remove = useDeleteComment(buildId);
  const [text, setText] = useState("");

  return (
    <section className="comments">
      <h2>{t("builds.comments")}</h2>
      {comments.data?.length === 0 && <p className="muted">{t("builds.noComments")}</p>}
      <ul>
        {comments.data?.map((c) => (
          <li key={c.id} className="comment">
            <div className="muted small">
              {c.author} · {formatDate(c.created_at, locale)}
              {user && (user.username === c.author || user.username === buildOwner) && (
                <button className="link danger small" onClick={() => remove.mutate(c.id)}>
                  {t("common.delete")}
                </button>
              )}
            </div>
            <p>{c.text}</p>
          </li>
        ))}
      </ul>
      {user ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            add.mutate(text, { onSuccess: () => setText("") });
          }}
        >
          <AutoTextarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={t("builds.commentPlaceholder")}
            required
            maxLength={2000}
            rows={3}
          />
          <button type="submit" disabled={add.isPending || !text.trim()}>
            {t("builds.comment")}
          </button>
          <ErrorMessage error={add.error ?? remove.error} />
        </form>
      ) : (
        <p className="muted">
          <Link to="/login">{t("nav.login")}</Link> — {t("builds.loginToComment")}
        </p>
      )}
    </section>
  );
}
