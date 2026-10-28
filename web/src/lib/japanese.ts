/** Furigana markup ({漢字|かんじ}), kana → romaji (Hepburn) and segmentation helpers. */

export type RubyToken = { base: string; reading?: string };

const RUBY_RE = /\{([^{}|]+)\|([^{}]+)\}/g;

export function parseRuby(text: string): RubyToken[] {
  const out: RubyToken[] = [];
  let last = 0;
  for (const m of text.matchAll(RUBY_RE)) {
    if (m.index! > last) out.push({ base: text.slice(last, m.index) });
    out.push({ base: m[1], reading: m[2] });
    last = m.index! + m[0].length;
  }
  if (last < text.length) out.push({ base: text.slice(last) });
  return out;
}

export const stripRuby = (text: string) => text.replace(RUBY_RE, "$1");
export const rubyReading = (text: string) => text.replace(RUBY_RE, "$2");

/** While streaming, hide a half-written `{漢字|かん` group. */
export function stripOpenRuby(text: string) {
  const open = text.lastIndexOf("{");
  return open > text.lastIndexOf("}") ? text.slice(0, open) : text;
}

export const hasKanji = (s: string) => /[一-鿿々]/.test(s);
export const isJapanese = (s: string) => /[぀-ヿ一-鿿]/.test(s);

// ---------------------------------------------------------------- romaji

const BASE: Record<string, string> = {
  あ: "a", い: "i", う: "u", え: "e", お: "o", か: "ka", き: "ki", く: "ku", け: "ke", こ: "ko",
  さ: "sa", し: "shi", す: "su", せ: "se", そ: "so", た: "ta", ち: "chi", つ: "tsu", て: "te", と: "to",
  な: "na", に: "ni", ぬ: "nu", ね: "ne", の: "no", は: "ha", ひ: "hi", ふ: "fu", へ: "he", ほ: "ho",
  ま: "ma", み: "mi", む: "mu", め: "me", も: "mo", や: "ya", ゆ: "yu", よ: "yo",
  ら: "ra", り: "ri", る: "ru", れ: "re", ろ: "ro", わ: "wa", を: "o", ん: "n",
  が: "ga", ぎ: "gi", ぐ: "gu", げ: "ge", ご: "go", ざ: "za", じ: "ji", ず: "zu", ぜ: "ze", ぞ: "zo",
  だ: "da", ぢ: "ji", づ: "zu", で: "de", ど: "do", ば: "ba", び: "bi", ぶ: "bu", べ: "be", ぼ: "bo",
  ぱ: "pa", ぴ: "pi", ぷ: "pu", ぺ: "pe", ぽ: "po", ぁ: "a", ぃ: "i", ぅ: "u", ぇ: "e", ぉ: "o", ゔ: "vu",
};
const YOON: Record<string, string> = { ゃ: "a", ゅ: "u", ょ: "o" };
const SMALL_VOWEL: Record<string, string> = { ぁ: "a", ぃ: "i", ぅ: "u", ぇ: "e", ぉ: "o" };

function toHiragana(s: string) {
  return s.replace(/[ァ-ヶ]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0x60));
}

export function kanaToRomaji(input: string): string {
  const s = toHiragana(input);
  let out = "";
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    const next = s[i + 1];
    if (c === "っ") {
      const following = BASE[next] ?? "";
      out += following.startsWith("ch") ? "t" : following[0] ?? "";
      continue;
    }
    if (c === "ー") {
      out += out.slice(-1).match(/[aeiou]/) ? out.slice(-1) : "";
      continue;
    }
    if (next && YOON[next] && BASE[c]) {
      const b = BASE[c];
      const stem = b.startsWith("sh") || b.startsWith("ch") || b === "ji" ? b.slice(0, -1) : b.slice(0, -1) + "y";
      out += stem + YOON[next];
      i++;
      continue;
    }
    if (next && SMALL_VOWEL[next] && BASE[c] && !SMALL_VOWEL[c]) {
      // foreign sounds: ファ fa, ティ ti, ウィ wi
      out += BASE[c].replace(/[aeiou]$/, "") + SMALL_VOWEL[next];
      i++;
      continue;
    }
    if (c === "ん" && next && /[あいうえおやゆよ]/.test(next)) {
      out += "n'";
      continue;
    }
    out += BASE[c] ?? (c === "。" ? "." : c === "、" ? "," : c === "？" ? "?" : c === "！" ? "!" : c);
  }
  return out;
}

/** Romaji for a marked-up Japanese string (uses the furigana readings). */
export function romajiFor(text: string): string {
  return kanaToRomaji(rubyReading(text)).replace(/\s+/g, " ").trim();
}

// ---------------------------------------------------------------- segmentation

export type WordSpan = { tokens: RubyToken[]; text: string; isWord: boolean };

/** Split marked-up text into tappable words. Japanese uses Intl.Segmenter;
 *  furigana groups are never split across words. */
export function segmentWords(text: string, lang: string): WordSpan[] {
  const tokens = parseRuby(text);
  if (lang !== "ja" || typeof Intl === "undefined" || !("Segmenter" in Intl)) {
    const spans: WordSpan[] = [];
    for (const t of tokens) {
      if (t.reading) {
        spans.push({ tokens: [t], text: t.base, isWord: true });
        continue;
      }
      for (const part of t.base.split(/([\p{L}\p{M}'’-]+)/u)) {
        if (!part) continue;
        const isWord = /[\p{L}]/u.test(part);
        spans.push({ tokens: [{ base: part }], text: part, isWord });
      }
    }
    return spans;
  }
  // Japanese: segment the plain base text, then map ruby groups onto segments.
  const plain = tokens.map((t) => t.base).join("");
  const segmenter = new Intl.Segmenter("ja", { granularity: "word" });
  const bounds: { start: number; end: number; isWord: boolean }[] = [];
  for (const seg of segmenter.segment(plain)) {
    bounds.push({ start: seg.index, end: seg.index + seg.segment.length, isWord: !!seg.isWordLike });
  }
  // token start offsets
  const tokStarts: number[] = [];
  let off = 0;
  for (const t of tokens) {
    tokStarts.push(off);
    off += t.base.length;
  }
  // merge segments that would cut through a ruby token
  const merged: typeof bounds = [];
  for (const b of bounds) {
    const prev = merged[merged.length - 1];
    const cuts = tokens.some((t, i) => t.reading && tokStarts[i] < b.start && tokStarts[i] + t.base.length > b.start);
    if (prev && cuts) {
      prev.end = b.end;
      prev.isWord = prev.isWord || b.isWord;
    } else merged.push({ ...b });
  }
  return merged.map((b) => {
    const spanTokens: RubyToken[] = [];
    tokens.forEach((t, i) => {
      const ts = tokStarts[i];
      const te = ts + t.base.length;
      const s = Math.max(ts, b.start);
      const e = Math.min(te, b.end);
      if (s >= e) return;
      if (t.reading) spanTokens.push(t);
      else spanTokens.push({ base: t.base.slice(s - ts, e - ts) });
    });
    return { tokens: spanTokens, text: plain.slice(b.start, b.end), isWord: b.isWord };
  });
}
