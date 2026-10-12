export type PracticeOwner = { owner: string; sessionId: string | null };
type Identity = { userId: string; sessionId?: string } | null;

/** Copy the identity before permission prompts, hashing or native capture starts. */
export function capturePracticeOwner(identity: Identity): PracticeOwner {
  return { owner: identity?.userId || "guest", sessionId: identity?.sessionId || null };
}

export function requirePracticeOwner(captured: PracticeOwner, identity: Identity): void {
  const current = capturePracticeOwner(identity);
  if (current.owner !== captured.owner || current.sessionId !== captured.sessionId) {
    throw new Error("账户或登录会话已更改，本次输入已停止。请重新开始练习。");
  }
}

/** An interrupted start never commits a take under the account seen afterward. */
export async function startOwnedPracticeInput<T>(
  captured: PracticeOwner, current: () => Identity,
  start: () => Promise<T>, stop: () => Promise<unknown>,
): Promise<T> {
  requirePracticeOwner(captured, current());
  try {
    const result = await start();
    requirePracticeOwner(captured, current());
    return result;
  } catch (error) {
    // Stop clears the original input's event receiver even if the native account
    // already changed and its strict ownership guard rejects an old stop request.
    try { await stop(); } catch { /* Preserve the start/identity error. */ }
    throw error;
  }
}
