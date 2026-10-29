"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Copy, Flag, Play, RefreshCw, Server, Settings2, Trash, Users, Wand } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { toast } from "sonner";

import { ChartCard, SimpleBars } from "@/components/charts";
import { Flag as LangFlag } from "@/components/flag";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/overlay";
import { Badge, Card, EmptyState, Input, Label, Select, Skeleton, Switch, Tabs, TabsContent, TabsList, TabsTrigger, Textarea } from "@/components/ui/primitives";
import { useMe } from "@/hooks/use-me";
import { del, errorMessage, get, patch, post, put } from "@/lib/api";
import { player } from "@/lib/audio";
import { LANG_CODES, LANGS } from "@/lib/languages";
import { cn, timeAgo } from "@/lib/utils";

type Config = {
  effective: Record<string, string | number | boolean>;
  voices: Record<string, Record<string, { female: string; male: string }>>;
  overrides: Record<string, unknown>;
  keys: Record<string, { set: boolean; masked: string; source: string }>;
  options: {
    llm_providers: string[]; tts_providers: string[]; stt_providers: string[];
    default_models: Record<string, Record<string, string>>; default_stt_models: Record<string, string>;
    default_fallback_models: Record<string, string>;
    google_voices: Record<string, string[]>;
  };
  registration_mode: string;
};
type TestResult = {
  ok: boolean; latency_ms?: number; error?: string; sample?: string; url?: string; transcript?: string; expected?: string; model?: string;
  backup?: boolean; failures?: string[];
};

const money = (n: number) => `$${n.toFixed(n < 1 ? 4 : 2)}`;

function TestBadge({ r }: { r?: TestResult | null }) {
  if (!r) return null;
  return (
    <p className={cn("mt-2 rounded-xl px-3 py-2 text-sm", r.ok ? "bg-success-soft text-success" : "bg-danger-soft text-danger")}>
      {r.ok ? "✓ OK" : "✗ Failed"}
      {r.latency_ms != null && <span className="opacity-80"> · {r.latency_ms} ms</span>}
      {r.model && <span className="opacity-80"> · {r.model}</span>}
      {r.backup && <span className="opacity-80"> (backup model)</span>}
      {r.sample && <span className="block text-foreground/80">{r.sample}</span>}
      {r.transcript != null && <span className="block text-foreground/80">Heard: “{r.transcript}” (expected “{r.expected}”)</span>}
      {r.failures?.length
        ? r.failures.map((f, i) => (
            <span key={i} className={cn("block", r.ok && "text-xs text-muted-foreground")}>
              {f}
            </span>
          ))
        : r.error && <span className="block">{r.error}</span>}
    </p>
  );
}

// ------------------------------------------------------------------ usage

