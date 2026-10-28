"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider, useTheme } from "next-themes";
import * as React from "react";
import { Toaster, toast } from "sonner";

import { LanguageProvider } from "@/hooks/use-language";
import { useMe } from "@/hooks/use-me";
import { flushOutbox } from "@/lib/outbox";
import { setSoundEnabled } from "@/lib/sounds";

function SettingsSync() {
  const { data: me } = useMe();
  const { setTheme } = useTheme();
  const theme = me?.settings.theme;
  const sound = me?.settings.sound;
  React.useEffect(() => {
    if (theme) setTheme(theme);
  }, [theme, setTheme]);
  React.useEffect(() => {
    setSoundEnabled(sound !== false);
  }, [sound]);
  return null;
}

function OfflineSync() {
  React.useEffect(() => {
    const flush = () =>
      flushOutbox().then((n) => {
        if (n) toast.success(`Back online — synced ${n} offline ${n === 1 ? "update" : "updates"}.`);
      });
    void flush();
    window.addEventListener("online", flush);
    if ("serviceWorker" in navigator && process.env.NODE_ENV === "production") {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    }
    return () => window.removeEventListener("online", flush);
  }, []);
  return null;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = React.useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { refetchOnWindowFocus: false, staleTime: 20_000 },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <ThemeProvider attribute="class" defaultTheme="dark" enableSystem disableTransitionOnChange>
        <LanguageProvider>
          <SettingsSync />
          <OfflineSync />
          {children}
          <Toaster position="top-center" richColors closeButton toastOptions={{ className: "!rounded-2xl" }} />
        </LanguageProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
