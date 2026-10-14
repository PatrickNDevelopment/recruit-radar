/**
 * Synthetic sample data (spec 05 "Honesty copy"): two OVERLAPPING datasets of invented companies.
 *
 * Nothing here is real hiring data. Company names are fictional; URLs use the reserved
 * `example.com` domain. Dates are generated relative to the `now` argument so the sample always
 * looks current, while staying deterministic for a given `now` (the tests pin it).
 *
 * The overlap is deliberate and exercises every identity path:
 *  - exact company match across datasets with different spellings ("Brightwater Labs" /
 *    "Brightwater Labs, Inc."), with some roles corroborated by both datasets;
 *  - a `spacing_variant` merge candidate ("North Harbor Analytics" / "NorthHarbor Analytics");
 *  - a `near_typo` candidate ("Cedar Point Robotics" / "Cedar Point Robotic");
 *  - a `token_overlap` candidate ("Quillstone Health Partners" / "Quillstone Health Partners Network").
 */
import { exportPostingsCsv, type CsvPostingRow, type Profile, type WorkMode } from '../engine';
import { dateDaysBefore, timestampDaysBefore } from './clock';
import { SAMPLE_LABEL_PREFIX } from './derive';

export interface SampleDataset {
  /** Becomes `source_ref` (source_kind `csv`). Always starts with {@link SAMPLE_LABEL_PREFIX}. */
  label: string;
  filename: string;
  description: string;
  csv: string;
  postings: number;
}

/** Keywords applied by "Load sample data" only when the user has configured none. */
export const SAMPLE_PROFILE: Profile = {
  include_keywords: ['engineer', 'data', 'machine learning'],
  exclude_keywords: ['intern'],
};

export const SAMPLE_LABEL_A = `${SAMPLE_LABEL_PREFIX}A Board export`;
export const SAMPLE_LABEL_B = `${SAMPLE_LABEL_PREFIX}B Job feed`;

interface Spec {
  company: string;
  title: string;
  location: string | null;
  mode: WorkMode;
  department: string | null;
  /** Days before `now` the posting date was; null = undated. */
  postedDaysAgo: number | null;
  id?: string;
  /** Days before `now` this row was observed; omitted = import time. */
  observedDaysAgo?: number;
}

function url(slug: string, id: string): string {
  return `https://careers.example.com/${slug}/jobs/${id}`;
}

const A_ROWS: readonly Spec[] = [
  // Brightwater Labs: three roles, two of which dataset B repeats.
  {
    company: 'Brightwater Labs',
    title: 'Senior Software Engineer',
    location: 'Austin, TX',
    mode: 'hybrid',
    department: 'Platform',
    postedDaysAgo: 12,
    id: 'bw-101',
    observedDaysAgo: 24,
  },
  {
    company: 'Brightwater Labs',
    title: 'Data Engineer',
    location: 'Remote - US',
    mode: 'remote',
    department: 'Data',
    postedDaysAgo: 52,
    id: 'bw-102',
    observedDaysAgo: 24,
  },
  {
    company: 'Brightwater Labs',
    title: 'Product Designer',
    location: 'Austin, TX',
    mode: 'hybrid',
    department: 'Design',
    postedDaysAgo: 5,
    id: 'bw-103',
  },
  // Cedar Point Robotics.
  {
    company: 'Cedar Point Robotics',
    title: 'Robotics Engineer',
    location: 'Denver, CO',
    mode: 'onsite',
    department: 'Controls',
    postedDaysAgo: 63,
    id: 'cp-11',
    observedDaysAgo: 24,
  },
  {
    company: 'Cedar Point Robotics',
    title: 'Firmware Engineer (Embedded)',
    location: 'Denver, CO',
    mode: 'onsite',
    department: 'Firmware',
    postedDaysAgo: 48,
    id: 'cp-12',
    observedDaysAgo: 24,
  },
  {
    company: 'Cedar Point Robotics',
    title: 'Engineering Intern',
    location: 'Denver, CO',
    mode: 'onsite',
    department: 'Controls',
    postedDaysAgo: 9,
    id: 'cp-13',
  },
  // North Harbor Analytics.
  {
    company: 'North Harbor Analytics',
    title: 'Machine Learning Engineer',
    location: 'Boston, MA',
    mode: 'hybrid',
    department: 'Research',
    postedDaysAgo: 20,
    id: 'nh-7',
  },
  {
    company: 'North Harbor Analytics',
    title: 'Data Analyst',
    location: 'Remote - US',
    mode: 'remote',
    department: 'Analytics',
    postedDaysAgo: 3,
    id: 'nh-8',
  },
  // Lumen Freight Co. (dataset A only).
  {
    company: 'Lumen Freight Co.',
    title: 'Operations Manager',
    location: 'Memphis, TN',
    mode: 'onsite',
    department: 'Operations',
    postedDaysAgo: 30,
    observedDaysAgo: 24,
  },
  {
    company: 'Lumen Freight Co.',
    title: 'Backend Engineer',
    location: 'Remote - US',
    mode: 'remote',
    department: 'Engineering',
    postedDaysAgo: 8,
  },
  // Tidewater Systems (dataset A only): long-listed roles.
  {
    company: 'Tidewater Systems',
    title: 'Staff Backend Engineer [Remote]',
    location: 'Remote - Europe',
    mode: 'remote',
    department: 'Engineering',
    postedDaysAgo: 91,
    id: 'tw-1',
    observedDaysAgo: 24,
  },
  {
    company: 'Tidewater Systems',
    title: 'Site Reliability Engineer',
    location: 'Lisbon, Portugal',
    mode: 'hybrid',
    department: 'Infrastructure',
    postedDaysAgo: 74,
    id: 'tw-2',
    observedDaysAgo: 24,
  },
  // Quillstone Health Partners.
  {
    company: 'Quillstone Health Partners',
    title: 'Data Scientist',
    location: 'Chicago, IL',
    mode: 'hybrid',
    department: 'Data',
    postedDaysAgo: 14,
  },
  {
    company: 'Quillstone Health Partners',
    title: 'Clinical Operations Lead',
    location: 'Chicago, IL',
    mode: 'onsite',
    department: 'Operations',
    postedDaysAgo: 40,
  },
];

