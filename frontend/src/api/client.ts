/**
 * Typed API client.
 *
 * `paths` is generated from the backend's OpenAPI schema (`npm run gen:api`),
 * so a renamed field or a changed endpoint on the backend breaks `tsc` here
 * instead of breaking the UI at runtime.
 */
import createClient from "openapi-fetch";

import { langStore } from "../i18n/context";
import type { paths } from "./schema";
import { tokenStore } from "./tokens";

const baseUrl = import.meta.env.VITE_API_URL ?? "";

let refreshing: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  const refresh = tokenStore.refresh;
  if (!refresh) return null;
  const response = await fetch(`${baseUrl}/api/auth/token/refresh/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh }),
  });
  if (!response.ok) {
    tokenStore.clear();
    return null;
  }
  const data = (await response.json()) as { access: string; refresh?: string };
  tokenStore.set(data.access, data.refresh ?? refresh);
  return data.access;
}

/**
 * Adds the bearer token and transparently retries once after refreshing an
 * expired access token. Concurrent 401s share a single refresh request.
 */
async function authFetch(request: Request): Promise<Response> {
  // Django picks the language of its own messages from this header.
  request.headers.set("Accept-Language", langStore.get());
  const retry = request.clone();
  const access = tokenStore.access;
  if (access) request.headers.set("Authorization", `Bearer ${access}`);

  const response = await fetch(request);
  if (response.status !== 401 || !tokenStore.refresh) return response;

  refreshing ??= refreshAccessToken().finally(() => {
    refreshing = null;
  });
  const fresh = await refreshing;
  if (!fresh) return response;
  retry.headers.set("Authorization", `Bearer ${fresh}`);
  return fetch(retry);
}

export const api = createClient<paths>({ baseUrl, fetch: authFetch });

/** DRF error body: field → messages, or {detail}. */
export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, body: unknown) {
    super(ApiError.describe(body) || `Request failed with status ${status}`);
    this.status = status;
    this.body = body;
  }

  static describe(body: unknown): string {
    if (!body || typeof body !== "object") return "";
    return Object.entries(body as Record<string, unknown>)
      .filter(([key]) => key !== "compatibility")
      .map(([key, value]) => {
        const text = Array.isArray(value) ? value.join(" ") : String(value);
        return key === "detail" || key === "non_field_errors" ? text : `${key}: ${text}`;
      })
      .join("\n");
  }
}

/** Turn an openapi-fetch result into data-or-throw, which is what TanStack Query wants. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || !result.response.ok) {
    throw new ApiError(result.response.status, result.error);
  }
  return result.data as T;
}
