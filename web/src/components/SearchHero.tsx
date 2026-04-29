import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faWandSparkles } from '@fortawesome/free-solid-svg-icons';
import { faCircleQuestion } from '@fortawesome/free-regular-svg-icons';
import SearchBar from './SearchBar';
import LoadingProgress from './LoadingProgress';
import QuickSuggestions from './QuickSuggestions';

interface SearchHeroProps {
  query: string;
  onQueryChange: (value: string) => void;
  onSubmit?: () => void;
  onSuggestionSelect?: (suggestion: string) => void;
  loading?: boolean;
}

export default function SearchHero({
  query,
  onQueryChange,
  onSubmit,
  onSuggestionSelect,
  loading = false,
}: SearchHeroProps) {
  return (
    <section className="px-5 pt-8 pb-6 flex flex-col items-center relative">
      <div className="absolute top-0 right-5">
        <button
          type="button"
          className="flex items-center gap-1.5 text-[12px] font-medium text-primary hover:text-primary/80 transition-colors bg-primary/10 px-3 py-1.5 rounded-full"
        >
          <FontAwesomeIcon icon={faCircleQuestion} />
          How to ask
        </button>
      </div>

      <div className="w-16 h-16 rounded-full bg-gradient-to-br from-primaryLight to-surface flex items-center justify-center mb-6 mt-4 shadow-sm border border-primary/20 relative">
        <FontAwesomeIcon
          icon={faWandSparkles}
          className="text-2xl text-primary absolute animate-pulse"
        />
      </div>

      <h2 className="text-[26px] font-bold text-center mb-2 tracking-tight text-[#0F172A]">
        What can I find for you?
      </h2>
      <p className="text-[15px] text-[#475569] text-center mb-8 max-w-[280px]">
        Search the MJS packaging knowledge base instantly.
      </p>

      <SearchBar value={query} onChange={onQueryChange} onSubmit={onSubmit} />

      {loading && <LoadingProgress />}

      <QuickSuggestions onSelect={onSuggestionSelect} />
    </section>
  );
}
