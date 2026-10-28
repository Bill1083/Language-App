"use client";

import { Mic, MicOff, Square, X } from "lucide-react";
import * as React from "react";

import { type Recording, useRecorder } from "@/hooks/use-recorder";
import { cn } from "@/lib/utils";

function Waveform({ read, active }: { read: () => Uint8Array | null; active: boolean }) {
  const ref = React.useRef<HTMLCanvasElement>(null);
  React.useEffect(() => {
    if (!active) return;
    let raf = 0;
    const history: number[] = [];
    const draw = () => {
      const canvas = ref.current;
      const data = read();
      if (canvas && data) {
        let peak = 0;
        for (const v of data) peak = Math.max(peak, Math.abs(v - 128));
        history.push(Math.min(1, peak / 64));
        if (history.length > 40) history.shift();
        const g = canvas.getContext("2d")!;
        const w = canvas.width;
        const h = canvas.height;
        g.clearRect(0, 0, w, h);
        g.fillStyle = getComputedStyle(canvas).color;
        const bar = w / 40;
        history.forEach((lvl, i) => {
          const bh = Math.max(3, lvl * h);
          g.globalAlpha = 0.35 + 0.65 * (i / history.length);
          g.beginPath();
          g.roundRect(i * bar + 1, (h - bh) / 2, bar - 2, bh, 2);
          g.fill();
        });
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [read, active]);
  return <canvas ref={ref} width={200} height={32} className="h-8 w-[200px] text-danger" aria-hidden />;
}

function formatSecs(s: number) {
  const whole = Math.floor(s);
  return `${Math.floor(whole / 60)}:${(whole % 60).toString().padStart(2, "0")}`;
}

type Props = {
  onRecorded: (r: Recording) => void;
  mode?: "hold" | "toggle";
  spaceToTalk?: boolean;
  disabled?: boolean;
  maxSeconds?: number;
  size?: "md" | "lg";
  hint?: string;
  className?: string;
};

/** Microphone button: permission handling, hold-to-talk or tap-to-toggle, space bar
 *  push-to-talk on desktop, a live waveform and timer, and clear error states. */
export function RecordButton({
  onRecorded,
  mode = "hold",
  spaceToTalk,
  disabled,
  maxSeconds = 60,
  size = "lg",
  hint,
  className,
}: Props) {
  const rec = useRecorder((r) => r && onRecorded(r), maxSeconds);
  const holding = React.useRef(false);

  React.useEffect(() => {
    if (!spaceToTalk || disabled) return;
    const typing = (el: EventTarget | null) =>
      el instanceof HTMLElement && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(el.tagName));
    const down = (e: KeyboardEvent) => {
      if (e.code !== "Space" || e.repeat || typing(e.target)) return;
      e.preventDefault();
      holding.current = true;
      void rec.start();
    };
    const up = (e: KeyboardEvent) => {
      if (e.code !== "Space" || !holding.current) return;
      e.preventDefault();
      holding.current = false;
      rec.stop();
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, [spaceToTalk, disabled, rec]);

  const pointer =
    mode === "hold"
      ? {
          onPointerDown: (e: React.PointerEvent) => {
            if (disabled || e.button !== 0) return;
            (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
            holding.current = true;
            void rec.start();
          },
          onPointerUp: () => {
            if (!holding.current) return;
            holding.current = false;
            rec.stop();
          },
          onPointerCancel: () => {
            holding.current = false;
            rec.cancel();
          },
          onKeyDown: (e: React.KeyboardEvent) => {
            if ((e.key === "Enter" || e.key === " ") && !e.repeat) {
              e.preventDefault();
              if (rec.recording) rec.stop();
              else void rec.start();
            }
          },
          onContextMenu: (e: React.MouseEvent) => e.preventDefault(),
        }
      : {
          onClick: () => (rec.recording ? rec.stop() : void rec.start()),
        };

  const big = size === "lg";
  const label = rec.recording ? "Stop recording and send" : mode === "hold" ? "Hold to record" : "Start recording";
  const blocked = rec.state === "denied" || rec.state === "unsupported";

  return (
    <div className={cn("flex flex-col items-center gap-2", className)}>
      <div className="flex items-center gap-3">
        {rec.recording && (
          <button
            type="button"
            onClick={rec.cancel}
            className="flex size-10 items-center justify-center rounded-full bg-muted text-muted-foreground transition hover:text-foreground"
            aria-label="Cancel recording"
          >
            <X className="size-5" />
          </button>
        )}
        <button
          type="button"
          disabled={disabled}
          aria-label={label}
          aria-pressed={rec.recording}
          className={cn(
            "relative flex touch-none select-none items-center justify-center rounded-full text-white transition active:scale-95 disabled:opacity-40",
            big ? "size-[72px] [&_svg]:size-8" : "size-12 [&_svg]:size-6",
            rec.recording
              ? "bg-danger shadow-[0_0_0_8px_color-mix(in_oklab,var(--danger)_22%,transparent)]"
              : blocked
                ? "bg-muted text-muted-foreground"
                : "bg-primary shadow-[0_4px_0_0_var(--lang-strong)] hover:brightness-105",
          )}
          {...pointer}
        >
          {rec.recording ? (mode === "toggle" ? <Square className="fill-current" /> : <Mic />) : blocked ? <MicOff /> : <Mic />}
          {rec.state === "requesting" && <span className="absolute inset-0 animate-ping rounded-full bg-primary/40" />}
        </button>
        {rec.recording && <span className="w-10" aria-hidden />}
      </div>
      <div className="flex h-9 items-center justify-center text-center text-xs text-muted-foreground" aria-live="polite">
        {rec.recording ? (
          <span className="flex items-center gap-3">
            <Waveform read={rec.readLevels} active={rec.recording} />
            <span className={cn("tabular-nums font-semibold", rec.elapsed > maxSeconds - 10 ? "text-danger" : "text-foreground")}>
              {formatSecs(rec.elapsed)}
            </span>
          </span>
        ) : rec.error ? (
          <span className="max-w-64 text-danger">{rec.error}</span>
        ) : (
          <span>
            {hint ?? (mode === "hold" ? "Hold to talk" : "Tap to talk")}
            {spaceToTalk && <span className="hidden sm:inline"> · or hold Space</span>}
          </span>
        )}
      </div>
    </div>
  );
}
