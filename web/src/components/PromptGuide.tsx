import { useEffect, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faLightbulb } from '@fortawesome/free-regular-svg-icons';
import { api } from '../api/client';
import type { GuideResponse } from '../types';

export default function PromptGuide() {
  const [guide, setGuide] = useState<GuideResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<GuideResponse>('/api/guide')
      .then(setGuide)
      .catch((e) => setError(e?.detail ?? 'Failed to load guide'));
  }, []);

  return (
    <section className="px-5 pt-8 pb-6 flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center text-primary">
          <FontAwesomeIcon icon={faLightbulb} />
        </div>
        <div>
          <h2 className="text-[20px] font-bold tracking-tight text-textPrimary leading-tight">
            {guide?.title ?? 'How to search'}
          </h2>
          <p className="text-[12px] text-textSecondary font-medium">
            Tips for getting the most out of the index
          </p>
        </div>
      </div>

      {error && <p className="text-[13px] text-red-600 font-medium">{error}</p>}

      <div className="flex flex-col gap-3">
        {guide?.sections.map((s) => (
          <div
            key={s.heading}
            className="bg-surface rounded-[16px] p-4 border border-border/60 shadow-sm"
          >
            <h3 className="text-[14px] font-semibold text-textPrimary mb-2">{s.heading}</h3>
            <p className="text-[13px] text-[#334155] leading-relaxed">{s.body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
