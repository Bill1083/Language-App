"use client";

import * as React from "react";

import { LANGS } from "@/lib/languages";
import type { Lang } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Special-character buttons for French / Italian above any text input. */
export function AccentBar({ lang, onInsert, className }: { lang: Lang; onInsert: (ch: string) => void; className?: string }) {
  const chars = LANGS[lang].accents;
  const [upper, setUpper] = React.useState(false);
  if (!chars.length) return null;
  return (
    <div className={cn("flex flex-wrap items-center gap-1", className)} role="toolbar" aria-label="Accented characters">
      {chars.map((c) => (
        <button
          key={c}
          type="button"
          // keep focus (and the caret) in the input
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => onInsert(upper ? c.toUpperCase() : c)}
          className="h-8 min-w-8 rounded-lg border bg-card px-1.5 text-[15px] font-medium transition hover:border-primary hover:bg-primary-soft"
          aria-label={`Insert ${c}`}
        >
          {upper ? c.toUpperCase() : c}
        </button>
      ))}
      <button
        type="button"
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => setUpper((u) => !u)}
        aria-pressed={upper}
        className={cn(
          "h-8 rounded-lg border px-2 text-xs font-semibold text-muted-foreground transition hover:bg-muted",
          upper && "border-primary bg-primary-soft text-primary-strong",
        )}
        aria-label="Toggle capital letters"
      >
        ⇧
      </button>
    </div>
  );
}

type Props = Omit<React.ComponentProps<"textarea">, "onChange" | "onSubmit"> & {
  value: string;
  onChange: (v: string) => void;
  lang: Lang | "en";
  onSubmit?: () => void;
  multiline?: boolean;
  showAccents?: boolean;
};

/** Text input for answers in the target language. IME-safe: Enter during
 *  composition (Japanese / Chinese input) confirms the IME candidate instead of submitting. */
export const TargetInput = React.forwardRef<HTMLTextAreaElement, Props>(function TargetInput(
  { value, onChange, lang, onSubmit, multiline, showAccents = true, className, ...props },
  ref,
) {
  const inner = React.useRef<HTMLTextAreaElement>(null);
  React.useImperativeHandle(ref, () => inner.current!);
  const composing = React.useRef(false);

  const insert = (ch: string) => {
    const el = inner.current;
    if (!el) return onChange(value + ch);
    const start = el.selectionStart ?? value.length;
    const end = el.selectionEnd ?? value.length;
    const next = value.slice(0, start) + ch + value.slice(end);
    onChange(next);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(start + ch.length, start + ch.length);
    });
  };

  // auto-grow
  React.useLayoutEffect(() => {
    const el = inner.current;
    if (!el) return;
    const max = multiline ? 220 : 160;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight + 2, max)}px`;
    el.style.overflowY = el.scrollHeight + 2 > max ? "auto" : "hidden";
  }, [value, multiline]);

  return (
    <div className="flex w-full flex-col gap-2">
      {showAccents && lang !== "en" && <AccentBar lang={lang} onInsert={insert} />}
      <textarea
        ref={inner}
        lang={lang}
        rows={1}
        value={value}
        autoCapitalize="off"
        autoCorrect="off"
        autoComplete="off"
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
        onCompositionStart={() => (composing.current = true)}
        onCompositionEnd={() => (composing.current = false)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            // isComposing covers browsers that fire keydown after compositionend
            if (composing.current || e.nativeEvent.isComposing || e.keyCode === 229) return;
            if (!multiline || !e.metaKey) {
              e.preventDefault();
              onSubmit?.();
            }
          }
        }}
        className={cn(
          "min-h-12 w-full resize-none rounded-2xl border-2 border-input bg-card px-4 py-3 text-lg outline-none transition placeholder:text-muted-foreground/60 focus:border-primary",
          lang === "ja" && "font-jp",
          className,
        )}
        {...props}
      />
    </div>
  );
});
