import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { ComparisonPanel } from "./ComparisonPanel";
import { EvidencePanel } from "./EvidencePanel";
import { MODE_OPTIONS, errorDetail, isJobStatus, isMode, isPublished, isTerminal } from "./jobApi";
import type { JobStatus, Mode } from "./jobApi";
import "./styles.css";

const API_ORIGIN = "http://127.0.0.1:8000";
const MAX_UPLOAD_BYTES = 32 * 1024 * 1024;

async function parseResponse(response: Response): Promise<JobStatus> {
  const payload: unknown = await response.json();
  if (!response.ok) throw new Error(errorDetail(payload));
  if (!isJobStatus(payload)) throw new Error("Local job response failed validation.");
  return payload;
}

function App() {
  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState<Mode>("geometric");
  const [job, setJob] = useState<JobStatus | null>(null);
  const [sourceUrl, setSourceUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const controllerRef = useRef<AbortController | null>(null);
  const submissionRef = useRef<{ file: File; mode: Mode; key: string } | null>(null);

  useEffect(() => {
    if (!file) { setSourceUrl(""); return; }
    const url = URL.createObjectURL(file);
    setSourceUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  useEffect(() => () => controllerRef.current?.abort(), []);

  const activeJob = job !== null && !isTerminal(job.state);
  const published = job !== null && isPublished(job.state);
  const artifactUrl = (name: string) =>
    published && job.artifacts[name] ? `${API_ORIGIN}${job.artifacts[name]}` : "";

  async function followJob(initial: JobStatus, controller: AbortController): Promise<void> {
    let current = initial;
    while (!isTerminal(current.state) && !controller.signal.aborted) {
      await new Promise<void>((resolve) => setTimeout(resolve, 600));
      if (controller.signal.aborted) return;
      const response = await fetch(`${API_ORIGIN}/v1/jobs/${current.job_id}`, { signal: controller.signal });
      current = await parseResponse(response);
      if (!controller.signal.aborted) setJob(current);
    }
  }

  async function vectorize() {
    if (!file) { setError("Choose a PNG or JPEG first."); return; }
    if (file.type !== "image/png" && file.type !== "image/jpeg") {
      setError("Only PNG and JPEG are supported."); return;
    }
    if (file.size > MAX_UPLOAD_BYTES) { setError("Image exceeds the 32 MiB local upload limit."); return; }
    const controller = new AbortController();
    controllerRef.current = controller;
    setBusy(true);
    setError("");
    try {
      let current: JobStatus;
      if (activeJob && job) {
        current = job; // Resume polling; never silently enqueue duplicate work.
      } else {
        setJob(null);
        const previous = submissionRef.current;
        const key = previous?.file === file && previous.mode === mode
          ? previous.key : crypto.randomUUID();
        submissionRef.current = { file, mode, key };
        const response = await fetch(`${API_ORIGIN}/v1/jobs`, { // nosemgrep: typescript.react.security.react-insecure-request.react-insecure-request
          method: "POST",
          headers: {
            "content-type": file.type,
            "x-vectorai-filename": file.name,
            "x-vectorai-mode": mode,
            "idempotency-key": key,
          },
          body: file,
          signal: controller.signal,
        });
        current = await parseResponse(response);
        if (controller.signal.aborted) return;
        setJob(current);
        submissionRef.current = null;
      }
      await followJob(current, controller);
    } catch (caught) {
      if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "Local request failed.");
    } finally {
      if (!controller.signal.aborted) {
        setBusy(false);
        controllerRef.current = null;
      }
    }
  }

  async function cancelJob() {
    if (!job || !activeJob || job.cancel_requested) return;
    try {
      const response = await fetch(`${API_ORIGIN}/v1/jobs/${job.job_id}/cancel`, {
        method: "POST",
        signal: controllerRef.current?.signal,
      });
      const updated = await parseResponse(response);
      setJob(updated);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to cancel local job.");
    }
  }

  return (
    <main>
      <header>
        <div className="brand">VectorAI</div>
        <span className="local-badge">● LOCAL-ONLY · 127.0.0.1</span>
      </header>
      <section className="hero">
        <p className="eyebrow">TOPOLOGY-FIRST VECTOR RECONSTRUCTION</p>
        <h1>We don’t trace pixels.<br />We reconstruct design intent.</h1>
        <p className="lede">Upload a flat-color logo or icon. The source never leaves this device.</p>
      </section>
      <section className="controls panel">
        <label className="file-picker">
          <input
            accept="image/png,image/jpeg"
            type="file"
            disabled={busy || activeJob}
            onChange={(event) => { setFile(event.target.files?.[0] ?? null); setJob(null); setError(""); submissionRef.current = null; }}
          />
          <span>{file ? file.name : "Choose PNG or JPEG"}</span>
        </label>
        <label>
          Reconstruction mode
          <select
            value={mode}
            disabled={busy || activeJob}
            onChange={(event) => { if (isMode(event.target.value)) { setMode(event.target.value); submissionRef.current = null; } }}
          >
            {MODE_OPTIONS.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <button disabled={busy} onClick={vectorize} type="button">
          {busy ? "Reconstructing locally…" : activeJob ? "Resume job status" : "Reconstruct locally"}
        </button>
        {activeJob && !job?.cancel_requested && (
          <button className="cancel" onClick={cancelJob} type="button">Cancel job</button>
        )}
      </section>
      {job && (
        <p className="job-state" role="status" aria-live="polite">
          Job {job.job_id.slice(-12)} · {job.state}
          {job.cancel_requested ? " · cancellation requested" : ""}
          {job.error ? ` · ${job.error.code}: ${job.error.message}` : ""}
        </p>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      {sourceUrl && (
        <ComparisonPanel
          key={`${sourceUrl}:${job?.job_id ?? ""}`}
          sourceUrl={sourceUrl}
          vectorUrl={job && artifactUrl("output.svg")
            ? `${API_ORIGIN}/v1/jobs/${job.job_id}/preview.svg` : ""}
          inspectionUrl={job?.mode !== "stroke" ? artifactUrl("scene.json") : ""}
        />
      )}
      {job && (
        <section className="metrics panel">
          <h2>Proof artifact</h2>
          <div className="metric-grid">
            <Metric label="Palette" value={job.palette_count === null ? "—" : `${job.palette_count} colors`} />
            <Metric label="Regions" value={job.region_count === null ? "—" : String(job.region_count)} />
            <Metric label="Seam gaps" value={job.seam_gap_rate === null ? "—" : `${(job.seam_gap_rate * 100).toFixed(2)}%`} />
            <Metric label="Mode" value={job.mode} />
            <Metric label="Status" value={job.state} />
          </div>
          {published && (
            <div className="downloads">
              {Object.entries(job.artifacts).map(([name, path]) => (
                <a href={`${API_ORIGIN}${path}`} key={name} target="_blank" rel="noreferrer">
                  Download {name}
                </a>
              ))}
            </div>
          )}
        </section>
      )}
      {published && job && <EvidencePanel key={job.job_id} job={job} apiOrigin={API_ORIGIN} />}
      <footer>Offline by design · deterministic artifacts · no remote inference</footer>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

createRoot(document.getElementById("root")!).render(<App />);
