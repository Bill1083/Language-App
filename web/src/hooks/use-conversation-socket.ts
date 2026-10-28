"use client";

import * as React from "react";
import { toast } from "sonner";

import { AudioQueue } from "@/lib/audio";
import type { Feedback, PronunciationFlag, Turn } from "@/lib/types";

export type PendingTurn = { client_id: string; text: string; localAudio?: string; status: "sending" | "transcribing" };
export type Streaming = { stream_id: string; text: string } | null;
type Status = "connecting" | "open" | "reconnecting" | "closed";

type ServerEvent =
  | { type: "pong" }
  | { type: "transcribing"; client_id?: string }
  | { type: "user_turn"; client_id?: string; turn: Turn }
  | { type: "ai_start"; stream_id: string }
  | { type: "ai_delta"; stream_id: string; delta: string }
  | { type: "ai_audio"; stream_id: string; index: number; url: string }
  | { type: "ai_done"; stream_id: string; turn: Turn }
  | { type: "feedback"; turn_id: number; feedback: Feedback; pronunciation: PronunciationFlag[]; pronunciation_notes: string[] }
  | { type: "feedback_error"; turn_id: number; message: string }
  | { type: "goal"; achieved: boolean }
  | { type: "summary" }
  | { type: "error"; message: string; client_id?: string; retryable?: boolean };

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
  const [feedbackErrors, setFeedbackErrors] = React.useState<Record<number, string>>({});
  const ws = React.useRef<WebSocket | null>(null);
  const queue = React.useRef<AudioQueue | null>(null);
  const optsRef = React.useRef(opts);
  optsRef.current = opts;
  const turnsRef = React.useRef(turns);
  turnsRef.current = turns;
  const closedByUs = React.useRef(false);
  const attempts = React.useRef(0);
  const started = React.useRef(false);

  React.useEffect(() => {
    if (initialTurns) setTurns(initialTurns);
  }, [initialTurns]);

  const handle = React.useCallback((ev: ServerEvent) => {
    switch (ev.type) {
      case "transcribing":
        setPending((p) => p.map((x) => (x.client_id === ev.client_id ? { ...x, status: "transcribing" } : x)));
        break;
      case "user_turn":
        setPending((p) => p.filter((x) => x.client_id !== ev.client_id));
        setTurns((t) => (t.some((x) => x.id === ev.turn.id) ? t : [...t, ev.turn]));
        break;
      case "ai_start":
        queue.current?.stop();
        queue.current = optsRef.current.voice ? new AudioQueue(`stream-${ev.stream_id}`, 1) : null;
        setStreaming({ stream_id: ev.stream_id, text: "" });
        break;
      case "ai_delta":
        setStreaming((s) => (s && s.stream_id === ev.stream_id ? { ...s, text: s.text + ev.delta } : s));
        break;
      case "ai_audio":
        queue.current?.add(ev.index, ev.url);
        break;
      case "ai_done":
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
        setStreaming(null);
        if (ev.client_id) setPending((p) => p.filter((x) => x.client_id !== ev.client_id));
        toast.error(ev.message);
        break;
    }
  }, []);

  const connect = React.useCallback(() => {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const sock = new WebSocket(`${proto}://${window.location.host}/api/v1/conversations/${id}/ws`);
    ws.current = sock;
    sock.onopen = () => {
      attempts.current = 0;
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
      if (e.code === 4401) {
        setStatus("closed");
        toast.error("Session expired — sign in again.");
        return;
      }
      setStatus("reconnecting");
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

  const stopAudio = React.useCallback(() => queue.current?.stop(), []);

  return { turns, setTurns, pending, streaming, status, sendText, sendAudio, stopAudio, feedbackErrors };
}

function uid() {
  // crypto.randomUUID needs a secure context; this only has to be unique per tab
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
