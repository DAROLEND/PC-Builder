import type { CategoryKind } from "../api/types";

const PATHS: Record<CategoryKind, React.ReactNode> = {
  cpu: (
    <>
      <rect x="6" y="6" width="12" height="12" rx="2" />
      <rect x="9.5" y="9.5" width="5" height="5" rx="1" />
      <path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3" />
    </>
  ),
  motherboard: (
    <>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <rect x="6" y="6" width="5" height="5" rx="1" />
      <path d="M14 6h4M14 9h4M6 14h12M6 17h7M16 17h2" />
    </>
  ),
  ram: (
    <>
      <rect x="2" y="7" width="20" height="9" rx="1.5" />
      <path d="M6 10v3M10 10v3M14 10v3M18 10v3M4 16v2M8 16v2M12 16v2M16 16v2M20 16v2" />
    </>
  ),
  gpu: (
    <>
      <rect x="2" y="6" width="20" height="11" rx="2" />
      <circle cx="8" cy="11.5" r="3" />
      <circle cx="16" cy="11.5" r="3" />
      <path d="M4 17v2h5v-2" />
    </>
  ),
  storage: (
    <>
      <rect x="3" y="8" width="18" height="8" rx="1.5" />
      <path d="M6 11h7M6 13h4" />
      <circle cx="17.5" cy="12" r="1" />
    </>
  ),
  psu: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <circle cx="12" cy="12" r="4.5" />
      <path d="M12 7.5v9M7.5 12h9" />
    </>
  ),
  case: (
    <>
      <rect x="6" y="2" width="12" height="20" rx="2" />
      <path d="M9 5.5h6M9 8h6" />
      <circle cx="12" cy="15" r="3" />
    </>
  ),
  cooler: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 12c0-4 1.5-6 4-6.2M12 12c4 0 6 1.5 6.2 4M12 12c0 4-1.5 6-4 6.2M12 12c-4 0-6-1.5-6.2-4" />
      <circle cx="12" cy="12" r="1.3" />
    </>
  ),
};

export function CategoryIcon({ kind, size = 22 }: { kind: CategoryKind; size?: number }) {
  return (
    <svg
      className="icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {PATHS[kind]}
    </svg>
  );
}

export function CheckIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </svg>
  );
}

export function SparkIcon({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M12 2l1.9 5.6L19.5 9.5l-5.6 1.9L12 17l-1.9-5.6L4.5 9.5l5.6-1.9L12 2zM19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15z" />
    </svg>
  );
}

export function BellIcon({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
      <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
    </svg>
  );
}

export function TelegramIcon({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M21.9 4.6 18.7 19.7c-.2 1-.9 1.3-1.8.8l-4.8-3.6-2.3 2.2c-.3.3-.5.5-1 .5l.3-4.9 8.9-8c.4-.3-.1-.5-.6-.2L6.4 13.4 1.7 12c-1-.3-1-1 .2-1.5l18.5-7.1c.9-.3 1.6.2 1.5 1.2Z" />
    </svg>
  );
}
