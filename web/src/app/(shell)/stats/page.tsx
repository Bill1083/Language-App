"use client";

import { useQuery } from "@tanstack/react-query";
import { BookOpen, Clock, Flame, Languages, Layers, MessageCircle, Trophy, Zap } from "lucide-react";

import { ChartCard, Heatmap, SimpleBars, SimpleLine } from "@/components/charts";
import { Flag } from "@/components/flag";
import { Card, Skeleton } from "@/components/ui/primitives";
import { useAchievements } from "@/hooks/queries";
import { useActiveLang } from "@/hooks/use-language";
import { get } from "@/lib/api";
import { ERROR_TYPE_LABEL, LANGS } from "@/lib/languages";
import type { Daily } from "@/lib/types";
import { cn } from "@/lib/utils";

type Summary = { xp_total: number; minutes_total: number; words: number; kanji: number; lessons: number; conversations: number; reviews: number; daily: Daily };
type Charts = {
  accuracy_weekly: { week: string; accuracy: number; answers: number }[];
  time_by_activity: { activity: string; minutes: number }[];
  conversation_scores: { date: string; score: number }[];
  error_types: { type: string; count: number }[];
};

const shortDate = (d: string) => new Date(d).toLocaleDateString(undefined, { day: "numeric", month: "short" });

function Tile({ icon: Icon, label, value }: { icon: typeof Zap; label: string; value: string | number }) {
  return (
    <Card className="p-4">
      <Icon className="size-5 text-primary" />
      <p className="mt-2 text-2xl font-black tabular-nums">{value}</p>
      <p className="text-xs font-semibold text-muted-foreground">{label}</p>
    </Card>
  );
}

export default function StatsPage() {
  const lang = useActiveLang();
  const { data: summary } = useQuery({ queryKey: ["stats", "summary", lang], queryFn: () => get<Summary>(`/stats/summary?lang=${lang}`) });
  const { data: heat } = useQuery({ queryKey: ["stats", "heatmap"], queryFn: () => get<{ date: string; xp: number; minutes: number }[]>("/stats/heatmap") });
  const { data: charts } = useQuery({ queryKey: ["stats", "charts", lang], queryFn: () => get<Charts>(`/stats/charts?lang=${lang}`) });
  const { data: achievements } = useAchievements();

  if (!summary || !charts) {
    return <div className="grid gap-3 sm:grid-cols-4">{Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-28" />)}</div>;
  }
  const errors = charts.error_types.map((e) => ({ type: ERROR_TYPE_LABEL[e.type] ?? e.type, count: e.count }));
  const earned = achievements?.filter((a) => a.earned_at).length ?? 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight sm:text-3xl">Stats</h1>
        <p className="mt-1 text-muted-foreground"><Flag lang={lang} /> {LANGS[lang].name} — and your overall activity.</p>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Tile icon={Flame} label={`Day streak · best ${summary.daily.longest_streak}`} value={summary.daily.streak} />
        <Tile icon={Zap} label="Total XP" value={summary.xp_total.toLocaleString()} />
        <Tile icon={Languages} label={lang === "ja" ? `Words · ${summary.kanji} kanji` : "Words learned"} value={summary.words} />
        <Tile icon={Clock} label="Time practised" value={`${Math.floor(summary.minutes_total / 60)}h ${summary.minutes_total % 60}m`} />
        <Tile icon={BookOpen} label="Lessons completed" value={summary.lessons} />
        <Tile icon={Layers} label="Cards reviewed" value={summary.reviews} />
        <Tile icon={MessageCircle} label="Conversations" value={summary.conversations} />
        <Tile icon={Trophy} label="Achievements" value={`${earned}/${achievements?.length ?? 0}`} />
      </div>

      <Card className="p-5">
        <h3 className="mb-4 font-bold">Activity</h3>
        {heat ? <Heatmap days={heat} /> : <Skeleton className="h-28" />}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title="Accuracy" subtitle="Share of exercises answered correctly, per week" columns={["Week of", "Accuracy", "Answers"]}
          rows={charts.accuracy_weekly.map((r) => [shortDate(r.week), `${r.accuracy}%`, r.answers])}>
          <SimpleLine data={charts.accuracy_weekly} x="week" y="accuracy" unit="%" domain={[0, 100]} labelFormat={shortDate} />
        </ChartCard>
        <ChartCard title="Conversation scores" subtitle="Average feedback score per conversation" columns={["Date", "Score"]}
          rows={charts.conversation_scores.map((r) => [shortDate(r.date), r.score])}>
          <SimpleLine data={charts.conversation_scores} x="date" y="score" domain={[0, 100]} labelFormat={shortDate} />
        </ChartCard>
        <ChartCard title="Time by activity" subtitle="Minutes, all time" columns={["Activity", "Minutes"]}
          rows={charts.time_by_activity.map((r) => [r.activity, r.minutes])}>
          <SimpleBars data={charts.time_by_activity} x="activity" y="minutes" unit=" min" />
        </ChartCard>
        <ChartCard title="Most common mistakes" subtitle="From conversation feedback" columns={["Type", "Count"]}
          rows={errors.map((r) => [r.type, r.count])}>
          <SimpleBars data={errors.slice(0, 7)} x="type" y="count" horizontal />
        </ChartCard>
      </div>

      <section>
        <h2 className="mb-3 text-lg font-bold">Achievements</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {achievements?.map((a) => (
            <Card key={a.key} className={cn("flex items-center gap-3 p-4", !a.earned_at && "opacity-50 grayscale")}>
              <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-gold-soft text-2xl">{a.icon}</span>
              <span className="min-w-0">
                <span className="block truncate text-sm font-bold">{a.title}</span>
                <span className="block text-xs text-muted-foreground">{a.earned_at ? new Date(a.earned_at).toLocaleDateString() : a.description}</span>
              </span>
            </Card>
          ))}
        </div>
      </section>
    </div>
  );
}
