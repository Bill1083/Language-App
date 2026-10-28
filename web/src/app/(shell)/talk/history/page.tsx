"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, MessageCircle, Search, Trash } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Badge, EmptyState, Input, Skeleton } from "@/components/ui/primitives";
import { useConversations } from "@/hooks/queries";
import { useActiveLang } from "@/hooks/use-language";
import { del, errorMessage } from "@/lib/api";
import { timeAgo } from "@/lib/utils";

const MODE_LABEL = { scenario: "Scenario", free: "Free chat", unit: "Unit", tutor: "Tutor" };

export default function HistoryPage() {
  const lang = useActiveLang();
  const [q, setQ] = React.useState("");
  const [search, setSearch] = React.useState("");
  const { data, isLoading } = useConversations(lang, search);
  const qc = useQueryClient();
  const remove = useMutation({
    mutationFn: (id: number) => del(`/conversations/${id}`),
    onSuccess: () => {
      toast.success("Conversation deleted");
      void qc.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  React.useEffect(() => {
    const t = setTimeout(() => setSearch(q), 300);
    return () => clearTimeout(t);
  }, [q]);

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="icon" asChild aria-label="Back to Talk">
          <Link href="/talk"><ArrowLeft /></Link>
        </Button>
        <h1 className="text-2xl font-extrabold tracking-tight">Conversation history</h1>
      </div>
      <div className="relative">
        <Search className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input className="pl-10" placeholder="Search titles and what was said…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {isLoading ? (
        <div className="space-y-2">{Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-16" />)}</div>
      ) : !data?.items.length ? (
        <EmptyState icon={<MessageCircle />} title={search ? "No matches" : "No conversations yet"}>
          {search ? "Try a different word." : "Start one from the Talk tab — transcripts, audio and feedback are saved here."}
        </EmptyState>
      ) : (
        <div className="divide-y rounded-2xl border bg-card">
          {data.items.map((c) => (
            <div key={c.id} className="flex items-center gap-3 px-4 py-3">
              <Link href={c.ended_at ? `/conversation/${c.id}/summary` : `/conversation/${c.id}`} className="flex min-w-0 flex-1 items-center gap-3">
                <span className="text-2xl">{c.scenario?.emoji ?? (c.mode === "tutor" ? "🎓" : "💬")}</span>
                <span className="min-w-0">
                  <span className="block truncate font-semibold">{c.title}</span>
                  <span className="block text-xs text-muted-foreground">
                    {MODE_LABEL[c.mode]} · {c.level} · {timeAgo(c.started_at)} · {c.turns} turns
                    {c.goal_achieved && " · 🎯 goal"}
                    {!c.ended_at && " · in progress"}
                  </span>
                </span>
              </Link>
              {c.avg_score != null && (
                <Badge tone={c.avg_score >= 85 ? "success" : c.avg_score >= 60 ? "warning" : "danger"}>{c.avg_score}</Badge>
              )}
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`Delete ${c.title}`}
                onClick={() => confirm("Delete this conversation, its transcript and recordings?") && remove.mutate(c.id)}
              >
                <Trash />
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
