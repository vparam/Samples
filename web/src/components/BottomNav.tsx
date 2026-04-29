import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faHouse } from '@fortawesome/free-solid-svg-icons';
import { faLightbulb, faFlag } from '@fortawesome/free-regular-svg-icons';
import type { IconDefinition } from '@fortawesome/fontawesome-svg-core';

interface NavItem {
  label: string;
  icon: IconDefinition;
  active?: boolean;
}

const ITEMS: NavItem[] = [
  { label: 'Search', icon: faHouse, active: true },
  { label: 'Prompt Guide', icon: faLightbulb },
  { label: 'Report Issue', icon: faFlag },
];

export default function BottomNav() {
  return (
    <nav className="fixed bottom-0 left-0 right-0 max-w-[430px] mx-auto glass-nav border-t border-border/50 px-6 py-4 flex justify-between items-center z-30 pb-safe">
      {ITEMS.map((item) => (
        <button
          key={item.label}
          type="button"
          className={
            item.active
              ? 'flex flex-col items-center gap-1.5 text-primary group'
              : 'flex flex-col items-center gap-1.5 text-textSecondary hover:text-textPrimary group transition-colors'
          }
        >
          <div
            className={
              item.active
                ? 'w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center group-hover:bg-primary/20 transition-colors'
                : 'w-10 h-10 rounded-full flex items-center justify-center group-hover:bg-surface transition-colors'
            }
          >
            <FontAwesomeIcon icon={item.icon} className="text-[18px]" />
          </div>
          <span
            className={
              item.active ? 'text-[10px] font-semibold' : 'text-[10px] font-medium'
            }
          >
            {item.label}
          </span>
        </button>
      ))}
    </nav>
  );
}
