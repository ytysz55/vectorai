import assert from "node:assert/strict";
import test from "node:test";
import { loadTs } from "./loadTs.mjs";

const { boundedView, initialView, panBy, screenToImage, viewBox, zoomAt } =
  await loadTs("../src/comparison.ts");
const image = { width: 400, height: 200 };
const viewport = { width: 500, height: 300 };

test("native source, SVG and equal-sized baseline share one image coordinate system", () => {
  const view = initialView(image);
  assert.equal(viewBox(view, image), "0 0 400 200");
  assert.deepEqual(screenToImage(view, image, viewport, 250, 150), { x: 200, y: 100 });
  assert.deepEqual(screenToImage(view, image, viewport, 0, 25), { x: 0, y: 0 });
  assert.deepEqual(screenToImage(view, image, viewport, 500, 275), { x: 400, y: 200 });
});

test("cursor anchored zoom retains the same source pixel despite letterboxing", () => {
  const first = initialView(image);
  const anchored = { x: 350, y: 175 };
  const pixel = screenToImage(first, image, viewport, anchored.x, anchored.y);
  const next = zoomAt(first, image, viewport, anchored.x, anchored.y, 3);
  const after = screenToImage(next, image, viewport, anchored.x, anchored.y);
  assert.ok(Math.abs(after.x - pixel.x) < 1e-8);
  assert.ok(Math.abs(after.y - pixel.y) < 1e-8);
  assert.equal(next.zoom, 3);
  assert.deepEqual(zoomAt(next, image, viewport, 250, 150, 1), initialView(image));
});

test("dragging maps screen pixels to bounded image-space pan on every pane", () => {
  const initial = zoomAt(initialView(image), image, viewport, 250, 150, 4);
  const panned = panBy(initial, image, viewport, 50, -25);
  assert.equal(panned.centerX, 190);
  assert.equal(panned.centerY, 105);
  assert.deepEqual(panBy(initial, image, viewport, -100000, 100000), {
    zoom: 4, centerX: 350, centerY: 25,
  });
  assert.deepEqual(boundedView({ zoom: Infinity, centerX: NaN, centerY: NaN }, image), initialView(image));
});

test("rectangles of different aspect ratios retain the same world viewport", () => {
  const view = zoomAt(initialView(image), image, viewport, 250, 150, 2);
  assert.equal(viewBox(view, image), "100 50 200 100");
  const narrow = { width: 300, height: 500 };
  assert.deepEqual(screenToImage(view, image, narrow, 150, 250), { x: 200, y: 100 });
  assert.deepEqual(screenToImage(view, image, viewport, 250, 150), { x: 200, y: 100 });
});
