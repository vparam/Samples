import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faFileLines,
  faVideo,
  faPodcast,
  faBoxesStacked,
  faNewspaper,
  faFilePdf,
} from '@fortawesome/free-solid-svg-icons';
import type { IconDefinition } from '@fortawesome/fontawesome-svg-core';
import type { ContentType, SearchResult } from '../types';

const KIND_LABEL: Record<string, string> = {
  blog: 'Blog',
  case_study: 'Case Study',
  product: 'Product',
  podcast: 'Podcast',
  video: 'Video',
  white_paper: 'White Paper',
};

const KIND_ICON: Record<string, { icon: IconDefinition; color: string }> = {
  blog: { icon: faNewspaper, color: 'text-emerald-500' },
  case_study: { icon: faFileLines, color: 'text-emerald-500' },
  product: { icon: faBoxesStacked, color: 'text-amber-500' },
  podcast: { icon: faPodcast, color: 'text-purple-500' },
  video: { icon: faVideo, color: 'text-blue-500' },
  white_paper: { icon: faFilePdf, color: 'text-red-500' },
};

function fallbackKind(ct: ContentType) {
  return KIND_ICON[ct] ?? { icon: faFileLines, color: 'text-textSecondary' };
}

function fallbackLabel(ct: ContentType) {
  return KIND_LABEL[ct] ?? String(ct).replace(/_/g, ' ');
}

function formatDate(d: string | null): string {
  if (!d) return '';
  const dt = new Date(d);
  if (isNaN(dt.getTime())) return d;
  return dt.toLocaleDateString('en-US', { month: 'short', day: '2-digit', year: 'numeric' });
}

interface ResultCardProps {
  result: SearchResult;
  position: number;
  onClick?: (r: SearchResult, position: number) => void;
}

export default function ResultCard({ result, position, onClick }: ResultCardProps) {
  const { icon, color } = fallbackKind(result.content_type);
  return (
    <a
      href={result.url}
      target="_blank"
      rel="noopener noreferrer"
      onClick={() => onClick?.(result, position)}
      className="block bg-surface rounded-[16px] p-4 border border-border/60 hover:border-primary/30 hover:bg-surfaceHover transition-all shadow-sm"
    >
      <div className="flex items-center gap-2 mb-2">
        <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md bg-white border border-border text-[10px] font-semibold text-textPrimary uppercase tracking-wide">
          <FontAwesomeIcon icon={icon} className={color} /> {fallbackLabel(result.content_type)}
        </span>
        {result.publish_date && (
          <span className="text-[11px] text-textSecondary">{formatDate(result.publish_date)}</span>
        )}
      </div>
      <h4 className="text-[15px] font-semibold text-textPrimary mb-1.5 leading-snug">
        {result.title}
      </h4>
      <p className="text-[13px] text-textSecondary line-clamp-2 leading-relaxed">
        {result.excerpt}
      </p>
    </a>
  );
}
