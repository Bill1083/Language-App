"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, CircleCheck, Clock, Gauge, LoaderCircle, MessageCircle, Plus, RefreshCw, Target, X } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { AiBubble, FeedbackCard, UserBubble } from "@/components/talk/messages";
import { Button } from "@/components/ui/button";
import { Badge, Card, Skeleton } from "@/components/ui/primitives";
import { useWordPopover, WordPopover } from "@/components/word-popover";
import { errorMessage, get, post } from "@/lib/api";
import { ERROR_TYPE_LABEL } from "@/lib/languages";
import type { Conversation } from "@/lib/types";
import { cn, formatDuration } from "@/lib/utils";

export default function SummaryPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const words = useWordPopover();
  const [showTranscript, setShowTranscript] = React.useState(false);
  const [added, setAdded] = React.useState<Set<string>>(new Set());
  const started = React.useRef(Date.now());
  const { data: conv } = useQuery({
    queryKey: ["conversation", id, "summary"],
    queryFn: () => get<Conversation>(`/conversations/${id}`),
    refetchInterval: (q) => (q.state.data?.summary || Date.now() - started.current > 90_000 ? false : 2000),
  });
  const again = useMutation({
    mutationFn: () =>
      post<Conversation>("/conversations", {
        lang: conv!.language, mode: conv!.mode, scenario_id: conv!.scenario?.id, unit_id: conv!.scenario?.unit_id,
        level: conv!.level, settings: conv!.settings,
      }),
    onSuccess: (c) => router.push(`/conversation/${c.id}`),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const addWord = useMutation({
    mutationFn: (v: { word: string; meaning: string; reading?: string | null }) =>
      post(`/vocab/${conv!.language}`, { ...v, source: "conversation", source_ref: `conversation:${id}` }),
    onSuccess: (_d, v) => {
      setAdded((s) => new Set(s).add(v.word));
      void qc.invalidateQueries({ queryKey: ["deck"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const retry = useMutation({ mutationFn: () => post(`/conversations/${id}/summary/retry`), onSuccess: () => (started.current = Date.now()) });

  React.useEffect(() => {
    if (conv) document.documentElement.dataset.lang = conv.language;
  }, [conv]);

  if (!conv) return <div className="mx-auto max-w-2xl space-y-4 p-6"><Skeleton className="h-10 w-2/3" /><Skeleton className="h-40" /></div>;
  const s = conv.summary;
  const lang = conv.language;

  return (
    <div className="mx-auto max-w-2xl px-4 pb-16 pt-5 sm:px-6">
      <div className="flex items-center justify-between">
        <Button variant="ghost" size="icon" asChild aria-label="Close">
          <Link href="/talk"><X /></Link>
        </Button>
      </div>
      <div className="mt-2 animate-rise">
        <p className="text-sm font-semibold text-muted-foreground">Session summary</p>
        <h1 className="mt-1 text-3xl font-black tracking-tight">
          {conv.scenario?.emoji ?? "💬"} {conv.title}
        </h1>
      </div>

      {!s ? (
        <Card className="mt-6 flex items-center gap-3 p-5 text-muted-foreground">
          <LoaderCircle className="size-5 animate-spin text-primary" />
          <span>Analysing your conversation…</span>
          {Date.now() - started.current > 60_000 && (
            <Button size="sm" variant="outline" className="ml-auto" onClick={() => retry.mutate()}>
              <RefreshCw /> Retry
            </Button>
          )}
        </Card>
      ) : (
        <div className="mt-6 space-y-6">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Card className="flex flex-col items-center gap-1 p-4">
              <Clock className="size-5 text-primary" />
              <span className="text-xl font-black">{formatDuration(s.duration_s)}</span>
              <span className="text-xs font-semibold text-muted-foreground">Duration</span>
            </Card>
            <Card className="flex flex-col items-center gap-1 p-4">
              <MessageCircle className="size-5 text-primary" />
              <span className="text-xl font-black">{s.turns}</span>
              <span className="text-xs font-semibold text-muted-foreground">Your turns</span>
            </Card>
            <Card className="flex flex-col items-center gap-1 p-4">
              <Gauge className="size-5 text-primary" />
              <span className={cn("text-xl font-black", s.avg_score != null && (s.avg_score >= 85 ? "text-success" : s.avg_score >= 60 ? "text-warning" : "text-danger"))}>
                {s.avg_score ?? "—"}
              </span>
              <span className="text-xs font-semibold text-muted-foreground">Avg score</span>
            </Card>
            <Card className="flex flex-col items-center gap-1 p-4">
              {s.goal_achieved ? <CircleCheck className="size-5 text-success" /> : <Target className="size-5 text-muted-foreground" />}
              <span className="text-xl font-black">{conv.scenario ? (s.goal_achieved ? "Yes" : "Not yet") : "—"}</span>
              <span className="text-xs font-semibold text-muted-foreground">Goal</span>
            </Card>
          </div>

          {s.encouragement && <p className="rounded-2xl bg-primary-soft p-4 text-[15px] text-primary-strong">{s.encouragement}</p>}

          {s.top_mistakes.length > 0 && (
            <section>
              <h2 className="mb-2.5 text-lg font-bold">Your top mistakes</h2>
              <div className="space-y-2.5">
                {s.top_mistakes.map((m, i) => (
                  <Card key={i} className="p-4">
                    <p className="font-semibold">{i + 1}. {m.title}</p>
                    <p className="mt-1 text-sm text-muted-foreground">{m.explanation}</p>
                    {m.wrong && m.right && (
                      <p className="mt-2 text-[15px]" lang={lang}>
                        <del className="text-danger decoration-2">{m.wrong}</del> → <ins className="font-semibold text-success no-underline">{m.right}</ins>
                      </p>
                    )}
                  </Card>
                ))}
              </div>
              {Object.keys(s.error_types).length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {Object.entries(s.error_types).sort((a, b) => b[1] - a[1]).map(([t, n]) => (
                    <Badge key={t}>{ERROR_TYPE_LABEL[t] ?? t} × {n}</Badge>
                  ))}
                </div>
              )}
            </section>
          )}

          {s.new_vocab.length > 0 && (
            <section>
              <h2 className="mb-2.5 text-lg font-bold">New words</h2>
              <div className="flex flex-wrap gap-2">
                {s.new_vocab.map((v) => (
                  <button
                    key={v.word}
                    type="button"
                    disabled={added.has(v.word)}
                    onClick={() => addWord.mutate({ word: v.word, meaning: v.meaning, reading: v.reading })}
                    className="flex items-center gap-2 rounded-xl border bg-card px-3 py-2 text-sm transition hover:border-primary disabled:border-success/40"
                  >
                    <span className="font-semibold" lang={lang}>{v.word}</span>
                    <span className="text-muted-foreground">{v.meaning}</span>
                    {added.has(v.word) ? <CircleCheck className="size-4 text-success" /> : <Plus className="size-4 text-primary" />}
                  </button>
                ))}
              </div>
            </section>
          )}

          {(s.suggested_lessons.length > 0 || s.suggested_drill) && (
            <section>
              <h2 className="mb-2.5 text-lg font-bold">Work on next</h2>
              <div className="space-y-2">
                {s.suggested_lessons.map((l) => (
                  <Link key={l.id} href={`/lesson/${l.id}`} className="flex items-center gap-3 rounded-2xl border bg-card p-4 transition hover:border-primary/50">
                    <BookOpen className="size-5 text-primary" />
                    <span className="flex-1">
                      <span className="block font-semibold">{l.title}</span>
                      <span className="block text-xs text-muted-foreground">{l.level} · {l.unit}</span>
                    </span>
                  </Link>
                ))}
                {s.suggested_drill && <p className="rounded-2xl border border-dashed p-4 text-sm text-muted-foreground">🔁 {s.suggested_drill}</p>}
              </div>
            </section>
          )}
          {s.error && <p className="text-sm text-danger">Summary analysis failed: {s.error}</p>}
        </div>
      )}

      <section className="mt-8">
        <button type="button" onClick={() => setShowTranscript(!showTranscript)} className="text-sm font-semibold text-primary-strong hover:underline">
          {showTranscript ? "Hide transcript" : `Show full transcript (${conv.turns?.length ?? 0} messages)`}
        </button>
        {showTranscript && (
          <div className="mt-4 flex flex-col gap-4">
            {conv.turns?.map((t) =>
              t.role === "assistant" ? (
                <AiBubble key={t.id} turn={t} lang={lang} settings={conv.settings} mode={conv.mode} onWordTap={words.open} />
              ) : (
                <div key={t.id} className="flex flex-col">
                  <UserBubble turn={t} lang={lang} />
                  {t.feedback && <FeedbackCard turn={t} lang={lang} />}
                </div>
              ),
            )}
          </div>
        )}
      </section>

      <div className="mt-10 flex flex-col gap-2.5 sm:flex-row">
        <Button size="lg" className="sm:flex-1" loading={again.isPending} onClick={() => again.mutate()}>
          <RefreshCw /> Practise again
        </Button>
        <Button size="lg" variant="outline" className="sm:flex-1" asChild>
          <Link href="/talk">Back to Talk</Link>
        </Button>
      </div>
      <WordPopover target={words.target} lang={lang} onClose={words.close} />
    </div>
  );
}
