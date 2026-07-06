import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { retrieve } from '../api/client.ts';
import type { RetrieveResponse } from '../api/types.ts';
import { ChunkEvidenceChip, EvidenceChip } from '../components/EvidenceChip.tsx';
import { ErrorState, LoadingState } from '../components/states.tsx';

interface Turn {
  id: number;
  query: string;
  answer?: RetrieveResponse;
  error?: unknown;
  pending: boolean;
}

/**
 * Conversation (§11.1): chat over the memory. There is no free-text generation
 * here — the surface renders exactly what /api/retrieve returns (graph facts +
 * chunks), each with an expandable evidence chip. When answerable=false we say
 * so plainly instead of inventing an answer (§8: never fill with general knowledge).
 */
export function Conversation() {
  const [input, setInput] = useState('');
  const [turns, setTurns] = useState<Turn[]>([]);

  const ask = useMutation({
    mutationFn: (query: string) => retrieve(query),
  });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const query = input.trim();
    if (!query || ask.isPending) return;

    const id = Date.now();
    setTurns((t) => [...t, { id, query, pending: true }]);
    setInput('');

    ask.mutate(query, {
      onSuccess: (answer) =>
        setTurns((t) =>
          t.map((turn) =>
            turn.id === id ? { ...turn, answer, pending: false } : turn,
          ),
        ),
      onError: (error) =>
        setTurns((t) =>
          t.map((turn) =>
            turn.id === id ? { ...turn, error, pending: false } : turn,
          ),
        ),
    });
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 space-y-6 overflow-y-auto px-1 py-2">
        {turns.length === 0 ? (
          <div className="mx-auto mt-16 max-w-lg text-center">
            <h2 className="font-display text-lg font-semibold text-gray-light">
              Preguntá a la memoria
            </h2>
            <p className="mt-2 text-sm text-gray">
              Las respuestas se construyen solo con hechos del grafo y fragmentos
              recuperados, cada uno con su evidencia. Si no hay evidencia, CORTEX
              dice que no sabe — no inventa.
            </p>
            <div className="mt-4 flex flex-wrap justify-center gap-2 text-xs">
              {SAMPLES.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setInput(s)}
                  className="rounded border border-ink-600 bg-ink-800/60 px-2 py-1 text-gray transition-colors hover:border-cyan/50 hover:text-gray-light"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          turns.map((turn) => <TurnView key={turn.id} turn={turn} />)
        )}
      </div>

      <form
        onSubmit={submit}
        className="mt-2 flex items-end gap-2 border-t border-ink-700 pt-3"
      >
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) submit(e);
          }}
          rows={1}
          placeholder="Ej.: ¿Qué compromisos vencen esta semana?"
          className="min-h-[2.5rem] flex-1 resize-none rounded border border-ink-600 bg-ink-900 px-3 py-2 text-sm text-gray-light placeholder:text-gray/60 focus:border-cyan focus:outline-none"
        />
        <button
          type="submit"
          disabled={ask.isPending || !input.trim()}
          className="h-10 rounded bg-blue px-4 text-sm font-medium text-white transition-colors hover:bg-cyan disabled:cursor-not-allowed disabled:opacity-40"
        >
          Consultar
        </button>
      </form>
    </div>
  );
}

const SAMPLES = [
  '¿Qué compromisos vencen esta semana?',
  '¿Qué se decidió sobre el proveedor?',
  '¿Con quién hablé de la migración?',
];

function TurnView({ turn }: { turn: Turn }) {
  return (
    <div className="space-y-2">
      <div className="flex justify-end">
        <p className="max-w-[80%] rounded-lg rounded-br-sm bg-ink-700 px-3 py-2 text-sm text-gray-light">
          {turn.query}
        </p>
      </div>

      <div className="max-w-[92%]">
        {turn.pending ? (
          <LoadingState label="Recuperando de la memoria…" />
        ) : turn.error ? (
          <ErrorState error={turn.error} />
        ) : turn.answer ? (
          <AnswerView answer={turn.answer} />
        ) : null}
      </div>
    </div>
  );
}

function AnswerView({ answer }: { answer: RetrieveResponse }) {
  const hasEvidence = answer.facts.length > 0 || answer.chunks.length > 0;

  if (!answer.answerable || !hasEvidence) {
    return (
      <div className="rounded-lg rounded-bl-sm border border-gold/30 bg-gold/5 px-3 py-2.5 text-sm text-gold/90">
        <p className="font-medium">Sin evidencia suficiente en la memoria.</p>
        <p className="mt-1 text-gold/70">
          {answer.note ||
            'No encontré hechos ni fragmentos que respalden una respuesta. No voy a inventar.'}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3 rounded-lg rounded-bl-sm border border-ink-600 bg-ink-800/60 px-3 py-3">
      {answer.note ? (
        <p className="text-sm leading-relaxed text-gray-light">{answer.note}</p>
      ) : null}

      {answer.facts.length > 0 ? (
        <section>
          <h4 className="mb-1.5 text-2xs font-semibold uppercase tracking-wide text-gray">
            Hechos del grafo
          </h4>
          <ul className="space-y-1.5">
            {answer.facts.map((f, i) => (
              <li
                key={`${f.src}-${f.rel}-${f.dst}-${i}`}
                className="flex flex-wrap items-center gap-1.5 text-sm text-gray-light"
              >
                <span className="font-medium text-white">{f.src}</span>
                <span className="rounded bg-ink-700 px-1.5 py-0.5 font-mono text-2xs text-cyan">
                  {f.rel}
                </span>
                <span className="font-medium text-white">{f.dst}</span>
                <EvidenceChip eventId={f.evidence_event} />
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {answer.chunks.length > 0 ? (
        <section>
          <h4 className="mb-1.5 text-2xs font-semibold uppercase tracking-wide text-gray">
            Fragmentos recuperados
          </h4>
          <ul className="space-y-2">
            {answer.chunks.map((c, i) => (
              <li
                key={`${c.event_id}-${i}`}
                className="rounded border border-ink-700 bg-ink-900/60 p-2"
              >
                <p className="text-sm leading-snug text-gray-light">{c.text}</p>
                <div className="mt-1.5">
                  <ChunkEvidenceChip chunk={c} />
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
