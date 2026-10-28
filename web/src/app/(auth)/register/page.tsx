"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, Input, Label, Skeleton } from "@/components/ui/primitives";
import { errorMessage, get, post } from "@/lib/api";
import type { Me } from "@/lib/types";

type Status = { needs_setup: boolean; registration_mode: string; invite_valid: boolean | null };

function RegisterForm() {
  const router = useRouter();
  const params = useSearchParams();
  const invite = params.get("invite");
  const qc = useQueryClient();
  const { data: status, isLoading } = useQuery({
    queryKey: ["auth-status", invite],
    queryFn: () => get<Status>(`/auth/status${invite ? `?invite=${encodeURIComponent(invite)}` : ""}`),
  });
  const [form, setForm] = React.useState({ display_name: "", email: "", password: "" });
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const me = await post<Me>("/auth/register", {
        ...form,
        invite,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      });
      qc.setQueryData(["me"], me);
      router.replace("/onboarding");
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  if (isLoading || !status) return <Skeleton className="h-96" />;

  const allowed = status.needs_setup || status.registration_mode === "open" || status.invite_valid;
  if (!allowed) {
    return (
      <Card className="p-6 text-center">
        <h1 className="text-xl font-bold">Invite needed</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {invite
            ? "This invite link is invalid or has expired. Ask the admin for a new one."
            : status.registration_mode === "closed"
              ? "Registration is closed on this server."
              : "Accounts on this server are invite-only. Ask the admin for an invite link."}
        </p>
        <Button asChild variant="outline" className="mt-5 w-full">
          <Link href="/login">Back to sign in</Link>
        </Button>
      </Card>
    );
  }

  return (
    <Card className="p-6 shadow-xl shadow-black/5">
      {status.needs_setup ? (
        <>
          <div className="mb-3 inline-flex items-center gap-1.5 rounded-full bg-primary-soft px-2.5 py-1 text-xs font-semibold text-primary-strong">
            <ShieldCheck className="size-3.5" /> First-time setup
          </div>
          <h1 className="text-xl font-bold tracking-tight">Create the admin account</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            You&apos;re the first person here, so this account manages the server. You can invite others later.
          </p>
        </>
      ) : (
        <>
          <h1 className="text-xl font-bold tracking-tight">Create your account</h1>
          <p className="mt-1 text-sm text-muted-foreground">A few seconds and you&apos;re learning.</p>
        </>
      )}
      <form onSubmit={submit} className="mt-6 space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="name">Your name</Label>
          <Input id="name" required autoComplete="given-name" value={form.display_name}
            onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="email">Email</Label>
          <Input id="email" type="email" required autoComplete="email" value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="password">Password</Label>
          <Input id="password" type="password" required minLength={8} autoComplete="new-password" value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })} />
          <p className="text-xs text-muted-foreground">At least 8 characters.</p>
        </div>
        {error && (
          <p className="rounded-xl bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">
            {error}
          </p>
        )}
        <Button type="submit" size="lg" className="w-full" loading={busy}>
          Create account
        </Button>
      </form>
      {!status.needs_setup && (
        <p className="mt-5 text-center text-sm text-muted-foreground">
          Already have an account?{" "}
          <Link href="/login" className="font-semibold text-primary-strong hover:underline">
            Sign in
          </Link>
        </p>
      )}
    </Card>
  );
}

export default function RegisterPage() {
  return (
    <React.Suspense>
      <RegisterForm />
    </React.Suspense>
  );
}
