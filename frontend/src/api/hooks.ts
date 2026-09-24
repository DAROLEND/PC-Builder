/**
 * TanStack Query hooks. Every request goes through the generated, typed client,
 * so parameters and responses are checked against the OpenAPI schema.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "./client";
import type { paths } from "./schema";
import type { AdvisorRequest, BuildItemWrite, BuildWrite, CategoryKind } from "./types";

type ComponentQuery = NonNullable<paths["/api/components/"]["get"]["parameters"]["query"]>;
type BuildQuery = NonNullable<paths["/api/builds/"]["get"]["parameters"]["query"]>;

export const keys = {
  categories: ["categories"] as const,
  components: (q: ComponentQuery) => ["components", q] as const,
  builds: (q: BuildQuery) => ["builds", q] as const,
  build: (id: number) => ["build", id] as const,
  comments: (id: number) => ["build", id, "comments"] as const,
  orders: ["orders"] as const,
  order: (id: number) => ["order", id] as const,
  me: ["me"] as const,
};

// --- Catalog -----------------------------------------------------------------

export function useCategories() {
  return useQuery({
    queryKey: keys.categories,
    queryFn: async () => unwrap(await api.GET("/api/categories/")),
    staleTime: Infinity, // categories practically never change
  });
}

export function useComponents(query: ComponentQuery, enabled = true) {
  return useQuery({
    queryKey: keys.components(query),
    queryFn: async () => unwrap(await api.GET("/api/components/", { params: { query } })),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useComponent(slug: string | undefined) {
  return useQuery({
    queryKey: ["component", slug],
    queryFn: async () =>
      unwrap(await api.GET("/api/components/{slug}/", { params: { path: { slug: slug! } } })),
    enabled: Boolean(slug),
  });
}

/** Daily price points, oldest first; `days` limits the period (undefined = all). */
export function usePriceHistory(slug: string | undefined, days?: number) {
  return useQuery({
    queryKey: ["component", slug, "price-history", days ?? "all"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/components/{slug}/price-history/", {
          params: { path: { slug: slug! }, query: days ? { days } : {} },
        }),
      ),
    enabled: Boolean(slug),
    placeholderData: keepPreviousData,
  });
}

export function useExchangeRate() {
  return useQuery({
    queryKey: ["exchange-rate"],
    queryFn: async () => {
      const result = await api.GET("/api/exchange-rates/latest/");
      return result.response.ok ? (result.data ?? null) : null;
    },
    staleTime: 60 * 60 * 1000,
  });
}

// --- Compatibility (stateless check for the configurator) ---------------------

export function useCompatibilityCheck(items: BuildItemWrite[]) {
  return useQuery({
    queryKey: ["compatibility", items],
    queryFn: async () =>
      unwrap(await api.POST("/api/compatibility/check/", { body: { items } })),
    placeholderData: keepPreviousData,
  });
}

// --- Builds ---------------------------------------------------------------------

export function useBuilds(query: BuildQuery) {
  return useQuery({
    queryKey: keys.builds(query),
    queryFn: async () => unwrap(await api.GET("/api/builds/", { params: { query } })),
    placeholderData: keepPreviousData,
  });
}

export function useBuild(id: number | undefined) {
  return useQuery({
    queryKey: keys.build(id ?? 0),
    queryFn: async () =>
      unwrap(await api.GET("/api/builds/{id}/", { params: { path: { id: id! } } })),
    enabled: id !== undefined,
  });
}

export function useSaveBuild() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, body }: { id?: number; body: BuildWrite }) =>
      id
        ? unwrap(await api.PATCH("/api/builds/{id}/", { params: { path: { id } }, body }))
        : unwrap(await api.POST("/api/builds/", { body })),
    onSuccess: (build) => {
      qc.setQueryData(keys.build(build.id), build);
      qc.invalidateQueries({ queryKey: ["builds"] });
    },
  });
}

export function useDeleteBuild() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) =>
      unwrap(await api.DELETE("/api/builds/{id}/", { params: { path: { id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["builds"] }),
  });
}

export function useCloneBuild() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) =>
      unwrap(await api.POST("/api/builds/{id}/clone/", { params: { path: { id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["builds"] }),
  });
}

export function useComments(buildId: number) {
  return useQuery({
    queryKey: keys.comments(buildId),
    queryFn: async () =>
      unwrap(await api.GET("/api/builds/{id}/comments/", { params: { path: { id: buildId } } })),
  });
}

