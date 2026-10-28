"use client";

import { CircleCheck, CircleX, Flag, Sparkles } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { AudioButton } from "@/components/audio-button";
import { RubyText } from "@/components/ruby-text";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/overlay";
import { Textarea } from "@/components/ui/primitives";
import { errorMessage, post } from "@/lib/api";
import { isJapanese } from "@/lib/japanese";
import type { AnswerResult, Lang, Segment } from "@/lib/types";
import { cn } from "@/lib/utils";

import type { SpeakResult } from "./exercises";

export function ReportDialog({
  open,
  onOpenChange,
  target,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  target: { type: "exercise" | "lesson" | "turn" | "vocab"; id: number };
}) {
  const [reason, setReason] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const presets = ["The answer is wrong", "My answer should be accepted", "The audio is wrong", "Typo or unnatural sentence"];
  const send = async () => {
    setBusy(true);
    try {
      await post("/flags", { target_type: target.type, target_id: target.id, reason });
      toast.success("Thanks — flagged for review.");
      onOpenChange(false);
      setReason("");
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Report a problem" description="An admin will review it and fix or regenerate the content.">
        <div className="flex flex-wrap gap-2">
          {presets.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setReason(p)}
              className={cn("rounded-full border px-3 py-1.5 text-sm transition hover:bg-muted", reason === p && "border-primary bg-primary-soft")}
            >
              {p}
            </button>
          ))}
        </div>
        <Textarea className="mt-3" placeholder="Anything else? (optional)" value={reason} onChange={(e) => setReason(e.target.value)} />
        <Button className="mt-4 w-full" disabled={!reason.trim()} loading={busy} onClick={send}>
          Send report
        </Button>
      </DialogContent>
    </Dialog>
  );
}

function Segments({ segments }: { segments: Segment[] }) {
  return (
    <>
      {segments.map((s, i) => (
        <span
          key={i}
          className={cn(
            s.kind === "accent" && "rounded bg-warning-soft px-0.5 text-warning underline decoration-wavy underline-offset-4",
            s.kind === "typo" && "rounded bg-warning-soft px-0.5 text-warning",
          )}
        >
          {s.text}
        </span>
      ))}
    </>
  );
}

const HEADINGS: Record<string, string> = {
  correct: "Correct!",
  typo: "Correct — watch the spelling",
  accent: "Almost — mind the accents",
  ai_accepted: "Accepted — nice alternative",
  wrong: "Not quite",
};

const CHEERS = ["Nice!", "Great job!", "Excellent!", "Spot on!", "Brilliant!", "You got it!"];

/** Slide-up result panel with the right answer, explanation and audio. */
export function FeedbackPanel({
  result,
  lang,
  speak,
  exerciseId,
  onContinue,
  answerInTarget = true,
}: {
  result: AnswerResult;
  lang: Lang;
  speak?: SpeakResult;
  exerciseId: number;
  onContinue: () => void;
  /** false when the expected answer is English (translate → English) */
  answerInTarget?: boolean;
}) {
  const [report, setReport] = React.useState(false);
  const good = result.is_correct;
  const heading = result.verdict === "correct" ? CHEERS[exerciseId % CHEERS.length] : HEADINGS[result.verdict];
  const answer = result.correct_answer;
  const answerIsTarget = !!answer && (lang === "ja" ? isJapanese(answer) : answerInTarget);
  const Icon = good ? CircleCheck : CircleX;

  return (
    <div
      className={cn(
        "animate-in slide-in-from-bottom-8 fade-in-0 border-t-2 duration-300",
        good ? "border-success/40 bg-success-soft" : "border-danger/40 bg-danger-soft",
      )}
      role="status"
      aria-live="polite"
    >
      <div className="mx-auto flex max-w-2xl flex-col gap-4 px-4 py-5 sm:flex-row sm:items-end sm:px-6">
        <div className="min-w-0 flex-1">
          <p className={cn("flex items-center gap-2 text-xl font-extrabold", good ? "text-success" : "text-danger")}>
            <Icon className="size-7" /> {heading}
            {result.judged_by_ai && good && <Sparkles className="size-4" aria-label="Judged by AI" />}
          </p>
          {speak && (
            <p className="mt-2 text-[15px]">
              <span className="text-muted-foreground">We heard: </span>
              <span lang={lang}>{speak.transcript || "—"}</span>
              <span className="ml-2 text-sm text-muted-foreground">({Math.round(speak.accuracy * 100)}% of words)</span>
            </p>
          )}
          {answer && result.verdict !== "correct" && !speak && (
            <div className="mt-2 flex items-start gap-2">
              <p className="text-[16px]">
                <span className="font-semibold">{result.verdict === "ai_accepted" ? "Also correct: " : "Correct answer: "}</span>
                <span lang={answerIsTarget ? lang : "en"}>
                  {result.segments && result.verdict !== "wrong" ? (
                    <Segments segments={result.segments} />
                  ) : answerIsTarget ? (
                    <RubyText text={answer} lang={lang} showRomaji={false} />
                  ) : (
                    answer
                  )}
                </span>
              </p>
              {answerIsTarget && <AudioButton text={answer} lang={lang} size="sm" autoPlay={!good} />}
            </div>
          )}
          {(result.ai_explanation || result.explanation) && (
            <p className="mt-1.5 text-sm text-foreground/80">{result.ai_explanation || result.explanation}</p>
          )}
          {speak && <p className="mt-1 text-xs text-muted-foreground">{speak.note}</p>}
          <button
            type="button"
            onClick={() => setReport(true)}
            className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground"
          >
            <Flag className="size-3.5" /> Report a problem
          </button>
        </div>
        <Button size="xl" variant={good ? "success" : "danger"} className="w-full sm:w-48" onClick={onContinue} autoFocus>
          Continue
        </Button>
      </div>
      <ReportDialog open={report} onOpenChange={setReport} target={{ type: "exercise", id: exerciseId }} />
    </div>
  );
}
