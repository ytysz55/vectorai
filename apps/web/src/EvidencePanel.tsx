import { useEffect, useState } from "react";
import { explainEvidence } from "./evidence";
import type { StageEvidence } from "./evidence";
import type { JobStatus } from "./jobApi";
import { readBoundedJson } from "./overlay";

type EvidenceState = { rows: StageEvidence[]; error: string; loading: boolean };

export function EvidencePanel({ job, apiOrigin }: { job: JobStatus; apiOrigin: string }) {
  const [state, setState] = useState<EvidenceState>({ rows: [], error: "", loading: true });
  useEffect(() => {
    const files = ["scene.json", "run-manifest.json", "validation-report.json"];
    const urls = files.map((name) => job.artifacts[name]);
    if (urls.some((url) => !url)) {
      setState({ rows: [], error: "Published evidence bundle is incomplete.", loading: false });
      return;
    }
    const controller = new AbortController();
    setState({ rows: [], error: "", loading: true });
    void Promise.all(urls.map(async (url) => {
      const response = await fetch(`${apiOrigin}${url}`, { signal: controller.signal });
      return readBoundedJson(response);
    })).then(([scene, manifest, validation]) => {
      if (!controller.signal.aborted) {
        setState({ rows: explainEvidence(scene, manifest, validation, job), error: "", loading: false });
      }
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) {
        setState({ rows: [], error: error instanceof Error ? error.message : "Local evidence unavailable.", loading: false });
      }
    });
    return () => controller.abort();
  }, [apiOrigin, job]);

  const flagged = state.rows.filter((row) => row.review);
  return (
    <section className="metrics panel evidence" aria-label="Stage evidence and confidence caveats">
      <h2>Residual and stage evidence</h2>
      <p className="evidence-caveat">
        Measured residuals and heuristic decision margins are different quantities.
        These scores are not calibrated probabilities; topology hard gates cannot be offset by visual fit.
      </p>
      {state.loading && <p role="status">Loading published local evidence…</p>}
      {state.error && <p className="error" role="alert">{state.error}</p>}
      {!state.loading && !state.error && (
        <>
          <p className={flagged.length ? "evidence-review" : "comparison-note"} role="status">
            {flagged.length ? `Review indicated by: ${[...new Set(flagged.map((row) => row.stage))].join(", ")}.` :
              "No stage was flagged by recorded evidence; confidence is not certified."}
          </p>
          {state.rows.length ? (
            <ul className="evidence-list">
              {state.rows.map((row, index) => (
                <li key={`${row.stage}-${row.kind}-${index}`} className={row.review ? "needs-review" : ""}>
                  <strong>{row.stage}</strong>
                  <span>{row.kind === "measured" ? "Measured residual" :
                    row.kind === "heuristic" ? "Uncalibrated heuristic" :
                    row.kind === "fallback" ? "Safe fallback" : "Validation gate"}</span>
                  <p>{row.detail}</p>
                </li>
              ))}
            </ul>
          ) : <p className="comparison-note">No per-stage numeric residual or confidence was recorded for this mode.</p>}
        </>
      )}
    </section>
  );
}
