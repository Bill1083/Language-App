"use client";

import * as React from "react";

import { useKnownKanji } from "@/hooks/queries";
import { useMe } from "@/hooks/use-me";
import { hasKanji, romajiFor, segmentWords, stripOpenRuby, type RubyToken } from "@/lib/japanese";
import type { Lang } from "@/lib/types";
import { cn } from "@/lib/utils";

type FuriganaMode = "always" | "new" | "never";

function Token({ t, mode, known }: { t: RubyToken; mode: FuriganaMode; known: string }) {
  if (!t.reading) return <>{t.base}</>;
  const familiar = mode === "new" && [...t.base].filter(hasKanji).every((ch) => known.includes(ch));
  if (mode === "never" || familiar) return <>{t.base}</>;
  return (
    <ruby>
      {t.base}
      <rp>(</rp>
      <rt>{t.reading}</rt>
      <rp>)</rp>
    </ruby>
  );
}

export function useJapaneseDisplay(override?: { furigana?: FuriganaMode; romaji?: "auto" | "on" | "off" }) {
  const { data: me } = useMe();
  const { data: kanji } = useKnownKanji("ja");
  const furigana = (override?.furigana ?? me?.settings.furigana ?? "always") as FuriganaMode;
  const romajiPref = override?.romaji ?? me?.settings.romaji ?? "auto";
  const ja = me?.enrolments.find((e) => e.language_code === "ja");
  // "auto": on while the learner is in the first units of A1, then off.
  const romaji = romajiPref === "on" || (romajiPref === "auto" && (!ja || ja.current_level === "A1") && (kanji?.count ?? 0) < 25);
  return { furigana, romaji, known: kanji?.kanji ?? "" };
}

type Props = {
  text: string;
  lang: Lang;
  className?: string;
  /** tap any word → WordPopover (handled by parent) */
  onWordTap?: (word: string, anchor: HTMLElement) => void;
  streaming?: boolean;
  furigana?: FuriganaMode;
  romaji?: "auto" | "on" | "off";
  showRomaji?: boolean;
};

/** Renders target-language text: Japanese with <ruby> furigana and optional
 *  romaji line (per user settings), every word optionally tappable. */
export function RubyText({ text, lang, className, onWordTap, streaming, furigana, romaji, showRomaji = true }: Props) {
  const display = useJapaneseDisplay({ furigana, romaji });
  const source = streaming ? stripOpenRuby(text) : text;
  const spans = React.useMemo(() => segmentWords(source, lang), [source, lang]);
  const isJa = lang === "ja";

  const content = spans.map((s, i) => {
    const inner = s.tokens.map((t, j) => <Token key={j} t={t} mode={display.furigana} known={display.known} />);
    if (!onWordTap || !s.isWord || streaming) return <React.Fragment key={i}>{inner}</React.Fragment>;
    return (
      <span
        key={i}
        role="button"
        tabIndex={0}
        onClick={(e) => onWordTap(s.text, e.currentTarget)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onWordTap(s.text, e.currentTarget);
          }
        }}
        className="cursor-pointer rounded-[4px] decoration-primary/40 decoration-dotted underline-offset-[5px] transition hover:bg-primary/10 hover:underline focus-visible:bg-primary/10"
      >
        {inner}
      </span>
    );
  });

  return (
    <span className={cn("inline", className)} lang={lang}>
      {/* extra line height only when there is furigana to make room for */}
      <span className={cn(isJa && source.includes("{") && "leading-[2.1]")}>{content}</span>
      {isJa && showRomaji && display.romaji && !streaming && (
        <span className="mt-0.5 block text-[0.78em] font-normal leading-snug text-muted-foreground" lang="ja-Latn">
          {romajiFor(text)}
        </span>
      )}
    </span>
  );
}
