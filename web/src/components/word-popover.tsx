"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Plus } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { errorMessage, post } from "@/lib/api";
import type { Lang } from "@/lib/types";

import { AudioButton } from "./audio-button";
import { Button } from "./ui/button";
import { Popover, PopoverAnchor, PopoverContent } from "./ui/overlay";
import { Badge, Skeleton } from "./ui/primitives";

type Lookup = {
  word: string;
  lemma: string;
  reading: string | null;
  meaning: string;
  pos: string | null;
  gender: string | null;
  notes: string | null;
  in_deck: boolean;
};

export type WordTarget = { word: string; rect: DOMRect; context: string } | null;

export function useWordPopover() {
  const [target, setTarget] = React.useState<WordTarget>(null);
  const open = React.useCallback((word: string, el: HTMLElement, context: string) => {
    setTarget({ word, rect: el.getBoundingClientRect(), context });
  }, []);
  return { target, open, close: () => setTarget(null) };
}

export function GenderBadge({ gender }: { gender?: string | null }) {
  if (gender === "m") return <Badge tone="masc">masc.</Badge>;
  if (gender === "f") return <Badge tone="fem">fem.</Badge>;
  if (gender === "m/f") return <Badge>m/f</Badge>;
  return null;
}

/** Tap-a-word lookup: meaning, reading, audio and "add to my review deck". */
export function WordPopover({ target, lang, onClose }: { target: WordTarget; lang: Lang; onClose: () => void }) {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["lookup", lang, target?.word, target?.context],
    queryFn: () => post<Lookup>("/lookup", { lang, word: target!.word, context: target!.context }),
    enabled: !!target,
    staleTime: Infinity,
  });
  const add = useMutation({
    mutationFn: () =>
      post(`/vocab/${lang}`, {
        word: data!.lemma, meaning: data!.meaning, reading: data!.reading, gender: data!.gender, pos: data!.pos,
        example: target?.context, source: "conversation",
      }),
    onSuccess: () => {
      toast.success(`“${data!.lemma}” added to your review deck`);
      qc.setQueryData(["lookup", lang, target?.word, target?.context], { ...data!, in_deck: true });
      void qc.invalidateQueries({ queryKey: ["deck"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  return (
    <Popover open={!!target} onOpenChange={(o) => !o && onClose()}>
      {target && (
        <PopoverAnchor asChild>
          <span
            style={{
              position: "fixed",
              left: target.rect.left,
              top: target.rect.top,
              width: target.rect.width,
              height: target.rect.height,
              pointerEvents: "none",
            }}
          />
        </PopoverAnchor>
      )}
      <PopoverContent side="top" className="w-80">
        {isLoading || !data ? (
          error ? (
            <p className="text-sm text-danger">{errorMessage(error)}</p>
          ) : (
            <div className="space-y-2">
              <Skeleton className="h-6 w-32" />
              <Skeleton className="h-4 w-48" />
              <Skeleton className="h-4 w-40" />
            </div>
          )
        ) : (
          <div className="space-y-3">
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <p className="text-xl font-bold leading-tight" lang={lang}>
                  {data.lemma}
                </p>
                {data.reading && data.reading !== data.lemma && (
                  <p className="text-sm text-muted-foreground" lang={lang}>
                    {data.reading}
                  </p>
                )}
              </div>
              <AudioButton text={data.lemma} lang={lang} size="sm" />
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              {data.pos && <Badge>{data.pos}</Badge>}
              <GenderBadge gender={data.gender} />
            </div>
            <p className="text-[15px]">{data.meaning}</p>
            {data.notes && <p className="text-sm text-muted-foreground">{data.notes}</p>}
            {data.in_deck ? (
              <p className="flex items-center gap-1.5 text-sm font-medium text-success">
                <Check className="size-4" /> In your review deck
              </p>
            ) : (
              <Button size="sm" variant="soft" className="w-full" loading={add.isPending} onClick={() => add.mutate()}>
                <Plus /> Add to my review deck
              </Button>
            )}
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
