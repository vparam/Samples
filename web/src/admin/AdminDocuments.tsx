import { useEffect, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faPenToSquare, faXmark, faCheck } from '@fortawesome/free-solid-svg-icons';
import { ApiError, api } from '../api/client';
import type { AdminDocument } from '../types';

export default function AdminDocuments() {
  const [docs, setDocs] = useState<AdminDocument[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);

  const load = () => {
    api
      .get<{ documents: AdminDocument[] }>('/api/admin/documents')
      .then((r) => setDocs(r.documents))
      .catch((e: ApiError) => setError(e.detail));
  };
  useEffect(load, []);

  const startEdit = (d: AdminDocument) => {
    setEditing(d.id);
    setDraft(d.admin_tags.join(', '));
  };

  const saveTags = async (id: number) => {
    const tags = draft
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean);
    setSaving(true);
    try {
      await api.put(`/api/admin/documents/${id}/tags`, { tags });
      setEditing(null);
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  if (error) return <p className="px-5 py-6 text-red-600 text-[13px]">{error}</p>;
  if (!docs) return <p className="px-5 py-6 text-textSecondary text-[13px]">Loading…</p>;

  return (
    <div className="flex flex-col gap-3 px-5 pb-6">
      <p className="text-[12px] text-textSecondary font-medium">
        {docs.length} indexed document{docs.length === 1 ? '' : 's'}. Tag edits trigger a
        re-index, never a re-scrape.
      </p>
      {docs.map((d) => (
        <div
          key={d.id}
          className="bg-surface rounded-[16px] p-4 border border-border/60 shadow-sm"
        >
          <div className="flex items-start justify-between gap-3 mb-2">
            <div className="min-w-0">
              <h4 className="text-[14px] font-semibold text-textPrimary leading-snug truncate">
                {d.title}
              </h4>
              <a
                href={d.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[11px] text-textSecondary hover:text-primary truncate block"
              >
                {d.source_url}
              </a>
            </div>
            <span className="shrink-0 inline-flex items-center px-2 py-1 rounded-md bg-white border border-border text-[10px] font-semibold uppercase tracking-wide text-textPrimary">
              {d.content_type.replace(/_/g, ' ')}
            </span>
          </div>

          {d.source_tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-2">
              {d.source_tags.map((t) => (
                <span
                  key={`s-${t}`}
                  className="text-[11px] px-2 py-0.5 rounded-full bg-white border border-border text-textSecondary"
                >
                  {t}
                </span>
              ))}
            </div>
          )}

          {editing === d.id ? (
            <div className="flex items-center gap-2">
              <input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="comma, separated, tags"
                className="flex-1 bg-white border border-border rounded-lg px-3 py-2 text-[13px] outline-none focus:border-primary"
                autoFocus
              />
              <button
                type="button"
                onClick={() => saveTags(d.id)}
                disabled={saving}
                className="w-9 h-9 rounded-lg bg-primary text-white flex items-center justify-center hover:bg-primary/90 disabled:opacity-50"
                aria-label="Save"
              >
                <FontAwesomeIcon icon={faCheck} />
              </button>
              <button
                type="button"
                onClick={() => setEditing(null)}
                className="w-9 h-9 rounded-lg bg-surface border border-border text-textPrimary flex items-center justify-center hover:bg-surfaceHover"
                aria-label="Cancel"
              >
                <FontAwesomeIcon icon={faXmark} />
              </button>
            </div>
          ) : (
            <div className="flex items-center justify-between gap-2">
              <div className="flex flex-wrap gap-1.5 min-w-0">
                {d.admin_tags.length === 0 ? (
                  <span className="text-[12px] text-textSecondary italic">No admin tags</span>
                ) : (
                  d.admin_tags.map((t) => (
                    <span
                      key={`a-${t}`}
                      className="text-[11px] px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium"
                    >
                      {t}
                    </span>
                  ))
                )}
              </div>
              <button
                type="button"
                onClick={() => startEdit(d)}
                className="shrink-0 text-[12px] font-semibold text-primary flex items-center gap-1.5 hover:text-primary/80"
              >
                <FontAwesomeIcon icon={faPenToSquare} /> Edit
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
