"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clapperboard, FileText, FileVideo, LoaderCircle, Plus, RefreshCw, Smartphone, Trash, TriangleAlert, Upload } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/overlay";
import { Badge, Card, EmptyState, Input, Label, Progress, Segmented, Skeleton } from "@/components/ui/primitives";
import { useVideos } from "@/hooks/queries";
import { useActiveLang } from "@/hooks/use-language";
import { api, ApiError, del, errorMessage, get, post } from "@/lib/api";
import { LANGS } from "@/lib/languages";
import type { Lang, Video } from "@/lib/types";
import { cn, formatDuration } from "@/lib/utils";

type Preview = { youtube_id: string; thumbnail: string; title: string; author: string };
type Limits = {
  can_upload: boolean; max_file_bytes: number; max_minutes: number; quota_bytes: number; used_bytes: number; chunk_bytes: number;
};

const gb = (bytes: number) => bytes < 1024 ** 3
  ? `${Math.max(bytes ? 1 : 0, Math.round(bytes / 1024 ** 2))} MB`
  : `${(bytes / 1024 ** 3).toFixed(bytes < 10 * 1024 ** 3 ? 1 : 0)} GB`;
const ACCEPT = ".mp4,.m4v,.mov,.webm,.mkv,video/mp4,video/webm,video/x-matroska,video/quicktime";
const RESUME_KEY = "parlo.upload";

function FilePick({ id, file, onPick, accept, placeholder, icon: Icon }: {
  id: string; file: File | null; onPick: (f: File | null) => void; accept: string; placeholder: string;
  icon: typeof FileText;
}) {
  return (
    <>
      <label htmlFor={id} className={cn(
        "flex h-12 cursor-pointer items-center gap-2.5 rounded-xl border border-dashed px-3.5 text-sm transition hover:bg-muted",
        file && "border-solid border-primary bg-primary-soft",
      )}>
        <Icon className="size-4 shrink-0 text-muted-foreground" />
        <span className="min-w-0 truncate">{file ? file.name : placeholder}</span>
      </label>
      <input id={id} type="file" accept={accept} className="sr-only" onChange={(e) => onPick(e.target.files?.[0] ?? null)} />
    </>
  );
}

/** Paste a YouTube link + attach its subtitle file. */
function YouTubeForm({ lang, initialUrl, onDone }: { lang: Lang; initialUrl: string; onDone: (v: Video) => void }) {
  const qc = useQueryClient();
  const [url, setUrl] = React.useState(initialUrl);
  const [file, setFile] = React.useState<File | null>(null);
  const [preview, setPreview] = React.useState<Preview | null>(null);
  const [previewError, setPreviewError] = React.useState<string | null>(null);

  React.useEffect(() => setUrl(initialUrl), [initialUrl]);
  React.useEffect(() => {
    setPreview(null);
    setPreviewError(null);
    if (!url.trim()) return;
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      get<Preview>(`/videos/preview?url=${encodeURIComponent(url.trim())}`, ctrl.signal)
        .then(setPreview)
        .catch((e) => (e as Error).name !== "AbortError" && setPreviewError(errorMessage(e)));
    }, 400);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [url]);

  const add = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.set("url", url.trim());
      form.set("lang", lang);
      form.set("subtitles", file!);
      return api<Video>("/videos/youtube", { form });
    },
    onSuccess: (v) => {
      toast.success("Added — preparing the subtitles now");
      void qc.invalidateQueries({ queryKey: ["videos"] });
      onDone(v);
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (preview && file) add.mutate(); }}>
      <div className="space-y-1.5">
        <Label htmlFor="yt-url">YouTube link</Label>
        <Input id="yt-url" inputMode="url" placeholder="https://youtu.be/…" value={url} onChange={(e) => setUrl(e.target.value)} />
        {previewError && <p className="text-sm text-danger">{previewError}</p>}
      </div>
      {preview && (
        <div className="flex gap-3 rounded-2xl border p-2.5">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={preview.thumbnail} alt="" className="aspect-video w-28 shrink-0 rounded-lg object-cover" />
          <div className="min-w-0 py-0.5">
            <p className="line-clamp-2 text-sm font-semibold">{preview.title || "YouTube video"}</p>
            {preview.author && <p className="truncate text-xs text-muted-foreground">{preview.author}</p>}
          </div>
        </div>
      )}
      <div className="space-y-1.5">
        <Label htmlFor="subs">Subtitle file (.srt, .vtt or .ass)</Label>
        <FilePick id="subs" file={file} onPick={setFile} accept=".srt,.vtt,.ass,.ssa,text/vtt" icon={FileText}
          placeholder="Choose the video's subtitle file" />
        <p className="text-xs text-muted-foreground">
          Use subtitles in {LANGS[lang].name}, ideally made by the creator. Parlo can&apos;t download subtitles or audio from YouTube itself.
        </p>
      </div>
      <Button type="submit" size="lg" className="w-full" disabled={!preview || !file} loading={add.isPending}>
        <Plus /> Add video
      </Button>
    </form>
  );
}

