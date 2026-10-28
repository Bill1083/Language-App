"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

export function LogoMark({ className }: { className?: string }) {
  // unique per instance: a gradient defined inside a display:none copy (the
  // hidden desktop sidebar) would otherwise blank out every other logo
  const id = `parlo-g-${React.useId().replace(/:/g, "")}`;
  return (
    <svg viewBox="0 0 48 48" className={cn("size-8", className)} aria-hidden>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="var(--lang)" />
          <stop offset="1" stopColor="color-mix(in oklab, var(--lang) 55%, #ff9a5c)" />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="44" height="44" rx="14" fill={`url(#${id})`} />
      <path
        d="M15 16.5c0-2 1.6-3.5 3.5-3.5h11c2 0 3.5 1.6 3.5 3.5v8c0 2-1.6 3.5-3.5 3.5h-6.2l-5 4.3c-.6.5-1.5.1-1.5-.7V28c-1.1-.4-1.8-1.5-1.8-2.7z"
        fill="white"
      />
      <circle cx="20" cy="20.5" r="1.7" fill="var(--lang)" />
      <circle cx="24" cy="20.5" r="1.7" fill="var(--lang)" />
      <circle cx="28" cy="20.5" r="1.7" fill="var(--lang)" />
    </svg>
  );
}

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <LogoMark />
      <span className="text-[19px] font-extrabold tracking-tight">Parlo</span>
    </span>
  );
}
