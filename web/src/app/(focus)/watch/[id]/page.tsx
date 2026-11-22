"use client";

import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, Check, LoaderCircle, Maximize, Minimize, Pause, Play, Repeat, SkipBack, SkipForward } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { RubyText } from "@/components/ruby-text";
import { Button } from "@/components/ui/button";
import { Badge, Card, Progress, Segmented, Skeleton, Switch } from "@/components/ui/primitives";
import { useWordPopover, WordPopover } from "@/components/word-popover";
import { useVideo } from "@/hooks/queries";
import { useMe, useUpdateSettings } from "@/hooks/use-me";
import { errorMessage, post, put } from "@/lib/api";
import { stripRuby } from "@/lib/japanese";
import type { Lang, VideoLine, VideoWord } from "@/lib/types";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------- YouTube player

type YTPlayer = {
  playVideo(): void;
  pauseVideo(): void;
  seekTo(seconds: number, allowSeekAhead: boolean): void;
  getCurrentTime(): number;
  setPlaybackRate(rate: number): void;
  destroy(): void;
  unloadModule?(name: string): void;
};
type YTNamespace = { Player: new (el: HTMLElement, opts: Record<string, unknown>) => YTPlayer };

declare global {
  interface Window {
    YT?: YTNamespace;
    onYouTubeIframeAPIReady?: () => void;
  }
}

const PLAYING = 1;
const ENDED = 0;

let ytApi: Promise<YTNamespace> | null = null;
/** YouTube's official IFrame Player API, loaded once. */
function loadYouTube(): Promise<YTNamespace> {
  ytApi ??= new Promise((resolve) => {
    if (window.YT?.Player) return resolve(window.YT);
    const previous = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => {
      previous?.();
      resolve(window.YT!);
    };
    const script = document.createElement("script");
    script.src = "https://www.youtube.com/iframe_api";
    script.async = true;
    document.head.appendChild(script);
  });
  return ytApi;
}

