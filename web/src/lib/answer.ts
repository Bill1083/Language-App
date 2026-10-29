/** Offline fallback for typed-answer checking. The server (services/answer_check.py)
 *  is authoritative; this mirrors its normalisation so a downloaded lesson still
 *  works without a connection. */

import { romajiFor, rubyReading, stripRuby } from "./japanese";

function strip(s: string) {
  return s.normalize("NFD").replace(/\p{M}/gu, "");
}

export function normalize(text: string, lang: string) {
  let t = stripRuby(text).normalize("NFC").trim();
  if (lang === "ja") {
    t = t.normalize("NFKC");
    return t.replace(/[。、，．・！？!?「」『』（）()[\]【】〜~…\s,.]/g, "").toLowerCase();
  }
  t = t.replace(/[’‘ʼ`´]/g, "'").toLowerCase().replace(/[  ]/g, " ").replace(/[-‐‑–—]/g, " ");
  t = t.replace(/[.,!?;:¡¿…"“”«»()[\]{}/\\]/g, " ").replace(/\s*'\s*/g, "'");
  return t.replace(/\s+/g, " ").trim();
}

export function localCheck(answer: string, accepted: string[], lang: string): "correct" | "accent" | "wrong" {
  const user = normalize(answer, lang);
  const variants = accepted.flatMap((a) => [stripRuby(a), rubyReading(a)]).map((a) => normalize(a, lang));
  if (variants.includes(user)) return "correct";
  if (lang !== "ja" && variants.some((v) => strip(v) === strip(user))) return "accent";
  return "wrong";
}

// ---------------------------------------------------------------- type-it practice

/** Edit distance (insert / delete / substitute / swap two letters), stopping early past `max`. */
export function editDistance(a: string, b: string, max = 2): number {
  if (Math.abs(a.length - b.length) > max) return max + 1;
  const d = Array.from({ length: a.length + 1 }, (_, i) => [i, ...Array(b.length).fill(0)]);
  for (let j = 1; j <= b.length; j++) d[0][j] = j;
  for (let i = 1; i <= a.length; i++) {
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost);
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) d[i][j] = Math.min(d[i][j], d[i - 2][j - 2] + 1);
    }
  }
  return d[a.length][b.length];
}

// Other common ways of writing the same kana in romaji.
const ROMAJI_ALIASES: [RegExp, string][] = [
  [/si/g, "shi"], [/ti/g, "chi"], [/tu/g, "tsu"], [/hu/g, "fu"], [/zi/g, "ji"],
  [/sy([aou])/g, "sh$1"], [/ty([aou])/g, "ch$1"], [/zy([aou])/g, "j$1"], [/jy([aou])/g, "j$1"],
];

function romajiKey(s: string) {
  let t = s.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().replace(/[\s'’\-.,!?。、]/g, "");
  for (const [re, to] of ROMAJI_ALIASES) t = t.replace(re, to);
  return t;
}

export type PracticeVerdict = "correct" | "close" | "wrong";

/** Typed-answer check for practice. "close" = one letter off (or only accents wrong) on an
 *  answer of 3+ letters — shorter answers like "ka"/"ki" are different words when one letter is off. */
export function practiceCheck(answer: string, accepted: string[], lang: string, kind: "word" | "kana"): PracticeVerdict {
  const typed = answer.trim();
  if (!typed) return "wrong";
  const romajiAnswer = kind === "kana" || (lang === "ja" && /^[\p{Script=Latin}\s'’\-.,!?]+$/u.test(typed));
  if (romajiAnswer) {
    const user = romajiKey(typed);
    const variants = accepted.flatMap((a) => (kind === "kana" ? [a] : [romajiFor(a), a])).map(romajiKey).filter(Boolean);
    if (variants.includes(user)) return "correct";
    return variants.some((v) => v.length >= 3 && editDistance(user, v, 1) <= 1) ? "close" : "wrong";
  }
  const exact = localCheck(typed, accepted, lang);
  if (exact === "correct") return "correct";
  if (exact === "accent") return "close";
  const user = normalize(typed, lang);
  const variants = accepted.flatMap((a) => [stripRuby(a), rubyReading(a)]).map((a) => normalize(a, lang));
  return variants.some((v) => v.length >= 3 && editDistance(user, v, 1) <= 1) ? "close" : "wrong";
}
