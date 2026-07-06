import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { chat, retrieve } from '../api/client.ts';
import type { GroundedAnswer, RetrieveResponse } from '../api/types.ts';
import { ChunkEvidenceChip, EvidenceChip } from '../components/EvidenceChip.tsx';
import { ErrorState, LoadingState } from '../components/states.tsx';

/** What one turn resolves to: the generated answer (may be absent if /api/chat
 *  failed) plus the raw evidence from /api/retrieve. */
interface TurnResult {
  answer?: GroundedAnswer;
  chatError?: unknown;
  evidence: RetrieveResponse;
}

interface Turn {
  id: number;
  query: string;
  result?: TurnResult;
  error?: unknown;
  pending: boolean;
}

/**
 * Conversation (§11.1): chat over the memory. On each turn we call BOTH
 * /api/chat (a grounded, generated answer) and /api/retrieve (the raw evidence
 * that backs it). The generated answer leads; the evidence sits below it so any
 * claim can be traced. If /api/chat fails we still show the evidence — we never
 * blank the screen. When there is no evidence, CORTEX says it does not know
 * instead of inventing an answer (§8: never fill with general knowledge).
 */
export function Conversation() {
  const [input, setInput] = useState('');
  const [turns, setTurns] = useState<Turn[]>([]);

  const ask = useMutation({
    mutationFn: async (query: string): Promise<TurnResult> => {
      // /api/chat may not be wired up or may error — don't let it sink the turn.
      const [answerOutcome, evidence] = await Promise.all([
        chat(query).then(
          (a) => ({ ok: true as const, value: a }),
          (e) => ({ ok: false as const, error: e }),
        ),
        retrieve(query),
      ]);
      return answerOutcome.ok
        ? { answer: answerOutcome.value, evidence }
        : { chatError: answerOutcome.error, evidence };
    },
  });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const query = input.trim();
    if (!query || ask.isPending) return;

    const id = Date.now();
    setTurns((t) => [...t, { id, query, pending: true }]);
    setInput('');

    ask.mutate(query, {
      onSuccess: (result) =>
        setTurns((t) =>
          t.map((turn) =>
            turn.id === id ? { ...turn, result, pending: false } : turn,
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
              CORTEX responde con una respuesta redactada y, debajo, la evidencia
              que la respalda: hechos del grafo y fragmentos recuperados, cada uno
              con su fuente. Si no hay evidencia, dice que no sabe — no inventa.
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

      <div className="max-w-[92%] space-y-3">
        {turn.pending ? (
          <LoadingState label="Recuperando de la memoria…" />
        ) : turn.error ? (
          <ErrorState error={turn.error} />
        ) : turn.result ? (
          <>
            <AnswerBlock result={turn.result} />
            <EvidenceBlock evidence={turn.result.evidence} />
          </>
        ) : null}
      </div>
    </div>
  );
}

// --- Generated answer (leads the turn) -----------------------------------

const ENGINE_BADGE: Record<GroundedAnswer['engine'], { label: string; cls: string }> = {
  llm: { label: 'IA', cls: 'border-cyan/40 bg-cyan/10 text-cyan' },
  extractive: {
    label: 'Extractivo · $0',
    cls: 'border-green/40 bg-green/10 text-green',
  },
  none: { label: 'Sin evidencia', cls: 'border-gray/40 bg-ink-700 text-gray' },
};

function EngineBadge({ engine }: { engine: GroundedAnswer['engine'] }) {
  const b = ENGINE_BADGE[engine] ?? ENGINE_BADGE.none;
  return (
    <span
      className={`shrink-0 rounded border px-1.5 py-0.5 text-2xs font-medium ${b.cls}`}
    >
      {b.label}
    </span>
  );
}

function AnswerBlock({ result }: { result: TurnResult }) {
  const { answer, chatError } = result;

  // /api/chat unavailable or errored: fall back to evidence-only, but say so.
  if (!answer) {
    return (
      <div className="rounded-lg rounded-bl-sm border border-ink-600 bg-ink-800/40 px-4 py-3 text-sm text-gray">
        No pude generar una respuesta redactada
        {chatError instanceof Error && chatError.message
          ? ` (${chatError.message})`
          : ''}
        . Debajo está la evidencia recuperada.
      </div>
    );
  }

  // Grounded=false or engine=none: CORTEX abstains rather than invent.
  if (!answer.grounded || answer.engine === 'none') {
    return (
      <div className="rounded-lg rounded-bl-sm border border-gold/30 bg-gold/5 px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-medium text-gold/90">
            No sé — sin evidencia suficiente en la memoria.
          </p>
          <EngineBadge engine={answer.engine} />
        </div>
        <p className="mt-1 text-sm leading-relaxed text-gold/70">
          {answer.answer ||
            answer.note ||
            'No encontré hechos ni fragmentos que respalden una respuesta. No voy a inventar.'}
        </p>
      </div>
    );
  }

  // Grounded answer — this is the star of the surface.
  return (
    <div className="rounded-lg rounded-bl-sm border border-cyan/25 bg-ink-800/70 px-4 py-3.5 shadow-[0_0_0_1px_rgba(55,182,199,0.06)]">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-2xs font-semibold uppercase tracking-wide text-gray">
          Respuesta
        </span>
        <EngineBadge engine={answer.engine} />
      </div>
      <p className="whitespace-pre-wrap font-display text-[0.95rem] leading-relaxed text-gray-light">
        {answer.answer}
      </p>
      {answer.used_events.length > 0 ? (
        <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-ink-700 pt-2.5">
          <span className="text-2xs text-gray">Basado en</span>
          {answer.used_events.map((ev, i) => (
            <EvidenceChip key={`${ev}-${i}`} eventId={ev} />
          ))}
        </div>
      ) : null}
      {answer.note ? (
        <p className="mt-2 text-2xs text-gray">{answer.note}</p>
      ) : null}
    </div>
  );
}

// --- Evidence (the traceable backing, below the answer) ------------------

function EvidenceBlock({ evidence }: { evidence: RetrieveResponse }) {
  const hasEvidence = evidence.facts.length > 0 || evidence.chunks.length > 0;
  if (!hasEvidence) return null;

  return (
    <div className="space-y-3 rounded-lg border border-ink-700 bg-ink-900/50 px-4 py-3">
      <h4 className="text-2xs font-semibold uppercase tracking-wide text-gray">
        Evidencia
      </h4>

      {evidence.facts.length > 0 ? (
        <section>
          <h5 className="mb-1.5 text-2xs font-medium uppercase tracking-wide text-gray/80">
            Hechos del grafo
          </h5>
          <ul className="space-y-1.5">
            {evidence.facts.map((f, i) => (
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

      {evidence.chunks.length > 0 ? (
        <section>
          <h5 className="mb-1.5 text-2xs font-medium uppercase tracking-wide text-gray/80">
            Fragmentos recuperados
          </h5>
          <ul className="space-y-2">
            {evidence.chunks.map((c, i) => (
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
