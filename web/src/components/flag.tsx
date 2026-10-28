import type { Lang } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Inline SVG flags — emoji flags don't render on Windows. */
export function Flag({ lang, className }: { lang: Lang; className?: string }) {
  const common = cn("inline-block h-[0.95em] w-[1.35em] shrink-0 rounded-[3px] align-[-0.12em] shadow-[0_0_0_1px_rgba(0,0,0,0.12)]", className);
  if (lang === "fr")
    return (
      <svg viewBox="0 0 3 2" className={common} aria-hidden>
        <rect width="1" height="2" fill="#0055a4" />
        <rect x="1" width="1" height="2" fill="#fff" />
        <rect x="2" width="1" height="2" fill="#ef4135" />
      </svg>
    );
  if (lang === "it")
    return (
      <svg viewBox="0 0 3 2" className={common} aria-hidden>
        <rect width="1" height="2" fill="#009246" />
        <rect x="1" width="1" height="2" fill="#fff" />
        <rect x="2" width="1" height="2" fill="#ce2b37" />
      </svg>
    );
  return (
    <svg viewBox="0 0 3 2" className={common} aria-hidden>
      <rect width="3" height="2" fill="#fff" />
      <circle cx="1.5" cy="1" r="0.6" fill="#bc002d" />
    </svg>
  );
}
