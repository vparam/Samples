import { useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faBoxOpen, faArrowRight } from '@fortawesome/free-solid-svg-icons';
import { useAuth } from './AuthContext';

const QUICK_LOGINS = [
  { email: 'alice@mjs-packaging.example', label: 'Alice (Standard)' },
  { email: 'tom@mjs-packaging.example', label: 'Tom (Admin)' },
];

export default function LoginScreen() {
  const { login, error } = useAuth();
  const [email, setEmail] = useState('');
  const [pending, setPending] = useState(false);

  const submit = async (value: string) => {
    if (!value.trim()) return;
    setPending(true);
    try {
      await login(value.trim());
    } catch {
      /* error surfaced via context */
    } finally {
      setPending(false);
    }
  };

  return (
    <main className="w-full max-w-[430px] mx-auto min-h-screen flex flex-col px-5 pt-16 pb-12 bg-background">
      <div className="flex items-center gap-3 mb-10">
        <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center text-primary">
          <FontAwesomeIcon icon={faBoxOpen} />
        </div>
        <div>
          <h1 className="text-[16px] font-semibold tracking-tight text-textPrimary leading-tight">
            MJS Content Repo
          </h1>
          <p className="text-[12px] text-textSecondary font-medium">Internal AI Assistant</p>
        </div>
      </div>

      <div className="flex-1 flex flex-col justify-center">
        <h2 className="text-[26px] font-bold tracking-tight text-textPrimary mb-2">Sign in</h2>
        <p className="text-[14px] text-[#475569] mb-8 leading-relaxed">
          Use your <span className="font-semibold">@mjs-packaging.example</span> address.
          Access is restricted to MJS employees.
        </p>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit(email);
          }}
          className="flex flex-col gap-3"
        >
          <label className="text-[12px] font-semibold uppercase tracking-wide text-textSecondary">
            Work email
          </label>
          <div className="search-glow transition-all duration-300 rounded-[16px] bg-white border-2 border-border shadow-sm flex items-center">
            <input
              type="email"
              autoFocus
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@mjs-packaging.example"
              className="flex-1 bg-transparent border-none outline-none py-4 px-4 text-[15px] font-medium placeholder:text-textSecondary"
            />
            <button
              type="submit"
              disabled={pending}
              aria-label="Sign in"
              className="mr-2 w-10 h-10 rounded-[12px] bg-primary text-white flex items-center justify-center hover:bg-primary/90 transition-colors disabled:opacity-50"
            >
              <FontAwesomeIcon icon={faArrowRight} />
            </button>
          </div>
          {error && (
            <p className="text-[13px] text-red-600 font-medium" role="alert">
              {error}
            </p>
          )}
        </form>

        <div className="mt-10">
          <p className="text-[11px] uppercase tracking-wider text-textSecondary font-semibold mb-3">
            Demo accounts
          </p>
          <div className="flex flex-col gap-2">
            {QUICK_LOGINS.map((q) => (
              <button
                key={q.email}
                type="button"
                onClick={() => submit(q.email)}
                disabled={pending}
                className="text-left bg-surface hover:bg-surfaceHover border border-border rounded-xl px-4 py-3 transition-colors disabled:opacity-50"
              >
                <div className="text-[14px] font-semibold text-textPrimary">{q.label}</div>
                <div className="text-[12px] text-textSecondary">{q.email}</div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </main>
  );
}
