import { useEffect, useState } from 'react';
import { ApiError, api } from '../api/client';
import type { IssueRow } from '../types';

const STATUSES: IssueRow['status'][] = ['open', 'in_progress', 'resolved', 'wont_fix'];

const KIND_LABEL: Record<IssueRow['kind'], string> = {
  broken_link: 'Broken link',
  wrong_result: 'Wrong result',
  missing_content: 'Missing content',
  other: 'Other',
};

const STATUS_STYLE: Record<IssueRow['status'], string> = {
  open: 'bg-red-100 text-red-700',
  in_progress: 'bg-amber-100 text-amber-700',
  resolved: 'bg-emerald-100 text-emerald-700',
  wont_fix: 'bg-slate-200 text-slate-700',
};

export default function AdminIssues() {
  const [issues, setIssues] = useState<IssueRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    api
      .get<{ issues: IssueRow[] }>('/api/admin/issues')
      .then((r) => setIssues(r.issues))
      .catch((e: ApiError) => setError(e.detail));

  useEffect(() => {
    load();
  }, []);

  const setStatus = async (id: number, status: IssueRow['status']) => {
    try {
      await api.put(`/api/admin/issues/${id}`, { status });
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : 'Update failed');
    }
  };

  if (error) return <p className="px-5 py-6 text-red-600 text-[13px]">{error}</p>;
  if (!issues) return <p className="px-5 py-6 text-textSecondary text-[13px]">Loading…</p>;
  if (issues.length === 0) {
    return (
      <p className="px-5 py-6 text-textSecondary text-[13px]">
        No reported issues yet.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3 px-5 pb-6">
      {issues.map((i) => (
        <div
          key={i.id}
          className="bg-surface rounded-[16px] p-4 border border-border/60 shadow-sm"
        >
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-textPrimary">
              {KIND_LABEL[i.kind]}
            </span>
            <span
              className={
                'text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded-full ' +
                STATUS_STYLE[i.status]
              }
            >
              {i.status.replace('_', ' ')}
            </span>
          </div>
          {i.query_text && (
            <p className="text-[13px] text-textPrimary font-medium mb-1">
              Query: <span className="font-normal">{i.query_text}</span>
            </p>
          )}
          {i.message && (
            <p className="text-[13px] text-[#334155] leading-relaxed mb-2">{i.message}</p>
          )}
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-textSecondary">
              {i.user_email} · {i.created_at}
            </span>
            <select
              value={i.status}
              onChange={(e) => setStatus(i.id, e.target.value as IssueRow['status'])}
              className="text-[11px] font-medium bg-white border border-border rounded-lg px-2 py-1 outline-none focus:border-primary"
            >
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s.replace('_', ' ')}
                </option>
              ))}
            </select>
          </div>
        </div>
      ))}
    </div>
  );
}
