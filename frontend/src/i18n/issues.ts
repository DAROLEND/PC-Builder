/**
 * Compatibility messages, rendered from the engine's `code` + `params`.
 * The backend stays language-agnostic; unknown codes fall back to its English text.
 */
import type { Issue } from "../api/types";
import type { Lang } from "./context";
import { format } from "./context";

type Templates = Record<string, string>;

const en: Templates = {
  TOO_MANY_PARTS: "A build can contain at most {limit} × {kind}, got {count}.",
  CPU_SOCKET_MISMATCH: "{cpu} uses socket {cpu_socket}, but {board} has socket {board_socket}.",
  CHIPSET_UNSUPPORTED: "{cpu} is not supported by the {chipset} chipset (supported: {supported}).",
  MIXED_MEMORY_TYPES: "DDR4 and DDR5 modules cannot be mixed.",
  MEMORY_TYPE_MISMATCH: "{ram} is {ram_type}, but {board} only supports {board_type}.",
  CPU_MEMORY_UNSUPPORTED: "{cpu} does not support {ram_type} memory.",
  NOT_ENOUGH_MEMORY_SLOTS: "{modules} memory modules selected, but {board} has {slots} slots.",
  MEMORY_OVER_MAX: "{total_gb} GB of memory exceeds the {max_gb} GB supported by {board}.",
  MIXED_MEMORY_KITS:
    "Mixing several memory kits may not run at rated speed; a single kit is more reliable.",
  CASE_FORM_FACTOR: "{board} is {form_factor}, but {case} supports {supported}.",
  GPU_TOO_LONG: "{gpu} is {length} mm long, {case} fits up to {limit} mm.",
  GPU_TIGHT_FIT: "{gpu} fits in {case} with only {spare} mm to spare.",
  GPU_LENGTH_UNKNOWN:
    "The length of {gpu} is unknown; check that it fits in {case} (up to {limit} mm).",
  PSU_FORM_FACTOR: "{psu} is {form_factor}, but {case} accepts {supported}.",
  NO_COOLER: "No CPU cooler selected; make sure {cpu} ships with a boxed cooler.",
  COOLER_SOCKET: "{cooler} does not support socket {socket}.",
  COOLER_UNDERRATED:
    "{cooler} is rated for {rating} W, but {cpu} has a TDP of {tdp} W and draws up to {load} W under load: it will overheat and throttle. Choose a cooler rated for {recommended} W or more.",
  COOLER_LOW_HEADROOM:
    "{cooler} ({rating} W) copes with {cpu} at its {tdp} W TDP, but under full load the CPU draws up to {load} W. For games and rendering choose {recommended} W or more.",
  COOLER_RATING_UNKNOWN:
    "{cooler} does not state how much heat it can remove; {cpu} produces up to {load} W under load. Check the cooler's specifications.",
  COOLER_REQUIRED: "{cpu} is sold without a cooler: add one rated for at least {recommended} W.",
  COOLER_HEIGHT_UNKNOWN:
    "The height of {cooler} is unknown; check that it fits in {case} (up to {limit} mm).",
  COOLER_TOO_TALL: "{cooler} is {height} mm tall, {case} fits coolers up to {limit} mm.",
  RADIATOR_UNKNOWN: "{case} does not list radiator support; check that {radiator} mm fits.",
  RADIATOR_TOO_LARGE: "{cooler} needs a {radiator} mm radiator mount, {case} supports {limit} mm.",
  NOT_ENOUGH_M2_SLOTS: "{count} M.2 drives selected, {board} has {slots} M.2 slots.",
  NOT_ENOUGH_SATA_PORTS: "{count} SATA drives selected, {board} has {ports} ports.",
  NO_VIDEO_OUTPUT: "{cpu} has no integrated graphics; add a graphics card.",
  PSU_INSUFFICIENT: "{psu} provides {wattage} W, the build draws about {estimated} W.",
  PSU_LOW_HEADROOM: "{psu} ({wattage} W) leaves little headroom for ~{estimated} W; {recommended} W is recommended.",
  PSU_BELOW_GPU_RECOMMENDATION: "The vendor of {gpu} recommends at least a {recommended} W PSU.",
};

