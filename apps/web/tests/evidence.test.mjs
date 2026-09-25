import assert from "node:assert/strict";
import test from "node:test";
import { loadTs } from "./loadTs.mjs";

const { explainEvidence } = await loadTs("../src/evidence.ts");
const job = { state: "needs_review", mode: "faithful" };
const validation = {
  schema_version: "1.0.0", status: "needs_review",
  gates: [{ id: "BOUNDARY.SOFT", severity: "soft", outcome: "failed" }],
};
const manifest = {
  schema_version: "1.0.0", final_status: "needs_review",
  seams: { observations: [{ renderer: "resvg", transparent_gap_rate: 0.02 }] },
};
const scene = {
  schema_version: "1.0.0",
  palette: { selected_color_count: 2, hypotheses: [{ color_count: 2, weighted_sse: 12.5 }] },
  junctions: [{ confidence: 0.3, requires_review: true }, { confidence: 0.8, requires_review: false }],
  optimizer: { status: "success", render_rank: { winner_id: "selected", scores: [
    { candidate_id: "other", aggregate_rmse: 0.1 },
    { candidate_id: "selected", aggregate_rmse: 0.04 },
  ] } },
};

test("shows measured residual separately from heuristic and review origins", () => {
  const rows = explainEvidence(scene, manifest, validation, job);
  assert.deepEqual(rows.filter((row) => row.review).map((row) => row.stage), [
    "Junction hypotheses", "Renderer seam", "Validation",
  ]);
  assert.match(rows.find((row) => row.stage === "Rendered fit").detail, /0\.0400/);
  assert.match(rows.find((row) => row.stage === "Palette fit").detail, /SSE 12\.5000/);
  assert.equal(rows.find((row) => row.stage === "Junction hypotheses").kind, "heuristic");
  assert.equal(rows.some((row) => /probability [0-9]/.test(row.detail)), false);
});

test("optimizer fallback and unattributed review are never called a successful optimization", () => {
  const degraded = { ...job, state: "degraded" };
  const rows = explainEvidence({ ...scene, optimizer: { status: "degraded", fallback_used: true } },
    { ...manifest, final_status: "degraded", seams: { observations: [] } },
    { ...validation, status: "passed", gates: [] }, degraded);
  assert.equal(rows.find((row) => row.stage === "Optimization").kind, "fallback");
  const unattributed = explainEvidence({ schema_version: "1.0.0" },
    { schema_version: "1.0.0", final_status: "needs_review" },
    { schema_version: "1.0.0", status: "passed", gates: [] }, job);
  assert.deepEqual(unattributed.map((row) => row.stage), ["Job status"]);
});

test("stroke routing ambiguity is a heuristic and selected candidate RMSE is measured", () => {
  const rows = explainEvidence({ schema_version: "1.0.0",
    routing: { selected: "ambiguous", confidence: 0, reasons: ["LOW_MARGIN"] },
    arbitration: { status: "needs_review", score_margin: 0.001,
      selected: "stroke", ranked: [{ candidate_id: "stroke", premultiplied_rgba_rmse: 0.033 }] },
  }, { schema_version: "1.0.0", final_status: "needs_review" },
  { ...validation, gates: [] }, { ...job, mode: "stroke" });
  assert.deepEqual(rows.map((row) => row.stage), ["Stroke routing", "Stroke selection", "Rendered fit"]);
  assert.equal(rows[0].review, true);
  assert.equal(rows[2].kind, "measured");
});

test("unknown and inconsistent artifacts cannot fabricate a confidence claim", () => {
  assert.throws(() => explainEvidence(scene, { ...manifest, final_status: "success" }, validation, job));
  const invalid = { ...scene, junctions: [{ confidence: 5, requires_review: true }] };
  const rows = explainEvidence(invalid, manifest, { ...validation, gates: [] }, job);
  assert.equal(rows.some((row) => row.stage === "Junction hypotheses"), false);
  assert.deepEqual(rows.filter((row) => row.review).map((row) => row.stage), ["Renderer seam"]);
});
