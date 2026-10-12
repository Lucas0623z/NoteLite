import { useEffect, useSyncExternalStore } from "react";
import { account } from "./account.ts";
import { AccountProfileStore, type ProfileIdentity } from "./profile-store.ts";
import { defaultPreferences, type ProfileChanges } from "./profile-model.ts";
const store = new AccountProfileStore(account);
export function useAccountProfile(identity: ProfileIdentity | null) {
  const snapshot = useSyncExternalStore(store.subscribe, store.getSnapshot);
  const user = identity?.userId || "guest", session = identity?.sessionId || "guest";
  useEffect(() => { void store.bind(identity); }, [user, session]);
  useEffect(() => {
    const sync = () => void store.sync();
    const visible = () => { if (document.visibilityState === "visible") sync(); };
    window.addEventListener("online", sync); window.addEventListener("focus", sync); document.addEventListener("visibilitychange", visible);
    return () => { window.removeEventListener("online", sync); window.removeEventListener("focus", sync); document.removeEventListener("visibilitychange", visible); };
  }, []);
  useEffect(() => {
    if (snapshot.status !== "pending" || snapshot.message !== "已保存到本机，等待账户同步。") return;
    const timer = window.setTimeout(() => void store.sync(), 600);
    return () => window.clearTimeout(timer);
  }, [snapshot]);
  const matched = snapshot.owner === user && snapshot.scope.includes(`|${user}|${session}|`);
  const current = matched ? snapshot : { ...snapshot, owner: user, preferences: defaultPreferences(), status: "loading" as const, message: "正在读取当前账户个人设置。" };
  return { ...current, change: (changes: ProfileChanges) => store.patch(changes, matched ? snapshot.scope : ""), retry: () => store.sync() };
}
