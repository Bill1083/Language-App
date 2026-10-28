"use client";

import { useQueryClient } from "@tanstack/react-query";
import * as React from "react";

import { isLang } from "@/lib/languages";
import type { Enrolment, Lang } from "@/lib/types";

import { useMe, useUpdateSettings } from "./use-me";

type Ctx = {
  lang: Lang | null;
  enrolment: Enrolment | null;
  enrolments: Enrolment[];
  setLang: (l: Lang) => void;
};

const LanguageContext = React.createContext<Ctx>({ lang: null, enrolment: null, enrolments: [], setLang: () => {} });

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const { data: me } = useMe();
  const update = useUpdateSettings();
  const qc = useQueryClient();
  const enrolments = me?.enrolments ?? [];
  const preferred = me?.settings.active_language;
  const enrolment =
    enrolments.find((e) => e.language_code === preferred) ?? enrolments[0] ?? null;
  const lang = enrolment?.language_code ?? null;

  React.useEffect(() => {
    if (lang) document.documentElement.dataset.lang = lang;
    else delete document.documentElement.dataset.lang;
  }, [lang]);

  const setLang = React.useCallback(
    (l: Lang) => {
      if (!isLang(l) || l === lang) return;
      document.documentElement.dataset.lang = l;
      update.mutate({ active_language: l });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    [lang, update, qc],
  );

  return (
    <LanguageContext.Provider value={{ lang, enrolment, enrolments, setLang }}>{children}</LanguageContext.Provider>
  );
}

export function useLanguage() {
  return React.useContext(LanguageContext);
}

/** For pages that need an enrolled language (everything inside the app shell). */
export function useActiveLang(): Lang {
  const { lang } = useLanguage();
  return lang ?? "fr";
}
