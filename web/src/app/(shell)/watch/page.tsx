"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Clapperboard, FileText, LoaderCircle, Plus, RefreshCw, Trash, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/overlay";
import { Badge, Card, EmptyState, Input, Label, Progress, Skeleton } from "@/components/ui/primitives";
import { useVideos } from "@/hooks/queries";
import { useActiveLang } from "@/hooks/use-language";
import { api, del, errorMessage, get, post } from "@/lib/api";
import { LANGS } from "@/lib/languages";
import type { Lang, Video } from "@/lib/types";
import { cn, formatDuration } from "@/lib/utils";

type Preview = { youtube_id: string; thumbnail: string; title: string; author: string };

/** Paste a YouTube link + attach its subtitle file. */
function AddVideo({ lang, open, onOpenChange, initialUrl }: {
  lang: Lang; open: boolean; onOpenChange: (o: boolean) => void; initialUrl: string;
}) {
  const qc = useQueryClient();
  const router = useRouter();
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
      onOpenChange(false);
      setUrl("");
      setFile(null);
      router.replace("/watch");
      router.push(`/watch/${v.id}`);
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent side="bottom" title="Add a YouTube video" description={`A ${LANGS[lang].name} video plus its ${LANGS[lang].name} subtitle file.`}>
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (preview && file) add.mutate(); }}>
          <div className="space-y-1.5">
            <Label htmlFor="yt-url">YouTube link</Label>
            <Input id="yt-url" inputMode="url" placeholder="https://youtu.be/…" value={url} onChange={(e) => setUrl(e.target.value)} autoFocus={!initialUrl} />
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
            <label
              htmlFor="subs"
              className={cn(
                "flex h-12 cursor-pointer items-center gap-2.5 rounded-xl border border-dashed px-3.5 text-sm transition hover:bg-muted",
                file && "border-solid border-primary bg-primary-soft",
              )}
            >
              <FileText className="size-4 shrink-0 text-muted-foreground" />
              <span className="min-w-0 truncate">{file ? file.name : "Choose the video's subtitle file"}</span>
            </label>
            <input id="subs" type="file" accept=".srt,.vtt,.ass,.ssa,text/vtt" className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <p className="text-xs text-muted-foreground">
              Use subtitles in {LANGS[lang].name}, ideally made by the creator. Parlo can&apos;t download subtitles or audio from YouTube itself.
            </p>
          </div>
          <Button type="submit" size="lg" className="w-full" disabled={!preview || !file} loading={add.isPending}>
            <Plus /> Add video
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

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
  const body = (
    <>
      <div className="relative aspect-video overflow-hidden rounded-xl bg-muted">
        {video.thumbnail && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={video.thumbnail} alt="" className={cn("size-full object-cover", !ready && "opacity-50")} loading="lazy" />
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
            <span className="min-w-0 flex-1 truncate text-danger" title={video.error ?? ""}>Couldn&apos;t prepare the subtitles</span>
            <Button size="sm" variant="outline" loading={retry.isPending} onClick={() => retry.mutate()}><RefreshCw /> Retry</Button>
          </>
        ) : !ready ? (
          <>
            <LoaderCircle className="size-4 shrink-0 animate-spin text-primary" />
            <span className="shrink-0">Preparing subtitles</span>
            <Progress value={video.progress / 100} className="h-1.5 flex-1" />
            <span className="tabular-nums">{video.progress}%</span>
          </>
        ) : (
          <span className="min-w-0 flex-1">{video.line_count} lines</span>
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
        <Button onClick={() => setAdding(true)} className="shrink-0"><Plus /> Add video</Button>
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
            <li>Tap <b>Add video</b>, paste the link and attach the file.</li>
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
