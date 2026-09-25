import { readFileSync } from "node:fs";
import { stripTypeScriptTypes } from "node:module";

export async function loadTs(relativePath) {
  const source = readFileSync(new URL(relativePath, import.meta.url), "utf8");
  const compiled = stripTypeScriptTypes(source);
  return import(`data:text/javascript;charset=utf-8,${encodeURIComponent(compiled)}`);
}
