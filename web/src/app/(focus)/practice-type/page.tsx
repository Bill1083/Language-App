"use client";

import { useQueryClient } from "@tanstack/react-query";
import { CircleCheck, CircleX, Keyboard, PartyPopper, Sparkles, X } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { AudioButton } from "@/components/audio-button";
import { RubyText } from "@/components/ruby-text";
import { TargetInput } from "@/components/target-input";
import { Button } from "@/components/ui/button";
import { Badge, Card, Kbd, Progress, Skeleton } from "@/components/ui/primitives";
import { GenderBadge } from "@/components/word-popover";
import { usePracticeItems, type PracticeItem } from "@/hooks/queries";
import { useActiveLang } from "@/hooks/use-language";
import { ApiError, post } from "@/lib/api";
import { practiceCheck } from "@/lib/answer";
import { stripRuby } from "@/lib/japanese";
import { LANGS } from "@/lib/languages";
import { queueOffline } from "@/lib/outbox";
import { sounds } from "@/lib/sounds";
import { cn, formatDuration } from "@/lib/utils";

/** Right this many times in a row and the word leaves the list. */
const TO_MASTER = 2;
/** Where a word goes back into the list (a range, so repeats don't land in a fixed rhythm):
 *  soon after a miss, a little later after a first hit. */
const AGAIN_AFTER_MISS = [2, 3] as const;
const AGAIN_AFTER_HIT = [3, 5] as const;
const between = ([lo, hi]: readonly [number, number]) => lo + Math.floor(Math.random() * (hi - lo + 1));

type Entry = { item: PracticeItem; streak: number; misses: number; rated: boolean };
type Phase = "answer" | "close" | "result";

