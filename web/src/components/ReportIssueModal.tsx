import { useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faXmark, faCheck } from '@fortawesome/free-solid-svg-icons';
import { ApiError, api } from '../api/client';
import type { IssueKind } from '../types';

interface ReportIssueModalProps {
  open: boolean;
  defaultQuery?: string;
  defaultKind?: IssueKind;
  onClose: () => void;
}

const KINDS: { value: IssueKind; label: string }[] = [
  { value: 'missing_content', label: 'Missing content' },
  { value: 'wrong_result', label: 'Wrong result' },
  { value: 'broken_link', label: 'Broken link' },
  { value: 'other', label: 'Other' },
];

export default function ReportIssueModal({
  open,
  defaultQuery = '',
  defaultKind = 'missing_content',
  onClose,
}: ReportIssueModalProps) {
  const [kind, setKind] = useState<IssueKind>(defaultKind);
  const [queryText, setQueryText] = useState(defaultQuery);
  const [message, setMessage] = useState('');
  const [pending, setPending] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const reset = () => {
    setKind(defaultKind);
    setQueryText(defaultQuery);
    setMessage('');
    setSubmitted(false);
    setError(null);
  };

  const close = () => {
    reset();
    onClose();
  };

  const submit = async () => {
    setPending(true);
    setError(null);
    try {
      await api.post('/api/issues', {
        kind,
        query_text: queryText || null,
        message: message || null,
      });
      setSubmitted(true);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : 'Submit failed');
    } finally {
      setPending(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-40 flex items-end sm:items-center justify-center bg-black/40 backdrop-blur-sm"
      onClick={close}
    >
      <div
        className="w-full max-w-[430px] bg-white rounded-t-[24px] sm:rounded-[24px] shadow-xl border border-border max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 pt-5 pb-3 border-b border-border/60">
          <h3 className="text-[16px] font-bold text-textPrimary">Report an issue</h3>
          <button
            type="button"
            onClick={close}
            className="w-8 h-8 rounded-full flex items-center justify-center text-textSecondary hover:bg-surface"
            aria-label="Close"
          >
            <FontAwesomeIcon icon={faXmark} />
          </button>
        </div>

        {submitted ? (
          <div className="px-5 py-8 text-center">
            <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center mx-auto mb-3 text-primary">
              <FontAwesomeIcon icon={faCheck} />
            </div>
            <h4 className="text-[16px] font-bold text-textPrimary mb-1">Thanks — submitted</h4>
            <p className="text-[13px] text-textSecondary mb-6">
              An admin will triage it from the issue queue.
            </p>
            <button
              type="button"
              onClick={close}
              className="px-5 py-2.5 rounded-full bg-primary text-white text-[14px] font-semibold hover:bg-primary/90"
            >
              Done
            </button>
          </div>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              submit();
            }}
            className="px-5 py-4 flex flex-col gap-4"
          >
            <div>
              <label className="text-[12px] font-semibold uppercase tracking-wide text-textSecondary mb-2 block">
                What's wrong?
              </label>
              <div className="flex flex-wrap gap-2">
                {KINDS.map((k) => (
                  <button
                    key={k.value}
                    type="button"
                    onClick={() => setKind(k.value)}
                    className={
                      'px-3 py-1.5 rounded-full text-[13px] font-medium transition-colors border ' +
                      (kind === k.value
                        ? 'bg-primary text-white border-primary'
                        : 'bg-surface text-[#475569] border-border hover:border-textSecondary')
                    }
                  >
                    {k.label}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="text-[12px] font-semibold uppercase tracking-wide text-textSecondary mb-2 block">
                Query (optional)
              </label>
              <input
                type="text"
                value={queryText}
                onChange={(e) => setQueryText(e.target.value)}
                placeholder="What did you search for?"
                className="w-full bg-surface border border-border rounded-xl px-3 py-2.5 text-[14px] outline-none focus:border-primary"
              />
            </div>

            <div>
              <label className="text-[12px] font-semibold uppercase tracking-wide text-textSecondary mb-2 block">
                Details (optional)
              </label>
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                rows={4}
                maxLength={2000}
                placeholder="What did you expect to find?"
                className="w-full bg-surface border border-border rounded-xl px-3 py-2.5 text-[14px] outline-none focus:border-primary resize-none"
              />
            </div>

            {error && (
              <p className="text-[13px] text-red-600 font-medium" role="alert">
                {error}
              </p>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={close}
                className="px-4 py-2 rounded-full bg-surface border border-border text-[14px] font-semibold text-textPrimary hover:bg-surfaceHover"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={pending}
                className="px-4 py-2 rounded-full bg-primary text-white text-[14px] font-semibold hover:bg-primary/90 disabled:opacity-50"
              >
                {pending ? 'Submitting…' : 'Submit'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
