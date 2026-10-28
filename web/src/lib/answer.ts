/** Offline fallback for typed-answer checking. The server (services/answer_check.py)
 *  is authoritative; this mirrors its normalisation so a downloaded lesson still
 *  works without a connection. */

import { rubyReading, stripRuby } from "./japanese";

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
