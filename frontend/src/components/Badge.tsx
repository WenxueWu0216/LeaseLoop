const TONES = {
  red: "bg-rose-100 text-rose-700",
  violet: "bg-violet-100 text-violet-700",
  sky: "bg-sky-100 text-sky-700",
  slate: "bg-slate-100 text-slate-600",
  green: "bg-emerald-100 text-emerald-700",
  amber: "bg-amber-100 text-amber-800",
} as const;

export function Badge({ tone = "slate", children }: { tone?: keyof typeof TONES; children: React.ReactNode }) {
  return <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ${TONES[tone]}`}>{children}</span>;
}

export const humanize = (s: string) => s.toLowerCase().replace(/_/g, " ");
