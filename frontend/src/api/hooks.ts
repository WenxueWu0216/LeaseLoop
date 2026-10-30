import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, query } from "./client";
import type {
  InboxRow, Me, Message, Paginated, Property, ProspectDetail, ProspectRow, ProspectStatus,
  Suggestion, Tour, Unit,
} from "./types";

export const useMe = (enabled: boolean) =>
  useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me/"), enabled, retry: false });

export type ProspectFilters = { status?: string; source?: string; q?: string; unassigned?: boolean; page?: number };

export const useProspects = (f: ProspectFilters) =>
  useQuery({
    queryKey: ["prospects", f],
    queryFn: () => api<Paginated<ProspectRow>>(`/prospects/${query({ ...f })}`),
    placeholderData: keepPreviousData,
  });

export const useProspect = (id: number) =>
  useQuery({ queryKey: ["prospect", id], queryFn: () => api<ProspectDetail>(`/prospects/${id}/`) });

export function useUpdateProspect(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: { status?: ProspectStatus; notes?: string }) =>
      api(`/prospects/${id}/`, { method: "PATCH", json: patch }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["prospect", id] });
      qc.invalidateQueries({ queryKey: ["prospects"] });
    },
  });
}

export type InboxFilter = "all" | "handoff" | "unread";

export const useInbox = (filter: InboxFilter) =>
  useQuery({
    queryKey: ["inbox", filter],
    queryFn: () =>
      api<Paginated<InboxRow>>(
        `/conversations/${query({
          needs_handoff: filter === "handoff" ? true : undefined,
          is_unread: filter === "unread" ? true : undefined,
          page_size: 50,
        })}`,
      ),
    refetchInterval: 15_000, // polling keeps the inbox fresh without websockets
  });

export const useThread = (conversationId: number | null) =>
  useQuery({
    queryKey: ["thread", conversationId],
    queryFn: () => api<Message[]>(`/conversations/${conversationId}/messages/`),
    enabled: conversationId !== null,
  });

export function useSendReply(conversationId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: string) =>
      api<Message[]>(`/conversations/${conversationId}/messages/`, { method: "POST", json: { body } }),
    onSuccess: (thread) => {
      qc.setQueryData(["thread", conversationId], thread);
      qc.invalidateQueries({ queryKey: ["inbox"] });
    },
  });
}

export const useSuggestReply = (conversationId: number) =>
  useMutation({
    mutationFn: () => api<Suggestion>(`/conversations/${conversationId}/suggest-reply/`, { method: "POST" }),
  });

export const useProperties = () =>
  useQuery({ queryKey: ["properties"], queryFn: () => api<Paginated<Property>>("/properties/?page_size=100") });

export const useTours = (range: { start: string; end: string; property?: number }) =>
  useQuery({
    queryKey: ["tours", range],
    queryFn: () =>
      api<Paginated<Tour>>(
        `/tours/${query({ start_after: range.start, start_before: range.end, property: range.property, status: "SCHEDULED", page_size: 100 })}`,
      ),
  });

/** Drag-to-reschedule: update the cache immediately, roll back if the server refuses. */
export function useRescheduleTour(range: { start: string; end: string; property?: number }) {
  const qc = useQueryClient();
  const key = ["tours", range];
  return useMutation({
    mutationFn: (v: { id: number; start: string; end: string }) =>
      api<Tour>(`/tours/${v.id}/`, { method: "PATCH", json: { start: v.start, end: v.end } }),
    onMutate: async (v) => {
      await qc.cancelQueries({ queryKey: key });
      const previous = qc.getQueryData<Paginated<Tour>>(key);
      if (previous) {
        qc.setQueryData<Paginated<Tour>>(key, {
          ...previous,
          results: previous.results.map((t) => (t.id === v.id ? { ...t, start: v.start, end: v.end } : t)),
        });
      }
      return { previous };
    },
    onError: (_err, _v, ctx) => {
      if (ctx?.previous) qc.setQueryData(key, ctx.previous);
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["tours"] }),
  });
}

/** Every unit of a property (follows pagination; the grid needs them all). */
export const useUnits = (property?: number) =>
  useQuery({
    queryKey: ["units", property],
    enabled: property !== undefined,
    queryFn: async () => {
      const units: Unit[] = [];
      for (let page = 1; ; page++) {
        const data = await api<Paginated<Unit>>(`/units/${query({ property, page_size: 100, page })}`);
        units.push(...data.results);
        if (!data.next) return units;
      }
    },
  });
