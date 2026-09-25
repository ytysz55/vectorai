export type ImageSize = { width: number; height: number };
export type ViewportSize = { width: number; height: number };
export type View = { zoom: number; centerX: number; centerY: number };

export const MAX_ZOOM = 16;

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

export function initialView(image: ImageSize): View {
  return { zoom: 1, centerX: image.width / 2, centerY: image.height / 2 };
}

export function boundedView(view: View, image: ImageSize): View {
  if (!Number.isFinite(image.width) || !Number.isFinite(image.height) || image.width <= 0 || image.height <= 0) {
    throw new Error("Image dimensions must be positive and finite.");
  }
  const zoom = clamp(Number.isFinite(view.zoom) ? view.zoom : 1, 1, MAX_ZOOM);
  const halfWidth = image.width / (2 * zoom);
  const halfHeight = image.height / (2 * zoom);
  return {
    zoom,
    centerX: clamp(Number.isFinite(view.centerX) ? view.centerX : image.width / 2, halfWidth, image.width - halfWidth),
    centerY: clamp(Number.isFinite(view.centerY) ? view.centerY : image.height / 2, halfHeight, image.height - halfHeight),
  };
}

export function viewBox(view: View, image: ImageSize): string {
  const bounded = boundedView(view, image);
  const width = image.width / bounded.zoom;
  const height = image.height / bounded.zoom;
  return `${bounded.centerX - width / 2} ${bounded.centerY - height / 2} ${width} ${height}`;
}

function layout(view: View, image: ImageSize, viewport: ViewportSize) {
  const bounded = boundedView(view, image);
  const visibleWidth = image.width / bounded.zoom;
  const visibleHeight = image.height / bounded.zoom;
  const scale = Math.min(viewport.width / visibleWidth, viewport.height / visibleHeight);
  if (!Number.isFinite(scale) || scale <= 0) return null;
  return {
    view: bounded, visibleWidth, visibleHeight, scale,
    insetX: (viewport.width - visibleWidth * scale) / 2,
    insetY: (viewport.height - visibleHeight * scale) / 2,
  };
}

export function screenToImage(
  view: View, image: ImageSize, viewport: ViewportSize, x: number, y: number,
): { x: number; y: number } {
  const fitted = layout(view, image, viewport);
  if (!fitted) return { x: image.width / 2, y: image.height / 2 };
  const { visibleWidth, visibleHeight, scale, insetX, insetY } = fitted;
  return {
    x: clamp(fitted.view.centerX - visibleWidth / 2 + (x - insetX) / scale, 0, image.width),
    y: clamp(fitted.view.centerY - visibleHeight / 2 + (y - insetY) / scale, 0, image.height),
  };
}

export function zoomAt(
  view: View, image: ImageSize, viewport: ViewportSize, x: number, y: number, zoom: number,
): View {
  const fitted = layout(view, image, viewport);
  if (!fitted) return boundedView({ ...view, zoom }, image);
  const anchor = screenToImage(view, image, viewport, x, y);
  const xFraction = clamp((x - fitted.insetX) / (fitted.visibleWidth * fitted.scale), 0, 1);
  const yFraction = clamp((y - fitted.insetY) / (fitted.visibleHeight * fitted.scale), 0, 1);
  const nextZoom = clamp(zoom, 1, MAX_ZOOM);
  return boundedView({
    zoom: nextZoom,
    centerX: anchor.x + (0.5 - xFraction) * image.width / nextZoom,
    centerY: anchor.y + (0.5 - yFraction) * image.height / nextZoom,
  }, image);
}

export function panBy(
  view: View, image: ImageSize, viewport: ViewportSize, deltaX: number, deltaY: number,
): View {
  const fitted = layout(view, image, viewport);
  if (!fitted) return boundedView(view, image);
  return boundedView({
    ...fitted.view,
    centerX: fitted.view.centerX - deltaX / fitted.scale,
    centerY: fitted.view.centerY - deltaY / fitted.scale,
  }, image);
}
