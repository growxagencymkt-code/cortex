import type {
  Health,
  InboxResponse,
  PanelData,
  PanelName,
  RetrieveResponse,
} from './types.ts';

/**
 * Raised for any non-2xx response or transport failure. Carries the HTTP
 * status so the UI can distinguish "not implemented yet" (501) from real errors.
 */
export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

/** True when the backend answered but the feature is not wired up yet. */
export function isNotImplemented(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 501 || err.status === 404);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        ...(init?.headers ?? {}),
      },
    });
  } catch {
    throw new ApiError('No se pudo conectar con el backend de CORTEX.', 0);
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string; note?: string };
      detail = body.detail ?? body.note ?? detail;
    } catch {
      /* body was not JSON; keep statusText */
    }
    throw new ApiError(detail || `Error ${res.status}`, res.status);
  }

  // 204 / empty body
  if (res.status === 204) return {} as T;
  const text = await res.text();
  if (!text) return {} as T;
  return JSON.parse(text) as T;
}

export function getHealth(): Promise<Health> {
  return request<Health>('/health');
}

export function retrieve(query: string): Promise<RetrieveResponse> {
  return request<RetrieveResponse>('/api/retrieve', {
    method: 'POST',
    body: JSON.stringify({ query }),
  });
}

export function getInbox(): Promise<InboxResponse> {
  return request<InboxResponse>('/api/inbox');
}

export function getPanel(name: PanelName): Promise<PanelData> {
  return request<PanelData>(`/api/panels/${name}`);
}

/**
 * Records a decision against a card. The backend writes it to decisions_log and
 * as an event source='human_ui' (§11.2). Endpoint is optimistic: if it is not
 * implemented yet we surface the ApiError to the caller.
 */
export function decide(
  cardId: string,
  choice: 'approve' | 'edit' | 'reject',
  note?: string,
): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/inbox/${cardId}/decide`, {
    method: 'POST',
    body: JSON.stringify({ choice, note: note ?? '' }),
  });
}
