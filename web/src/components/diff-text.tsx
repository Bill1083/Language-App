import * as React from "react";

import { stripRuby } from "@/lib/japanese";
import { cn } from "@/lib/utils";

type Op = { kind: "same" | "del" | "add"; text: string };

function tokenize(text: string, lang: string): string[] {
  if (lang === "ja") return [...text];
  return text.split(/(\s+)/).filter(Boolean);
}

function lcsDiff(a: string[], b: string[]): Op[] {
  const n = a.length;
  const m = b.length;
  const norm = (s: string) => s.toLowerCase().replace(/[.,!?;:«»"“”。、！？]/g, "");
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i][j] = norm(a[i]) === norm(b[j]) ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const ops: Op[] = [];
  let i = 0;
  let j = 0;
  const push = (kind: Op["kind"], text: string) => {
    const last = ops[ops.length - 1];
    if (last && last.kind === kind) last.text += text;
    else ops.push({ kind, text });
  };
  while (i < n && j < m) {
    if (norm(a[i]) === norm(b[j])) {
      push("same", b[j]);
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) push("del", a[i++]);
    else push("add", b[j++]);
  }
  while (i < n) push("del", a[i++]);
  while (j < m) push("add", b[j++]);
  return ops;
}

/** Inline correction diff: what was wrong struck through in red, the fix in green. */
export function DiffText({ from, to, lang, className }: { from: string; to: string; lang: string; className?: string }) {
  const ops = React.useMemo(() => lcsDiff(tokenize(stripRuby(from), lang), tokenize(stripRuby(to), lang)), [from, to, lang]);
  return (
    <span className={cn("leading-relaxed", className)} lang={lang}>
      {ops.map((op, i) =>
        op.kind === "same" ? (
          <span key={i}>{op.text}</span>
        ) : op.kind === "del" ? (
          op.text.trim() ? (
            <del key={i} className="rounded bg-danger-soft px-0.5 text-danger decoration-danger/70 decoration-2">
              {op.text}
            </del>
          ) : null
        ) : (
          <ins key={i} className="rounded bg-success-soft px-0.5 font-semibold text-success no-underline">
            {op.text}
          </ins>
        ),
      )}
    </span>
  );
}
