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

export function useQueue(lang: Lang, mistakes: boolean) {
  return useQuery({
    queryKey: ["queue", lang, mistakes],
    queryFn: () => get<{ cards: SrsCard[]; counts: DeckStats["counts"] }>(`/srs/${lang}/queue?limit=100${mistakes ? "&mistakes=true" : ""}`),
    staleTime: Infinity,
    gcTime: 0,
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
