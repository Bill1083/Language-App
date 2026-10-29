"use client";

import * as React from "react";
import { toast } from "sonner";

import { AudioQueue } from "@/lib/audio";
import type { Feedback, PronunciationFlag, Turn } from "@/lib/types";

export type PendingTurn = {
  client_id: string; text: string; localAudio?: string; status: "sending" | "transcribing"; note?: string;
};
export type Streaming = { stream_id: string; text: string; status?: string } | null;
type Status = "connecting" | "open" | "reconnecting" | "closed";

/** Why the socket can't be used: shown instead of an endless "reconnecting". */
export type SocketFailure = { kind: "auth" | "origin" | "network"; message: string } | null;
export type StartError = { message: string; detail?: string } | null;

type ServerEvent =
  | { type: "pong" }
  | { type: "transcribing"; client_id?: string; message?: string }
  | { type: "user_turn"; client_id?: string; turn: Turn }
  | { type: "ai_start"; stream_id: string }
  | { type: "ai_status"; stream_id: string; message: string }
  | { type: "ai_delta"; stream_id: string; delta: string }
  | { type: "ai_audio"; stream_id: string; index: number; url: string }
  | { type: "ai_done"; stream_id: string; turn: Turn }
  | { type: "feedback"; turn_id: number; feedback: Feedback; pronunciation: PronunciationFlag[]; pronunciation_notes: string[] }
  | { type: "feedback_error"; turn_id: number; message: string }
  | { type: "goal"; achieved: boolean }
  | { type: "summary" }
  | { type: "error"; message: string; detail?: string; client_id?: string; retryable?: boolean };

/** No word from the server this long after the AI started its turn: give up
 *  waiting (the server itself tries two models for at most ~12 s each to start). */
const SILENT_REPLY_MS = 70_000;

const FAILURES: Record<number, SocketFailure> = {
  4401: { kind: "auth", message: "Your session has expired. Sign in again to continue this conversation." },
  4403: {
    kind: "origin",
    message:
      "The server refused the live connection because the page's address didn't match it. Check DOMAIN in .env and the WebSocket block in the Nginx site (see DEPLOYMENT.md).",
  },
};

/** WebSocket client for a conversation: streams AI replies token-by-token,
 *  plays reply audio sentence-by-sentence as it arrives, and merges feedback
 *  events (computed by the worker) into the transcript. Reconnects with backoff. */
