import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";

import {
  useBuild,
  useCategories,
  useCompatibilityCheck,
  useComponents,
  useSaveBuild,
} from "../api/hooks";
import type { Category, CategoryKind, ComponentBrief } from "../api/types";
import { useAuth } from "../auth/useAuth";
import { Collapse } from "../components/Collapse";
import { CompatibilityPanel } from "../components/CompatibilityPanel";
import { CategoryIcon } from "../components/icons";
import { MarketBadges, MarketInfo, PartImage } from "../components/PartMedia";
import { ErrorMessage, Loading } from "../components/ui";
import { useI18n } from "../i18n/context";
import { specSummary, sumMoney } from "../lib/format";
import { MULTI_SLOTS, fromBrief, fromComponent } from "../lib/picked";
import type { Line, Picked } from "../lib/picked";
import { useAnimatedNumber } from "../lib/useAnimatedNumber";
import { useMoney } from "../lib/useMoney";

interface Initial {
  lines: Line[];
  name: string;
  isPublic: boolean;
}

/**
 * Loads what the editor starts from (an existing build, a preset handed over by
 * the AI advisor, or nothing) and mounts the editor once it is known. The
 * editor takes it as initial state; `key` remounts it when the source changes,
 * so no effect has to copy server data into local state.
 */
export function ConfiguratorPage() {
  const { id } = useParams();
  const buildId = id ? Number(id) : undefined;
  const location = useLocation();
  const { user } = useAuth();
  const { t } = useI18n();
  const categories = useCategories();
  const existing = useBuild(buildId);

  if (categories.isLoading || (buildId && existing.isLoading)) return <Loading />;
  if (buildId && !existing.data) return <ErrorMessage error={existing.error} />;
  if (existing.data && user && existing.data.owner !== user.username) {
    return <ErrorMessage error={new Error(t("conf.notOwner"))} />;
  }

  // Handed over by the AI advisor (a whole build) or by a part page (one part).
  const state = location.state as { preset?: ComponentBrief[]; parts?: Picked[] } | null;
  const preset = state?.preset;
  const initial: Initial = existing.data
    ? {
        lines: existing.data.items.map((i) => ({
          part: fromBrief(i.component),
          quantity: i.quantity ?? 1,
        })),
        name: existing.data.name,
        isPublic: existing.data.is_public ?? false,
      }
    : preset
      ? {
          lines: preset.map((c) => ({ part: fromBrief(c), quantity: 1 })),
          name: t("conf.aiName"),
          isPublic: false,
        }
      : state?.parts
        ? { lines: state.parts.map((part) => ({ part, quantity: 1 })), name: "", isPublic: false }
        : { lines: [], name: "", isPublic: false };

  return (
    <Editor
      key={buildId ?? location.key}
      buildId={buildId}
      initial={initial}
      categories={categories.data ?? []}
    />
  );
}

