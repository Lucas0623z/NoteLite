import { CloudError, createUUID } from "./cloud.ts";
import { isDeletedAccountOwner } from "./account-local-data.ts";
import { defaultPreferences, mergePreferences, mergeProfileChanges, validateAccountProfile, validateProfileChanges, PROFILE_COURSES, PROFILE_OPTIONS, type AccountProfile, type ProfileChanges, type ProfilePreferences } from "./profile-model.ts";
import { profileStorageKey, PROFILE_ORIGIN } from "./profile-storage.ts";
export type ProfileIdentity = { userId: string; sessionId: string };
type ProfileAPI = { readonly current: ProfileIdentity | null; profile(): Promise<AccountProfile>; updateProfile(etag: string, changes: ProfileChanges, requestId: string): Promise<AccountProfile> };
type Pending = { requestId: string; etag: string; changes: ProfileChanges };
type Persisted = { version: 1; owner: string; envelope: AccountProfile | null; dirty: ProfileChanges; pending: Pending | null; guest?: ProfilePreferences };
export type ProfileSnapshot = { owner: string; scope: string; preferences: ProfilePreferences; status: "guest" | "loading" | "synced" | "pending" | "unavailable" | "error"; message: string };
export class AccountProfileStore {
  private generation = 0;
  private identity: ProfileIdentity | null = null;
  private data: Persisted = { version: 1, owner: "guest", envelope: null, dirty: {}, pending: null };
  private listeners = new Set<() => void>();
  private flights = new Map<number, Promise<void>>();
  private snapshot: ProfileSnapshot = { owner: "guest", scope: "", preferences: defaultPreferences(), status: "loading", message: "正在读取个人设置。" };
  private api: ProfileAPI;
  private storage: Storage | undefined;
  private uuid: () => string;
  private origin: string;
  constructor(api: ProfileAPI, storage: Storage | undefined = typeof localStorage === "undefined" ? undefined : localStorage, uuid: () => string = createUUID, origin = PROFILE_ORIGIN) { this.api = api; this.storage = storage; this.uuid = uuid; this.origin = origin; }
  getSnapshot = (): ProfileSnapshot => this.snapshot;
  subscribe = (listener: () => void): (() => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener); };
  private scope() { return `${this.origin}|${this.identity?.userId || "guest"}|${this.identity?.sessionId || "guest"}|${this.generation}`; }
  private current(generation: number): boolean { return generation === this.generation && !isDeletedAccountOwner(this.data.owner) && (!this.identity || this.api.current?.userId === this.identity.userId && this.api.current?.sessionId === this.identity.sessionId); }
  private view(status: ProfileSnapshot["status"], message: string) {
    const base = this.data.guest || this.data.envelope?.preferences || defaultPreferences();
    this.snapshot = { owner: this.data.owner, scope: this.scope(), preferences: mergePreferences(mergePreferences(base, this.data.pending?.changes || {}), this.data.dirty), status, message };
    for (const listener of this.listeners) listener();
  }
  private persist() {
    if (isDeletedAccountOwner(this.data.owner)) throw new Error("账户已注销，不能保存个人资料。");
    if (!this.storage) throw new Error("本机存储不可用，个人设置尚未保存。");
    this.storage.setItem(profileStorageKey(this.data.owner, this.origin), JSON.stringify(this.data));
  }
  private load(owner: string): Persisted {
    if (isDeletedAccountOwner(owner)) return { version: 1, owner, envelope: null, dirty: {}, pending: null };
    const raw = this.storage?.getItem(profileStorageKey(owner, this.origin));
    if (raw) {
      const value = JSON.parse(raw) as Persisted;
      if (value.version !== 1 || value.owner !== owner) throw new Error("本机个人设置归属无效。");
      value.dirty = validateProfileChanges(value.dirty);
      if (value.envelope) value.envelope = validateAccountProfile(value.envelope, owner);
      if (value.pending) {
        if (!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value.pending.requestId) || !/^"profile-\d+"$/.test(value.pending.etag)) throw new Error("本机待同步设置无效。");
        value.pending.changes = validateProfileChanges(value.pending.changes);
      }
      if (owner === "guest" && value.guest) value.guest = mergePreferences(defaultPreferences(), validateProfileChanges(value.guest));
      return value;
    }
    const data: Persisted = { version: 1, owner, envelope: null, dirty: {}, pending: null };
    // Legacy unowned preferences remain guest data; a later login never claims them.
    if (owner === "guest" && this.storage) {
      const options: Record<string, boolean> = {};
      try { const old = JSON.parse(this.storage.getItem("music-settings") || "{}"); for (const key of PROFILE_OPTIONS) if (typeof old?.[key] === "boolean") options[key] = old[key]; } catch { /* Keep known defaults. */ }
      const course = this.storage.getItem("music-selected-course");
      const name = this.storage.getItem("music-display-name") || "名字";
      data.guest = { ...defaultPreferences(), displayName: Array.from(name).slice(0, 30).join(""), avatar: this.storage.getItem("music-avatar") === "portrait" ? "portrait" : "mascot", selectedCourse: course && PROFILE_COURSES.includes(course) ? course : null, theme: this.storage.getItem("sheet-music-theme") === "dark" ? "dark" : "light", options };
    }
    return data;
  }
  async bind(identity: ProfileIdentity | null): Promise<void> {
    this.generation++; this.identity = identity ? { ...identity } : null;
    const owner = identity?.userId || "guest";
    try { this.data = this.load(owner); }
    catch { this.data = { version: 1, owner, envelope: null, dirty: {}, pending: null }; this.view("error", "本机个人设置无法读取，请重试。原存储已保留。"); return; }
    this.view(identity ? "loading" : "guest", identity ? "正在读取账户个人设置。" : "访客设置仅保存在本机。");
    if (identity) await this.sync();
  }
  patch(changes: ProfileChanges, expectedScope: string): void {
    if (expectedScope !== this.scope() || !this.current(this.generation)) throw new CloudError("账户已切换，请重新修改个人设置。", 409);
    changes = validateProfileChanges(changes);
    const before = this.data;
    if (this.identity) this.data = { ...this.data, dirty: mergeProfileChanges(this.data.dirty, changes) };
    else this.data = { ...this.data, guest: mergePreferences(this.data.guest || defaultPreferences(), changes) };
    try { this.persist(); }
    catch (error) { this.data = before; this.view("error", error instanceof Error ? error.message : "个人设置尚未保存。"); throw error; }
    this.view(this.identity ? "pending" : "guest", this.identity ? "已保存到本机，等待账户同步。" : "访客设置仅保存在本机。");
  }
  sync(): Promise<void> {
    const generation = this.generation;
    if (!this.identity || !this.current(generation)) return Promise.resolve();
    const existing = this.flights.get(generation); if (existing) return existing;
    const flight = this.performSync(generation).finally(() => this.flights.delete(generation));
    this.flights.set(generation, flight); return flight;
  }
  private async performSync(generation: number): Promise<void> {
    let conflicts = 0;
    let replaying = !!this.data.pending;
    try {
      // An uncertain PUT must be replayed unchanged before a new read/edit batch.
      if (!this.data.pending) {
        const remote = validateAccountProfile(await this.api.profile(), this.data.owner);
        if (!this.current(generation)) return;
        this.data = { ...this.data, envelope: remote }; this.persist();
      }
      while (this.current(generation)) {
        if (!this.data.pending) {
          if (!Object.keys(this.data.dirty).length) { this.view("synced", "已同步到当前账户。"); return; }
          if (!this.data.envelope) throw new Error("请先读取账户个人设置。");
          this.data = { ...this.data, pending: { requestId: this.uuid(), etag: this.data.envelope.etag, changes: this.data.dirty }, dirty: {} }; this.persist();
        }
        const pending = this.data.pending!;
        try {
          const response = await this.api.updateProfile(pending.etag, pending.changes, pending.requestId);
          if (!this.current(generation)) return;
          const envelope = validateAccountProfile(response, this.data.owner);
          this.data = { ...this.data, envelope, pending: null }; this.persist(); this.view("pending", "正在同步个人设置。");
          if (replaying) {
            // A receipt can predate another device's write. Keep its exact replay,
            // then read the current profile before claiming that we are synced.
            const latest = validateAccountProfile(await this.api.profile(), this.data.owner);
            if (!this.current(generation)) return;
            this.data = { ...this.data, envelope: latest }; this.persist(); replaying = false;
          }
        } catch (error) {
          if (!this.current(generation)) return;
          if (!(error instanceof CloudError) || error.status !== 412 || ++conflicts > 3) throw error;
          // Only our edited fields survive a conflict; other-device fields use GET.
          const remote = validateAccountProfile(await this.api.profile(), this.data.owner);
          if (!this.current(generation)) return;
          this.data = { ...this.data, envelope: remote, dirty: mergeProfileChanges(pending.changes, this.data.dirty), pending: null }; this.persist();
        }
      }
    } catch (error) {
      if (!this.current(generation)) return;
      if (error instanceof CloudError && error.status === 404) this.view("unavailable", "个人设置已保留在本机，云端同步服务待更新。");
      else this.view(Object.keys(this.data.dirty).length || this.data.pending ? "pending" : "error", "个人设置同步未完成，本机修改已保留；联网后重试。");
    }
  }
}
