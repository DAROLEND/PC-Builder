import type { CategoryKind, Component, ComponentBrief } from "../api/types";

/** A selected part, normalised from either a catalog Component or a ComponentBrief. */
export interface Picked {
  id: number;
  name: string;
  kind: CategoryKind;
  manufacturer: string;
  price: string;
  specs: Record<string, unknown>;
  image: string | null;
  market: ComponentBrief["market"];
}

export interface Line {
  part: Picked;
  quantity: number;
}

export function fromComponent(c: Component): Picked {
  return {
    id: c.id,
    name: c.name,
    kind: c.category.kind,
    manufacturer: c.manufacturer.name,
    price: c.price,
    specs: c.specs,
    image: c.image,
    market: c.market,
  };
}

export function fromBrief(c: ComponentBrief): Picked {
  return {
    id: c.id,
    name: c.name,
    kind: c.kind,
    manufacturer: c.manufacturer,
    price: c.price,
    specs: c.specs,
    image: c.image,
    market: c.market,
  };
}

/** Slots that can hold several different parts (two memory kits, several drives). */
export const MULTI_SLOTS: ReadonlySet<CategoryKind> = new Set(["ram", "storage", "gpu"]);