/** Length of a local video file, if the browser can read it (it can't for some .mkv files). */
function localDuration(file: File): Promise<number | null> {
  return new Promise((resolve) => {
    const el = document.createElement("video");
    const url = URL.createObjectURL(file);
    const done = (v: number | null) => { URL.revokeObjectURL(url); resolve(v); };
    el.preload = "metadata";
    el.onloadedmetadata = () => done(Number.isFinite(el.duration) ? el.duration : null);
    el.onerror = () => done(null);
    setTimeout(() => done(null), 5000);
    el.src = url;
  });
}

function readResume(file: File): number | null {
  try {
    const r = JSON.parse(localStorage.getItem(RESUME_KEY) ?? "null");
    return r && r.name === file.name && r.size === file.size && r.modified === file.lastModified ? r.id : null;
  } catch {
    return null;
  }
}

function writeResume(file: File | null, id?: number) {
  try {
    if (file && id) localStorage.setItem(RESUME_KEY, JSON.stringify({ name: file.name, size: file.size, modified: file.lastModified, id }));
    else localStorage.removeItem(RESUME_KEY);
  } catch {
    /* private mode: no resume */
  }
}

/** Upload your own video file in small pieces (resumable), optionally with subtitles. */
function FileForm({ lang, limits, onDone }: { lang: Lang; limits: Limits; onDone: (v: Video) => void }) {
  const qc = useQueryClient();
  const [file, setFile] = React.useState<File | null>(null);
  const [subs, setSubs] = React.useState<File | null>(null);
  const [title, setTitle] = React.useState("");
  const [problem, setProblem] = React.useState<string | null>(null);
  const [progress, setProgress] = React.useState<number | null>(null);
  const cancelled = React.useRef(false);
  const left = limits.quota_bytes - limits.used_bytes;

  const pick = async (f: File | null) => {
    setFile(f);
    setProblem(null);
    if (!f) return;
    if (!title) setTitle(f.name.replace(/\.[^.]+$/, ""));
    if (f.size > limits.max_file_bytes) return setProblem(`That file is ${gb(f.size)} — the limit is ${gb(limits.max_file_bytes)} per file.`);
    if (f.size > left) return setProblem(`Only ${gb(Math.max(0, left))} left in the library — delete a video first.`);
    const seconds = await localDuration(f);
    if (seconds && seconds > limits.max_minutes * 60) {
      setProblem(`That video is ${Math.round(seconds / 60)} minutes — the limit is ${limits.max_minutes}.`);
    }
  };

  const upload = async () => {
    if (!file) return;
    cancelled.current = false;
    setProgress(0);
    try {
      let id = readResume(file);
      let received = new Set<number>();
      let chunks = Math.ceil(file.size / limits.chunk_bytes);
      if (id) {
        try {
          const s = await get<{ chunks: number; received: number[] }>(`/videos/uploads/${id}`);
          received = new Set(s.received);
          chunks = s.chunks;
        } catch {
          id = null; // expired or finished: start again
        }
      }
      if (!id) {
        const r = await post<{ id: number; chunks: number }>("/videos/uploads", { name: file.name, size: file.size, lang, title: title.trim() || null });
        id = r.id;
        chunks = r.chunks;
        writeResume(file, id);
      }
      if (subs) {
        const form = new FormData();
        form.set("subtitles", subs);
        await api(`/videos/uploads/${id}/subtitles`, { form });
      }
      for (let n = 0; n < chunks; n++) {
        if (cancelled.current) throw new Error("Upload paused — choose the same file again to carry on.");
        if (!received.has(n)) {
          const piece = file.slice(n * limits.chunk_bytes, Math.min(file.size, (n + 1) * limits.chunk_bytes));
          for (let attempt = 0; ; attempt++) {
            try {
              await api(`/videos/uploads/${id}/${n}`, { method: "PUT", blob: piece });
              break;
            } catch (e) {
              if (attempt >= 3 || (e instanceof ApiError && e.status >= 400 && e.status < 500)) throw e;
              await new Promise((r) => setTimeout(r, 1500 * (attempt + 1)));
            }
          }
        }
        setProgress((n + 1) / chunks);
      }
      const video = await post<Video>(`/videos/uploads/${id}/finish`);
      writeResume(null);
      toast.success("Uploaded — Parlo is preparing it now");
      void qc.invalidateQueries({ queryKey: ["videos"] });
      onDone(video);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setProgress(null);
    }
  };

  if (!limits.can_upload) {
    return <p className="rounded-xl bg-muted p-4 text-sm text-muted-foreground">Only admins can upload video files on this server. YouTube links work for everyone.</p>;
  }
  const busy = progress !== null;
  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (file && !problem) void upload(); }}>
      <div className="space-y-1.5">
        <Label htmlFor="video-file">Video file (.mp4, .webm or .mkv)</Label>
        <FilePick id="video-file" file={file} onPick={(f) => void pick(f)} accept={ACCEPT} icon={FileVideo}
          placeholder={`Choose a video — up to ${gb(limits.max_file_bytes)}, ${limits.max_minutes} min`} />
        {problem && <p className="text-sm text-danger">{problem}</p>}
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="video-title">Title</Label>
        <Input id="video-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Shirokuma Café, episode 1" />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="file-subs">Subtitles (optional)</Label>
        <FilePick id="file-subs" file={subs} onPick={setSubs} accept=".srt,.vtt,.ass,.ssa,text/vtt" icon={FileText}
          placeholder="Add a subtitle file, or leave empty" />
        <p className="text-xs text-muted-foreground">
          Without one, Parlo uses a {LANGS[lang].name} subtitle track inside the file, or listens to the audio and writes them.
        </p>
      </div>
      {busy ? (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="font-semibold">Uploading…</span>
            <span className="tabular-nums text-muted-foreground">{Math.round((progress ?? 0) * 100)}%</span>
          </div>
          <Progress value={progress ?? 0} />
          <Button type="button" variant="outline" className="w-full" onClick={() => (cancelled.current = true)}>Pause</Button>
        </div>
      ) : (
        <Button type="submit" size="lg" className="w-full" disabled={!file || !!problem}>
          <Upload /> Upload
        </Button>
      )}
      <p className="text-xs text-muted-foreground">
        {gb(limits.used_bytes)} of {gb(limits.quota_bytes)} used · Only upload videos you have the right to use.
        Big files are quicker from a computer than over mobile data.
      </p>
    </form>
  );
}

