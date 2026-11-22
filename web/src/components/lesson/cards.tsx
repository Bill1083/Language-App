"use client";

import * as React from "react";

import { AudioButton } from "@/components/audio-button";
import { RubyText } from "@/components/ruby-text";
import { Badge } from "@/components/ui/primitives";
import { GenderBadge } from "@/components/word-popover";
import { useMe } from "@/hooks/use-me";
import type { Exercise, Grammar, Lang, Vocab } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Minimal markdown for explanations: **bold**, *italic*, line breaks and "- " bullets. */
export function RichText({ text, className }: { text: string; className?: string }) {
  const inline = (s: string) =>
    s.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g).map((part, i) =>
      part.startsWith("**") ? (
        <strong key={i} className="font-semibold text-foreground">
          {part.slice(2, -2)}
        </strong>
      ) : part.startsWith("*") && part.length > 2 ? (
        <em key={i}>{part.slice(1, -1)}</em>
      ) : (
        <React.Fragment key={i}>{part}</React.Fragment>
      ),
    );
  const blocks = text.split(/\n{2,}/);
  return (
    <div className={cn("space-y-2.5", className)}>
      {blocks.map((b, i) => {
        const lines = b.split("\n");
        if (lines.every((l) => /^\s*[-•]\s/.test(l))) {
          return (
            <ul key={i} className="list-disc space-y-1 pl-5">
              {lines.map((l, j) => (
                <li key={j}>{inline(l.replace(/^\s*[-•]\s/, ""))}</li>
              ))}
            </ul>
          );
        }
        return (
          <p key={i}>
            {lines.map((l, j) => (
              <React.Fragment key={j}>
                {j > 0 && <br />}
                {inline(l)}
              </React.Fragment>
            ))}
          </p>
        );
      })}
    </div>
  );
}

function genderColor(gender: string | null | undefined, on: boolean) {
  if (!on) return "";
  if (gender === "m") return "text-masc";
  if (gender === "f") return "text-fem";
  return "";
}

export function VocabCard({ vocab, lang, autoPlay = true }: { vocab: Vocab; lang: Lang; autoPlay?: boolean }) {
  const { data: me } = useMe();
  const colors = me?.settings.gender_colors !== false;
  return (
    <div className="flex flex-col items-center text-center">
      <p className="text-sm font-bold uppercase tracking-wider text-primary">New word</p>
      {vocab.emoji && <div className="mt-5 text-6xl">{vocab.emoji}</div>}
      <div className="mt-5 flex items-center gap-3">
        <h2 className={cn("text-4xl font-extrabold tracking-tight sm:text-5xl", genderColor(vocab.gender, colors))}>
          <RubyText text={vocab.word} lang={lang} showRomaji={!vocab.romaji} />
        </h2>
        <AudioButton text={vocab.word} lang={lang} size="lg" autoPlay={autoPlay} />
      </div>
      {vocab.reading && lang === "ja" && !vocab.word.includes("{") && vocab.reading !== vocab.word && (
        <p className="mt-1 text-lg text-muted-foreground" lang="ja">
          {vocab.reading}
        </p>
      )}
      {vocab.romaji && <p className="mt-1 text-muted-foreground">{vocab.romaji}</p>}
      <div className="mt-3 flex flex-wrap items-center justify-center gap-1.5">
        {vocab.pos && <Badge>{vocab.pos}</Badge>}
        <GenderBadge gender={vocab.gender} />
        {vocab.plural && <Badge>pl. {vocab.plural}</Badge>}
      </div>
      <p className="mt-4 text-2xl font-semibold">{vocab.meaning}</p>
      {vocab.example && (
        <div className="mt-7 w-full max-w-md rounded-2xl border bg-card p-4 text-left">
          <div className="flex items-start gap-3">
            <p className="flex-1 text-lg">
              <RubyText text={vocab.example} lang={lang} />
            </p>
            <AudioButton text={vocab.example} lang={lang} size="sm" />
          </div>
          {vocab.example_translation && <p className="mt-1.5 text-sm text-muted-foreground">{vocab.example_translation}</p>}
        </div>
      )}
      {vocab.note && <p className="mt-4 max-w-md text-sm text-muted-foreground">💡 {vocab.note}</p>}
    </div>
  );
}

