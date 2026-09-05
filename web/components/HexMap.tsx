"use client";

import { ScatterplotLayer, SolidPolygonLayer, TextLayer } from "@deck.gl/layers";
import { MapboxOverlay } from "@deck.gl/mapbox";
import maplibregl from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

import "maplibre-gl/dist/maplibre-gl.css";

import type { Boundaries } from "../lib/data/geometry";

/**
 * The map. Imported dynamically by every view that uses it, so deck.gl and MapLibre stay
 * out of the app shell and the §11.3 600 KB shell budget is met by construction rather
 * than by hoping the bundler splits them.
 *
 * **Binary rendering path.** Cell geometry arrives as a `Float64Array` of vertices with
 * polygon start indices, computed in a worker, and colours as a **per-vertex**
 * `Uint8Array`. deck.gl uploads both straight to the GPU without walking 53,208 objects.
 * That is what the sustained frame-rate budget needs, and it is why this uses
 * `SolidPolygonLayer` from `@deck.gl/layers` rather than `H3HexagonLayer` from the much
 * larger `@deck.gl/geo-layers` - the latter's job is precisely the conversion the worker
 * does.
 *
 * Two things about that path are load-bearing and were each responsible for an invisible
 * layer, so neither may be "simplified" back:
 *
 * 1. **`_normalize` stays at its default.** Setting it to `false` makes deck.gl draw
 *    nothing here, while still reporting the full feature count.
 * 2. **Colours are per VERTEX, not per polygon.** A per-polygon buffer is a seventh of the
 *    length the layer reads and produces wrong colours.
 *
 * See `lib/render.ts` and the Phase 6 report for the diagnosis.
 *
 * The basemap is **OpenFreeMap**, which needs no key (§2: "No keyed provider"). §12 records
 * that it is a single point of failure and that a self-hosted Protomaps fallback belongs on
 * R2; that fallback is Phase 7 infrastructure. Until it exists, a basemap failure is
 * surfaced rather than swallowed: the data layer still renders, and the page says the
 * geographic context is missing instead of showing an empty country.
 */
const BASEMAP = "https://tiles.openfreemap.org/styles/positron";

/** A selected portfolio area, drawn as a dominant marker on top of the faint eligible set. */
export interface SelectedDatum {
  readonly longitude: number;
  readonly latitude: number;
  readonly rank: number;
}

export interface SiteDatum {
  readonly longitude: number;
  readonly latitude: number;
  readonly serves_dcfc: boolean;
}

export interface HexMapProps {
  readonly boundaries: Boundaries | null;
  /** RGBA per VERTEX: length = (positions.length / 2) * 4. See lib/render.ts. */
  readonly colors: Uint8Array | null;
  /**
   * Draw the analytical layer. Off is used by the rendering regression test, which
   * compares rendered output with the layer on against the same view with it off - a
   * check that the layer is *visible*, not merely populated.
   */
  readonly analyticalLayer?: boolean;
  readonly sites?: readonly SiteDatum[];
  /**
   * The chosen portfolio. Drawn as its own marker layer rather than a shade of the
   * eligible fill: at state zoom a recoloured hexagon is a few pixels, and "which 20 did
   * it pick" must be answerable in about a second.
   */
  readonly selected?: readonly SelectedDatum[];
  readonly initialViewState?: { longitude: number; latitude: number; zoom: number };
  /** Reports the map's zoom so the view can pick a display resolution (lib/aggregate.ts). */
  readonly onZoom?: (zoom: number) => void;
  /** Index of the hovered cell in `boundaries`, or null. Drives the shared feature card. */
  readonly onHoverCell?: (index: number | null, x: number, y: number) => void;
  /** Index of the clicked cell, which pins the card and syncs any table. */
  readonly onPickCell?: (index: number | null) => void;
  /** Index of the hovered selected marker, for map-to-table highlighting. */
  readonly onHoverSelected?: (rank: number | null, x: number, y: number) => void;
  readonly onPickSelected?: (rank: number | null) => void;
  /** Rank currently highlighted from the table, outlined on the map. */
  readonly highlightRank?: number | null;
  /** Camera target; changing it flies the map there. */
  readonly focus?: { longitude: number; latitude: number; zoom: number } | null;
}

function BasemapWarning() {
  return (
    <div
      style={{
        position: "absolute", top: "0.75rem", left: "0.75rem", zIndex: 6,
        background: "rgba(23,26,33,0.94)", border: "1px solid var(--warn)",
        borderRadius: "var(--radius)", padding: "0.5rem 0.7rem",
        fontSize: "0.75rem", color: "var(--warn)", maxWidth: "34ch",
      }}
    >
      Basemap unavailable. The data layer below is complete and correct; only the
      geographic context is missing.
    </div>
  );
}

