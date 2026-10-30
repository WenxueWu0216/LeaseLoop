import { useState } from "react";

import { type InboxFilter, useInbox } from "../api/hooks";
import { ConversationList } from "../features/inbox/ConversationList";
import { ConversationView } from "../features/inbox/ConversationView";

const FILTERS: [InboxFilter, string][] = [["all", "All"], ["handoff", "Needs handoff"], ["unread", "Unread"]];

export function InboxPage() {
  const [filter, setFilter] = useState<InboxFilter>("all");
  const [selected, setSelected] = useState<number | null>(null);
  const inbox = useInbox(filter);
  const rows = inbox.data?.results ?? [];
  const current = rows.find((r) => r.id === selected) ?? null;

  return (
    <div className="flex h-full">
      <aside className="flex w-96 shrink-0 flex-col border-r bg-white">
        <div className="flex gap-1 border-b p-2">
          {FILTERS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setFilter(key)}
              className={`rounded px-2.5 py-1 text-sm ${filter === key ? "bg-slate-800 text-white" : "text-slate-600 hover:bg-slate-100"}`}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="flex-1 overflow-y-auto">
          {inbox.isLoading ? <p className="p-4 text-sm text-slate-500">Loading…</p> : (
            <ConversationList rows={rows} selectedId={selected} onSelect={setSelected} />
          )}
        </div>
      </aside>
      <section className="min-w-0 flex-1 bg-slate-50">
        {current ? <ConversationView key={current.id} conversation={current} /> : (
          <p className="p-6 text-slate-500">Select a conversation.</p>
        )}
      </section>
    </div>
  );
}
