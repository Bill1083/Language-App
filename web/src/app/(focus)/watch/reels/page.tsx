"use client";

import { ArrowLeft, ChevronDown, ChevronUp, Clapperboard, LoaderCircle, Volume2, VolumeX } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Badge, EmptyState, Progress, Segmented } from "@/components/ui/primitives";
import { LineText, lineAt, type Mode } from "@/components/video/subtitles";
import { useWordPopover, WordPopover } from "@/components/word-popover";
import { useActiveLang } from "@/hooks/use-language";
import { useMe, useUpdateSettings } from "@/hooks/use-me";
import { errorMessage, get, post } from "@/lib/api";
import { stripRuby } from "@/lib/japanese";
import type { Lang, Reel, ReelsDifficulty } from "@/lib/types";
import { cn } from "@/lib/utils";
import { loadYouTube, PLAYING, type YTPlayer } from "@/lib/youtube";

const DIFFICULTIES: { value: ReelsDifficulty; label: string }[] = [
  { value: "easier", label: "Easier" }, { value: "level", label: "My level" },
  { value: "harder", label: "Harder" }, { value: "challenge", label: "Challenge" },
];
const PAGE = 8;

/** Plays one clip at a time on a single reused player (YouTube or a file), looping it. */
function ClipPlayer({ reel, muted, paused, onTime, onTapSound }: {
  reel: Reel; muted: boolean; paused: boolean; onTime: (ms: number) => void; onTapSound: () => void;
}) {
  const ytHost = React.useRef<HTMLDivElement>(null);
  const yt = React.useRef<YTPlayer | null>(null);
  const ytReady = React.useRef<Promise<YTPlayer> | null>(null);
  const file = React.useRef<HTMLVideoElement>(null);
  const [waiting, setWaiting] = React.useState(true);
  const live = React.useRef({ reel, muted, paused, onTime });
  live.current = { reel, muted, paused, onTime };

  const youtube = React.useCallback((): Promise<YTPlayer> => {
    ytReady.current ??= loadYouTube().then((YT) => new Promise<YTPlayer>((resolve) => {
      const r = live.current.reel;
      const p: YTPlayer = new YT.Player(ytHost.current!, {
        videoId: r.youtube_id, host: "https://www.youtube-nocookie.com", width: "100%", height: "100%",
        playerVars: { playsinline: 1, rel: 0, autoplay: 1, mute: 1, controls: 0, disablekb: 1, cc_load_policy: 0,
          iv_load_policy: 3, start: Math.floor(r.start / 1000) },
        events: {
          onReady: () => { yt.current = p; resolve(p); },
          onStateChange: (e: { data: number }) => {
            if (e.data === PLAYING) { p.unloadModule?.("captions"); setWaiting(false); }
          },
        },
      });
    }));
    return ytReady.current;
  }, []);

  // switch clips
  React.useEffect(() => {
    setWaiting(true);
    if (reel.source === "youtube" && reel.youtube_id) {
      file.current?.pause();
      void youtube().then((p) => {
        if (live.current.reel.id !== reel.id) return;
        if (live.current.muted) p.mute?.(); else p.unMute?.();
        p.loadVideoById?.({ videoId: reel.youtube_id!, startSeconds: reel.start / 1000 });
      });
    } else if (reel.file_url && file.current) {
      yt.current?.pauseVideo();
      const v = file.current;
      const start = () => { v.currentTime = reel.start / 1000; void v.play().catch(() => {}); };
      if (v.getAttribute("src") !== reel.file_url) {
        v.src = reel.file_url;
        v.addEventListener("loadedmetadata", start, { once: true });
      } else start();
    }
  }, [reel, youtube]);

  // sound, pause
  React.useEffect(() => {
    if (reel.source === "youtube") {
      if (muted) yt.current?.mute?.(); else yt.current?.unMute?.();
      if (paused) yt.current?.pauseVideo(); else if (yt.current) yt.current.playVideo();
    } else if (file.current) {
      file.current.muted = muted;
      if (paused) file.current.pause(); else void file.current.play().catch(() => {});
    }
  }, [muted, paused, reel]);

  // follow the playhead; loop the clip
  React.useEffect(() => {
    const t = setInterval(() => {
      const { reel: r, onTime: report } = live.current;
      const now = r.source === "youtube" ? (yt.current?.getCurrentTime() ?? 0) * 1000 : (file.current?.currentTime ?? 0) * 1000;
      report(Math.round(now));
      if (now >= r.end) {
        if (r.source === "youtube") yt.current?.seekTo(r.start / 1000, true);
        else if (file.current) file.current.currentTime = r.start / 1000;
      }
    }, 150);
    return () => clearInterval(t);
  }, []);

  React.useEffect(() => () => yt.current?.destroy(), []);

  const isFile = reel.source === "file";
  return (
    <div className="relative aspect-video w-full overflow-hidden bg-black">
      <div className={cn("absolute inset-0 [&_iframe]:pointer-events-none [&_iframe]:size-full", isFile && "invisible")}>
        <div ref={ytHost} />
      </div>
      <video ref={file} playsInline muted={muted} preload="auto" onPlaying={() => setWaiting(false)}
        className={cn("absolute inset-0 size-full", !isFile && "invisible")} />
      {waiting && reel.poster && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={reel.poster} alt="" className="absolute inset-0 size-full object-cover opacity-70" />
      )}
      {waiting && <LoaderCircle className="absolute inset-0 m-auto size-8 animate-spin text-white" />}
      <button type="button" onClick={onTapSound} aria-label={muted ? "Turn sound on" : "Mute"}
        className={cn("absolute bottom-2 right-2 flex items-center gap-1.5 rounded-full bg-black/65 px-3 py-1.5 text-sm font-semibold text-white",
          !muted && "px-2")}>
        {muted ? <><VolumeX className="size-4" /> Tap for sound</> : <Volume2 className="size-4" />}
      </button>
    </div>
  );
}

