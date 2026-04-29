import { useEffect, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faBolt, faPlus } from '@fortawesome/free-solid-svg-icons';
import { ApiError, api } from '../api/client';
import type { ManagedSource } from '../types';

type Kind = ManagedSource['kind'];

const KINDS: Kind[] = ['sitemap', 'rss', 'youtube_websub'];

export default function AdminSources() {
  const [sources, setSources] = useState<ManagedSource[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tickResult, setTickResult] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [kind, setKind] = useState<Kind>('sitemap');
  const [feedUrl, setFeedUrl] = useState('');
  const [contentType, setContentType] = useState('blog');
  const [interval, setInterval] = useState(300);

  const load = () =>
    api
      .get<{ sources: ManagedSource[] }>('/api/admin/sources')
      .then((r) => setSources(r.sources))
      .catch((e: ApiError) => setError(e.detail));

  useEffect(() => {
    load();
  }, []);

  const tick = async () => {
    setBusy(true);
    setTickResult(null);
    try {
      const r = await api.post<{ ran: { id: number; status: string }[] }>(
        '/api/admin/scheduler/tick',
      );
      setTickResult(`Ran ${r.ran.length} source${r.ran.length === 1 ? '' : 's'}`);
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : 'Tick failed');
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post('/api/admin/sources', {
        kind,
        feed_url: feedUrl,
        default_content_type: contentType,
        enabled: true,
        poll_interval_seconds: interval,
      });
      setShowForm(false);
      setFeedUrl('');
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : 'Save failed');
    } finally {
      setBusy(false);
    }
  };

  if (error && !sources)
    return <p className="px-5 py-6 text-red-600 text-[13px]">{error}</p>;
  if (!sources) return <p className="px-5 py-6 text-textSecondary text-[13px]">Loading…</p>;

  return (
    <div className="flex flex-col gap-3 px-5 pb-6">
      <div className="flex items-center justify-between">
        <p className="text-[12px] text-textSecondary font-medium">
          {sources.length} managed source{sources.length === 1 ? '' : 's'}
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={tick}
            disabled={busy}
            className="text-[12px] font-semibold text-primary flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-primary/10 hover:bg-primary/20 disabled:opacity-50"
          >
            <FontAwesomeIcon icon={faBolt} /> Tick now
          </button>
          <button
            type="button"
            onClick={() => setShowForm((s) => !s)}
            className="text-[12px] font-semibold text-textPrimary flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-surface border border-border hover:bg-surfaceHover"
          >
            <FontAwesomeIcon icon={faPlus} /> Add
          </button>
        </div>
      </div>

      {tickResult && (
        <p className="text-[12px] text-primary font-medium">{tickResult}</p>
      )}
      {error && sources && (
        <p className="text-[12px] text-red-600 font-medium">{error}</p>
      )}

      {showForm && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
          className="bg-white rounded-[16px] p-4 border border-border shadow-sm flex flex-col gap-3"
        >
          <div className="flex flex-wrap gap-2">
            {KINDS.map((k) => (
              <button
                key={k}
                type="button"
                onClick={() => setKind(k)}
                className={
                  'px-3 py-1 rounded-full text-[12px] font-medium border ' +
                  (kind === k
                    ? 'bg-primary text-white border-primary'
                    : 'bg-surface text-[#475569] border-border')
                }
              >
                {k}
              </button>
            ))}
          </div>
          <input
            value={feedUrl}
            onChange={(e) => setFeedUrl(e.target.value)}
            placeholder="https://example.com/sitemap.xml"
            className="bg-surface border border-border rounded-lg px-3 py-2 text-[13px] outline-none focus:border-primary"
            required
          />
          <div className="flex gap-2">
            <input
              value={contentType}
              onChange={(e) => setContentType(e.target.value)}
              placeholder="blog"
              className="flex-1 bg-surface border border-border rounded-lg px-3 py-2 text-[13px] outline-none focus:border-primary"
            />
            <input
              type="number"
              min={60}
              value={interval}
              onChange={(e) => setInterval(Number(e.target.value) || 300)}
              className="w-28 bg-surface border border-border rounded-lg px-3 py-2 text-[13px] outline-none focus:border-primary"
              title="Poll interval (seconds)"
            />
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="px-3 py-1.5 rounded-full bg-surface border border-border text-[13px] font-semibold"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={busy}
              className="px-3 py-1.5 rounded-full bg-primary text-white text-[13px] font-semibold hover:bg-primary/90 disabled:opacity-50"
            >
              Save
            </button>
          </div>
        </form>
      )}

      {sources.length === 0 ? (
        <p className="text-[13px] text-textSecondary">No managed sources yet.</p>
      ) : (
        sources.map((s) => (
          <div
            key={s.id}
            className="bg-surface rounded-[16px] p-4 border border-border/60 shadow-sm"
          >
            <div className="flex items-center justify-between mb-1">
              <span className="text-[11px] font-bold uppercase tracking-wide text-textPrimary">
                {s.kind}
              </span>
              <span
                className={
                  'text-[10px] font-semibold uppercase px-2 py-0.5 rounded-full ' +
                  (s.enabled
                    ? 'bg-emerald-100 text-emerald-700'
                    : 'bg-slate-200 text-slate-700')
                }
              >
                {s.enabled ? 'enabled' : 'disabled'}
              </span>
            </div>
            <p className="text-[12px] text-textPrimary font-medium break-all">{s.feed_url}</p>
            <p className="text-[11px] text-textSecondary mt-1">
              poll {s.poll_interval_seconds}s
              {s.last_polled_at ? ` · last ${s.last_polled_at}` : ''}
              {s.last_status ? ` · ${s.last_status}` : ''}
            </p>
          </div>
        ))
      )}
    </div>
  );
}
