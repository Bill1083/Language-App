export type Lang = "fr" | "it" | "ja";
export type Cefr = "A1" | "A2" | "B1" | "B2" | "C1";

export type UserSettings = {
  theme: "dark" | "light" | "system";
  sound: boolean;
  daily_goal_type: "xp" | "minutes";
  daily_goal_value: number;
  new_cards_per_day: number;
  voice_gender: "female" | "male";
  speech_speed: number;
  furigana: "always" | "new" | "never";
  romaji: "auto" | "on" | "off";
  strictness: "gentle" | "normal" | "strict";
  gender_colors: boolean;
  reminders: boolean;
  reminder_hour: number;
  timezone: string;
  active_language: Lang | null;
  onboarded: boolean;
  voice_notice_seen: boolean;
};

export type Enrolment = {
  language_code: Lang;
  current_level: Cefr;
  settings: Record<string, unknown>;
  placement: { level: Cefr } | null;
};

export type Me = {
  id: number;
  email: string;
  display_name: string;
  role: "admin" | "user";
  settings: UserSettings;
  enrolments: Enrolment[];
};

export type Daily = {
  xp_today: number;
  minutes_today: number;
  goal_type: "xp" | "minutes";
  goal_value: number;
  goal_progress: number;
  goal_met: boolean;
  streak: number;
  longest_streak: number;
  freezes_available: number;
  active_today: boolean;
};

export type LessonState = "locked" | "available" | "completed" | "perfect";

export type CourseLesson = {
  id: number;
  slug: string;
  title: string;
  kind: "lesson" | "checkpoint" | "level_test" | "kana";
  order: number;
  state: LessonState;
  best_accuracy: number | null;
  ready: boolean;
};

export type CourseUnit = {
  id: number;
  slug: string;
  title: string;
  theme: string;
  order: number;
  objectives: string[];
  is_test: boolean;
  lessons: CourseLesson[];
  done: number;
  total: number;
  reached: boolean;
  vocab: string[];
};

export type CourseLevel = {
  cefr: "PRE" | Cefr;
  order: number;
  unlocked: boolean;
  completed: number;
  total: number;
  test_passed: boolean;
  units: CourseUnit[];
};

export type NextLesson = { id: number; title: string; unit: string; kind: string; level: string };

export type Course = {
  language: Lang;
  current_level: Cefr;
  kana_done: boolean;
  levels: CourseLevel[];
  next_lesson: NextLesson | null;
};

export type Vocab = {
  word: string;
  reading?: string | null;
  romaji?: string | null;
  meaning: string;
  pos?: string | null;
  gender?: "m" | "f" | "m/f" | null;
  plural?: string | null;
  example?: string | null;
  example_translation?: string | null;
  emoji?: string | null;
  note?: string | null;
};

export type Grammar = {
  title: string;
  explanation: string;
  examples?: { target: string; english: string }[];
  table?: { title?: string | null; headers: string[]; rows: string[][] } | null;
  politeness?: "polite" | "plain" | "both" | null;
};

export type Exercise = { id: number; type: string; explanation?: string } & Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

export type LessonPayload = {
  id: number;
  title: string;
  kind: string;
  language: Lang;
  level: string;
  unit: { id: number; title: string };
  status: string;
  error?: string | null;
  content?: { intro: string; vocab: Vocab[]; grammar: Grammar[]; pronunciation: string[]; is_test?: boolean; pass_mark?: number };
  exercises?: Exercise[];
};

export type Segment = { text: string; kind: "same" | "accent" | "typo" };

export type AnswerResult = {
  verdict: "correct" | "typo" | "accent" | "ai_accepted" | "wrong";
  is_correct: boolean;
  correct_answer: string | null;
  explanation: string;
  segments: Segment[] | null;
  judged_by_ai: boolean;
  ai_explanation?: string;
  correct_index?: number;
  matched?: string | null;
};

export type Achievement = { key: string; title: string; description: string; icon: string; earned_at?: string | null };

