import { useState } from 'react';
import type { RetrievedChunk } from '../api/types.ts';

/**
 * Evidence chip (§11.1). A compact, clickable token that expands to reveal the
 * source event: event_id + source + timestamp (+ retrieved text when available).
 * Trust comes from traceability, so every generated claim is backed by one of these.
 */
export function EvidenceChip({
  eventId,
  source,
  ts,
  score,
  text,
}: {
  eventId: number | string;
  source?: string;
  ts?: string;
  score?: number;
  text?: string;
}) {
  const [open, setOpen] = useState(false);

  return (
    <span className="inline-block">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="inline-flex items-center gap-1 rounded border border-cyan/40 bg-cyan/10 px-1.5 py-0.5 text-2xs font-medium text-cyan transition-colors hover:bg-cyan/20"
        title={source ? `${source} · evento ${eventId}` : `evento ${eventId}`}
      >
        <span className="font-mono">#{eventId}</span>
        {source ? <span className="text-cyan/70">{source}</span> : null}
      </button>

      {open ? (
        <span className="mt-1 block rounded border border-ink-600 bg-ink-900 p-2 text-2xs text-gray-light">
          <span className="flex flex-wrap gap-x-3 gap-y-0.5 text-gray">
            <span>
              evento <span className="font-mono text-gray-light">#{eventId}</span>
            </span>
            {source ? (
              <span>
                fuente <span className="text-gray-light">{source}</span>
              </span>
            ) : null}
            {ts ? (
              <span>
                ts <span className="text-gray-light">{formatTs(ts)}</span>
              </span>
            ) : null}
            {typeof score === 'number' ? (
              <span>
                score <span className="text-gray-light">{score.toFixed(3)}</span>
              </span>
            ) : null}
          </span>
          {text ? (
            <span className="mt-1 block whitespace-pre-wrap border-t border-ink-600 pt-1 text-gray-light">
              {text}
            </span>
          ) : null}
        </span>
      ) : null}
    </span>
  );
}

export function ChunkEvidenceChip({ chunk }: { chunk: RetrievedChunk }) {
  return (
    <EvidenceChip
      eventId={chunk.event_id}
      source={chunk.source}
      ts={chunk.ts}
      score={chunk.score}
      text={chunk.text}
    />
  );
}

function formatTs(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString('es-AR', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}
