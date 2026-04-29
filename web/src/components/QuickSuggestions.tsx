interface QuickSuggestionsProps {
  onSelect?: (suggestion: string) => void;
}

const SUGGESTIONS = ['Glass vs Plastic', 'Q3 Pricing Guide', 'FDA Compliance'];

export default function QuickSuggestions({ onSelect }: QuickSuggestionsProps) {
  return (
    <div className="flex flex-wrap gap-2 mt-6 justify-center">
      {SUGGESTIONS.map((label) => (
        <button
          key={label}
          type="button"
          onClick={() => onSelect?.(label)}
          className="px-4 py-2 rounded-full bg-surface border border-border text-[13px] font-medium text-[#475569] hover:text-[#0F172A] hover:border-[#64748B] transition-colors"
        >
          {label}
        </button>
      ))}
    </div>
  );
}