export type CompleteResult = {
  accuracy: number;
  passed: boolean;
  is_test: boolean;
  pass_mark: number;
  xp: number;
  streak: number;
  goal_just_met: boolean;
  used_freeze: boolean;
  new_words: { id: number; lemma: string; reading: string | null; meaning: string; ruby: string | null }[];
  achievements: Achievement[];
  level_up: { from: string; to: string } | null;
};

export type FeedbackError = {
  type: string;
  original: string;
  correction: string;
  explanation: string;
};

export type Feedback = {
  overall: "perfect" | "minor_issues" | "errors";
  score: number;
  corrected: string;
  more_natural?: string | null;
  errors: FeedbackError[];
  praise?: string | null;
  new_vocab: { word: string; reading?: string | null; meaning: string }[];
  goal_achieved?: boolean | null;
};

export type PronunciationFlag = { heard: string; expected: string | null; reason: "unclear" | "mismatch" | "low_confidence"; confidence?: number | null };

export type Turn = {
  id: number;
  role: "user" | "assistant";
  text: string;
  translation: string | null;
  recording_url: string | null;
  audio_urls: string[];
  voice: boolean;
  pronunciation: PronunciationFlag[];
  pronunciation_notes: string[];
  feedback: Feedback | null;
  score: number | null;
  created_at: string | null;
};

export type Scenario = {
  id: number;
  slug: string;
  title: string;
  emoji: string;
  description: string;
  goal: string;
  ai_role: string;
  user_role: string;
  min_level: Cefr;
  unit_id: number | null;
};

export type ConversationSettings = {
  input: "voice" | "text";
  ai_voice: boolean;
  speed: number;
  voice_gender: "female" | "male";
  politeness: "polite" | "casual";
  furigana: "always" | "new" | "never";
  romaji: "auto" | "on" | "off";
  strictness: "gentle" | "normal" | "strict";
  feedback: boolean;
  topic: string;
};

export type Summary = {
  duration_s: number;
  turns: number;
  avg_score: number | null;
  goal_achieved: boolean;
  new_vocab: { word: string; reading?: string | null; meaning: string }[];
  error_types: Record<string, number>;
  top_mistakes: { title: string; explanation: string; wrong?: string | null; right?: string | null }[];
  suggested_lessons: { id: number; title: string; unit: string; level: string }[];
  suggested_drill?: string | null;
  encouragement: string;
  error?: string;
};

export type Conversation = {
  id: number;
  language: Lang;
  mode: "scenario" | "free" | "unit" | "tutor";
  title: string;
  level: Cefr;
  settings: ConversationSettings;
  goal_achieved: boolean;
  started_at: string;
  ended_at: string | null;
  summary: Summary | null;
  scenario: Scenario | null;
  turns?: Turn[];
  avg_score?: number | null;
};

export type SrsCard = {
  id: number;
  card_type: "recognize" | "produce" | "listen" | "kanji" | "mistake";
  front: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  back: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  source: string;
  language: Lang;
  is_new: boolean;
  due_at: string;
  reps: number;
  lapses: number;
  intervals?: Record<string, string>;
};

export type Dashboard = {
  language: Lang | null;
  daily: Daily;
  next_lesson?: NextLesson | null;
  kana_done?: boolean;
  level?: { cefr: Cefr; completed: number; total: number };
  reviews_due?: number;
  suggested_scenario?: { id: number; title: string; emoji: string; goal: string; min_level: Cefr } | null;
  recent?: { reason: string; label: string; language: Lang | null; xp: number; at: string; count: number }[];
  enrolments: { language_code: Lang; current_level: Cefr; words: number }[];
};

export type VocabRow = {
  id: number;
  lemma: string;
  reading: string | null;
  ruby: string | null;
  meaning: string;
  pos: string | null;
  gender: string | null;
  level: string | null;
  example: string | null;
  example_translation: string | null;
  emoji: string | null;
  plural: string | null;
  note: string | null;
  source: string;
  unit: string | null;
  status: string | null;
  learned_at: string | null;
};
