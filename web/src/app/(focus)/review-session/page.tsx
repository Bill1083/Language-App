"use client";

import { useQueryClient } from "@tanstack/react-query";
import { CircleCheck, CircleX, Layers, PartyPopper, X } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { AudioButton } from "@/components/audio-button";
import { RubyText } from "@/components/ruby-text";
import { TargetInput } from "@/components/target-input";
import { Button } from "@/components/ui/button";
import { Badge, Card, Kbd, Progress, Skeleton } from "@/components/ui/primitives";
import { GenderBadge } from "@/components/word-popover";
import { useQueue } from "@/hooks/queries";
import { useActiveLang } from "@/hooks/use-language";
import { ApiError, post } from "@/lib/api";
import { localCheck } from "@/lib/answer";
import { player } from "@/lib/audio";
import { stripRuby } from "@/lib/japanese";
import { queueOffline } from "@/lib/outbox";
import { sounds } from "@/lib/sounds";
import type { Lang, SrsCard } from "@/lib/types";
import { cn, formatDuration } from "@/lib/utils";

const RATINGS = [
  { r: 1, label: "Again", cls: "bg-danger-soft text-danger hover:bg-danger hover:text-white" },
  { r: 2, label: "Hard", cls: "bg-warning-soft text-warning hover:bg-warning hover:text-white" },
  { r: 3, label: "Good", cls: "bg-success-soft text-success hover:bg-success hover:text-white" },
  { r: 4, label: "Easy", cls: "bg-primary-soft text-primary-strong hover:bg-primary hover:text-primary-foreground" },
];

const TYPE_LABEL: Record<string, string> = {
  recognize: "What does it mean?",
  produce: "Say it in the language",
  listen: "What do you hear?",
  kanji: "How is it read?",
  kana: "How is it read?",
  mistake: "Fix your mistake",
};

function Front({ card, lang, typed, setTyped, onSubmit, revealed }: {
  card: SrsCard; lang: Lang; typed: string; setTyped: (s: string) => void; onSubmit: () => void; revealed: boolean;
}) {
  const f = card.front;
  switch (card.card_type) {
    case "recognize":
      return (
        <div className="flex flex-col items-center gap-4">
          <p className="text-4xl font-extrabold"><RubyText text={f.text} lang={lang} /></p>
          <AudioButton text={f.audio_text ?? f.text} lang={lang} autoPlay />
        </div>
      );
    case "listen":
      return (
        <div className="flex flex-col items-center gap-3">
          <AudioButton text={f.audio_text} lang={lang} size="xl" variant="solid" autoPlay />
          <AudioButton text={f.audio_text} lang={lang} slow size="md" />
        </div>
      );
    case "kanji":
      return <p className="font-jp text-6xl font-bold" lang="ja">{f.text}</p>;
    case "kana":
      return (
        <p className="font-jp text-[96px] font-medium leading-none" lang="ja">
          {f.char}
        </p>
      );
    case "produce":
      return (
        <div className="flex w-full flex-col items-center gap-4">
          <p className="text-3xl font-extrabold">{f.prompt}</p>
          <div className="flex gap-1.5">
            {f.pos && <Badge>{f.pos}</Badge>}
            <GenderBadge gender={f.gender} />
          </div>
          {!revealed && (
            <div className="w-full max-w-md">
              <TargetInput lang={lang} value={typed} onChange={setTyped} onSubmit={onSubmit} placeholder="Type it (optional) — or just think of it" autoFocus />
            </div>
          )}
        </div>
      );
    default:
      return (
        <div className="flex flex-col items-center gap-3">
          <p className="text-2xl font-bold">{f.prompt}</p>
          {f.wrong && <p className="text-sm text-muted-foreground">You answered: <span className="text-danger line-through">{f.wrong}</span></p>}
          {f.context && <p className="text-sm text-muted-foreground">“{f.context}”</p>}
        </div>
      );
  }
}

