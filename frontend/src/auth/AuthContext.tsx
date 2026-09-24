import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useSyncExternalStore } from "react";
import type { ReactNode } from "react";

import { api, unwrap } from "../api/client";
import { keys } from "../api/hooks";
import { tokenStore } from "../api/tokens";
import { AuthContext } from "./useAuth";
import type { AuthState } from "./useAuth";

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const access = useSyncExternalStore(tokenStore.subscribe, () => tokenStore.access);

  const me = useQuery({
    queryKey: [...keys.me, access],
    queryFn: async () => unwrap(await api.GET("/api/auth/me/")),
    enabled: Boolean(access),
    retry: false,
    staleTime: 5 * 60 * 1000,
  });

  const login = useCallback(
    async (username: string, password: string) => {
      const tokens = unwrap(
        await api.POST("/api/auth/token/", { body: { username, password } }),
      );
      tokenStore.set(tokens.access, tokens.refresh);
      // Anything cached as an anonymous user (e.g. build lists) is now stale.
      await qc.invalidateQueries();
    },
    [qc],
  );

  const register = useCallback(
    async (username: string, email: string, password: string) => {
      unwrap(await api.POST("/api/auth/register/", { body: { username, email, password } }));
      await login(username, password);
    },
    [login],
  );

  const logout = useCallback(() => {
    tokenStore.clear();
    qc.clear();
  }, [qc]);

  const value = useMemo<AuthState>(
    () => ({
      user: access ? (me.data ?? null) : null,
      isLoading: Boolean(access) && me.isLoading,
      login,
      register,
      logout,
    }),
    [access, me.data, me.isLoading, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