const uk: Templates = {
  TOO_MANY_PARTS: "У збірці може бути щонайбільше {limit} × «{kind}», а вибрано {count}.",
  CPU_SOCKET_MISMATCH: "{cpu} має сокет {cpu_socket}, а {board} — {board_socket}.",
  CHIPSET_UNSUPPORTED: "Чипсет {chipset} не підтримує {cpu} (підтримуються: {supported}).",
  MIXED_MEMORY_TYPES: "Не можна змішувати модулі DDR4 і DDR5.",
  MEMORY_TYPE_MISMATCH: "{ram} — це {ram_type}, а {board} підтримує лише {board_type}.",
  CPU_MEMORY_UNSUPPORTED: "{cpu} не підтримує пам'ять {ram_type}.",
  NOT_ENOUGH_MEMORY_SLOTS: "Вибрано {modules} модулів пам'яті, а на {board} лише {slots} слоти.",
  MEMORY_OVER_MAX: "{total_gb} ГБ пам'яті — більше, ніж {max_gb} ГБ, які підтримує {board}.",
  MIXED_MEMORY_KITS:
    "Кілька різних комплектів пам'яті можуть не запрацювати на заявленій частоті; один комплект надійніший.",
  CASE_FORM_FACTOR: "{board} має форм-фактор {form_factor}, а {case} підтримує {supported}.",
  GPU_TOO_LONG: "{gpu} завдовжки {length} мм, а в {case} влазить до {limit} мм.",
  GPU_TIGHT_FIT: "{gpu} влазить у {case} із запасом лише {spare} мм.",
  GPU_LENGTH_UNKNOWN: "Довжина {gpu} невідома — перевір, чи влізе вона в {case} (до {limit} мм).",
  PSU_FORM_FACTOR: "{psu} формату {form_factor}, а {case} приймає {supported}.",
  NO_COOLER: "Кулер не вибрано: переконайся, що {cpu} продається з боксовим кулером.",
  COOLER_SOCKET: "{cooler} не підтримує сокет {socket}.",
  COOLER_UNDERRATED:
    "{cooler} розрахований на {rating} Вт, а {cpu} має TDP {tdp} Вт і під навантаженням споживає до {load} Вт: буде перегрів і скидання частот. Потрібен кулер від {recommended} Вт.",
  COOLER_LOW_HEADROOM:
    "{cooler} ({rating} Вт) впорається з {cpu} на базових {tdp} Вт, але під повним навантаженням процесор споживає до {load} Вт. Для ігор і рендеру краще кулер від {recommended} Вт.",
  COOLER_RATING_UNKNOWN:
    "Виробник {cooler} не вказує, скільки тепла він відводить, а {cpu} під навантаженням виділяє до {load} Вт. Перевір характеристики кулера.",
  COOLER_REQUIRED: "{cpu} продається без кулера: додай систему охолодження щонайменше на {recommended} Вт.",
  COOLER_HEIGHT_UNKNOWN: "Висота {cooler} невідома — перевір, чи влізе він у {case} (до {limit} мм).",
  COOLER_TOO_TALL: "{cooler} заввишки {height} мм, а {case} вміщує кулери до {limit} мм.",
  RADIATOR_UNKNOWN: "{case} не вказує підтримку радіаторів; перевір, чи влізе {radiator} мм.",
  RADIATOR_TOO_LARGE: "{cooler} потребує кріплення радіатора {radiator} мм, а {case} — до {limit} мм.",
  NOT_ENOUGH_M2_SLOTS: "Вибрано {count} M.2-накопичувачів, а на {board} {slots} M.2-слоти.",
  NOT_ENOUGH_SATA_PORTS: "Вибрано {count} SATA-накопичувачів, а на {board} {ports} портів.",
  NO_VIDEO_OUTPUT: "{cpu} не має вбудованої графіки — додай відеокарту.",
  PSU_INSUFFICIENT: "{psu} дає {wattage} Вт, а збірка споживає близько {estimated} Вт.",
  PSU_LOW_HEADROOM: "{psu} ({wattage} Вт) майже без запасу для ~{estimated} Вт; радимо {recommended} Вт.",
  PSU_BELOW_GPU_RECOMMENDATION: "Виробник {gpu} радить блок живлення щонайменше на {recommended} Вт.",
};

