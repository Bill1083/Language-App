"use client";

import { BookOpen, Check, Crown, Dumbbell, Lock, MessageCircle, Play, Shield, Star, Trophy } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Flag } from "@/components/flag";
import { Dialog, DialogContent, Popover, PopoverContent, PopoverTrigger } from "@/components/ui/overlay";
import { Badge, Card, Progress, Skeleton } from "@/components/ui/primitives";
import { useCourse } from "@/hooks/queries";
import { useActiveLang } from "@/hooks/use-language";
import { CEFR_LABEL, LANGS } from "@/lib/languages";
import type { CourseLesson, CourseLevel, CourseUnit, Lang } from "@/lib/types";
import { cn } from "@/lib/utils";

const OFFSETS = [0, 1, 1.6, 1, 0, -1, -1.6, -1];

function nodeIcon(lesson: CourseLesson) {
  if (lesson.state === "locked") return Lock;
  if (lesson.kind === "checkpoint") return Shield;
  if (lesson.kind === "level_test" || (lesson.kind === "kana" && lesson.order === 100)) return Trophy;
  if (lesson.state === "perfect") return Crown;
  if (lesson.state === "completed") return Check;
  return lesson.kind === "kana" ? BookOpen : Star;
}

function LessonNode({ lesson, offset, isNext }: { lesson: CourseLesson; offset: number; isNext: boolean }) {
  const router = useRouter();
  const Icon = nodeIcon(lesson);
  const big = lesson.kind !== "lesson" && lesson.kind !== "kana" ? true : lesson.order === 100;
  const done = lesson.state === "completed" || lesson.state === "perfect";
  const kindLabel = {
    lesson: "Lesson", kana: lesson.order === 100 ? "Script test" : "Writing", checkpoint: "Checkpoint", level_test: "Level test",
  }[lesson.kind];
  return (
    <div className="flex flex-col items-center" style={{ transform: `translateX(${offset * 46}px)` }} id={isNext ? "next-lesson" : undefined}>
      <Popover>
        <PopoverTrigger asChild>
          <button
            type="button"
            aria-label={`${lesson.title} — ${lesson.state}`}
            className={cn(
              "relative flex items-center justify-center rounded-full transition active:translate-y-0.5",
              big ? "size-[78px] [&_svg]:size-9" : "size-[68px] [&_svg]:size-8",
              lesson.state === "locked" && "bg-muted text-muted-foreground/60 shadow-[0_5px_0_0_var(--border)]",
              lesson.state === "available" && "bg-primary text-primary-foreground shadow-[0_5px_0_0_var(--lang-strong)]",
              lesson.state === "completed" && "bg-primary text-primary-foreground shadow-[0_5px_0_0_var(--lang-strong)]",
              lesson.state === "perfect" && "bg-gold text-white shadow-[0_5px_0_0_color-mix(in_oklab,var(--gold)_70%,black)]",
              isNext && "animate-pulse-ring",
            )}
          >
            <Icon className={cn(lesson.state === "perfect" && "fill-white/30", lesson.state === "available" && "fill-white/20")} />
            {isNext && (
              <span className="absolute -top-9 whitespace-nowrap rounded-xl border bg-card px-3 py-1 text-xs font-bold uppercase tracking-wide text-primary-strong shadow-sm">
                Start
                <span className="absolute -bottom-1.5 left-1/2 size-3 -translate-x-1/2 rotate-45 border-b border-r bg-card" />
              </span>
            )}
          </button>
        </PopoverTrigger>
        <PopoverContent side="bottom" className="w-72">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{kindLabel}</p>
          <p className="mt-1 text-lg font-bold leading-snug">{lesson.title}</p>
          {done && lesson.best_accuracy != null && (
            <p className="mt-1 text-sm text-muted-foreground">Best score: {Math.round(lesson.best_accuracy * 100)}%</p>
          )}
          {lesson.state === "locked" ? (
            <p className="mt-3 text-sm text-muted-foreground">Finish the lessons before this one to unlock it.</p>
          ) : (
            <Button className="mt-4 w-full" onClick={() => router.push(`/lesson/${lesson.id}`)}>
              <Play className="fill-current" /> {done ? "Practise again" : lesson.kind === "level_test" ? "Take the test" : "Start"}
            </Button>
          )}
        </PopoverContent>
      </Popover>
      <p
        className={cn(
          "mt-3 max-w-36 text-center text-xs font-semibold leading-tight",
          lesson.state === "locked" ? "text-muted-foreground/70" : "text-foreground",
        )}
      >
        {lesson.title}
      </p>
    </div>
  );
}