function AddVideo({ lang, open, onOpenChange, initialUrl }: {
  lang: Lang; open: boolean; onOpenChange: (o: boolean) => void; initialUrl: string;
}) {
  const router = useRouter();
  const [tab, setTab] = React.useState<"youtube" | "file">("youtube");
  const { data: limits } = useQuery({ queryKey: ["video-limits"], queryFn: () => get<Limits>("/videos/limits"), enabled: open });
  const done = (v: Video) => {
    onOpenChange(false);
    router.replace("/watch");
    if (v.status !== "uploading" && v.source === "youtube") router.push(`/watch/${v.id}`);
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent side="bottom" title="Add a video" description={`A ${LANGS[lang].name} video to learn from.`}>
        <Segmented ariaLabel="Where from" className="mb-4 w-full" value={tab} onChange={setTab}
          options={[{ value: "youtube", label: "YouTube link" }, { value: "file", label: "Upload a file" }]} />
        {tab === "youtube" ? (
          <YouTubeForm lang={lang} initialUrl={initialUrl} onDone={done} />
        ) : limits ? (
          <FileForm lang={lang} limits={limits} onDone={done} />
        ) : (
          <Skeleton className="h-64" />
        )}
      </DialogContent>
    </Dialog>
  );
}

const STAGE: Record<string, string> = {
  uploading: "Uploading", repackaging: "Getting it ready to play", subtitles: "Reading the subtitles",
  transcribing: "Listening and writing subtitles",
};

