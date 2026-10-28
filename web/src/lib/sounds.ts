/** Tiny synthesised UI sounds (no audio files): correct, wrong, complete. */

let ctx: AudioContext | null = null;
let enabled = true;

export function setSoundEnabled(on: boolean) {
  enabled = on;
}

function tone(freq: number, start: number, duration: number, type: OscillatorType = "sine", gain = 0.12) {
  if (!ctx) return;
  const osc = ctx.createOscillator();
  const g = ctx.createGain();
  osc.type = type;
  osc.frequency.value = freq;
  g.gain.setValueAtTime(0, ctx.currentTime + start);
  g.gain.linearRampToValueAtTime(gain, ctx.currentTime + start + 0.015);
  g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + start + duration);
  osc.connect(g).connect(ctx.destination);
  osc.start(ctx.currentTime + start);
  osc.stop(ctx.currentTime + start + duration + 0.05);
}

function ensure() {
  if (!enabled || typeof window === "undefined") return false;
  try {
    ctx ??= new AudioContext();
    if (ctx.state === "suspended") void ctx.resume();
    return true;
  } catch {
    return false;
  }
}

export const sounds = {
  correct() {
    if (!ensure()) return;
    tone(660, 0, 0.18, "sine");
    tone(990, 0.09, 0.25, "sine");
  },
  wrong() {
    if (!ensure()) return;
    tone(220, 0, 0.22, "triangle", 0.1);
    tone(180, 0.1, 0.25, "triangle", 0.08);
  },
  complete() {
    if (!ensure()) return;
    [523, 659, 784, 1047].forEach((f, i) => tone(f, i * 0.09, 0.35, "sine", 0.1));
  },
  tap() {
    if (!ensure()) return;
    tone(880, 0, 0.05, "sine", 0.04);
  },
};
