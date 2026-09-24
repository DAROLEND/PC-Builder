import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { I18nContext, LANGS, format, langStore, plural } from "./context";
import type { I18nState, Lang } from "./context";
import { en } from "./en";
import type { MessageKey } from "./en";
import { uk } from "./uk";

const STORAGE_KEY = "pcb.lang";
const DICTIONARIES: Record<Lang, Record<MessageKey, string>> = { en, uk };

function initialLang(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved && LANGS.includes(saved as Lang)) return saved as Lang;
  } catch {
    // storage unavailable → fall through to the browser language
  }
  return navigator.language?.toLowerCase().startsWith("en") ? "en" : "uk";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [lang, setLangState] = useState<Lang>(() => {
    const value = initialLang();
    langStore.set(value);
    return value;
  });

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = useCallback(
    (next: Lang) => {
      langStore.set(next);
      setLangState(next);
      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch {
        // not persisted, still works for this tab
      }
      // Server messages (validation errors, advisor text) depend on the language.
      qc.invalidateQueries({ queryKey: ["advisor"] });
    },
    [qc],
  );

  const value = useMemo<I18nState>(
    () => ({
      lang,
      setLang,
      locale: lang === "uk" ? "uk-UA" : "en-US",
      t: (key, params) => {
        let template: string = DICTIONARIES[lang][key] ?? key;
        if (template.includes("|") && typeof params?.count === "number") {
          template = plural(template, params.count, lang);
        }
        return format(template, params);
      },
    }),
    [lang, setLang],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}
