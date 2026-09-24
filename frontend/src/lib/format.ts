import type { Lang } from "../i18n/context";

type Amount = string | number | null | undefined;

const cache = new Map<string, Intl.NumberFormat>();
function nf(locale: string, currency: string, digits: number) {
  const key = `${locale}|${currency}|${digits}`;
  let f = cache.get(key);
  if (!f) {
    f = new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
    cache.set(key, f);
  }
  return f;
}

/** The API sends money as decimal strings ("123.45"); never do arithmetic on floats. */
export function formatUsd(value: Amount, locale = "en-US"): string {
  if (value === null || value === undefined || value === "") return "—";
  return nf(locale, "USD", 2).format(Number(value));
}

export function formatUah(value: Amount, locale = "uk-UA"): string {
  if (value === null || value === undefined || value === "") return "";
  return nf(locale, "UAH", 0).format(Number(value));
}

export function formatDate(value: string, locale = "uk-UA"): string {
  return new Date(value).toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" });
}

/** Cents-based sum for decimal strings, to avoid 0.1 + 0.2 style errors. */
export function sumMoney(values: string[]): string {
  const cents = values.reduce((acc, v) => acc + Math.round(Number(v) * 100), 0);
  return (cents / 100).toFixed(2);
}

const SPEC_LABELS: Record<Lang, Record<string, string>> = {
  en: {
    socket: "Socket",
    cores: "Cores",
    threads: "Threads",
    base_clock_ghz: "Base, GHz",
    boost_clock_ghz: "Boost, GHz",
    integrated_graphics: "Integrated graphics",
    supported_chipsets: "Chipsets",
    memory_types: "Memory types",
    memory_slots: "Memory slots",
    max_memory_gb: "Max memory, GB",
    m2_slots: "M.2 slots",
    sata_ports: "SATA ports",
    modules: "Modules",
    module_size_gb: "Module size, GB",
    recommended_psu_w: "Recommended PSU, W",
    psu_form_factors: "PSU formats",
    max_radiator_mm: "Max radiator, mm",
    sockets: "Sockets",
    max_power_w: "Max power, W",
    boxed_cooler: "Boxed cooler",
    tdp_w: "TDP, W",
    chipset: "Chipset",
    form_factor: "Form factor",
    memory_type: "Memory",
    speed_mhz: "Speed, MHz",
    vram_gb: "VRAM, GB",
    length_mm: "Length, mm",
    interface: "Interface",
    capacity_gb: "Capacity, GB",
    wattage: "Power, W",
    efficiency: "Efficiency",
    max_gpu_length_mm: "Max GPU, mm",
    max_cooler_height_mm: "Max cooler, mm",
    supported_form_factors: "Boards",
    type: "Type",
    height_mm: "Height, mm",
    radiator_mm: "Radiator, mm",
    tdp_rating_w: "Rated, W",
  },
  uk: {
    socket: "Сокет",
    cores: "Ядра",
    threads: "Потоки",
    base_clock_ghz: "Базова, ГГц",
    boost_clock_ghz: "Буст, ГГц",
    integrated_graphics: "Вбудована графіка",
    supported_chipsets: "Чипсети",
    memory_types: "Типи пам'яті",
    memory_slots: "Слотів пам'яті",
    max_memory_gb: "Макс. пам'ять, ГБ",
    m2_slots: "Слотів M.2",
    sata_ports: "Портів SATA",
    modules: "Модулів",
    module_size_gb: "Модуль, ГБ",
    recommended_psu_w: "Рекомендований БЖ, Вт",
    psu_form_factors: "Формат БЖ",
    max_radiator_mm: "Радіатор до, мм",
    sockets: "Сокети",
    max_power_w: "Макс. потужність, Вт",
    boxed_cooler: "Кулер у комплекті",
    tdp_w: "TDP, Вт",
    chipset: "Чипсет",
    form_factor: "Форм-фактор",
    memory_type: "Пам'ять",
    speed_mhz: "Частота, МГц",
    vram_gb: "Відеопам'ять, ГБ",
    length_mm: "Довжина, мм",
    interface: "Інтерфейс",
    capacity_gb: "Обсяг, ГБ",
    wattage: "Потужність, Вт",
    efficiency: "Сертифікат",
    max_gpu_length_mm: "Відеокарта до, мм",
    max_cooler_height_mm: "Кулер до, мм",
    supported_form_factors: "Плати",
    type: "Тип",
    height_mm: "Висота, мм",
    radiator_mm: "Радіатор, мм",
    tdp_rating_w: "Розсіює, Вт",
  },
};

