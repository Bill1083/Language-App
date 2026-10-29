"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CircleCheck,
  Keyboard,
  Languages,
  Lightbulb,
  LoaderCircle,
  Mic,
  Send,
  Settings2,
  Target,
  WifiOff,
} from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { AudioButton } from "@/components/audio-button";
import { Flag } from "@/components/flag";
import { RecordButton } from "@/components/record-button";
import { RubyText } from "@/components/ruby-text";
import { AiBubble, FeedbackCard, StreamingBubble, UserBubble } from "@/components/talk/messages";
import { ConversationSettingsForm } from "@/components/talk/settings-form";
import { TargetInput } from "@/components/target-input";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/overlay";
import { Input, Skeleton } from "@/components/ui/primitives";
import { useWordPopover, WordPopover } from "@/components/word-popover";
import { useConversationSocket } from "@/hooks/use-conversation-socket";
import type { Recording } from "@/hooks/use-recorder";
import { api, errorMessage, get, patch, post } from "@/lib/api";
import { LANGS } from "@/lib/languages";
import { sounds } from "@/lib/sounds";
import type { Conversation, ConversationSettings } from "@/lib/types";
import { cn } from "@/lib/utils";

type Hint = { suggestions: { target: string; english: string }[] };
type Say = { target: string; reading: string | null; english: string; notes: string | null; alternatives: string[] };

function useRecordMode(): ["hold" | "toggle", (m: "hold" | "toggle") => void] {
  const [mode, setMode] = React.useState<"hold" | "toggle">("hold");
  React.useEffect(() => {
    try {
      const saved = localStorage.getItem("parlo-record-mode");
      if (saved === "hold" || saved === "toggle") setMode(saved);
      else if (!window.matchMedia("(pointer: coarse)").matches) setMode("toggle");
    } catch {
      /* storage unavailable — keep the default */
    }
  }, []);
  const set = (m: "hold" | "toggle") => {
    setMode(m);
    try {
      localStorage.setItem("parlo-record-mode", m);
    } catch {
      /* ignore */
    }
  };
  return [mode, set];
}

