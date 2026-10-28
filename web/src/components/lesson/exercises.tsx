"use client";

import { Eye, EyeOff, LoaderCircle } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { AudioButton } from "@/components/audio-button";
import { RecordButton } from "@/components/record-button";
import { RubyText } from "@/components/ruby-text";
import { TargetInput } from "@/components/target-input";
import { Kbd } from "@/components/ui/primitives";
import type { Recording } from "@/hooks/use-recorder";
import { api, errorMessage } from "@/lib/api";
import { stripRuby } from "@/lib/japanese";
import { sounds } from "@/lib/sounds";
import type { AnswerResult, Exercise, Lang } from "@/lib/types";
import { cn, shuffle } from "@/lib/utils";

export type AnswerValue = {
  text?: string;
  selected?: number;
  clientCorrect?: boolean;
  speak?: SpeakResult;
  ready: boolean;
};

export type SpeakResult = {
  transcript: string;
  words: { word: string; ok: boolean }[];
  accuracy: number;
  verdict: "correct" | "typo" | "wrong";
  is_correct: boolean;
  note: string;
};

export type ExerciseProps = {
  ex: Exercise;
  lang: Lang;
  value: AnswerValue;
  onChange: (v: AnswerValue) => void;
  result: AnswerResult | null;
  /** submit immediately (match pairs finished, speech graded, Enter in a text box) */
  onSubmit: (v?: AnswerValue) => void;
};

const PROMPTS: Record<string, string> = {
  multiple_choice: "Choose the right answer",
  listening_choice: "What did you hear?",
  word_bank: "Build the sentence",
  translate: "Translate this",
  fill_blank: "Fill in the blank",
  match_pairs: "Match the pairs",
  dictation: "Type what you hear",
  speak: "Read this aloud",
  reading: "Read and answer",
  kana_choice: "Which is it?",
};

export function ExerciseTitle({ ex }: { ex: Exercise }) {
  const label =
    ex.type === "translate" ? (ex.direction === "to_english" ? "Translate into English" : "Translate this sentence") : PROMPTS[ex.type];
  return <h2 className="text-xl font-extrabold tracking-tight sm:text-2xl">{ex.prompt && ex.type === "multiple_choice" ? ex.prompt : label}</h2>;
}

// ------------------------------------------------------------------ choice options (shared)

