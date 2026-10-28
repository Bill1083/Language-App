"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ApiError, errorMessage, get, patch } from "@/lib/api";
import type { Me, UserSettings } from "@/lib/types";

export function useMe() {
  return useQuery<Me, ApiError>({
    queryKey: ["me"],
    queryFn: () => get<Me>("/auth/me"),
    retry: (count, e) => e.status !== 401 && count < 2,
    staleTime: 60_000,
  });
}

/** Optimistically patch user settings (theme, voice, furigana…). */
export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (settings: Partial<UserSettings>) => patch<Me>("/auth/me", { settings }),
    onMutate: async (settings) => {
      await qc.cancelQueries({ queryKey: ["me"] });
      const prev = qc.getQueryData<Me>(["me"]);
      if (prev) qc.setQueryData<Me>(["me"], { ...prev, settings: { ...prev.settings, ...settings } });
      return { prev };
    },
    onError: (e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(["me"], ctx.prev);
      toast.error(errorMessage(e));
    },
    onSuccess: (me) => qc.setQueryData(["me"], me),
  });
}
