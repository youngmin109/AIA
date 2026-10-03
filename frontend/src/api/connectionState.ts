/** Consecutive polls that got no response at all before the console says it lost the server. */
export const CONNECTION_LOST_AFTER = 2

export type PollOutcome = 'ok' | 'http-error' | 'network-error'

/** An HTTP error still proves the local server answered, so only network failures count. */
export function nextConnectionFailures(previous: number, outcome: PollOutcome): number {
  return outcome === 'network-error' ? previous + 1 : 0
}

export function isConnectionLost(consecutiveFailures: number): boolean {
  return consecutiveFailures >= CONNECTION_LOST_AFTER
}

/** fetch() rejects with a TypeError when no response arrives; HTTP errors are plain Errors. */
export function pollOutcomeOf(error: unknown): PollOutcome {
  return error instanceof TypeError ? 'network-error' : 'http-error'
}
