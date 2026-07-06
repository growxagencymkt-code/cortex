// API contract types (§11 surfaces). These mirror the FastAPI backend exactly.
// Endpoints may currently return 501/empty; callers must handle that gracefully.

export interface Health {
  status: string;
  version: string;
  pipeline_ver: string;
  db: string;
}

// --- Conversation (11.1) --------------------------------------------------

/** A grounded fact from the graph, always backed by an evidence event. */
export interface RetrievedFact {
  src: string;
  rel: string;
  dst: string;
  evidence_event: number | string;
}

/** A retrieved text chunk with provenance (event/source/timestamp/score). */
export interface RetrievedChunk {
  text: string;
  event_id: number | string;
  source: string;
  ts: string;
  score: number;
}

export interface RetrieveResponse {
  answerable: boolean;
  facts: RetrievedFact[];
  chunks: RetrievedChunk[];
  note: string;
}

/**
 * A grounded, generated answer from /api/chat. `engine` says how it was produced:
 * 'llm' (a model wrote it), 'extractive' (assembled from evidence at $0 cost), or
 * 'none' (no evidence, so no answer). When `grounded` is false, CORTEX abstains.
 */
export interface GroundedAnswer {
  answer: string;
  grounded: boolean;
  used_events: number[];
  engine: 'llm' | 'extractive' | 'none';
  note: string;
}

// --- Decision inbox (11.2) ------------------------------------------------

export type DecisionKind =
  | 'action_proposal'
  | 'disambiguation'
  | 'new_agent_proposal'
  | 'commitment_alert'
  // legacy short forms tolerated at the edge
  | 'action'
  | 'new_agent'
  | string;

export interface DecisionCard {
  id: string;
  kind: DecisionKind;
  title: string;
  /** Summarized recommendation. May be empty for anti-inertia cards (~1 in 15). */
  recommendation: string;
  /** Collapsed reasoning shown behind the "why". */
  why: string;
  evidence_events: Array<number | string>;
  /** Optional priority hint from the backend (e.g. 'high' | 'medium' | 'low'). */
  urgency?: string;
  /** True when the card is deliberately shown without a recommendation. */
  anti_inertia?: boolean;
}

export interface InboxResponse {
  cards: DecisionCard[];
  count?: number;
}

export type DecisionChoice = 'approve' | 'edit' | 'reject';

// --- Panels (11.3) --------------------------------------------------------

export type PanelName = 'map' | 'agents' | 'commitments' | 'economy';

/** Panels return free-form objects for now; each surface narrows as needed. */
export type PanelData = Record<string, unknown>;