function Back({ card, lang, verdict }: { card: SrsCard; lang: Lang; verdict: string | null }) {
  const b = card.back;
  if (card.card_type === "kana") {
    return (
      <div className="flex flex-col items-center gap-3">
        <div className="flex items-center gap-3">
          <p className="text-4xl font-black">{b.romaji}</p>
          <AudioButton text={b.audio_text ?? card.front.char} lang="ja" autoPlay />
        </div>
        {b.mnemonic && <p className="max-w-sm text-center text-sm text-muted-foreground">{b.mnemonic}</p>}
      </div>
    );
  }
  if (card.card_type === "produce" || card.card_type === "mistake") {
    return (
      <div className="flex flex-col items-center gap-3">
        {verdict && (
          <p className={cn("flex items-center gap-1.5 text-sm font-bold", verdict === "wrong" ? "text-danger" : "text-success")}>
            {verdict === "wrong" ? <CircleX className="size-4" /> : <CircleCheck className="size-4" />}
            {verdict === "wrong" ? "Not quite" : verdict === "accent" ? "Right — watch the accents" : "Correct"}
          </p>
        )}
        <div className="flex items-center gap-3">
          <p className="text-3xl font-extrabold"><RubyText text={b.answer} lang={lang} /></p>
          {(b.audio_text ?? b.answer) && <AudioButton text={stripRuby(b.audio_text ?? b.answer)} lang={lang} autoPlay />}
        </div>
        {b.explanation && <p className="max-w-md text-center text-sm text-muted-foreground">{b.explanation}</p>}
        {b.example && (
          <p className="max-w-md text-center text-sm">
            <RubyText text={b.example} lang={lang} showRomaji={false} />
            {b.example_translation && <span className="block text-muted-foreground">{b.example_translation}</span>}
          </p>
        )}
      </div>
    );
  }
  return (
    <div className="flex flex-col items-center gap-2">
      {(card.card_type === "listen" || card.card_type === "kanji") && (
        <p className="text-3xl font-extrabold"><RubyText text={b.text} lang={lang} /></p>
      )}
      {b.reading && card.card_type === "kanji" && <p className="font-jp text-xl text-muted-foreground">{b.reading}</p>}
      <p className="text-2xl font-semibold">{b.meaning}</p>
      <div className="flex gap-1.5">
        {b.pos && <Badge>{b.pos}</Badge>}
        <GenderBadge gender={b.gender} />
      </div>
      {b.example && (
        <div className="mt-3 flex max-w-md items-start gap-2 rounded-xl bg-muted/60 p-3 text-left text-sm">
          <AudioButton text={b.example} lang={lang} size="sm" />
          <p>
            <RubyText text={b.example} lang={lang} showRomaji={false} />
            {b.example_translation && <span className="block text-muted-foreground">{b.example_translation}</span>}
          </p>
        </div>
      )}
    </div>
  );
}

