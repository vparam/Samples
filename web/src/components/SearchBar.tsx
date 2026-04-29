import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faArrowUp, faMagnifyingGlass } from '@fortawesome/free-solid-svg-icons';

interface SearchBarProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit?: () => void;
}

export default function SearchBar({ value, onChange, onSubmit }: SearchBarProps) {
  return (
    <form
      className="w-full relative search-glow transition-all duration-300 rounded-[20px] bg-white border-2 border-border shadow-sm"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit?.();
      }}
    >
      <div className="absolute left-4 top-1/2 -translate-y-1/2 text-primary">
        <FontAwesomeIcon icon={faMagnifyingGlass} className="text-[16px]" />
      </div>
      <input
        type="text"
        className="w-full bg-transparent border-none outline-none py-5 pl-[48px] pr-[56px] text-[16px] text-[#0F172A] placeholder:text-[#64748B] font-medium h-[64px]"
        placeholder="Ask about sustainable bottle options..."
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      <button
        type="submit"
        className="absolute right-2 top-1/2 -translate-y-1/2 w-12 h-12 rounded-[14px] bg-primary text-white flex items-center justify-center shadow-sm hover:bg-primary/90 transition-colors"
        aria-label="Submit search"
      >
        <FontAwesomeIcon icon={faArrowUp} className="text-[15px]" />
      </button>
    </form>
  );
}
