/**
 * Honesty copy (spec 05) and shared wording. Kept in one module so tests can assert the exact
 * phrases and so no screen paraphrases them.
 *
 * Product rule (spec 00): a posting is a posting. Nothing here may say or imply that a company
 * needs, is struggling, or will pay an outside recruiter.
 */
import type { ComponentKey, EventType, MergeReason, ReasonCode, WorkMode } from '../engine';

export const COPY = {
  localBanner:
    'Local-data mode: your data stays in this browser. Live ATS refresh needs the local backend.',
  sampleBanner: 'Synthetic sample data — invented companies, not real hiring data.',
  scoreCaption:
    'Priority score = observed hiring activity in the roles you configured, from the sources you ' +
    'loaded. It is not evidence that a company needs or will use an outside recruiter.',
  missingHeading: 'Missing information',
  missingExplainer:
    'These parts of the score could not be measured from the data you loaded. They are left out ' +
    'of the score and of its coverage; they are never counted as zero.',
  urgencyLabel: 'Possible urgency signal (aged postings) — not evidence of hiring difficulty.',
  appTagline: 'Evidence-backed view of hiring activity in public job postings',
} as const;

export const COMPONENT_TITLES: Readonly<Record<ComponentKey, string>> = {
  role_relevance: 'Role relevance',
  volume: 'Volume of matching roles',
  change: 'Change in the last 30 days',
  urgency: COPY.urgencyLabel,
  source_confidence: 'Source confidence',
  freshness: 'Freshness',
};

/** Short title for places where the full urgency label would not fit; never used alone. */
export const COMPONENT_SHORT: Readonly<Record<ComponentKey, string>> = {
  role_relevance: 'Role relevance',
  volume: 'Volume',
  change: 'Change (30 days)',
  urgency: 'Urgency signal',
  source_confidence: 'Source confidence',
  freshness: 'Freshness',
};

export const COMPONENT_RULES: Readonly<Record<ComponentKey, string>> = {
  role_relevance: 'Relevant active roles ÷ active roles, scaled to 0–100.',
  volume:
    'Looked up from a fixed table by the number of roles in scope: 1 role = 30, 2 = 48, 3 = 60, ' +
    '4 = 69, 5 = 76, 6 = 82, 7 = 87, 8 = 91, 9 = 95, 10 or more = 100.',
  change: '50 + 10 × (added − removed) in the last 30 days, limited to 0–100.',
  urgency: 'Share of dated roles in scope that have been listed for 45 or more days.',
  source_confidence:
    'Average over roles in scope of the best source weight (ATS 100, CSV 60, manual 40), plus 10 ' +
    'when two or more different sources list the same role, capped at 100.',
  freshness:
    '100 if the newest active role was seen within 7 days, 0 after 60 days, falling in a straight ' +
    'line between.',
};

export const REASONS: Readonly<Record<ReasonCode, { text: string; help: string }>> = {
  no_active_roles: {
    text: 'No active roles in the loaded data.',
    help: 'Every role of this company is marked removed, so nothing can be measured right now.',
  },
  no_keywords: {
    text: 'No role keywords are configured.',
    help: 'Add include keywords in Settings so roles can be matched against them.',
  },
  insufficient_history: {
    text: 'Not enough history to measure change.',
    help:
      'Change needs at least two full-list snapshots (live ATS refreshes) taken 14 or more days ' +
      'apart. CSV imports and manual entries are not full lists, so they cannot show removals.',
  },
  no_scope_roles: {
    text: 'No active role matches your keywords.',
    help: 'Roles are in scope when they match an include keyword and no exclude keyword.',
  },
  no_dated_roles: {
    text: 'No role has a posting date or enough history to estimate its age.',
    help:
      'Add posted_at dates to your CSV, or keep refreshing a live source for at least 45 days ' +
      'so first-seen dates become meaningful.',
  },
};

export const WORK_MODE_LABELS: Readonly<Record<WorkMode, string>> = {
  remote: 'Remote',
  hybrid: 'Hybrid',
  onsite: 'Onsite',
  unknown: 'Unknown',
};

export const EVENT_LABELS: Readonly<Record<EventType, string>> = {
  baseline: 'First observed (baseline)',
  added: 'Added',
  changed: 'Changed',
  removed: 'No longer listed',
  reappeared: 'Listed again',
};

export const MERGE_REASON_TEXT: Readonly<Record<MergeReason, string>> = {
  spacing_variant: 'The names are identical apart from spacing.',
  token_overlap: 'The names share most of their words.',
  near_typo: 'The names differ by a single character.',
};

export const FIELD_LABELS: Readonly<Record<string, string>> = {
  company_name: 'Company',
  title: 'Title',
  location: 'Location',
  work_mode: 'Work mode',
  department: 'Department',
  url: 'URL',
  posted_at: 'Posted date',
  source_posting_id: 'Posting ID',
  observed_at: 'Observed at',
  form: 'The request',
};

export const PROVIDER_LABELS = {
  greenhouse: 'Greenhouse',
  lever: 'Lever',
  ashby: 'Ashby',
} as const;

export const ERROR_KIND_TEXT: Readonly<Record<string, string>> = {
  not_found: 'Board not found (404). Check the board token.',
  unauthorized: 'The board is not public (401/403).',
  rate_limited: 'The provider rate-limited the request (429).',
  server_error: 'The provider had a server error (5xx).',
  network: 'A network error stopped the request.',
  timeout: 'The provider did not answer in time.',
  malformed: 'The provider answered with data that could not be read.',
  too_large: 'The provider’s answer was larger than the supported limit.',
};
