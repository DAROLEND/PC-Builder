import { Link, useParams, useSearchParams } from "react-router-dom";

import { useOrder, useOrderAction, useOrders } from "../api/hooks";
import type { Order } from "../api/types";
import { Empty, ErrorMessage, Loading } from "../components/ui";
import { useI18n } from "../i18n/context";
import { formatDate } from "../lib/format";
import { useMoney } from "../lib/useMoney";

type Status = NonNullable<Order["status"]>;

function StatusBadge({ status }: { status: Order["status"] }) {
  const { t } = useI18n();
  const s: Status = status ?? "pending";
  return <span className={`badge status-${s}`}>{t(`status.${s}`)}</span>;
}

export function OrdersPage() {
  const { t, locale } = useI18n();
  const money = useMoney();
  const orders = useOrders();
  if (orders.isLoading) return <Loading />;
  return (
    <div>
      <div className="page-title">
        <span className="eyebrow">{t("orders.eyebrow")}</span>
        <h1>{t("orders.title")}</h1>
      </div>
      <ErrorMessage error={orders.error} />
      {!orders.data?.results.length ? (
        <Empty>
          <Link to="/builds">{t("orders.empty")}</Link>
        </Empty>
      ) : (
        <table className="parts">
          <thead>
            <tr>
              <th>{t("orders.order")}</th>
              <th>{t("orders.created")}</th>
              <th>{t("orders.status")}</th>
              <th className="num">{t("common.total")}</th>
            </tr>
          </thead>
          <tbody>
            {orders.data.results.map((o) => (
              <tr key={o.id}>
                <td>
                  <Link to={`/orders/${o.id}`}>#{o.id}</Link>
                </td>
                <td>{formatDate(o.created_at, locale)}</td>
                <td>
                  <StatusBadge status={o.status} />
                </td>
                <td className="num">{money.main(o.total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function OrderDetailPage() {
  const id = Number(useParams().id);
  const { t, locale } = useI18n();
  const money = useMoney();
  const [params] = useSearchParams();
  const order = useOrder(id);
  const action = useOrderAction(id);

  if (order.isLoading) return <Loading />;
  if (!order.data) return <ErrorMessage error={order.error} />;
  const o = order.data;

  return (
    <div className="detail">
      <div className="page-head">
        <div className="page-title">
          <span className="eyebrow">
            {formatDate(o.created_at, locale)}
            {o.build && (
              <>
                {" · "}
                <Link to={`/builds/${o.build}`}>{t("orders.fromBuild", { id: o.build })}</Link>
              </>
            )}
          </span>
          <h1>
            {t("orders.order")} #{o.id}
          </h1>
        </div>
        <StatusBadge status={o.status} />
      </div>

      {params.get("paid") && o.status === "pending" && (
        <div className="alert info">{t("orders.waitingStripe")}</div>
      )}

      <table className="parts">
        <thead>
          <tr>
            <th>{t("orders.item")}</th>
            <th className="num">{t("common.qty")}</th>
            <th className="num">{t("common.price")}</th>
          </tr>
        </thead>
        <tbody>
          {o.items.map((item) => (
            <tr key={item.id}>
              <td>{item.component_name}</td>
              <td className="num">{item.quantity}</td>
              <td className="num">{money.main(item.line_total)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={2}>{t("common.total")}</td>
            <td className="num">
              <strong>{money.main(o.total)}</strong>
            </td>
          </tr>
        </tfoot>
      </table>

      <p>
        <span className="muted">{t("orders.shipTo")}</span> {o.shipping_address}
      </p>

      <div className="actions">
        {o.status === "pending" && (
          <button disabled={action.isPending} onClick={() => action.mutate("pay")}>
            {t("orders.pay", { amount: money.main(o.total) })}
          </button>
        )}
        {o.allowed_transitions.includes("cancelled") && (
          <button
            className="secondary danger"
            disabled={action.isPending}
            onClick={() => confirm(t("orders.confirmCancel")) && action.mutate("cancel")}
          >
            {t("orders.cancel")}
          </button>
        )}
      </div>
      <ErrorMessage error={action.error} />
    </div>
  );
}
