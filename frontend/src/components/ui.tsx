import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { ApiError } from "../api/client";
import { useAuth } from "../auth/useAuth";

export function ErrorMessage({ error }: { error: unknown }) {
  if (!error) return null;
  const text =
    error instanceof ApiError ? error.message : error instanceof Error ? error.message : "Error";
  return (
    <div className="alert error" role="alert">
      {text.split("\n").map((line) => (
        <div key={line}>{line}</div>
      ))}
    </div>
  );
}

/** Shimmering placeholders instead of a bare "Loading…" line. */
export function Loading({ rows = 3, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div className="skeleton-stack" aria-busy="true" aria-label={label}>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton" style={{ width: `${92 - i * 14}%` }} />
      ))}
    </div>
  );
}

export function SkeletonGrid({ count = 6 }: { count?: number }) {
  return (
    <div className="grid" aria-busy="true">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="card skeleton-card">
          <div className="skeleton" style={{ width: "40%" }} />
          <div className="skeleton tall" style={{ width: "85%" }} />
          <div className="skeleton" style={{ width: "65%" }} />
          <div className="skeleton" style={{ width: "30%" }} />
        </div>
      ))}
    </div>
  );
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth();
  const location = useLocation();
  if (isLoading) return <Loading />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}