function Editor({
  buildId,
  initial,
  categories,
}: {
  buildId: number | undefined;
  initial: Initial;
  categories: Category[];
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { t, lang } = useI18n();
  const money = useMoney();
  const save = useSaveBuild();

  const [lines, setLines] = useState<Line[]>(initial.lines);
  const [active, setActive] = useState<CategoryKind | null>(initial.lines.length ? null : "cpu");
  const slotRefs = useRef(new Map<CategoryKind, HTMLElement>());
  const firstRender = useRef(true);

  // Bring the opened slot into view after the previous one has folded away
  // (the collapse takes ~450 ms and moves everything below it).
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    if (!active) return;
    const timer = window.setTimeout(() => {
      const slot = slotRefs.current.get(active);
      if (!slot) return;
      const { top } = slot.getBoundingClientRect();
      if (top < 90 || top > window.innerHeight * 0.45) {
        slot.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }, 460);
    return () => window.clearTimeout(timer);
  }, [active]);
  const [name, setName] = useState(initial.name);
  const [isPublic, setIsPublic] = useState(initial.isPublic);

  const items = useMemo(
    () => lines.map((l) => ({ component: l.part.id, quantity: l.quantity })),
    [lines],
  );
  const check = useCompatibilityCheck(items);
  const total = sumMoney(lines.map((l) => (Number(l.part.price) * l.quantity).toFixed(2)));
  const psu = lines.find((l) => l.part.kind === "psu")?.part.specs.wattage as number | undefined;
  const animatedTotal = useAnimatedNumber(Number(total));
  const filledSlots = new Set(lines.map((l) => l.part.kind)).size;

  function pick(part: Picked) {
    setLines((current) => {
      if (MULTI_SLOTS.has(part.kind)) {
        if (current.some((l) => l.part.id === part.id)) return current;
        return [...current, { part, quantity: 1 }];
      }
      return [...current.filter((l) => l.part.kind !== part.kind), { part, quantity: 1 }];
    });
    if (!MULTI_SLOTS.has(part.kind)) setActive(null);
  }

  function remove(partId: number) {
    setLines((current) => current.filter((l) => l.part.id !== partId));
  }

  function setQuantity(partId: number, quantity: number) {
    setLines((current) => current.map((l) => (l.part.id === partId ? { ...l, quantity } : l)));
  }

  function onSave(event: React.FormEvent) {
    event.preventDefault();
    if (!user) {
      navigate("/login", { state: { from: location.pathname } });
      return;
    }
    // mutate (not mutateAsync): errors land in save.error and are rendered below.
    save.mutate(
      { id: buildId, body: { name, is_public: isPublic, items } },
      { onSuccess: (build) => navigate(`/builds/${build.id}`) },
    );
  }

  return (
    <div className="configurator">
      <div className="slots">
        <div className="page-title">
          <span className="eyebrow">{buildId ? t("conf.eyebrowEdit") : t("conf.eyebrowNew")}</span>
          <h1>{buildId ? initial.name : t("conf.title")}</h1>
          <p className="muted">{t("conf.lead")}</p>
        </div>
        <div
          className="progress"
          aria-label={t("conf.slots", { filled: filledSlots, total: categories.length })}
        >
          {categories.map((c) => {
            const done = lines.some((l) => l.part.kind === c.kind);
            return (
              <button
                key={c.kind}
                type="button"
                className={`progress-step ${done ? "done" : ""} ${active === c.kind ? "current" : ""}`}
                title={t(`kinds.${c.kind}`)}
                aria-pressed={active === c.kind}
                onClick={() => setActive(active === c.kind ? null : c.kind)}
              >
                <CategoryIcon kind={c.kind} size={20} />
                <span className="progress-label">{t(`short.${c.kind}`)}</span>
                {done && (
                  <span className="progress-check" aria-hidden="true">
                    ✓
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {categories.map((category) => {
          const selected = lines.filter((l) => l.part.kind === category.kind);
          const isOpen = active === category.kind;
          return (
            <section
              key={category.kind}
              ref={(node) => {
                if (node) slotRefs.current.set(category.kind, node);
                else slotRefs.current.delete(category.kind);
              }}
              className={`slot ${isOpen ? "open" : ""} ${selected.length ? "filled" : ""}`}
            >
              <header className="slot-head">
                <h2>
                  <span className="slot-icon">
                    <CategoryIcon kind={category.kind} />
                  </span>
                  {t(`kinds.${category.kind}`)}
                </h2>
                <button
                  className={isOpen ? "secondary small" : "small"}
                  onClick={() => setActive(isOpen ? null : category.kind)}
                >
                  {isOpen
                    ? t("common.close")
                    : selected.length && !MULTI_SLOTS.has(category.kind)
                      ? t("common.change")
                      : t("common.add")}
                </button>
              </header>

              {selected.map((line) => (
                <div key={line.part.id} className="picked">
                  <PartImage
                    src={line.part.image}
                    kind={line.part.kind}
                    alt={line.part.name}
                    size="sm"
                  />
                  <div className="picked-body">
                    <div className="part-name">
                      {line.part.manufacturer} {line.part.name}
                    </div>
                    <div className="specs">
                      {specSummary(line.part.kind, line.part.specs, lang).join(" · ")}
                    </div>
                    <MarketInfo market={line.part.market} compact />
                  </div>
                  <div className="picked-actions">
                    {MULTI_SLOTS.has(line.part.kind) && (
                      <select
                        aria-label={t("common.qty")}
                        value={line.quantity}
                        onChange={(e) => setQuantity(line.part.id, Number(e.target.value))}
                      >
                        {[1, 2, 3, 4].map((n) => (
                          <option key={n} value={n}>
                            × {n}
                          </option>
                        ))}
                      </select>
                    )}
                    <span className="price">
                      {money.main(Number(line.part.price) * line.quantity)}
                    </span>
                    <button className="link danger" onClick={() => remove(line.part.id)}>
                      {t("common.remove")}
                    </button>
                  </div>
                </div>
              ))}

              <Collapse open={isOpen}>
                <Picker
                  kind={category.kind}
                  selectedIds={lines.map((l) => l.part.id)}
                  onPick={pick}
                />
              </Collapse>
            </section>
          );
        })}
      </div>

      <aside className="summary">
        <div className="summary-inner">
          <div className="total">
            <span className="muted">{t("common.total")}</span>
            <strong>{money.main(animatedTotal)}</strong>
            <span className="muted small">
              {money.secondary(total)}
              {money.secondary(total) ? " · " : ""}
              {t("conf.slots", { filled: filledSlots, total: categories.length })}
            </span>
          </div>
          <CompatibilityPanel report={check.data} isFetching={check.isFetching} psuWattage={psu} />

          <form onSubmit={onSave} className="save-form">
            <label>
              {t("conf.name")}
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                maxLength={100}
              />
            </label>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={isPublic}
                onChange={(e) => setIsPublic(e.target.checked)}
              />
              {t("conf.public")}
            </label>
            <button type="submit" disabled={save.isPending || !check.data?.is_compatible}>
              {save.isPending
                ? t("conf.saving")
                : buildId
                  ? t("conf.saveChanges")
                  : user
                    ? t("conf.save")
                    : t("conf.loginToSave")}
            </button>
            {!check.data?.is_compatible && lines.length > 0 && (
              <p className="muted small">{t("conf.fixErrors")}</p>
            )}
            <ErrorMessage error={save.error} />
          </form>
        </div>
      </aside>
    </div>
  );
}

function Picker({
  kind,
  selectedIds,
  onPick,
}: {
  kind: CategoryKind;
  selectedIds: number[];
  onPick: (part: Picked) => void;
}) {
  const { t, lang } = useI18n();
  const money = useMoney();
  const [onlyCompatible, setOnlyCompatible] = useState(true);
  const [search, setSearch] = useState("");
  const [ordering, setOrdering] = useState("-popularity");

  const components = useComponents({
    category: kind,
    buildable: true, // catalog-only parts can't be checked, so they can't be picked
    page_size: 100,
    ordering,
    search: search || undefined,
    compatible_with: onlyCompatible && selectedIds.length ? selectedIds.join(",") : undefined,
  });

  return (
    <div className="picker">
      <div className="picker-controls">
        <input
          type="search"
          placeholder={t("common.search")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select value={ordering} onChange={(e) => setOrdering(e.target.value)} aria-label="Sort">
          <option value="-popularity">{t("catalog.sort.popular")}</option>
          <option value="price">{t("conf.sort.cheap")}</option>
          <option value="-price">{t("conf.sort.expensive")}</option>
          <option value="name">{t("conf.sort.name")}</option>
        </select>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={onlyCompatible}
            onChange={(e) => setOnlyCompatible(e.target.checked)}
          />
          {t("conf.onlyCompatible")}
        </label>
      </div>
      <ErrorMessage error={components.error} />
      {components.isLoading ? (
        <Loading />
      ) : components.data?.results.length === 0 ? (
        <p className="muted">{t("conf.nothingFits")}</p>
      ) : (
        <ul className="picker-list">
          {components.data?.results.map((c, i) => (
            <li key={c.id} style={{ "--i": i } as React.CSSProperties}>
              <button
                className="picker-item"
                disabled={selectedIds.includes(c.id)}
                onClick={() => onPick(fromComponent(c))}
              >
                <PartImage src={c.image} kind={kind} alt={c.name} size="sm" />
                <span className="picker-body">
                  <span className="part-name">
                    {c.manufacturer.name} {c.name}
                  </span>
                  <span className="picker-badges">
                    <MarketBadges part={c} kind={kind} />
                  </span>
                  <span className="specs">{specSummary(kind, c.specs, lang).join(" · ")}</span>
                  <MarketInfo market={c.market} compact />
                </span>
                <span className="price">{money.main(c.price)}</span>
                <span className="picker-add" aria-hidden="true">
                  +
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
