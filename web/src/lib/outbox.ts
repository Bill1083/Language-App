/** Offline outbox: requests made while offline (lesson completions, reviews)
 *  are stored locally and replayed when the connection returns. */

import { api } from "./api";

type Item = { path: string; body: unknown; at: string };
const KEY = "parlo-outbox";

function read(): Item[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) || "[]");
  } catch {
    return [];
  }
}

function write(items: Item[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(items));
  } catch {
    /* storage full or blocked — nothing more we can do offline */
  }
}

export function queueOffline(path: string, body: unknown) {
  write([...read(), { path, body, at: new Date().toISOString() }]);
}

export function pendingCount() {
  return read().length;
}

let flushing = false;
export async function flushOutbox(): Promise<number> {
  if (flushing || typeof navigator === "undefined" || !navigator.onLine) return 0;
  flushing = true;
  let sent = 0;
  try {
    const items = read();
    const remaining: Item[] = [];
    for (const item of items) {
      try {
        await api(item.path, { method: "POST", body: item.body });
        sent++;
      } catch (e) {
        if ((e as { status?: number }).status === 0) remaining.push(item);
      }
    }
    write(remaining);
  } finally {
    flushing = false;
  }
  return sent;
}
