import { paidActionTokens, paidRootTokens, releaseFeatures } from "./release-features.ts";

export class PurchaseUnavailableError extends Error {
  readonly code = "purchase_unavailable";
  constructor() { super(releaseFeatures.purchaseUnavailableMessage); this.name = "PurchaseUnavailableError"; }
}

export function isPaidRequest(action: string, payload: unknown = {}): boolean {
  const paid = (value: string) => {
    const components = value.toLowerCase().split(/[?#]/, 1)[0].split("/").filter(Boolean);
    while (["api", "account"].includes(components[0])) components.shift();
    return components.some(part => paidActionTokens.includes(part)) || paidRootTokens.includes(components[0]);
  };
  const path = payload && typeof payload === "object" ? (payload as { path?: unknown }).path : undefined;
  return paid(action) || (typeof path === "string" && paid(path));
}

export function requireAllowedRequest(action: string, payload: unknown = {}): void {
  if (!releaseFeatures.inAppPurchases && isPaidRequest(action, payload)) throw new PurchaseUnavailableError();
}

/** Transaction/entitlement mutation must sit behind this gate, including direct calls. */
export async function performPurchase<T>(transaction: () => T | Promise<T>): Promise<T> {
  if (!releaseFeatures.inAppPurchases) throw new PurchaseUnavailableError();
  return transaction();
}

export function requestPurchase(): Promise<never> {
  // This release ships no StoreKit or external-payment adapter, including if
  // a future release edits its flag before its transaction work is complete.
  return performPurchase(() => { throw new PurchaseUnavailableError(); });
}

export const isPurchaseEntry = (title: string) => ["订购", "挑选套餐", "恢复订购"].includes(title);
