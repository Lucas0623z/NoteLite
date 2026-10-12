export const PROFILE_STORAGE_PREFIX = "notelite-profile-v1:";
export const PROFILE_ORIGIN = "https://124.221.211.156";
export const profileStorageKey = (owner: string, origin = PROFILE_ORIGIN) => `${PROFILE_STORAGE_PREFIX}${encodeURIComponent(origin)}:${owner}`;
export function purgeProfileStorage(owner: string, storage: Storage | undefined = typeof localStorage === "undefined" ? undefined : localStorage): void {
  if (!storage) return;
  const keys: string[] = [];
  for (let index = 0; index < storage.length; index++) { const key = storage.key(index); if (key?.startsWith(PROFILE_STORAGE_PREFIX) && key.endsWith(`:${owner}`)) keys.push(key); }
  for (const key of keys) storage.removeItem(key);
}
