export type Role = 'Standard.User' | 'Admin';

export interface User {
  email: string;
  name: string;
  role: Role;
}

export type ContentType =
  | 'blog'
  | 'case_study'
  | 'product'
  | 'podcast'
  | 'video'
  | 'white_paper'
  | string;

export interface SearchResult {
  document_id: number;
  title: string;
  content_type: ContentType;
  publish_date: string | null;
  url: string;
  excerpt: string;
  tags: string[];
  score: number;
  recency_boost: number;
}

export interface SearchResponse {
  results: SearchResult[];
  no_results: boolean;
  reason?: string;
  query_id: number;
}

export interface GuideSection {
  heading: string;
  body: string;
}

export interface GuideResponse {
  title: string;
  sections: GuideSection[];
}

export type IssueKind = 'broken_link' | 'wrong_result' | 'missing_content' | 'other';

export interface IssueRow {
  id: number;
  user_email: string;
  kind: IssueKind;
  query_text: string | null;
  document_id: number | null;
  message: string | null;
  status: 'open' | 'in_progress' | 'resolved' | 'wont_fix';
  created_at: string;
  doc_title: string | null;
  doc_url: string | null;
}

export interface AdminDocument {
  id: number;
  source_url: string;
  content_type: ContentType;
  title: string;
  publish_date: string | null;
  fetched_at: string | null;
  source_tags: string[];
  admin_tags: string[];
}

export interface ManagedSource {
  id: number;
  kind: 'sitemap' | 'rss' | 'youtube_websub';
  feed_url: string;
  default_content_type: string;
  enabled: number | boolean;
  poll_interval_seconds: number;
  last_polled_at: string | null;
  last_status: string | null;
  etag: string | null;
  last_modified: string | null;
}

export interface AnalyticsResponse {
  totals: {
    total_queries: number;
    zero_result_queries: number;
    total_clicks: number;
    indexed_documents: number;
  };
  top_queries: { query_text: string; n: number }[];
  zero_result_queries: { query_text: string; n: number }[];
  clicked_content_types: { content_type: string; n: number }[];
  daily_volume: { day: string; n: number }[];
}
