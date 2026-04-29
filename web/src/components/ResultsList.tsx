import type { SearchResult } from '../types';
import EmptyState from './EmptyState';
import ResultCard from './ResultCard';

interface ResultsListProps {
  results: SearchResult[];
  query: string;
  onClear?: () => void;
  onSuggestionSelect?: (suggestion: string) => void;
}

export default function ResultsList({
  results,
  query,
  onClear,
  onSuggestionSelect,
}: ResultsListProps) {
  return (
    <section className="px-5 flex-1 pb-6">
      <div className="flex items-center justify-between mb-4 mt-2">
        <h3 className="text-[13px] font-semibold text-[#0F172A] uppercase tracking-wider">
          Top Results
        </h3>
        <span className="text-[13px] font-medium text-[#475569]">
          Found {results.length} items
        </span>
      </div>

      {results.length === 0 ? (
        <EmptyState
          query={query}
          onClear={onClear}
          onSuggestionSelect={onSuggestionSelect}
        />
      ) : (
        <div className="flex flex-col gap-3">
          {results.map((result) => (
            <ResultCard key={result.id} result={result} />
          ))}
        </div>
      )}
    </section>
  );
}
