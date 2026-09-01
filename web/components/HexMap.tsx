"use client";

import { H3HexagonLayer } from "@deck.gl/geo-layers";
import { ScatterplotLayer } from "@deck.gl/layers";
import { MapboxOverlay } from "@deck.gl/mapbox";
import maplibregl from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

import "maplibre-gl/dist/maplibre-gl.css";

/**
 * The map. Imported dynamically by every view that uses it, so deck.gl and MapLibre stay
 * out of the app shell and the §11.3 600 KB shell budget is met by construction rather
 * than by hoping the bundler splits them.
 *
 * The basemap is **OpenFreeMap**, which needs no key (§2: "No keyed provider"). §12 records
 * that it is a single point of failure and that a self-hosted Protomaps fallback belongs on
 * R2; that fallback is Phase 7 infrastructure, and its absence is recorded rather than
 * papered over - if the basemap fails to load the data layer still renders.
 */
const BASEMAP = "https://tiles.openfreemap.org/styles/positron";

export interface HexDatum {
  readonly h3_index: string;
  readonly color: [number, number, number, number];
  readonly value: number;
  readonly tier: string;
}

export interface SiteDatum {
  readonly longitude: number;
  readonly latitude: number;
  readonly serves_dcfc: boolean;
}

export interface HexMapProps {
  readonly hexes: readonly HexDatum[];
  readonly sites?: readonly SiteDatum[];
  readonly highlighted?: ReadonlySet<string>;
  readonly onHover?: (datum: HexDatum | null) => void;
  readonly initialViewState?: { longitude: number; latitude: number; zoom: number };
}

/**
 * Whether the basemap failed. §12 records that OpenFreeMap's public instance is a single
 * point of failure and that a self-hosted fallback belongs on R2 - that fallback is Phase 7
 * infrastructure. Until it exists, a basemap failure must be *visible*: the data layer
 * still renders on its own, and a user needs to know they are looking at cells without
 * geographic context rather than at an empty country.
 */
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
  hexes,
  sites,
  highlighted,
  onHover,
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
      // Style or tile failure. Reported, never swallowed: the map would otherwise show an
      // empty country and look like a data problem.
      // eslint-disable-next-line no-console
      console.warn("basemap:", event.error?.message ?? event);
      setBasemapFailed(true);
    });
    const deck = new MapboxOverlay({ interleaved: false, layers: [] });
    instance.addControl(deck);
    map.current = instance;
    overlay.current = deck;
    return () => {
      deck.finalize();
      instance.remove();
      map.current = null;
      overlay.current = null;
    };
    // Mount once. View state changes are pushed through the map instance, not by
    // rebuilding it: recreating the map on every prop change would reset the user's pan.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (overlay.current === null) return;
    const layers = [
      new H3HexagonLayer<HexDatum>({
        id: "hex6",
        data: hexes as HexDatum[],
        getHexagon: (d) => d.h3_index,
        getFillColor: (d) =>
          highlighted && highlighted.size > 0
            ? highlighted.has(d.h3_index)
              ? [255, 214, 102, 245]
              : [d.color[0], d.color[1], d.color[2], 60]
            : d.color,
        getLineColor: [0, 0, 0, 0],
        extruded: false,
        stroked: false,
        filled: true,
        pickable: onHover !== undefined,
        onHover: onHover
          ? (info) => onHover((info.object as HexDatum | undefined) ?? null)
          : undefined,
        updateTriggers: { getFillColor: [hexes, highlighted] },
      }),
      ...(sites && sites.length > 0
        ? [
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
          ]
        : []),
    ];
    overlay.current.setProps({ layers });
  }, [hexes, sites, highlighted, onHover]);

  return (
    <>
      <div ref={container} style={{ position: "absolute", inset: 0 }} />
      {basemapFailed && <BasemapWarning />}
    </>
  );
}
