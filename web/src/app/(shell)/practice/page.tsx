"use client";

import { Check, Dumbbell, Keyboard, Layers, Minus } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, EmptyState, Segmented, Skeleton } from "@/components/ui/primitives";
import { usePracticeBlocks, type PracticeBlocks } from "@/hooks/queries";
import { useActiveLang } from "@/hooks/use-language";
import { CEFR_LABEL } from "@/lib/languages";
import { cn } from "@/lib/utils";

type Mode = "type" | "cards";
type Order = "course" | "shuffle";
type Level = PracticeBlocks[number];
const COUNTS = [5, 10, 15, 20] as const;
const PREFS_KEY = "parlo.practice";
/** With no block named in the link, start with the most recent few. */
const DEFAULT_BLOCKS = 3;

type Prefs = { mode: Mode; order: Order; limit: number };
const DEFAULT_PREFS: Prefs = { mode: "type", order: "course", limit: 20 };

function loadPrefs(): Prefs {
  try {
    return { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem(PREFS_KEY) ?? "{}") };
  } catch {
    return DEFAULT_PREFS;
  }
}

function savePrefs(p: Prefs) {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(p));
  } catch {
    /* private mode: just don't remember */
  }
}

const lessonsOf = (lv: Level) => lv.units.flatMap((u) => u.lessons);
const levelName = (lv: Level) => (lv.level === "PRE" ? "Hiragana & katakana" : CEFR_LABEL[lv.level]);
const itemNoun = (lv: Level | undefined, n: number) =>
  lv?.level === "PRE" ? (n === 1 ? "symbol or word" : "symbols & words") : n === 1 ? "word" : "words";

function Tick({ state }: { state: "all" | "some" | "none" }) {
  return (
    <span
      className={cn(
        "flex size-6 shrink-0 items-center justify-center rounded-lg border-2 transition",
        state === "none" ? "border-border" : "border-primary bg-primary text-primary-foreground",
      )}
    >
      {state === "all" && <Check className="size-4" strokeWidth={3} />}
      {state === "some" && <Minus className="size-4" strokeWidth={3} />}
    </span>
  );
}

