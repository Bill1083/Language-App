"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, NotebookPen, Search } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { GrammarCard } from "@/components/lesson/cards";
import { EmptyState, Input, Skeleton } from "@/components/ui/primitives";
import { useActiveLang } from "@/hooks/use-language";
import { get } from "@/lib/api";
import { LANGS } from "@/lib/languages";
import type { Grammar } from "@/lib/types";
import { cn } from "@/lib/utils";

type Item = { lesson_id: number; lesson: string; unit: string; level: string; grammar: Grammar };

export default function GrammarPage() {
  const lang = useActiveLang();
  const [q, setQ] = React.useState("");
  const [search, setSearch] = React.useState("");
  const [open, setOpen] = React.useState<string | null>(null);
  React.useEffect(() => {
    const t = setTimeout(() => setSearch(q), 250);
    return () => clearTimeout(t);
  }, [q]);
  const { data, isLoading } = useQuery({
    queryKey: ["grammar", lang, search],
    queryFn: () => get<{ items: Item[] }>(`/grammar/${lang}?q=${encodeURIComponent(search)}`),
    placeholderData: (p) => p,
  });

  const grouped = React.useMemo(() => {
    const g = new Map<string, Item[]>();
    for (const it of data?.items ?? []) {
      const key = `${it.level} · ${it.unit}`;
      g.set(key, [...(g.get(key) ?? []), it]);
    }
    return [...g.entries()];
  }, [data]);

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight sm:text-3xl">Grammar</h1>
        <p className="mt-1 text-muted-foreground">Every {LANGS[lang].name} grammar note from lessons you&apos;ve completed, with conjugation tables.</p>
      </div>
      <div className="relative">
        <Search className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input className="pl-10" placeholder={lang === "ja" ? "Search: particles, て-form, です…" : "Search: past tense, articles, être…"} value={q}
          onChange={(e) => setQ(e.target.value)} aria-label="Search grammar" />
      </div>
      {isLoading ? (
        <div className="space-y-2">{Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-14" />)}</div>
      ) : !grouped.length ? (
        <EmptyState icon={<NotebookPen />} title={search ? "Nothing matches" : "No grammar notes yet"}>
          {search ? "Try another term." : <>Complete lessons in <Link href="/learn" className="font-semibold text-primary-strong">Learn</Link> and their grammar notes collect here.</>}
        </EmptyState>
      ) : (
        grouped.map(([group, items]) => (
          <section key={group}>
            <h2 className="mb-2 text-sm font-semibold text-muted-foreground">{group}</h2>
            <div className="space-y-2">
              {items.map((it, i) => {
                const key = `${it.lesson_id}-${i}`;
                const isOpen = open === key;
                return (
                  <div key={key} className="rounded-2xl border bg-card">
                    <button type="button" onClick={() => setOpen(isOpen ? null : key)} aria-expanded={isOpen}
                      className="flex w-full items-center gap-3 px-4 py-3.5 text-left">
                      <span className="min-w-0 flex-1">
                        <span className="block font-semibold">{it.grammar.title}</span>
                        <span className="block text-xs text-muted-foreground">from “{it.lesson}”</span>
                      </span>
                      <ChevronDown className={cn("size-5 text-muted-foreground transition", isOpen && "rotate-180")} />
                    </button>
                    {isOpen && (
                      <div className="border-t px-4 pb-5 pt-4">
                        <GrammarCard grammar={it.grammar} lang={lang} />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        ))
      )}
    </div>
  );
}
