import type maplibregl from "maplibre-gl";

declare global {
  interface Window {
    /** Set by HexMap for the reproducible frame-rate benchmark. Inert in the app. */
    __voltgapMap?: maplibregl.Map;
    /** Cells actually handed to the render layer, so the benchmark cannot pass on an
     *  empty map. Set by HexMap when the layer is built. */
    __voltgapLayerCells?: number;
  }
}
export {};
