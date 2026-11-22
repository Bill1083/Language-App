"use client";

import { RubyText } from "@/components/ruby-text";
import type { Lang, VideoLine } from "@/lib/types";
import { cn } from "@/lib/utils";

export type Mode = "full" | "kana" | "text";

/** Index of the line being spoken at `ms`: the last line that has started (-1 before the first). */
export function lineAt(lines: VideoLine[], ms: number): number {
  let lo = 0;
  let hi = lines.length - 1;
  let found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (lines[mid].start <= ms) {
      found = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return found;
}

export function LineText({ line, mode, lang, big, onWordTap }: {
  line: VideoLine; mode: Mode; lang: Lang; big?: boolean; onWordTap?: (w: string, el: HTMLElement) => void;
}) {
  const ja = lang === "ja";
  const text = mode === "kana" && ja ? (line.kana ?? line.text) : line.text;
  return (
    <div className={cn(big ? "space-y-1.5" : "space-y-0.5")}>
      <p className={cn(big ? "text-[22px] font-semibold leading-relaxed" : "text-[15px] leading-relaxed")} lang={lang}>
        <RubyText text={text} lang={lang} furigana={mode === "full" ? "always" : "never"} romaji="off" showRomaji={false}
          onWordTap={onWordTap} />
      </p>
      {mode === "full" && line.en && (
        <p className={cn("text-muted-foreground", big ? "text-[15px]" : "text-xs")}>{line.en}</p>
      )}
    </div>
  );
}
