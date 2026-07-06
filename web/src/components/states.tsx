import type { ReactNode } from 'react';
import { ApiError, isNotImplemented } from '../api/client.ts';

/** Thin, sober loading strip — no spinners, no decoration. */
export function LoadingState({ label = 'Cargando…' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 px-4 py-6 text-sm text-gray">
      <span className="h-2 w-2 animate-pulse rounded-full bg-cyan" aria-hidden />
      <span>{label}</span>
    </div>
  );
}

export function EmptyState({
  title,
  hint,
}: {
  title: string;
  hint?: ReactNode;
}) {
  return (
    <div className="rounded border border-ink-600/60 bg-ink-800/40 px-4 py-8 text-center">
      <p className="text-sm font-medium text-gray-light">{title}</p>
      {hint ? <p className="mt-1 text-xs text-gray">{hint}</p> : null}
    </div>
  );
}

/**
 * Distinguishes three failure modes:
 *  - backend unreachable (status 0)
 *  - feature not implemented yet (501/404) — shown as a neutral "pending" note
 *  - real error
 */
export function ErrorState({ error }: { error: unknown }) {
  if (isNotImplemented(error)) {
    return (
      <div className="rounded border border-gold/30 bg-gold/5 px-4 py-6 text-sm text-gold/90">
        Esta superficie todavía no está implementada en el backend (501).
        La interfaz está lista y se conectará cuando el endpoint responda.
      </div>
    );
  }

  const offline = error instanceof ApiError && error.status === 0;
  const message =
    error instanceof Error ? error.message : 'Error desconocido.';

  return (
    <div className="rounded border border-red-500/30 bg-red-500/5 px-4 py-6 text-sm text-red-300">
      <p className="font-medium">
        {offline ? 'Backend no disponible' : 'No se pudo completar la operación'}
      </p>
      <p className="mt-1 text-red-300/80">{message}</p>
    </div>
  );
}
