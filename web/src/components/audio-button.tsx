"use client";

import { LoaderCircle, Snail, Volume2 } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { useMe } from "@/hooks/use-me";
import { ApiError, errorMessage } from "@/lib/api";
import { player, playSequence, ttsUrl } from "@/lib/audio";
import { stripRuby } from "@/lib/japanese";
import type { Lang } from "@/lib/types";
import { cn } from "@/lib/utils";

function usePlaying(id: string) {
  const [playing, setPlaying] = React.useState(false);
  React.useEffect(() => player?.subscribe((p) => setPlaying(p === id)), [id]);
  return playing;
}

type Props = {
  text?: string;
  /** pre-generated clips (conversation replies) — played in order instead of `text` */
  urls?: string[];
  lang: Lang;
  slow?: boolean;
  speed?: number;
  purpose?: "lesson" | "conversation";
  size?: "sm" | "md" | "lg" | "xl";
  variant?: "soft" | "ghost" | "solid";
  autoPlay?: boolean;
  label?: string;
  className?: string;
};

/** Play (or slow-play) any text through TTS. Shows a spinner while the clip is generated. */
export function AudioButton({
  text,
  urls,
  lang,
  slow,
  speed,
  purpose = "lesson",
  size = "md",
  variant = "soft",
  autoPlay,
  label,
  className,
}: Props) {
  const { data: me } = useMe();
  const clean = text ? stripRuby(text) : "";
  const rate = speed ?? (slow ? 0.75 : me?.settings.speech_speed ?? 1);
  const id = React.useMemo(() => `${lang}|${rate}|${clean}|${urls?.join(",") ?? ""}`, [lang, rate, clean, urls]);
  const playing = usePlaying(id);
  const [loading, setLoading] = React.useState(false);
  const gender = me?.settings.voice_gender ?? "female";

  const play = React.useCallback(async (quiet = false) => {
    if (playing) {
      player.stop();
      return;
    }
    try {
      if (urls?.length && !slow) {
        await playSequence(urls, id, 1);
        return;
      }
      if (!clean) return;
      setLoading(true);
      const url = await ttsUrl(clean, lang, { speed: rate, purpose, gender });
      setLoading(false);
      await player.play(url, id);
    } catch (e) {
      setLoading(false);
      // Auto-play failures stay silent (no toast storm when TTS isn't configured).
      if (!quiet) {
        const detail = e instanceof ApiError && typeof e.detail === "string" ? e.detail : errorMessage(e);
        toast.error("Audio unavailable", { id: "audio-error", description: detail });
      }
    }
  }, [playing, urls, slow, id, clean, lang, rate, purpose, gender]);

  const auto = React.useRef(false);
  React.useEffect(() => {
    if (autoPlay && !auto.current && (clean || urls?.length)) {
      auto.current = true;
      void play(true);
    }
  }, [autoPlay, clean, urls, play]);

  const dims = { sm: "size-8 [&_svg]:size-4", md: "size-10 [&_svg]:size-5", lg: "size-14 [&_svg]:size-7", xl: "size-24 [&_svg]:size-11" }[size];
  const styles = {
    soft: "bg-primary-soft text-primary-strong hover:brightness-105",
    ghost: "text-muted-foreground hover:bg-muted hover:text-foreground",
    solid: "bg-primary text-primary-foreground shadow-[0_3px_0_0_var(--lang-strong)] hover:brightness-105",
  }[variant];

  const Icon = loading ? LoaderCircle : slow ? Snail : Volume2;
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        void play();
      }}
      aria-label={label ?? (slow ? "Play slowly" : "Play audio")}
      title={label ?? (slow ? "Play slowly" : "Play audio")}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full transition active:scale-95",
        dims,
        styles,
        playing && "ring-4 ring-primary/25",
        className,
      )}
    >
      <Icon className={cn(loading && "animate-spin", playing && !loading && "animate-pulse")} aria-hidden />
    </button>
  );
}
