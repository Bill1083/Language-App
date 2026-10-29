"use client";

import { useQuery } from "@tanstack/react-query";

import { get } from "@/lib/api";
import type { Achievement, Conversation, Course, Dashboard, Lang, Scenario, SrsCard } from "@/lib/types";

export function useDashboard(lang: Lang | null) {
  return useQuery({
    queryKey: ["dashboard", lang],
    queryFn: () => get<Dashboard>(`/dashboard${lang ? `?lang=${lang}` : ""}`),
    enabled: !!lang,
    staleTime: 15_000,
  });
}

export function useCourse(lang: Lang | null) {
  return useQuery({ queryKey: ["course", lang], queryFn: () => get<Course>(`/course/${lang}`), enabled: !!lang });
}

export type DeckStats = { counts: { due: number; new: number; mistakes_new: number }; total: number; mistakes: number; forecast: number[] };

export function useDeckStats(lang: Lang | null) {
  return useQuery({
    queryKey: ["deck", lang],
    queryFn: () => get<DeckStats>(`/srs/${lang}/stats`),
    enabled: !!lang,
    staleTime: 30_000,
  });
}

export type SessionScope = {
  mistakes?: boolean;
  level?: string | null;
  unit?: string | null;
  units?: string | null; // "3,4,5"
  lessons?: string | null; // lesson blocks from the course map, "12,13,14"
  order?: string | null; // "course" | "shuffle"
  limit?: string | null;
};

/** Query string for a practice selection (a level, one unit or several). */
export function practiceParams(scope: SessionScope) {
  const p = new URLSearchParams();
  if (scope.lessons) p.set("lessons", scope.lessons);
  else if (scope.units) p.set("units", scope.units);
  else if (scope.unit) p.set("unit_id", scope.unit);
  else if (scope.level) p.set("level", scope.level);
  if (scope.order) p.set("order", scope.order);
  if (scope.limit) p.set("limit", scope.limit);
  return p.toString();
}

/** Cards for a review session: the daily queue, the mistakes deck, or practice of a level / units. */
export function useQueue(lang: Lang, scope: SessionScope) {
  const practice = !!(scope.level || scope.unit || scope.units || scope.lessons);
  const path = practice
    ? `/srs/${lang}/practice?${practiceParams(scope)}`
    : `/srs/${lang}/queue?limit=100${scope.mistakes ? "&mistakes=true" : ""}`;
  return useQuery({
    queryKey: ["queue", lang, scope.mistakes ?? false, practice ? practiceParams(scope) : null],
    queryFn: () => get<{ cards: SrsCard[]; counts: DeckStats["counts"]; title?: string }>(path),
    staleTime: Infinity,
    gcTime: 0,
  });
}

export type PracticeLevel = {
  level: string;
  label: string;
  items: number;
  cards: number;
  due: number;
  units: { id: number; title: string; items: number; due: number }[];
};

export type PracticeItem = {
  card_id: number;
  kind: "word" | "kana";
  prompt: string;
  answer: string;
  accepted: string[];
  audio_text?: string | null;
  hint?: string | null;
  pos?: string | null;
  gender?: string | null;
  example?: string | null;
  example_translation?: string | null;
};

export type PracticeBlocks = {
  level: string;
  label: string;
  units: { id: number; title: string; lessons: { id: number; title: string; kind: string; items: number }[] }[];
}[];

/** Finished lessons from the course map, to pick for practice. */
export function usePracticeBlocks(lang: Lang | null) {
  return useQuery({
    queryKey: ["practice-blocks", lang],
    queryFn: () => get<PracticeBlocks>(`/srs/${lang}/practice/blocks`),
    enabled: !!lang,
    staleTime: 30_000,
  });
}

/** Words and kana for type-the-answer practice. */
export function usePracticeItems(lang: Lang, scope: SessionScope) {
  return useQuery({
    queryKey: ["practice-items", lang, practiceParams(scope)],
    queryFn: () => get<{ items: PracticeItem[]; title: string }>(`/srs/${lang}/practice/items?${practiceParams(scope)}`),
    staleTime: Infinity,
    gcTime: 0,
  });
}

export function usePracticeLevels(lang: Lang | null) {
  return useQuery({
    queryKey: ["practice-levels", lang],
    queryFn: () => get<PracticeLevel[]>(`/srs/${lang}/levels`),
    enabled: !!lang,
    staleTime: 30_000,
  });
}

export function useScenarios(lang: Lang | null) {
  return useQuery({ queryKey: ["scenarios", lang], queryFn: () => get<Scenario[]>(`/scenarios?lang=${lang}`), enabled: !!lang, staleTime: 300_000 });
}

export function useConversations(lang: Lang | null, q = "") {
  return useQuery({
    queryKey: ["conversations", lang, q],
    queryFn: () => get<{ items: (Conversation & { turns: number })[]; total: number }>(
      `/conversations?${new URLSearchParams({ ...(lang ? { lang } : {}), q })}`,
    ),
    enabled: !!lang,
  });
}

export function useAchievements() {
  return useQuery({ queryKey: ["achievements"], queryFn: () => get<Achievement[]>("/achievements") });
}

export function useKnownKanji(lang: Lang | null) {
  return useQuery({
    queryKey: ["kanji", lang],
    queryFn: () => get<{ kanji: string; count: number }>(`/kanji/${lang}`),
    enabled: lang === "ja",
    staleTime: 300_000,
  });
}