const B_ROWS: readonly Spec[] = [
  // Brightwater Labs again, with another legal-name spelling; first two repeat dataset A roles.
  {
    company: 'Brightwater Labs, Inc.',
    title: 'Senior Software Engineer',
    location: 'Austin, TX',
    mode: 'hybrid',
    department: 'Platform',
    postedDaysAgo: 12,
  },
  {
    company: 'Brightwater Labs, Inc.',
    title: 'Data Engineer',
    location: 'Remote - US',
    mode: 'remote',
    department: 'Data',
    postedDaysAgo: 52,
  },
  {
    company: 'Brightwater Labs, Inc.',
    title: 'Machine Learning Engineer',
    location: 'Remote - US',
    mode: 'remote',
    department: 'Data',
    postedDaysAgo: 2,
  },
  // Typo variant of Cedar Point Robotics.
  {
    company: 'Cedar Point Robotic',
    title: 'Robotics Engineer',
    location: 'Denver, CO',
    mode: 'onsite',
    department: 'Controls',
    postedDaysAgo: 63,
  },
  {
    company: 'Cedar Point Robotic',
    title: 'Mechanical Engineer',
    location: 'Denver, CO',
    mode: 'onsite',
    department: 'Hardware',
    postedDaysAgo: 11,
  },
  // Spacing variant of North Harbor Analytics.
  {
    company: 'NorthHarbor Analytics',
    title: 'Data Analyst',
    location: 'Remote - US',
    mode: 'remote',
    department: 'Analytics',
    postedDaysAgo: 3,
  },
  {
    company: 'NorthHarbor Analytics',
    title: 'Analytics Engineer',
    location: 'Boston, MA',
    mode: 'hybrid',
    department: 'Analytics',
    postedDaysAgo: 6,
  },
  // Token-overlap variant of Quillstone Health Partners.
  {
    company: 'Quillstone Health Partners Network',
    title: 'Data Scientist',
    location: 'Chicago, IL',
    mode: 'hybrid',
    department: 'Data',
    postedDaysAgo: 14,
  },
  {
    company: 'Quillstone Health Partners Network',
    title: 'Security Engineer',
    location: null,
    mode: 'unknown',
    department: 'IT',
    postedDaysAgo: null,
  },
  // B only.
  {
    company: 'Ashgrove Games',
    title: 'Gameplay Engineer',
    location: 'Montreal, Canada',
    mode: 'hybrid',
    department: 'Studio',
    postedDaysAgo: 19,
  },
  {
    company: 'Ashgrove Games',
    title: 'Community Manager',
    location: 'Remote - Canada',
    mode: 'remote',
    department: 'Community',
    postedDaysAgo: 27,
  },
  {
    company: 'Ashgrove Games',
    title: 'Data Engineer',
    location: 'Montreal, Canada',
    mode: 'onsite',
    department: 'Studio',
    postedDaysAgo: null,
  },
];

function rowsOf(specs: readonly Spec[], now: string, slugPrefix: string): CsvPostingRow[] {
  return specs.map((spec, index) => {
    const slug = `${slugPrefix}-${spec.company.toLowerCase().replace(/[^a-z0-9]+/gu, '-')}`;
    const postingId = spec.id ?? null;
    return {
      company_name: spec.company,
      title: spec.title,
      location: spec.location,
      work_mode: spec.mode,
      department: spec.department,
      url: url(slug, postingId ?? `${index + 1}`),
      posted_at: spec.postedDaysAgo === null ? null : dateDaysBefore(now, spec.postedDaysAgo),
      source_posting_id: postingId,
      observed_at:
        spec.observedDaysAgo === undefined ? null : timestampDaysBefore(now, spec.observedDaysAgo),
    };
  });
}

/**
 * The two sample datasets as CSV text in the import format (spec 05). `now` is the UTC timestamp
 * the dates are relative to.
 */
export function buildSampleDatasets(now: string): SampleDataset[] {
  const a = rowsOf(A_ROWS, now, 'a');
  const b = rowsOf(B_ROWS, now, 'b');
  return [
    {
      label: SAMPLE_LABEL_A,
      filename: 'recruit-radar-sample-a-board-export.csv',
      description:
        'Synthetic board export: 14 postings across 6 invented companies. Some rows carry an ' +
        'earlier observation date so the role history has events.',
      csv: exportPostingsCsv(a),
      postings: a.length,
    },
    {
      label: SAMPLE_LABEL_B,
      filename: 'recruit-radar-sample-b-job-feed.csv',
      description:
        'Synthetic job feed: 12 postings that overlap dataset A (same roles, other spellings of ' +
        'company names), so duplicates collapse and merge candidates appear.',
      csv: exportPostingsCsv(b),
      postings: b.length,
    },
  ];
}
