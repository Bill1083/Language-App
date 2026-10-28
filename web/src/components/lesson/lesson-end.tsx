"use client";

import { ArrowRight, Clock, Flame, PartyPopper, RotateCcw, Target, Trophy, Zap } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { RubyText } from "@/components/ruby-text";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/primitives";
import { sounds } from "@/lib/sounds";
import type { CompleteResult, Lang } from "@/lib/types";
import { cn, formatDuration } from "@/lib/utils";

function useCountUp(target: number, ms = 900) {
  const [v, setV] = React.useState(0);
  React.useEffect(() => {
    const start = performance.now();
    let raf = 0;
    const tick = (t: number) => {
      const p = Math.min(1, (t - start) / ms);
      setV(Math.round(target * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return v;
}

function Burst() {
  const pieces = React.useMemo(
    () => Array.from({ length: 18 }, (_, i) => ({ i, x: (Math.random() - 0.5) * 320, y: -80 - Math.random() * 160, r: Math.random() * 360 })),
    [],
  );
  const colors = ["var(--lang)", "var(--gold)", "var(--success)", "var(--flame)", "var(--fem)"];
  return (
    <div aria-hidden className="pointer-events-none absolute left-1/2 top-24">
      {pieces.map((p) => (
        <span
          key={p.i}
          className="absolute block h-3 w-1.5 rounded-sm opacity-0"
          style={{
            background: colors[p.i % colors.length],
            animation: `burst-${p.i} 1.1s cubic-bezier(.2,.8,.3,1) ${p.i * 18}ms forwards`,
          }}
        >
          <style>{`@keyframes burst-${p.i}{0%{opacity:1;transform:translate(0,0) rotate(0)}100%{opacity:0;transform:translate(${p.x}px,${p.y + 260}px) rotate(${p.r}deg)}}`}</style>
        </span>
      ))}
    </div>
  );
}

export type Mistake = { prompt: string; answer: string | null };

export function LessonEnd({
  result,
  lang,
  seconds,
  mistakes,
  nextHref,
  onRetry,
}: {
  result: CompleteResult;
  lang: Lang;
  seconds: number;
  mistakes: Mistake[];
  nextHref: string | null;
  onRetry: () => void;
}) {
  const xp = useCountUp(result.xp);
  const passed = result.passed;
  React.useEffect(() => {
    if (passed) sounds.complete();
    else sounds.wrong();
  }, [passed]);

  return (
    <div className="relative mx-auto flex min-h-dvh max-w-xl flex-col px-4 pb-8 pt-10 sm:px-6">
      {passed && <Burst />}
      <div className="flex animate-rise flex-col items-center text-center">
        <div
          className={cn(
            "flex size-24 items-center justify-center rounded-[1.75rem] text-white shadow-lg",
            passed ? (result.accuracy >= 0.999 ? "bg-gold" : "bg-primary") : "bg-muted text-muted-foreground",
          )}
        >
          {result.is_test ? <Trophy className="size-12" /> : <PartyPopper className="size-12" />}
        </div>
        <h1 className="mt-6 text-3xl font-black tracking-tight">
          {!passed
            ? "So close!"
            : result.level_up
              ? `Welcome to ${result.level_up.to}!`
              : result.accuracy >= 0.999
                ? "Perfect lesson!"
                : result.is_test
                  ? "Test passed!"
                  : "Lesson complete!"}
        </h1>
        <p className="mt-2 text-muted-foreground">
          {!passed
            ? `You need ${Math.round(result.pass_mark * 100)}% to pass — you got ${Math.round(result.accuracy * 100)}%. Have another go!`
            : result.level_up
              ? `You passed the ${result.level_up.from} level test. ${result.level_up.to} is now unlocked.`
              : result.goal_just_met
                ? "And that's your daily goal done. 🎯"
                : "Every lesson makes the next conversation easier."}
        </p>
      </div>

      <div className="mt-8 grid grid-cols-3 gap-3">
        <Card className="flex flex-col items-center gap-1 p-4">
          <Zap className="size-5 text-gold" />
          <span className="text-2xl font-black tabular-nums">+{xp}</span>
          <span className="text-xs font-semibold text-muted-foreground">XP</span>
        </Card>
        <Card className="flex flex-col items-center gap-1 p-4">
          <Target className="size-5 text-success" />
          <span className="text-2xl font-black tabular-nums">{Math.round(result.accuracy * 100)}%</span>
          <span className="text-xs font-semibold text-muted-foreground">Accuracy</span>
        </Card>
        <Card className="flex flex-col items-center gap-1 p-4">
          <Clock className="size-5 text-primary" />
          <span className="text-2xl font-black tabular-nums">{formatDuration(seconds)}</span>
          <span className="text-xs font-semibold text-muted-foreground">Time</span>
        </Card>
      </div>

      {result.streak > 0 && (
        <p className="mt-4 flex items-center justify-center gap-1.5 text-sm font-semibold text-flame">
          <Flame className="size-4 fill-flame/25" /> {result.streak}-day streak
          {result.used_freeze && <span className="font-normal text-muted-foreground"> · a streak freeze covered yesterday</span>}
        </p>
      )}

      {result.achievements.length > 0 && (
        <div className="mt-6 space-y-2">
          {result.achievements.map((a) => (
            <Card key={a.key} className="flex items-center gap-3 border-gold/40 bg-gold-soft p-3.5">
              <span className="text-2xl">{a.icon}</span>
              <span>
                <span className="block font-bold">Achievement: {a.title}</span>
                <span className="block text-sm text-muted-foreground">{a.description}</span>
              </span>
            </Card>
          ))}
        </div>
      )}

      {result.new_words.length > 0 && (
        <div className="mt-6">
          <h2 className="mb-2 text-sm font-semibold text-muted-foreground">New words added to your review deck</h2>
          <div className="flex flex-wrap gap-2">
            {result.new_words.map((w) => (
              <span key={w.id} className="rounded-xl border bg-card px-3 py-1.5 text-sm">
                <span className="font-semibold">
                  <RubyText text={w.ruby ?? w.lemma} lang={lang} showRomaji={false} />
                </span>{" "}
                <span className="text-muted-foreground">· {w.meaning}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {mistakes.length > 0 && (
        <div className="mt-6">
          <h2 className="mb-2 text-sm font-semibold text-muted-foreground">Worth another look</h2>
          <ul className="space-y-2">
            {mistakes.slice(0, 6).map((m, i) => (
              <li key={i} className="rounded-xl border bg-card px-3.5 py-2.5 text-sm">
                <span className="text-muted-foreground">{m.prompt}</span>
                {m.answer && (
                  <span className="mt-0.5 block font-semibold" lang={lang}>
                    <RubyText text={m.answer} lang={lang} showRomaji={false} />
                  </span>
                )}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-muted-foreground">These are in your Mistakes deck for review.</p>
        </div>
      )}

      <div className="mt-auto flex flex-col gap-2.5 pt-10 sm:flex-row">
        {passed && nextHref ? (
          <Button asChild size="xl" className="flex-1">
            <Link href={nextHref}>
              Next lesson <ArrowRight />
            </Link>
          </Button>
        ) : !passed ? (
          <Button size="xl" className="flex-1" onClick={onRetry}>
            <RotateCcw /> Try again
          </Button>
        ) : null}
        <Button asChild size="xl" variant="outline" className="flex-1">
          <Link href="/learn">Back to course</Link>
        </Button>
      </div>
    </div>
  );
}