const DEFAULT_VIEW = { longitude: -98.6, latitude: 39.8, zoom: 3.4 };

export default function HexMap({
  boundaries,
  colors,
  sites,
  selected,
  analyticalLayer = true,
  initialViewState = DEFAULT_VIEW,
  onZoom,
  onHoverCell,
  onPickCell,
  onHoverSelected,
  onPickSelected,
  highlightRank = null,
  focus = null,
}: HexMapProps) {
  const container = useRef<HTMLDivElement | null>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const overlay = useRef<MapboxOverlay | null>(null);
  const sizeObserver = useRef<ResizeObserver | null>(null);
  // Held in a ref so the mount-once effect never needs it as a dependency.
  const onZoomRef = useRef(onZoom);
  onZoomRef.current = onZoom;
  const handlers = useRef({ onHoverCell, onPickCell, onHoverSelected, onPickSelected });
  handlers.current = { onHoverCell, onPickCell, onHoverSelected, onPickSelected };
  /** Whether the analytical layer answers a pointer — a boolean, so it is a stable dep. */
  const pickable = onHoverCell !== undefined || onPickCell !== undefined;
  const [basemapFailed, setBasemapFailed] = useState(false);

  useEffect(() => {
    const node = container.current;
    if (node === null || map.current !== null) return;

    // Do not create the map until the container has real layout.
    //
    // The map sits in a CSS grid column that resolves after first paint, and the view
    // renders a "Loading map..." placeholder before it. Creating the WebGL context against
    // that intermediate box left deck.gl's drawing buffer stuck at 34x420 - the
    // placeholder's size - for the life of the page, so the analytical layer drew into a
    // narrow strip while the basemap, which tracks its container independently, looked
    // correct. Neither `map.resize()` nor `deck.setProps({width, height})` recovered it.
    let cancelled = false;
    let observer: ResizeObserver | null = null;

    const create = () => {
      if (cancelled || map.current !== null) return;
      buildMap(node);
    };

    if (node.clientWidth > 0 && node.clientHeight > 0) {
      create();
    } else {
      observer = new ResizeObserver(() => {
        if (node.clientWidth > 0 && node.clientHeight > 0) {
          observer?.disconnect();
          observer = null;
          create();
        }
      });
      observer.observe(node);
    }

    function buildMap(element: HTMLDivElement) {
    const instance = new maplibregl.Map({
      container: element,
      style: BASEMAP,
      center: [initialViewState.longitude, initialViewState.latitude],
      zoom: initialViewState.zoom,
      attributionControl: { compact: true },
    });
    instance.addControl(new maplibregl.NavigationControl({ showCompass: false }));
    if (onZoomRef.current) {
      const report = () => onZoomRef.current?.(instance.getZoom());
      instance.on("zoomend", report);
      instance.on("load", report);
    }
    instance.on("error", (event) => {
      // eslint-disable-next-line no-console
      console.warn("basemap:", event.error?.message ?? event);
      setBasemapFailed(true);
    });
    const deck = new MapboxOverlay({ interleaved: false, layers: [] });
    instance.addControl(deck);
    map.current = instance;
    overlay.current = deck;
    // Keep the drawing buffer in step with the container from here on.
    const resize = new ResizeObserver(() => instance.resize());
    resize.observe(element);
    sizeObserver.current = resize;
    // Exposed for the reproducible frame-rate benchmark, which needs to drive the camera
    // deterministically. Reading a handle is inert; nothing in the app uses it.
    (window as unknown as { __voltgapMap?: maplibregl.Map }).__voltgapMap = instance;
    }

    return () => {
      cancelled = true;
      observer?.disconnect();
      sizeObserver.current?.disconnect();
      sizeObserver.current = null;
      overlay.current?.finalize();
      map.current?.remove();
      map.current = null;
      overlay.current = null;
    };
    // Mount once. Recreating the map on a prop change would reset the user's pan.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (overlay.current === null) return;
    const layers = [];
    if (analyticalLayer && boundaries !== null && colors !== null) {
      layers.push(
        new SolidPolygonLayer({
          id: "hex6",
          data: {
            length: boundaries.length,
            startIndices: boundaries.startIndices,
            attributes: {
              getPolygon: { value: boundaries.positions, size: 2 },
              getFillColor: { value: colors, size: 4, normalized: false },
            },
          },
          positionFormat: "XY",
          extruded: false,
          filled: true,
          stroked: false,
          // Picking is what turns the surface from a picture into something explorable:
          // a reader can ask any cell where it is and what its value means.
          pickable,
          onHover: (info) =>
            handlers.current.onHoverCell?.(
              info.index >= 0 ? info.index : null, info.x, info.y),
          onClick: (info) =>
            handlers.current.onPickCell?.(info.index >= 0 ? info.index : null),
        }),
      );
    }
    if (selected && selected.length > 0) {
      layers.push(
        new ScatterplotLayer<SelectedDatum>({
          id: "selected-halo",
          data: selected as SelectedDatum[],
          getPosition: (d) => [d.longitude, d.latitude],
          getFillColor: [255, 193, 61, 70],
          getRadius: 9000,
          radiusMinPixels: 16, radiusMaxPixels: 44, stroked: false,
        }),
        new ScatterplotLayer<SelectedDatum>({
          id: "selected",
          data: selected as SelectedDatum[],
          getPosition: (d) => [d.longitude, d.latitude],
          getFillColor: (d) =>
            d.rank === highlightRank ? [255, 255, 255, 255] : [255, 193, 61, 255],
          getLineColor: (d) =>
            d.rank === highlightRank ? [255, 193, 61, 255] : [26, 24, 18, 230],
          getRadius: (d) => (d.rank === highlightRank ? 7000 : 4200),
          radiusMinPixels: 10, radiusMaxPixels: 24,
          stroked: true, lineWidthMinPixels: 2,
          pickable: true,
          onHover: (info) =>
            handlers.current.onHoverSelected?.(
              info.object ? (info.object as SelectedDatum).rank : null, info.x, info.y),
          onClick: (info) =>
            handlers.current.onPickSelected?.(
              info.object ? (info.object as SelectedDatum).rank : null),
          updateTriggers: {
            getFillColor: highlightRank, getLineColor: highlightRank,
            getRadius: highlightRank,
          },
        }),
        // Rank labels, so "which dot is candidate #4" is answerable by looking.
        new TextLayer<SelectedDatum>({
          id: "selected-rank",
          data: selected as SelectedDatum[],
          getPosition: (d) => [d.longitude, d.latitude],
          getText: (d) => String(d.rank),
          getColor: [26, 24, 18, 255],
          getSize: 11,
          sizeUnits: "pixels",
          fontWeight: 700,
          getTextAnchor: "middle",
          getAlignmentBaseline: "center",
          pickable: false,
        }),
      );
    }
    if (sites && sites.length > 0) {
      layers.push(
        new ScatterplotLayer<SiteDatum>({
          id: "sites",
          data: sites as SiteDatum[],
          getPosition: (d) => [d.longitude, d.latitude],
          getFillColor: (d) =>
            d.serves_dcfc ? [79, 191, 127, 200] : [154, 163, 178, 130],
          getRadius: (d) => (d.serves_dcfc ? 900 : 500),
          radiusMinPixels: 1.2,
          radiusMaxPixels: 5,
          stroked: false,
        }),
      );
    }
    overlay.current.setProps({ layers });
    // Published so the frame-rate benchmark can assert it is measuring a full layer
    // rather than an empty map, which would otherwise hit vsync trivially. This counts
    // cells HANDED to the layer, which this defect showed is not the same as cells
    // DRAWN - the rendering regression test covers that separately.
    (window as unknown as { __voltgapLayerCells?: number }).__voltgapLayerCells =
      analyticalLayer ? (boundaries?.length ?? 0) : 0;
    // `onHoverCell` / `onPickCell` are deliberately NOT dependencies.
    //
    // They arrive as inline arrow functions, so they are new objects on every render of
    // the parent — and the national view re-renders on every zoom change, which during a
    // pan is every frame. Listing them here rebuilt all three layers and re-uploaded the
    // 370,384-vertex buffer once per frame, which measured 26.3 fps against a 60.0 fps
    // baseline on the same machine. The callbacks are read through `handlers.current`,
    // which is refreshed on every render, so the layer always calls the current one; only
    // WHETHER picking is enabled can change what the layer must be rebuilt for.
  }, [boundaries, colors, sites, selected, analyticalLayer, highlightRank, pickable]);

  // Fly to a place chosen elsewhere on the page — a table row, or a regional summary.
  useEffect(() => {
    if (map.current === null || focus === null) return;
    map.current.easeTo({
      center: [focus.longitude, focus.latitude], zoom: focus.zoom, duration: 700,
    });
  }, [focus]);

  return (
    <>
      <div ref={container} style={{ position: "absolute", inset: 0 }} />
      {basemapFailed && <BasemapWarning />}
    </>
  );
}
