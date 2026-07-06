import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getPanel } from '../api/client.ts';
import type { PanelData, PanelName } from '../api/types.ts';
import {
  asArray,
  asNumber,
  asString,
  isEmptyData,
  isRecord,
  pick,
} from '../api/read.ts';
import { EmptyState, ErrorState, LoadingState } from '../components/states.tsx';

const PANELS: { name: PanelName; label: string }[] = [
  { name: 'operative', label: 'Mapa operativo' },
  { name: 'agents', label: 'Agentes' },
  { name: 'commitments', label: 'Compromisos' },
  { name: 'economy', label: 'Economía' },
];

/**
 * Panels (§11.3). Four read-only shells over /api/panels/{name}. Each renders a
 * purpose-built view when the expected shape is present and falls back to a raw
 * key/value view otherwise, so the surface is useful the moment data arrives.
 */
export function Panels() {
  const [active, setActive] = useState<PanelName>('operative');

  return (
    <div className="flex h-full flex-col">
      <nav className="mb-4 flex flex-wrap gap-1 border-b border-ink-700">
        {PANELS.map((p) => (
          <button
            key={p.name}
            type="button"
            onClick={() => setActive(p.name)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
              active === p.name
                ? 'border-gold text-gray-light'
                : 'border-transparent text-gray hover:text-gray-light'
            }`}
          >
            {p.label}
          </button>
        ))}
      </nav>

      <div className="flex-1 overflow-y-auto">
        <PanelBody name={active} />
      </div>
    </div>
  );
}

function PanelBody({ name }: { name: PanelName }) {
  const query = useQuery({
    queryKey: ['panel', name],
    queryFn: () => getPanel(name),
  });

  if (query.isLoading) return <LoadingState label="Cargando panel…" />;
  if (query.isError) return <ErrorState error={query.error} />;

  const data = query.data ?? {};
  if (isEmptyData(data)) {
    return (
      <EmptyState
        title="Panel sin datos"
        hint="El endpoint respondió vacío. La vista se poblará cuando el backend entregue datos."
      />
    );
  }

  switch (name) {
    case 'operative':
      return <OperativePanel data={data} />;
    case 'agents':
      return <AgentsPanel data={data} />;
    case 'commitments':
      return <CommitmentsPanel data={data} />;
    case 'economy':
      return <EconomyPanel data={data} />;
    default:
      return <RawPanel data={data} />;
  }
}

// --- Operative map (as-is / to-be) ---------------------------------------

function OperativePanel({ data }: { data: PanelData }) {
  const asIs = asArray(pick(data, 'as_is', 'asIs'));
  const toBe = asArray(pick(data, 'to_be', 'toBe'));

  if (asIs.length === 0 && toBe.length === 0) return <RawPanel data={data} />;

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <ProcessColumn title="As-is (cómo opera hoy)" accent="gray" steps={asIs} />
      <ProcessColumn title="To-be (cómo debería operar)" accent="cyan" steps={toBe} />
    </div>
  );
}

function ProcessColumn({
  title,
  accent,
  steps,
}: {
  title: string;
  accent: 'gray' | 'cyan';
  steps: unknown[];
}) {
  const dot = accent === 'cyan' ? 'bg-cyan' : 'bg-gray';
  return (
    <section className="rounded-lg border border-ink-600 bg-ink-800/50 p-3">
      <h3 className="mb-3 font-display text-sm font-semibold text-gray-light">
        {title}
      </h3>
      {steps.length === 0 ? (
        <p className="text-xs text-gray">Sin pasos definidos.</p>
      ) : (
        <ol className="space-y-2">
          {steps.map((step, i) => {
            const label = isRecord(step)
              ? asString(pick(step, 'label', 'name', 'step', 'title'), `Paso ${i + 1}`)
              : asString(step, `Paso ${i + 1}`);
            const note = isRecord(step) ? asString(pick(step, 'note', 'detail')) : '';
            return (
              <li key={i} className="flex gap-2 text-sm text-gray-light">
                <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} />
                <span>
                  {label}
                  {note ? <span className="block text-xs text-gray">{note}</span> : null}
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

// --- Agents panel ---------------------------------------------------------

function stageStyle(stage: string): string {
  switch (stage) {
    case 'production':
      return 'bg-green/15 text-green border-green/40';
    case 'canary':
      return 'bg-gold/15 text-gold border-gold/40';
    case 'shadow':
      return 'bg-cyan/15 text-cyan border-cyan/40';
    case 'retired':
      return 'bg-ink-700 text-gray border-ink-600';
    default:
      return 'bg-blue/15 text-blue border-blue/40';
  }
}

function AgentsPanel({ data }: { data: PanelData }) {
  const agents = asArray(pick(data, 'agents', 'items'));
  if (agents.length === 0) return <RawPanel data={data} />;

  return (
    <div className="space-y-3">
      {agents.map((a, i) => {
        if (!isRecord(a)) return null;
        const name = asString(pick(a, 'name'), 'agente');
        const version = asString(pick(a, 'version', 'ver'));
        const stage = asString(pick(a, 'stage'), 'design');
        const cost = asNumber(pick(a, 'cost', 'cost_usd', 'cost_per_case'));
        const metrics = pick(a, 'metrics');

        return (
          <article
            key={i}
            className="rounded-lg border border-ink-600 bg-ink-800/50 p-3"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <h3 className="font-display text-sm font-semibold text-gray-light">
                  {name}
                </h3>
                {version ? (
                  <span className="font-mono text-2xs text-gray">v{version}</span>
                ) : null}
                <span
                  className={`rounded border px-1.5 py-0.5 text-2xs font-medium capitalize ${stageStyle(
                    stage,
                  )}`}
                >
                  {stage}
                </span>
              </div>
              {cost !== null ? (
                <span className="text-2xs text-gray">
                  costo/caso{' '}
                  <span className="font-mono text-gray-light">${cost.toFixed(4)}</span>
                </span>
              ) : null}
            </div>

            <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Metric
                label="Acuerdo"
                value={fmtPct(pick(metrics, 'agreement', 'acuerdo'))}
              />
              <Metric
                label="Cobertura"
                value={fmtPct(pick(metrics, 'coverage', 'cobertura'))}
              />
              <Metric
                label="Peligrosa"
                value={fmtPct(pick(metrics, 'dangerous_rate', 'dangerous', 'peligrosa'))}
                danger
              />
              <Metric
                label="Costo/caso"
                value={fmtUsd(pick(metrics, 'cost_per_case', 'cost'))}
              />
            </div>

            <div className="mt-3 flex flex-wrap gap-2">
              <StageButton label="Promover" tone="promote" />
              <StageButton label="Degradar" tone="degrade" />
              <StageButton label="Retirar" tone="retire" />
              <StageButton label="Runbook" tone="neutral" />
            </div>
          </article>
        );
      })}
      <p className="text-2xs text-gray">
        Los botones de ciclo de vida quedan cableados a la interfaz; la acción se
        habilitará cuando el orquestador exponga el endpoint (§10).
      </p>
    </div>
  );
}

function Metric({
  label,
  value,
  danger,
}: {
  label: string;
  value: string;
  danger?: boolean;
}) {
  return (
    <div className="rounded border border-ink-700 bg-ink-900/60 px-2 py-1.5">
      <p className="text-2xs uppercase tracking-wide text-gray">{label}</p>
      <p
        className={`mt-0.5 font-mono text-sm ${
          danger && value !== '—' && value !== '0%'
            ? 'text-red-300'
            : 'text-gray-light'
        }`}
      >
        {value}
      </p>
    </div>
  );
}

function StageButton({
  label,
  tone,
}: {
  label: string;
  tone: 'promote' | 'degrade' | 'retire' | 'neutral';
}) {
  const cls =
    tone === 'promote'
      ? 'border-green/50 text-green hover:bg-green/10'
      : tone === 'degrade'
        ? 'border-gold/50 text-gold hover:bg-gold/10'
        : tone === 'retire'
          ? 'border-red-500/50 text-red-300 hover:bg-red-500/10'
          : 'border-ink-600 text-gray hover:bg-ink-700';
  return (
    <button
      type="button"
      disabled
      title="Disponible cuando el backend exponga la acción de ciclo de vida"
      className={`cursor-not-allowed rounded border px-2.5 py-1 text-2xs font-medium opacity-60 ${cls}`}
    >
      {label}
    </button>
  );
}

// --- Commitments panel ----------------------------------------------------

function CommitmentsPanel({ data }: { data: PanelData }) {
  const current = asArray(pick(data, 'current', 'vigentes'));
  const atRisk = asArray(pick(data, 'at_risk', 'atRisk', 'en_riesgo'));
  const breached = asArray(pick(data, 'breached', 'incumplidos'));

  if (current.length === 0 && atRisk.length === 0 && breached.length === 0) {
    return <RawPanel data={data} />;
  }

  return (
    <div className="grid gap-4 md:grid-cols-3">
      <CommitmentColumn title="Vigentes" tone="green" items={current} />
      <CommitmentColumn title="En riesgo" tone="gold" items={atRisk} />
      <CommitmentColumn title="Incumplidos" tone="red" items={breached} />
    </div>
  );
}

function CommitmentColumn({
  title,
  tone,
  items,
}: {
  title: string;
  tone: 'green' | 'gold' | 'red';
  items: unknown[];
}) {
  const head =
    tone === 'green'
      ? 'text-green'
      : tone === 'gold'
        ? 'text-gold'
        : 'text-red-300';
  return (
    <section className="rounded-lg border border-ink-600 bg-ink-800/50 p-3">
      <h3 className={`mb-3 font-display text-sm font-semibold ${head}`}>
        {title}{' '}
        <span className="text-2xs font-normal text-gray">({items.length})</span>
      </h3>
      {items.length === 0 ? (
        <p className="text-xs text-gray">Ninguno.</p>
      ) : (
        <ul className="space-y-2">
          {items.map((it, i) => {
            const text = isRecord(it)
              ? asString(pick(it, 'text', 'title', 'what', 'description'), 'Compromiso')
              : asString(it, 'Compromiso');
            const who = isRecord(it) ? asString(pick(it, 'who', 'party', 'with')) : '';
            const due = isRecord(it) ? asString(pick(it, 'due', 'deadline', 'valid_to')) : '';
            const direction = isRecord(it)
              ? asString(pick(it, 'direction', 'dir'))
              : '';
            return (
              <li
                key={i}
                className="rounded border border-ink-700 bg-ink-900/60 p-2 text-sm text-gray-light"
              >
                <p>{text}</p>
                <div className="mt-1 flex flex-wrap gap-x-3 text-2xs text-gray">
                  {who ? <span>{who}</span> : null}
                  {due ? <span>vence: {due}</span> : null}
                  {direction ? (
                    <span className="uppercase tracking-wide">
                      {direction === 'inbound' || direction === 'to_us'
                        ? 'hacia nosotros'
                        : direction === 'outbound' || direction === 'by_us'
                          ? 'de nosotros'
                          : direction}
                    </span>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

// --- Economy panel --------------------------------------------------------

function EconomyPanel({ data }: { data: PanelData }) {
  const cost = asNumber(pick(data, 'cost_usd', 'cost', 'total_cost'));
  const savings = asNumber(pick(data, 'savings_usd', 'savings', 'estimated_savings'));

  if (cost === null && savings === null) return <RawPanel data={data} />;

  const net = (savings ?? 0) - (cost ?? 0);
  const ratio = cost && cost > 0 ? (savings ?? 0) / cost : null;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <BigStat label="Costo (LLM + operación)" value={fmtUsd(cost)} tone="gray" />
        <BigStat label="Ahorro estimado" value={fmtUsd(savings)} tone="green" />
        <BigStat
          label="Neto"
          value={fmtUsd(net)}
          tone={net >= 0 ? 'green' : 'red'}
        />
      </div>

      {cost !== null && savings !== null ? (
        <div className="rounded-lg border border-ink-600 bg-ink-800/50 p-3">
          <div className="mb-1 flex justify-between text-2xs text-gray">
            <span>Costo vs ahorro</span>
            {ratio !== null ? <span>{ratio.toFixed(2)}× retorno</span> : null}
          </div>
          <div className="flex h-3 overflow-hidden rounded bg-ink-900">
            <div
              className="bg-gray/70"
              style={{ width: `${barWidth(cost, cost + savings)}%` }}
              title={`Costo ${fmtUsd(cost)}`}
            />
            <div
              className="bg-green/70"
              style={{ width: `${barWidth(savings, cost + savings)}%` }}
              title={`Ahorro ${fmtUsd(savings)}`}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}

function BigStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: 'gray' | 'green' | 'red';
}) {
  const v =
    tone === 'green'
      ? 'text-green'
      : tone === 'red'
        ? 'text-red-300'
        : 'text-gray-light';
  return (
    <div className="rounded-lg border border-ink-600 bg-ink-800/50 p-3">
      <p className="text-2xs uppercase tracking-wide text-gray">{label}</p>
      <p className={`mt-1 font-display text-xl font-semibold ${v}`}>{value}</p>
    </div>
  );
}

// --- Raw fallback ---------------------------------------------------------

function RawPanel({ data }: { data: PanelData }) {
  return (
    <div className="rounded-lg border border-ink-600 bg-ink-800/50 p-3">
      <p className="mb-2 text-2xs uppercase tracking-wide text-gray">
        Datos crudos del panel
      </p>
      <pre className="overflow-x-auto whitespace-pre-wrap break-words text-xs text-gray-light">
        {JSON.stringify(data, null, 2)}
      </pre>
    </div>
  );
}

// --- formatters -----------------------------------------------------------

function fmtPct(v: unknown): string {
  const n = asNumber(v);
  if (n === null) return '—';
  // Accept both 0..1 and 0..100 conventions.
  const pct = n <= 1 ? n * 100 : n;
  return `${pct.toFixed(0)}%`;
}

function fmtUsd(v: unknown): string {
  const n = asNumber(v);
  if (n === null) return '—';
  const abs = Math.abs(n);
  const digits = abs < 1 ? 4 : 2;
  return `${n < 0 ? '-' : ''}$${abs.toFixed(digits)}`;
}

function barWidth(part: number, total: number): number {
  if (total <= 0) return 0;
  return Math.max(2, Math.min(100, (part / total) * 100));
}
