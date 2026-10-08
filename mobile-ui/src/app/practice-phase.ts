/** Observe phase transitions without re-entering the finished handler through its own mutations. */
export function watchPracticePhase(readPhase: () => string | undefined, subscribe: (callback: () => void) => () => void, onFinished: () => void) {
  let active = true;
  let lastPhase = readPhase();
  const unsubscribe = subscribe(() => {
    if (!active) return;
    const phase = readPhase();
    if (phase === lastPhase) return;
    // Update before saving: a synchronous save can enqueue another observer notification.
    lastPhase = phase;
    if (phase === "finished") onFinished();
  });
  return () => { if (!active) return; active = false; unsubscribe(); };
}