const VALUE_LABELS: Record<Lang, Record<string, string>> = {
  en: { air: "air", liquid: "liquid", true: "yes", false: "no" },
  uk: { air: "повітряний", liquid: "рідинний", true: "так", false: "ні" },
};

const SHORT_SPECS: Record<string, string[]> = {
  cpu: ["socket", "cores", "threads", "boost_clock_ghz", "tdp_w"],
  motherboard: ["socket", "chipset", "form_factor", "memory_type"],
  ram: ["memory_type", "speed_mhz"],
  gpu: ["vram_gb", "length_mm", "tdp_w"],
  storage: ["interface", "capacity_gb"],
  psu: ["wattage", "form_factor", "efficiency"],
  case: ["supported_form_factors", "max_gpu_length_mm", "max_cooler_height_mm"],
  cooler: ["type", "height_mm", "radiator_mm", "tdp_rating_w"],
};

export function specSummary(kind: string, specs: Record<string, unknown>, lang: Lang = "en"): string[] {
  return (SHORT_SPECS[kind] ?? [])
    .filter((key) => specs[key] !== undefined && specs[key] !== null)
    .map((key) => {
      const value = specs[key];
      const text = Array.isArray(value)
        ? value.join("/")
        : (VALUE_LABELS[lang][String(value)] ?? String(value));
      return `${SPEC_LABELS[lang][key] ?? key}: ${text}`;
    });
}

/** Order of the full specification table; unknown keys follow in API order. */
const FULL_SPECS: Record<string, string[]> = {
  cpu: [
    "socket",
    "cores",
    "threads",
    "base_clock_ghz",
    "boost_clock_ghz",
    "tdp_w",
    "max_power_w",
    "integrated_graphics",
    "boxed_cooler",
    "memory_types",
    "supported_chipsets",
  ],
  motherboard: [
    "socket",
    "chipset",
    "form_factor",
    "memory_type",
    "memory_slots",
    "max_memory_gb",
    "m2_slots",
    "sata_ports",
  ],
  ram: ["memory_type", "modules", "module_size_gb", "speed_mhz"],
  gpu: ["chipset", "vram_gb", "length_mm", "tdp_w", "recommended_psu_w"],
  storage: ["interface", "capacity_gb"],
  psu: ["wattage", "form_factor", "efficiency"],
  case: [
    "supported_form_factors",
    "max_gpu_length_mm",
    "max_cooler_height_mm",
    "max_radiator_mm",
    "psu_form_factors",
  ],
  cooler: ["type", "sockets", "height_mm", "radiator_mm", "tdp_rating_w"],
};

export function specLabel(key: string, lang: Lang = "en"): string {
  return SPEC_LABELS[lang][key] ?? key;
}

/** Every known spec as [label, value] rows for the part page. */
export function specRows(
  kind: string,
  specs: Record<string, unknown>,
  lang: Lang = "en",
): [string, string][] {
  const order = FULL_SPECS[kind] ?? [];
  const keys = [...order, ...Object.keys(specs).filter((k) => !order.includes(k))];
  return keys
    .filter((key) => specs[key] !== undefined && specs[key] !== null)
    .map((key) => {
      const value = specs[key];
      const text = Array.isArray(value)
        ? value.join(", ")
        : (VALUE_LABELS[lang][String(value)] ?? String(value));
      return [specLabel(key, lang), text];
    });
}