function UnitGuide({ unit, lang, open, onOpenChange }: { unit: CourseUnit; lang: Lang; open: boolean; onOpenChange: (o: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent side="bottom" title={unit.title} description="What you'll learn in this unit">
        <h3 className="text-sm font-semibold text-muted-foreground">Objectives</h3>
        <ul className="mt-2 space-y-1.5">
          {unit.objectives.map((o) => (
            <li key={o} className="flex gap-2 text-[15px]">
              <Check className="mt-0.5 size-4 shrink-0 text-success" /> {o}
            </li>
          ))}
        </ul>
        {unit.vocab.length > 0 && (
          <>
            <h3 className="mt-5 text-sm font-semibold text-muted-foreground">Vocabulary</h3>
            <div className="mt-2 flex flex-wrap gap-1.5" lang={lang}>
              {unit.vocab.map((w) => (
                <span key={w} className="rounded-lg bg-muted px-2 py-1 text-sm">
                  {w}
                </span>
              ))}
            </div>
          </>
        )}
        <div className="mt-6 space-y-2.5">
          {unit.done > 0 && (
            <Button asChild className="w-full">
              <Link href={`/review-session?unit=${unit.id}`}>
                <Dumbbell /> {unit.theme === "writing" ? "Practise these characters" : "Practise this unit's words"}
              </Link>
            </Button>
          )}
          {unit.theme !== "writing" && (
            <Button asChild variant="soft" className="w-full">
              <Link href={`/talk?unit=${unit.id}`}>
                <MessageCircle /> Practise this unit in a conversation
              </Link>
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function UnitSection({ unit, index, lang, nextId }: { unit: CourseUnit; index: number; lang: Lang; nextId?: number }) {
  const [guide, setGuide] = React.useState(false);
  const lessons = unit.lessons;
  return (
    <section className="animate-rise" aria-label={unit.title}>
      <div
        className={cn(
          "flex items-center gap-4 rounded-2xl p-4 sm:p-5",
          unit.is_test ? "border bg-gold-soft" : unit.reached ? "bg-primary text-primary-foreground" : "border bg-card",
        )}
      >
        <div className="min-w-0 flex-1">
          <p className={cn("text-xs font-bold uppercase tracking-wider", unit.reached && !unit.is_test ? "text-white/75" : "text-muted-foreground")}>
            {unit.is_test ? "Level test" : unit.theme === "writing" ? "Writing system" : `Unit ${index + 1}`}
          </p>
          <h2 className="mt-0.5 truncate text-lg font-extrabold sm:text-xl">{unit.title}</h2>
          {!unit.is_test && (
            <p className={cn("mt-0.5 text-sm", unit.reached ? "text-white/80" : "text-muted-foreground")}>
              {unit.done}/{unit.total} lessons
            </p>
          )}
        </div>
        {!unit.is_test && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setGuide(true)}
            className={cn(unit.reached ? "bg-white/15 text-white hover:bg-white/25" : "bg-muted")}
          >
            <BookOpen /> Guide
          </Button>
        )}
      </div>
      <div className="flex flex-col items-center gap-12 py-10">
        {lessons.map((le, i) => (
          <LessonNode key={le.id} lesson={le} offset={OFFSETS[i % OFFSETS.length]} isNext={le.id === nextId} />
        ))}
        {!unit.is_test && unit.theme !== "writing" && (
          <Link
            href={unit.reached ? `/talk?unit=${unit.id}` : "#"}
            aria-disabled={!unit.reached}
            onClick={(e) => !unit.reached && e.preventDefault()}
            className={cn("flex flex-col items-center", !unit.reached && "pointer-events-none opacity-60")}
            style={{ transform: `translateX(${OFFSETS[lessons.length % OFFSETS.length] * 46}px)` }}
          >
            <span
              className={cn(
                "flex size-[68px] items-center justify-center rounded-full border-2 border-dashed transition hover:scale-105",
                unit.reached ? "border-primary bg-primary-soft text-primary-strong" : "border-border bg-muted text-muted-foreground",
              )}
            >
              <MessageCircle className="size-8" />
            </span>
            <span className="mt-3 text-center text-xs font-semibold">Unit conversation</span>
          </Link>
        )}
      </div>
      <UnitGuide unit={unit} lang={lang} open={guide} onOpenChange={setGuide} />
    </section>
  );
}

function LevelHeader({ level, lang }: { level: CourseLevel; lang: Lang }) {
  const test = level.units.find((u) => u.is_test)?.lessons[0];
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center gap-4">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-muted-foreground">
            <Flag lang={lang} /> {LANGS[lang].name}
          </p>
          <h1 className="text-2xl font-extrabold tracking-tight">
            {level.cefr === "PRE" ? "Hiragana & katakana" : `${level.cefr} · ${CEFR_LABEL[level.cefr]}`}
          </h1>
        </div>
        {(level.completed > 0 || (test && level.unlocked)) && (
          <div className="flex gap-2">
            {level.completed > 0 && (
              <Button asChild variant="soft">
                <Link href={`/review-session?level=${level.cefr}`}>
                  <Dumbbell /> Practise
                </Link>
              </Button>
            )}
            {test && level.unlocked && (
              <Button asChild variant={level.test_passed ? "secondary" : "outline"}>
                <Link href={`/lesson/${test.id}`}>
                  <Trophy /> {level.test_passed ? "Test passed" : "Test out"}
                </Link>
              </Button>
            )}
          </div>
        )}
      </div>
      <div className="mt-4 flex items-center gap-3">
        <Progress value={level.total ? level.completed / level.total : 0} className="flex-1" />
        <span className="text-sm font-semibold tabular-nums text-muted-foreground">
          {level.completed}/{level.total}
        </span>
      </div>
      {!level.unlocked && (
        <div className="mt-4 flex gap-3 rounded-xl bg-muted p-3 text-sm">
          <Lock className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <p className="text-muted-foreground">
            {lang === "ja" && level.cefr === "A1"
              ? "Finish (or test out of) hiragana and katakana first."
              : "Pass the previous level's test to unlock this level — or unlock it manually in Settings."}
          </p>
        </div>
      )}
    </Card>
  );
}

export default function LearnPage() {
  const lang = useActiveLang();
  const { data: course, isLoading } = useCourse(lang);
  const [selected, setSelected] = React.useState<string | null>(null);

  const defaultLevel = React.useMemo(() => {
    if (!course) return null;
    if (lang === "ja" && !course.kana_done) return "PRE";
    return course.next_lesson?.level ?? course.current_level;
  }, [course, lang]);
  const active = selected ?? defaultLevel;
  const level = course?.levels.find((l) => l.cefr === active);

  React.useEffect(() => {
    setSelected(null);
  }, [lang]);

  React.useEffect(() => {
    if (!level) return;
    const t = setTimeout(() => document.getElementById("next-lesson")?.scrollIntoView({ block: "center", behavior: "smooth" }), 250);
    return () => clearTimeout(t);
  }, [level]);

  if (isLoading || !course || !level) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-11 w-full" />
        <Skeleton className="h-32" />
        <Skeleton className="h-24" />
        <div className="flex flex-col items-center gap-8 py-6">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="size-[68px] rounded-full" />
          ))}
        </div>
      </div>
    );
  }

  let unitNumber = 0;
  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <div className="-mx-4 overflow-x-auto px-4 scrollbar-none sm:mx-0 sm:px-0">
        <div className="flex gap-2" role="tablist" aria-label="Levels">
          {course.levels.map((lv) => (
            <button
              key={lv.cefr}
              role="tab"
              aria-selected={lv.cefr === active}
              onClick={() => setSelected(lv.cefr)}
              className={cn(
                "flex shrink-0 items-center gap-1.5 rounded-xl border-2 px-3.5 py-2 text-sm font-bold transition",
                lv.cefr === active ? "border-primary bg-primary-soft text-primary-strong" : "bg-card text-muted-foreground hover:text-foreground",
              )}
            >
              {!lv.unlocked && <Lock className="size-3.5" />}
              {lv.cefr === "PRE" ? "Kana" : lv.cefr}
              {lv.test_passed && <Check className="size-3.5 text-success" />}
              {lv.cefr === course.current_level && <Badge tone="primary" className="px-1.5 py-0 text-[10px]">you</Badge>}
            </button>
          ))}
        </div>
      </div>

      <LevelHeader level={level} lang={lang} />

      {level.units.map((u) => {
        const idx = u.is_test || u.theme === "writing" ? -1 : unitNumber++;
        return <UnitSection key={u.id} unit={u} index={idx} lang={lang} nextId={course.next_lesson?.id} />;
      })}
    </div>
  );
}
