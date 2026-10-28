"use client";

import * as React from "react";

export type Recording = { blob: Blob; mime: string; durationMs: number };
export type RecorderState = "idle" | "requesting" | "recording" | "denied" | "unsupported" | "error";

function pickMime(): string {
  if (typeof MediaRecorder === "undefined") return "";
  for (const m of ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"]) {
    if (MediaRecorder.isTypeSupported(m)) return m;
  }
  return "";
}

/** Push-to-talk recorder: MediaRecorder + an AnalyserNode for the live waveform.
 *  The mic is opened only while recording and released immediately after. */
export function useRecorder(onFinish: (r: Recording | null) => void, maxSeconds = 60) {
  const [state, setState] = React.useState<RecorderState>("idle");
  const [elapsed, setElapsed] = React.useState(0);
  const [error, setError] = React.useState<string | null>(null);
  const levels = React.useRef<Uint8Array | null>(null);
  const analyser = React.useRef<AnalyserNode | null>(null);
  const recorder = React.useRef<MediaRecorder | null>(null);
  const stream = React.useRef<MediaStream | null>(null);
  const ctx = React.useRef<AudioContext | null>(null);
  const chunks = React.useRef<Blob[]>([]);
  const started = React.useRef(0);
  const timer = React.useRef<number | null>(null);
  const finish = React.useRef(onFinish);
  finish.current = onFinish;
  const cancelled = React.useRef(false);
  const pendingStop = React.useRef(false);

  const cleanup = React.useCallback(() => {
    if (timer.current) window.clearInterval(timer.current);
    timer.current = null;
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    void ctx.current?.close().catch(() => {});
    ctx.current = null;
    analyser.current = null;
  }, []);

  React.useEffect(() => cleanup, [cleanup]);

  const start = React.useCallback(async () => {
    if (recorder.current?.state === "recording") return;
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setState("unsupported");
      setError("Recording isn't supported in this browser.");
      return;
    }
    if (!window.isSecureContext) {
      setState("unsupported");
      setError("The microphone only works over HTTPS.");
      return;
    }
    setError(null);
    pendingStop.current = false;
    setState("requesting");
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      stream.current = s;
      const mime = pickMime();
      const rec = new MediaRecorder(s, mime ? { mimeType: mime } : undefined);
      chunks.current = [];
      cancelled.current = false;
      rec.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
      rec.onstop = () => {
        const durationMs = Date.now() - started.current;
        const type = rec.mimeType || mime || "audio/webm";
        const blob = new Blob(chunks.current, { type });
        cleanup();
        setState("idle");
        setElapsed(0);
        const result = cancelled.current || durationMs < 400 || blob.size < 500 ? null : { blob, mime: type, durationMs };
        finish.current(result);
      };
      // live levels for the waveform
      const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const ac = new AC();
      const src = ac.createMediaStreamSource(s);
      const an = ac.createAnalyser();
      an.fftSize = 256;
      src.connect(an);
      ctx.current = ac;
      analyser.current = an;
      levels.current = new Uint8Array(an.frequencyBinCount);

      recorder.current = rec;
      started.current = Date.now();
      rec.start(250);
      setState("recording");
      if (pendingStop.current) {
        // released before the mic opened: treat as a cancelled tap
        cancelled.current = true;
        rec.stop();
        return;
      }
      timer.current = window.setInterval(() => {
        const secs = (Date.now() - started.current) / 1000;
        setElapsed(secs);
        if (secs >= maxSeconds) rec.stop();
      }, 100);
    } catch (e) {
      cleanup();
      const name = (e as Error).name;
      if (name === "NotAllowedError" || name === "SecurityError") {
        setState("denied");
        setError("Microphone access is blocked. Allow it in your browser's site settings, then try again.");
      } else if (name === "NotFoundError") {
        setState("error");
        setError("No microphone found.");
      } else {
        setState("error");
        setError("Couldn't start recording.");
      }
    }
  }, [cleanup, maxSeconds]);

  /** Stop; onFinish receives the recording (null if cancelled or too short). */
  const stop = React.useCallback(() => {
    if (recorder.current?.state === "recording") recorder.current.stop();
    else pendingStop.current = true;
  }, []);

  const cancel = React.useCallback(() => {
    cancelled.current = true;
    pendingStop.current = true;
    if (recorder.current?.state === "recording") recorder.current.stop();
  }, []);

  const readLevels = React.useCallback(() => {
    if (!analyser.current || !levels.current) return null;
    analyser.current.getByteTimeDomainData(levels.current as Uint8Array<ArrayBuffer>);
    return levels.current;
  }, []);

  return { state, elapsed, error, start, stop, cancel, readLevels, recording: state === "recording" };
}
