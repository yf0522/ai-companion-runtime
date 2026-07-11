import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import ts from "typescript";

const source = fs.readFileSync(new URL("../lib/toolLabels.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ESNext,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;
const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`;
const {
  resolveToolFamily,
  toolChipCopy,
  toolChipTarget,
  toolGroupLabel,
} = await import(moduleUrl);

test("maps wire and legacy tool names to the three Pi families", () => {
  assert.equal(resolveToolFamily("memory"), "memory");
  assert.equal(resolveToolFamily("caretask"), "caretask");
  assert.equal(resolveToolFamily("utility"), "utility");
  assert.equal(resolveToolFamily("reminder"), "caretask");
  assert.equal(resolveToolFamily("weather"), "utility");
  assert.equal(resolveToolFamily("calculator"), "utility");
  assert.equal(resolveToolFamily("search"), "utility");
});

test("chip copy exposes memory / caretask / utility labels", () => {
  assert.match(toolChipCopy("memory").name, /memory/i);
  assert.match(toolChipCopy("caretask").name, /caretask/i);
  assert.match(toolChipCopy("utility").name, /utility/i);
  assert.equal(toolChipCopy("memory").family, "memory");
  assert.equal(toolChipCopy("reminder").family, "caretask");
});

test("chip targets prefer action, then clarification, then family default", () => {
  assert.equal(toolChipTarget("memory", "记下过敏史"), "记下过敏史");
  assert.equal(toolChipTarget("caretask", undefined, "needs_clarification"), "等待确认");
  assert.equal(toolChipTarget("utility"), "查询或计算");
});

test("group label names families instead of generic 照护动作", () => {
  assert.match(toolGroupLabel(["memory"]), /memory/i);
  assert.match(toolGroupLabel(["caretask"]), /caretask/i);
  assert.match(toolGroupLabel(["utility"]), /utility/i);
  assert.doesNotMatch(toolGroupLabel(["memory"]), /正在执行照护动作/);
  const mixed = toolGroupLabel(["memory", "caretask"]);
  assert.match(mixed, /memory/i);
  assert.match(mixed, /caretask/i);
});
