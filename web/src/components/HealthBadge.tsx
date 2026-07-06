import { useQuery } from '@tanstack/react-query';
import { getHealth } from '../api/client.ts';

/**
 * Live backend status in the header. Traceability starts with knowing whether
 * the memory is reachable, and against which pipeline version.
 */
export function HealthBadge() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    refetchInterval: 30_000,
  });

  let dot = 'bg-gray';
  let label = 'sin conexión';

  if (isLoading) {
    dot = 'bg-gold animate-pulse';
    label = 'conectando…';
  } else if (isError) {
    dot = 'bg-red-500';
    label = 'backend caído';
  } else if (data) {
    dot = data.status === 'ok' ? 'bg-green' : 'bg-gold';
    label = data.status;
  }

  return (
    <div className="flex items-center gap-3 text-2xs text-gray">
      <span className="flex items-center gap-1.5">
        <span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden />
        <span className="text-gray-light">{label}</span>
      </span>
      {data ? (
        <>
          <span title="Versión de la app">v{data.version}</span>
          <span title="Versión del pipeline">pipe {data.pipeline_ver}</span>
          <span title="Estado de la base de datos">db {data.db}</span>
        </>
      ) : null}
    </div>
  );
}