function Setup() {
  const lang = useActiveLang();
  const params = useSearchParams();
  const { data: levels, isLoading } = usePracticeBlocks(lang);
  const [prefs, setPrefs] = React.useState<Prefs>(DEFAULT_PREFS);
  const [level, setLevel] = React.useState<string | null>(null);
  const [picked, setPicked] = React.useState<Set<number>>(new Set());

  React.useEffect(() => setPrefs(loadPrefs()), []);
  const update = (p: Partial<Prefs>) =>
    setPrefs((old) => {
      const next = { ...old, ...p };
      savePrefs(next);
      return next;
    });

  // Initial selection from the link: ?unit=ID (that unit's blocks), ?level=A1 (the whole level),
  // or else the last few blocks you finished.
  React.useEffect(() => {
    if (!levels?.length || level) return;
    const unitId = Number(params.get("unit"));
    const fromUnit = unitId ? levels.find((lv) => lv.units.some((u) => u.id === unitId)) : undefined;
    const fromLevel = levels.find((l) => l.level === params.get("level"));
    const lv = fromUnit ?? fromLevel ?? levels[levels.length - 1];
    setLevel(lv.level);
    const ids = fromUnit
      ? lv.units.find((u) => u.id === unitId)!.lessons.map((l) => l.id)
      : fromLevel
        ? lessonsOf(lv).map((l) => l.id)
        : lessonsOf(lv).slice(-DEFAULT_BLOCKS).map((l) => l.id);
    setPicked(new Set(ids));
  }, [levels, level, params]);

  if (isLoading || !levels) {
    return (
      <div className="mx-auto max-w-2xl space-y-4">
        <Skeleton className="h-10 w-48" />
        <Skeleton className="h-40" />
        <Skeleton className="h-64" />
      </div>
    );
  }
  if (!levels.length) {
    return (
      <div className="mx-auto max-w-2xl">
        <EmptyState icon={<Dumbbell />} title="Nothing to practise yet">
          Finish a lesson and the words it taught show up here.
        </EmptyState>
      </div>
    );
  }

  const current = levels.find((l) => l.level === level);
  const chosen = current ? lessonsOf(current).filter((l) => picked.has(l.id)) : [];
  const selectedItems = chosen.reduce((n, l) => n + l.items, 0);
  const count = Math.min(prefs.limit, selectedItems);
  const setMany = (ids: number[], on: boolean) =>
    setPicked((s) => {
      const next = new Set(s);
      for (const id of ids) {
        if (on) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  const stateOf = (ids: number[]) => {
    const n = ids.filter((id) => picked.has(id)).length;
    return n === 0 ? "none" : n === ids.length ? "all" : "some";
  };
  const pickLevel = (lv: Level) => {
    setLevel(lv.level);
    setPicked(new Set(lessonsOf(lv).slice(-DEFAULT_BLOCKS).map((l) => l.id)));
  };
  const allIds = current ? lessonsOf(current).map((l) => l.id) : [];
  const query = new URLSearchParams({
    lessons: chosen.map((l) => l.id).join(","),
    order: prefs.order,
    limit: String(prefs.limit),
  });
  const href = `${prefs.mode === "type" ? "/practice-type" : "/review-session"}?${query}`;
  let blockNumber = 0;

  return (
    <div className="mx-auto max-w-2xl space-y-5 pb-28">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight sm:text-3xl">Practice</h1>
        <p className="mt-1 text-muted-foreground">Pick blocks from the course map to drill — up to 20 items at a time.</p>
      </div>

      <Card className="space-y-3 p-5">
        <p className="text-sm font-semibold text-muted-foreground">How</p>
        <div className="grid grid-cols-2 gap-2.5">
          {([
            { value: "type", icon: Keyboard, title: "Type it", text: "See the meaning, type the word. Right twice in a row and it's done." },
            { value: "cards", icon: Layers, title: "Flashcards", text: "Flip the card and rate how well you knew it." },
          ] as const).map(({ value, icon: Icon, title, text }) => (
            <button
              key={value}
              type="button"
              aria-pressed={prefs.mode === value}
              onClick={() => update({ mode: value })}
              className={cn(
                "flex flex-col items-start gap-1.5 rounded-2xl border-2 p-3.5 text-left transition",
                prefs.mode === value ? "border-primary bg-primary-soft" : "bg-card hover:border-primary/40",
              )}
            >
              <Icon className={cn("size-5", prefs.mode === value ? "text-primary-strong" : "text-muted-foreground")} />
              <span className="font-bold">{title}</span>
              <span className="text-xs leading-snug text-muted-foreground">{text}</span>
            </button>
          ))}
        </div>
      </Card>

      <Card className="overflow-hidden">
        <div className="space-y-3 p-5 pb-3">
          <p className="text-sm font-semibold text-muted-foreground">What</p>
          <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1 scrollbar-none" role="tablist" aria-label="Levels">
            {levels.map((lv) => (
              <button
                key={lv.level}
                role="tab"
                aria-selected={lv.level === level}
                onClick={() => pickLevel(lv)}
                className={cn(
                  "shrink-0 rounded-xl border-2 px-3.5 py-1.5 text-sm font-bold transition",
                  lv.level === level ? "border-primary bg-primary-soft text-primary-strong" : "bg-card text-muted-foreground hover:text-foreground",
                )}
              >
                {lv.label}
              </button>
            ))}
          </div>
          {current && (
            <div className="flex items-center justify-between gap-3">
              <p className="min-w-0 truncate text-sm font-semibold">{levelName(current)}</p>
              <button
                type="button"
                onClick={() => setMany(allIds, stateOf(allIds) !== "all")}
                className="shrink-0 text-sm font-semibold text-primary-strong hover:underline"
              >
                {stateOf(allIds) === "all" ? "Select none" : "Select all"}
              </button>
            </div>
          )}
        </div>
        {current?.units.map((u) => {
          const ids = u.lessons.map((l) => l.id);
          return (
            <section key={u.id} className="border-t">
              <button
                type="button"
                onClick={() => setMany(ids, stateOf(ids) !== "all")}
                aria-pressed={stateOf(ids) === "all"}
                className="flex w-full items-center gap-3 bg-muted/50 px-5 py-2.5 text-left transition hover:bg-muted"
              >
                <Tick state={stateOf(ids)} />
                <span className="min-w-0 flex-1 truncate text-sm font-bold uppercase tracking-wide text-muted-foreground">{u.title}</span>
              </button>
              <ul className="divide-y">
                {u.lessons.map((l) => {
                  blockNumber += 1;
                  const on = picked.has(l.id);
                  return (
                    <li key={l.id}>
                      <button
                        type="button"
                        aria-pressed={on}
                        onClick={() => setMany([l.id], !on)}
                        className="flex w-full items-center gap-3 px-5 py-3 text-left transition hover:bg-muted/40"
                      >
                        <Tick state={on ? "all" : "none"} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate font-semibold" lang={lang}>
                            <span className="text-muted-foreground">{blockNumber}.</span> {l.title}
                          </span>
                          <span className="block text-xs text-muted-foreground">
                            {l.items} {itemNoun(current, l.items)}
                          </span>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          );
        })}
      </Card>

      <Card className="grid gap-4 p-5 sm:grid-cols-2">
        <div className="space-y-2">
          <p className="text-sm font-semibold text-muted-foreground">Order</p>
          <Segmented
            ariaLabel="Order"
            className="w-full"
            value={prefs.order}
            onChange={(order) => update({ order })}
            options={[{ value: "course", label: "Course order" }, { value: "shuffle", label: "Shuffle" }]}
          />
        </div>
        <div className="space-y-2">
          <p className="text-sm font-semibold text-muted-foreground">How many</p>
          <Segmented
            ariaLabel="How many"
            className="w-full"
            value={prefs.limit}
            onChange={(limit) => update({ limit })}
            options={COUNTS.map((n) => ({ value: n, label: n }))}
          />
        </div>
      </Card>

      {/* sits above the mobile tab bar (h-16) and beside the desktop sidebar (w-60) */}
      <div className="fixed inset-x-0 bottom-[calc(4rem+env(safe-area-inset-bottom))] z-20 border-t bg-background/95 backdrop-blur lg:bottom-0 lg:left-60">
        <div className="mx-auto flex max-w-2xl items-center gap-3 px-4 py-3 sm:px-6">
          <p className="min-w-0 flex-1 text-sm text-muted-foreground">
            {count
              ? `${count} of ${selectedItems} ${itemNoun(current, selectedItems)} · ${chosen.length} ${chosen.length === 1 ? "block" : "blocks"}`
              : "Pick at least one block"}
          </p>
          <Button asChild size="lg" className={cn(!count && "pointer-events-none opacity-45")}>
            <Link href={count ? href : "#"} aria-disabled={!count}>
              {prefs.mode === "type" ? <Keyboard /> : <Layers />} Start
            </Link>
          </Button>
        </div>
      </div>
    </div>
  );
}

export default function PracticePage() {
  return (
    <React.Suspense>
      <Setup />
    </React.Suspense>
  );
}
