"use client";

import { LoaderCircle, WifiOff } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import * as React from "react";

import { useMe } from "@/hooks/use-me";

import { LogoMark } from "./brand";
import { Button } from "./ui/button";

export function FullscreenLoader({ label }: { label?: string }) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-4 text-muted-foreground">
      <LogoMark className="size-12 animate-pulse" />
      {label && (
        <p className="flex items-center gap-2 text-sm">
          <LoaderCircle className="size-4 animate-spin" /> {label}
        </p>
      )}
    </div>
  );
}

export function AuthGuard({ children, requireLanguage = true }: { children: React.ReactNode; requireLanguage?: boolean }) {
  const { data: me, error, isLoading, refetch } = useMe();
  const router = useRouter();
  const pathname = usePathname();

  React.useEffect(() => {
    if (error?.status === 401) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    else if (me && requireLanguage && me.enrolments.length === 0) router.replace("/onboarding");
  }, [error, me, requireLanguage, router, pathname]);

  if (error && error.status !== 401) {
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-4 p-6 text-center">
        <WifiOff className="size-10 text-muted-foreground" />
        <div>
          <p className="font-semibold">Can&apos;t reach Parlo</p>
          <p className="mt-1 text-sm text-muted-foreground">{error.message}</p>
        </div>
        <Button variant="outline" onClick={() => refetch()}>
          Try again
        </Button>
      </div>
    );
  }
  if (isLoading || !me || (requireLanguage && me.enrolments.length === 0)) return <FullscreenLoader />;
  return <>{children}</>;
}
