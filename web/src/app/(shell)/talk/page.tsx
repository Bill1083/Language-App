"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, BookOpen, GraduationCap, History, Lock, MessagesSquare, Target } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { ConversationSettingsForm } from "@/components/talk/settings-form";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/overlay";
import { Badge, Card, Input, Label, Segmented, Skeleton } from "@/components/ui/primitives";
import { useConversations, useCourse, useScenarios } from "@/hooks/queries";
import { useActiveLang, useLanguage } from "@/hooks/use-language";
import { useMe } from "@/hooks/use-me";
import { errorMessage, get, post } from "@/lib/api";
import { CEFR_LEVELS, LANGS } from "@/lib/languages";
import type { Conversation, ConversationSettings, Scenario } from "@/lib/types";
import { cn, timeAgo } from "@/lib/utils";

type Pending =
  | { mode: "scenario"; scenario: Scenario }
  | { mode: "free" }
  | { mode: "tutor" }
  | { mode: "unit"; unitId: number; title: string };

const TOPICS = ["Your weekend", "Food you love", "Travel stories", "Work or studies", "Films & series", "Hobbies"];

function StartSheet({ pending, onClose }: { pending: Pending | null; onClose: () => void }) {
  const lang = useActiveLang();
  const { enrolment } = useLanguage();
  const { data: me } = useMe();
  const router = useRouter();
  const { data: meta } = useQuery({ queryKey: ["meta"], queryFn: () => get<{ stt_provider: string }>("/meta") });
  const [level, setLevel] = React.useState<string>(enrolment?.current_level ?? "A1");
  const [topic, setTopic] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [settings, setSettings] = React.useState<ConversationSettings>({
    input: "voice", ai_voice: true, speed: me?.settings.speech_speed ?? 1, voice_gender: me?.settings.voice_gender ?? "female",
    politeness: "polite", furigana: me?.settings.furigana ?? "always", romaji: me?.settings.romaji === "on" ? "on" : "off",
    strictness: me?.settings.strictness ?? "normal", feedback: true, topic: "",
  });
  React.useEffect(() => setLevel(enrolment?.current_level ?? "A1"), [enrolment, pending]);

  if (!pending) return null;
  const start = async () => {
    setBusy(true);
    try {
      const conv = await post<Conversation>("/conversations", {
        lang, mode: pending.mode, level,
        scenario_id: pending.mode === "scenario" ? pending.scenario.id : undefined,
        unit_id: pending.mode === "unit" ? pending.unitId : undefined,
        settings: { ...settings, topic },
      });
      router.push(`/conversation/${conv.id}`);
    } catch (e) {
      toast.error(errorMessage(e));
      setBusy(false);
    }
  };

  const title =
    pending.mode === "scenario" ? `${pending.scenario.emoji} ${pending.scenario.title}`
      : pending.mode === "free" ? "💬 Free conversation"
        : pending.mode === "tutor" ? "🎓 Ask a tutor" : `📘 ${pending.title}`;
  const description =
    pending.mode === "scenario" ? pending.scenario.description
      : pending.mode === "free" ? `Chat about anything with a friendly local from ${LANGS[lang].name === "Japanese" ? "Tokyo" : LANGS[lang].name === "Italian" ? "Rome" : "Paris"}.`
        : pending.mode === "tutor" ? "Ask questions in English about grammar, words and usage — get clear explanations with examples."
          : "A role-play built from this unit's vocabulary and grammar.";

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent side="bottom" title={title} description={description} className="sm:max-w-xl">
        {pending.mode === "scenario" && (
          <div className="mb-5 flex gap-3 rounded-2xl bg-primary-soft p-4">
            <Target className="mt-0.5 size-5 shrink-0 text-primary" />
            <div className="text-sm">
              <p className="font-semibold text-primary-strong">Your goal</p>
              <p className="mt-0.5">{pending.scenario.goal}</p>
              <p className="mt-1.5 text-xs text-muted-foreground">
                You&apos;re {pending.scenario.user_role}; the AI plays {pending.scenario.ai_role}.
              </p>
            </div>
          </div>
        )}
        {pending.mode === "free" && (
          <div className="mb-5 space-y-2">
            <Label htmlFor="topic">Topic (optional)</Label>
            <Input id="topic" placeholder="Anything you like" value={topic} onChange={(e) => setTopic(e.target.value)} />
            <div className="flex flex-wrap gap-1.5">
              {TOPICS.map((t) => (
                <button key={t} type="button" onClick={() => setTopic(t)}
                  className={cn("rounded-full border px-2.5 py-1 text-xs transition hover:bg-muted", topic === t && "border-primary bg-primary-soft")}>
                  {t}
                </button>
              ))}
            </div>
          </div>
        )}
        <ConversationSettingsForm value={settings} onChange={setSettings} lang={lang} showLevel level={level} onLevel={setLevel} mode={pending.mode} />
        {settings.input === "voice" && (
          <p className="mt-5 rounded-xl bg-muted px-3 py-2.5 text-xs text-muted-foreground">
            🔒 Voice is sent to {meta?.stt_provider ?? "the speech provider"} for transcription only. The mic is on only while you
            record.
          </p>
        )}
        <Button size="xl" className="mt-5 w-full" loading={busy} onClick={start}>
          Start conversation <ArrowRight />
        </Button>
      </DialogContent>
    </Dialog>
  );
}

