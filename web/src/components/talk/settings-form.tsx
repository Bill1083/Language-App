"use client";

import { Label, Segmented, Switch } from "@/components/ui/primitives";
import type { ConversationSettings, Lang } from "@/lib/types";

/** Per-conversation settings, used both before starting and mid-conversation. */
export function ConversationSettingsForm({
  value,
  onChange,
  lang,
  showLevel,
  level,
  onLevel,
  mode,
}: {
  value: ConversationSettings;
  onChange: (v: ConversationSettings) => void;
  lang: Lang;
  showLevel?: boolean;
  level?: string;
  onLevel?: (l: string) => void;
  mode?: string;
}) {
  const set = <K extends keyof ConversationSettings>(k: K, v: ConversationSettings[K]) => onChange({ ...value, [k]: v });
  return (
    <div className="space-y-5">
      {showLevel && onLevel && (
        <div className="space-y-2">
          <Label>Level</Label>
          <Segmented
            className="flex w-full"
            value={level ?? "A1"}
            onChange={onLevel}
            options={["A1", "A2", "B1", "B2", "C1"].map((l) => ({ value: l, label: l }))}
            ariaLabel="Conversation level"
          />
          <p className="text-xs text-muted-foreground">The AI adapts its vocabulary, sentence length and speed.</p>
        </div>
      )}
      <div className="space-y-2">
        <Label>I&apos;ll reply by</Label>
        <Segmented
          className="flex w-full"
          value={value.input}
          onChange={(v) => set("input", v)}
          options={[
            { value: "voice", label: "🎙️ Speaking" },
            { value: "text", label: "⌨️ Typing" },
          ]}
          ariaLabel="Input mode"
        />
      </div>
      <div className="flex items-center justify-between gap-4">
        <div>
          <Label htmlFor="ai-voice">AI voice</Label>
          <p className="text-xs text-muted-foreground">Hear every reply read aloud.</p>
        </div>
        <Switch id="ai-voice" checked={value.ai_voice} onCheckedChange={(c) => set("ai_voice", c)} />
      </div>
      {value.ai_voice && (
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label>Speed</Label>
            <Segmented
              className="flex w-full"
              value={value.speed}
              onChange={(v) => set("speed", v)}
              options={[
                { value: 0.75, label: "0.75×" },
                { value: 1, label: "1×" },
                { value: 1.25, label: "1.25×" },
              ]}
              ariaLabel="Speech speed"
            />
          </div>
          <div className="space-y-2">
            <Label>Voice</Label>
            <Segmented
              className="flex w-full"
              value={value.voice_gender}
              onChange={(v) => set("voice_gender", v)}
              options={[
                { value: "female", label: "Female" },
                { value: "male", label: "Male" },
              ]}
              ariaLabel="Voice"
            />
          </div>
        </div>
      )}
      {lang === "ja" && (
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label>Politeness</Label>
            <Segmented
              className="flex w-full"
              value={value.politeness}
              onChange={(v) => set("politeness", v)}
              options={[
                { value: "polite", label: "です/ます" },
                { value: "casual", label: "Casual" },
              ]}
              ariaLabel="Politeness level"
            />
          </div>
          <div className="space-y-2">
            <Label>Furigana</Label>
            <Segmented
              className="flex w-full"
              value={value.furigana}
              onChange={(v) => set("furigana", v)}
              options={[
                { value: "always", label: "Always" },
                { value: "new", label: "New" },
                { value: "never", label: "Never" },
              ]}
              ariaLabel="Furigana"
            />
          </div>
          <div className="flex items-center justify-between gap-4 sm:col-span-2">
            <Label htmlFor="romaji">Show romaji</Label>
            <Switch
              id="romaji"
              checked={value.romaji === "on"}
              onCheckedChange={(c) => set("romaji", c ? "on" : "off")}
            />
          </div>
        </div>
      )}
      {mode !== "tutor" && (
        <div className="space-y-2">
          <Label>Feedback</Label>
          <Segmented
            className="flex w-full"
            value={value.strictness}
            onChange={(v) => set("strictness", v)}
            options={[
              { value: "gentle", label: "Gentle" },
              { value: "normal", label: "Normal" },
              { value: "strict", label: "Strict" },
            ]}
            ariaLabel="Feedback strictness"
          />
          <p className="text-xs text-muted-foreground">
            {value.strictness === "gentle"
              ? "Only major errors are pointed out."
              : value.strictness === "strict"
                ? "Everything, including naturalness and word choice."
                : "All grammar and vocabulary errors."}
          </p>
        </div>
      )}
    </div>
  );
}
