import { useEffect, useRef, useState } from "react";
import type { Dispatch, PointerEvent, SetStateAction } from "react";
import { boundedView, initialView, panBy, viewBox, zoomAt } from "./comparison";
import type { ImageSize, View } from "./comparison";
import { readLocalOverlay } from "./overlay";
import type { InspectionOverlay } from "./overlay";

const MAX_BASELINE_BYTES = 32 * 1024 * 1024;

type PaneProps = {
  title: string;
  imageUrl: string;
  placeholder: string;
  size: ImageSize | null;
  view: View | null;
  setView: Dispatch<SetStateAction<View | null>>;
  raster?: boolean;
  overlay: InspectionOverlay | null;
  showNodes: boolean;
  showRegions: boolean;
  showEdges: boolean;
  selectedId: string;
  selectId: (id: string) => void;
};

function regionPath(cycles: [number, number][][]): string {
  return cycles.map((cycle) =>
    `M${cycle.map(([x, y]) => `${x} ${y}`).join(" L")} Z`
  ).join(" ");
}

function Pane({ title, imageUrl, placeholder, size, view, setView, raster = false,
  overlay, showNodes, showRegions, showEdges, selectedId, selectId }: PaneProps) {
  const canvasRef = useRef<SVGSVGElement>(null);
  const dragRef = useRef<{ pointerId: number; x: number; y: number; candidate: string | null } | null>(null);
  const [dragging, setDragging] = useState(false);
  const draggedRef = useRef(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !size || !imageUrl) return;
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      const rectangle = canvas.getBoundingClientRect();
      const viewport = { width: rectangle.width, height: rectangle.height };
      setView((previous) => previous && zoomAt(
        previous, size, viewport,
        event.clientX - rectangle.left, event.clientY - rectangle.top,
        previous.zoom * (event.deltaY < 0 ? 1.25 : 0.8),
      ));
    };
    canvas.addEventListener("wheel", wheel, { passive: false });
    return () => canvas.removeEventListener("wheel", wheel);
  }, [imageUrl, setView, size]);

  function pointerDown(event: PointerEvent<SVGSVGElement>) {
    if (event.button !== 0 || !size) return;
    const candidate = event.target instanceof Element
      ? event.target.getAttribute("data-entity-id") : null;
    dragRef.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, candidate };
    draggedRef.current = false;
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging(true);
  }

  function pointerMove(event: PointerEvent<SVGSVGElement>) {
    const previous = dragRef.current;
    if (!previous || previous.pointerId !== event.pointerId || !size) return;
    if (Math.abs(event.clientX - previous.x) + Math.abs(event.clientY - previous.y) > 1) {
      draggedRef.current = true;
    }
    dragRef.current = { ...previous, x: event.clientX, y: event.clientY };
    const rectangle = event.currentTarget.getBoundingClientRect();
    setView((view) => view && panBy(
      view, size, { width: rectangle.width, height: rectangle.height },
      event.clientX - previous.x, event.clientY - previous.y,
    ));
  }

  function pointerEnd(event: PointerEvent<SVGSVGElement>) {
    const last = dragRef.current;
    if (last?.pointerId !== event.pointerId) return;
    dragRef.current = null;
    setDragging(false);
    if (event.type === "pointerup" && !draggedRef.current && last.candidate) {
      selectId(last.candidate);
    }
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  const nodeRadius = size && view ? Math.min(size.width, size.height) / (110 * view.zoom) : 0;

  return (
    <article className="panel visual">
      <h2>{title}</h2>
      {size && view && imageUrl ? (
        <svg
          ref={canvasRef}
          className={`compare-canvas${dragging ? " is-dragging" : ""}`}
          viewBox={viewBox(view, size)}
          preserveAspectRatio="xMidYMid meet"
          role="img"
          aria-label={`${title}, ${Math.round(view.zoom * 100)}% zoom; drag to pan`}
          onPointerDown={pointerDown}
          onPointerMove={pointerMove}
          onPointerUp={pointerEnd}
          onPointerCancel={pointerEnd}
        >
          <title>{title}</title>
          <image
            href={imageUrl}
            x={0} y={0} width={size.width} height={size.height}
            preserveAspectRatio="none"
            imageRendering={raster ? "pixelated" : "auto"}
          />
          {overlay?.available && showRegions && overlay.faces.map((face) => (
            <path key={face.id} className={`overlay-region${selectedId === face.id ? " selected" : ""}`}
              d={regionPath(face.cycles)} fillRule="evenodd"
              data-entity-id={face.id} aria-label={`Region ${face.face_id}`} />
          ))}
          {overlay?.available && showEdges && overlay.shared_edges.map((edge) => (
            <line key={edge.id} className={`overlay-edge${selectedId === edge.id ? " selected" : ""}`}
              x1={edge.start[0]} y1={edge.start[1]} x2={edge.end[0]} y2={edge.end[1]}
              data-entity-id={edge.id} aria-label={`Canonical edge ${edge.id}`} />
          ))}
          {overlay?.available && showNodes && overlay.nodes.map((node) => (
            <circle key={node.id} className={`overlay-node${selectedId === node.id ? " selected" : ""}`}
              cx={node.x} cy={node.y} r={Math.max(nodeRadius, 0.01)}
              data-entity-id={node.id} aria-label={`Scene node ${node.id}`} />
          ))}
        </svg>
      ) : (
        <div className="placeholder">{placeholder}</div>
      )}
    </article>
  );
}