function TalkHub() {
  const lang = useActiveLang();
  const { enrolment } = useLanguage();
  const params = useSearchParams();
  const router = useRouter();
  const { data: scenarios, isLoading } = useScenarios(lang);
  const { data: history } = useConversations(lang);
  const { data: course } = useCourse(lang);
  const [pending, setPending] = React.useState<Pending | null>(null);
  const [filter, setFilter] = React.useState<string>("all");
  const levelIdx = CEFR_LEVELS.indexOf((enrolment?.current_level ?? "A1") as (typeof CEFR_LEVELS)[number]);

  // deep links: /talk?scenario=3, /talk?unit=12
  React.useEffect(() => {
    const sid = params.get("scenario");
    const uid = params.get("unit");
    if (sid && scenarios) {
      const s = scenarios.find((x) => String(x.id) === sid);
      if (s) setPending({ mode: "scenario", scenario: s });
      router.replace("/talk");
    } else if (uid && course) {
      const unit = course.levels.flatMap((l) => l.units).find((u) => String(u.id) === uid);
      if (unit) setPending({ mode: "unit", unitId: unit.id, title: unit.title });
      router.replace("/talk");
    }
  }, [params, scenarios, course, router]);

  const currentUnit = React.useMemo(() => {
    if (!course?.next_lesson) return null;
    return course.levels.flatMap((l) => l.units).find((u) => u.lessons.some((le) => le.id === course.next_lesson!.id)) ?? null;
  }, [course]);

  const shown = (scenarios ?? []).filter((s) => filter === "all" || s.min_level === filter);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight sm:text-3xl">Talk</h1>
        <p className="mt-1 text-muted-foreground">Practise real conversations. Every reply you give gets feedback.</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <button type="button" onClick={() => setPending({ mode: "free" })}
          className="group flex flex-col items-start rounded-2xl border-2 bg-card p-5 text-left transition hover:border-primary/50">
          <span className="flex size-11 items-center justify-center rounded-xl bg-primary-soft text-primary"><MessagesSquare className="size-6" /></span>
          <span className="mt-3 font-bold">Free conversation</span>
          <span className="text-sm text-muted-foreground">Chat about anything, at your level.</span>
        </button>
        <button type="button" disabled={!currentUnit || currentUnit.theme === "writing"}
          onClick={() => currentUnit && setPending({ mode: "unit", unitId: currentUnit.id, title: currentUnit.title })}
          className="group flex flex-col items-start rounded-2xl border-2 bg-card p-5 text-left transition hover:border-primary/50 disabled:opacity-50">
          <span className="flex size-11 items-center justify-center rounded-xl bg-primary-soft text-primary"><BookOpen className="size-6" /></span>
          <span className="mt-3 font-bold">Unit conversation</span>
          <span className="line-clamp-1 text-sm text-muted-foreground">
            {currentUnit && currentUnit.theme !== "writing" ? `Use what you learned in “${currentUnit.title}”` : "Available once you start a unit"}
          </span>
        </button>
        <button type="button" onClick={() => setPending({ mode: "tutor" })}
          className="group flex flex-col items-start rounded-2xl border-2 bg-card p-5 text-left transition hover:border-primary/50">
          <span className="flex size-11 items-center justify-center rounded-xl bg-primary-soft text-primary"><GraduationCap className="size-6" /></span>
          <span className="mt-3 font-bold">Ask a tutor</span>
          <span className="text-sm text-muted-foreground">Questions in English about grammar & usage.</span>
        </button>
      </div>

      <section>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-bold">Scenarios</h2>
          <Segmented size="sm" value={filter} onChange={setFilter} ariaLabel="Filter by level"
            options={[{ value: "all", label: "All" }, ...CEFR_LEVELS.map((l) => ({ value: l, label: l }))]} />
        </div>
        {isLoading ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-40" />)}
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {shown.map((s) => {
              const above = CEFR_LEVELS.indexOf(s.min_level) > levelIdx;
              const done = history?.items.some((c) => c.scenario?.id === s.id && c.goal_achieved);
              return (
                <button key={s.id} type="button" onClick={() => setPending({ mode: "scenario", scenario: s })}
                  className="flex flex-col rounded-2xl border bg-card p-4 text-left transition hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-md">
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-3xl">{s.emoji}</span>
                    <div className="flex gap-1.5">
                      {done && <Badge tone="success">✓ done</Badge>}
                      <Badge tone={above ? "warning" : "neutral"}>
                        {above && <Lock className="size-3" />} {s.min_level}
                      </Badge>
                    </div>
                  </div>
                  <span className="mt-3 font-bold">{s.title}</span>
                  <span className="mt-1 line-clamp-2 text-sm text-muted-foreground">{s.goal}</span>
                </button>
              );
            })}
          </div>
        )}
      </section>

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-bold">Recent conversations</h2>
          <Link href="/talk/history" className="flex items-center gap-1 text-sm font-semibold text-primary-strong hover:underline">
            <History className="size-4" /> All history
          </Link>
        </div>
        {history?.items.length ? (
          <div className="divide-y rounded-2xl border bg-card">
            {history.items.slice(0, 4).map((c) => (
              <Link key={c.id} href={c.ended_at ? `/conversation/${c.id}/summary` : `/conversation/${c.id}`}
                className="flex items-center gap-3 px-4 py-3 transition first:rounded-t-2xl last:rounded-b-2xl hover:bg-muted/50">
                <span className="text-2xl">{c.scenario?.emoji ?? (c.mode === "tutor" ? "🎓" : "💬")}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-semibold">{c.title}</span>
                  <span className="block text-xs text-muted-foreground">
                    {timeAgo(c.started_at)} · {c.turns} turns{c.ended_at ? "" : " · in progress"}
                  </span>
                </span>
                {c.avg_score != null && <Badge tone={c.avg_score >= 85 ? "success" : c.avg_score >= 60 ? "warning" : "danger"}>{c.avg_score}</Badge>}
              </Link>
            ))}
          </div>
        ) : (
          <p className="rounded-2xl border border-dashed p-6 text-center text-sm text-muted-foreground">
            Your conversations will appear here — transcript, audio and feedback included.
          </p>
        )}
      </section>

      <StartSheet pending={pending} onClose={() => setPending(null)} />
    </div>
  );
}

export default function TalkPage() {
  return (
    <React.Suspense>
      <TalkHub />
    </React.Suspense>
  );
}
