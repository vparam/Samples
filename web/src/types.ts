export type ResultKind = 'pdf' | 'video' | 'article';

export interface SearchResult {
  id: string;
  kind: ResultKind;
  kindLabel: string;
  date: string;
  title: string;
  snippet: string;
}
