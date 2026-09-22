import { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type VectorizeResponse = {
  job_id: string;
  status: "success" | "needs_review";
  mode: "faithful" | "geometric" | "minimal" | "stroke";
  artifacts: Record<string, string>;
  palette_count: number;
  region_count: number;
  seam_gap_rate: number;
};

type ErrorResponse = { detail?: unknown };

const API_ORIGIN = "http://127.0.0.1:8000";

function isVectorizeResponse(value: unknown): value is VectorizeResponse {
  return typeof value === "object" && value !== null && "job_id" in value;
}

function errorDetail(value: unknown): string {
  const detail = (value as ErrorResponse).detail;
  return typeof detail === "string" ? detail : "Local reconstruction failed.";
}

function App() {
  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState("geometric");
  const [result, setResult] = useState<VectorizeResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const sourceUrl = useMemo(
    () => (file ? URL.createObjectURL(file) : ""),
    [file],
  );
  const artifactUrl = (name: string) =>
    result ? `${API_ORIGIN}${result.artifacts[name]}` : "";

  async function vectorize() {
    if (!file) {
      setError("Choose a PNG or JPEG first.");
      return;
    }
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const response = await fetch(`${API_ORIGIN}/v1/vectorize`, { // nosemgrep: typescript.react.security.react-insecure-request.react-insecure-request
        method: "POST",
        headers: {
          "content-type":
            file.type === "image/jpeg" ? "image/jpeg" : "image/png",
          "x-vectorai-filename": file.name,
          "x-vectorai-mode": mode,
        },
        body: await file.arrayBuffer(),
      });
      const payload: unknown = await response.json();
      if (!response.ok || !isVectorizeResponse(payload)) {
        throw new Error(errorDetail(payload));
      }
      setResult(payload);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Unexpected local error.",
      );
    } finally {
      setBusy(false);
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
        <h1>
          We don’t trace pixels.
          <br />
          We reconstruct design intent.
        </h1>
        <p className="lede">
          Upload a flat-color logo or icon. The source never leaves this device.
        </p>
      </section>
      <section className="controls panel">
        <label className="file-picker">
          <input
            accept="image/png,image/jpeg"
            type="file"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
          <span>{file ? file.name : "Choose PNG or JPEG"}</span>
        </label>
        <label>
          Reconstruction mode
          <select
            value={mode}
            onChange={(event) => setMode(event.target.value)}
          >
            <option value="faithful">Faithful</option>
            <option value="geometric">Geometric</option>
            <option value="minimal">Minimal</option>
            <option value="stroke">Stroke / line-art</option>
          </select>
        </label>
        <button disabled={busy} onClick={vectorize} type="button">
          {busy ? "Reconstructing locally…" : "Reconstruct locally"}
        </button>
      </section>
      {error && <p className="error">{error}</p>}
      {(sourceUrl || result) && (
        <section className="comparison">
          <article className="panel visual">
            <h2>Source raster</h2>
            {sourceUrl && <img alt="Uploaded source raster" src={sourceUrl} />}
          </article>
          <article className="panel visual">
            <h2>Editable vector result</h2>
            {result ? (
              <img
                alt="Rendered vector preview"
                src={artifactUrl("preview.png")}
              />
            ) : (
              <div className="placeholder">Awaiting local reconstruction</div>
            )}
          </article>
        </section>
      )}
      {result && (
        <section className="metrics panel">
          <h2>Proof artifact</h2>
          <div className="metric-grid">
            <Metric label="Palette" value={`${result.palette_count} colors`} />
            <Metric label="Regions" value={String(result.region_count)} />
            <Metric
              label="Seam gaps"
              value={`${(result.seam_gap_rate * 100).toFixed(2)}%`}
            />
            <Metric label="Mode" value={result.mode} />
            <Metric label="Status" value={result.status} />
          </div>
          <div className="downloads">
            {Object.entries(result.artifacts).map(([name, path]) => (
              <a
                href={`${API_ORIGIN}${path}`}
                key={name}
                target="_blank"
                rel="noreferrer"
              >
                Download {name}
              </a>
            ))}
          </div>
        </section>
      )}
      <footer>
        Offline by design · deterministic artifacts · no remote inference
      </footer>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
