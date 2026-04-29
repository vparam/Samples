import { useState } from 'react';
import { AuthProvider, useAuth } from './auth/AuthContext';
import LoginScreen from './auth/LoginScreen';
import Header from './components/Header';
import SearchHero from './components/SearchHero';
import ResultsList from './components/ResultsList';
import BottomNav from './components/BottomNav';
import type { NavView } from './components/BottomNav';
import PromptGuide from './components/PromptGuide';
import ReportIssueModal from './components/ReportIssueModal';
import AdminPanel from './admin/AdminPanel';
import { useSearch } from './hooks/useSearch';

const DEFAULT_QUERY = 'biodegradable resin alternatives';

function AuthedApp() {
  const { user } = useAuth();
  const search = useSearch(DEFAULT_QUERY);
  const [view, setView] = useState<NavView>('search');
  const [issueOpen, setIssueOpen] = useState(false);

  const goSearch = () => setView('search');

  // Treat the "Report Issue" tab as a modal trigger so users stay on the
  // search results context.
  const handleNav = (next: NavView) => {
    if (next === 'report') {
      setIssueOpen(true);
      return;
    }
    if (next === 'admin' && user?.role !== 'Admin') {
      return; // belt-and-braces; tab is hidden for non-admins
    }
    setView(next);
  };

  return (
    <main className="w-full max-w-[430px] mx-auto flex-1 flex flex-col pb-24 relative shadow-sm min-h-screen bg-background">
      <Header />

      {view === 'search' && (
        <>
          <SearchHero
            query={search.query}
            onQueryChange={search.setQuery}
            onSubmit={() => search.run()}
            onSuggestionSelect={(s) => {
              search.setQuery(s);
              search.run(s);
            }}
            onShowGuide={() => setView('guide')}
            loading={search.loading}
          />
          <ResultsList
            results={search.results}
            query={search.query}
            hasSearched={search.hasSearched}
            onClear={search.clear}
            onSuggestionSelect={(s) => {
              search.setQuery(s);
              search.run(s);
            }}
            onResultClick={search.reportClick}
            onReportIssue={() => setIssueOpen(true)}
          />
        </>
      )}

      {view === 'guide' && <PromptGuide />}
      {view === 'admin' && user?.role === 'Admin' && <AdminPanel />}

      <BottomNav active={view} onChange={handleNav} />

      <ReportIssueModal
        open={issueOpen}
        defaultQuery={search.query}
        onClose={() => {
          setIssueOpen(false);
          goSearch();
        }}
      />
    </main>
  );
}

function Gate() {
  const { status } = useAuth();
  if (status === 'loading') {
    return (
      <main className="w-full max-w-[430px] mx-auto min-h-screen flex items-center justify-center bg-background">
        <p className="text-[13px] text-textSecondary font-medium">Loading…</p>
      </main>
    );
  }
  if (status === 'anon') return <LoginScreen />;
  return <AuthedApp />;
}

export default function App() {
  return (
    <AuthProvider>
      <Gate />
    </AuthProvider>
  );
}
