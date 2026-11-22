/** YouTube's official IFrame Player API, shared by the video page and reels. */

export type YTPlayer = {
  playVideo(): void;
  pauseVideo(): void;
  seekTo(seconds: number, allowSeekAhead: boolean): void;
  getCurrentTime(): number;
  setPlaybackRate(rate: number): void;
  destroy(): void;
  unloadModule?(name: string): void;
  mute?(): void;
  unMute?(): void;
  loadVideoById?(opts: { videoId: string; startSeconds?: number; endSeconds?: number }): void;
};
type YTNamespace = { Player: new (el: HTMLElement, opts: Record<string, unknown>) => YTPlayer };

declare global {
  interface Window {
    YT?: YTNamespace;
    onYouTubeIframeAPIReady?: () => void;
  }
}

export const PLAYING = 1;
export const ENDED = 0;

let ytApi: Promise<YTNamespace> | null = null;
/** YouTube's official IFrame Player API, loaded once. */
export function loadYouTube(): Promise<YTNamespace> {
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