function YouTubePlayer({ youtubeId, startS, onReady, onState }: {
  youtubeId: string; startS: number; onReady: (p: YTPlayer) => void; onState: (state: number) => void;
}) {
  const host = React.useRef<HTMLDivElement>(null);
  const handlers = React.useRef({ onReady, onState });
  handlers.current = { onReady, onState };
  React.useEffect(() => {
    let player: YTPlayer | null = null;
    let gone = false;
    void loadYouTube().then((YT) => {
      if (gone || !host.current) return;
      player = new YT.Player(host.current, {
        videoId: youtubeId,
        host: "https://www.youtube-nocookie.com", // no tracking cookies until play
        width: "100%",
        height: "100%",
        playerVars: { playsinline: 1, rel: 0, start: Math.floor(startS), cc_load_policy: 0, iv_load_policy: 3 },
        events: {
          onReady: () => handlers.current.onReady(player!),
          onStateChange: (e: { data: number }) => {
            // YouTube's own captions would cover the picture and compete with Parlo's
            if (e.data === PLAYING) player?.unloadModule?.("captions");
            handlers.current.onState(e.data);
          },
        },
      });
    });
    return () => {
      gone = true;
      player?.destroy();
    };
    // the start position only matters for the first load
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [youtubeId]);
  return (
    <div className="aspect-video w-full overflow-hidden bg-black [&_iframe]:size-full">
      <div ref={host} />
    </div>
  );
}

// ---------------------------------------------------------------- your own file

const PAUSED = 2;

/** A plain <video> behind the same small interface as the YouTube player, with room for
 * subtitles on the picture and a full-screen mode that keeps them. */
function FilePlayer({ src, poster, startS, onReady, onState, onSeek, overlay, fullscreen, onFullscreen }: {
  src: string; poster: string | null; startS: number; onReady: (p: YTPlayer) => void; onState: (s: number) => void;
  onSeek: (ms: number) => void; overlay: React.ReactNode; fullscreen: boolean; onFullscreen: (on: boolean) => void;
}) {
  const box = React.useRef<HTMLDivElement>(null);
  const el = React.useRef<HTMLVideoElement>(null);
  const started = React.useRef(false);

  React.useEffect(() => {
    const h = () => onFullscreen(document.fullscreenElement === box.current);
    document.addEventListener("fullscreenchange", h);
    return () => document.removeEventListener("fullscreenchange", h);
  }, [onFullscreen]);

  const toggleFullscreen = () => {
    const v = el.current as (HTMLVideoElement & { webkitEnterFullscreen?: () => void }) | null;
    if (document.fullscreenElement) void document.exitFullscreen();
    else if (box.current?.requestFullscreen) void box.current.requestFullscreen().catch(() => v?.webkitEnterFullscreen?.());
    else v?.webkitEnterFullscreen?.(); // iPhone: the system player (subtitles stay below)
  };

  return (
    <div ref={box} className={cn("relative w-full bg-black", fullscreen ? "flex h-full items-center" : "aspect-video")}>
      <video ref={el} src={src} poster={poster ?? undefined} controls playsInline preload="metadata"
        controlsList="nofullscreen nodownload" disablePictureInPicture className="size-full"
        onLoadedMetadata={(e) => {
          const v = e.currentTarget;
          if (!started.current && startS > 1 && startS < v.duration - 5) v.currentTime = startS;
          started.current = true;
          onReady({
            playVideo: () => void v.play().catch(() => {}),
            pauseVideo: () => v.pause(),
            seekTo: (s) => { v.currentTime = s; },
            getCurrentTime: () => v.currentTime,
            setPlaybackRate: (r) => { v.playbackRate = r; },
            destroy: () => v.pause(),
          });
        }}
        onPlay={() => onState(PLAYING)} onPause={() => onState(PAUSED)} onEnded={() => onState(ENDED)}
        onSeeked={(e) => onSeek(Math.round(e.currentTarget.currentTime * 1000))} />
      {overlay && (
        <div className={cn("pointer-events-none absolute inset-x-0 flex justify-center px-3",
          fullscreen ? "bottom-16 sm:bottom-20" : "bottom-14")}>
          <div className={cn("pointer-events-auto max-w-[92%] rounded-xl bg-black/70 px-3 py-1.5 text-center text-white",
            "[&_rt]:text-white/80", fullscreen && "sm:max-w-[70%] sm:px-5 sm:py-2.5 sm:text-2xl")}>
            {overlay}
          </div>
        </div>
      )}
      <Button size="icon-sm" variant="ghost" aria-label={fullscreen ? "Exit full screen" : "Full screen with subtitles"}
        onClick={toggleFullscreen}
        className="absolute right-2 top-2 size-9 rounded-full bg-black/55 text-white hover:bg-black/75 hover:text-white">
        {fullscreen ? <Minimize /> : <Maximize />}
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------- subtitles

type Mode = "full" | "kana" | "text";

/** Index of the line being spoken at `ms`: the last line that has started (-1 before the first). */
function lineAt(lines: VideoLine[], ms: number): number {
  let lo = 0;
  let hi = lines.length - 1;
  let found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (lines[mid].start <= ms) {
      found = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return found;
}

function LineText({ line, mode, lang, big, onWordTap }: {
  line: VideoLine; mode: Mode; lang: Lang; big?: boolean; onWordTap?: (w: string, el: HTMLElement) => void;
}) {
  const ja = lang === "ja";
  const text = mode === "kana" && ja ? (line.kana ?? line.text) : line.text;
  return (
    <div className={cn(big ? "space-y-1.5" : "space-y-0.5")}>
      <p className={cn(big ? "text-[22px] font-semibold leading-relaxed" : "text-[15px] leading-relaxed")} lang={lang}>
        <RubyText text={text} lang={lang} furigana={mode === "full" ? "always" : "never"} romaji="off" showRomaji={false}
          onWordTap={onWordTap} />
      </p>
      {mode === "full" && line.en && (
        <p className={cn("text-muted-foreground", big ? "text-[15px]" : "text-xs")}>{line.en}</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- words from this video

function VideoWords({ videoId, lines, lang }: { videoId: number; lines: VideoLine[]; lang: Lang }) {
  const router = useRouter();
  const words = React.useMemo(() => {
    const seen = new Map<string, VideoWord & { example: string; example_translation: string | null }>();
    for (const l of lines) {
      for (const w of l.words) {
        const key = stripRuby(w.word);
        if (!seen.has(key)) seen.set(key, { ...w, example: l.text, example_translation: l.en });
      }
    }
    return [...seen.values()];
  }, [lines]);
  const [picked, setPicked] = React.useState<Set<string>>(new Set());
  React.useEffect(() => setPicked(new Set(words.slice(0, 15).map((w) => w.word))), [words]);
  const [added, setAdded] = React.useState<number[] | null>(null);
  const add = useMutation({
    mutationFn: () => post<{ vocab_ids: number[] }>(`/videos/${videoId}/words`, { words: words.filter((w) => picked.has(w.word)) }),
    onSuccess: (r) => {
      setAdded(r.vocab_ids);
      toast.success(`${r.vocab_ids.length} words added to your review deck`);
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  if (!words.length) return null;
  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between gap-3 p-4 pb-3">
        <div>
          <h2 className="font-bold">Words from this video</h2>
          <p className="text-sm text-muted-foreground">Pick the ones you want to learn.</p>
        </div>
        <button type="button" className="shrink-0 text-sm font-semibold text-primary-strong hover:underline"
          onClick={() => setPicked(picked.size === words.length ? new Set() : new Set(words.map((w) => w.word)))}>
          {picked.size === words.length ? "None" : "All"}
        </button>
      </div>
      <ul className="max-h-80 divide-y overflow-y-auto border-t">
        {words.map((w) => {
          const on = picked.has(w.word);
          return (
            <li key={w.word}>
              <button type="button" aria-pressed={on}
                onClick={() => setPicked((s) => { const n = new Set(s); if (on) n.delete(w.word); else n.add(w.word); return n; })}
                className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-muted/50">
                <span className={cn("flex size-6 shrink-0 items-center justify-center rounded-lg border-2", on ? "border-primary bg-primary text-primary-foreground" : "border-border")}>
                  {on && <Check className="size-4" strokeWidth={3} />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block font-semibold" lang={lang}><RubyText text={w.word} lang={lang} showRomaji={false} /></span>
                  <span className="block truncate text-sm text-muted-foreground">{w.meaning}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <div className="grid gap-2 border-t p-3 sm:grid-cols-2">
        <Button variant="outline" disabled={!picked.size} loading={add.isPending} onClick={() => add.mutate()}>
          Add {picked.size} to my deck
        </Button>
        <Button disabled={!added?.length} onClick={() => router.push(`/practice-type?vocab=${added!.join(",")}`)}>
          Practise them now
        </Button>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------- page

export default function WatchVideoPage() {
  const { id } = useParams<{ id: string }>();
  const { data: video, isLoading } = useVideo(Number(id));
  const { data: me } = useMe();
  const update = useUpdateSettings();
  const words = useWordPopover();
  const player = React.useRef<YTPlayer | null>(null);
  const [ready, setReady] = React.useState(false);
  const [playing, setPlaying] = React.useState(false);
  const [ended, setEnded] = React.useState(false);
  const [ms, setMs] = React.useState(0);
  const [slow, setSlow] = React.useState(false);
  const [fullscreen, setFullscreen] = React.useState(false);
  const [onPicture, setOnPicture] = React.useState(true);
  React.useEffect(() => {
    try { setOnPicture(localStorage.getItem("parlo.subs-on-video") !== "0"); } catch { /* default on */ }
  }, []);
  const pictureSubs = (on: boolean) => {
    setOnPicture(on);
    try { localStorage.setItem("parlo.subs-on-video", on ? "1" : "0"); } catch { /* not remembered */ }
  };
  const stopAt = React.useRef<number | null>(null); // pause-after-each-line target
  const transcript = React.useRef<HTMLDivElement>(null);
  const userScrolledAt = React.useRef(0);

  const lines = React.useMemo(() => video?.lines ?? [], [video?.lines]);
  const lang = (video?.language ?? "ja") as Lang;
  const mode: Mode = lang !== "ja" && me?.settings.video_subtitles === "kana" ? "full" : (me?.settings.video_subtitles ?? "full");
  const autopause = !!me?.settings.video_autopause;
  const current = lineAt(lines, ms);
  const line = current >= 0 ? lines[current] : undefined;
  const showing = line && ms <= line.end + 1500 ? line : undefined; // keep a line up briefly, then clear

  // follow the playhead
  React.useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => {
      const now = Math.round((player.current?.getCurrentTime() ?? 0) * 1000);
      setMs(now);
      if (stopAt.current !== null && now >= stopAt.current - 60) {
        stopAt.current = null;
        player.current?.pauseVideo();
      }
    }, 150);
    return () => clearInterval(t);
  }, [playing]);

  // pause after each line: arm when a new line starts
  React.useEffect(() => {
    if (autopause && playing && line) stopAt.current = line.end;
    if (!autopause) stopAt.current = null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current, autopause]);

  // remember where you got to
  const save = React.useCallback(() => {
    if (video && ms > 0) void put(`/videos/${video.id}/progress`, { position_ms: ms }).catch(() => {});
  }, [video, ms]);
  const saveRef = React.useRef(save);
  saveRef.current = save;
  React.useEffect(() => {
    const t = setInterval(() => saveRef.current(), 15_000);
    return () => { clearInterval(t); saveRef.current(); };
  }, []);

  // keep the current line in view in the transcript (unless you're scrolling it yourself)
  React.useEffect(() => {
    const box = transcript.current;
    const el = box?.querySelector<HTMLElement>(`[data-i="${current}"]`);
    if (!box || !el || Date.now() - userScrolledAt.current < 4000) return;
    box.scrollTo({ top: el.offsetTop - box.clientHeight / 3, behavior: "smooth" });
  }, [current]);

  const seekLine = React.useCallback((i: number) => {
    const target = lines[Math.max(0, Math.min(lines.length - 1, i))];
    if (!target || !player.current) return;
    player.current.seekTo(Math.max(0, target.start / 1000 - 0.15), true);
    setMs(target.start);
    stopAt.current = autopause ? target.end : null;
    player.current.playVideo();
  }, [lines, autopause]);

  const toggle = React.useCallback(() => {
    if (!player.current) return;
    if (playing) player.current.pauseVideo();
    else player.current.playVideo();
  }, [playing]);

  React.useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest("input, textarea")) return;
      if (e.code === "Space") { e.preventDefault(); toggle(); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); seekLine(current - (ms - (line?.start ?? 0) > 1500 ? 0 : 1)); }
      else if (e.key === "ArrowRight") { e.preventDefault(); seekLine(current + 1); }
      else if (e.key === "r") seekLine(current);
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [toggle, seekLine, current, ms, line]);

  if (isLoading || !video) {
    return <div className="mx-auto max-w-3xl space-y-3 p-4"><Skeleton className="aspect-video" /><Skeleton className="h-32" /></div>;
  }

  const modes = [
    { value: "full" as Mode, label: lang === "ja" ? "漢字 + よみ + EN" : "Text + English" },
    ...(lang === "ja" ? [{ value: "kana" as Mode, label: "ひらがな" }] : []),
    { value: "text" as Mode, label: lang === "ja" ? "日本語のみ" : "Text only" },
  ];

  return (
    <div className="mx-auto flex min-h-dvh max-w-3xl flex-col">
      <header className="safe-top flex items-center gap-2 px-2 py-2 sm:px-4">
        <Button asChild variant="ghost" size="icon" aria-label="Back to Watch">
          <Link href="/watch"><ArrowLeft /></Link>
        </Button>
        <h1 className="min-w-0 flex-1 truncate font-bold">{video.title}</h1>
        {video.level && <Badge tone="primary">{video.level}</Badge>}
      </header>

      <div className="sticky top-0 z-10 sm:static">
        {video.file_url && (
          <FilePlayer src={video.file_url} poster={video.poster} startS={video.position_ms / 1000}
            fullscreen={fullscreen} onFullscreen={setFullscreen} onSeek={setMs}
            onReady={(p) => { player.current = p; setReady(true); }}
            onState={(s) => { setPlaying(s === PLAYING); if (s === ENDED) setEnded(true); }}
            overlay={(onPicture || fullscreen) && showing ? (
              <div lang={lang}>
                <p className="text-[17px] font-semibold leading-snug sm:text-[1.15em]">
                  <RubyText text={mode === "kana" && lang === "ja" ? (showing.kana ?? showing.text) : showing.text} lang={lang}
                    furigana={mode === "full" ? "always" : "never"} romaji="off" showRomaji={false}
                    onWordTap={fullscreen ? undefined : (w, el) => { player.current?.pauseVideo(); words.open(w, el, stripRuby(showing.text)); }} />
                </p>
                {mode === "full" && showing.en && <p className="text-[13px] text-white/80 sm:text-[0.7em]">{showing.en}</p>}
              </div>
            ) : null} />
        )}
        {video.youtube_id && (
          <YouTubePlayer youtubeId={video.youtube_id} startS={video.position_ms / 1000}
            onReady={(p) => { player.current = p; setReady(true); }}
            onState={(s) => { setPlaying(s === PLAYING); if (s === ENDED) setEnded(true); }} />
        )}
      </div>

      <main className="flex-1 space-y-4 px-3 pb-10 pt-3 sm:px-4">
        {video.status !== "ready" && video.status !== "failed" && (
          <p className="flex items-center gap-2 rounded-xl bg-muted px-3 py-2 text-sm text-muted-foreground">
            <LoaderCircle className="size-4 animate-spin text-primary" /> Preparing subtitles — {video.progress}%.
            You can start watching; readings and English fill in as they&apos;re ready.
          </p>
        )}

        <Card className="space-y-3 p-4">
          <Segmented ariaLabel="Subtitle level" className="w-full" value={mode}
            onChange={(v) => update.mutate({ video_subtitles: v })} options={modes} />
          <div className="flex min-h-28 items-center" aria-live="polite">
            {showing ? (
              <LineText line={showing} mode={mode} lang={lang} big
                onWordTap={(w, el) => { player.current?.pauseVideo(); words.open(w, el, stripRuby(showing.text)); }} />
            ) : (
              <p className="text-muted-foreground">{ms === 0 ? "Press play — subtitles appear here. Tap any word to look it up." : "…"}</p>
            )}
          </div>
          <div className="flex items-center justify-between gap-1">
            <Button variant="ghost" size="icon-lg" aria-label="Previous line" disabled={!ready} onClick={() => seekLine(current - 1)}><SkipBack /></Button>
            <Button variant="ghost" size="icon-lg" aria-label="Repeat this line" disabled={!ready || current < 0} onClick={() => seekLine(current)}><Repeat /></Button>
            <Button size="icon-lg" className="size-14 rounded-full" aria-label={playing ? "Pause" : "Play"} disabled={!ready} onClick={toggle}>
              {playing ? <Pause className="fill-current" /> : <Play className="fill-current" />}
            </Button>
            <Button variant="ghost" size="icon-lg" aria-label="Next line" disabled={!ready} onClick={() => seekLine(current + 1)}><SkipForward /></Button>
            <Button variant={slow ? "soft" : "ghost"} size="icon-lg" aria-label="Slower" aria-pressed={slow} disabled={!ready}
              onClick={() => { player.current?.setPlaybackRate(slow ? 1 : 0.75); setSlow(!slow); }}>
              <span className="text-sm font-bold">{slow ? "0.75×" : "1×"}</span>
            </Button>
          </div>
          <label className="flex items-center justify-between gap-3 border-t pt-3 text-sm">
            <span>
              <span className="block font-semibold">Pause after each line</span>
              <span className="block text-xs text-muted-foreground">Time to read it, or say it back.</span>
            </span>
            <Switch checked={autopause} onCheckedChange={(c) => update.mutate({ video_autopause: c })} />
          </label>
          {video.file_url && (
            <label className="flex items-center justify-between gap-3 border-t pt-3 text-sm">
              <span>
                <span className="block font-semibold">Subtitles on the video</span>
                <span className="block text-xs text-muted-foreground">Full screen always shows them.</span>
              </span>
              <Switch checked={onPicture} onCheckedChange={pictureSubs} />
            </label>
          )}
        </Card>

        {ended && <p className="text-center text-sm font-semibold text-primary-strong">Finished! Pick the words you want to keep below.</p>}

        <Card className="overflow-hidden">
          <h2 className="border-b px-4 py-3 font-bold">Transcript</h2>
          <div ref={transcript} className="relative max-h-[45vh] overflow-y-auto"
            onWheel={() => (userScrolledAt.current = Date.now())} onTouchMove={() => (userScrolledAt.current = Date.now())}>
            {lines.map((l) => (
              <button key={l.i} type="button" data-i={l.i} onClick={() => seekLine(l.i)}
                className={cn("block w-full border-b px-4 py-2.5 text-left transition last:border-0 hover:bg-muted/50",
                  l.i === current && "bg-primary-soft")}>
                <span className="mb-0.5 block text-[11px] tabular-nums text-muted-foreground">
                  {Math.floor(l.start / 60000)}:{String(Math.floor((l.start / 1000) % 60)).padStart(2, "0")}
                </span>
                <LineText line={l} mode={mode} lang={lang} />
              </button>
            ))}
          </div>
        </Card>

        {video.status === "ready" && <VideoWords videoId={video.id} lines={lines} lang={lang} />}
        {video.duration_s ? <Progress value={Math.min(1, ms / 1000 / video.duration_s)} className="h-1" /> : null}
      </main>
      <WordPopover target={words.target} lang={lang} onClose={words.close} />
    </div>
  );
}