function useNumberKeys(count: number, onPick: (i: number) => void, enabled: boolean) {
  React.useEffect(() => {
    if (!enabled) return;
    const h = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "TEXTAREA" || (e.target as HTMLElement)?.tagName === "INPUT") return;
      const n = Number(e.key);
      if (n >= 1 && n <= count) {
        e.preventDefault();
        onPick(n - 1);
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [count, onPick, enabled]);
}

function Options({
  options,
  lang,
  selected,
  onSelect,
  result,
  big,
  grid,
}: {
  options: string[];
  lang: Lang | "en";
  selected?: number;
  onSelect: (i: number) => void;
  result: AnswerResult | null;
  big?: boolean;
  grid?: boolean;
}) {
  const locked = !!result;
  useNumberKeys(options.length, onSelect, !locked);
  return (
    <div className={cn("grid gap-2.5", grid && "grid-cols-2")}>
      {options.map((o, i) => {
        const isSel = selected === i;
        const correct = result && result.correct_index === i;
        const wrongPick = result && isSel && !result.is_correct;
        return (
          <button
            key={i}
            type="button"
            disabled={locked}
            onClick={() => {
              sounds.tap();
              onSelect(i);
            }}
            aria-pressed={isSel}
            className={cn(
              "flex items-center gap-3 rounded-2xl border-2 border-b-4 bg-card px-4 py-3.5 text-left font-medium transition",
              big ? "justify-center py-5 text-3xl font-jp" : "text-[17px]",
              !locked && "hover:border-primary/50 hover:bg-primary-soft/40",
              isSel && !locked && "border-primary bg-primary-soft",
              correct && "border-success bg-success-soft",
              wrongPick && "animate-shake border-danger bg-danger-soft",
            )}
          >
            {!big && <Kbd className="shrink-0">{i + 1}</Kbd>}
            <span lang={lang === "en" ? "en" : lang} className="min-w-0">
              {lang === "en" ? o : <RubyText text={o} lang={lang} showRomaji={false} />}
            </span>
          </button>
        );
      })}
    </div>
  );
}

// ------------------------------------------------------------------ exercise types

function MultipleChoice({ ex, lang, value, onChange, result }: ExerciseProps) {
  const qLang = ex.question_lang === "en" ? "en" : lang;
  return (
    <div className="space-y-7">
      <div className="flex items-center gap-3 rounded-2xl border bg-card p-5">
        {qLang !== "en" && <AudioButton text={ex.question} lang={lang} autoPlay />}
        <p className="text-2xl font-bold leading-snug">
          {qLang === "en" ? ex.question : <RubyText text={ex.question} lang={lang} />}
        </p>
      </div>
      <Options
        options={ex.options}
        lang={ex.options_lang === "target" ? lang : "en"}
        selected={value.selected}
        onSelect={(i) => onChange({ selected: i, ready: true })}
        result={result}
      />
    </div>
  );
}

function ListeningChoice({ ex, lang, value, onChange, result }: ExerciseProps) {
  return (
    <div className="space-y-7">
      <div className="flex items-center justify-center gap-4 py-2">
        <AudioButton text={ex.audio_text} lang={lang} size="xl" variant="solid" autoPlay />
        <AudioButton text={ex.audio_text} lang={lang} slow size="lg" />
      </div>
      <Options
        options={ex.options}
        lang={ex.options_lang === "target" ? lang : "en"}
        selected={value.selected}
        onSelect={(i) => onChange({ selected: i, ready: true })}
        result={result}
        big={lang === "ja" && ex.options.every((o: string) => o.length <= 2)}
        grid={lang === "ja" && ex.options.every((o: string) => o.length <= 2)}
      />
    </div>
  );
}

function KanaChoice({ ex, value, onChange, result }: ExerciseProps) {
  const toRomaji = ex.mode === "char_to_romaji";
  return (
    <div className="space-y-7">
      <div className="flex flex-col items-center gap-3">
        <div className="flex size-36 items-center justify-center rounded-[1.75rem] border-2 bg-card text-center shadow-sm">
          {toRomaji ? (
            <span className="font-jp text-[88px] leading-none" lang="ja">
              {ex.char}
            </span>
          ) : (
            <span className="text-5xl font-black">{ex.romaji}</span>
          )}
        </div>
        {!toRomaji && <AudioButton text={ex.char} lang="ja" />}
      </div>
      <Options
        options={ex.options}
        lang={toRomaji ? "en" : "ja"}
        selected={value.selected}
        onSelect={(i) => onChange({ selected: i, ready: true })}
        result={result}
        big={!toRomaji}
        grid
      />
    </div>
  );
}

function SourceSentence({ text, lang, isTarget }: { text: string; lang: Lang; isTarget: boolean }) {
  return (
    <div className="flex items-start gap-3 rounded-2xl border bg-card p-5">
      {isTarget && <AudioButton text={text} lang={lang} autoPlay />}
      <p className="text-xl font-semibold leading-snug sm:text-2xl">
        {isTarget ? <RubyText text={text} lang={lang} /> : text}
      </p>
    </div>
  );
}

function Translate({ ex, lang, value, onChange, result, onSubmit }: ExerciseProps) {
  const toEnglish = ex.direction === "to_english";
  return (
    <div className="space-y-5">
      <SourceSentence text={ex.source} lang={lang} isTarget={toEnglish} />
      <TargetInput
        lang={toEnglish ? "en" : lang}
        value={value.text ?? ""}
        onChange={(t) => onChange({ text: t, ready: t.trim().length > 0 })}
        onSubmit={() => onSubmit()}
        placeholder={toEnglish ? "Type in English" : "Type your translation"}
        disabled={!!result}
        autoFocus
        multiline
      />
    </div>
  );
}

function Dictation({ ex, lang, value, onChange, result, onSubmit }: ExerciseProps) {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-center gap-4 py-2">
        <AudioButton text={ex.text} lang={lang} size="xl" variant="solid" autoPlay />
        <AudioButton text={ex.text} lang={lang} slow size="lg" />
      </div>
      <TargetInput
        lang={lang}
        value={value.text ?? ""}
        onChange={(t) => onChange({ text: t, ready: t.trim().length > 0 })}
        onSubmit={() => onSubmit()}
        placeholder="Type what you hear"
        disabled={!!result}
        autoFocus
      />
    </div>
  );
}

