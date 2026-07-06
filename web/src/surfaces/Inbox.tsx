import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { decide, getInbox } from '../api/client.ts';
import type { DecisionCard, DecisionKind } from '../api/types.ts';
import { EvidenceChip } from '../components/EvidenceChip.tsx';
import { EmptyState, ErrorState, LoadingState } from '../components/states.tsx';

/**
 * Decision inbox (§11.2): a queue of cards. Each card follows the anatomy
 * title → summarized recommendation → Approve/Edit/Reject → collapsible "why"
 * (reasoning + evidence). Anti-inertia cards arrive without a recommendation
 * (~1 in 15) and force the human to decide unaided.
 */
export function Inbox() {
  const query = useQuery({ queryKey: ['inbox'], queryFn: getInbox });

  if (query.isLoading) return <LoadingState label="Cargando bandeja…" />;
  if (query.isError) return <ErrorState error={query.error} />;

  const cards = query.data?.cards ?? [];
  if (cards.length === 0) {
    return (
      <EmptyState
        title="Bandeja vacía"
        hint="No hay decisiones pendientes. Las propuestas de acción, desambiguaciones y alertas de compromiso aparecerán aquí."
      />
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray">
          {cards.length} {cards.length === 1 ? 'decisión' : 'decisiones'} en cola
        </p>
      </div>
      {cards.map((card) => (
        <Card key={card.id} card={card} />
      ))}
    </div>
  );
}

const KIND_LABEL: Record<string, string> = {
  action: 'Propuesta de acción',
  disambiguation: 'Desambiguación',
  new_agent: 'Nuevo agente',
  commitment_alert: 'Alerta de compromiso',
};

function kindStyle(kind: DecisionKind): string {
  switch (kind) {
    case 'commitment_alert':
      return 'border-red-500/40 text-red-300 bg-red-500/10';
    case 'disambiguation':
      return 'border-gold/40 text-gold bg-gold/10';
    case 'new_agent':
      return 'border-green/40 text-green bg-green/10';
    default:
      return 'border-cyan/40 text-cyan bg-cyan/10';
  }
}

function Card({ card }: { card: DecisionCard }) {
  const qc = useQueryClient();
  const [showWhy, setShowWhy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState('');
  const [resolved, setResolved] = useState<null | string>(null);

  const noRecommendation = card.recommendation.trim() === '';

  const mutation = useMutation({
    mutationFn: (choice: 'approve' | 'edit' | 'reject') =>
      decide(card.id, choice, choice === 'edit' ? note : undefined),
    onSuccess: (_data, choice) => {
      setResolved(choice);
      // Refresh queue; the backend logs the decision as an event.
      void qc.invalidateQueries({ queryKey: ['inbox'] });
    },
  });

  const disabled = mutation.isPending || resolved !== null;

  return (
    <article className="rounded-lg border border-ink-600 bg-ink-800/60">
      <header className="flex items-start justify-between gap-3 border-b border-ink-700 px-4 py-3">
        <div className="min-w-0">
          <span
            className={`inline-block rounded border px-1.5 py-0.5 text-2xs font-medium ${kindStyle(
              card.kind,
            )}`}
          >
            {KIND_LABEL[card.kind] ?? card.kind}
          </span>
          <h3 className="mt-1.5 font-display text-sm font-semibold text-gray-light">
            {card.title}
          </h3>
        </div>
        {resolved ? (
          <span className="shrink-0 rounded bg-ink-700 px-2 py-1 text-2xs font-medium uppercase text-gray-light">
            {resolved === 'approve'
              ? 'Aprobada'
              : resolved === 'reject'
                ? 'Rechazada'
                : 'Editada'}
          </span>
        ) : null}
      </header>

      <div className="px-4 py-3">
        {noRecommendation ? (
          <p className="rounded border border-gold/30 bg-gold/5 px-2 py-1.5 text-xs text-gold/90">
            Sin recomendación. Esta decisión requiere tu criterio (anti-inercia).
          </p>
        ) : (
          <p className="text-sm text-gray-light">
            <span className="text-2xs font-semibold uppercase tracking-wide text-gray">
              Recomendación:{' '}
            </span>
            {card.recommendation}
          </p>
        )}

        {editing ? (
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            placeholder="Editá la acción o dejá una nota para el log…"
            className="mt-3 w-full resize-none rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-gray-light placeholder:text-gray/60 focus:border-cyan focus:outline-none"
          />
        ) : null}

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={disabled}
            onClick={() => mutation.mutate('approve')}
            className="rounded bg-green/90 px-3 py-1.5 text-xs font-medium text-ink-900 transition-colors hover:bg-green disabled:opacity-40"
          >
            Aprobar
          </button>
          {editing ? (
            <button
              type="button"
              disabled={disabled}
              onClick={() => mutation.mutate('edit')}
              className="rounded bg-gold px-3 py-1.5 text-xs font-medium text-ink-900 transition-colors hover:bg-gold/90 disabled:opacity-40"
            >
              Guardar edición
            </button>
          ) : (
            <button
              type="button"
              disabled={disabled}
              onClick={() => setEditing(true)}
              className="rounded border border-gold/50 px-3 py-1.5 text-xs font-medium text-gold transition-colors hover:bg-gold/10 disabled:opacity-40"
            >
              Editar
            </button>
          )}
          <button
            type="button"
            disabled={disabled}
            onClick={() => mutation.mutate('reject')}
            className="rounded border border-red-500/50 px-3 py-1.5 text-xs font-medium text-red-300 transition-colors hover:bg-red-500/10 disabled:opacity-40"
          >
            Rechazar
          </button>

          <button
            type="button"
            onClick={() => setShowWhy((v) => !v)}
            aria-expanded={showWhy}
            className="ml-auto text-xs text-gray transition-colors hover:text-gray-light"
          >
            {showWhy ? '▾ Ocultar por qué' : '▸ Por qué'}
          </button>
        </div>

        {mutation.isError ? (
          <div className="mt-2">
            <ErrorState error={mutation.error} />
          </div>
        ) : null}

        {showWhy ? (
          <div className="mt-3 space-y-2 rounded border border-ink-700 bg-ink-900/60 p-3">
            <p className="whitespace-pre-wrap text-xs leading-relaxed text-gray-light">
              {card.why || 'Sin razonamiento adjunto.'}
            </p>
            {card.evidence_events.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {card.evidence_events.map((ev, i) => (
                  <EvidenceChip key={`${ev}-${i}`} eventId={ev} />
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </article>
  );
}
