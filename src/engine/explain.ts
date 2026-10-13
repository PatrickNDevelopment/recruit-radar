/**
 * Human-readable wording for score components. The shortlist export uses it, and UI code can
 * reuse it so the exported text and the on-screen breakdown never drift apart.
 *
 * Nothing here claims that a company "needs" or "will pay" anyone: a score only describes
 * observed hiring activity in the roles the user configured, from the sources the user loaded.
 */
import type { ComponentKey, ReasonCode, ScoreComponent } from './types';

/** Short component names, usable inside a sentence or a CSV cell. */
export const COMPONENT_NAMES: Readonly<Record<ComponentKey, string>> = {
  role_relevance: 'Role relevance',
  volume: 'Volume of matching roles',
  change: 'Change in the last 30 days',
  urgency: 'Possible urgency signal (aged postings)',
  source_confidence: 'Source confidence',
  freshness: 'Freshness',
};

/**
 * Display labels. The urgency label is the exact honesty copy required by spec 05: it must
 * accompany the component wherever it is shown on its own.
 */
export const COMPONENT_LABELS: Readonly<Record<ComponentKey, string>> = {
  ...COMPONENT_NAMES,
  urgency: 'Possible urgency signal (aged postings) — not evidence of hiring difficulty.',
};

export const REASON_TEXT: Readonly<Record<ReasonCode, string>> = {
  no_active_roles: 'no active roles in the loaded data',
  no_keywords: 'no role keywords are configured',
  insufficient_history:
    'needs full-list snapshots at least 14 days apart (change cannot be measured yet)',
  no_scope_roles: 'no active roles match the configured keywords',
  no_dated_roles: 'none of the roles has a posting date or enough history to estimate its age',
};

function plural(count: number, singular: string): string {
  return `${count} ${count === 1 ? singular : `${singular}s`}`;
}

/** One-line, human-readable calculation for a component (or its missing-information reason). */
export function describeComponent(component: ScoreComponent): string {
  if (component.value === null) {
    const reason = component.reason_code === null ? 'unknown' : REASON_TEXT[component.reason_code];
    return `Missing information: ${reason}`;
  }
  switch (component.key) {
    case 'role_relevance': {
      const { relevant, active } = component.inputs;
      return `${relevant ?? 0} of ${plural(active, 'active role')} match the role keywords`;
    }
    case 'volume':
      return `${plural(component.inputs.scope_roles, 'active role')} in scope`;
    case 'change': {
      const { added, removed, net, span_days } = component.inputs;
      return (
        `${added ?? 0} added or reappeared and ${removed ?? 0} removed in the last 30 days ` +
        `(net ${net ?? 0}); history spans ${plural(span_days ?? 0, 'day')}`
      );
    }
    case 'urgency': {
      const { aged, known, threshold_days } = component.inputs;
      return (
        `${aged ?? 0} of ${plural(known ?? 0, 'dated role')} are ${threshold_days} or more ` +
        `days old — a possible signal only, not evidence of hiring difficulty`
      );
    }
    case 'source_confidence': {
      const { scope_roles, corroborated } = component.inputs;
      return (
        `${plural(scope_roles, 'role')} in scope, ${corroborated ?? 0} confirmed by two or ` +
        `more sources`
      );
    }
    case 'freshness': {
      const days = component.inputs.days_since_last_seen ?? 0;
      return `last seen ${plural(days, 'day')} ago`;
    }
  }
}

/** Format a 0..1000 score as shown in the UI: score / 10 with one decimal ("64.0"). */
export function formatScore(score: number | null): string {
  if (score === null) return '';
  return `${Math.floor(score / 10)}.${score % 10}`;
}
