/** Audio: TTS URL resolution (cached per session), one shared player, and an
 *  ordered queue for sentence-by-sentence conversation audio. */

import { api } from "./api";
import type { Lang } from "./types";

type TtsOpts = { speed?: number; purpose?: "lesson" | "conversation"; gender?: string };

const urlCache = new Map<string, Promise<string>>();

export function ttsUrl(text: string, lang: Lang, opts: TtsOpts = {}): Promise<string> {
  const speed = opts.speed ?? 1;
  const key = `${lang}|${speed}|${opts.purpose ?? "lesson"}|${opts.gender ?? ""}|${text}`;
  let p = urlCache.get(key);
  if (!p) {
    p = api<{ url: string }>("/tts", {
      method: "POST",
      body: { text, lang, speed, purpose: opts.purpose ?? "lesson", gender: opts.gender ?? "female" },
    }).then((r) => r.url);
    p.catch(() => urlCache.delete(key));
    urlCache.set(key, p);
  }
  return p;
}

type Listener = (playingId: string | null) => void;

class Player {
  private el: HTMLAudioElement | null = null;
  private listeners = new Set<Listener>();
  playingId: string | null = null;

  private audio() {
    if (!this.el) {
      this.el = new Audio();
      this.el.preload = "auto";
      this.el.addEventListener("ended", () => this.set(null));
      this.el.addEventListener("pause", () => this.set(null));
      this.el.addEventListener("error", () => this.set(null));
    }
    return this.el;
  }

  private set(id: string | null) {
    this.playingId = id;
    this.listeners.forEach((l) => l(id));
  }

  subscribe(l: Listener) {
    this.listeners.add(l);
    return () => {
      this.listeners.delete(l);
    };
  }

  async play(url: string, id = url, rate = 1): Promise<void> {
    const a = this.audio();
    a.pause();
    a.src = url;
    a.playbackRate = rate;
    this.set(id);
    return new Promise((resolve) => {
      const done = () => {
        a.removeEventListener("ended", done);
        a.removeEventListener("error", done);
        resolve();
      };
      a.addEventListener("ended", done);
      a.addEventListener("error", done);
      a.play().catch(() => {
        this.set(null);
        resolve();
      });
    });
  }

  stop() {
    this.el?.pause();
    this.set(null);
  }
}

export const player = typeof window !== "undefined" ? new Player() : (null as unknown as Player);

/** Plays clips strictly in index order as they arrive (streamed AI replies). */
export class AudioQueue {
  private clips = new Map<number, string>();
  private next = 0;
  private playing = false;
  private stopped = false;
  constructor(private id: string, private rate = 1) {}

  add(index: number, url: string) {
    this.clips.set(index, url);
    void this.pump();
  }

  stop() {
    this.stopped = true;
    player.stop();
  }

  private async pump() {
    if (this.playing || this.stopped) return;
    while (this.clips.has(this.next) && !this.stopped) {
      this.playing = true;
      const url = this.clips.get(this.next)!;
      this.next++;
      await player.play(url, this.id, this.rate);
    }
    this.playing = false;
  }
}

export async function playSequence(urls: string[], id: string, rate = 1) {
  for (const url of urls) {
    if (player.playingId && player.playingId !== id) return;
    await player.play(url, id, rate);
  }
}
