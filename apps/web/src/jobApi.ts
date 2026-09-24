export const MODE_OPTIONS = [
  { value: "faithful", label: "Faithful (fidelity profile)" },
  { value: "geometric", label: "Geometric (fast baseline)" },
  { value: "minimal", label: "Minimal (compactness profile)" },
  { value: "stroke", label: "Stroke / line-art" },
] as const;

export type Mode = (typeof MODE_OPTIONS)[number]["value"];
export type JobState =
  | "accepted"
  | "running"
  | "success"
  | "degraded"
  | "needs_review"
  | "unsupported"
  | "failed"
  | "canceled";

export type JobStatus = {
  job_id: string;
  state: JobState;
  mode: Mode;
  cancel_requested: boolean;
  artifacts: Record<string, string>;
  palette_count: number | null;
  region_count: number | null;
  seam_gap_rate: number | null;
  error: { code: string; stage: string; message: string; retryable: boolean } | null;
};

const states: JobState[] = [
  "accepted", "running", "success", "degraded", "needs_review", "unsupported", "failed", "canceled",
];
const artifactNames = [
  "output.svg", "preview.png", "scene.json", "run-manifest.json",
  "validation-report.json", "events.jsonl", "cut-outline.svg",
];

export function isMode(value: string): value is Mode {
  return MODE_OPTIONS.some((option) => option.value === value);
}

export function isTerminal(state: JobState): boolean {
  return state !== "accepted" && state !== "running";
}

export function isPublished(state: JobState): boolean {
  return state === "success" || state === "degraded" || state === "needs_review";
}

function isCount(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isInteger(value) && value >= 0);
}

export function isJobStatus(value: unknown): value is JobStatus {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Record<string, unknown>;
  if (typeof item.job_id !== "string" || !/^[a-f0-9]{64}-[a-f0-9]{12}$/.test(item.job_id)) return false;
  if (!states.includes(item.state as JobState) || typeof item.mode !== "string" || !isMode(item.mode)) return false;
  if (typeof item.cancel_requested !== "boolean" || !isCount(item.palette_count) || !isCount(item.region_count)) return false;
  if (item.seam_gap_rate !== null && (typeof item.seam_gap_rate !== "number" || !Number.isFinite(item.seam_gap_rate) || item.seam_gap_rate < 0 || item.seam_gap_rate > 1)) return false;
  if (typeof item.artifacts !== "object" || item.artifacts === null || Array.isArray(item.artifacts)) return false;
  const artifacts = item.artifacts as Record<string, unknown>;
  if (!Object.entries(artifacts).every(([name, path]) =>
    artifactNames.includes(name) && path === `/v1/jobs/${item.job_id}/artifacts/${name}`)) return false;
  if (item.error !== null) {
    if (typeof item.error !== "object" || item.error === null) return false;
    const error = item.error as Record<string, unknown>;
    if (typeof error.code !== "string" || typeof error.stage !== "string" ||
        typeof error.message !== "string" || typeof error.retryable !== "boolean") return false;
  }
  return true;
}

export function errorDetail(value: unknown): string {
  if (typeof value !== "object" || value === null || !("detail" in value)) return "Local request failed.";
  const detail = value.detail;
  if (typeof detail === "string") return detail;
  if (typeof detail === "object" && detail !== null && "message" in detail && typeof detail.message === "string") {
    return detail.message;
  }
  return "Local request failed.";
}