export default function ReelsPage() {
  const lang = useActiveLang();
  const { data: me } = useMe();
  const update = useUpdateSettings();
  const words = useWordPopover();
  const difficulty: ReelsDifficulty = me?.settings.reels_difficulty ?? "level";
  const mode: Mode = lang !== "ja" && me?.settings.video_subtitles === "kana" ? "full" : (me?.settings.video_subtitles ?? "full");

  const [items, setItems] = React.useState<Reel[]>([]);
  const [index, setIndex] = React.useState(0);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [done, setDone] = React.useState(false);
  const [muted, setMuted] = React.useState(true);
  const [paused, setPaused] = React.useState(false);
  const [ms, setMs] = React.useState(0);
  const fetching = React.useRef(false);

  const load = React.useCallback(async (reset: boolean) => {
    if (!lang || fetching.current) return;
    fetching.current = true;
    setLoading(true);
    try {
      const have = reset ? [] : items;
      const exclude = have.map((r) => r.id).join(",");
      const r = await get<{ items: Reel[] }>(`/videos/reels?lang=${lang}&difficulty=${difficulty}&limit=${PAGE}&exclude=${exclude}`);
      setItems(reset ? r.items : [...have, ...r.items]);
      setDone(r.items.length < PAGE);
      if (reset) setIndex(0);
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      fetching.current = false;
      setLoading(false);
    }
  }, [lang, difficulty, items]);

  // first page, and a fresh feed whenever the difficulty changes
  React.useEffect(() => {
    if (me) void load(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lang, difficulty, !!me]);

  // keep a few clips ahead
  React.useEffect(() => {
    if (!done && items.length && index >= items.length - 3) void load(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index, items.length, done]);

  const reel = items[index];

  // seen after 3 seconds on a clip, so the feed moves on next time
  React.useEffect(() => {
    if (!reel) return;
    setPaused(false);
    const t = setTimeout(() => void post(`/videos/reels/${reel.id}/seen`).catch(() => {}), 3000);
    return () => clearTimeout(t);
  }, [reel]);

  const go = React.useCallback((step: number) => {
    setIndex((i) => Math.max(0, Math.min(items.length - 1, i + step)));
    words.close();
  }, [items.length, words]);

  // swipe, wheel and keys
  const touchY = React.useRef<number | null>(null);
  const wheelAt = React.useRef(0);
  React.useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); go(1); }
      else if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); go(-1); }
      else if (e.code === "Space") { e.preventDefault(); setPaused((p) => !p); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [go]);

  const line = reel ? (() => { const i = lineAt(reel.lines, ms); return i >= 0 && ms <= reel.lines[i].end + 1200 ? reel.lines[i] : undefined; })() : undefined;
  const clipProgress = reel ? Math.max(0, Math.min(1, (ms - reel.start) / (reel.end - reel.start))) : 0;

  return (
    <div className="mx-auto flex h-dvh max-w-xl flex-col overflow-hidden"
      onTouchStart={(e) => (touchY.current = e.touches[0].clientY)}
      onTouchEnd={(e) => {
        if (touchY.current === null) return;
        const dy = e.changedTouches[0].clientY - touchY.current;
        touchY.current = null;
        if (Math.abs(dy) > 60) go(dy < 0 ? 1 : -1);
      }}
      onWheel={(e) => {
        if (Math.abs(e.deltaY) < 30 || Date.now() - wheelAt.current < 600) return;
        wheelAt.current = Date.now();
        go(e.deltaY > 0 ? 1 : -1);
      }}>
      <header className="safe-top flex items-center gap-2 px-2 pt-2 sm:px-4">
        <Button asChild variant="ghost" size="icon" aria-label="Back to Watch">
          <Link href="/watch"><ArrowLeft /></Link>
        </Button>
        <h1 className="flex-1 font-bold">Reels</h1>
        {reel && <span className="text-sm tabular-nums text-muted-foreground">{index + 1} / {items.length}{done ? "" : "+"}</span>}
      </header>
      <div className="px-3 pb-3 pt-2 sm:px-4">
        <Segmented ariaLabel="Difficulty" className="w-full" value={difficulty} options={DIFFICULTIES}
          onChange={(v) => update.mutate({ reels_difficulty: v })} />
      </div>

      {!reel ? (
        <div className="flex flex-1 items-center justify-center p-4">
          {loading ? <LoaderCircle className="size-8 animate-spin text-primary" /> : error ? (
            <EmptyState title="Couldn't load reels">
              {error} <Button variant="outline" className="mt-3" onClick={() => void load(true)}>Try again</Button>
            </EmptyState>
          ) : (
            <EmptyState icon={<Clapperboard />} title="No clips yet">
              Reels are cut from the videos in Watch. Add a video and they appear here once it&apos;s ready.
              <Button asChild className="mt-3"><Link href="/watch">Go to Watch</Link></Button>
            </EmptyState>
          )}
        </div>
      ) : (
        <>
          <div className="relative" onClick={(e) => { if ((e.target as HTMLElement).closest("button")) return; setPaused((p) => !p); }}>
            <ClipPlayer reel={reel} muted={muted} paused={paused} onTime={setMs} onTapSound={() => setMuted((m) => !m)} />
            {paused && (
              <span className="pointer-events-none absolute left-2 top-2 rounded-full bg-black/65 px-2.5 py-1 text-xs font-semibold text-white">Paused</span>
            )}
            <Progress value={clipProgress} className="absolute inset-x-0 bottom-0 h-1 rounded-none bg-black/30" />
          </div>

          <main className="flex min-h-0 flex-1 flex-col px-4 pt-3">
            <div className="flex items-center gap-2">
              <Badge tone="primary" className="shrink-0">{reel.level}</Badge>
              {reel.known !== null && <Badge className="shrink-0 whitespace-nowrap">{reel.known}% known</Badge>}
              <Link href={`/watch/${reel.video_id}`} className="ml-auto min-w-0 truncate text-sm font-semibold text-primary-strong hover:underline">
                {reel.title}
              </Link>
            </div>
            <div className="flex min-h-0 flex-1 items-center py-4" aria-live="polite">
              {line ? (
                <LineText line={line} mode={mode} lang={lang as Lang} big
                  onWordTap={(w, el) => { setPaused(true); words.open(w, el, stripRuby(line.text)); }} />
              ) : (
                <p className="text-muted-foreground">…</p>
              )}
            </div>
            <div className="safe-bottom flex items-center justify-between gap-2 border-t py-2">
              <Button variant="ghost" size="sm" disabled={index === 0} onClick={() => go(-1)}><ChevronUp /> Back</Button>
              <span className="text-xs text-muted-foreground">Swipe up for the next clip</span>
              <Button variant="ghost" size="sm" disabled={index >= items.length - 1} onClick={() => go(1)}>Next <ChevronDown /></Button>
            </div>
          </main>
        </>
      )}
      {lang && <WordPopover target={words.target} lang={lang as Lang} onClose={words.close} />}
    </div>
  );
}
