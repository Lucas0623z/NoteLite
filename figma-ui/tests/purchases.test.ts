import test from "node:test";
import assert from "node:assert/strict";
import { AccountClient, type AccountRequest } from "../src/app/account.ts";
import { nativeRequest } from "../src/app/cloud.ts";
import { isPaidRequest, performPurchase, PurchaseUnavailableError, requestPurchase, requireAllowedRequest } from "../src/app/purchases.ts";
import { releaseFeatures } from "../src/app/release-features.ts";

test("compiled test release rejects direct transaction and entitlement callbacks", async () => {
  assert.equal(releaseFeatures.inAppPurchases, false);
  assert.equal(Object.isFrozen(releaseFeatures), true);
  assert.throws(() => Object.assign(releaseFeatures, { inAppPurchases: true }));
  let calls = 0;
  await assert.rejects(performPurchase(() => { calls++; return { success: true, entitlement: "premium" }; }), PurchaseUnavailableError);
  await assert.rejects(requestPurchase(), { code: "purchase_unavailable", message: "测试期未开放" });
  assert.equal(calls, 0);
});

test("paid native actions and disguised account paths never reach the real message handler", async () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "window");
  let calls = 0;
  Object.defineProperty(globalThis, "window", { configurable: true, value: { webkit: { messageHandlers: { noteLiteCloud: { postMessage() { calls++; } } } } } });
  try {
    for (const [action, payload] of [
      ["iap/purchase", {}], ["membership/restore", {}], ["store/checkout", {}], ["coins/topup", {}],
      ["account/request", { path: "/api/account/subscriptions?plan=pro" }],
      ["account/request", { path: "/payments" }],
    ] as const) await assert.rejects(nativeRequest(action, payload), PurchaseUnavailableError);
    assert.equal(calls, 0);
  } finally {
    if (previous) Object.defineProperty(globalThis, "window", previous);
    else Reflect.deleteProperty(globalThis, "window");
  }
});

test("paid browser or custom native account requests cannot fetch, discover a session or bridge", async () => {
  for (const native of [false, true]) {
    let calls = 0;
    const client = new AccountClient(async () => { calls++; return new Response("{}"); }, () => native,
      (async () => { calls++; return {}; }) as never, () => {});
    const direct = client as unknown as { request(input: AccountRequest): Promise<unknown> };
    for (const path of ["/billing/checkout", "/membership", "/coins/purchase", "/store/restore"]) {
      await assert.rejects(direct.request({ path, method: "POST", response: "json" }), PurchaseUnavailableError);
    }
    assert.equal(calls, 0);
  }
});

test("free practice, cloud OMR, account registration and classroom membership stay allowed", () => {
  for (const [action, payload] of [
    ["notewise/start", {}], ["notewise/refine", {}], ["jobs/create", {}], ["notes/patch", {}],
    ["account/request", { path: "/register" }], ["account/request", { path: "/history?limit=200" }],
    ["account/request", { path: "/courses/11111111-1111-4111-8111-111111111111/membership" }],
    ["account/request", { path: "/assignments/11111111-1111-4111-8111-111111111111/submissions" }],
  ] as const) {
    assert.equal(isPaidRequest(action, payload), false);
    assert.doesNotThrow(() => requireAllowedRequest(action, payload));
  }
});
