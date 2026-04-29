import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faHouse, faShieldHalved } from '@fortawesome/free-solid-svg-icons';
import { faLightbulb, faFlag } from '@fortawesome/free-regular-svg-icons';
import type { IconDefinition } from '@fortawesome/fontawesome-svg-core';
import { useAuth } from '../auth/AuthContext';

export type NavView = 'search' | 'guide' | 'report' | 'admin';

interface NavItem {
  id: NavView;
  label: string;
  icon: IconDefinition;
  adminOnly?: boolean;
}

const ITEMS: NavItem[] = [
  { id: 'search', label: 'Search', icon: faHouse },
  { id: 'guide', label: 'Prompt Guide', icon: faLightbulb },
  { id: 'report', label: 'Report Issue', icon: faFlag },
  { id: 'admin', label: 'Admin', icon: faShieldHalved, adminOnly: true },
];

interface BottomNavProps {
  active: NavView;
  onChange: (view: NavView) => void;
}

export default function BottomNav({ active, onChange }: BottomNavProps) {
  const { user } = useAuth();
  const isAdmin = user?.role === 'Admin';
  const items = ITEMS.filter((i) => !i.adminOnly || isAdmin);

  return (
    <nav className="fixed bottom-0 left-0 right-0 max-w-[430px] mx-auto glass-nav border-t border-border/50 px-6 py-4 flex justify-between items-center z-30 pb-safe">
      {items.map((item) => {
        const isActive = active === item.id;
        return (
          <button
            key={item.id}
            type="button"
            onClick={() => onChange(item.id)}
            className={
              isActive
                ? 'flex flex-col items-center gap-1.5 text-primary group'
                : 'flex flex-col items-center gap-1.5 text-textSecondary hover:text-textPrimary group transition-colors'
            }
          >
            <div
              className={
                isActive
                  ? 'w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center group-hover:bg-primary/20 transition-colors'
                  : 'w-10 h-10 rounded-full flex items-center justify-center group-hover:bg-surface transition-colors'
              }
            >
              <FontAwesomeIcon icon={item.icon} className="text-[18px]" />
            </div>
            <span
              className={isActive ? 'text-[10px] font-semibold' : 'text-[10px] font-medium'}
            >
              {item.label}
            </span>
          </button>
        );
      })}
    </nav>
  );
}
