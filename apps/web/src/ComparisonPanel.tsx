import { useEffect, useRef, useState } from "react";
import type { Dispatch, PointerEvent, SetStateAction } from "react";
import { boundedView, initialView, panBy, viewBox, zoomAt } from "./comparison";
import type { ImageSize, View } from "./comparison";

const MAX_BASELINE_BYTES = 32 * 1024 * 1024;

type PaneProps = {
  title: string;
  imageUrl: string;
  placeholder: string;
  size: ImageSize | null;
  view: View | null;
  setView: Dispatch<SetStateAction<View | null>>;
  raster?: boolean;
};

function Pane({ title, imageUrl, placeholder, size, view, setView, raster = false }: PaneProps) {
  const canvasRef = useRef<SVGSVGElement>(null);
  const dragRef = useRef<{ pointerId: number; x: number; y: number } | null>(null);
  const [dragging, setDragging] = useState(false);

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
    dragRef.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY };
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging(true);
  }

  function pointerMove(event: PointerEvent<SVGSVGElement>) {
    const previous = dragRef.current;
    if (!previous || previous.pointerId !== event.pointerId || !size) return;
    dragRef.current = { pointerId: previous.pointerId, x: event.clientX, y: event.clientY };
    const rectangle = event.currentTarget.getBoundingClientRect();
    setView((view) => view && panBy(
      view, size, { width: rectangle.width, height: rectangle.height },
      event.clientX - previous.x, event.clientY - previous.y,
    ));
  }

  function pointerEnd(event: PointerEvent<SVGSVGElement>) {
    if (dragRef.current?.pointerId !== event.pointerId) return;
    dragRef.current = null;
    setDragging(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

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
        </svg>
      ) : (
        <div className="placeholder">{placeholder}</div>
      )}
    </article>
  );
}

export function ComparisonPanel({ sourceUrl, vectorUrl }: { sourceUrl: string; vectorUrl: string }) {
  const [size, setSize] = useState<ImageSize | null>(null);
  const [view, setView] = useState<View | null>(null);
  const [baselineFile, setBaselineFile] = useState<File | null>(null);
  const [baselineUrl, setBaselineUrl] = useState("");
  const [baselineError, setBaselineError] = useState("");
  const [vectorImageUrl, setVectorImageUrl] = useState("");
  const [vectorError, setVectorError] = useState("");

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
      <div className="comparison">
        <Pane title="Source raster" imageUrl={sourceUrl} placeholder="Loading source" size={size} view={view} setView={setView} raster />
        <Pane title="Validated SVG" imageUrl={vectorImageUrl} placeholder="Awaiting aligned validated SVG" size={size} view={view} setView={setView} />
        <Pane title="User-supplied baseline (not certified)" imageUrl={baselineUrl} placeholder="Select a local baseline PNG/JPEG" size={size} view={view} setView={setView} raster />
      </div>
      <p className="comparison-note">Only the SVG job output has passed VectorAI validation. A user-supplied baseline is visual reference, not benchmark or cut-ready evidence.</p>
    </section>
  );
}
