"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Library, Plus, Search } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { AudioButton } from "@/components/audio-button";
import { RubyText } from "@/components/ruby-text";
import { TargetInput } from "@/components/target-input";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/overlay";
import { Badge, EmptyState, Input, Label, Select, Skeleton } from "@/components/ui/primitives";
import { GenderBadge } from "@/components/word-popover";
import { useActiveLang } from "@/hooks/use-language";
import { useMe } from "@/hooks/use-me";
import { errorMessage, get, post } from "@/lib/api";
import { CEFR_LEVELS, LANGS } from "@/lib/languages";
import type { Lang, VocabRow } from "@/lib/types";
import { cn } from "@/lib/utils";

type VocabPage = { items: VocabRow[]; total: number; page: number; units: { id: number; title: string; level: string }[] };

function AddWordDialog({ lang, open, onOpenChange }: { lang: Lang; open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const [form, setForm] = React.useState({ word: "", meaning: "", reading: "", gender: "", example: "" });
  const add = useMutation({
    mutationFn: () => post(`/vocab/${lang}`, { ...form, reading: form.reading || null, gender: form.gender || null, example: form.example || null }),
    onSuccess: () => {
      toast.success("Word added — it's in your review deck too.");
      setForm({ word: "", meaning: "", reading: "", gender: "", example: "" });
      onOpenChange(false);
      void qc.invalidateQueries({ queryKey: ["vocab"] });
      void qc.invalidateQueries({ queryKey: ["deck"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent side="bottom" title="Add a word" description={`Add your own ${LANGS[lang].name} word to your list and review deck.`}>
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
          <div className="space-y-1.5">
            <Label>{LANGS[lang].name}</Label>
            <TargetInput lang={lang} value={form.word} onChange={(v) => setForm({ ...form, word: v })} placeholder={lang === "fr" ? "la boulangerie" : lang === "it" ? "il panificio" : "パン屋"} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="meaning">English meaning</Label>
            <Input id="meaning" required value={form.meaning} onChange={(e) => setForm({ ...form, meaning: e.target.value })} />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            {lang === "ja" ? (
              <div className="space-y-1.5">
                <Label htmlFor="reading">Reading (kana)</Label>
                <Input id="reading" lang="ja" value={form.reading} onChange={(e) => setForm({ ...form, reading: e.target.value })} />
              </div>
            ) : (
              <div className="space-y-1.5">
                <Label htmlFor="gender">Gender</Label>
                <Select id="gender" value={form.gender} onChange={(e) => setForm({ ...form, gender: e.target.value })}>
                  <option value="">—</option>
                  <option value="m">Masculine</option>
                  <option value="f">Feminine</option>
                </Select>
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="example">Example (optional)</Label>
              <Input id="example" lang={lang} value={form.example} onChange={(e) => setForm({ ...form, example: e.target.value })} />
            </div>
          </div>
          <Button type="submit" className="w-full" size="lg" disabled={!form.word.trim() || !form.meaning.trim()} loading={add.isPending}>
            Add word
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function WordsPage() {
  const lang = useActiveLang();
  const { data: me } = useMe();
  const [q, setQ] = React.useState("");
  const [search, setSearch] = React.useState("");
  const [level, setLevel] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [unit, setUnit] = React.useState("");
  const [page, setPage] = React.useState(1);
  const [adding, setAdding] = React.useState(false);
  const colors = me?.settings.gender_colors !== false;

  React.useEffect(() => {
    const t = setTimeout(() => { setSearch(q); setPage(1); }, 250);
    return () => clearTimeout(t);
  }, [q]);

  const params = new URLSearchParams({ q: search, level, status, page: String(page), per_page: "50", ...(unit ? { unit_id: unit } : {}) });
  const { data, isLoading } = useQuery({
    queryKey: ["vocab", lang, params.toString()],
    queryFn: () => get<VocabPage>(`/vocab/${lang}?${params}`),
    placeholderData: (prev) => prev,
  });

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight sm:text-3xl">Vocabulary</h1>
          <p className="mt-1 text-muted-foreground">{data ? `${data.total} words learned` : "Every word you've learned"} in {LANGS[lang].name}.</p>
        </div>
        <Button onClick={() => setAdding(true)}><Plus /> Add word</Button>
      </div>

      <div className="grid gap-2.5 sm:grid-cols-[1fr_auto_auto_auto]">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="pl-10" placeholder="Search words or meanings" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search vocabulary" />
        </div>
        <Select value={level} onChange={(e) => { setLevel(e.target.value); setPage(1); }} aria-label="Filter by level" className="sm:w-28">
          <option value="">All levels</option>
          {CEFR_LEVELS.map((l) => <option key={l} value={l}>{l}</option>)}
        </Select>
        <Select value={unit} onChange={(e) => { setUnit(e.target.value); setPage(1); }} aria-label="Filter by unit" className="sm:w-48">
          <option value="">All units</option>
          {data?.units.map((u) => <option key={u.id} value={u.id}>{u.level} · {u.title}</option>)}
        </Select>
        <Select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} aria-label="Filter by status" className="sm:w-36">
          <option value="">Any status</option>
          <option value="learning">Learning</option>
          <option value="known">Known</option>
        </Select>
      </div>

      {isLoading ? (
        <div className="space-y-2">{Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-16" />)}</div>
      ) : !data?.items.length ? (
        <EmptyState icon={<Library />} title={search || level || unit || status ? "No matching words" : "No words yet"}>
          {search || level || unit || status ? "Try clearing a filter." : "Finish a lesson and its words appear here — or add your own."}
        </EmptyState>
      ) : (
        <>
          <ul className="divide-y rounded-2xl border bg-card">
            {data.items.map((w) => (
              <li key={w.id} className="flex items-center gap-3 px-4 py-3">
                <AudioButton text={w.lemma} lang={lang} size="sm" />
                <div className="min-w-0 flex-1">
                  <p className={cn("text-[17px] font-semibold", colors && (w.gender === "m" ? "text-masc" : w.gender === "f" ? "text-fem" : ""))}>
                    {w.emoji && <span className="mr-1.5">{w.emoji}</span>}
                    <RubyText text={w.ruby ?? w.lemma} lang={lang} showRomaji={false} />
                    {w.reading && !w.ruby && lang === "ja" && w.reading !== w.lemma && (
                      <span className="ml-2 text-sm font-normal text-muted-foreground">{w.reading}</span>
                    )}
                  </p>
                  <p className="truncate text-sm text-muted-foreground">{w.meaning}</p>
                </div>
                <div className="hidden items-center gap-1.5 sm:flex">
                  <GenderBadge gender={w.gender} />
                  {w.level && <Badge>{w.level}</Badge>}
                  {w.source !== "lesson" && <Badge tone="primary">{w.source === "custom" ? "added" : "from chat"}</Badge>}
                </div>
                <Badge tone={w.status === "known" ? "success" : "neutral"}>{w.status === "known" ? "Known" : "Learning"}</Badge>
              </li>
            ))}
          </ul>
          {data.total > 50 && (
            <div className="flex items-center justify-center gap-3">
              <Button variant="outline" size="sm" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous</Button>
              <span className="text-sm text-muted-foreground">Page {page} of {Math.ceil(data.total / 50)}</span>
              <Button variant="outline" size="sm" disabled={page * 50 >= data.total} onClick={() => setPage(page + 1)}>Next</Button>
            </div>
          )}
        </>
      )}
      <AddWordDialog lang={lang} open={adding} onOpenChange={setAdding} />
    </div>
  );
}