function ConversationScreen({ conv }: { conv: Conversation }) {
  const router = useRouter();
  const qc = useQueryClient();
  const lang = conv.language;
  const [settings, setSettings] = React.useState<ConversationSettings>(conv.settings);
  const [goal, setGoal] = React.useState(conv.goal_achieved);
  const [inputMode, setInputMode] = React.useState<"voice" | "text">(conv.settings.input);
  const [text, setText] = React.useState("");
  const [recordMode, setRecordMode] = useRecordMode();
  const [uploading, setUploading] = React.useState(false);
  const [settingsOpen, setSettingsOpen] = React.useState(false);
  const [hintOpen, setHintOpen] = React.useState(false);
  const [sayOpen, setSayOpen] = React.useState(false);
  const [endOpen, setEndOpen] = React.useState(false);
  const [english, setEnglish] = React.useState("");
  const words = useWordPopover();
  const bottom = React.useRef<HTMLDivElement>(null);
  const input = React.useRef<HTMLTextAreaElement>(null);
  const ended = !!conv.ended_at;

  const socket = useConversationSocket(conv.id, conv.turns, {
    voice: settings.ai_voice,
    rate: settings.speed,
    onGoal: () => {
      setGoal(true);
      sounds.complete();
      toast.success("Goal achieved! 🎯", { description: conv.scenario?.goal });
    },
  });

  React.useEffect(() => {
    document.documentElement.dataset.lang = lang;
  }, [lang]);

  React.useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [socket.turns.length, socket.pending.length, socket.streaming?.text]);

  const hint = useMutation({ mutationFn: () => post<Hint>(`/conversations/${conv.id}/hint`), onError: (e) => toast.error(errorMessage(e)) });
  const say = useMutation({
    mutationFn: (en: string) => post<Say>(`/conversations/${conv.id}/say`, { english: en }),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const end = useMutation({
    mutationFn: () => post(`/conversations/${conv.id}/end`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["conversations"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
      router.replace(`/conversation/${conv.id}/summary`);
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const saveSettings = (s: ConversationSettings) => {
    setSettings(s);
    void patch(`/conversations/${conv.id}`, { settings: s }).catch((e) => toast.error(errorMessage(e)));
  };

  const busy = !!socket.streaming || socket.pending.length > 0 || uploading;

  const sendText = () => {
    const t = text.trim();
    if (!t || busy) return;
    socket.stopAudio();
    socket.sendText(t);
    setText("");
  };

  const onRecorded = async (r: Recording) => {
    socket.stopAudio();
    setUploading(true);
    const form = new FormData();
    form.append("audio", r.blob, `turn.${r.mime.includes("mp4") ? "m4a" : "webm"}`);
    form.append("duration_ms", String(r.durationMs));
    try {
      const { recording_id } = await api<{ recording_id: string }>(`/conversations/${conv.id}/audio`, { form });
      socket.sendAudio(recording_id, URL.createObjectURL(r.blob));
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setUploading(false);
    }
  };

  const applySentence = (s: string) => {
    setText(s.replace(/\{([^{}|]+)\|[^{}]+\}/g, "$1"));
    setInputMode("text");
    setHintOpen(false);
    setSayOpen(false);
    // after the dialog has returned focus to its trigger, move it to the reply box
    setTimeout(() => input.current?.focus(), 80);
  };

  const lastUserTurnId = [...socket.turns].reverse().find((t) => t.role === "user")?.id;

  return (
    <div className="flex h-dvh flex-col">
      {/* Header */}
      <header className="safe-top border-b bg-background/90 backdrop-blur">
        <div className="mx-auto flex max-w-3xl items-center gap-2 px-3 py-2.5 sm:px-5">
          <Button variant="ghost" size="icon" asChild aria-label="Back to Talk">
            <Link href="/talk">
              <ArrowLeft />
            </Link>
          </Button>
          <div className="min-w-0 flex-1">
            <p className="truncate font-bold leading-tight">
              {conv.scenario?.emoji ?? (conv.mode === "tutor" ? "🎓" : "💬")} {conv.title}
            </p>
            <p className="text-xs text-muted-foreground">
              <Flag lang={lang} /> {LANGS[lang].name} · {conv.level}
              {socket.status === "reconnecting" && (
                <span className="ml-2 inline-flex items-center gap-1 text-warning">
                  <WifiOff className="size-3" /> reconnecting
                </span>
              )}
            </p>
          </div>
          <Button variant="ghost" size="icon" onClick={() => setSettingsOpen(true)} aria-label="Conversation settings">
            <Settings2 />
          </Button>
          {!ended && (
            <Button variant="outline" size="sm" onClick={() => setEndOpen(true)}>
              End
            </Button>
          )}
        </div>
        {conv.scenario && (
          <div className="mx-auto max-w-3xl px-3 pb-2.5 sm:px-5">
            <div
              className={cn(
                "flex items-center gap-2 rounded-xl px-3 py-2 text-sm transition",
                goal ? "bg-success-soft text-success" : "bg-primary-soft text-primary-strong",
              )}
            >
              {goal ? <CircleCheck className="size-4 shrink-0" /> : <Target className="size-4 shrink-0" />}
              <span className="line-clamp-2 font-medium">{conv.scenario.goal}</span>
            </div>
          </div>
        )}
      </header>

      {/* Messages */}
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-3xl flex-col gap-4 px-3 py-5 sm:px-5" aria-live="polite">
          {socket.turns.map((t) =>
            t.role === "assistant" ? (
              <AiBubble key={t.id} turn={t} lang={lang} settings={settings} mode={conv.mode} onWordTap={words.open} />
            ) : (
              <div key={t.id} className="flex flex-col">
                <UserBubble turn={t} lang={lang} />
                {settings.feedback && conv.mode !== "tutor" && (
                  <FeedbackCard turn={t} lang={lang} error={socket.feedbackErrors[t.id]} defaultOpen={t.id === lastUserTurnId} />
                )}
              </div>
            ),
          )}
          {socket.pending.map((p) => (
            <UserBubble
              key={p.client_id}
              lang={lang}
              turn={p.text ? ({ text: p.text } as never) : undefined}
              pendingLabel={p.status === "transcribing" ? (p.note ?? "Transcribing…") : undefined}
              localAudio={p.localAudio}
            />
          ))}
          {socket.streaming && (
            <StreamingBubble text={socket.streaming.text} lang={lang} settings={settings} status={socket.streaming.status} />
          )}
          {socket.failure ? (
            <div className="mx-auto flex max-w-md flex-col items-center gap-3 py-12 text-center" role="alert">
              <span className="flex size-12 items-center justify-center rounded-2xl bg-danger-soft text-danger">
                <WifiOff className="size-6" />
              </span>
              <p className="font-bold">
                {socket.failure.kind === "auth" ? "Signed out" : socket.failure.kind === "origin" ? "Connection refused" : "Can't connect"}
              </p>
              <p className="text-sm text-muted-foreground">{socket.failure.message}</p>
              {socket.failure.kind === "auth" ? (
                <Button asChild>
                  <Link href={`/login?next=/conversation/${conv.id}`}>Sign in</Link>
                </Button>
              ) : (
                <Button variant="outline" onClick={() => window.location.reload()}>
                  Try again
                </Button>
              )}
            </div>
          ) : socket.startError && socket.turns.length === 0 ? (
            <div className="mx-auto flex max-w-md flex-col items-center gap-3 py-12 text-center" role="alert">
              <p className="font-bold">The AI couldn&apos;t start the conversation</p>
              <p className="text-sm text-muted-foreground">{socket.startError.message}</p>
              {socket.startError.detail && (
                <p className="w-full break-words rounded-xl bg-muted px-3 py-2 text-left font-mono text-xs text-muted-foreground">
                  {socket.startError.detail}
                </p>
              )}
              <Button variant="outline" onClick={socket.retryStart}>
                Try again
              </Button>
            </div>
          ) : (
            socket.turns.length === 0 &&
            !socket.streaming && (
              <div className="flex flex-col items-center gap-2 py-16 text-muted-foreground">
                <LoaderCircle className="size-6 animate-spin" />
                <p className="text-sm">Starting the conversation…</p>
              </div>
            )
          )}
          <div ref={bottom} />
        </div>
      </main>

      {/* Composer */}
      {ended ? (
        <footer className="safe-bottom border-t bg-card">
          <div className="mx-auto flex max-w-3xl items-center justify-between gap-3 px-4 py-4">
            <p className="text-sm text-muted-foreground">This conversation has ended.</p>
            <Button asChild>
              <Link href={`/conversation/${conv.id}/summary`}>View summary</Link>
            </Button>
          </div>
        </footer>
      ) : (
        <footer className="safe-bottom border-t bg-background/95 backdrop-blur">
          <div className="mx-auto max-w-3xl px-3 pb-3 pt-2.5 sm:px-5">
            <div className="mb-2 flex items-center gap-1.5 overflow-x-auto scrollbar-none">
              {conv.mode !== "tutor" && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    setHintOpen(true);
                    hint.mutate();
                  }}
                >
                  <Lightbulb /> Hint
                </Button>
              )}
              <Button variant="secondary" size="sm" onClick={() => setSayOpen(true)}>
                <Languages /> How do I say…
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="ml-auto"
                onClick={() => setInputMode(inputMode === "voice" ? "text" : "voice")}
                aria-label={inputMode === "voice" ? "Switch to typing" : "Switch to speaking"}
              >
                {inputMode === "voice" ? <Keyboard /> : <Mic />}
                <span className="hidden sm:inline">{inputMode === "voice" ? "Type instead" : "Speak instead"}</span>
              </Button>
            </div>
            {inputMode === "voice" ? (
              <div className="flex flex-col items-center pt-1">
                {uploading ? (
                  <p className="flex h-[112px] items-center gap-2 text-sm text-muted-foreground">
                    <LoaderCircle className="size-5 animate-spin" /> Sending your recording…
                  </p>
                ) : (
                  <RecordButton onRecorded={onRecorded} mode={recordMode} spaceToTalk disabled={busy}
                    hint={busy ? "Wait for the reply…" : undefined} />
                )}
                <button
                  type="button"
                  onClick={() => setRecordMode(recordMode === "hold" ? "toggle" : "hold")}
                  className="text-[11px] font-medium text-muted-foreground underline-offset-2 hover:underline"
                >
                  {recordMode === "hold" ? "Prefer tap to start / stop?" : "Prefer hold to talk?"}
                </button>
              </div>
            ) : (
              <div className="flex items-end gap-2">
                <div className="flex-1">
                  <TargetInput
                    ref={input}
                    lang={conv.mode === "tutor" ? "en" : lang}
                    showAccents={conv.mode !== "tutor"}
                    value={text}
                    onChange={setText}
                    onSubmit={sendText}
                    multiline
                    placeholder={conv.mode === "tutor" ? "Ask a question…" : `Reply in ${LANGS[lang].name}…`}
                    className="text-[16px]"
                    autoFocus
                  />
                </div>
                <Button size="icon-lg" onClick={sendText} disabled={!text.trim() || busy} aria-label="Send" className="mb-0.5 rounded-2xl">
                  <Send />
                </Button>
              </div>
            )}
          </div>
        </footer>
      )}

      <WordPopover target={words.target} lang={lang} onClose={words.close} />

      <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
        <DialogContent side="bottom" title="Conversation settings">
          <ConversationSettingsForm value={settings} onChange={saveSettings} lang={lang} mode={conv.mode} />
        </DialogContent>
      </Dialog>

      <Dialog open={hintOpen} onOpenChange={setHintOpen}>
        <DialogContent side="bottom" title="You could say…" description="Tap one to use it, or just get inspired.">
          {hint.isPending || !hint.data ? (
            <div className="space-y-2">
              <Skeleton className="h-16" />
              <Skeleton className="h-16" />
            </div>
          ) : (
            <ul className="space-y-2">
              {hint.data.suggestions.map((s, i) => (
                <li key={i} className="flex items-start gap-3 rounded-2xl border bg-card p-3.5">
                  <AudioButton text={s.target} lang={lang} size="sm" />
                  <div className="min-w-0 flex-1">
                    <p className="text-[16px] font-medium">
                      <RubyText text={s.target} lang={lang} showRomaji={false} />
                    </p>
                    <p className="text-sm text-muted-foreground">{s.english}</p>
                  </div>
                  <Button size="sm" variant="soft" onClick={() => applySentence(s.target)}>
                    Use
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={sayOpen} onOpenChange={setSayOpen}>
        <DialogContent side="bottom" title="How do I say…" description={`Type it in English and get the ${LANGS[lang].name} to use.`}>
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (english.trim()) say.mutate(english.trim());
            }}
          >
            <Input value={english} onChange={(e) => setEnglish(e.target.value)} placeholder="e.g. Could I have the bill?" autoFocus />
            <Button type="submit" loading={say.isPending} disabled={!english.trim()}>
              Go
            </Button>
          </form>
          {say.data && (
            <div className="mt-4 rounded-2xl border bg-card p-4">
              <div className="flex items-start gap-3">
                <AudioButton text={say.data.target} lang={lang} />
                <div className="min-w-0 flex-1">
                  <p className="text-lg font-semibold">
                    <RubyText text={say.data.target} lang={lang} />
                  </p>
                  {say.data.notes && <p className="mt-1 text-sm text-muted-foreground">{say.data.notes}</p>}
                  {say.data.alternatives.length > 0 && (
                    <p className="mt-1 text-sm text-muted-foreground">Also: {say.data.alternatives.join(" · ")}</p>
                  )}
                </div>
              </div>
              <Button className="mt-3 w-full" variant="soft" onClick={() => applySentence(say.data!.target)}>
                Use this
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={endOpen} onOpenChange={setEndOpen}>
        <DialogContent side="bottom" title="End this conversation?" description="You'll get a summary with your recurring mistakes and new words.">
          <div className="flex flex-col gap-2.5 sm:flex-row">
            <Button className="sm:flex-1" size="lg" loading={end.isPending} onClick={() => end.mutate()}>
              End & see summary
            </Button>
            <Button className="sm:flex-1" size="lg" variant="outline" onClick={() => setEndOpen(false)}>
              Keep talking
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function ConversationPage() {
  const { id } = useParams<{ id: string }>();
  const { data, error } = useQuery({
    queryKey: ["conversation", id],
    queryFn: () => get<Conversation>(`/conversations/${id}`),
    staleTime: Infinity,
    gcTime: 0,
  });
  if (error) {
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-3 p-6 text-center">
        <p className="font-bold">Conversation not found</p>
        <Button asChild>
          <Link href="/talk">Back to Talk</Link>
        </Button>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="flex min-h-dvh items-center justify-center">
        <LoaderCircle className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }
  return <ConversationScreen conv={data} />;
}
