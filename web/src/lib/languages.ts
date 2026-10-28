import type { Lang } from "./types";

export const LANGS: Record<Lang, {
  name: string;
  native: string;
  flag: string;
  hello: string;
  accents: string[];
  speechLang: string;
}> = {
  fr: {
    name: "French", native: "Français", flag: "🇫🇷", hello: "Bonjour",
    accents: ["é", "è", "ê", "ë", "à", "â", "ç", "î", "ï", "ô", "û", "ù", "ü", "œ", "æ"], speechLang: "fr-FR",
  },
  it: {
    name: "Italian", native: "Italiano", flag: "🇮🇹", hello: "Ciao",
    accents: ["à", "è", "é", "ì", "ò", "ù"], speechLang: "it-IT",
  },
  ja: { name: "Japanese", native: "日本語", flag: "🇯🇵", hello: "こんにちは", accents: [], speechLang: "ja-JP" },
};

export const LANG_CODES = Object.keys(LANGS) as Lang[];

export const CEFR_LEVELS = ["A1", "A2", "B1", "B2", "C1"] as const;

export const CEFR_LABEL: Record<string, string> = {
  PRE: "Writing systems",
  A1: "Beginner",
  A2: "Elementary",
  B1: "Intermediate",
  B2: "Upper intermediate",
  C1: "Advanced",
};

export const ERROR_TYPE_LABEL: Record<string, string> = {
  grammar: "Grammar",
  vocabulary: "Vocabulary",
  spelling: "Spelling",
  gender: "Gender",
  conjugation: "Conjugation",
  particle: "Particle",
  word_order: "Word order",
  politeness: "Politeness",
  accent: "Accent",
};

export function isLang(x: unknown): x is Lang {
  return x === "fr" || x === "it" || x === "ja";
}