function Session() {
  const lang = useActiveLang();
  const params = useSearchParams();
  const router = useRouter();
  const qc = useQueryClient();
  const scope = {
    lessons: params.get("lessons"), units: params.get("units"), unit: params.get("unit"), level: params.get("level"),
    order: params.get("order") ?? "course", limit: params.get("limit") ?? "20",
  };
  const { data, isLoading } = usePracticeItems(lang, scope);

  const [entries, setEntries] = React.useState<Entry[]>([]);
  const [queue, setQueue] = React.useState<number[] | null>(null);
  const [phase, setPhase] = React.useState<Phase>("answer");
  const [typed, setTyped] = React.useState("");
  const [correct, setCorrect] = React.useState(false);
  const [finished, setFinished] = React.useState(false);
  const startedAt = React.useRef(Date.now());
  const shownAt = React.useRef(Date.now());
  const input = React.useRef<HTMLTextAreaElement>(null);

  const start = React.useCallback((items: PracticeItem[]) => {
    setEntries(items.map((item) => ({ item, streak: 0, misses: 0, rated: false })));
    setQueue(items.map((_, i) => i));
    setPhase("answer");
    setTyped("");
    setFinished(false);
    startedAt.current = shownAt.current = Date.now();
  }, []);

  React.useEffect(() => {
    if (data && queue === null) start(data.items);
  }, [data, queue, start]);

  const index = queue?.[0];
  const entry = index != null ? entries[index] : undefined;
  const item = entry?.item;

  const rate = React.useCallback((card_id: number, rating: number) => {
    const body = { card_id, rating, elapsed_ms: Date.now() - shownAt.current, reviewed_at: new Date().toISOString() };
    post("/srs/review", body).catch((e) => {
      if (e instanceof ApiError && e.offline) queueOffline("/srs/review", body);
    });
  }, []);

  const finish = React.useCallback(async (count: number) => {
    setFinished(true);
    sounds.complete();
    const body = { lang, reviewed: count, seconds: Math.round((Date.now() - startedAt.current) / 1000) };
    try {
      await post("/srs/session", body);
    } catch (e) {
      if (e instanceof ApiError && e.offline) queueOffline("/srs/session", body);
    }
    void qc.invalidateQueries({ queryKey: ["deck"] });
    void qc.invalidateQueries({ queryKey: ["dashboard"] });
    void qc.invalidateQueries({ queryKey: ["practice-levels"] });
  }, [lang, qc]);

  const check = React.useCallback(() => {
    if (!entry || index == null || phase === "result" || !typed.trim()) return;
    const verdict = practiceCheck(typed, entry.item.accepted, lang, entry.item.kind);
    if (verdict === "close" && phase === "answer") {
      setPhase("close"); // one more go
      sounds.wrong();
      requestAnimationFrame(() => input.current?.focus());
      return;
    }
    const right = verdict === "correct";
    if (!entry.rated) rate(entry.item.card_id, right ? (phase === "close" ? 2 : 3) : 1);
    setEntries((all) =>
      all.map((e, i) =>
        i === index ? { ...e, rated: true, streak: right ? e.streak + 1 : 0, misses: e.misses + (right ? 0 : 1) } : e,
      ),
    );
    setCorrect(right);
    setPhase("result");
    if (right) sounds.correct();
    else sounds.wrong();
  }, [entry, index, phase, typed, lang, rate]);

  const next = React.useCallback(() => {
    if (!queue || index == null || !entry) return;
    const rest = queue.slice(1);
    const done = correct && entry.streak >= TO_MASTER;
    if (!done) {
      const at = Math.min(between(correct ? AGAIN_AFTER_HIT : AGAIN_AFTER_MISS), rest.length);
      rest.splice(at, 0, index);
    }
    setQueue(rest);
    setTyped("");
    setPhase("answer");
    shownAt.current = Date.now();
    if (!rest.length) void finish(entries.length);
    else requestAnimationFrame(() => input.current?.focus());
  }, [queue, index, entry, correct, entries.length, finish]);

  React.useEffect(() => {
    if (phase !== "result") return;
    const h = (e: KeyboardEvent) => {
      if (e.key === "Enter") {
        e.preventDefault();
        next();
      }
    };
    // wait a tick so the Enter that checked the answer doesn't also continue
    const t = setTimeout(() => window.addEventListener("keydown", h), 50);
    return () => {
      clearTimeout(t);
      window.removeEventListener("keydown", h);
    };
  }, [phase, next]);

  if (isLoading || queue === null) {
    return <div className="mx-auto max-w-xl space-y-4 p-6"><Skeleton className="h-4" /><Skeleton className="h-80" /></div>;
  }

  const total = entries.length;
  const mastered = total - new Set(queue).size;

  if (finished || !total) {
    const firstTry = entries.filter((e) => e.misses === 0).length;
    const tricky = entries.filter((e) => e.misses > 0);
    return (
      <div className="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-4 px-6 py-10 text-center">
        <div className="mx-auto flex size-20 items-center justify-center rounded-3xl bg-primary text-primary-foreground">
          {total ? <PartyPopper className="size-10" /> : <Keyboard className="size-10" />}
        </div>
        <h1 className="text-3xl font-black">{total ? "List cleared!" : "Nothing to practise"}</h1>
        {total ? (
          <p className="text-muted-foreground">
            {total} {total === 1 ? "item" : "items"} in {formatDuration((Date.now() - startedAt.current) / 1000)} ·{" "}
            {Math.round((firstTry / total) * 100)}% right first time · +{total} XP
          </p>
        ) : (
          <p className="text-muted-foreground">Finish a lesson in these blocks first, then come back.</p>
        )}
        {tricky.length > 0 && (
          <div className="text-left">
            <p className="mb-2 text-sm font-semibold text-muted-foreground">Worth another look</p>
            <ul className="space-y-1.5">
              {tricky.map(({ item: it, misses }) => (
                <li key={it.card_id} className="flex items-center gap-3 rounded-xl border bg-card px-3.5 py-2.5 text-sm">
                  <span className="min-w-0 flex-1 truncate text-muted-foreground">{it.prompt}</span>
                  <span className="font-semibold" lang={it.kind === "kana" ? undefined : lang}>
                    {it.kind === "kana" ? it.answer : <RubyText text={it.answer} lang={lang} showRomaji={false} />}
                  </span>
                  <Badge tone="danger">{misses}×</Badge>
                </li>
              ))}
            </ul>
          </div>
        )}
        <div className="mt-4 flex w-full flex-col gap-2.5">
          {total > 0 && <Button size="lg" onClick={() => start(entries.map((e) => e.item))}>Practise again</Button>}
          <Button size="lg" variant="outline" asChild><Link href="/practice">Choose other blocks</Link></Button>
        </div>
      </div>
    );
  }

  const kana = item!.kind === "kana";
  const languageName = LANGS[lang].name;
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="safe-top mx-auto flex w-full max-w-2xl items-center gap-3 px-4 py-3 sm:px-6">
        <Button variant="ghost" size="icon" aria-label="Stop practising" onClick={() => router.push("/practice")}>
          <X />
        </Button>
        <Progress value={total ? mastered / total : 0} className="h-3 flex-1" />
        <span className="text-sm font-semibold tabular-nums text-muted-foreground" aria-label="Left to clear">
          {total - mastered} left
        </span>
      </header>

      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col px-4 pb-6 sm:px-6">
        <div className="flex items-center justify-between py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          <span>
            {data?.title && <span className="text-primary-strong">{data.title} · </span>}
            {kana ? "Type the romaji" : `Type it in ${languageName}`}
          </span>
          <span className="flex items-center gap-1" aria-label={`${entry!.streak} of ${TO_MASTER} in a row`}>
            {Array.from({ length: TO_MASTER }, (_, i) => (
              <span key={i} className={cn("size-2.5 rounded-full", i < entry!.streak ? "bg-success" : "bg-muted")} />
            ))}
          </span>
        </div>

        <Card key={`${index}-${queue.length}`} className="flex min-h-[15rem] animate-rise flex-col items-center justify-center gap-3 p-6 text-center shadow-lg sm:p-10">
          {kana ? (
            <p className="font-jp text-[96px] font-medium leading-none" lang="ja">{item!.prompt}</p>
          ) : (
            <>
              <p className="text-3xl font-extrabold">{item!.prompt}</p>
              <div className="flex gap-1.5">
                {item!.pos && <Badge>{item!.pos}</Badge>}
                <GenderBadge gender={item!.gender ?? undefined} />
              </div>
            </>
          )}
        </Card>

        <div className="mt-5 space-y-3">
          {phase !== "result" ? (
            <>
              <TargetInput
                ref={input}
                lang={kana ? "en" : lang}
                value={typed}
                onChange={setTyped}
                onSubmit={check}
                autoFocus
                placeholder={kana ? "Romaji, e.g. ka" : lang === "ja" ? "In kana, kanji or romaji" : `The ${languageName} word`}
                className={cn(phase === "close" && "border-warning focus:border-warning")}
              />
              {phase === "close" && (
                <p className="flex items-center gap-2 rounded-xl bg-warning-soft px-3.5 py-2.5 text-sm font-semibold text-warning" role="status">
                  <Sparkles className="size-4" /> Close! Check your spelling — one more try.
                </p>
              )}
            </>
          ) : (
            <div
              role="status"
              className={cn("space-y-2 rounded-2xl border-2 p-4", correct ? "border-success/40 bg-success-soft" : "border-danger/40 bg-danger-soft")}
            >
              <p className={cn("flex items-center gap-2 text-lg font-extrabold", correct ? "text-success" : "text-danger")}>
                {correct ? <CircleCheck className="size-6" /> : <CircleX className="size-6" />}
                {correct
                  ? entry!.streak >= TO_MASTER ? "Got it — cleared!" : "Correct! Once more to clear it."
                  : "Not quite — it'll come back soon."}
              </p>
              <div className="flex items-center gap-3">
                <p className="text-2xl font-extrabold" lang={kana ? undefined : lang}>
                  {kana ? item!.answer : <RubyText text={item!.answer} lang={lang} />}
                </p>
                {item!.audio_text && <AudioButton text={stripRuby(item!.audio_text)} lang={lang} autoPlay />}
              </div>
              {!correct && <p className="text-sm text-muted-foreground">You typed: <span className="line-through">{typed}</span></p>}
              {kana && item!.hint && <p className="text-sm text-muted-foreground">{item!.hint}</p>}
              {!kana && item!.example && (
                <p className="text-sm">
                  <RubyText text={item!.example} lang={lang} showRomaji={false} />
                  {item!.example_translation && <span className="block text-muted-foreground">{item!.example_translation}</span>}
                </p>
              )}
            </div>
          )}
        </div>
      </main>

      <footer className="safe-bottom sticky bottom-0 border-t bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-2xl px-4 py-4 sm:px-6">
          {phase === "result" ? (
            <Button size="xl" className="w-full" variant={correct ? "success" : "danger"} onClick={next}>
              Continue <Kbd className="ml-1 bg-white/20 text-white">Enter</Kbd>
            </Button>
          ) : (
            <Button size="xl" className="w-full" disabled={!typed.trim()} onClick={check}>
              Check <Kbd className="ml-1 bg-white/20 text-white">Enter</Kbd>
            </Button>
          )}
        </div>
      </footer>
    </div>
  );
}

export default function PracticeTypePage() {
  return (
    <React.Suspense>
      <Session />
    </React.Suspense>
  );
}
