"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, BookOpen, LoaderCircle, RotateCcw, Sparkles, X } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { GrammarCard, KanaCard, VocabCard } from "@/components/lesson/cards";
import { Flag } from "@/components/flag";
import {
  type AnswerValue,
  ExerciseTitle,
  ExerciseView,
  INFO_TYPES,
  SELF_SUBMITTING,
} from "@/components/lesson/exercises";
import { FeedbackPanel } from "@/components/lesson/feedback";
import { LessonEnd, type Mistake } from "@/components/lesson/lesson-end";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/overlay";
import { Card, Progress } from "@/components/ui/primitives";
import { player } from "@/lib/audio";
import { ApiError, api, errorMessage, get, post } from "@/lib/api";
import { localCheck } from "@/lib/answer";
import { LANGS } from "@/lib/languages";
import { queueOffline } from "@/lib/outbox";
import { sounds } from "@/lib/sounds";
import type { AnswerResult, CompleteResult, Course, Exercise, LessonPayload } from "@/lib/types";

const GENERATION_TIPS = [
  "Writing natural example sentences…",
  "Picking words you already know…",
  "Building exercises for this lesson…",
  "Recording-ready sentences coming up…",
];

function useLesson(id: string) {
  return useQuery({
    queryKey: ["lesson", id],
    queryFn: async () => {
      const res = await api<Response>(`/lessons/${id}`, { raw: true });
      const data = (await res.json()) as LessonPayload & { detail?: string };
      if (!res.ok) throw new ApiError(data.detail ?? "Couldn't open this lesson", res.status);
      return data;
    },
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s && s !== "ready" && s !== "failed" ? 2500 : false;
    },
    retry: (n, e) => (e as ApiError).status === 0 && n < 2,
    staleTime: Infinity,
  });
}