export function useAddComment(buildId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (text: string) =>
      unwrap(
        await api.POST("/api/builds/{id}/comments/", {
          params: { path: { id: buildId } },
          body: { text },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.comments(buildId) }),
  });
}

export function useDeleteComment(buildId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) =>
      unwrap(await api.DELETE("/api/comments/{id}/", { params: { path: { id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.comments(buildId) }),
  });
}

// --- Orders ---------------------------------------------------------------------

export function useOrders() {
  return useQuery({
    queryKey: keys.orders,
    queryFn: async () => unwrap(await api.GET("/api/orders/")),
  });
}

export function useOrder(id: number) {
  return useQuery({
    queryKey: keys.order(id),
    queryFn: async () => unwrap(await api.GET("/api/orders/{id}/", { params: { path: { id } } })),
  });
}

export function useCreateOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { build: number; shipping_address: string }) =>
      unwrap(await api.POST("/api/orders/", { body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.orders }),
  });
}

export function useOrderAction(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (action: "pay" | "cancel") => {
      const params = { path: { id } };
      if (action === "pay") {
        const session = unwrap(await api.POST("/api/orders/{id}/pay/", { params }));
        if (session.checkout_url) window.location.assign(session.checkout_url);
        return session.order;
      }
      return unwrap(await api.POST("/api/orders/{id}/cancel/", { params }));
    },
    onSuccess: (order) => {
      qc.setQueryData(keys.order(id), order);
      qc.invalidateQueries({ queryKey: keys.orders });
    },
  });
}

// --- Advisor & stats ----------------------------------------------------------------

export function useAdvisor() {
  return useMutation({
    mutationFn: async (body: AdvisorRequest) => unwrap(await api.POST("/api/advisor/", { body })),
  });
}

export function useCategoryStats() {
  return useQuery({
    queryKey: ["stats", "categories"],
    queryFn: async () => unwrap(await api.GET("/api/stats/categories/")),
  });
}

export function usePopularComponents(limit = 10) {
  return useQuery({
    queryKey: ["stats", "popular", limit],
    queryFn: async () =>
      unwrap(await api.GET("/api/stats/popular-components/", { params: { query: { limit } } })),
  });
}

export function useTopPerCategory(top = 3) {
  return useQuery({
    queryKey: ["stats", "top", top],
    queryFn: async () =>
      unwrap(await api.GET("/api/stats/top-per-category/", { params: { query: { top } } })),
  });
}

export function usePricePosition(category: CategoryKind) {
  return useQuery({
    queryKey: ["stats", "price-position", category],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/stats/price-position/", { params: { query: { category } } }),
      ),
  });
}

// --- Price watches and Telegram alerts ----------------------------------------

type WatchTarget = { component?: number; build?: number };

export function useWatches(target: WatchTarget = {}, enabled = true) {
  return useQuery({
    queryKey: ["watches", target],
    queryFn: async () =>
      unwrap(await api.GET("/api/watches/", { params: { query: target } })),
    enabled,
  });
}

export function useSaveWatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      body,
    }: {
      id?: number;
      body: { component?: number; build?: number; threshold_percent?: number; target_price?: string | null };
    }) =>
      id
        ? unwrap(await api.PATCH("/api/watches/{id}/", { params: { path: { id } }, body }))
        : unwrap(await api.POST("/api/watches/", { body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watches"] }),
  });
}

export function useDeleteWatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      const result = await api.DELETE("/api/watches/{id}/", { params: { path: { id } } });
      if (!result.response.ok) unwrap(result);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watches"] }),
  });
}

/** Polls every 3 s while waiting for the user to press Start in the bot. */
export function useTelegram(enabled = true, waiting = false) {
  return useQuery({
    queryKey: ["telegram"],
    queryFn: async () => unwrap(await api.GET("/api/telegram/")),
    enabled,
    refetchInterval: waiting ? 3000 : false,
  });
}

export function useUpdateTelegram() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { enabled?: boolean; quiet_hours?: boolean; language?: "uk" | "en" }) =>
      unwrap(await api.PATCH("/api/telegram/", { body })),
    onSuccess: (data) => qc.setQueryData(["telegram"], data),
  });
}

export function useLinkTelegram() {
  return useMutation({
    mutationFn: async (language: "uk" | "en") =>
      unwrap(await api.POST("/api/telegram/link/", { body: { language } })),
  });
}

export function useUnlinkTelegram() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await api.DELETE("/api/telegram/");
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["telegram"] }),
  });
}
