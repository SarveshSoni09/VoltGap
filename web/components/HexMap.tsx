"use client";

import { ScatterplotLayer, SolidPolygonLayer } from "@deck.gl/layers";
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
 * polygon start indices, computed in a worker, and colours as a `Uint8Array`. deck.gl
 * uploads both straight to the GPU without walking 53,208 objects. That is what the
 * sustained frame-rate budget needs, and it is why this uses `SolidPolygonLayer` from
 * `@deck.gl/layers` rather than `H3HexagonLayer` from the much larger
 * `@deck.gl/geo-layers` - the latter's job is precisely the conversion the worker does.
 *
 * The basemap is **OpenFreeMap**, which needs no key (§2: "No keyed provider"). §12 records
 * that it is a single point of failure and that a self-hosted Protomaps fallback belongs on
 * R2; that fallback is Phase 7 infrastructure. Until it exists, a basemap failure is
 * surfaced rather than swallowed: the data layer still renders, and the page says the
 * geographic context is missing instead of showing an empty country.
 */
const BASEMAP = "https://tiles.openfreemap.org/styles/positron";

export interface SiteDatum {
  readonly longitude: number;
  readonly latitude: number;
  readonly serves_dcfc: boolean;
}

export interface HexMapProps {
  readonly boundaries: Boundaries | null;
  /** RGBA per cell, length = boundaries.length * 4. */
  readonly colors: Uint8Array | null;
  readonly sites?: readonly SiteDatum[];
  readonly initialViewState?: { longitude: number; latitude: number; zoom: number };
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
  initialViewState = DEFAULT_VIEW,
}: HexMapProps) {
  const container = useRef<HTMLDivElement | null>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const overlay = useRef<MapboxOverlay | null>(null);
  const [basemapFailed, setBasemapFailed] = useState(false);

  useEffect(() => {
    if (container.current === null || map.current !== null) return;
    const instance = new maplibregl.Map({
      container: container.current,
      style: BASEMAP,
      center: [initialViewState.longitude, initialViewState.latitude],
      zoom: initialViewState.zoom,
      attributionControl: { compact: true },
    });
    instance.addControl(new maplibregl.NavigationControl({ showCompass: false }));
    instance.on("error", (event) => {
      // eslint-disable-next-line no-console
      console.warn("basemap:", event.error?.message ?? event);
      setBasemapFailed(true);
    });
    const deck = new MapboxOverlay({ interleaved: false, layers: [] });
    instance.addControl(deck);
    map.current = instance;
    overlay.current = deck;
    // Exposed for the reproducible frame-rate benchmark, which needs to drive the camera
    // deterministically. Reading a handle is inert; nothing in the app uses it.
    (window as unknown as { __voltgapMap?: maplibregl.Map }).__voltgapMap = instance;
    return () => {
      deck.finalize();
      instance.remove();
      map.current = null;
      overlay.current = null;
    };
    // Mount once. Recreating the map on a prop change would reset the user's pan.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (overlay.current === null) return;
    const layers = [];
    if (boundaries !== null && colors !== null) {
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
          _normalize: false,
          positionFormat: "XY",
          extruded: false,
          filled: true,
          stroked: false,
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
    // rather than an empty map, which would otherwise hit vsync trivially.
    (window as unknown as { __voltgapLayerCells?: number }).__voltgapLayerCells =
      boundaries?.length ?? 0;
  }, [boundaries, colors, sites]);

  return (
    <>
      <div ref={container} style={{ position: "absolute", inset: 0 }} />
      {basemapFailed && <BasemapWarning />}
    </>
  );
}
