import { readFile } from "node:fs/promises";
import ts from "typescript";

export async function load(url, context, nextLoad) {
  if (!url.endsWith(".ts") && !url.endsWith(".tsx")) {
    return nextLoad(url, context);
  }

  const source = await readFile(new URL(url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    fileName: new URL(url).pathname,
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
      isolatedModules: true,
    },
  });

  return {
    format: "module",
    source: outputText,
    shortCircuit: true,
  };
}
