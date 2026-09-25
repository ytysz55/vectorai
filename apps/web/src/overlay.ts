import type { ImageSize } from "./comparison";

export type FaceOverlay = { id: string; face_id: number; cycles: [number, number][][] };
export type NodeOverlay = { id: string; face_id: number; x: number; y: number };
export type SharedEdgeOverlay = {
  id: string; faces: [number, number]; start: [number, number]; end: [number, number];
};
export type InspectionOverlay = {
  schema_version: "1.0.0";
  available: boolean;
  reason: string | null;
  faces: FaceOverlay[];
  nodes: NodeOverlay[];
  shared_edges: SharedEdgeOverlay[];
};

const MAX_OVERLAY_BYTES = 8 * 1024 * 1024;
const MAX_NODES = 2_000;
const MAX_SHARED_EDGES = 4_000;

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

function positiveId(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) > 0;
}

function point(value: unknown, size: ImageSize): value is [number, number] {
  return Array.isArray(value) && value.length === 2 &&
    value.every((component) => typeof component === "number" && Number.isFinite(component)) &&
    value[0] >= 0 && value[0] <= size.width && value[1] >= 0 && value[1] <= size.height;
}

export function parseInspectionOverlay(value: unknown, size: ImageSize): InspectionOverlay | null {
  const item = record(value);
  if (!item || item.schema_version !== "1.0.0" || typeof item.available !== "boolean" ||
      !Array.isArray(item.faces) || !Array.isArray(item.nodes) || !Array.isArray(item.shared_edges) ||
      item.faces.length > MAX_NODES || item.nodes.length > MAX_NODES ||
      item.shared_edges.length > MAX_SHARED_EDGES) return null;
  if (!item.available) {
    if (item.reason !== "OVERLAY_BUDGET_EXCEEDED" || item.faces.length || item.nodes.length || item.shared_edges.length) return null;
    return { schema_version: "1.0.0", available: false, reason: item.reason, faces: [], nodes: [], shared_edges: [] };
  }
  const faces: FaceOverlay[] = [];
  const faceIds = new Set<number>();
  let cyclePoints = 0;
  for (const entry of item.faces) {
    const face = record(entry);
    if (!face || !positiveId(face.face_id) || face.id !== `face-${face.face_id}` ||
        faceIds.has(face.face_id) || !Array.isArray(face.cycles)) return null;
    const cycles: [number, number][][] = [];
    for (const cycle of face.cycles) {
      if (!Array.isArray(cycle) || cycle.length < 3 || cycle.length > MAX_NODES ||
          !cycle.every((vertex) => point(vertex, size))) return null;
      cyclePoints += cycle.length;
      if (cyclePoints > MAX_NODES) return null;
      cycles.push(cycle);
    }
    if (!cycles.length) return null;
    faceIds.add(face.face_id);
    faces.push({ id: face.id, face_id: face.face_id, cycles });
  }
  const nodes: NodeOverlay[] = [];
  const nodeIds = new Set<string>();
  for (const entry of item.nodes) {
    const node = record(entry);
    if (!node || !positiveId(node.face_id) || !faceIds.has(node.face_id) ||
        typeof node.id !== "string" || !point([node.x, node.y], size)) return null;
    const match = /^face-([1-9]\d*)-cycle-(0|[1-9]\d*)-node-(0|[1-9]\d*)$/.exec(node.id);
    if (!match || Number(match[1]) !== node.face_id || nodeIds.has(node.id)) return null;
    const face = faces.find((candidate) => candidate.face_id === node.face_id);
    const expected = face?.cycles[Number(match[2])]?.[Number(match[3])];
    if (!expected || expected[0] !== node.x || expected[1] !== node.y) return null;
    nodeIds.add(node.id);
    nodes.push({ id: node.id, face_id: node.face_id, x: node.x as number, y: node.y as number });
  }
  if (nodes.length !== cyclePoints) return null;
  const shared_edges: SharedEdgeOverlay[] = [];
  const edgeIds = new Set<string>();
  for (const entry of item.shared_edges) {
    const edge = record(entry);
    if (!edge || typeof edge.id !== "string" || !/^edge-(0|[1-9]\d*)$/.test(edge.id) ||
        edgeIds.has(edge.id) || !Array.isArray(edge.faces) || edge.faces.length !== 2 ||
        !positiveId(edge.faces[0]) || !positiveId(edge.faces[1]) ||
        edge.faces[0] >= edge.faces[1] || !faceIds.has(edge.faces[0]) || !faceIds.has(edge.faces[1]) ||
        !point(edge.start, size) || !point(edge.end, size) ||
        edge.start[0] === edge.end[0] && edge.start[1] === edge.end[1]) return null;
    edgeIds.add(edge.id);
    shared_edges.push({ id: edge.id, faces: edge.faces as [number, number], start: edge.start, end: edge.end });
  }
  return { schema_version: "1.0.0", available: true, reason: null, faces, nodes, shared_edges };
}

export async function readBoundedJson(response: Response): Promise<unknown> {
  if (!response.ok) {
    await response.body?.cancel();
    throw new Error("Local evidence artifact is unavailable.");
  }
  const claimed = response.headers.get("content-length");
  if (claimed && Number(claimed) > MAX_OVERLAY_BYTES) {
    await response.body?.cancel();
    throw new Error("Local scene metadata exceeds the inspection budget.");
  }
  if (!response.body) throw new Error("Local scene response has no body.");
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      total += next.value.byteLength;
      if (total > MAX_OVERLAY_BYTES) throw new Error("Local scene metadata exceeds the inspection budget.");
      chunks.push(next.value);
    }
  } finally {
    reader.releaseLock();
    if (total > MAX_OVERLAY_BYTES) await response.body.cancel();
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try {
    const parsed: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
    return parsed;
  } catch (error) {
    if (error instanceof SyntaxError || error instanceof TypeError) {
      throw new Error("Local scene metadata could not be decoded.", { cause: error });
    }
    throw error;
  }
}

export async function readLocalOverlay(response: Response, size: ImageSize): Promise<InspectionOverlay> {
  const scene = record(await readBoundedJson(response));
  const overlay = parseInspectionOverlay(scene?.inspection_overlay, size);
  if (!overlay) throw new Error("Local inspection geometry failed validation.");
  return overlay;
}
