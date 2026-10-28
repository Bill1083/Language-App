"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bell,
  ChartColumn,
  Compass,
  Download,
  Library,
  LogOut,
  NotebookPen,
  Plus,
  Server,
  ShieldCheck,
  Trash,
} from "lucide-react";
import Link from "next/link";
import { useTheme } from "next-themes";
import * as React from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Flag } from "@/components/flag";
import { Card, Input, Label, Segmented, Select, Switch } from "@/components/ui/primitives";
import { useMe, useUpdateSettings } from "@/hooks/use-me";
import { del, errorMessage, get, patch, post } from "@/lib/api";
import { CEFR_LABEL, CEFR_LEVELS, LANGS } from "@/lib/languages";
import type { UserSettings } from "@/lib/types";

function Section({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <Card className="p-5 sm:p-6">
      <h2 className="text-lg font-bold">{title}</h2>
      {description && <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>}
      <div className="mt-5 space-y-5">{children}</div>
    </Card>
  );
}

function Row({ label, hint, children, htmlFor }: { label: string; hint?: string; children: React.ReactNode; htmlFor?: string }) {
  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-6">
      <div className="min-w-0">
        <Label htmlFor={htmlFor}>{label}</Label>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

function urlBase64ToUint8Array(base64: string) {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const raw = atob((base64 + padding).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

function Reminders({ settings, set }: { settings: UserSettings; set: (s: Partial<UserSettings>) => void }) {
  const [busy, setBusy] = React.useState(false);
  const supported = typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window;
  const enable = async (on: boolean) => {
    if (!on) {
      set({ reminders: false });
      const reg = await navigator.serviceWorker.getRegistration();
      const sub = await reg?.pushManager.getSubscription();
      if (sub) {
        await post("/push/unsubscribe", { endpoint: sub.endpoint }).catch(() => {});
        await sub.unsubscribe();
      }
      return;
    }
    setBusy(true);
    try {
      if ((await Notification.requestPermission()) !== "granted") throw new Error("Notifications are blocked for this site.");
      const reg = await navigator.serviceWorker.ready;
      const { public_key } = await get<{ public_key: string }>("/push/key");
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(public_key) });
      await post("/push/subscribe", sub.toJSON());
      set({ reminders: true, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone });
      toast.success("Daily reminders are on for this device.");
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Row label="Daily reminder" hint={supported ? "A nudge if you haven't practised yet that day." : "Install the app (or use a browser with push support) to get reminders."}>
        <Switch checked={settings.reminders} disabled={!supported || busy} onCheckedChange={(c) => void enable(c)} aria-label="Daily reminder" />
      </Row>
      {settings.reminders && (
        <Row label="Remind me at" htmlFor="reminder-hour">
          <div className="flex gap-2">
            <Select id="reminder-hour" className="w-32" value={settings.reminder_hour} onChange={(e) => set({ reminder_hour: Number(e.target.value) })}>
              {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{`${h.toString().padStart(2, "0")}:00`}</option>)}
            </Select>
            <Button variant="outline" onClick={() => post("/push/test").then(() => toast.success("Test sent")).catch((e) => toast.error(errorMessage(e)))}>
              Test
            </Button>
          </div>
        </Row>
      )}
    </>
  );
}

export default function ProfilePage() {
  const { data: me } = useMe();
  const update = useUpdateSettings();
  const { setTheme } = useTheme();
  const qc = useQueryClient();
  const [name, setName] = React.useState("");
  const [pw, setPw] = React.useState({ current: "", next: "" });
  const { data: meta } = useQuery({ queryKey: ["meta"], queryFn: () => get<{ stt_provider: string; recording_retention_days: number; store_recordings: boolean }>("/meta") });
  React.useEffect(() => setName(me?.display_name ?? ""), [me?.display_name]);

  const saveName = useMutation({
    mutationFn: () => patch("/auth/me", { display_name: name }),
    onSuccess: () => { toast.success("Saved"); void qc.invalidateQueries({ queryKey: ["me"] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const changePw = useMutation({
    mutationFn: () => post("/auth/me/password", { current: pw.current, new: pw.next }),
    onSuccess: () => { toast.success("Password changed. Other devices were signed out."); setPw({ current: "", next: "" }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const setLevel = useMutation({
    mutationFn: ({ lang, level }: { lang: string; level: string }) => patch(`/enrolments/${lang}`, { current_level: level }),
    onSuccess: () => { toast.success("Level updated"); void qc.invalidateQueries(); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const wipe = useMutation({
    mutationFn: () => del<{ deleted: number }>("/auth/me/recordings"),
    onSuccess: (r) => toast.success(`Deleted ${r.deleted} recordings`),
    onError: (e) => toast.error(errorMessage(e)),
  });

  if (!me) return null;
  const s = me.settings;
  const set = (patchSettings: Partial<UserSettings>) => update.mutate(patchSettings);
  const hasJa = me.enrolments.some((e) => e.language_code === "ja");
  const logout = async () => {
    await post("/auth/logout").catch(() => {});
    window.location.href = "/login";
  };

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div className="flex items-center gap-4">
        <span className="flex size-16 items-center justify-center rounded-2xl bg-primary text-2xl font-black text-primary-foreground">
          {me.display_name.slice(0, 1).toUpperCase()}
        </span>
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-extrabold tracking-tight">{me.display_name}</h1>
          <p className="truncate text-sm text-muted-foreground">{me.email}{me.role === "admin" && " · admin"}</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4 lg:hidden">
        {[
          { href: "/words", label: "Vocabulary", icon: Library },
          { href: "/grammar", label: "Grammar", icon: NotebookPen },
          { href: "/stats", label: "Stats", icon: ChartColumn },
          ...(me.role === "admin" ? [{ href: "/admin", label: "Admin", icon: Server }] : []),
        ].map(({ href, label, icon: Icon }) => (
          <Link key={href} href={href} className="flex items-center gap-2.5 rounded-2xl border bg-card px-4 py-3 text-sm font-semibold transition hover:bg-muted">
            <Icon className="size-5 text-primary" /> {label}
          </Link>
        ))}
      </div>

      <Section title="Languages" description="Your courses. Changing a level unlocks everything up to it.">
        {me.enrolments.map((e) => (
          <div key={e.language_code} className="flex flex-wrap items-center gap-3" data-lang={e.language_code}>
            <span className="text-2xl"><Flag lang={e.language_code} /></span>
            <span className="min-w-0 flex-1">
              <span className="block font-semibold">{LANGS[e.language_code].name}</span>
              <span className="block text-xs text-muted-foreground">{CEFR_LABEL[e.current_level]}</span>
            </span>
            <Select
              className="w-24"
              value={e.current_level}
              aria-label={`${LANGS[e.language_code].name} level`}
              onChange={(ev) => {
                const level = ev.target.value;
                if (confirm(`Set ${LANGS[e.language_code].name} to ${level}? Levels up to ${level} will be unlocked.`)) {
                  setLevel.mutate({ lang: e.language_code, level });
                }
              }}
            >
              {CEFR_LEVELS.map((l) => <option key={l} value={l}>{l}</option>)}
            </Select>
            <Button asChild variant="outline" size="sm">
              <Link href={`/placement/${e.language_code}`}><Compass /> Placement</Link>
            </Button>
          </div>
        ))}
        {me.enrolments.length < 3 && (
          <Button asChild variant="soft"><Link href="/onboarding?add=1"><Plus /> Add a language</Link></Button>
        )}
      </Section>

      <Section title="Goals">
        <Row label="Daily goal" hint="Counts XP or minutes across all your languages.">
          <div className="flex gap-2">
            <Segmented size="sm" value={s.daily_goal_type} ariaLabel="Goal type"
              onChange={(v) => set({ daily_goal_type: v, daily_goal_value: v === "xp" ? 30 : 10 })}
              options={[{ value: "xp", label: "XP" }, { value: "minutes", label: "Minutes" }]} />
            <Select className="w-28" value={s.daily_goal_value} aria-label="Goal amount" onChange={(e) => set({ daily_goal_value: Number(e.target.value) })}>
              {(s.daily_goal_type === "xp" ? [10, 20, 30, 50, 80, 120] : [5, 10, 15, 20, 30, 45, 60]).map((v) => <option key={v} value={v}>{v}</option>)}
            </Select>
          </div>
        </Row>
        <Row label="New review cards per day" hint="How many new words enter your daily reviews.">
          <Select className="w-28" value={s.new_cards_per_day} aria-label="New cards per day" onChange={(e) => set({ new_cards_per_day: Number(e.target.value) })}>
            {[5, 10, 15, 20, 30, 50].map((v) => <option key={v} value={v}>{v}</option>)}
          </Select>
        </Row>
      </Section>

      <Section title="Voice & sound">
        <Row label="Voice">
          <Segmented size="sm" value={s.voice_gender} onChange={(v) => set({ voice_gender: v })} ariaLabel="Voice"
            options={[{ value: "female", label: "Female" }, { value: "male", label: "Male" }]} />
        </Row>
        <Row label="Speech speed">
          <Segmented size="sm" value={s.speech_speed} onChange={(v) => set({ speech_speed: v })} ariaLabel="Speech speed"
            options={[{ value: 0.75, label: "0.75×" }, { value: 1, label: "1×" }, { value: 1.25, label: "1.25×" }]} />
        </Row>
        <Row label="Sound effects" hint="Chimes for right and wrong answers." htmlFor="sound">
          <Switch id="sound" checked={s.sound} onCheckedChange={(c) => set({ sound: c })} />
        </Row>
        <Row label="Conversation feedback" hint="How picky the per-message feedback is.">
          <Segmented size="sm" value={s.strictness} onChange={(v) => set({ strictness: v })} ariaLabel="Feedback strictness"
            options={[{ value: "gentle", label: "Gentle" }, { value: "normal", label: "Normal" }, { value: "strict", label: "Strict" }]} />
        </Row>
      </Section>

      <Section title="Display">
        <Row label="Theme">
          <Segmented size="sm" value={s.theme} ariaLabel="Theme"
            onChange={(v) => { setTheme(v); set({ theme: v }); }}
            options={[{ value: "dark", label: "Dark" }, { value: "light", label: "Light" }, { value: "system", label: "System" }]} />
        </Row>
        <Row label="Colour-code noun gender" hint="Masculine in blue, feminine in pink (French and Italian)." htmlFor="gender-colors">
          <Switch id="gender-colors" checked={s.gender_colors} onCheckedChange={(c) => set({ gender_colors: c })} />
        </Row>
        {hasJa && (
          <>
            <Row label="Furigana" hint="Readings above kanji.">
              <Segmented size="sm" value={s.furigana} onChange={(v) => set({ furigana: v })} ariaLabel="Furigana"
                options={[{ value: "always", label: "Always" }, { value: "new", label: "New kanji" }, { value: "never", label: "Never" }]} />
            </Row>
            <Row label="Romaji" hint="Auto shows it for your first units, then hides it.">
              <Segmented size="sm" value={s.romaji} onChange={(v) => set({ romaji: v })} ariaLabel="Romaji"
                options={[{ value: "auto", label: "Auto" }, { value: "on", label: "On" }, { value: "off", label: "Off" }]} />
            </Row>
          </>
        )}
      </Section>

      <Section title="Notifications">
        <Reminders settings={s} set={set} />
      </Section>

      <Section title="Account">
        <form className="flex flex-col gap-2 sm:flex-row sm:items-end" onSubmit={(e) => { e.preventDefault(); saveName.mutate(); }}>
          <div className="flex-1 space-y-1.5">
            <Label htmlFor="display-name">Display name</Label>
            <Input id="display-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <Button type="submit" variant="outline" disabled={!name.trim() || name === me.display_name} loading={saveName.isPending}>Save</Button>
        </form>
        <form className="grid gap-2 sm:grid-cols-[1fr_1fr_auto] sm:items-end" onSubmit={(e) => { e.preventDefault(); changePw.mutate(); }}>
          <div className="space-y-1.5">
            <Label htmlFor="pw-current">Current password</Label>
            <Input id="pw-current" type="password" autoComplete="current-password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="pw-new">New password</Label>
            <Input id="pw-new" type="password" autoComplete="new-password" minLength={8} value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} />
          </div>
          <Button type="submit" variant="outline" disabled={!pw.current || pw.next.length < 8} loading={changePw.isPending}>Change</Button>
        </form>
      </Section>

      <Section title="Privacy & data">
        <div className="flex gap-3 rounded-xl bg-muted/60 p-3.5 text-sm text-muted-foreground">
          <ShieldCheck className="mt-0.5 size-5 shrink-0 text-success" />
          <p>
            Voice recordings go to {meta?.stt_provider ?? "the speech provider"} for transcription only.{" "}
            {meta?.store_recordings === false
              ? "This server keeps transcripts only — recordings are deleted right after transcription."
              : `Recordings are kept on this server for ${meta?.recording_retention_days ?? 30} days so you can replay them.`}
          </p>
        </div>
        <Row label="Delete all my recordings" hint="Transcripts and feedback are kept.">
          <Button variant="outline" loading={wipe.isPending} onClick={() => confirm("Delete all of your voice recordings?") && wipe.mutate()}>
            <Trash /> Delete
          </Button>
        </Row>
        <Row label="Export your data" hint="Progress, vocabulary, reviews and conversations.">
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline" size="sm"><a href="/api/v1/export/json" download><Download /> JSON</a></Button>
            <Button asChild variant="outline" size="sm"><a href="/api/v1/export/vocab.csv" download><Download /> Vocab CSV</a></Button>
            <Button asChild variant="outline" size="sm"><a href="/api/v1/export/anki.csv" download><Download /> Anki</a></Button>
          </div>
        </Row>
      </Section>

      <Button variant="ghost" className="w-full text-danger hover:bg-danger-soft" onClick={logout}>
        <LogOut /> Sign out
      </Button>
      <p className="pb-4 text-center text-xs text-muted-foreground">
        <Bell className="mr-1 inline size-3" /> Parlo · self-hosted · your keys, your data
      </p>
    </div>
  );
}