function FillBlank({ ex, lang, value, onChange, result, onSubmit }: ExerciseProps) {
  const [before, after] = String(ex.sentence).split("___");
  const options: string[] | undefined = ex.options;
  const filled = result ? (result.matched ?? (options && value.selected != null ? options[value.selected] : value.text)) : null;
  return (
    <div className="space-y-6">
      <div className="rounded-2xl border bg-card p-5">
        <p className="text-xl font-semibold leading-[2.2] sm:text-2xl" lang={lang}>
          <RubyText text={before} lang={lang} showRomaji={false} />
          {options ? (
            <span
              className={cn(
                "mx-1 inline-block min-w-16 rounded-lg border-b-2 border-dashed border-primary px-2 text-center text-primary-strong",
                result && (result.is_correct ? "border-success text-success" : "border-danger text-danger"),
              )}
            >
              {value.selected != null ? options[value.selected] : " "}
            </span>
          ) : (
            <input
              lang={lang}
              autoFocus
              disabled={!!result}
              value={result && filled ? filled : value.text ?? ""}
              onChange={(e) => onChange({ text: e.target.value, ready: e.target.value.trim().length > 0 })}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.nativeEvent.isComposing && e.keyCode !== 229) {
                  e.preventDefault();
                  onSubmit();
                }
              }}
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              aria-label="Missing word"
              style={{ width: `${Math.max(4, (String(ex.answers?.[0] ?? "").length || 4) + 2)}ch` }}
              className={cn(
                "mx-1 inline-block rounded-lg border-b-2 border-primary bg-primary-soft/50 px-2 text-center text-primary-strong outline-none",
                result && (result.is_correct ? "border-success bg-success-soft text-success" : "border-danger bg-danger-soft text-danger"),
              )}
            />
          )}
          <RubyText text={after ?? ""} lang={lang} showRomaji={false} />
        </p>
        {ex.hint && <p className="mt-2 text-sm font-medium text-muted-foreground">Hint: {ex.hint}</p>}
        {ex.translation && <p className="mt-1 text-sm text-muted-foreground">“{ex.translation}”</p>}
      </div>
      {options && (
        <Options options={options} lang={lang} selected={value.selected}
          result={result ? { ...result, correct_index: options.findIndex((o) => (ex.answers as string[]).includes(o)) } : null}
          onSelect={(i) => !result && onChange({ selected: i, text: options[i], ready: true })} />
      )}
    </div>
  );
}

function WordBank({ ex, lang, value, onChange, result }: ExerciseProps) {
  const tiles = React.useMemo(
    () => shuffle([...(ex.answer_tiles as string[]), ...((ex.distractors as string[]) ?? [])]).map((t, i) => ({ id: i, t })),
    [ex],
  );
  const [picked, setPicked] = React.useState<number[]>([]);
  const joiner = lang === "ja" ? "" : " ";
  const update = (next: number[]) => {
    setPicked(next);
    const text = next.map((id) => tiles.find((x) => x.id === id)!.t).join(joiner);
    onChange({ text, ready: next.length > 0 });
  };
  return (
    <div className="space-y-6">
      <SourceSentence text={ex.prompt} lang={lang} isTarget={false} />
      <div
        className={cn(
          "flex min-h-[4.5rem] flex-wrap content-start gap-2 border-b-2 border-dashed pb-3",
          result && (result.is_correct ? "border-success" : "border-danger"),
        )}
        aria-label="Your answer"
      >
        {picked.map((id) => (
          <button
            key={id}
            type="button"
            disabled={!!result}
            onClick={() => update(picked.filter((p) => p !== id))}
            className="animate-pop rounded-xl border-2 border-b-4 bg-card px-3 py-2 text-[17px] font-medium transition hover:border-danger/50"
            lang={lang}
          >
            <RubyText text={tiles.find((x) => x.id === id)!.t} lang={lang} showRomaji={false} />
          </button>
        ))}
        {!picked.length && <span className="self-center text-sm text-muted-foreground">Tap the words below in order</span>}
      </div>
      <div className="flex flex-wrap justify-center gap-2">
        {tiles.map(({ id, t }) => {
          const used = picked.includes(id);
          return (
            <button
              key={id}
              type="button"
              disabled={used || !!result}
              onClick={() => {
                sounds.tap();
                update([...picked, id]);
              }}
              className={cn(
                "rounded-xl border-2 border-b-4 px-3 py-2 text-[17px] font-medium transition",
                used ? "border-transparent bg-muted text-transparent" : "bg-card hover:border-primary/50",
              )}
              lang={lang}
              aria-hidden={used}
            >
              <RubyText text={t} lang={lang} showRomaji={false} />
            </button>
          );
        })}
      </div>
      {value.text && !result && <span className="sr-only">Current answer: {value.text}</span>}
    </div>
  );
}

