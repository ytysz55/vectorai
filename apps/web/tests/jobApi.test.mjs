import assert from "node:assert/strict";
import test from "node:test";
import { loadTs } from "./loadTs.mjs";

const { MODE_OPTIONS, errorDetail, isJobStatus, isMode, isPublished, isTerminal } =
  await loadTs("../src/jobApi.ts");

const jobId = `${"a".repeat(64)}-123456789abc`;
const valid = {
  job_id: jobId,
  state: "accepted",
  mode: "geometric",
  cancel_requested: false,
  artifacts: {},
  palette_count: null,
  region_count: null,
  seam_gap_rate: null,
  error: null,
};

test("all four advertised modes are represented and bounded", () => {
  assert.deepEqual(MODE_OPTIONS.map((mode) => mode.value), ["faithful", "geometric", "minimal", "stroke"]);
  assert.equal(isMode("minimal"), true);
  assert.equal(isMode("cut_ready"), false);
});

test("every terminal outcome and publication gate is explicit", () => {
  for (const state of ["accepted", "running"]) {
    assert.equal(isTerminal(state), false);
    assert.equal(isPublished(state), false);
  }
  for (const state of ["success", "degraded", "needs_review", "unsupported", "failed", "canceled"]) {
    assert.equal(isTerminal(state), true);
    assert.equal(isPublished(state), ["success", "degraded", "needs_review"].includes(state));
  }
});

test("rejects malformed statuses and untrusted artifact paths", () => {
  assert.equal(isJobStatus(valid), true);
  assert.equal(isJobStatus({ ...valid, state: "surprise" }), false);
  assert.equal(isJobStatus({ ...valid, mode: "fake" }), false);
  assert.equal(isJobStatus({ ...valid, artifacts: { "preview.png": `https://elsewhere/${jobId}` } }), false);
  assert.equal(isJobStatus({ ...valid, artifacts: { "preview.png": `/v1/jobs/${jobId}/artifacts/preview.png` } }), true);
  assert.equal(isJobStatus({ ...valid, error: { code: "DECODE_ERROR", stage: "decode", message: "invalid", retryable: false } }), true);
});

test("typed API errors do not leak arbitrary server objects", () => {
  assert.equal(errorDetail({ detail: { code: "RESOURCE_LIMIT", message: "Local queue is full." } }), "Local queue is full.");
  assert.equal(errorDetail({ detail: { stack: "secret" } }), "Local request failed.");
  assert.equal(errorDetail(null), "Local request failed.");
});
