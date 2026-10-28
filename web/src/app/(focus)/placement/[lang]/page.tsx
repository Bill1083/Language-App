"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Compass, LoaderCircle, X } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { AudioButton } from "@/components/audio-button";
import { RubyText } from "@/components/ruby-text";
import { Button } from "@/components/ui/button";
import { Card, Progress } from "@/components/ui/primitives";
import { errorMessage, post } from "@/lib/api";
import { CEFR_LABEL, isLang, LANGS } from "@/lib/languages";
import type { Lang } from "@/lib/types";
import { cn } from "@/lib/utils";

type Question = { id: number; level: string; question: string; question_lang: "target" | "en"; options: string[] };
type Answer = { correct: boolean; correct_index: number; done: boolean; question?: Question; progress?: { n: number; max: number }; result?: { level: string; answered: number; correct: number } };

export default function PlacementPage() {
  const params = useParams<{ lang: string }>();
  const lang = (isLang(params.lang) ? params.lang : "fr") as Lang;
  const router = useRouter();
  const qc = useQueryClient();
  const [attempt, setAttempt] = React.useState<string | null>(null);
  const [question, setQuestion] = React.useState<Question | null>(null);
  const [progress, setProgress] = React.useState({ n: 1, max: 15 });
  const [picked, setPicked] = React.useState<number | null>(null);
  const [reveal, setReveal] = React.useState<{ correct: number } | null>(null);
  const [result, setResult] = React.useState<Answer["result"] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const started = React.useRef(false);

  React.useEffect(() => {
    if (started.current) return;
    started.current = true;
    document.documentElement.dataset.lang = lang;
    post<{ attempt_id: string; question: Question; progress: { n: number; max: number } }>(`/placement/${lang}/start`)
      .then((r) => {
        setAttempt(r.attempt_id);
        setQuestion(r.question);
        setProgress(r.progress);
      })
      .catch((e) => setError(errorMessage(e)));
  }, [lang]);

  const answer = async (i: number) => {
    if (!attempt || picked !== null) return;
    setPicked(i);
    try {
      const r = await post<Answer>(`/placement/${lang}/answer`, { attempt_id: attempt, answer_index: i });
      setReveal({ correct: r.correct_index });
      await new Promise((res) => setTimeout(res, 650));
      if (r.done) setResult(r.result!);
      else {
        setQuestion(r.question!);
        setProgress(r.progress!);
      }
    } catch (e) {
      toast.error(errorMessage(e));
    }
    setPicked(null);
    setReveal(null);
  };

  const finish = async (accept: boolean) => {
    setBusy(true);
    try {
      await post(`/placement/${lang}/finish`, { attempt_id: attempt, accept });
      await qc.invalidateQueries();
      router.replace("/learn");
    } catch (e) {
      toast.error(errorMessage(e));
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto flex min-h-dvh max-w-xl flex-col px-4 pb-8 pt-5" data-lang={lang}>
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon" onClick={() => router.replace("/learn")} aria-label="Leave placement test">
          <X />
        </Button>
        <Progress value={result ? 1 : progress.n / progress.max} className="flex-1" />
      </div>

      {error ? (
        <Card className="mt-16 p-6 text-center">
          <p className="font-semibold">Couldn&apos;t prepare the test</p>
          <p className="mt-1 text-sm text-muted-foreground">{error}</p>
          <Button className="mt-4" variant="outline" onClick={() => router.replace("/learn")}>
            Start from the beginning instead
          </Button>
        </Card>
      ) : result ? (
        <div className="flex flex-1 animate-rise flex-col items-center justify-center text-center">
          <div className="flex size-20 items-center justify-center rounded-3xl bg-primary-soft text-primary">
            <Compass className="size-10" />
          </div>
          <p className="mt-6 text-sm font-semibold uppercase tracking-wider text-muted-foreground">Your starting level</p>
          <p className="mt-1 text-5xl font-black text-primary">{result.level}</p>
          <p className="mt-1 text-lg font-semibold">{CEFR_LABEL[result.level]}</p>
          <p className="mt-3 max-w-sm text-sm text-muted-foreground">
            You got {result.correct} of {result.answered} right. Earlier levels stay open for revision, and you can change
            your level any time in Settings.
          </p>
          <div className="mt-8 flex w-full flex-col gap-2.5 sm:w-auto sm:flex-row">
            <Button size="lg" loading={busy} onClick={() => finish(true)}>
              Start at {result.level}
            </Button>
            {result.level !== "A1" && (
              <Button size="lg" variant="outline" disabled={busy} onClick={() => finish(false)}>
                Start from A1 instead
              </Button>
            )}
          </div>
        </div>
      ) : !question ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center text-muted-foreground">
          <LoaderCircle className="size-8 animate-spin text-primary" />
          <p className="font-medium text-foreground">Preparing your {LANGS[lang].name} placement test…</p>
          <p className="max-w-xs text-sm">The first time, the questions are written for you — this can take up to a minute.</p>
        </div>
      ) : (
        <div className="flex flex-1 animate-rise flex-col py-10" key={question.id}>
          <p className="text-sm font-semibold text-muted-foreground">
            Question {progress.n} of up to {progress.max}
          </p>
          <div className="mt-4 flex items-start gap-3">
            <h1 className="flex-1 text-2xl font-bold leading-snug">
              {question.question_lang === "target" ? <RubyText text={question.question} lang={lang} /> : question.question}
            </h1>
            {question.question_lang === "target" && <AudioButton text={question.question} lang={lang} />}
          </div>
          <div className="mt-8 grid gap-2.5">
            {question.options.map((o, i) => (
              <button
                key={i}
                type="button"
                disabled={picked !== null}
                onClick={() => answer(i)}
                className={cn(
                  "flex items-center gap-3 rounded-2xl border-2 bg-card px-4 py-3.5 text-left text-[17px] font-medium transition hover:border-primary/60",
                  picked === i && !reveal && "border-primary bg-primary-soft",
                  reveal && i === reveal.correct && "border-success bg-success-soft",
                  reveal && picked === i && i !== reveal.correct && "animate-shake border-danger bg-danger-soft",
                )}
              >
                <span className="flex size-7 shrink-0 items-center justify-center rounded-lg border text-sm font-bold text-muted-foreground">
                  {i + 1}
                </span>
                <span lang={lang}>{o}</span>
              </button>
            ))}
          </div>
          <button
            type="button"
            className="mt-6 self-center text-sm font-medium text-muted-foreground hover:text-foreground"
            onClick={() => answer(-1)}
            disabled={picked !== null}
          >
            I don&apos;t know
          </button>
        </div>
      )}
    </div>
  );
}
