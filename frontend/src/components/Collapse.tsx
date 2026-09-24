import { useState } from "react";
import type { ReactNode } from "react";

/**
 * Animated expand/collapse of content with unknown height.
 *
 * The wrapper transitions `grid-template-rows` between 0fr and 1fr, which
 * animates to the content's natural height without measuring it. Children
 * stay mounted until the closing transition ends, so the content slides
 * away instead of disappearing at once.
 */
export function Collapse({ open, children }: { open: boolean; children: ReactNode }) {
  const [mounted, setMounted] = useState(open);
  if (open && !mounted) setMounted(true); // derived during render: no extra frame

  return (
    <div
      className={`collapse ${open ? "open" : ""}`}
      aria-hidden={!open}
      onTransitionEnd={(event) => {
        if (event.target === event.currentTarget && !open) setMounted(false);
      }}
    >
      <div className="collapse-inner">{mounted && children}</div>
    </div>
  );
}