function Session() {
  const lang = useActiveLang();
  const params = useSearchParams();
  const mistakes = params.get("mistakes") === "1";
  const level = params.get("level");
  const unit = params.get("unit");
  const practice = !!(level || unit);
  const router = useRouter();
  const qc = useQueryClient();
  const { data, isLoading, refetch } = useQueue(lang, { mistakes, level, unit });
  const [queue, setQueue] = React.useState<SrsCard[] | null>(null);
  const [pos, setPos] = React.useState(0);
  const [revealed, setRevealed] = React.useState(false);
  const [typed, setTyped] = React.useState("");
  const [verdict, setVerdict] = React.useState<string | null>(null);
  const [stats, setStats] = React.useState({ reviewed: 0, good: 0 });
  const [finished, setFinished] = React.useState(false);
  const shownAt = React.useRef(Date.now());
  const startedAt = React.useRef(Date.now());
  const repeats = React.useRef(new Set<number>());

  React.useEffect(() => {
    if (data && !queue) setQueue(data.cards);
  }, [data, queue]);

  const card = queue?.[pos];

  const finish = React.useCallback(async (reviewed: number) => {
    setFinished(true);
    sounds.complete();
    const seconds = Math.round((Date.now() - startedAt.current) / 1000);
    try {
      const r = await post<{ xp: number; achievements?: { title: string; icon: string }[] }>("/srs/session", { lang, reviewed, seconds });
      r.achievements?.forEach((a) => toast.success(`${a.icon} Achievement: ${a.title}`));
    } catch (e) {
      if (e instanceof ApiError && e.offline) queueOffline("/srs/session", { lang, reviewed, seconds });
    }
    void qc.invalidateQueries({ queryKey: ["deck"] });
    void qc.invalidateQueries({ queryKey: ["dashboard"] });
    void qc.invalidateQueries({ queryKey: ["practice-levels"] });
  }, [lang, qc]);

  /** Practice only: a fresh shuffle of the same level or unit. */
  const again = React.useCallback(async () => {
    const { data: next } = await refetch();
    setQueue(next?.cards ?? []);
    setPos(0);
    setRevealed(false);
    setTyped("");
    setVerdict(null);
    setStats({ reviewed: 0, good: 0 });
    setFinished(false);
    repeats.current.clear();
    startedAt.current = shownAt.current = Date.now();
  }, [refetch]);

  const reveal = React.useCallback(() => {
    if (!card || revealed) return;
    if (card.card_type === "produce" && typed.trim()) {
      const v = localCheck(typed, [card.back.answer, ...(card.back.accepted ?? [])], lang);
      setVerdict(v);
      if (v === "wrong") sounds.wrong();
      else sounds.correct();
    }
    setRevealed(true);
  }, [card, revealed, typed, lang]);

  const rate = React.useCallback(
    (rating: number) => {
      if (!card || !revealed) return;
      player?.stop();
      const body = { card_id: card.id, rating, elapsed_ms: Date.now() - shownAt.current, reviewed_at: new Date().toISOString() };
      post("/srs/review", body).catch((e) => {
        if (e instanceof ApiError && e.offline) queueOffline("/srs/review", body);
        else toast.error(e.message);
      });
      const reviewed = stats.reviewed + 1;
      setStats((s) => ({ reviewed, good: s.good + (rating >= 3 ? 1 : 0) }));
      let nextQueue = queue!;
      if (rating === 1 && !repeats.current.has(card.id)) {
        repeats.current.add(card.id);
        nextQueue = [...queue!, { ...card, intervals: undefined }];
        setQueue(nextQueue);
      }
      setRevealed(false);
      setTyped("");
      setVerdict(null);
      shownAt.current = Date.now();
      if (pos + 1 >= nextQueue.length) void finish(reviewed);
      else setPos(pos + 1);
    },
    [card, revealed, stats, queue, pos, finish],
  );

  React.useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      const typing = t?.tagName === "TEXTAREA" || t?.tagName === "INPUT";
      if (!revealed && (e.code === "Space" || e.key === "Enter") && !typing) {
        e.preventDefault();
        reveal();
      } else if (revealed && ["1", "2", "3", "4"].includes(e.key)) {
        e.preventDefault();
        rate(Number(e.key));
      } else if (revealed && (e.code === "Space" || e.key === "Enter") && !typing) {
        e.preventDefault();
        rate(verdict === "wrong" ? 1 : 3);
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [revealed, reveal, rate, verdict]);

  if (isLoading || !queue) {
    return <div className="mx-auto max-w-xl space-y-4 p-6"><Skeleton className="h-4" /><Skeleton className="h-80" /></div>;
  }

  if (finished || !queue.length) {
    return (
      <div className="mx-auto flex min-h-dvh max-w-md flex-col items-center justify-center gap-4 px-6 text-center">
        <div className="flex size-20 items-center justify-center rounded-3xl bg-primary text-primary-foreground">
          {queue.length ? <PartyPopper className="size-10" /> : <Layers className="size-10" />}
        </div>
        <h1 className="text-3xl font-black">{queue.length ? "Session complete!" : "Nothing to review"}</h1>
        {queue.length ? (
          <p className="text-muted-foreground">
            {stats.reviewed} cards in {formatDuration((Date.now() - startedAt.current) / 1000)} ·{" "}
            {stats.reviewed ? Math.round((stats.good / stats.reviewed) * 100) : 0}% remembered · +{stats.reviewed} XP
          </p>
        ) : (
          <p className="text-muted-foreground">
            {practice
              ? "Nothing to practise here yet — finish a lesson in this part of the course first."
              : mistakes
                ? "No mistake cards right now."
                : "You're all caught up. Come back later!"}
          </p>
        )}
        <div className="mt-4 flex w-full flex-col gap-2.5">
          {practice && queue.length > 0 ? (
            <Button size="lg" onClick={() => void again()}>Practise again</Button>
          ) : (
            <Button size="lg" asChild><Link href="/">Home</Link></Button>
          )}
          <Button size="lg" variant="outline" asChild><Link href="/review">Review overview</Link></Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="safe-top mx-auto flex w-full max-w-2xl items-center gap-3 px-4 py-3 sm:px-6">
        <Button variant="ghost" size="icon" aria-label="Stop reviewing" onClick={() => (stats.reviewed ? void finish(stats.reviewed) : router.push("/review"))}>
          <X />
        </Button>
        <Progress value={pos / queue.length} className="h-3 flex-1" />
        <span className="text-sm font-semibold tabular-nums text-muted-foreground">{queue.length - pos}</span>
      </header>

      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col px-4 pb-6 sm:px-6">
        <div className="flex items-center justify-between py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          <span>
            {practice && data?.title && <span className="text-primary-strong">Practice · {data.title} · </span>}
            {TYPE_LABEL[card!.card_type]}
          </span>
          {card!.is_new && <Badge tone="primary">New</Badge>}
        </div>
        <div className="flex-1 [perspective:1400px]" key={`${card!.id}-${pos}`}>
          <Card
            className={cn(
              "relative flex min-h-[22rem] flex-col items-center justify-center gap-6 p-6 text-center shadow-lg transition-transform duration-500 [transform-style:preserve-3d] sm:p-10",
              "animate-rise",
            )}
          >
            <Front card={card!} lang={lang} typed={typed} setTyped={setTyped} onSubmit={reveal} revealed={revealed} />
            {revealed && (
              <div className="w-full animate-in fade-in-0 slide-in-from-bottom-2 border-t pt-6">
                <Back card={card!} lang={lang} verdict={verdict} />
              </div>
            )}
          </Card>
        </div>
      </main>

      <footer className="safe-bottom sticky bottom-0 border-t bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-2xl px-4 py-4 sm:px-6">
          {!revealed ? (
            <Button size="xl" className="w-full" onClick={reveal}>
              {card!.card_type === "produce" && typed.trim() ? "Check" : "Show answer"} <Kbd className="ml-1 bg-white/20 text-white">Space</Kbd>
            </Button>
          ) : (
            <div className="grid grid-cols-4 gap-2">
              {RATINGS.map(({ r, label, cls }) => (
                <button
                  key={r}
                  type="button"
                  onClick={() => rate(r)}
                  className={cn(
                    "flex flex-col items-center rounded-2xl py-2.5 font-bold transition active:scale-95",
                    cls,
                    verdict === "wrong" && r === 1 && "ring-2 ring-danger",
                    verdict && verdict !== "wrong" && r === 3 && "ring-2 ring-success",
                  )}
                >
                  <span className="text-[15px]">{label}</span>
                  <span className="text-[11px] font-semibold opacity-80">
                    {card!.intervals?.[String(r)] ?? ""} <span className="hidden sm:inline">· {r}</span>
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      </footer>
    </div>
  );
}

export default function ReviewSessionPage() {
  return (
    <React.Suspense>
      <Session />
    </React.Suspense>
  );
}
