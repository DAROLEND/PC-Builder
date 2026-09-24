import { useLayoutEffect, useRef } from "react";
import type { TextareaHTMLAttributes } from "react";

/**
 * A textarea that grows with its text instead of a resize handle: starts at
 * `rows`, gets taller as the user types, and scrolls only past the CSS
 * max-height. Height is recalculated whenever the value changes.
 */
export function AutoTextarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto"; // shrink first, so deleting text makes it smaller again
    const borders = el.offsetHeight - el.clientHeight;
    const max = parseFloat(getComputedStyle(el).maxHeight) || Infinity;
    const wanted = el.scrollHeight + borders;
    el.style.height = `${Math.min(wanted, max)}px`;
    el.style.overflowY = wanted > max ? "auto" : "hidden";
  }, [props.value]);

  return <textarea ref={ref} {...props} className={`auto-grow ${props.className ?? ""}`.trim()} />;
}
