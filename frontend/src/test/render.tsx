import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";

import { langStore } from "../i18n/context";
import { I18nProvider } from "../i18n/I18nProvider";

/** Render with the providers every component expects. */
export function renderWithProviders(ui: ReactElement, lang: "en" | "uk" = "en") {
  localStorage.setItem("pcb.lang", lang);
  langStore.set(lang);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider>{ui}</I18nProvider>
    </QueryClientProvider>,
  );
}