export function GrammarTable({ table, lang }: { table: NonNullable<Grammar["table"]>; lang: Lang }) {
  return (
    <div className="overflow-hidden rounded-xl border">
      {table.title && <p className="border-b bg-muted px-4 py-2 text-sm font-semibold">{table.title}</p>}
      <table className="w-full text-left text-[15px]" lang={lang}>
        {table.headers.length > 0 && (
          <thead className="bg-muted/60 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              {table.headers.map((h, i) => (
                <th key={i} className="px-4 py-2 font-semibold">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
        )}
        <tbody>
          {table.rows.map((row, i) => (
            <tr key={i} className="border-t">
              {row.map((cell, j) => (
                <td key={j} className={cn("px-4 py-2", j === 0 ? "text-muted-foreground" : "font-medium")}>
                  <RubyText text={cell} lang={lang} showRomaji={false} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function GrammarCard({ grammar, lang }: { grammar: Grammar; lang: Lang }) {
  return (
    <div className="w-full">
      <p className="text-sm font-bold uppercase tracking-wider text-primary">Grammar</p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <h2 className="text-2xl font-extrabold tracking-tight">{grammar.title}</h2>
        {grammar.politeness && (
          <Badge tone={grammar.politeness === "polite" ? "primary" : "warning"}>
            {grammar.politeness === "polite" ? "です/ます polite" : grammar.politeness === "plain" ? "plain / casual" : "polite & plain"}
          </Badge>
        )}
      </div>
      <RichText text={grammar.explanation} className="mt-3 text-[16px] leading-relaxed text-muted-foreground" />
      {!!grammar.examples?.length && (
        <ul className="mt-5 space-y-2.5">
          {grammar.examples.map((e, i) => (
            <li key={i} className="flex items-start gap-3 rounded-2xl border bg-card p-3.5">
              <AudioButton text={e.target} lang={lang} size="sm" />
              <div className="min-w-0">
                <p className="text-[17px] font-medium">
                  <RubyText text={e.target} lang={lang} />
                </p>
                <p className="text-sm text-muted-foreground">{e.english}</p>
              </div>
            </li>
          ))}
        </ul>
      )}
      {grammar.table && (
        <div className="mt-5">
          <GrammarTable table={grammar.table} lang={lang} />
        </div>
      )}
    </div>
  );
}

export function KanaCard({ ex }: { ex: Exercise }) {
  return (
    <div className="flex flex-col items-center text-center">
      <p className="text-sm font-bold uppercase tracking-wider text-primary">
        New {ex.script === "katakana" ? "katakana" : "hiragana"}
      </p>
      <div className="mt-6 flex size-44 items-center justify-center rounded-[2rem] border-2 bg-card font-jp text-[110px] leading-none shadow-sm" lang="ja">
        {ex.char}
      </div>
      <div className="mt-5 flex items-center gap-3">
        <p className="text-4xl font-black tracking-tight">{ex.romaji}</p>
        <AudioButton text={ex.audio_text ?? ex.char} lang="ja" autoPlay />
      </div>
      <p className="mt-5 max-w-sm text-[16px] text-muted-foreground">{ex.mnemonic}</p>
    </div>
  );
}

type KanjiWord = { word: string; reading?: string | null; meaning?: string | null };

/** Readings, labelled for learners: on = from Chinese (in compounds), kun = native Japanese. */
export function KanjiReadings({ on, kun }: { on?: string[]; kun?: string[] }) {
  if (!on?.length && !kun?.length) return null;
  return (
    <div className="flex flex-wrap justify-center gap-x-4 gap-y-1 text-sm">
      {!!on?.length && (
        <span>
          <span className="text-muted-foreground">In compounds </span>
          <span className="font-jp font-semibold" lang="ja">{on.join("・")}</span>
        </span>
      )}
      {!!kun?.length && (
        <span>
          <span className="text-muted-foreground">On its own </span>
          <span className="font-jp font-semibold" lang="ja">{kun.join("・")}</span>
        </span>
      )}
    </div>
  );
}

export function KanjiWords({ words }: { words?: KanjiWord[] }) {
  if (!words?.length) return null;
  return (
    <ul className="w-full max-w-sm divide-y rounded-2xl border bg-card text-left">
      {words.map((w) => (
        <li key={w.word} className="flex items-center gap-3 px-4 py-2.5">
          <span className="min-w-0 flex-1">
            <span className="block text-lg font-semibold" lang="ja"><RubyText text={w.word} lang="ja" showRomaji={false} /></span>
            {w.meaning && <span className="block text-sm text-muted-foreground">{w.meaning}</span>}
          </span>
          <AudioButton text={w.word} lang="ja" size="sm" />
        </li>
      ))}
    </ul>
  );
}

/** "New kanji" card shown in a lesson just before the first word that uses it. */
export function KanjiCard({ ex }: { ex: Exercise }) {
  return (
    <div className="flex flex-col items-center text-center">
      <p className="text-sm font-bold uppercase tracking-wider text-primary">New kanji</p>
      <div className="mt-6 flex size-40 items-center justify-center rounded-[2rem] border-2 bg-card font-jp text-[100px] leading-none shadow-sm sm:size-44 sm:text-[110px]" lang="ja">
        {ex.char}
      </div>
      <p className="mt-5 text-3xl font-black tracking-tight">{(ex.meanings ?? []).slice(0, 2).join(", ")}</p>
      {ex.hook && <p className="mt-2 max-w-sm text-[16px] text-muted-foreground">{ex.hook}</p>}
      {ex.parts?.length > 0 && (
        <p className="mt-2 text-sm text-muted-foreground">
          Built from <span className="font-jp text-base text-foreground" lang="ja">{ex.parts.join(" + ")}</span>
        </p>
      )}
      <div className="mt-4"><KanjiReadings on={ex.on} kun={ex.kun} /></div>
      {ex.words?.length > 0 && (
        <div className="mt-5 flex w-full flex-col items-center gap-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">In this lesson</p>
          <KanjiWords words={ex.words} />
        </div>
      )}
    </div>
  );
}

/** One card for the less common new kanji of a lesson (each still gets a review card). */
export function KanjiMoreCard({ ex }: { ex: Exercise }) {
  const items = (ex.kanji ?? []) as { char: string; meaning: string; word?: KanjiWord | null }[];
  return (
    <div className="flex flex-col items-center text-center">
      <p className="text-sm font-bold uppercase tracking-wider text-primary">Also new in this lesson</p>
      <p className="mt-2 max-w-sm text-sm text-muted-foreground">
        You&apos;ll see these in the words ahead. Each one gets its own review card once you finish the lesson.
      </p>
      <div className="mt-6 grid w-full max-w-sm grid-cols-3 gap-2.5">
        {items.map((k) => (
          <div key={k.char} className="rounded-2xl border bg-card px-2 py-3">
            <p className="font-jp text-4xl leading-tight" lang="ja">{k.char}</p>
            <p className="mt-1 text-sm font-semibold leading-tight">{k.meaning}</p>
            {k.word && (
              <p className="mt-1.5 text-sm" lang="ja"><RubyText text={k.word.word} lang="ja" showRomaji={false} /></p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
