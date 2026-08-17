import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = join(root, ".venv", "Lib", "site-packages", "workers");
const destRoot = join(root, "python_modules");
const dest = join(destRoot, "workers");

if (!existsSync(src)) {
  console.error("Missing .venv workers package. Run: uv sync");
  process.exit(1);
}

mkdirSync(destRoot, { recursive: true });
rmSync(dest, { recursive: true, force: true });
cpSync(src, dest, { recursive: true });
console.log("Vendored workers SDK -> python_modules/workers");