function Generating({ lesson }: { lesson?: LessonPayload }) {
  const [tip, setTip] = React.useState(0);
  React.useEffect(() => {
    const t = setInterval(() => setTip((x) => (x + 1) % GENERATION_TIPS.length), 3500);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-5 px-6 text-center">
      <div className="relative flex size-20 items-center justify-center rounded-3xl bg-primary-soft text-primary">
        <Sparkles className="size-9" />
        <LoaderCircle className="absolute -right-2 -top-2 size-6 animate-spin" />
      </div>
      <div>
        <p className="text-xl font-bold">{lesson?.title ?? "Preparing your lesson"}</p>
        <p className="mt-2 text-muted-foreground transition-opacity" key={tip}>
          {GENERATION_TIPS[tip]}
        </p>
        <p className="mt-4 max-w-xs text-xs text-muted-foreground">
          The first time a lesson is opened it&apos;s written for you — this takes about 20–40 seconds. After that it&apos;s instant.
        </p>
      </div>
      <Button asChild variant="ghost">
        <Link href="/learn">Back to course</Link>
      </Button>
    </div>
  );
}

function accepted(ex: Exercise): string[] {
  switch (ex.type) {
    case "translate":
    case "fill_blank":
      return ex.answers;
    case "dictation":
      return [ex.text, ...(ex.accepted ?? [])];
    case "word_bank":
      return [ex.answer, ...(ex.accepted ?? [])];
    default:
      return [];
  }
}

function offlineResult(ex: Exercise, v: AnswerValue, lang: string): AnswerResult {
  let verdict: AnswerResult["verdict"] = "wrong";
  if (typeof ex.answer_index === "number") verdict = v.selected === ex.answer_index ? "correct" : "wrong";
  else if (v.clientCorrect !== undefined) verdict = v.clientCorrect ? "correct" : "wrong";
  else {
    const check = localCheck(v.text ?? "", accepted(ex), ex.type === "translate" && ex.direction === "to_english" ? "en" : lang);
    verdict = check;
  }
  const answer =
    ex.type === "fill_blank" ? String(ex.sentence).replace("___", ex.answers[0]) : (accepted(ex)[0] ?? (ex.options?.[ex.answer_index] ?? null));
  return {
    verdict, is_correct: verdict !== "wrong", correct_answer: answer, explanation: ex.explanation ?? "",
    segments: null, judged_by_ai: false, correct_index: ex.answer_index,
  };
}

function mistakePrompt(ex: Exercise): string {
  if (ex.type === "translate") return `Translate: ${ex.source}`;
  if (ex.type === "fill_blank") return ex.sentence;
  if (ex.type === "word_bank") return ex.prompt;
  if (ex.type === "multiple_choice") return `${ex.prompt} ${ex.question}`;
  if (ex.type === "kana_choice") return ex.mode === "char_to_romaji" ? `Read: ${ex.char}` : `Which is “${ex.romaji}”?`;
  if (ex.type === "listening_choice") return "What did you hear?";
  if (ex.type === "dictation") return "Write what you hear";
  return ex.type.replace("_", " ");
}

function Player({ lesson, onRestart }: { lesson: LessonPayload; onRestart: () => void }) {
  const router = useRouter();
  const qc = useQueryClient();
  const lang = lesson.language;
  const exercises = React.useMemo(() => lesson.exercises ?? [], [lesson]);
  const [started, setStarted] = React.useState(false);
  const [queue, setQueue] = React.useState<number[]>(() => exercises.map((_, i) => i));
  const [pos, setPos] = React.useState(0);
  const [value, setValue] = React.useState<AnswerValue>({ ready: false });
  const [result, setResult] = React.useState<AnswerResult | null>(null);
  const [checking, setChecking] = React.useState(false);
  const [quit, setQuit] = React.useState(false);
  const firstTry = React.useRef(new Map<number, boolean>());
  const retried = React.useRef(new Set<number>());
  const mistakes = React.useRef<Mistake[]>([]);
  const startedAt = React.useRef(Date.now());
  const [done, setDone] = React.useState<{ result: CompleteResult; seconds: number } | null>(null);
  const [nextHref, setNextHref] = React.useState<string | null>(null);
  const [finishing, setFinishing] = React.useState(false);

  const ex = exercises[queue[pos]];
  const isInfo = ex && INFO_TYPES.has(ex.type);
  const graded = exercises.filter((e) => !INFO_TYPES.has(e.type)).length;

  React.useEffect(() => {
    document.documentElement.dataset.lang = lang;
  }, [lang]);

  const finish = React.useCallback(async () => {
    setFinishing(true);
    const correct = [...firstTry.current.values()].filter(Boolean).length;
    const total = firstTry.current.size || 1;
    const seconds = Math.round((Date.now() - startedAt.current) / 1000);
    const body = { correct, total, seconds, mistakes: [] };
    try {
      const r = await post<CompleteResult>(`/lessons/${lesson.id}/complete`, body);
      setDone({ result: r, seconds });
      void qc.invalidateQueries({ queryKey: ["course"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
      void qc.invalidateQueries({ queryKey: ["deck"] });
      get<Course>(`/course/${lang}`)
        .then((c) => setNextHref(c.next_lesson ? `/lesson/${c.next_lesson.id}` : null))
        .catch(() => {});
    } catch (e) {
      if (e instanceof ApiError && e.offline) {
        queueOffline(`/lessons/${lesson.id}/complete`, body);
        toast.message("You're offline — your progress will sync when you reconnect.");
        setDone({
          result: {
            accuracy: correct / total, passed: true, is_test: false, pass_mark: 0, xp: 0, streak: 0, goal_just_met: false,
            used_freeze: false, new_words: [], achievements: [], level_up: null,
          },
          seconds,
        });
      } else {
        toast.error(errorMessage(e));
      }
    } finally {
      setFinishing(false);
    }
  }, [lesson.id, lang, qc]);

  const advance = React.useCallback(() => {
    player?.stop();
    setResult(null);
    setValue({ ready: false });
    if (pos + 1 >= queue.length) void finish();
    else setPos(pos + 1);
  }, [pos, queue.length, finish]);

  const check = React.useCallback(
    async (override?: AnswerValue) => {
      const v = override ?? value;
      if (!ex || result || checking || !v.ready) return;
      setChecking(true);
      let r: AnswerResult;
      if (ex.type === "speak" && v.speak) {
        r = {
          verdict: v.speak.verdict, is_correct: v.speak.is_correct, correct_answer: ex.text, explanation: ex.explanation ?? "",
          segments: null, judged_by_ai: false,
        };
        void post(`/exercises/${ex.id}/answer`, { answer: v.speak.transcript, client_correct: v.speak.is_correct }).catch(() => {});
      } else if (ex.type === "speak") {
        // skipped — doesn't count either way
        setChecking(false);
        advance();
        return;
      } else {
        try {
          r = await post<AnswerResult>(`/exercises/${ex.id}/answer`, {
            answer: v.text ?? null,
            selected: v.selected ?? null,
            client_correct: v.clientCorrect ?? null,
          });
        } catch (e) {
          if (e instanceof ApiError && e.offline) r = offlineResult(ex, v, lang);
          else {
            toast.error(errorMessage(e));
            setChecking(false);
            return;
          }
        }
      }
      setChecking(false);
      if (ex.type === "match_pairs" && !r.is_correct && !r.explanation) {
        r = { ...r, explanation: "A few mismatches — this set comes back at the end of the lesson." };
      }
      setResult(r);
      if (!firstTry.current.has(ex.id)) firstTry.current.set(ex.id, r.is_correct);
      if (r.is_correct) sounds.correct();
      else {
        sounds.wrong();
        if (!retried.current.has(ex.id)) {
          // second chance at the end of the lesson
          retried.current.add(ex.id);
          setQueue((q) => [...q, queue[pos]]);
          if (ex.type !== "match_pairs" && ex.type !== "reading") {
            mistakes.current.push({ prompt: mistakePrompt(ex), answer: r.correct_answer });
          }
        }
      }
    },
    [ex, result, checking, value, advance, lang, queue, pos],
  );

  // Enter = check / continue
  React.useEffect(() => {
    if (!started || done) return;
    const h = (e: KeyboardEvent) => {
      if (e.key !== "Enter" || e.isComposing || e.keyCode === 229) return;
      const t = e.target as HTMLElement;
      if (t?.tagName === "TEXTAREA" || t?.tagName === "INPUT" || t?.tagName === "BUTTON") return;
      e.preventDefault();
      if (result || isInfo) advance();
      else void check();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [started, done, result, isInfo, advance, check]);

  if (done) {
    return (
      <LessonEnd
        result={done.result}
        lang={lang}
        seconds={done.seconds}
        mistakes={mistakes.current}
        nextHref={nextHref}
        onRetry={onRestart}
      />
    );
  }

  if (!started) {
    const content = lesson.content;
    return (
      <div className="mx-auto flex min-h-dvh max-w-xl flex-col px-4 pb-8 pt-5 sm:px-6">
        <Button variant="ghost" size="icon" onClick={() => router.push("/learn")} aria-label="Close">
          <X />
        </Button>
        <div className="flex flex-1 animate-rise flex-col justify-center">
          <p className="text-sm font-semibold text-muted-foreground">
            <Flag lang={lang} /> {lesson.level === "PRE" ? "Writing systems" : `${lesson.level} · ${lesson.unit.title}`}
          </p>
          <h1 className="mt-2 text-3xl font-black tracking-tight sm:text-4xl">{lesson.title}</h1>
          {content?.intro && <p className="mt-3 text-lg text-muted-foreground">{content.intro}</p>}
          <div className="mt-6 flex flex-wrap gap-2 text-sm">
            {!!content?.vocab.length && <span className="rounded-full bg-primary-soft px-3 py-1 font-semibold text-primary-strong">{content.vocab.length} new words</span>}
            {!!content?.grammar.length && <span className="rounded-full bg-muted px-3 py-1 font-semibold">{content.grammar.length} grammar point{content.grammar.length > 1 ? "s" : ""}</span>}
            <span className="rounded-full bg-muted px-3 py-1 font-semibold">{graded} exercises</span>
            {content?.is_test && <span className="rounded-full bg-gold-soft px-3 py-1 font-semibold text-gold">Pass mark {Math.round((content.pass_mark ?? 0.8) * 100)}%</span>}
          </div>
          {!!content?.pronunciation.length && (
            <Card className="mt-6 p-4">
              <p className="text-sm font-semibold">Pronunciation tips</p>
              <ul className="mt-1.5 list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                {content.pronunciation.map((p, i) => (
                  <li key={i}>{p}</li>
                ))}
              </ul>
            </Card>
          )}
        </div>
        <Button size="xl" className="w-full" autoFocus onClick={() => { startedAt.current = Date.now(); setStarted(true); }}>
          Start <ArrowRight />
        </Button>
      </div>
    );
  }

  if (!ex) return null;
  const progress = Math.min(1, pos / Math.max(1, queue.length));
  const isRetry = pos >= exercises.length;

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="safe-top sticky top-0 z-10 bg-background/90 backdrop-blur">
        <div className="mx-auto flex max-w-2xl items-center gap-3 px-4 py-3 sm:px-6">
          <Button variant="ghost" size="icon" onClick={() => setQuit(true)} aria-label="Quit lesson">
            <X />
          </Button>
          <Progress value={progress} className="h-3.5 flex-1" />
          {isRetry && (
            <span className="flex items-center gap-1 text-xs font-semibold text-warning">
              <RotateCcw className="size-3.5" /> Second try
            </span>
          )}
        </div>
      </header>

      <main className="mx-auto w-full max-w-2xl flex-1 px-4 pb-10 pt-4 sm:px-6 sm:pt-8" key={`${pos}-${ex.id}`}>
        <div className="animate-rise">
          {ex.type === "vocab_intro" ? (
            <VocabCard vocab={ex.vocab} lang={lang} />
          ) : ex.type === "grammar_note" ? (
            <GrammarCard grammar={ex.grammar} lang={lang} />
          ) : ex.type === "kana_intro" ? (
            <KanaCard ex={ex} />
          ) : (
            <div className="space-y-6">
              <ExerciseTitle ex={ex} />
              <ExerciseView ex={ex} lang={lang} value={value} onChange={setValue} result={result} onSubmit={(v) => void check(v)} />
            </div>
          )}
        </div>
      </main>

      <footer className="sticky bottom-0 safe-bottom">
        {result ? (
          <FeedbackPanel result={result} lang={lang} speak={value.speak} exerciseId={ex.id} onContinue={advance}
            answerInTarget={!(ex.type === "translate" && ex.direction === "to_english")} />
        ) : (
          <div className="border-t bg-background/95 backdrop-blur">
            <div className="mx-auto flex max-w-2xl items-center justify-between gap-3 px-4 py-4 sm:px-6">
              {!isInfo && !SELF_SUBMITTING.has(ex.type) && (
                <Button variant="ghost" className="hidden sm:inline-flex" onClick={() => void check({ ...value, text: value.text ?? "", ready: true })}>
                  Skip
                </Button>
              )}
              {isInfo ? (
                <Button size="xl" className="w-full sm:ml-auto sm:w-48" onClick={advance} loading={finishing} autoFocus>
                  {ex.type === "grammar_note" ? "Got it" : "Continue"}
                </Button>
              ) : SELF_SUBMITTING.has(ex.type) ? (
                <p className="w-full text-center text-sm text-muted-foreground">
                  {ex.type === "match_pairs" ? "Tap a word, then its match" : "Record yourself, or skip"}
                </p>
              ) : (
                <Button size="xl" className="w-full sm:ml-auto sm:w-48" disabled={!value.ready} loading={checking || finishing} onClick={() => void check()}>
                  Check
                </Button>
              )}
            </div>
          </div>
        )}
      </footer>

      <Dialog open={quit} onOpenChange={setQuit}>
        <DialogContent title="Quit this lesson?" description="Your progress in this lesson won't be saved." side="bottom">
          <div className="flex flex-col gap-2.5 sm:flex-row">
            <Button className="sm:flex-1" size="lg" onClick={() => setQuit(false)}>
              Keep learning
            </Button>
            <Button className="sm:flex-1" size="lg" variant="outline" onClick={() => router.push("/learn")}>
              Quit
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function LessonPage() {
  const { id } = useParams<{ id: string }>();
  const { data, error, refetch, isLoading } = useLesson(id);
  const [attempt, setAttempt] = React.useState(0);

  if (error) {
    const locked = (error as ApiError).status === 403;
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-4 px-6 text-center">
        <BookOpen className="size-10 text-muted-foreground" />
        <div>
          <p className="text-lg font-bold">{locked ? "This lesson is locked" : "Couldn't open this lesson"}</p>
          <p className="mt-1 text-sm text-muted-foreground">{errorMessage(error)}</p>
        </div>
        <div className="flex gap-2">
          {!locked && (
            <Button variant="outline" onClick={() => refetch()}>
              Try again
            </Button>
          )}
          <Button asChild>
            <Link href="/learn">Back to course</Link>
          </Button>
        </div>
      </div>
    );
  }
  if (isLoading || !data) return <Generating />;
  if (data.status === "failed") {
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-4 px-6 text-center">
        <p className="text-lg font-bold">This lesson couldn&apos;t be generated</p>
        <p className="max-w-md text-sm text-muted-foreground">{data.error ?? "The AI provider returned an error."}</p>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => refetch()}>
            Retry
          </Button>
          <Button asChild>
            <Link href="/learn">Back to course</Link>
          </Button>
        </div>
      </div>
    );
  }
  if (data.status !== "ready") return <Generating lesson={data} />;
  return <Player key={attempt} lesson={data} onRestart={() => setAttempt((a) => a + 1)} />;
}