const TEMPLATES: Record<Lang, Templates> = { en, uk };

const TITLES: Record<Lang, Record<string, string>> = {
  en: {},
  uk: {
    TOO_MANY_PARTS: "ЗАБАГАТО ДЕТАЛЕЙ",
    CPU_SOCKET_MISMATCH: "НЕ ТОЙ СОКЕТ",
    CHIPSET_UNSUPPORTED: "ЧИПСЕТ НЕ ПІДТРИМУЄ",
    MIXED_MEMORY_TYPES: "ЗМІШАНА ПАМ'ЯТЬ",
    MEMORY_TYPE_MISMATCH: "НЕ ТОЙ ТИП ПАМ'ЯТІ",
    CPU_MEMORY_UNSUPPORTED: "ПРОЦЕСОР НЕ ПІДТРИМУЄ ПАМ'ЯТЬ",
    NOT_ENOUGH_MEMORY_SLOTS: "БРАКУЄ СЛОТІВ ПАМ'ЯТІ",
    MEMORY_OVER_MAX: "ЗАБАГАТО ПАМ'ЯТІ",
    MIXED_MEMORY_KITS: "РІЗНІ КОМПЛЕКТИ ПАМ'ЯТІ",
    CASE_FORM_FACTOR: "ПЛАТА НЕ ВЛАЗИТЬ",
    GPU_TOO_LONG: "ВІДЕОКАРТА НЕ ВЛАЗИТЬ",
    GPU_TIGHT_FIT: "ВІДЕОКАРТА ВПРИТУЛ",
    GPU_LENGTH_UNKNOWN: "ДОВЖИНА ВІДЕОКАРТИ — ПЕРЕВІР",
    PSU_FORM_FACTOR: "НЕ ТОЙ ФОРМАТ БЖ",
    NO_COOLER: "НЕМАЄ КУЛЕРА",
    COOLER_SOCKET: "КУЛЕР НЕ ПІДХОДИТЬ",
    COOLER_UNDERRATED: "СЛАБКИЙ КУЛЕР",
    COOLER_LOW_HEADROOM: "КУЛЕР НА МЕЖІ",
    COOLER_RATING_UNKNOWN: "ПОТУЖНІСТЬ КУЛЕРА — ПЕРЕВІР",
    COOLER_REQUIRED: "ПОТРІБЕН КУЛЕР",
    COOLER_HEIGHT_UNKNOWN: "ВИСОТА КУЛЕРА — ПЕРЕВІР",
    COOLER_TOO_TALL: "КУЛЕР НЕ ВЛАЗИТЬ",
    RADIATOR_UNKNOWN: "РАДІАТОР — ПЕРЕВІР",
    RADIATOR_TOO_LARGE: "РАДІАТОР НЕ ВЛАЗИТЬ",
    NOT_ENOUGH_M2_SLOTS: "БРАКУЄ M.2-СЛОТІВ",
    NOT_ENOUGH_SATA_PORTS: "БРАКУЄ SATA-ПОРТІВ",
    NO_VIDEO_OUTPUT: "НЕМАЄ ВИВОДУ ЗОБРАЖЕННЯ",
    PSU_INSUFFICIENT: "СЛАБКИЙ БЛОК ЖИВЛЕННЯ",
    PSU_LOW_HEADROOM: "МАЛИЙ ЗАПАС БЖ",
    PSU_BELOW_GPU_RECOMMENDATION: "БЖ НИЖЧЕ РЕКОМЕНДАЦІЇ",
  },
};

export function issueText(issue: Issue, lang: Lang): string {
  const template = TEMPLATES[lang][issue.code];
  return template ? format(template, issue.params as Record<string, unknown>) : issue.message;
}

export function issueTitle(issue: Issue, lang: Lang): string {
  return TITLES[lang][issue.code] ?? issue.code.replaceAll("_", " ");
}
