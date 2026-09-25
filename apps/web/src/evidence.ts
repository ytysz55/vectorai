import type { JobStatus } from "./jobApi";

export type EvidenceKind = "measured" | "heuristic" | "gate" | "fallback";
export type StageEvidence = {
  stage: string;
  kind: EvidenceKind;
  review: boolean;
  detail: string;
};

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

function items(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function metric(value: unknown, minimum = 0, maximum = Number.MAX_VALUE): number | null {
  return typeof value === "number" && Number.isFinite(value) &&
    value >= minimum && value <= maximum ? value : null;
}

function fixed(value: number, digits = 4): string {
  return value.toFixed(digits);
}

export function explainEvidence(
  sceneValue: unknown, manifestValue: unknown, validationValue: unknown, job: JobStatus,
): StageEvidence[] {
  const scene = record(sceneValue);
  const manifest = record(manifestValue);
  const validation = record(validationValue);
  if (!scene || !manifest || !validation || scene.schema_version !== "1.0.0" ||
      manifest.schema_version !== "1.0.0" || validation.schema_version !== "1.0.0" ||
      manifest.final_status !== job.state ||
      !["passed", "needs_review"].includes(String(validation.status))) {
    throw new Error("Local evidence artifacts do not match the published job.");
  }
  const result: StageEvidence[] = [];
  if (job.mode === "stroke") {
    const routing = record(scene.routing);
    const routingConfidence = metric(routing?.confidence, 0, 1);
    if (routingConfidence !== null && ["fill", "stroke", "ambiguous"].includes(String(routing?.selected))) {
      const ambiguous = routing?.selected === "ambiguous";
      result.push({ stage: "Stroke routing", kind: "heuristic", review: ambiguous,
        detail: `Decision-margin heuristic ${fixed(routingConfidence)}; route ${routing?.selected}.${ambiguous ? " Ambiguous routing needs review." : ""}` });
    }
    const arbitration = record(scene.arbitration);
    const scoreMargin = metric(arbitration?.score_margin);
    if (scoreMargin !== null && ["success", "needs_review"].includes(String(arbitration?.status))) {
      result.push({ stage: "Stroke selection", kind: "heuristic",
        review: arbitration?.status === "needs_review",
        detail: `Competing candidate score margin ${fixed(scoreMargin)}; not a probability.` });
    }
    const selected = items(arbitration?.ranked).map(record)
      .find((candidate) => candidate?.candidate_id === arbitration?.selected);
    const rmse = metric(selected?.premultiplied_rgba_rmse, 0, 1);
    if (rmse !== null) result.push({ stage: "Rendered fit", kind: "measured", review: false,
      detail: `Selected stroke/fill candidate premultiplied RGBA RMSE ${fixed(rmse)} (unit interval).` });
  } else {
    const palette = record(scene.palette);
    const selectedColors = palette?.selected_color_count;
    const hypothesis = items(palette?.hypotheses).map(record)
      .find((candidate) => candidate?.color_count === selectedColors);
    const sse = metric(hypothesis?.weighted_sse);
    if (sse !== null) result.push({ stage: "Palette fit", kind: "measured", review: false,
      detail: `Selected palette weighted color SSE ${fixed(sse)}; this is not pixel RMSE or calibrated confidence.` });
    const junctions = items(scene.junctions).map(record).filter((item) => item !== null);
    if (junctions.length > 2048) throw new Error("Junction evidence exceeds the review budget.");
    if (junctions.length) {
      const confidences = junctions.map((item) => metric(item?.confidence, 0, 1))
        .filter((value): value is number => value !== null);
      const flagged = junctions.filter((item) => item?.requires_review === true).length;
      if (confidences.length === junctions.length) {
        result.push({ stage: "Junction hypotheses", kind: "heuristic", review: flagged > 0,
          detail: `${flagged} of ${junctions.length} junctions flagged for review; minimum local margin heuristic ${fixed(confidences.reduce((smallest, value) => Math.min(smallest, value), 1))}. Not a probability.` });
      }
    }
    const optimizer = record(scene.optimizer);
    if (optimizer?.status === "degraded" && optimizer.fallback_used === true) {
      result.push({ stage: "Optimization", kind: "fallback", review: true,
        detail: "The optimizer fell back to validated baseline geometry; optimized quality is not claimed." });
    }
    const rank = record(optimizer?.render_rank);
    const winner = items(rank?.scores).map(record)
      .find((candidate) => candidate?.candidate_id === rank?.winner_id);
    const rmse = metric(winner?.aggregate_rmse, 0, 1);
    if (rmse !== null) result.push({ stage: "Rendered fit", kind: "measured", review: false,
      detail: `Selected candidate mean premultiplied RGBA RMSE ${fixed(rmse)} across pinned scales/backgrounds; not a browser residual heatmap.` });
    const seams = record(manifest.seams);
    const observations = items(seams?.observations).map(record).filter((item) => item !== null);
    const gaps = observations.map((item) => metric(item?.transparent_gap_rate, 0, 1))
      .filter((value): value is number => value !== null);
    if (gaps.length && gaps.length === observations.length) {
      const worst = Math.max(...gaps);
      result.push({ stage: "Renderer seam", kind: "measured", review: worst > 0,
        detail: `Maximum observed transparent gap rate ${fixed(worst)} across ${gaps.length} renderer(s). A seam-cover stroke is not a geometric boundary.` });
    }
  }
  const findings = items(validation.gates).map(record).filter((item) => item !== null);
  if (findings.length > 64) throw new Error("Validation evidence exceeds the review budget.");
  const failed = findings.filter((item) => item?.outcome === "failed");
  for (const finding of failed) {
    if (finding?.severity !== "soft" || typeof finding.id !== "string" ||
        !/^[A-Z][A-Z0-9_.-]{1,63}$/.test(finding.id)) continue;
    result.push({ stage: "Validation", kind: "gate", review: true,
      detail: `Soft validation gate ${finding.id} needs review; structural hard gates remain mandatory.` });
  }
  if (job.state === "needs_review" && !result.some((item) => item.review)) {
    result.push({ stage: "Job status", kind: "gate", review: true,
      detail: "The job requests review, but these artifacts do not identify a more specific cause." });
  }
  if (job.state === "degraded" && !result.some((item) => item.kind === "fallback")) {
    result.push({ stage: "Job status", kind: "fallback", review: true,
      detail: "A safe fallback was used; its exact stage is not recorded in this evidence." });
  }
  return result;
}
