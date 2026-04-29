import { useCallback, useState } from 'react';
import { ApiError, api } from '../api/client';
import type { SearchResponse, SearchResult } from '../types';

export interface SearchState {
  query: string;
  setQuery: (q: string) => void;
  results: SearchResult[];
  loading: boolean;
  hasSearched: boolean;
  noResultsReason: string | null;
  queryId: number | null;
  error: string | null;
  run: (q?: string) => Promise<void>;
  clear: () => void;
  reportClick: (r: SearchResult, position: number) => void;
}

export function useSearch(initialQuery = ''): SearchState {
  const [query, setQuery] = useState(initialQuery);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [noResultsReason, setNoResultsReason] = useState<string | null>(null);
  const [queryId, setQueryId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(
    async (q?: string) => {
      const text = (q ?? query).trim();
      if (!text) return;
      setQuery(text);
      setLoading(true);
      setError(null);
      try {
        const data = await api.get<SearchResponse>(
          `/api/search?q=${encodeURIComponent(text)}`,
        );
        setResults(data.results);
        setNoResultsReason(data.no_results ? data.reason ?? 'no_results' : null);
        setQueryId(data.query_id);
        setHasSearched(true);
      } catch (e) {
        const msg = e instanceof ApiError ? e.detail : 'Search failed';
        setError(msg);
        setResults([]);
        setHasSearched(true);
      } finally {
        setLoading(false);
      }
    },
    [query],
  );

  const clear = useCallback(() => {
    setQuery('');
    setResults([]);
    setHasSearched(false);
    setNoResultsReason(null);
    setQueryId(null);
    setError(null);
  }, []);

  const reportClick = useCallback(
    (r: SearchResult, position: number) => {
      if (queryId == null) return;
      api
        .post('/api/search/click', {
          query_id: queryId,
          document_id: r.document_id,
          position,
          content_type: r.content_type,
        })
        .catch(() => {
          /* swallow telemetry errors */
        });
    },
    [queryId],
  );

  return {
    query,
    setQuery,
    results,
    loading,
    hasSearched,
    noResultsReason,
    queryId,
    error,
    run,
    clear,
    reportClick,
  };
}
