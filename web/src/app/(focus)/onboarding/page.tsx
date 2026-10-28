"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Check, Compass, Headphones, Mic, ShieldCheck, Sprout } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { AudioButton } from "@/components/audio-button";
import { Flag } from "@/components/flag";
import { Logo } from "@/components/brand";
import { RecordButton } from "@/components/record-button";
import { Button } from "@/components/ui/button";
import { Card, Progress, Segmented } from "@/components/ui/primitives";
import { useMe } from "@/hooks/use-me";
import type { Recording } from "@/hooks/use-recorder";
import { errorMessage, get, patch, post } from "@/lib/api";
import { LANG_CODES, LANGS } from "@/lib/languages";
import type { Lang } from "@/lib/types";
import { cn } from "@/lib/utils";

type Meta = { stt_provider: string; tts_provider: string; max_recording_seconds: number };

const GOALS = {
  xp: [
    { value: 10, label: "Casual", note: "~5 min a day" },
    { value: 30, label: "Regular", note: "~10 min a day" },
    { value: 50, label: "Serious", note: "~20 min a day" },
    { value: 80, label: "Intense", note: "~30 min a day" },
  ],
  minutes: [
    { value: 5, label: "Casual", note: "5 minutes" },
    { value: 10, label: "Regular", note: "10 minutes" },
    { value: 20, label: "Serious", note: "20 minutes" },
    { value: 30, label: "Intense", note: "30 minutes" },
  ],
};

