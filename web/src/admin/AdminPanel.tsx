import { useState } from 'react';
import AdminDocuments from './AdminDocuments';
import AdminIssues from './AdminIssues';
import AdminSources from './AdminSources';
import AdminAnalytics from './AdminAnalytics';

type Tab = 'documents' | 'issues' | 'sources' | 'analytics';

const TABS: { id: Tab; label: string }[] = [
  { id: 'documents', label: 'Documents' },
  { id: 'issues', label: 'Issues' },
  { id: 'sources', label: 'Sources' },
  { id: 'analytics', label: 'Analytics' },
];

export default function AdminPanel() {
  const [tab, setTab] = useState<Tab>('documents');

  return (
    <section className="pt-2 pb-4">
      <div className="px-5 mb-4">
        <h2 className="text-[20px] font-bold tracking-tight text-textPrimary">
          Admin
        </h2>
        <p className="text-[12px] text-textSecondary font-medium">
          Manage indexed content, sources, and the issue queue.
        </p>
      </div>

      <div className="px-5 mb-4">
        <div className="flex bg-surface border border-border rounded-full p-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={
                'flex-1 text-[12px] font-semibold py-1.5 rounded-full transition-colors ' +
                (tab === t.id
                  ? 'bg-white text-textPrimary shadow-sm'
                  : 'text-textSecondary hover:text-textPrimary')
              }
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {tab === 'documents' && <AdminDocuments />}
      {tab === 'issues' && <AdminIssues />}
      {tab === 'sources' && <AdminSources />}
      {tab === 'analytics' && <AdminAnalytics />}
    </section>
  );
}