export function ComparisonPanel({ sourceUrl, vectorUrl, inspectionUrl }: {
  sourceUrl: string; vectorUrl: string; inspectionUrl: string;
}) {
  const [size, setSize] = useState<ImageSize | null>(null);
  const [view, setView] = useState<View | null>(null);
  const [baselineFile, setBaselineFile] = useState<File | null>(null);
  const [baselineUrl, setBaselineUrl] = useState("");
  const [baselineError, setBaselineError] = useState("");
  const [vectorImageUrl, setVectorImageUrl] = useState("");
  const [vectorError, setVectorError] = useState("");
  const [overlay, setOverlay] = useState<InspectionOverlay | null>(null);
  const [overlayError, setOverlayError] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [showNodes, setShowNodes] = useState(false);
  const [showRegions, setShowRegions] = useState(false);
  const [showEdges, setShowEdges] = useState(true);

  useEffect(() => {
    if (!sourceUrl) return;
    const image = new Image();
    let active = true;
    image.onload = () => {
      if (!active) return;
      const loaded = { width: image.naturalWidth, height: image.naturalHeight };
      if (loaded.width <= 0 || loaded.height <= 0) return;
      setSize(loaded);
      setView(initialView(loaded));
    };
    image.onerror = () => { if (active) setBaselineError("Source image could not be decoded locally."); };
    image.src = sourceUrl;
    return () => { active = false; image.onload = null; image.onerror = null; };
  }, [sourceUrl]);

  useEffect(() => {
    setVectorImageUrl("");
    setVectorError("");
    if (!vectorUrl || !size) return;
    const image = new Image();
    let active = true;
    image.onload = () => {
      if (!active) return;
      if (image.naturalWidth !== size.width || image.naturalHeight !== size.height) {
        setVectorError("SVG dimensions do not match the source; aligned comparison is disabled.");
      } else {
        setVectorImageUrl(vectorUrl);
      }
    };
    image.onerror = () => { if (active) setVectorError("Validated SVG could not be displayed."); };
    image.src = vectorUrl;
    return () => { active = false; image.onload = null; image.onerror = null; };
  }, [vectorUrl, size]);

  useEffect(() => {
    if (!baselineFile || !size) return;
    const url = URL.createObjectURL(baselineFile);
    const image = new Image();
    let active = true;
    setBaselineUrl("");
    setBaselineError("");
    image.onload = () => {
      if (!active) return;
      if (image.naturalWidth !== size.width || image.naturalHeight !== size.height) {
        setBaselineError(`Baseline must be ${size.width} × ${size.height} pixels to align.`);
      } else {
        setBaselineUrl(url);
      }
    };
    image.onerror = () => { if (active) setBaselineError("Baseline image could not be decoded locally."); };
    image.src = url;
    return () => { active = false; image.onload = null; image.onerror = null; URL.revokeObjectURL(url); };
  }, [baselineFile, size]);

  useEffect(() => {
    setOverlay(null);
    setOverlayError("");
    setSelectedId("");
    if (!inspectionUrl || !size || !vectorImageUrl) return;
    const controller = new AbortController();
    void fetch(inspectionUrl, { signal: controller.signal })
      .then((response) => readLocalOverlay(response, size))
      .then((parsed) => { if (!controller.signal.aborted) setOverlay(parsed); })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setOverlayError(caught instanceof Error ? caught.message : "Inspection geometry unavailable.");
        }
      });
    return () => controller.abort();
  }, [inspectionUrl, size, vectorImageUrl]);

  const selected = overlay?.available ?
    overlay.faces.find((face) => face.id === selectedId) ??
    overlay.shared_edges.find((edge) => edge.id === selectedId) ??
    overlay.nodes.find((node) => node.id === selectedId) : null;
  const paneProps = { size, view, setView, overlay, showNodes, showRegions, showEdges,
    selectedId, selectId: setSelectedId };
  const percent = view ? Math.round(view.zoom * 100) : 100;
  const zoom = (factor: number) => {
    if (!size) return;
    setView((previous) => previous && boundedView({ ...previous, zoom: previous.zoom * factor }, size));
  };
  return (
    <section className="comparison-section" aria-label="Synchronized local comparison">
      <div className="comparison-tools panel">
        <span>Linked image coordinates · drag any view to pan; scroll to zoom</span>
        <div className="zoom-controls" aria-label="Comparison zoom controls">
          <button aria-label="Zoom out" disabled={!size || percent === 100} onClick={() => zoom(0.5)} type="button">−</button>
          <output aria-live="polite">{percent}%</output>
          <button aria-label="Zoom in" disabled={!size || percent === 1600} onClick={() => zoom(2)} type="button">+</button>
          <button disabled={!size} onClick={() => { if (size) setView(initialView(size)); }} type="button">Reset view</button>
        </div>
        <label className="baseline-picker">
          Optional local baseline PNG/JPEG (same pixel dimensions; unverified)
          <input
            type="file" accept="image/png,image/jpeg"
            onChange={(event) => {
              const selected = event.target.files?.[0] ?? null;
              event.target.value = "";
              setBaselineFile(null);
              setBaselineUrl("");
              if (selected && !["image/png", "image/jpeg"].includes(selected.type)) {
                setBaselineError("Baseline must be PNG or JPEG."); return;
              }
              if (selected && selected.size > MAX_BASELINE_BYTES) {
                setBaselineError("Baseline exceeds the 32 MiB local limit."); return;
              }
              setBaselineError("");
              setBaselineFile(selected);
            }}
          />
        </label>
      </div>
      {baselineError && <p className="error" role="alert">{baselineError}</p>}
      {vectorError && <p className="error" role="alert">{vectorError}</p>}
      {overlayError && <p className="error" role="alert">{overlayError}</p>}
      {overlay && !overlay.available && (
        <p className="comparison-note">Inspection overlay omitted: local entity budget exceeded.</p>
      )}
      {overlay?.available && (
        <div className="overlay-tools panel" aria-label="Inspection overlays">
          <label><input type="checkbox" checked={showRegions} onChange={(event) => setShowRegions(event.target.checked)} /> Model regions</label>
          <label><input type="checkbox" checked={showEdges} onChange={(event) => setShowEdges(event.target.checked)} /> Canonical graph edges</label>
          <label><input type="checkbox" checked={showNodes} onChange={(event) => setShowNodes(event.target.checked)} /> Scene vertices</label>
          <span role="status" aria-live="polite">
            {selected ? `${selected.id}${"faces" in selected ? ` · faces ${selected.faces.join(" / ")}` :
              "x" in selected ? ` · (${selected.x.toFixed(2)}, ${selected.y.toFixed(2)})` : ""}` : "Select an entity to inspect its stable job ID"}
          </span>
        </div>
      )}
      <div className="comparison">
        <Pane {...paneProps} title="Source raster" imageUrl={sourceUrl} placeholder="Loading source" raster />
        <Pane {...paneProps} title="Validated SVG" imageUrl={vectorImageUrl} placeholder="Awaiting aligned validated SVG" />
        <Pane {...paneProps} title="User-supplied baseline (not certified)" imageUrl={baselineUrl} placeholder="Select a local baseline PNG/JPEG" raster />
      </div>
      <p className="comparison-note">Only the SVG job output has passed VectorAI validation. A user-supplied baseline is visual reference, not benchmark or cut-ready evidence.</p>
    </section>
  );
}