function Onboarding() {
  const router = useRouter();
  const adding = useSearchParams().get("add") === "1";
  const qc = useQueryClient();
  const { data: me } = useMe();
  const { data: meta } = useQuery({ queryKey: ["meta"], queryFn: () => get<Meta>("/meta") });
  const enrolled = new Set(me?.enrolments.map((e) => e.language_code));
  const available = LANG_CODES.filter((l) => !enrolled.has(l));

  const steps = adding ? ["language", "start"] : ["language", "goal", "start", "audio"];
  const [step, setStep] = React.useState(0);
  const [langs, setLangs] = React.useState<Lang[]>([]);
  const [goalType, setGoalType] = React.useState<"xp" | "minutes">("xp");
  const [goal, setGoal] = React.useState(30);
  const [start, setStart] = React.useState<Record<string, "scratch" | "placement">>({});
  const [busy, setBusy] = React.useState(false);
  const [playback, setPlayback] = React.useState<string | null>(null);

  const current = steps[step];
  const canNext = current !== "language" || langs.length > 0;

  const finish = async () => {
    setBusy(true);
    try {
      for (const l of langs) await post("/enrolments", { language_code: l });
      if (!adding) {
        await patch("/auth/me", {
          settings: {
            daily_goal_type: goalType, daily_goal_value: goal, onboarded: true, voice_notice_seen: true,
            active_language: langs[0], timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
          },
        });
      } else {
        await patch("/auth/me", { settings: { active_language: langs[0] } });
      }
      await qc.invalidateQueries({ queryKey: ["me"] });
      const placement = langs.find((l) => start[l] === "placement");
      router.replace(placement ? `/placement/${placement}` : "/learn");
    } catch (e) {
      toast.error(errorMessage(e));
      setBusy(false);
    }
  };

  const next = () => (step < steps.length - 1 ? setStep(step + 1) : void finish());

  const onRecorded = (r: Recording) => {
    if (playback) URL.revokeObjectURL(playback);
    const url = URL.createObjectURL(r.blob);
    setPlayback(url);
    void new Audio(url).play();
  };

  return (
    <div className="mx-auto flex min-h-dvh max-w-2xl flex-col px-4 pb-8 pt-5 sm:px-6">
      <div className="flex items-center gap-4">
        {step > 0 ? (
          <Button variant="ghost" size="icon" onClick={() => setStep(step - 1)} aria-label="Back">
            <ArrowLeft />
          </Button>
        ) : adding ? (
          <Button variant="ghost" size="icon" onClick={() => router.back()} aria-label="Back">
            <ArrowLeft />
          </Button>
        ) : (
          <Logo />
        )}
        <Progress value={(step + 1) / steps.length} className="flex-1" />
      </div>

      <div className="flex-1 animate-rise py-8" key={current}>
        {current === "language" && (
          <section>
            <h1 className="text-balance text-2xl font-extrabold tracking-tight sm:text-3xl">
              {adding ? "Add a language" : `Welcome${me ? `, ${me.display_name}` : ""}! What do you want to learn?`}
            </h1>
            <p className="mt-2 text-muted-foreground">Pick one or more — you can switch any time from the top bar.</p>
            <div className="mt-7 grid gap-3 sm:grid-cols-3">
              {(adding ? available : LANG_CODES).map((l) => {
                const on = langs.includes(l);
                return (
                  <button
                    key={l}
                    type="button"
                    data-lang={l}
                    aria-pressed={on}
                    onClick={() => setLangs(on ? langs.filter((x) => x !== l) : [...langs, l])}
                    className={cn(
                      "group relative flex items-center gap-4 rounded-2xl border-2 bg-card p-4 text-left transition sm:flex-col sm:items-start sm:p-5",
                      on ? "border-primary bg-primary-soft" : "hover:border-primary/50",
                    )}
                  >
                    <span className="text-4xl sm:text-5xl"><Flag lang={l} /></span>
                    <span>
                      <span className="block text-lg font-bold">{LANGS[l].name}</span>
                      <span className="block text-sm text-muted-foreground" lang={l}>
                        {LANGS[l].hello} · {LANGS[l].native}
                      </span>
                    </span>
                    <span
                      className={cn(
                        "absolute right-4 top-4 flex size-6 items-center justify-center rounded-full border-2 transition",
                        on ? "border-primary bg-primary text-primary-foreground" : "border-border",
                      )}
                    >
                      {on && <Check className="size-4" />}
                    </span>
                  </button>
                );
              })}
            </div>
          </section>
        )}

        {current === "goal" && (
          <section>
            <h1 className="text-2xl font-extrabold tracking-tight sm:text-3xl">Set a daily goal</h1>
            <p className="mt-2 text-muted-foreground">Small and steady beats big and rare. You can change this later.</p>
            <Segmented
              className="mt-6"
              value={goalType}
              onChange={(v) => {
                setGoalType(v);
                setGoal(v === "xp" ? 30 : 10);
              }}
              options={[
                { value: "xp", label: "XP" },
                { value: "minutes", label: "Minutes" },
              ]}
              ariaLabel="Goal type"
            />
            <div className="mt-4 grid gap-2.5">
              {GOALS[goalType].map((g) => (
                <button
                  key={g.value}
                  type="button"
                  aria-pressed={goal === g.value}
                  onClick={() => setGoal(g.value)}
                  className={cn(
                    "flex items-center justify-between rounded-2xl border-2 bg-card px-5 py-4 text-left transition",
                    goal === g.value ? "border-primary bg-primary-soft" : "hover:border-primary/50",
                  )}
                >
                  <span className="font-semibold">{g.label}</span>
                  <span className="text-sm text-muted-foreground">
                    {g.value} {goalType === "xp" ? "XP" : "min"} · {g.note}
                  </span>
                </button>
              ))}
            </div>
          </section>
        )}

        {current === "start" && (
          <section>
            <h1 className="text-2xl font-extrabold tracking-tight sm:text-3xl">Where should you start?</h1>
            <p className="mt-2 text-muted-foreground">Already know some? A quick adaptive test (about 15 questions) finds your level.</p>
            <div className="mt-6 space-y-6">
              {langs.map((l) => (
                <div key={l} data-lang={l}>
                  <p className="mb-2.5 flex items-center gap-2 font-semibold">
                    <span className="text-xl"><Flag lang={l} /></span> {LANGS[l].name}
                  </p>
                  <div className="grid gap-2.5 sm:grid-cols-2">
                    {(["scratch", "placement"] as const).map((opt) => {
                      const on = (start[l] ?? "scratch") === opt;
                      const Icon = opt === "scratch" ? Sprout : Compass;
                      return (
                        <button
                          key={opt}
                          type="button"
                          aria-pressed={on}
                          onClick={() => setStart({ ...start, [l]: opt })}
                          className={cn(
                            "flex gap-3 rounded-2xl border-2 bg-card p-4 text-left transition",
                            on ? "border-primary bg-primary-soft" : "hover:border-primary/50",
                          )}
                        >
                          <Icon className="mt-0.5 size-6 shrink-0 text-primary" />
                          <span>
                            <span className="block font-semibold">
                              {opt === "scratch" ? (l === "ja" ? "Start with hiragana" : "Start from scratch") : "Find my level"}
                            </span>
                            <span className="block text-sm text-muted-foreground">
                              {opt === "scratch"
                                ? l === "ja"
                                  ? "Learn the writing systems first, then A1."
                                  : "Begin at A1, lesson one."
                                : "Take the placement test — skip what you know."}
                            </span>
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {current === "audio" && (
          <section data-lang={langs[0]}>
            <h1 className="text-2xl font-extrabold tracking-tight sm:text-3xl">Check your sound and mic</h1>
            <p className="mt-2 text-muted-foreground">You&apos;ll hear every word and speak your answers out loud.</p>
            <div className="mt-6 grid gap-3 sm:grid-cols-2">
              <Card className="flex flex-col items-center gap-3 p-6 text-center">
                <Headphones className="size-6 text-muted-foreground" />
                <p className="font-semibold">Can you hear this?</p>
                <AudioButton text={langs[0] ? LANGS[langs[0]].hello : "Bonjour"} lang={langs[0] ?? "fr"} size="lg" variant="solid" />
                <p className="text-sm text-muted-foreground" lang={langs[0]}>
                  {langs[0] ? LANGS[langs[0]].hello : "Bonjour"}
                </p>
              </Card>
              <Card className="flex flex-col items-center gap-2 p-6 text-center">
                <Mic className="size-6 text-muted-foreground" />
                <p className="font-semibold">Say something</p>
                <RecordButton onRecorded={onRecorded} mode="toggle" size="md" hint="Tap, speak, tap again — it plays back" />
                {playback && (
                  <button type="button" onClick={() => void new Audio(playback).play()} className="text-sm font-medium text-primary-strong hover:underline">
                    Play it again
                  </button>
                )}
              </Card>
            </div>
            <div className="mt-4 flex gap-3 rounded-2xl border bg-card p-4 text-sm">
              <ShieldCheck className="mt-0.5 size-5 shrink-0 text-success" />
              <p className="text-muted-foreground">
                <span className="font-semibold text-foreground">Your voice, your server.</span> When you speak, the recording is
                sent to <span className="font-semibold text-foreground">{meta?.stt_provider ?? "the speech provider"}</span> for
                transcription only. The microphone is only on while you hold or tap the mic button, and you can delete your
                recordings at any time in Settings.
              </p>
            </div>
          </section>
        )}
      </div>

      <Button size="xl" className="w-full sm:ml-auto sm:w-64" disabled={!canNext} loading={busy} onClick={next}>
        {step === steps.length - 1 ? "Let's go" : "Continue"} <ArrowRight />
      </Button>
    </div>
  );
}

export default function OnboardingPage() {
  return (
    <React.Suspense>
      <Onboarding />
    </React.Suspense>
  );
}