export function useConversationSocket(
  id: number,
  initialTurns: Turn[] | undefined,
  opts: { voice: boolean; rate: number; onGoal: () => void },
) {
  const [turns, setTurns] = React.useState<Turn[]>(initialTurns ?? []);
  const [pending, setPending] = React.useState<PendingTurn[]>([]);
  const [streaming, setStreaming] = React.useState<Streaming>(null);
  const [status, setStatus] = React.useState<Status>("connecting");
  const [failure, setFailure] = React.useState<SocketFailure>(null);
  const [startError, setStartError] = React.useState<StartError>(null);
  const [feedbackErrors, setFeedbackErrors] = React.useState<Record<number, string>>({});
  const ws = React.useRef<WebSocket | null>(null);
  const queue = React.useRef<AudioQueue | null>(null);
  const optsRef = React.useRef(opts);
  optsRef.current = opts;
  const turnsRef = React.useRef(turns);
  turnsRef.current = turns;
  const closedByUs = React.useRef(false);
  const attempts = React.useRef(0);
  const everOpened = React.useRef(false);
  const started = React.useRef(false);
  const silence = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  React.useEffect(() => {
    if (initialTurns) setTurns(initialTurns);
  }, [initialTurns]);

  const stopWaiting = React.useCallback(() => {
    if (silence.current) clearTimeout(silence.current);
    silence.current = null;
  }, []);

  /** (Re)start the clock on a reply that hasn't produced any text yet. */
  const waitForReply = React.useCallback(() => {
    stopWaiting();
    silence.current = setTimeout(() => {
      silence.current = null;
      setStreaming(null);
      const message = "The AI didn't answer in time.";
      const detail = "No reply after a minute — the AI service may be overloaded. Try again in a moment.";
      if (turnsRef.current.length === 0) setStartError({ message, detail });
      else toast.error(message, { description: detail });
    }, SILENT_REPLY_MS);
  }, [stopWaiting]);

  React.useEffect(() => stopWaiting, [stopWaiting]);

  const handle = React.useCallback((ev: ServerEvent) => {
    switch (ev.type) {
      case "transcribing":
        setPending((p) =>
          p.map((x) => (x.client_id === ev.client_id ? { ...x, status: "transcribing", note: ev.message ?? x.note } : x)),
        );
        break;
      case "user_turn":
        setPending((p) => p.filter((x) => x.client_id !== ev.client_id));
        setTurns((t) => (t.some((x) => x.id === ev.turn.id) ? t : [...t, ev.turn]));
        break;
      case "ai_start":
        setStartError(null);
        queue.current?.stop();
        queue.current = optsRef.current.voice ? new AudioQueue(`stream-${ev.stream_id}`, 1) : null;
        setStreaming({ stream_id: ev.stream_id, text: "" });
        waitForReply();
        break;
      case "ai_status":
        setStreaming((s) => (s && s.stream_id === ev.stream_id ? { ...s, status: ev.message } : s));
        waitForReply();
        break;
      case "ai_delta":
        stopWaiting();
        setStreaming((s) => (s && s.stream_id === ev.stream_id ? { ...s, text: s.text + ev.delta, status: undefined } : s));
        break;
      case "ai_audio":
        queue.current?.add(ev.index, ev.url);
        break;
      case "ai_done":
        stopWaiting();
        setStartError(null);
        setStreaming(null);
        setTurns((t) => (t.some((x) => x.id === ev.turn.id) ? t : [...t, ev.turn]));
        break;
      case "feedback":
        setTurns((t) =>
          t.map((x) =>
            x.id === ev.turn_id
              ? { ...x, feedback: ev.feedback, score: ev.feedback.score, pronunciation: ev.pronunciation, pronunciation_notes: ev.pronunciation_notes }
              : x,
          ),
        );
        break;
      case "feedback_error":
        setFeedbackErrors((f) => ({ ...f, [ev.turn_id]: ev.message }));
        break;
      case "goal":
        if (ev.achieved) optsRef.current.onGoal();
        break;
      case "error":
        stopWaiting();
        setStreaming(null);
        if (ev.client_id) setPending((p) => p.filter((x) => x.client_id !== ev.client_id));
        if (turnsRef.current.length === 0) setStartError({ message: ev.message, detail: ev.detail });
        else toast.error(ev.message, { description: ev.detail });
        break;
    }
  }, [waitForReply, stopWaiting]);

  const connect = React.useCallback(() => {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const sock = new WebSocket(`${proto}://${window.location.host}/api/v1/conversations/${id}/ws`);
    ws.current = sock;
    sock.onopen = () => {
      attempts.current = 0;
      everOpened.current = true;
      setFailure(null);
      setStatus("open");
      if (!started.current && turnsRef.current.length === 0) {
        started.current = true;
        sock.send(JSON.stringify({ type: "start" }));
      }
    };
    sock.onmessage = (m) => {
      try {
        handle(JSON.parse(m.data));
      } catch {
        /* ignore malformed frames */
      }
    };
    sock.onclose = (e) => {
      ws.current = null;
      if (closedByUs.current) return setStatus("closed");
      const known = FAILURES[e.code];
      if (known) {
        // the server said no on purpose: retrying won't help
        setStatus("closed");
        setFailure(known);
        return;
      }
      setStatus("reconnecting");
      if (!everOpened.current && attempts.current >= 2) {
        setFailure({
          kind: "network",
          message:
            "Can't open the live connection to the server. If Parlo runs behind Nginx, the WebSocket location must pass the Upgrade header (see nginx.conf). Still retrying…",
        });
      }
      const delay = Math.min(10_000, 1000 * 2 ** attempts.current++);
      setTimeout(() => !closedByUs.current && connect(), delay);
    };
  }, [id, handle]);

  React.useEffect(() => {
    if (!initialTurns) return; // wait for the transcript before opening (decides whether to ask for an opener)
    closedByUs.current = false;
    started.current = initialTurns.length > 0;
    connect();
    const ping = setInterval(() => ws.current?.readyState === 1 && ws.current.send('{"type":"ping"}'), 25_000);
    return () => {
      closedByUs.current = true;
      clearInterval(ping);
      queue.current?.stop();
      ws.current?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connect, initialTurns === undefined]);

  const send = React.useCallback((payload: Record<string, unknown>) => {
    if (ws.current?.readyState !== WebSocket.OPEN) {
      toast.error("Not connected — reconnecting…");
      return false;
    }
    ws.current.send(JSON.stringify(payload));
    return true;
  }, []);

  const sendText = React.useCallback(
    (text: string) => {
      const client_id = uid();
      if (send({ type: "user_text", text, client_id })) setPending((p) => [...p, { client_id, text, status: "sending" }]);
    },
    [send],
  );

  const sendAudio = React.useCallback(
    (recording_id: string, localAudio: string) => {
      const client_id = uid();
      if (send({ type: "user_audio", recording_id, client_id }))
        setPending((p) => [...p, { client_id, text: "", localAudio, status: "transcribing" }]);
    },
    [send],
  );

  /** Ask the AI for its opening line again (after a provider error). */
  const retryStart = React.useCallback(() => {
    if (send({ type: "start" })) setStartError(null);
  }, [send]);

  const stopAudio = React.useCallback(() => queue.current?.stop(), []);

  return {
    turns, setTurns, pending, streaming, status, failure, startError, retryStart, sendText, sendAudio, stopAudio,
    feedbackErrors,
  };
}

function uid() {
  // crypto.randomUUID needs a secure context; this only has to be unique per tab
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
