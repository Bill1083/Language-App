"use client";

import { Brain, CircleAlert, Layers, Sparkles } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Card, Skeleton } from "@/components/ui/primitives";
import { useDeckStats } from "@/hooks/queries";
import { useActiveLang } from "@/hooks/use-language";
import { LANGS } from "@/lib/languages";

const DAYS = ["Today", "Tomorrow"];

export default function ReviewPage() {
  const lang = useActiveLang();
  const { data, isLoading } = useDeckStats(lang);
  if (isLoading || !data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-48" />
        <Skeleton className="h-48" />
        <Skeleton className="h-32" />
      </div>
    );
  }
  const total = data.counts.due + data.counts.new;
  const max = Math.max(1, ...data.forecast);
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight sm:text-3xl">Review</h1>
        <p className="mt-1 text-muted-foreground">
          Spaced repetition brings each {LANGS[lang].name} word back right before you&apos;d forget it.
        </p>
      </div>

      <Card className="overflow-hidden">
        <div className="flex flex-col items-center gap-2 bg-primary-soft px-6 py-8 text-center">
          <Layers className="size-8 text-primary" />
          <p className="text-5xl font-black tabular-nums">{total}</p>
          <p className="text-sm font-semibold text-muted-foreground">
            {data.counts.due} due · {data.counts.new} new
          </p>
          <Button asChild size="xl" className="mt-3 w-full max-w-xs" disabled={!total}>
            <Link href={total ? "/review-session" : "#"} aria-disabled={!total}>
              {total ? "Start review" : "All done for now"}
            </Link>
          </Button>
        </div>
        <div className="grid grid-cols-2 divide-x border-t">
          <div className="p-4 text-center">
            <p className="text-2xl font-bold tabular-nums">{data.total}</p>
            <p className="text-xs font-semibold text-muted-foreground">Cards in deck</p>
          </div>
          <div className="p-4 text-center">
            <p className="text-2xl font-bold tabular-nums">{data.mistakes}</p>
            <p className="text-xs font-semibold text-muted-foreground">Mistake cards</p>
          </div>
        </div>
      </Card>

      <Card className="flex items-center gap-4 p-5">
        <span className="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-danger-soft text-danger">
          <CircleAlert className="size-6" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-bold">Mistakes deck</p>
          <p className="text-sm text-muted-foreground">Drill only the things you got wrong in lessons and conversations.</p>
        </div>
        <Button asChild variant="outline" disabled={!data.mistakes}>
          <Link href="/review-session?mistakes=1">Drill</Link>
        </Button>
      </Card>

      <Card className="p-5">
        <p className="flex items-center gap-2 font-bold">
          <Sparkles className="size-4 text-primary" /> Coming up
        </p>
        <div className="mt-4 flex h-28 items-end gap-2">
          {data.forecast.map((n, i) => (
            <div key={i} className="flex flex-1 flex-col items-center gap-1.5">
              <span className="text-xs font-semibold tabular-nums text-muted-foreground">{n || ""}</span>
              <div className="w-full rounded-t-lg bg-primary/80" style={{ height: `${Math.max(4, (n / max) * 72)}px`, opacity: n ? 1 : 0.25 }} />
              <span className="text-[11px] text-muted-foreground">
                {DAYS[i] ?? new Date(Date.now() + i * 86400000).toLocaleDateString(undefined, { weekday: "short" })}
              </span>
            </div>
          ))}
        </div>
      </Card>

      <p className="flex items-start gap-2 text-sm text-muted-foreground">
        <Brain className="mt-0.5 size-4 shrink-0" />
        Words join your deck when you finish a lesson, or when you add them from a conversation or the word list. New
        cards per day can be changed in Settings.
      </p>
    </div>
  );
}
