/** Re-export of the columnar store for tests, so `lib/data/table.ts` can keep its worker
 *  import at module scope without a test environment needing a Worker global. */
export { ColumnTable } from "./data/table";
