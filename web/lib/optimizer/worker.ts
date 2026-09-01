/**
 * The greedy solver, in a Web Worker.
 *
 * §11.3 budgets a state-level re-solve at 2 seconds. Running it on the main thread would
 * meet that number and still freeze the interface while sliders move, so it runs here and
 * the page stays responsive. The worker owns the candidate set between solves, so a slider
 * move sends two numbers rather than re-posting the whole state.
 */

import { greedySelect, type Candidate, type Coverage, type Weights } from "./greedy";

export interface LoadMessage {
  readonly kind: "load";
  readonly candidates: Candidate[];
  readonly coverage: [string, string[]][];
}

export interface SolveMessage {
  readonly kind: "solve";
  readonly budget: number;
  readonly weights: Weights;
}

export type Incoming = LoadMessage | SolveMessage;

export interface SolvedMessage {
  readonly kind: "solved";
  readonly selected: string[];
  readonly demandCovered: number;
  readonly equityCovered: number;
  readonly populationCovered: number;
  readonly elapsedMs: number;
  readonly candidates: number;
}

export interface FailedMessage {
  readonly kind: "failed";
  readonly message: string;
}

export type Outgoing = SolvedMessage | FailedMessage;

let candidates: Candidate[] = [];
let coverage: Coverage = new Map();

self.onmessage = (event: MessageEvent<Incoming>) => {
  const message = event.data;
  try {
    if (message.kind === "load") {
      candidates = message.candidates;
      coverage = new Map(message.coverage);
      return;
    }
    const result = greedySelect(candidates, coverage, message.budget, message.weights);
    const payload: SolvedMessage = {
      kind: "solved",
      selected: [...result.selected],
      demandCovered: result.demandCovered,
      equityCovered: result.equityCovered,
      populationCovered: result.populationCovered,
      elapsedMs: result.elapsedMs,
      candidates: candidates.length,
    };
    (self as unknown as Worker).postMessage(payload);
  } catch (error) {
    const payload: FailedMessage = {
      kind: "failed",
      message: error instanceof Error ? error.message : String(error),
    };
    (self as unknown as Worker).postMessage(payload);
  }
};
