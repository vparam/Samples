import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faBoxOpen } from '@fortawesome/free-solid-svg-icons';

export default function Header() {
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
          <p className="text-[11px] text-textSecondary font-medium">Internal AI Assistant</p>
        </div>
      </div>
      <button
        type="button"
        className="w-9 h-9 rounded-full bg-surface flex items-center justify-center text-textSecondary hover:bg-surfaceHover transition-colors border border-border/50 overflow-hidden"
      >
        <img
          src="https://storage.googleapis.com/uxpilot-auth.appspot.com/avatars/avatar-4.jpg"
          alt="User Profile"
          className="w-full h-full rounded-full object-cover"
        />
      </button>
    </header>
  );
}
