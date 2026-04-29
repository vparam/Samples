import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faMagnifyingGlass, faRotateRight } from '@fortawesome/free-solid-svg-icons';
import { faFolderOpen, faFlag } from '@fortawesome/free-regular-svg-icons';

interface EmptyStateProps {
  query: string;
  hasSearched: boolean;
  onClear?: () => void;
  onSuggestionSelect?: (suggestion: string) => void;
  onReportIssue?: () => void;
}

const SUGGESTIONS = ['Recyclable materials', 'Lead times for PCR', 'Glass vs PET cost analysis'];

export default function EmptyState({
  query,
  hasSearched,
  onClear,
  onSuggestionSelect,
  onReportIssue,
}: EmptyStateProps) {
  const heading = hasSearched ? 'No results found' : 'Run a search to see results';
  const body = hasSearched
    ? `We couldn't find any documents matching "${query}" in the repository.`
    : 'Type a question above and tap the green button — only indexed MJS content is returned.';

  return (
    <div className="flex flex-col items-center justify-center py-10 px-4 text-center bg-surface rounded-[20px] border-2 border-dashed border-border/80">
      <div className="w-16 h-16 rounded-2xl bg-white border border-border flex items-center justify-center mb-4 shadow-sm">
        <FontAwesomeIcon icon={faFolderOpen} className="text-2xl text-[#475569]" />
      </div>
      <h4 className="text-[18px] font-bold text-[#0F172A] mb-2">{heading}</h4>
      <p className="text-[14px] text-[#334155] max-w-[260px] leading-relaxed mb-6 font-medium">
        {body}
      </p>

      <div className="w-full bg-white rounded-xl p-4 border border-border mb-6 text-left shadow-sm">
        <h5 className="text-[13px] font-bold text-[#0F172A] mb-3 uppercase tracking-wide">
          Try searching for:
        </h5>
        <div className="flex flex-col gap-2">
          {SUGGESTIONS.map((label) => (
            <button
              key={label}
              type="button"
              onClick={() => onSuggestionSelect?.(label)}
              className="flex items-center gap-2 text-[14px] font-medium text-[#334155] hover:text-primary transition-colors text-left w-full p-2 rounded-lg hover:bg-surface"
            >
              <FontAwesomeIcon
                icon={faMagnifyingGlass}
                className="text-[12px] text-primary"
              />
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-col sm:flex-row items-center gap-3 w-full justify-center">
        <button
          type="button"
          onClick={onClear}
          className="px-5 py-2.5 rounded-full bg-white border border-border text-[14px] font-semibold text-[#0F172A] hover:bg-surfaceHover transition-colors shadow-sm flex items-center justify-center gap-2 w-full sm:w-auto"
        >
          <FontAwesomeIcon icon={faRotateRight} className="text-[12px]" />
          Clear Search
        </button>
        <button
          type="button"
          onClick={onReportIssue}
          className="px-5 py-2.5 rounded-full bg-surface border border-border/50 text-[14px] font-semibold text-red-600 hover:bg-red-50 transition-colors flex items-center justify-center gap-2 w-full sm:w-auto"
        >
          <FontAwesomeIcon icon={faFlag} className="text-[12px]" />
          Report missing content
        </button>
      </div>
    </div>
  );
}
