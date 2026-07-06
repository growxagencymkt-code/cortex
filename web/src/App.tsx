import { useState } from 'react';
import { HealthBadge } from './components/HealthBadge.tsx';
import { Conversation } from './surfaces/Conversation.tsx';
import { Inbox } from './surfaces/Inbox.tsx';
import { Panels } from './surfaces/Panels.tsx';

type Surface = 'conversation' | 'inbox' | 'panels';

const SURFACES: { id: Surface; label: string; hint: string }[] = [
  { id: 'conversation', label: 'Conversación', hint: 'Chat sobre la memoria' },
  { id: 'inbox', label: 'Bandeja', hint: 'Cola de decisiones' },
  { id: 'panels', label: 'Paneles', hint: 'Estado operativo' },
];

export default function App() {
  const [surface, setSurface] = useState<Surface>('conversation');

  return (
    <div className="flex h-screen flex-col bg-ink-900 text-gray-light">
      <header className="flex shrink-0 items-center justify-between border-b border-ink-700 px-4 py-2.5">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="font-display text-base font-bold tracking-tight text-white">
              CORTEX
            </span>
            <span className="hidden text-2xs text-gray sm:inline">
              memoria operativa · trazable
            </span>
          </div>
        </div>
        <HealthBadge />
      </header>

      <nav className="flex shrink-0 gap-1 border-b border-ink-700 bg-ink-800/40 px-3">
        {SURFACES.map((s) => (
          <button
            key={s.id}
            type="button"
            onClick={() => setSurface(s.id)}
            title={s.hint}
            className={`-mb-px border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
              surface === s.id
                ? 'border-gold text-white'
                : 'border-transparent text-gray hover:text-gray-light'
            }`}
          >
            {s.label}
          </button>
        ))}
      </nav>

      <main className="mx-auto w-full max-w-4xl flex-1 overflow-hidden px-4 py-4">
        {surface === 'conversation' ? (
          <Conversation />
        ) : surface === 'inbox' ? (
          <div className="h-full overflow-y-auto">
            <Inbox />
          </div>
        ) : (
          <Panels />
        )}
      </main>
    </div>
  );
}