function MatchPairs({ ex, lang, onChange, onSubmit, result }: ExerciseProps) {
  const pairs = ex.pairs as { left: string; right: string }[];
  const lefts = React.useMemo(() => shuffle(pairs.map((p, i) => ({ i, t: p.left }))), [pairs]);
  const rights = React.useMemo(() => shuffle(pairs.map((p, i) => ({ i, t: p.right }))), [pairs]);
  const [sel, setSel] = React.useState<{ side: "l" | "r"; i: number } | null>(null);
  const [done, setDone] = React.useState<number[]>([]);
  const [wrong, setWrong] = React.useState<number[]>([]);
  const mistakes = React.useRef(0);

  const choose = (side: "l" | "r", i: number) => {
    if (result || done.includes(i)) return;
    if (!sel || sel.side === side) {
      setSel({ side, i });
      return;
    }
    if (sel.i === i) {
      sounds.correct();
      const next = [...done, i];
      setDone(next);
      setSel(null);
      if (next.length === pairs.length) {
        const v = { clientCorrect: mistakes.current <= 1, ready: true, text: `${mistakes.current} mistakes` };
        onChange(v);
        setTimeout(() => onSubmit(v), 350);
      }
    } else {
      sounds.wrong();
      mistakes.current++;
      setWrong([sel.i, i]);
      setSel(null);
      setTimeout(() => setWrong([]), 450);
    }
  };

  const tile = (side: "l" | "r", item: { i: number; t: string }) => {
    const isDone = done.includes(item.i);
    const isSel = sel?.side === side && sel.i === item.i;
    const isWrong = wrong.length > 0 && (side === "l" ? wrong[0] === item.i : wrong[1] === item.i);
    return (
      <button
        key={`${side}${item.i}`}
        type="button"
        disabled={isDone}
        onClick={() => choose(side, item.i)}
        className={cn(
          "min-h-14 rounded-2xl border-2 border-b-4 bg-card px-3 py-2.5 text-[16px] font-medium transition",
          !isDone && "hover:border-primary/50",
          isSel && "border-primary bg-primary-soft",
          isDone && "border-success/40 bg-success-soft text-success opacity-60",
          isWrong && "animate-shake border-danger bg-danger-soft",
        )}
        lang={side === "l" ? lang : "en"}
      >
        {side === "l" ? <RubyText text={item.t} lang={lang} showRomaji={false} /> : item.t}
      </button>
    );
  };

  return (
    <div className="grid grid-cols-2 gap-3">
      <div className="flex flex-col gap-2.5">{lefts.map((l) => tile("l", l))}</div>
      <div className="flex flex-col gap-2.5">{rights.map((r) => tile("r", r))}</div>
    </div>
  );
}

