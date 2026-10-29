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

export type SessionScope = { mistakes?: boolean; level?: string | null; unit?: string | null };

/** Cards for a review session: the daily queue, the mistakes deck, or practice of one level / unit. */
export function useQueue(lang: Lang, scope: SessionScope) {
  const practice = !!(scope.level || scope.unit);
  const path = practice
    ? `/srs/${lang}/practice?${new URLSearchParams(scope.unit ? { unit_id: scope.unit } : { level: scope.level! })}`
    : `/srs/${lang}/queue?limit=100${scope.mistakes ? "&mistakes=true" : ""}`;
  return useQuery({
    queryKey: ["queue", lang, scope.mistakes ?? false, scope.level ?? null, scope.unit ?? null],
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
