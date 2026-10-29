"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  Ear,
  Languages,
  LoaderCircle,
  Mic,
  Play,
  Plus,
  RefreshCw,
  Sparkles,
  ThumbsUp,
  Trash,
  Volume2,
} from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { AudioButton } from "@/components/audio-button";
import { DiffText } from "@/components/diff-text";
import { RubyText } from "@/components/ruby-text";
import { Badge } from "@/components/ui/primitives";
import { del, errorMessage, post } from "@/lib/api";
import { player, playSequence } from "@/lib/audio";
import { stripRuby } from "@/lib/japanese";
import { ERROR_TYPE_LABEL } from "@/lib/languages";
import type { ConversationSettings, Feedback, Lang, Turn } from "@/lib/types";
import { cn } from "@/lib/utils";

function ToolButton({ onClick, label, children, active }: { onClick: () => void; label: string; children: React.ReactNode; active?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={cn(
        "flex h-7 items-center gap-1 rounded-lg px-2 text-xs font-medium text-muted-foreground transition hover:bg-muted hover:text-foreground [&_svg]:size-3.5",
        active && "bg-muted text-foreground",
      )}
    >
      {children}
    </button>
  );
}

export function AiBubble({
  turn,
  lang,
  settings,
  onWordTap,
  mode,
}: {
  turn: Turn;
  lang: Lang;
  settings: ConversationSettings;
  onWordTap: (w: string, el: HTMLElement, context: string) => void;
  mode: string;
}) {
  const [showTranslation, setShowTranslation] = React.useState(false);
  const translate = useMutation({
    mutationFn: () => post<{ translation: string }>(`/turns/${turn.id}/translate`),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const translation = turn.translation ?? translate.data?.translation;
  const [playing, setPlaying] = React.useState(false);
  React.useEffect(() => player?.subscribe((p) => setPlaying(p === `turn-${turn.id}`)), [turn.id]);

  const replay = () => {
    if (playing) return player.stop();
    if (turn.audio_urls.length) void playSequence(turn.audio_urls, `turn-${turn.id}`, 1);
  };

  const tutor = mode === "tutor";
  return (
    <div className="flex max-w-[88%] flex-col items-start gap-1 sm:max-w-[78%]">
      <div className="rounded-2xl rounded-tl-md border bg-card px-4 py-3 text-[17px] leading-relaxed shadow-sm">
        {tutor ? (
          <p className="whitespace-pre-line text-[16px]">
            <RubyText text={turn.text} lang={lang} furigana={settings.furigana} romaji="off" />
          </p>
        ) : (
          <RubyText
            text={turn.text}
            lang={lang}
            furigana={settings.furigana}
            romaji={settings.romaji}
            onWordTap={(w, el) => onWordTap(w, el, stripRuby(turn.text))}
          />
        )}
        {showTranslation && (
          <p className="mt-2 border-t pt-2 text-[15px] text-muted-foreground">
            {translation ?? (
              <span className="flex items-center gap-1.5">
                <LoaderCircle className="size-3.5 animate-spin" /> Translating…
              </span>
            )}
          </p>
        )}
      </div>
      {!tutor && (
        <div className="flex items-center gap-0.5 pl-1">
          {turn.audio_urls.length > 0 && (
            <ToolButton onClick={replay} label={playing ? "Stop" : "Replay"} active={playing}>
              <Volume2 className={cn(playing && "animate-pulse")} /> Replay
            </ToolButton>
          )}
          <SlowReplay text={turn.text} lang={lang} />
          <ToolButton
            onClick={() => {
              setShowTranslation(!showTranslation);
              if (!translation && !translate.isPending) translate.mutate();
            }}
            label="Translate to English"
            active={showTranslation}
          >
            <Languages /> {showTranslation ? "Hide" : "Translate"}
          </ToolButton>
        </div>
      )}
    </div>
  );
}

function SlowReplay({ text, lang }: { text: string; lang: Lang }) {
  return (
    <span className="inline-flex">
      <AudioButton text={text} lang={lang} slow size="sm" variant="ghost" purpose="conversation" label="Slow replay" className="size-7 [&_svg]:size-3.5" />
    </span>
  );
}

export function StreamingBubble({ text, lang, settings, status }: {
  text: string; lang: Lang; settings: ConversationSettings; status?: string;
}) {
  return (
    <div className="max-w-[88%] rounded-2xl rounded-tl-md border bg-card px-4 py-3 text-[17px] leading-relaxed shadow-sm sm:max-w-[78%]">
      {text ? (
        <RubyText text={text} lang={lang} streaming furigana={settings.furigana} />
      ) : (
        <>
          <span className="flex gap-1 py-2" aria-label="Typing">
            {[0, 1, 2].map((i) => (
              <span key={i} className="size-2 animate-bounce rounded-full bg-muted-foreground/60" style={{ animationDelay: `${i * 0.15}s` }} />
            ))}
          </span>
          {status && (
            <span className="block text-sm text-muted-foreground" role="status">
              {status}
            </span>
          )}
        </>
      )}
    </div>
  );
}

export function UserBubble({ turn, lang, pendingLabel, localAudio }: { turn?: Turn; lang: Lang; pendingLabel?: string; localAudio?: string }) {
  const [deleted, setDeleted] = React.useState(false);
  const rec = deleted ? undefined : turn?.recording_url ?? localAudio;
  const playRec = () => rec && void player.play(rec, rec);
  const remove = async () => {
    if (!turn?.recording_url || !confirm("Delete this recording? The transcript and feedback stay.")) return;
    try {
      await del(turn.recording_url.replace("/api/v1", ""));
      setDeleted(true);
      toast.success("Recording deleted");
    } catch (e) {
      toast.error(errorMessage(e));
    }
  };
  return (
    <div className="flex max-w-[88%] flex-col items-end gap-1 self-end sm:max-w-[78%]">
      <div className="rounded-2xl rounded-tr-md bg-primary px-4 py-3 text-[17px] leading-relaxed text-primary-foreground shadow-sm">
        {pendingLabel && !turn?.text ? (
          <span className="flex items-center gap-2 text-[15px] text-white/85">
            <Mic className="size-4" /> {pendingLabel}
            <LoaderCircle className="size-4 animate-spin" />
          </span>
        ) : (
          <span lang={lang}>{turn?.text}</span>
        )}
      </div>
      {(turn?.voice || localAudio) && rec && (
        <span className="flex items-center gap-2 pr-1 text-xs font-medium text-muted-foreground">
          <button type="button" onClick={playRec} className="flex items-center gap-1 hover:text-foreground">
            <Play className="size-3" /> My recording
          </button>
          {turn?.recording_url && (
            <button type="button" onClick={remove} className="flex items-center gap-1 hover:text-danger" aria-label="Delete this recording">
              <Trash className="size-3" />
            </button>
          )}
        </span>
      )}
    </div>
  );
}

const OVERALL = {
  perfect: { label: "Perfect", tone: "success" as const, dot: "bg-success" },
  minor_issues: { label: "Minor issues", tone: "warning" as const, dot: "bg-warning" },
  errors: { label: "Errors", tone: "danger" as const, dot: "bg-danger" },
};

export function FeedbackCard({
  turn,
  lang,
  error,
  defaultOpen,
}: {
  turn: Turn;
  lang: Lang;
  error?: string;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = React.useState(!!defaultOpen);
  const qc = useQueryClient();
  const fb = turn.feedback as Feedback | null;
  const [added, setAdded] = React.useState<Set<string>>(new Set());
  const add = useMutation({
    mutationFn: (v: { key: string; word: string; meaning: string; reading?: string | null; example?: string }) =>
      post(`/vocab/${lang}`, { word: v.word, meaning: v.meaning, reading: v.reading, example: v.example, source: "conversation", source_ref: `turn:${turn.id}` }),
    onSuccess: (_d, v) => {
      setAdded((s) => new Set(s).add(v.key));
      toast.success("Added to your review deck");
      void qc.invalidateQueries({ queryKey: ["deck"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const retry = useMutation({ mutationFn: () => post(`/turns/${turn.id}/feedback/retry`) });
  // Feedback arrives after the message: open it automatically when it has real errors.
  const arrivedWithErrors = !!fb && fb.overall === "errors";
  React.useEffect(() => {
    if (defaultOpen && arrivedWithErrors) setOpen(true);
  }, [defaultOpen, arrivedWithErrors]);

  if (!fb) {
    return (
      <div className="mt-1 flex items-center gap-2 self-end pr-1 text-xs text-muted-foreground">
        {error ? (
          <>
            <span className="text-danger">Feedback failed</span>
            <button type="button" className="flex items-center gap-1 font-medium hover:text-foreground" onClick={() => retry.mutate()}>
              <RefreshCw className="size-3" /> Retry
            </button>
          </>
        ) : (
          <>
            <LoaderCircle className="size-3 animate-spin" /> Checking your sentence…
          </>
        )}
      </div>
    );
  }

  const o = OVERALL[fb.overall];
  const pron = turn.pronunciation ?? [];
  return (
    <div className="mt-1 w-full max-w-[88%] self-end sm:max-w-[78%]">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="ml-auto flex items-center gap-2 rounded-full border bg-card px-3 py-1.5 text-xs font-semibold shadow-sm transition hover:bg-muted"
      >
        <span className={cn("size-2.5 rounded-full", o.dot)} />
        {o.label}
        <span className="tabular-nums text-muted-foreground">{fb.score}</span>
        {fb.errors.length > 0 && <span className="text-muted-foreground">· {fb.errors.length} fix{fb.errors.length > 1 ? "es" : ""}</span>}
        {pron.length > 0 && <Ear className="size-3.5 text-warning" aria-label="Possible pronunciation issues" />}
        <ChevronDown className={cn("size-3.5 transition", open && "rotate-180")} />
      </button>
      {open && (
        <div className="mt-2 animate-in fade-in-0 slide-in-from-top-1 space-y-3 rounded-2xl border bg-card p-4 text-[15px] shadow-sm">
          {fb.overall !== "perfect" && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Corrected</p>
              <div className="flex items-start gap-2">
                <p className="flex-1 text-[16px]">
                  <DiffText from={turn.text} to={fb.corrected} lang={lang} />
                </p>
                <AudioButton text={fb.corrected} lang={lang} size="sm" purpose="conversation" />
              </div>
            </div>
          )}
          {fb.more_natural && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">More natural</p>
              <div className="flex items-start gap-2">
                <p className="flex-1 text-[16px] font-medium">
                  <RubyText text={fb.more_natural} lang={lang} showRomaji={false} />
                </p>
                <AudioButton text={fb.more_natural} lang={lang} size="sm" purpose="conversation" />
              </div>
            </div>
          )}
          {fb.errors.length > 0 && (
            <ul className="space-y-2">
              {fb.errors.map((e, i) => {
                const key = `e${i}`;
                return (
                  <li key={i} className="rounded-xl bg-muted/60 p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone="danger">{ERROR_TYPE_LABEL[e.type] ?? e.type}</Badge>
                      <span lang={lang}>
                        <del className="text-danger decoration-2">{e.original}</del> → <ins className="font-semibold text-success no-underline">{stripRuby(e.correction)}</ins>
                      </span>
                    </div>
                    <p className="mt-1.5 text-sm text-muted-foreground">{e.explanation}</p>
                    <button
                      type="button"
                      disabled={added.has(key)}
                      onClick={() => add.mutate({ key, word: stripRuby(e.correction), meaning: e.explanation, example: stripRuby(fb.corrected) })}
                      className="mt-1.5 flex items-center gap-1 text-xs font-semibold text-primary-strong hover:underline disabled:text-success disabled:no-underline"
                    >
                      <Plus className="size-3.5" /> {added.has(key) ? "In your review deck" : "Add to review"}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
          {pron.length > 0 && (
            <div className="rounded-xl border border-warning/40 bg-warning-soft/60 p-3">
              <p className="flex items-center gap-1.5 text-sm font-semibold text-warning">
                <Ear className="size-4" /> Possible pronunciation issues
              </p>
              <ul className="mt-2 space-y-1.5">
                {pron.map((p, i) => (
                  <li key={i} className="flex items-center gap-2 text-sm">
                    <span>
                      We heard <span className="font-semibold" lang={lang}>“{p.heard}”</span>
                      {p.expected && p.expected !== p.heard && (
                        <>
                          {" "}— expected <span className="font-semibold" lang={lang}>“{p.expected}”</span>
                        </>
                      )}
                      {p.reason === "unclear" && <span className="text-muted-foreground"> (unclear)</span>}
                    </span>
                    {p.expected && <AudioButton text={p.expected} lang={lang} size="sm" variant="ghost" className="size-7" />}
                  </li>
                ))}
              </ul>
              {turn.pronunciation_notes?.map((n, i) => (
                <p key={i} className="mt-1 text-sm text-muted-foreground">
                  • {n}
                </p>
              ))}
              <p className="mt-2 text-[11px] text-muted-foreground">
                Approximate — based on speech recognition, not a phoneme-level assessment.
              </p>
            </div>
          )}
          {fb.praise && (
            <p className="flex gap-2 text-sm text-success">
              <ThumbsUp className="mt-0.5 size-4 shrink-0" /> {fb.praise}
            </p>
          )}
          {fb.new_vocab.length > 0 && (
            <div>
              <p className="mb-1.5 flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                <Sparkles className="size-3.5" /> Useful words
              </p>
              <div className="flex flex-wrap gap-1.5">
                {fb.new_vocab.map((v, i) => {
                  const key = `v${i}`;
                  return (
                    <button
                      key={i}
                      type="button"
                      disabled={added.has(key)}
                      onClick={() => add.mutate({ key, word: v.word, meaning: v.meaning, reading: v.reading })}
                      className="flex items-center gap-1.5 rounded-lg border bg-background px-2.5 py-1 text-sm transition hover:border-primary disabled:border-success/40 disabled:text-success"
                      title="Add to review"
                    >
                      <span lang={lang} className="font-semibold">{v.word}</span>
                      <span className="text-muted-foreground">{v.meaning}</span>
                      {added.has(key) ? "✓" : <Plus className="size-3.5" />}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

