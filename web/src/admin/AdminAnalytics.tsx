import { useEffect, useState } from 'react';
import { ApiError, api } from '../api/client';
import type { AnalyticsResponse } from '../types';

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="bg-surface rounded-[16px] p-4 border border-border/60 shadow-sm">
      <p className="text-[11px] uppercase tracking-wide text-textSecondary font-semibold">
        {label}
      </p>
      <p className="text-[22px] font-bold text-textPrimary mt-1">{value}</p>
    </div>
  );
}

function ListBlock({
  title,
  rows,
  empty,
}: {
  title: string;
  rows: { label: string; n: number }[];
  empty: string;
}) {
  return (
    <div className="bg-surface rounded-[16px] p-4 border border-border/60 shadow-sm">
      <h3 className="text-[12px] font-bold uppercase tracking-wide text-textPrimary mb-3">
        {title}
      </h3>
      {rows.length === 0 ? (
        <p className="text-[12px] text-textSecondary">{empty}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {rows.map((r, i) => (
            <li key={i} className="flex items-center justify-between gap-3">
              <span className="text-[13px] text-textPrimary truncate">{r.label}</span>
              <span className="text-[12px] font-semibold text-textSecondary shrink-0">
                {r.n}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function AdminAnalytics() {
  const [data, setData] = useState<AnalyticsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<AnalyticsResponse>('/api/admin/analytics')
      .then(setData)
      .catch((e: ApiError) => setError(e.detail));
  }, []);

  if (error) return <p className="px-5 py-6 text-red-600 text-[13px]">{error}</p>;
  if (!data) return <p className="px-5 py-6 text-textSecondary text-[13px]">Loading…</p>;

  return (
    <div className="flex flex-col gap-3 px-5 pb-6">
      <div className="grid grid-cols-2 gap-3">
        <StatCard label="Indexed docs" value={data.totals.indexed_documents} />
        <StatCard label="Total queries" value={data.totals.total_queries} />
        <StatCard label="Zero-result" value={data.totals.zero_result_queries} />
        <StatCard label="Total clicks" value={data.totals.total_clicks} />
      </div>

      <ListBlock
        title="Top queries"
        rows={data.top_queries.map((q) => ({ label: q.query_text, n: q.n }))}
        empty="No queries yet."
      />

      <ListBlock
        title="Zero-result queries"
        rows={data.zero_result_queries.map((q) => ({ label: q.query_text, n: q.n }))}
        empty="None — every query had at least one match."
      />

      <ListBlock
        title="Clicked content types"
        rows={data.clicked_content_types.map((c) => ({
          label: c.content_type.replace(/_/g, ' '),
          n: c.n,
        }))}
        empty="No clicks recorded yet."
      />

      <ListBlock
        title="Daily volume (last 14 days)"
        rows={data.daily_volume.map((d) => ({ label: d.day, n: d.n }))}
        empty="No traffic in the last 14 days."
      />
    </div>
  );
}
