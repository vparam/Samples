import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faBoxOpen, faRightFromBracket } from '@fortawesome/free-solid-svg-icons';
import { useAuth } from '../auth/AuthContext';

export default function Header() {
  const { user, logout } = useAuth();
  return (
    <header className="px-5 pt-12 pb-4 flex items-center justify-between sticky top-0 bg-background/95 backdrop-blur z-20 border-b border-border/50">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center text-primary">
          <FontAwesomeIcon icon={faBoxOpen} className="text-sm" />
        </div>
        <div>
          <h1 className="text-[15px] font-semibold tracking-tight text-textPrimary leading-tight">
            MJS Content Repo
          </h1>
          <p className="text-[11px] text-textSecondary font-medium">
            {user ? `${user.name} · ${user.role === 'Admin' ? 'Admin' : 'Standard'}` : 'Internal AI Assistant'}
          </p>
        </div>
      </div>
      {user && (
        <button
          type="button"
          onClick={logout}
          className="w-9 h-9 rounded-full bg-surface flex items-center justify-center text-textSecondary hover:bg-surfaceHover transition-colors border border-border/50"
          aria-label="Sign out"
          title="Sign out"
        >
          <FontAwesomeIcon icon={faRightFromBracket} className="text-[13px]" />
        </button>
      )}
    </header>
  );
}