function VideoCard({ video }: { video: Video }) {
  const qc = useQueryClient();
  const retry = useMutation({
    mutationFn: () => post(`/videos/${video.id}/retry`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["videos"] }),
  });
  const remove = useMutation({
    mutationFn: () => del(`/videos/${video.id}`),
    onSuccess: () => { toast.success("Video removed"); void qc.invalidateQueries({ queryKey: ["videos"] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const ready = video.status === "ready";
  const watched = video.duration_s ? Math.min(1, video.position_ms / 1000 / video.duration_s) : 0;
  const stage = video.stage ? STAGE[video.stage] : "Preparing subtitles";
  const showProgress = !video.stage || video.stage === "transcribing";
  const body = (
    <>
      <div className="relative aspect-video overflow-hidden rounded-xl bg-muted">
        {video.thumbnail ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={video.thumbnail} alt="" className={cn("size-full object-cover", !ready && "opacity-50")} loading="lazy" />
        ) : (
          <FileVideo className="absolute inset-0 m-auto size-10 text-muted-foreground" />
        )}
        {video.duration_s != null && (
          <span className="absolute bottom-1.5 right-1.5 rounded-md bg-black/75 px-1.5 py-0.5 text-xs font-semibold text-white tabular-nums">
            {formatDuration(video.duration_s)}
          </span>
        )}
        {watched > 0.02 && <Progress value={watched} className="absolute inset-x-0 bottom-0 h-1 rounded-none bg-black/30" />}
      </div>
      <div className="mt-2.5 flex items-start gap-2">
        <p className="line-clamp-2 min-w-0 flex-1 font-semibold leading-snug">{video.title}</p>
        {video.level && <Badge tone="primary" className="shrink-0">{video.level}</Badge>}
      </div>
    </>
  );
  return (
    <Card className="p-2.5">
      {ready ? <Link href={`/watch/${video.id}`} className="block">{body}</Link> : body}
      <div className="mt-2 flex items-center gap-2 text-sm text-muted-foreground">
        {video.status === "failed" ? (
          <>
            <TriangleAlert className="size-4 shrink-0 text-danger" />
            <span className="min-w-0 flex-1 text-danger">{video.error ?? "Couldn't prepare this video"}</span>
            {/* a refused file isn't kept (size 0), so only a fixed re-upload helps */}
            {(video.source !== "file" || video.size_bytes > 0) && (
              <Button size="sm" variant="outline" loading={retry.isPending} onClick={() => retry.mutate()}><RefreshCw /> Retry</Button>
            )}
          </>
        ) : !ready ? (
          <>
            <LoaderCircle className="size-4 shrink-0 animate-spin text-primary" />
            <span className="min-w-0 truncate">{stage}</span>
            {showProgress && (
              <>
                <Progress value={video.progress / 100} className="h-1.5 min-w-10 flex-1" />
                <span className="tabular-nums">{video.progress}%</span>
              </>
            )}
            {!showProgress && <span className="flex-1" />}
          </>
        ) : (
          <span className="min-w-0 flex-1">
            {video.line_count} lines
            {video.subtitle_source === "transcribed" && " · subtitles written by AI"}
            {video.source === "file" && video.size_bytes > 0 && ` · ${gb(video.size_bytes)}`}
          </span>
        )}
        {video.can_delete && (
          <Button size="icon-sm" variant="ghost" className="size-10 shrink-0 sm:size-8" aria-label={`Remove ${video.title}`}
            onClick={() => confirm(`Remove “${video.title}” from the library?`) && remove.mutate()}>
            <Trash />
          </Button>
        )}
      </div>
    </Card>
  );
}

function Library() {
  const lang = useActiveLang();
  const params = useSearchParams();
  // Shared from the YouTube app (web share target): the link is in url or text
  const shared = params.get("share_url") || params.get("share_text") || "";
  const [adding, setAdding] = React.useState(!!shared);
  const { data: videos, isLoading } = useVideos(lang);

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight sm:text-3xl">Watch</h1>
          <p className="mt-1 text-muted-foreground">Real {LANGS[lang].name} videos with subtitles at your level.</p>
        </div>
        <div className="flex shrink-0 flex-col gap-2 sm:flex-row">
          <Button onClick={() => setAdding(true)}><Plus /> Add video</Button>
          {!!videos?.some((v) => v.status === "ready") && (
            <Button asChild variant="outline"><Link href="/watch/reels"><Smartphone /> Reels</Link></Button>
          )}
        </div>
      </div>

      {isLoading || !videos ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <Skeleton className="aspect-video" />
          <Skeleton className="aspect-video" />
        </div>
      ) : !videos.length ? (
        <EmptyState icon={<Clapperboard />} title="Learn from real videos">
          <ol className="mx-auto mt-2 max-w-sm list-decimal space-y-1 pl-5 text-left">
            <li>Find a {LANGS[lang].name} video on YouTube — a kids&apos; show, a vlog, a cooking video.</li>
            <li>Get its {LANGS[lang].name} subtitle file (.srt or .vtt).</li>
            <li>Tap <b>Add video</b>, paste the link and attach the file — or upload a video file you own.</li>
          </ol>
        </EmptyState>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {videos.map((v) => <VideoCard key={v.id} video={v} />)}
        </div>
      )}

      <AddVideo lang={lang} open={adding} onOpenChange={setAdding} initialUrl={shared} />
    </div>
  );
}

export default function WatchPage() {
  return (
    <React.Suspense>
      <Library />
    </React.Suspense>
  );
}
