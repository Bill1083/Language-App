"use client";

import { ArrowRight, BookOpen, Flame, Layers, MessageCircle, Snowflake, Sparkles, Target, Trophy } from "lucide-react";
import Link from "next/link";

import { ProgressRing } from "@/components/progress-ring";
import { Flag } from "@/components/flag";
import { Button } from "@/components/ui/button";
import { Badge, Card, Progress, Skeleton } from "@/components/ui/primitives";
import { useDashboard } from "@/hooks/queries";
import { useLanguage } from "@/hooks/use-language";
import { useMe } from "@/hooks/use-me";
import { CEFR_LABEL, LANGS } from "@/lib/languages";
import { cn, greeting, timeAgo } from "@/lib/utils";

const ACTIVITY_ICON: Record<string, typeof BookOpen> = {
  lesson: BookOpen,
  test: Trophy,
  review: Layers,
  conversation: MessageCircle,
  placement: Target,
};

export default function HomePage() {
  const { data: me } = useMe();
  const { lang, setLang } = useLanguage();
  const { data, isLoading } = useDashboard(lang);

  if (isLoading || !data || !lang) {
    return (
      <div className="grid gap-4 md:grid-cols-3">
        <Skeleton className="h-10 w-64 md:col-span-3" />
        <Skeleton className="h-52 md:col-span-2" />
        <Skeleton className="h-52" />
        <Skeleton className="h-36" />
        <Skeleton className="h-36" />
        <Skeleton className="h-36" />
      </div>
    );
  }

  const { daily } = data;
  const next = data.next_lesson;
  const level = data.level;
  const meta = LANGS[lang];

  return (
    <div className="space-y-6">
      <div className="animate-rise">
        <h1 className="text-2xl font-extrabold tracking-tight sm:text-3xl">
          {greeting()}, {me?.display_name}
        </h1>
        <p className="mt-1 text-muted-foreground">
          {daily.goal_met
            ? "Daily goal done — anything more is a bonus."
            : daily.active_today
              ? "Nice start today. Keep it rolling."
              : `A few minutes of ${meta.name} keeps the streak alive.`}
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        {/* Continue */}
        <Card className="relative overflow-hidden border-0 bg-primary p-6 text-primary-foreground md:col-span-2">
          <div aria-hidden className="pointer-events-none absolute -right-10 -top-16 size-56 rounded-full bg-white/10" />
          <div aria-hidden className="pointer-events-none absolute -bottom-20 right-24 size-40 rounded-full bg-white/10" />
          <div className="relative flex h-full flex-col">
            <div className="flex items-center gap-2 text-sm font-semibold text-white/85">
              <span className="text-lg"><Flag lang={lang} /></span> {meta.name} ·{" "}
              {level ? `${level.cefr} ${CEFR_LABEL[level.cefr]}` : ""}
            </div>
            {next ? (
              <>
                <p className="mt-5 text-sm font-medium text-white/75">{next.kind === "kana" ? "Writing systems" : next.unit}</p>
                <p className="mt-0.5 text-2xl font-extrabold leading-tight sm:text-[28px]">{next.title}</p>
              </>
            ) : (
              <p className="mt-5 text-2xl font-extrabold">You&apos;re all caught up 🎉</p>
            )}
            {level && level.total > 0 && (
              <div className="mt-5 max-w-sm">
                <div className="mb-1.5 flex justify-between text-xs font-semibold text-white/80">
                  <span>{level.cefr} progress</span>
                  <span>
                    {level.completed}/{level.total} lessons
                  </span>
                </div>
                <Progress value={level.completed / level.total} className="bg-white/20" barClassName="bg-white" />
              </div>
            )}
            <div className="mt-6 flex flex-wrap gap-2.5">
              {next ? (
                <Button asChild size="lg" className="bg-white text-primary-strong shadow-[0_3px_0_0_rgba(0,0,0,0.15)] hover:bg-white">
                  <Link href={`/lesson/${next.id}`}>
                    Continue <ArrowRight />
                  </Link>
                </Button>
              ) : (
                <Button asChild size="lg" className="bg-white text-primary-strong hover:bg-white">
                  <Link href="/learn">Open the course</Link>
                </Button>
              )}
              <Button asChild size="lg" variant="ghost" className="text-white hover:bg-white/15">
                <Link href="/learn">Course map</Link>
              </Button>
            </div>
          </div>
        </Card>

        {/* Daily goal + streak */}
        <Card className="flex flex-col items-center justify-center gap-4 p-6 text-center">
          <ProgressRing value={daily.goal_progress} size={120} stroke={11} done={daily.goal_met}>
            <span className="flex flex-col items-center">
              <span className="text-3xl font-black tabular-nums">
                {daily.goal_type === "xp" ? daily.xp_today : daily.minutes_today}
              </span>
              <span className="text-xs font-semibold text-muted-foreground">
                of {daily.goal_value} {daily.goal_type === "xp" ? "XP" : "min"}
              </span>
            </span>
          </ProgressRing>
          <div className="flex items-center gap-4 text-sm">
            <span className={cn("flex items-center gap-1.5 font-bold", daily.active_today ? "text-flame" : "text-muted-foreground")}>
              <Flame className={cn("size-5", daily.active_today && "fill-flame/25")} /> {daily.streak} day
              {daily.streak === 1 ? "" : "s"}
            </span>
            <span
              className="flex items-center gap-1 text-muted-foreground"
              title="A streak freeze covers one missed day. You get one each week."
            >
              <Snowflake className={cn("size-4", daily.freezes_available ? "text-sky-400" : "opacity-40")} />
              {daily.freezes_available ? "Freeze ready" : "Freeze used"}
            </span>
          </div>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card className="flex flex-col p-5">
          <div className="flex items-center gap-2 text-sm font-semibold text-muted-foreground">
            <Layers className="size-4" /> Reviews
          </div>
          <p className="mt-3 text-3xl font-black tabular-nums">{data.reviews_due ?? 0}</p>
          <p className="text-sm text-muted-foreground">
            {data.reviews_due ? "cards ready for you" : "Nothing due — come back later"}
          </p>
          <Button asChild variant={data.reviews_due ? "default" : "secondary"} className="mt-4" disabled={!data.reviews_due}>
            <Link href="/review">Review now</Link>
          </Button>
        </Card>

        <Card className="flex flex-col p-5">
          <div className="flex items-center gap-2 text-sm font-semibold text-muted-foreground">
            <MessageCircle className="size-4" /> Suggested conversation
          </div>
          {data.suggested_scenario ? (
            <>
              <p className="mt-3 flex items-center gap-2 text-lg font-bold">
                <span className="text-2xl">{data.suggested_scenario.emoji}</span> {data.suggested_scenario.title}
              </p>
              <p className="line-clamp-2 text-sm text-muted-foreground">{data.suggested_scenario.goal}</p>
              <Button asChild variant="soft" className="mt-auto pt-0">
                <Link href={`/talk?scenario=${data.suggested_scenario.id}`} className="mt-4">
                  Start talking
                </Link>
              </Button>
            </>
          ) : (
            <Button asChild variant="soft" className="mt-4">
              <Link href="/talk">Open Talk</Link>
            </Button>
          )}
        </Card>

        <Card className="p-5">
          <div className="flex items-center gap-2 text-sm font-semibold text-muted-foreground">
            <Sparkles className="size-4" /> Recent activity
          </div>
          {data.recent?.length ? (
            <ul className="mt-3 space-y-2.5">
              {data.recent.slice(0, 5).map((r, i) => {
                const Icon = ACTIVITY_ICON[r.reason] ?? Sparkles;
                return (
                  <li key={i} className="flex items-center gap-3 text-sm">
                    <span className="flex size-8 items-center justify-center rounded-lg bg-muted">
                      <Icon className="size-4 text-muted-foreground" />
                    </span>
                    <span className="flex-1">
                      {r.label}
                      {r.language && <span className="ml-1"><Flag lang={r.language} /></span>}
                      <span className="block text-xs text-muted-foreground">{timeAgo(r.at)}</span>
                    </span>
                    <Badge tone="primary">+{r.xp} XP</Badge>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-muted-foreground">Your lessons, reviews and conversations will show up here.</p>
          )}
        </Card>
      </div>

      {data.enrolments.length > 1 && (
        <div>
          <h2 className="mb-3 text-sm font-semibold text-muted-foreground">Your languages</h2>
          <div className="flex flex-wrap gap-2.5">
            {data.enrolments.map((e) => (
              <button
                key={e.language_code}
                type="button"
                data-lang={e.language_code}
                onClick={() => setLang(e.language_code)}
                className={cn(
                  "flex items-center gap-3 rounded-2xl border-2 bg-card px-4 py-3 text-left transition hover:border-primary/50",
                  e.language_code === lang && "border-primary",
                )}
              >
                <span className="text-2xl"><Flag lang={e.language_code} /></span>
                <span>
                  <span className="block font-semibold">{LANGS[e.language_code].name}</span>
                  <span className="block text-xs text-muted-foreground">
                    {e.current_level} · {e.words} words
                  </span>
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