function Speak({ ex, lang, value, onChange, onSubmit, result }: ExerciseProps) {
  const [busy, setBusy] = React.useState(false);
  const [showTranslation, setShowTranslation] = React.useState(false);
  const graded = value.speak;
  const onRecorded = async (r: Recording) => {
    setBusy(true);
    const form = new FormData();
    form.append("audio", r.blob, `speech.${r.mime.includes("mp4") ? "m4a" : "webm"}`);
    form.append("duration_ms", String(r.durationMs));
    try {
      const res = await api<SpeakResult>(`/exercises/${ex.id}/speak`, { form });
      const v = { speak: res, clientCorrect: res.is_correct, ready: true, text: res.transcript };
      onChange(v);
      onSubmit(v);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-6">
      <div className="rounded-2xl border bg-card p-5">
        <div className="flex items-start gap-3">
          <AudioButton text={ex.text} lang={lang} />
          <p className="flex-1 text-2xl font-semibold leading-snug">
            {graded ? (
              <span lang={lang}>
                {graded.words.map((w, i) => (
                  <span key={i} className={cn("rounded px-0.5", w.ok ? "text-success" : "bg-danger-soft text-danger")}>
                    {w.word}
                    {lang === "ja" ? "" : " "}
                  </span>
                ))}
              </span>
            ) : (
              <RubyText text={ex.text} lang={lang} />
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowTranslation(!showTranslation)}
          className="mt-3 flex items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground"
        >
          {showTranslation ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
          {showTranslation ? ex.translation : "Show meaning"}
        </button>
      </div>
      {!result && (
        <div className="flex flex-col items-center gap-2 pt-2">
          {busy ? (
            <p className="flex h-[104px] items-center gap-2 text-sm text-muted-foreground">
              <LoaderCircle className="size-5 animate-spin" /> Listening to your recording…
            </p>
          ) : (
            <RecordButton onRecorded={onRecorded} mode="toggle" spaceToTalk hint="Tap and read the sentence aloud" />
          )}
          <button
            type="button"
            onClick={() => {
              const v = { clientCorrect: true, ready: true, text: "(skipped)" };
              onChange(v);
              onSubmit(v);
            }}
            className="text-sm font-medium text-muted-foreground hover:text-foreground"
          >
            Can&apos;t speak right now
          </button>
        </div>
      )}
    </div>
  );
}

function Reading({ ex, lang, value, onChange, result }: ExerciseProps) {
  const questions = ex.questions as { question: string; options: string[]; answer_index: number }[];
  const [answers, setAnswers] = React.useState<(number | undefined)[]>([]);
  const [translation, setTranslation] = React.useState(false);
  const pick = (qi: number, oi: number) => {
    const next = [...answers];
    next[qi] = oi;
    setAnswers(next);
    const complete = questions.every((_, i) => next[i] != null);
    onChange({ ready: complete, clientCorrect: questions.every((q, i) => q.answer_index === next[i]), text: next.join(",") });
  };
  return (
    <div className="space-y-5">
      <div className="rounded-2xl border bg-card p-5">
        <div className="flex items-center justify-between gap-3">
          <h3 className="font-bold">{ex.title}</h3>
          <AudioButton text={stripRuby(ex.passage)} lang={lang} size="sm" />
        </div>
        <p className="mt-2 whitespace-pre-line text-[17px] leading-relaxed">
          <RubyText text={ex.passage} lang={lang} showRomaji={false} />
        </p>
        {ex.translation && (
          <button type="button" onClick={() => setTranslation(!translation)} className="mt-3 text-sm font-medium text-muted-foreground hover:text-foreground">
            {translation ? "Hide translation" : "Show translation"}
          </button>
        )}
        {translation && <p className="mt-2 text-sm text-muted-foreground">{ex.translation}</p>}
      </div>
      {questions.map((q, qi) => (
        <div key={qi} className="space-y-2">
          <p className="font-semibold">{q.question}</p>
          <div className="grid gap-2">
            {q.options.map((o, oi) => {
              const sel = answers[qi] === oi;
              return (
                <button
                  key={oi}
                  type="button"
                  disabled={!!result}
                  onClick={() => pick(qi, oi)}
                  className={cn(
                    "rounded-xl border-2 bg-card px-3.5 py-2.5 text-left text-[15px] transition hover:border-primary/50",
                    sel && !result && "border-primary bg-primary-soft",
                    result && oi === q.answer_index && "border-success bg-success-soft",
                    result && sel && oi !== q.answer_index && "border-danger bg-danger-soft",
                  )}
                >
                  {o}
                </button>
              );
            })}
          </div>
        </div>
      ))}
      {value.ready && !result && <span className="sr-only">All questions answered</span>}
    </div>
  );
}

const RENDERERS: Record<string, React.ComponentType<ExerciseProps>> = {
  multiple_choice: MultipleChoice,
  listening_choice: ListeningChoice,
  kana_choice: KanaChoice,
  translate: Translate,
  dictation: Dictation,
  fill_blank: FillBlank,
  word_bank: WordBank,
  match_pairs: MatchPairs,
  speak: Speak,
  reading: Reading,
};

export function ExerciseView(props: ExerciseProps) {
  const Comp = RENDERERS[props.ex.type];
  if (!Comp) return <p className="text-muted-foreground">Unsupported exercise type: {props.ex.type}</p>;
  return <Comp {...props} />;
}

export const INFO_TYPES = new Set(["vocab_intro", "grammar_note", "kana_intro"]);
export const SELF_SUBMITTING = new Set(["match_pairs", "speak"]);
