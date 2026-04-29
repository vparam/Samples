import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faFilePdf, faVideo, faFileLines } from '@fortawesome/free-solid-svg-icons';
import type { IconDefinition } from '@fortawesome/fontawesome-svg-core';
import type { ResultKind, SearchResult } from '../types';

const KIND_ICON: Record<ResultKind, { icon: IconDefinition; color: string }> = {
  pdf: { icon: faFilePdf, color: 'text-red-500' },
  video: { icon: faVideo, color: 'text-blue-500' },
  article: { icon: faFileLines, color: 'text-emerald-500' },
};

interface ResultCardProps {
  result: SearchResult;
}

export default function ResultCard({ result }: ResultCardProps) {
  const { icon, color } = KIND_ICON[result.kind];
  return (
    <a
      href="#"
      className="block bg-surface rounded-[16px] p-4 border border-border/60 hover:border-primary/30 hover:bg-surfaceHover transition-all shadow-sm"
    >
      <div className="flex items-center gap-2 mb-2">
        <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md bg-white border border-border text-[10px] font-semibold text-textPrimary uppercase tracking-wide">
          <FontAwesomeIcon icon={icon} className={color} /> {result.kindLabel}
        </span>
        <span className="text-[11px] text-textSecondary">{result.date}</span>
      </div>
      <h4 className="text-[15px] font-semibold text-textPrimary mb-1.5 leading-snug">
        {result.title}
      </h4>
      <p className="text-[13px] text-textSecondary line-clamp-2 leading-relaxed">
        {result.snippet}
      </p>
    </a>
  );
}
