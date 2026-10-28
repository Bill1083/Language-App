"use client";

import {
  BookOpen,
  ChartColumn,
  Check,
  ChevronDown,
  Flame,
  House,
  Layers,
  Library,
  LogOut,
  MessageCircle,
  NotebookPen,
  Plus,
  Server,
  Settings,
  User,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import * as React from "react";

import { useDashboard, useDeckStats } from "@/hooks/queries";
import { useLanguage } from "@/hooks/use-language";
import { useMe } from "@/hooks/use-me";
import { post } from "@/lib/api";
import { LANGS } from "@/lib/languages";
import { cn } from "@/lib/utils";

import { Logo, LogoMark } from "./brand";
import { Flag } from "./flag";
import { ProgressRing } from "./progress-ring";
import { Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from "./ui/overlay";

const PRIMARY = [
  { href: "/", label: "Home", icon: House },
  { href: "/learn", label: "Learn", icon: BookOpen },
  { href: "/talk", label: "Talk", icon: MessageCircle },
  { href: "/review", label: "Review", icon: Layers },
  { href: "/profile", label: "Profile", icon: User },
];

const SECONDARY = [
  { href: "/words", label: "Vocabulary", icon: Library },
  { href: "/grammar", label: "Grammar", icon: NotebookPen },
  { href: "/stats", label: "Stats", icon: ChartColumn },
];

function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

export function LanguageSwitcher({ compact }: { compact?: boolean }) {
  const { lang, enrolment, enrolments, setLang } = useLanguage();
  const router = useRouter();
  if (!lang || !enrolment) return null;
  return (
    <Menu>
      <MenuTrigger
        className="flex items-center gap-2 rounded-xl border bg-card px-2.5 py-1.5 text-sm font-semibold transition hover:bg-muted"
        aria-label={`Current language: ${LANGS[lang].name}. Switch language`}
      >
        <span className="text-lg leading-none"><Flag lang={lang} /></span>
        {!compact && <span>{LANGS[lang].name}</span>}
        <span className="rounded-md bg-primary-soft px-1.5 py-0.5 text-[11px] font-bold text-primary-strong">
          {enrolment.current_level}
        </span>
        <ChevronDown className="size-4 text-muted-foreground" />
      </MenuTrigger>
      <MenuContent align="start">
        <MenuLabel>Your languages</MenuLabel>
        {enrolments.map((e) => (
          <MenuItem key={e.language_code} onSelect={() => setLang(e.language_code)}>
            <span className="text-lg leading-none"><Flag lang={e.language_code} /></span>
            <span className="flex-1">{LANGS[e.language_code].name}</span>
            <span className="text-xs text-muted-foreground">{e.current_level}</span>
            {e.language_code === lang && <Check className="!text-primary" />}
          </MenuItem>
        ))}
        {enrolments.length < 3 && (
          <>
            <MenuSeparator />
            <MenuItem onSelect={() => router.push("/onboarding?add=1")}>
              <Plus /> Add a language
            </MenuItem>
          </>
        )}
      </MenuContent>
    </Menu>
  );
}

function DailyChips() {
  const { lang } = useLanguage();
  const { data } = useDashboard(lang);
  const daily = data?.daily;
  if (!daily) return <div className="h-9 w-28" />;
  return (
    <div className="flex items-center gap-2">
      <Link
        href="/stats"
        className={cn(
          "flex items-center gap-1 rounded-xl px-2 py-1.5 text-sm font-bold transition hover:bg-muted",
          daily.active_today ? "text-flame" : "text-muted-foreground",
        )}
        aria-label={`${daily.streak} day streak`}
        title={daily.active_today ? "Streak extended today" : "Practise today to extend your streak"}
      >
        <Flame className={cn("size-5", daily.active_today && "fill-flame/25")} />
        {daily.streak}
      </Link>
      <Link
        href="/"
        className="flex items-center gap-1.5 rounded-xl px-1.5 py-1 text-sm font-semibold text-muted-foreground transition hover:bg-muted"
        aria-label={`Daily goal ${Math.round(daily.goal_progress * 100)}% complete`}
      >
        <ProgressRing value={daily.goal_progress} size={26} stroke={3.5} done={daily.goal_met} />
        <span className="hidden tabular-nums sm:inline">
          {daily.goal_type === "xp" ? daily.xp_today : daily.minutes_today}/{daily.goal_value}
          <span className="ml-0.5 text-xs">{daily.goal_type === "xp" ? "XP" : "min"}</span>
        </span>
      </Link>
    </div>
  );
}

function UserMenu() {
  const { data: me } = useMe();
  const router = useRouter();
  if (!me) return null;
  const logout = async () => {
    await post("/auth/logout").catch(() => {});
    window.location.href = "/login";
  };
  return (
    <Menu>
      <MenuTrigger
        className="flex size-9 items-center justify-center rounded-full bg-primary-soft text-sm font-bold text-primary-strong transition hover:brightness-105"
        aria-label="Account menu"
      >
        {me.display_name.slice(0, 1).toUpperCase()}
      </MenuTrigger>
      <MenuContent align="end">
        <MenuLabel>
          {me.display_name}
          <div className="truncate font-normal">{me.email}</div>
        </MenuLabel>
        <MenuSeparator />
        <MenuItem onSelect={() => router.push("/profile")}>
          <Settings /> Settings
        </MenuItem>
        {SECONDARY.map((s) => (
          <MenuItem key={s.href} onSelect={() => router.push(s.href)}>
            <s.icon /> {s.label}
          </MenuItem>
        ))}
        {me.role === "admin" && (
          <MenuItem onSelect={() => router.push("/admin")}>
            <Server /> Admin
          </MenuItem>
        )}
        <MenuSeparator />
        <MenuItem onSelect={logout}>
          <LogOut /> Sign out
        </MenuItem>
      </MenuContent>
    </Menu>
  );
}

function ReviewBadge() {
  const { lang } = useLanguage();
  const { data } = useDeckStats(lang);
  const n = (data?.counts.due ?? 0) + (data?.counts.new ?? 0);
  if (!n) return null;
  return (
    <span className="ml-auto min-w-5 rounded-full bg-primary px-1.5 text-center text-[11px] font-bold leading-5 text-primary-foreground">
      {n > 99 ? "99+" : n}
    </span>
  );
}

function Sidebar() {
  const pathname = usePathname();
  const { data: me } = useMe();
  const items = [...SECONDARY, ...(me?.role === "admin" ? [{ href: "/admin", label: "Admin", icon: Server }] : [])];
  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r bg-card/60 px-3 py-5 backdrop-blur lg:flex">
      <Link href="/" className="mb-7 px-3">
        <Logo />
      </Link>
      <nav className="flex flex-col gap-1" aria-label="Main">
        {PRIMARY.map(({ href, label, icon: Icon }) => {
          const active = isActive(pathname, href);
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-3 rounded-xl px-3 py-2.5 text-[15px] font-semibold text-muted-foreground transition hover:bg-muted hover:text-foreground",
                active && "bg-primary-soft text-primary-strong hover:bg-primary-soft hover:text-primary-strong",
              )}
            >
              <Icon className="size-5" />
              {label}
              {href === "/review" && <ReviewBadge />}
            </Link>
          );
        })}
      </nav>
      <div className="mx-3 my-4 h-px bg-border" />
      <nav className="flex flex-col gap-1" aria-label="More">
        {items.map(({ href, label, icon: Icon }) => {
          const active = isActive(pathname, href);
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium text-muted-foreground transition hover:bg-muted hover:text-foreground",
                active && "bg-muted text-foreground",
              )}
            >
              <Icon className="size-[18px]" />
              {label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}

function BottomNav() {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-30 border-t bg-card/90 backdrop-blur-lg safe-bottom lg:hidden"
    >
      <div className="mx-auto grid h-16 max-w-lg grid-cols-5">
        {PRIMARY.map(({ href, label, icon: Icon }) => {
          const active = isActive(pathname, href);
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "relative flex flex-col items-center justify-center gap-0.5 text-[11px] font-semibold text-muted-foreground transition",
                active && "text-primary-strong",
              )}
            >
              <span className={cn("flex h-7 w-12 items-center justify-center rounded-full transition", active && "bg-primary-soft")}>
                <Icon className="size-5" />
              </span>
              {label}
              {href === "/review" && (
                <span className="absolute right-[18%] top-1.5">
                  <ReviewBadge />
                </span>
              )}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-dvh">
      <Sidebar />
      <div className="lg:pl-60">
        <header className="sticky top-0 z-20 border-b bg-background/85 backdrop-blur-lg safe-top">
          <div className="mx-auto flex h-14 max-w-5xl items-center gap-3 px-4 sm:px-6">
            <Link href="/" className="lg:hidden" aria-label="Home">
              <LogoMark className="size-7" />
            </Link>
            <LanguageSwitcher />
            <div className="ml-auto flex items-center gap-1.5">
              <DailyChips />
              <UserMenu />
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-5xl px-4 pb-28 pt-5 sm:px-6 lg:pb-12">{children}</main>
      </div>
      <BottomNav />
    </div>
  );
}