function UsageTab() {
  const { data } = useQuery({
    queryKey: ["admin", "usage"],
    queryFn: () => get<{
      today: number; month: number; daily_budget_per_user: number;
      by_day: { day: string; cost: number; calls: number }[];
      by_model: { provider: string; model: string; calls: number; input_tokens: number; output_tokens: number; chars: number; audio_seconds: number; cost: number; avg_latency_ms: number; failures: number }[];
      by_task: { task: string; calls: number; cost: number }[];
      by_user: { email: string; calls: number; cost: number }[];
    }>("/admin/usage?days=30"),
  });
  if (!data) return <Skeleton className="h-64" />;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <Card className="p-4"><p className="text-xs font-semibold text-muted-foreground">Today</p><p className="mt-1 text-2xl font-black">{money(data.today)}</p></Card>
        <Card className="p-4"><p className="text-xs font-semibold text-muted-foreground">This month</p><p className="mt-1 text-2xl font-black">{money(data.month)}</p></Card>
        <Card className="p-4"><p className="text-xs font-semibold text-muted-foreground">Daily budget / user</p><p className="mt-1 text-2xl font-black">{money(data.daily_budget_per_user)}</p></Card>
      </div>
      <ChartCard title="Estimated cost per day" subtitle="Last 30 days, all users" columns={["Day", "Cost", "Calls"]}
        rows={data.by_day.map((d) => [d.day, money(d.cost), d.calls])}>
        <SimpleBars data={data.by_day} x="day" y="cost" unit=" $" labelFormat={(d) => new Date(d).toLocaleDateString(undefined, { day: "numeric", month: "short" })} />
      </ChartCard>
      <Card className="overflow-x-auto p-0">
        <table className="w-full min-w-[640px] text-sm">
          <thead className="bg-muted text-xs text-muted-foreground">
            <tr>{["Provider / model", "Calls", "Tokens in/out", "Chars", "Audio", "Latency", "Fails", "Cost"].map((h) => <th key={h} className="px-3 py-2 text-left font-semibold">{h}</th>)}</tr>
          </thead>
          <tbody>
            {data.by_model.map((m) => (
              <tr key={`${m.provider}${m.model}`} className="border-t">
                <td className="px-3 py-2"><span className="font-semibold">{m.provider}</span> <span className="text-muted-foreground">{m.model}</span></td>
                <td className="px-3 py-2 tabular-nums">{m.calls}</td>
                <td className="px-3 py-2 tabular-nums">{m.input_tokens.toLocaleString()} / {m.output_tokens.toLocaleString()}</td>
                <td className="px-3 py-2 tabular-nums">{m.chars.toLocaleString()}</td>
                <td className="px-3 py-2 tabular-nums">{m.audio_seconds}s</td>
                <td className="px-3 py-2 tabular-nums">{m.avg_latency_ms} ms</td>
                <td className={cn("px-3 py-2 tabular-nums", m.failures && "text-danger")}>{m.failures}</td>
                <td className="px-3 py-2 font-semibold tabular-nums">{money(m.cost)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <div className="grid gap-4 sm:grid-cols-2">
        <Card className="p-4">
          <h3 className="mb-2 font-bold">By task</h3>
          {data.by_task.map((t) => <p key={t.task} className="flex justify-between border-t py-1.5 text-sm first-of-type:border-0"><span>{t.task}</span><span className="tabular-nums text-muted-foreground">{t.calls} · {money(t.cost)}</span></p>)}
        </Card>
        <Card className="p-4">
          <h3 className="mb-2 font-bold">By user</h3>
          {data.by_user.map((u) => <p key={u.email} className="flex justify-between border-t py-1.5 text-sm first-of-type:border-0"><span className="truncate">{u.email}</span><span className="tabular-nums text-muted-foreground">{u.calls} · {money(u.cost)}</span></p>)}
        </Card>
      </div>
      <p className="text-xs text-muted-foreground">Costs are estimates from the pricing table — also set a hard spend limit in each provider&apos;s billing console.</p>
    </div>
  );
}

// ------------------------------------------------------------------ providers

function ProvidersTab() {
  const qc = useQueryClient();
  const { data: cfg } = useQuery({ queryKey: ["admin", "config"], queryFn: () => get<Config>("/admin/config") });
  const [form, setForm] = React.useState<Record<string, string | number | boolean>>({});
  const [keys, setKeys] = React.useState<Record<string, string>>({});
  const [tests, setTests] = React.useState<Record<string, TestResult | null>>({});
  const [busy, setBusy] = React.useState<string | null>(null);
  React.useEffect(() => { if (cfg) setForm(cfg.effective); }, [cfg]);

  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(form)) if (cfg && v !== cfg.effective[k]) body[k] = v;
      const keyBody = Object.fromEntries(Object.entries(keys).filter(([, v]) => v.trim()));
      if (Object.keys(keyBody).length) body.keys = keyBody;
      return put("/admin/config", body);
    },
    onSuccess: () => { toast.success("Provider settings saved — live within a few seconds."); setKeys({}); void qc.invalidateQueries({ queryKey: ["admin", "config"] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const reset = useMutation({
    mutationFn: (k: string) => put("/admin/config", { [k]: null }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["admin", "config"] }),
  });

  const runTest = async (key: string, path: string, body: unknown, play = false) => {
    setBusy(key);
    try {
      const r = await post<TestResult>(path, body);
      setTests((t) => ({ ...t, [key]: r }));
      if (play && r.url) void player.play(r.url);
    } catch (e) {
      setTests((t) => ({ ...t, [key]: { ok: false, error: errorMessage(e) } }));
    } finally {
      setBusy(null);
    }
  };

  if (!cfg) return <Skeleton className="h-96" />;
  const field = (k: string, label: string, placeholder?: string) => (
    <div className="space-y-1.5">
      <Label htmlFor={k}>{label}</Label>
      <div className="flex gap-1.5">
        <Input id={k} value={String(form[k] ?? "")} placeholder={placeholder} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
        {k in cfg.overrides && <Button variant="ghost" size="sm" onClick={() => reset.mutate(k)} title="Reset to .env">Reset</Button>}
      </div>
    </div>
  );
  const select = (k: string, label: string, options: string[]) => (
    <div className="space-y-1.5">
      <Label htmlFor={k}>{label}</Label>
      <Select id={k} value={String(form[k] ?? "")} onChange={(e) => setForm({ ...form, [k]: e.target.value })}>
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </Select>
    </div>
  );
  const llmDefaults = cfg.options.default_models[String(form.llm_provider)] ?? {};

  return (
    <div className="space-y-4">
      <Card className="space-y-4 p-5">
        <h3 className="font-bold">Language model</h3>
        <div className="grid gap-4 sm:grid-cols-2">
          {select("llm_provider", "Provider", cfg.options.llm_providers)}
          {field("llm_base_url", "Base URL (OpenAI-compatible only)", "http://ollama:11434/v1")}
          {field("llm_model_conversation", "Conversation model (fast)", llmDefaults.conversation)}
          {field("llm_model_feedback", "Feedback model", llmDefaults.feedback)}
          {field("llm_model_content", "Lesson content model (strongest)", llmDefaults.content)}
          {field("llm_model_fallback", "Backup model when busy (“off” = none)",
            cfg.options.default_fallback_models[String(form.llm_provider)] ?? "off")}
          {field("daily_ai_budget_usd", "Daily budget per user (USD)")}
        </div>
        <div className="flex flex-wrap gap-2">
          {(["conversation", "feedback", "content"] as const).map((t) => (
            <Button key={t} variant="outline" size="sm" loading={busy === `llm-${t}`} onClick={() => runTest(`llm-${t}`, "/admin/test/llm", { task: t })}>
              <Play /> Test {t}
            </Button>
          ))}
        </div>
        {(["conversation", "feedback", "content"] as const).map((t) => <TestBadge key={t} r={tests[`llm-${t}`]} />)}
      </Card>

      <Card className="space-y-4 p-5">
        <h3 className="font-bold">Speech</h3>
        <div className="grid gap-4 sm:grid-cols-2">
          {select("tts_provider_lesson", "TTS for lessons", cfg.options.tts_providers)}
          {select("tts_provider_conversation", "TTS for conversations", cfg.options.tts_providers)}
          {field("tts_base_url", "TTS base URL (local / OpenAI-compatible)", "http://tts:8880/v1")}
          {field("tts_azure_region", "Azure region", "westeurope")}
          {select("stt_provider", "Speech-to-text provider", cfg.options.stt_providers)}
          {field("stt_model", "STT model", cfg.options.default_stt_models[String(form.stt_provider)])}
          {field("stt_base_url", "STT base URL (local / OpenAI-compatible)", "http://stt:8000/v1")}
          <div className="flex items-center justify-between gap-4 rounded-xl border p-3">
            <div>
              <Label htmlFor="combined">Combined Gemini call</Label>
              <p className="text-xs text-muted-foreground">Transcript + feedback in one request.</p>
            </div>
            <Switch id="combined" checked={!!form.stt_combined_feedback} onCheckedChange={(c) => setForm({ ...form, stt_combined_feedback: c })} />
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {LANG_CODES.map((l) => (
            <Button key={l} variant="outline" size="sm" loading={busy === `stt-${l}`} onClick={() => runTest(`stt-${l}`, "/admin/test/stt", { lang: l })}>
              <Play /> STT round-trip · {LANGS[l].name}
            </Button>
          ))}
        </div>
        {LANG_CODES.map((l) => <TestBadge key={l} r={tests[`stt-${l}`]} />)}
      </Card>

      <Card className="space-y-4 p-5">
        <div>
          <h3 className="font-bold">Compare voices</h3>
          <p className="text-sm text-muted-foreground">Play two voices side by side, then make one the default for that language.</p>
        </div>
        {LANG_CODES.map((l) => <VoiceCompare key={l} lang={l} cfg={cfg} provider={String(form.tts_provider_lesson)} />)}
      </Card>

      <Card className="space-y-4 p-5">
        <div>
          <h3 className="font-bold">API keys</h3>
          <p className="text-sm text-muted-foreground">Keys from .env are used by default. Keys entered here override them and are stored in the database. Leave blank to keep.</p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          {Object.entries(cfg.keys).filter(([p]) => p !== "local" && p !== "openai_compatible").map(([p, k]) => (
            <div key={p} className="space-y-1.5">
              <Label htmlFor={`key-${p}`} className="flex items-center gap-2">
                {p} {k.set ? <Badge tone="success">{k.masked || "set"} · {k.source}</Badge> : <Badge>not set</Badge>}
              </Label>
              <Input id={`key-${p}`} type="password" autoComplete="off" placeholder="Paste a new key" value={keys[p] ?? ""} onChange={(e) => setKeys({ ...keys, [p]: e.target.value })} />
            </div>
          ))}
        </div>
      </Card>

      <div className="sticky bottom-20 z-10 flex justify-end lg:bottom-4">
        <Button size="lg" loading={save.isPending} onClick={() => save.mutate()} className="shadow-lg">
          <Settings2 /> Save provider settings
        </Button>
      </div>
    </div>
  );
}

function VoiceCompare({ lang, cfg, provider }: { lang: (typeof LANG_CODES)[number]; cfg: Config; provider: string }) {
  const qc = useQueryClient();
  const current = cfg.voices[provider]?.[lang] ?? { female: "", male: "" };
  const options = provider === "google" ? cfg.options.google_voices[lang] : [current.female, current.male].filter(Boolean);
  const [a, setA] = React.useState(current.female);
  const [b, setB] = React.useState(current.male);
  React.useEffect(() => {
    setA(current.female);
    setB(current.male);
  }, [current.female, current.male]);
  const [busy, setBusy] = React.useState<string | null>(null);
  const play = async (voice: string) => {
    setBusy(voice);
    try {
      const r = await post<TestResult>("/admin/test/tts", { lang, voice });
      if (r.ok && r.url) await player.play(r.url);
      else toast.error(r.error ?? "TTS failed");
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };
  const use = async (voice: string, gender: "female" | "male") => {
    const voices = { ...((cfg.overrides.voices as Record<string, unknown>) ?? {}) } as Record<string, Record<string, Record<string, string>>>;
    voices[provider] = { ...(voices[provider] ?? {}), [lang]: { ...(voices[provider]?.[lang] ?? {}), [gender]: voice } };
    try {
      await put("/admin/config", { voices });
      toast.success(`${LANGS[lang].name} ${gender} voice set to ${voice}`);
      void qc.invalidateQueries({ queryKey: ["admin", "config"] });
    } catch (e) {
      toast.error(errorMessage(e));
    }
  };
  const column = (value: string, set: (v: string) => void) => (
    <div className="flex flex-1 flex-col gap-2">
      {provider === "google" ? (
        <Select value={value} onChange={(e) => set(e.target.value)} aria-label="Voice">
          {[...new Set([value, ...options])].map((v) => <option key={v} value={v}>{v.split("-").slice(-1)[0] || v}</option>)}
        </Select>
      ) : (
        <Input value={value} onChange={(e) => set(e.target.value)} aria-label="Voice" />
      )}
      <div className="flex gap-1.5">
        <Button size="sm" variant="soft" loading={busy === value} onClick={() => play(value)}><Play /> Play</Button>
        <Button size="sm" variant="ghost" onClick={() => use(value, "female")}>Female default</Button>
        <Button size="sm" variant="ghost" onClick={() => use(value, "male")}>Male default</Button>
      </div>
    </div>
  );
  return (
    <div className="rounded-xl border p-3">
      <p className="mb-2 text-sm font-semibold"><LangFlag lang={lang} /> {LANGS[lang].name} <span className="font-normal text-muted-foreground">· now {current.female} / {current.male}</span></p>
      <div className="flex flex-col gap-3 sm:flex-row">{column(a, setA)}{column(b, setB)}</div>
    </div>
  );
}

// ------------------------------------------------------------------ content

type ContentLesson = { id: number; slug: string; title: string; kind: string; status: string; version: number; edited: boolean; model_used: string | null; error: string | null; flags: number };

function LessonEditor({ id, onClose }: { id: number; onClose: () => void }) {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["admin", "lesson", id], queryFn: () => get<{ title: string; status: string; content: unknown; skeleton: unknown; error: string | null }>(`/admin/lessons/${id}`) });
  const [json, setJson] = React.useState("");
  React.useEffect(() => { if (data) setJson(JSON.stringify(data.content, null, 2)); }, [data]);
  const save = useMutation({
    mutationFn: () => put(`/admin/lessons/${id}`, { content: JSON.parse(json) }),
    onSuccess: () => { toast.success("Lesson saved"); void qc.invalidateQueries({ queryKey: ["admin"] }); onClose(); },
    onError: (e) => toast.error(e instanceof SyntaxError ? `Invalid JSON: ${e.message}` : errorMessage(e)),
  });
  const regen = useMutation({
    mutationFn: () => post(`/admin/lessons/${id}/regenerate`),
    onSuccess: () => { toast.success("Regeneration queued"); void qc.invalidateQueries({ queryKey: ["admin"] }); onClose(); },
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={data?.title ?? "Lesson"} description="Edit the generated JSON directly, or regenerate it from the skeleton." className="sm:max-w-3xl">
        {!data ? <Skeleton className="h-96" /> : (
          <>
            {data.error && <p className="mb-3 rounded-xl bg-danger-soft p-3 text-sm text-danger">{data.error}</p>}
            <details className="mb-3 text-sm"><summary className="cursor-pointer font-semibold">Skeleton</summary><pre className="mt-2 overflow-auto rounded-xl bg-muted p-3 text-xs">{JSON.stringify(data.skeleton, null, 2)}</pre></details>
            <Textarea className="h-[50vh] font-mono text-xs" value={json} onChange={(e) => setJson(e.target.value)} spellCheck={false} />
            <div className="mt-3 flex flex-wrap justify-end gap-2">
              <Button variant="outline" loading={regen.isPending} onClick={() => regen.mutate()}><Wand /> Regenerate</Button>
              <Button loading={save.isPending} onClick={() => save.mutate()} disabled={!data.content}>Save edits</Button>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

const STATUS_TONE: Record<string, "success" | "warning" | "danger" | "neutral" | "primary"> = { ready: "success", queued: "primary", generating: "warning", failed: "danger", pending: "neutral" };

function ContentTab() {
  const qc = useQueryClient();
  const [lang, setLang] = React.useState<string>("fr");
  const [editing, setEditing] = React.useState<number | null>(null);
  const { data } = useQuery({
    queryKey: ["admin", "content", lang],
    queryFn: () => get<{ levels: { cefr: string; units: { id: number; title: string; lessons: ContentLesson[] }[] }[]; counts: Record<string, number> }>(`/admin/content?lang=${lang}`),
    refetchInterval: 8000,
  });
  const pregen = useMutation({
    mutationFn: (body: { cefr?: string; unit_id?: number }) => post<{ queued: number }>("/admin/pregenerate", { lang, ...body }),
    onSuccess: (r) => { toast.success(`${r.queued} lessons queued`); void qc.invalidateQueries({ queryKey: ["admin", "content"] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const placement = useMutation({
    mutationFn: () => post<{ items: number }>(`/admin/placement/${lang}/regenerate`),
    onSuccess: (r) => toast.success(`Placement bank regenerated (${r.items} items)`),
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Select className="w-40" value={lang} onChange={(e) => setLang(e.target.value)} aria-label="Language">
          {LANG_CODES.map((l) => <option key={l} value={l}>{LANGS[l].name}</option>)}
        </Select>
        {data && Object.entries(data.counts).map(([s, n]) => <Badge key={s} tone={STATUS_TONE[s] ?? "neutral"}>{s}: {n}</Badge>)}
        <Button variant="outline" size="sm" className="ml-auto" loading={placement.isPending} onClick={() => placement.mutate()}><RefreshCw /> Placement bank</Button>
      </div>
      {!data ? <Skeleton className="h-96" /> : data.levels.map((lv) => (
        <details key={lv.cefr} className="rounded-2xl border bg-card" open={lv.cefr === "A1"}>
          <summary className="flex cursor-pointer items-center justify-between gap-3 px-4 py-3 font-bold">
            {lv.cefr === "PRE" ? "Writing systems" : lv.cefr}
            <Button size="sm" variant="ghost" onClick={(e) => { e.preventDefault(); pregen.mutate({ cefr: lv.cefr }); }}><Wand /> Pre-generate level</Button>
          </summary>
          <div className="divide-y border-t">
            {lv.units.map((u) => (
              <div key={u.id} className="px-4 py-3">
                <p className="mb-2 text-sm font-semibold text-muted-foreground">{u.title}</p>
                <div className="space-y-1">
                  {u.lessons.map((le) => (
                    <div key={le.id} className="flex items-center gap-2 text-sm">
                      <Badge tone={STATUS_TONE[le.status] ?? "neutral"}>{le.status}</Badge>
                      <span className="min-w-0 flex-1 truncate">{le.title}</span>
                      {le.edited && <Badge tone="primary">edited</Badge>}
                      {le.flags > 0 && <Badge tone="danger"><Flag className="size-3" /> {le.flags}</Badge>}
                      {le.version > 0 && <span className="hidden text-xs text-muted-foreground sm:inline">v{le.version}</span>}
                      <Button size="icon-sm" variant="ghost" onClick={() => setEditing(le.id)} aria-label={`Open ${le.title}`}><Settings2 /></Button>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </details>
      ))}
      {editing && <LessonEditor id={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

// ------------------------------------------------------------------ flags

function FlagsTab() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["admin", "flags"], queryFn: () => get<{ id: number; target_type: string; target_id: number; reason: string; created_at: string; user: string | null; lesson_id: number | null; context: Record<string, unknown> | null }[]>("/admin/flags") });
  const [editing, setEditing] = React.useState<number | null>(null);
  const setStatus = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) => patch(`/admin/flags/${id}`, { status }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["admin", "flags"] }),
  });
  if (!data) return <Skeleton className="h-64" />;
  if (!data.length) return <EmptyState icon={<Flag />} title="No open reports">When someone taps “Report a problem”, it shows up here.</EmptyState>;
  return (
    <div className="space-y-3">
      {data.map((f) => (
        <Card key={f.id} className="p-4">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Badge tone="danger">{f.target_type}</Badge>
            <span className="text-muted-foreground">{f.user ?? "someone"} · {timeAgo(f.created_at)}</span>
          </div>
          <p className="mt-2 font-medium">{f.reason}</p>
          {f.context && <pre className="mt-2 max-h-40 overflow-auto rounded-xl bg-muted p-3 text-xs">{JSON.stringify(f.context, null, 2)}</pre>}
          <div className="mt-3 flex flex-wrap gap-2">
            {f.lesson_id && <Button size="sm" variant="outline" onClick={() => setEditing(f.lesson_id)}><Settings2 /> Open lesson</Button>}
            <Button size="sm" variant="soft" onClick={() => setStatus.mutate({ id: f.id, status: "resolved" })}>Resolved</Button>
            <Button size="sm" variant="ghost" onClick={() => setStatus.mutate({ id: f.id, status: "dismissed" })}>Dismiss</Button>
          </div>
        </Card>
      ))}
      {editing && <LessonEditor id={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

// ------------------------------------------------------------------ users

function UsersTab() {
  const qc = useQueryClient();
  const { data: me } = useMe();
  const { data: users } = useQuery({ queryKey: ["admin", "users"], queryFn: () => get<{ id: number; email: string; display_name: string; role: string; is_active: boolean; created_at: string; last_seen_at: string | null; cost_30d: number }[]>("/admin/users") });
  const { data: invites } = useQuery({ queryKey: ["admin", "invites"], queryFn: () => get<{ id: number; url: string; note: string | null; expires_at: string; used_by: string | null; status: string }[]>("/admin/invites") });
  const [note, setNote] = React.useState("");
  const invalidate = () => { void qc.invalidateQueries({ queryKey: ["admin", "users"] }); void qc.invalidateQueries({ queryKey: ["admin", "invites"] }); };
  const createInvite = useMutation({
    mutationFn: () => post<{ url: string }>("/admin/invites", { note: note || null }),
    onSuccess: (r) => { const url = `${window.location.origin}${r.url}`; void navigator.clipboard?.writeText(url).catch(() => {}); toast.success("Invite link created and copied", { description: url }); setNote(""); invalidate(); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const patchUser = useMutation({ mutationFn: ({ id, body }: { id: number; body: object }) => patch(`/admin/users/${id}`, body), onSuccess: invalidate, onError: (e) => toast.error(errorMessage(e)) });
  const removeUser = useMutation({ mutationFn: (id: number) => del(`/admin/users/${id}`), onSuccess: invalidate, onError: (e) => toast.error(errorMessage(e)) });
  const revoke = useMutation({ mutationFn: (id: number) => del(`/admin/invites/${id}`), onSuccess: invalidate });
  return (
    <div className="space-y-4">
      <Card className="p-5">
        <h3 className="font-bold">Invite someone</h3>
        <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); createInvite.mutate(); }}>
          <Input placeholder="Note, e.g. “Mum”" value={note} onChange={(e) => setNote(e.target.value)} />
          <Button type="submit" loading={createInvite.isPending}>Create link</Button>
        </form>
        <div className="mt-4 space-y-1.5">
          {invites?.map((i) => (
            <div key={i.id} className="flex items-center gap-2 text-sm">
              <Badge tone={i.status === "active" ? "success" : "neutral"}>{i.status}</Badge>
              <span className="min-w-0 flex-1 truncate">{i.note ?? "Invite"}{i.used_by && ` → ${i.used_by}`}</span>
              {i.status === "active" && (
                <>
                  <Button size="icon-sm" variant="ghost" aria-label="Copy link" onClick={() => { void navigator.clipboard?.writeText(`${window.location.origin}${i.url}`); toast.success("Copied"); }}><Copy /></Button>
                  <Button size="icon-sm" variant="ghost" aria-label="Revoke" onClick={() => revoke.mutate(i.id)}><Trash /></Button>
                </>
              )}
            </div>
          ))}
        </div>
      </Card>
      <Card className="overflow-x-auto p-0">
        <table className="w-full min-w-[560px] text-sm">
          <thead className="bg-muted text-xs text-muted-foreground"><tr>{["User", "Role", "Last seen", "AI cost (30d)", ""].map((h) => <th key={h} className="px-3 py-2 text-left font-semibold">{h}</th>)}</tr></thead>
          <tbody>
            {users?.map((u) => (
              <tr key={u.id} className={cn("border-t", !u.is_active && "opacity-50")}>
                <td className="px-3 py-2"><span className="font-semibold">{u.display_name}</span><span className="block text-xs text-muted-foreground">{u.email}</span></td>
                <td className="px-3 py-2"><Badge tone={u.role === "admin" ? "primary" : "neutral"}>{u.role}</Badge></td>
                <td className="px-3 py-2 text-muted-foreground">{u.last_seen_at ? timeAgo(u.last_seen_at) : "—"}</td>
                <td className="px-3 py-2 tabular-nums">{money(u.cost_30d)}</td>
                <td className="px-3 py-2 text-right">
                  {u.id !== me?.id && (
                    <div className="flex justify-end gap-1">
                      <Button size="sm" variant="ghost" onClick={() => patchUser.mutate({ id: u.id, body: { role: u.role === "admin" ? "user" : "admin" } })}>{u.role === "admin" ? "Make user" : "Make admin"}</Button>
                      <Button size="sm" variant="ghost" onClick={() => patchUser.mutate({ id: u.id, body: { is_active: !u.is_active } })}>{u.is_active ? "Disable" : "Enable"}</Button>
                      <Button size="icon-sm" variant="ghost" aria-label="Delete user" onClick={() => confirm(`Delete ${u.email} and all their data?`) && removeUser.mutate(u.id)}><Trash /></Button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

// ------------------------------------------------------------------ jobs

function JobsTab() {
  const { data } = useQuery({
    queryKey: ["admin", "jobs"],
    queryFn: () => get<{ queued: number; in_progress: number; recent: { at: string; event: string; [k: string]: unknown }[]; lessons: Record<string, number> }>("/admin/jobs"),
    refetchInterval: 4000,
  });
  if (!data) return <Skeleton className="h-64" />;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Card className="p-4"><p className="text-xs font-semibold text-muted-foreground">Queued</p><p className="mt-1 text-2xl font-black">{data.queued}</p></Card>
        <Card className="p-4"><p className="text-xs font-semibold text-muted-foreground">Running</p><p className="mt-1 text-2xl font-black">{data.in_progress}</p></Card>
        <Card className="p-4 sm:col-span-2"><p className="text-xs font-semibold text-muted-foreground">Lessons</p>
          <div className="mt-2 flex flex-wrap gap-1.5">{Object.entries(data.lessons).map(([s, n]) => <Badge key={s} tone={STATUS_TONE[s] ?? "neutral"}>{s}: {n}</Badge>)}</div></Card>
      </div>
      <Card className="p-0">
        <h3 className="border-b px-4 py-3 font-bold">Recent worker events</h3>
        {data.recent.length ? (
          <ul className="divide-y text-sm">
            {data.recent.map((e, i) => {
              const { at, event, ...rest } = e;
              return (
                <li key={i} className="flex gap-3 px-4 py-2">
                  <span className="w-20 shrink-0 text-xs text-muted-foreground">{timeAgo(at)}</span>
                  <span className={cn("font-semibold", event.includes("failed") && "text-danger")}>{event}</span>
                  <span className="min-w-0 flex-1 truncate text-muted-foreground">{Object.entries(rest).map(([k, v]) => `${k}=${String(v)}`).join(" ")}</span>
                </li>
              );
            })}
          </ul>
        ) : <p className="p-4 text-sm text-muted-foreground">No events yet.</p>}
      </Card>
    </div>
  );
}

export default function AdminPage() {
  const { data: me } = useMe();
  if (me && me.role !== "admin") {
    return <EmptyState icon={<Server />} title="Admins only"><Link href="/" className="font-semibold text-primary-strong">Back home</Link></EmptyState>;
  }
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight sm:text-3xl">Admin</h1>
        <p className="mt-1 text-muted-foreground">Providers, costs, content and people on this server.</p>
      </div>
      <Tabs defaultValue="usage">
        <div className="-mx-4 overflow-x-auto px-4 scrollbar-none sm:mx-0 sm:px-0">
          <TabsList>
            <TabsTrigger value="usage"><Activity className="size-4" /> Usage</TabsTrigger>
            <TabsTrigger value="providers"><Settings2 className="size-4" /> Providers</TabsTrigger>
            <TabsTrigger value="content"><Wand className="size-4" /> Content</TabsTrigger>
            <TabsTrigger value="flags"><Flag className="size-4" /> Reports</TabsTrigger>
            <TabsTrigger value="users"><Users className="size-4" /> Users</TabsTrigger>
            <TabsTrigger value="jobs"><Server className="size-4" /> Jobs</TabsTrigger>
          </TabsList>
        </div>
        <TabsContent value="usage" className="mt-5"><UsageTab /></TabsContent>
        <TabsContent value="providers" className="mt-5"><ProvidersTab /></TabsContent>
        <TabsContent value="content" className="mt-5"><ContentTab /></TabsContent>
        <TabsContent value="flags" className="mt-5"><FlagsTab /></TabsContent>
        <TabsContent value="users" className="mt-5"><UsersTab /></TabsContent>
        <TabsContent value="jobs" className="mt-5"><JobsTab /></TabsContent>
      </Tabs>
    </div>
  );
}
