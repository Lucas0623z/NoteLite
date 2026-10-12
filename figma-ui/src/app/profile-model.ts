export type ProfilePreferences = { displayName: string; avatar: "mascot" | "portrait" | "custom"; avatarImage: string | null; email: string; phone: string; selectedCourse: string | null; theme: "light" | "dark"; options: Record<string, boolean> };
export type ProfileChanges = Partial<ProfilePreferences>;
export type AccountProfile = { userId: string; revision: number; etag: string; updatedAt: string | null; preferences: ProfilePreferences };
export const PROFILE_COURSES = ["弦乐-小提琴", "弦乐-中提琴", "弦乐-大提琴", "弦乐-低音提琴", "弦乐-竖琴", "打击乐-钢琴", "木管-长笛", "木管-单簧管", "木管-巴松管", "木管-双簧管", "铜管-圆号", "铜管-小号", "铜管-长号", "铜管-大号", "铜管-上低音号"];
export const PROFILE_OPTIONS = ["音效", "触觉反馈", "鼓励信息", "屏蔽其他应用", "信息收集", "分享练琴录音", ...["每日练琴提醒", "连胜提醒", "练习目标提醒", "周报提醒", "未打卡提醒", "新关注", "好友成就", "排位更新", "新功能", "优惠", "活动", "好友练习提醒", "好友邀请", "好友消息"].map(key => `通知-${key}`)];
export const defaultPreferences = (): ProfilePreferences => ({ displayName: "名字", avatar: "mascot", avatarImage: null, email: "", phone: "", selectedCourse: null, theme: "light", options: {} });
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
export function validateProfileChanges(value: unknown): ProfileChanges {
  if (!object(value) || Object.keys(value).some(key => !Object.prototype.hasOwnProperty.call(defaultPreferences(), key))) throw new Error("个人设置字段无效。");
  const result: ProfileChanges = {};
  for (const [key, item] of Object.entries(value)) {
    if (["displayName", "email", "phone"].includes(key)) {
      const limit = key === "displayName" ? 80 : key === "email" ? 254 : 40;
      if (typeof item !== "string" || Array.from(item).length > limit || /[\u0000-\u001f\u007f]/u.test(item)) throw new Error("个人资料文字无效或过长。");
    } else if (key === "avatar" && (typeof item !== "string" || !["mascot", "portrait", "custom"].includes(item))) throw new Error("头像选择无效。");
    else if (key === "avatarImage" && item !== null && (typeof item !== "string" || item.length > 196608 || !/^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/]+={0,2}$/.test(item))) throw new Error("头像图片无效或过大。");
    else if (key === "selectedCourse" && item !== null && (typeof item !== "string" || !PROFILE_COURSES.includes(item))) throw new Error("课程选择无效。");
    else if (key === "theme" && item !== "light" && item !== "dark") throw new Error("外观设置无效。");
    else if (key === "options" && (!object(item) || Object.keys(item).length > 200 || Object.entries(item).some(([name, enabled]) => !name || Array.from(name).length > 80 || /[\u0000-\u001f\u007f]/u.test(name) || ["__proto__", "prototype", "constructor"].includes(name) || typeof enabled !== "boolean"))) throw new Error("偏好开关无效。");
    Object.assign(result, { [key]: key === "options" ? { ...item as Record<string, boolean> } : item });
  }
  if (new TextEncoder().encode(JSON.stringify(result)).length > 256 * 1024) throw new Error("个人设置过大。");
  return result;
}
export function mergeProfileChanges(base: ProfileChanges, changes: ProfileChanges): ProfileChanges {
  return { ...base, ...changes, ...(base.options || changes.options ? { options: { ...base.options, ...changes.options } } : {}) };
}
export function mergePreferences(base: ProfilePreferences, changes: ProfileChanges): ProfilePreferences { return mergeProfileChanges(base, changes) as ProfilePreferences; }
export function validateAccountProfile(value: unknown, owner: string): AccountProfile {
  if (!object(value) || value.userId !== owner || !Number.isSafeInteger(value.revision) || Number(value.revision) < 0 || value.etag !== `"profile-${value.revision}"` || (value.updatedAt !== null && (typeof value.updatedAt !== "string" || !Number.isFinite(Date.parse(value.updatedAt)))) || !object(value.preferences)) throw new Error("个人设置响应不完整，请重试读取。");
  const changes = validateProfileChanges(value.preferences);
  if (Object.keys(changes).length !== Object.keys(defaultPreferences()).length) throw new Error("个人设置响应不完整，请重试读取。");
  const preferences = mergePreferences(defaultPreferences(), changes);
  return { userId: owner, revision: Number(value.revision), etag: String(value.etag), updatedAt: value.updatedAt as string | null, preferences };
}
