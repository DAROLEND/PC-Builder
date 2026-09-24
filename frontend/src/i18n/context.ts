import { createContext, useContext } from "react";

import type { MessageKey } from "./en";

export type Lang = "uk" | "en";
export const LANGS: Lang[] = ["uk", "en"];

export interface I18nState {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (key: MessageKey, params?: Record<string, unknown>) => string;
  /** Locale for Intl formatters ("uk-UA" / "en-US"). */
  locale: string;
}

export const I18nContext = createContext<I18nState | null>(null);

export function useI18n(): I18nState {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used inside <I18nProvider>");
  return ctx;
}

// Order of "|"-separated plural forms in the dictionaries.
const PLURAL_FORMS: Record<Lang, Intl.LDMLPluralRule[]> = {
  uk: ["one", "few", "many"], // 1 деталь · 3 деталі · 5 деталей
  en: ["one", "other"],
};

/** Pick the plural form for `count`: "{count} offer|{count} offers". */
export function plural(template: string, count: number, lang: Lang): string {
  const forms = template.split("|");
  const category = new Intl.PluralRules(lang === "uk" ? "uk-UA" : "en-US").select(count);
  const index = PLURAL_FORMS[lang].indexOf(category);
  return forms[index >= 0 ? index : forms.length - 1] ?? forms[0];
}

/** "{a} of {b}" + {a: 1, b: 2} → "1 of 2". Unknown placeholders stay visible. */
export function format(template: string, params?: Record<string, unknown>): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    params[name] === undefined || params[name] === null ? match : String(params[name]),
  );
}

// The API client lives outside React, so the current language is also kept here.
let currentLang: Lang = "uk";
export const langStore = {
  get: () => currentLang,
  set: (lang: Lang) => {
    currentLang = lang;
  },
};
