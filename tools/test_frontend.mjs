// Headless test for index.html's UPLINK routing logic.
//
// Follows the repo's "extract runtime sections from index.html and run them in
// Node" pattern (CLAUDE.md): pulls the two PURE helpers out of the page source
// and asserts the brain-state -> endpoint / placeholder mapping. Verifies the
// load-bearing rule from the Codex review: route /ask ONLY when brain==ready,
// never silently speak a question back.
//
//   node tools/test_frontend.mjs
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");

function extract(re, label) {
  const m = html.match(re);
  if (!m) throw new Error(`could not find ${label} in index.html`);
  return m[0];
}

// uplinkEndpoint is one line; the others span to a brace at line start.
const src =
  extract(/function uplinkEndpoint\(brain\)\{[^\n]*\}/, "uplinkEndpoint") +
  "\n" +
  extract(/function uplinkPlaceholder\(brain\)\{[\s\S]*?\n\}/, "uplinkPlaceholder") +
  "\n" +
  extract(/function brainCaption\(brain, model\)\{[\s\S]*?\n\}/, "brainCaption") +
  "\nreturn { uplinkEndpoint, uplinkPlaceholder, brainCaption };";

const { uplinkEndpoint, uplinkPlaceholder, brainCaption } = new Function(src)();

let pass = 0;
const check = (cond, msg) => { assert.ok(cond, msg); pass++; };

// --- endpoint routing: /ask ONLY when ready ---------------------------------
check(uplinkEndpoint("ready") === "/ask", "ready -> /ask");
for (const s of ["offline", "pulling", "warming", "error", "none"]) {
  check(uplinkEndpoint(s) === "/speak", `${s} -> /speak (never silent /ask)`);
}

// --- placeholder copy reflects the mode -------------------------------------
check(uplinkPlaceholder("ready") === "ASK THE HEAD", "ready placeholder = ASK");
check(uplinkPlaceholder("warming").includes("LOADING"), "warming shows LOADING");
check(uplinkPlaceholder("pulling").includes("LOADING"), "pulling shows LOADING");
const off = uplinkPlaceholder("offline");
check(!off.includes("ASK") && !off.includes("LOADING"), "offline = literal speak copy");

// --- brainCaption: every brain state maps to a visible caption + kind --------
check(brainCaption("ready", "qwen2.5:3b").text.startsWith("BRAIN ONLINE"), "ready -> BRAIN ONLINE");
check(brainCaption("ready", "qwen2.5:3b").text.includes("qwen2.5:3b"), "ready caption names the model");
check(brainCaption("ready", null).text === "BRAIN ONLINE", "ready w/o model = no suffix");
check(brainCaption("warming").kind === "loading" && brainCaption("warming").text.includes("LOADING"), "warming -> loading");
check(brainCaption("offline").text === "BRAIN OFFLINE" && brainCaption("offline").kind === "offline", "offline mapping");
check(brainCaption("error").text === "BRAIN OFFLINE", "error -> visible offline caption (not silent)");
check(brainCaption("none").text === "UPLINK ONLINE", "none -> speech-only UPLINK ONLINE");

console.log(`ok - ${pass} frontend assertions passed`);
