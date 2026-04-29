import { useState } from 'react';
import Header from './components/Header';
import SearchHero from './components/SearchHero';
import ResultsList from './components/ResultsList';
import BottomNav from './components/BottomNav';
import { SAMPLE_RESULTS } from './sampleResults';
import type { SearchResult } from './types';

const DEFAULT_QUERY = 'biodegradable resin alternatives';

export default function App() {
  const [query, setQuery] = useState(DEFAULT_QUERY);
  const [results, setResults] = useState<SearchResult[]>([]);

  const handleClear = () => {
    setQuery('');
    setResults([]);
  };

  const handleSuggestion = (suggestion: string) => {
    setQuery(suggestion);
  };

  const handleSubmit = () => {
    setResults(SAMPLE_RESULTS);
  };

  return (
    <main className="w-full max-w-[430px] mx-auto flex-1 flex flex-col pb-24 relative shadow-sm min-h-screen bg-background">
      <Header />
      <SearchHero
        query={query}
        onQueryChange={setQuery}
        onSubmit={handleSubmit}
        onSuggestionSelect={handleSuggestion}
      />
      <ResultsList
        results={results}
        query={query}
        onClear={handleClear}
        onSuggestionSelect={handleSuggestion}
      />
      <BottomNav />
    </main>
  );
}
