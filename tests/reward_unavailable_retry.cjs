// Deterministic Mini App boundary: real generated script, fake DOM/ad/API only.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync(0, "utf8");
const listeners = [];
const button = {
  disabled: false,
  hidden: false,
  textContent: "",
  onclick: null,
  addEventListener(event, callback) {
    assert.equal(event, "click");
    listeners.push(callback);
  },
  async click() {
    assert.equal(this.disabled, false);
    // Both forms are dispatched by a real browser. Keeping both here detects
    // accidentally retaining the old ad listener when replacing onclick.
    const handlers = [...listeners];
    if (this.onclick) handlers.push(this.onclick);
    await Promise.all(handlers.map((handler) => handler()));
  },
};
const statusBox = { textContent: "" };
let ads = 0;
let claims = 0;
const context = {
  window: {
    Telegram: { WebApp: { ready() {}, expand() {}, close() {}, initData: "signed-test" } },
    Adsgram: { init() { return { async show() { ads += 1; } }; } },
  },
  document: { getElementById(id) { return id === "watch" ? button : statusBox; } },
  async fetch(url, options) {
    assert.match(url, /^\/api\/rewards\/.+\/claim$/);
    assert.equal(options.method, "POST");
    claims += 1;
    const unavailable = claims === 1;
    return {
      status: unavailable ? 409 : 200,
      async json() {
        return unavailable
          ? { status: "unavailable", reward_retained: true, detail: "earned credit retained" }
          : { status: "delivered", telegram_message_id: 123 };
      },
    };
  },
  setTimeout(callback, delay) {
    assert.equal(delay, 1200, "unexpected polling instead of unavailable handling");
    return 0;
  },
};

(async () => {
  vm.runInNewContext(source, context);
  assert.equal(ads, 0);
  assert.equal(claims, 0);
  await button.click();
  assert.equal(ads, 1, "initial pending request must complete one ad");
  assert.equal(claims, 1, "unavailable response must stop the first claim path");
  assert.equal(button.disabled, false);
  assert.equal(statusBox.textContent, "earned credit retained");
  await button.click();
  assert.equal(ads, 1, "retained-credit retry must not display another ad");
  assert.equal(claims, 2, "retry must invoke exactly one claim path");
  assert.match(statusBox.textContent, /تم التحقق وإرسال الفيلم/);
  process.stdout.write("PASS: pending -> one ad -> unavailable409 -> retry; one ad and two total claims\n");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
