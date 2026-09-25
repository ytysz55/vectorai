import assert from "node:assert/strict";
import test from "node:test";
import { loadTs } from "./loadTs.mjs";

const { parseInspectionOverlay, readLocalOverlay } = await loadTs("../src/overlay.ts");
const size = { width: 24, height: 12 };
const valid = {
  schema_version: "1.0.0", available: true, reason: null,
  faces: [
    { id: "face-1", face_id: 1, cycles: [[[0, 0], [12, 0], [12, 12], [0, 12]]] },
    { id: "face-2", face_id: 2, cycles: [[[12, 0], [24, 0], [24, 12], [12, 12]]] },
  ],
  nodes: [
    ...[[0, 0], [12, 0], [12, 12], [0, 12]].map(([x, y], index) => ({
      id: `face-1-cycle-0-node-${index}`, face_id: 1, x, y,
    })),
    ...[[12, 0], [24, 0], [24, 12], [12, 12]].map(([x, y], index) => ({
      id: `face-2-cycle-0-node-${index}`, face_id: 2, x, y,
    })),
  ],
  shared_edges: [{ id: "edge-12", faces: [1, 2], start: [12, 0], end: [12, 12] }],
};

test("stable entity IDs, source pixels, canonical face links and bounded geometry", () => {
  assert.deepEqual(parseInspectionOverlay(valid, size), valid);
  assert.equal(parseInspectionOverlay({ ...valid, nodes: [{ ...valid.nodes[0], x: Infinity }, ...valid.nodes.slice(1)] }, size), null);
  assert.equal(parseInspectionOverlay({ ...valid, nodes: valid.nodes.slice(1) }, size), null);
  assert.equal(parseInspectionOverlay({ ...valid, nodes: [{ ...valid.nodes[0], x: 1 }, ...valid.nodes.slice(1)] }, size), null);
  assert.equal(parseInspectionOverlay({ ...valid, faces: [valid.faces[0], valid.faces[0]] }, size), null);
  assert.equal(parseInspectionOverlay({ ...valid, shared_edges: [{ ...valid.shared_edges[0], faces: [2, 1] }] }, size), null);
  assert.equal(parseInspectionOverlay({ ...valid, shared_edges: [{ ...valid.shared_edges[0], id: "edge-onclick()" }] }, size), null);
  assert.equal(parseInspectionOverlay({ ...valid, shared_edges: [{ ...valid.shared_edges[0], end: [12, 0] }] }, size), null);
});

test("budget omission is explicit and never mistaken for empty valid geometry", () => {
  const omitted = { schema_version: "1.0.0", available: false,
    reason: "OVERLAY_BUDGET_EXCEEDED", nodes: [], faces: [], shared_edges: [] };
  assert.deepEqual(parseInspectionOverlay(omitted, size), omitted);
  assert.equal(parseInspectionOverlay({ ...omitted, shared_edges: valid.shared_edges }, size), null);
});

test("scene fetch is bounded and malformed remote JSON fails closed", async () => {
  const url = "http://127.0.0.1:8000/v1/jobs/test/artifacts/scene.json";
  const body = JSON.stringify({ inspection_overlay: valid });
  assert.deepEqual(await readLocalOverlay(new Response(body), size), valid);
  await assert.rejects(readLocalOverlay(new Response("not json"), size), /could not be decoded/);
  await assert.rejects(readLocalOverlay(new Response(body, { headers: { "content-length": "9000000" } }), size), /budget/);
  await assert.rejects(readLocalOverlay(new Response("{}"), size), /failed validation/);
  assert.equal(url.startsWith("http://127.0.0.1:"), true);
});
