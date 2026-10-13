// One-time setup: creates the backend virtualenv, installs all dependencies and copies the example env files.
// Usage (from the project root): npm run setup
import { spawnSync } from "node:child_process";
import { copyFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const isWindows = process.platform === "win32";
const backend = join(root, "backend");
const frontend = join(root, "frontend");
const python = join(backend, ".venv", isWindows ? "Scripts/python.exe" : "bin/python");

function run(command, args, cwd) {
  console.log(`\n> ${command} ${args.join(" ")}  (in ${cwd})`);
  const result = spawnSync(command, args, { cwd, stdio: "inherit", shell: isWindows });
  if (result.status !== 0) {
    console.error(`\nSetup failed while running: ${command} ${args.join(" ")}`);
    process.exit(result.status ?? 1);
  }
}

if (!existsSync(python)) run(isWindows ? "python" : "python3", ["-m", "venv", ".venv"], backend);
run(python, ["-m", "pip", "install", "-r", "requirements.txt"], backend);
run("npm", ["install"], frontend);

for (const [example, target] of [
  [join(backend, ".env.example"), join(backend, ".env")],
  [join(frontend, ".env.example"), join(frontend, ".env.local")],
]) {
  if (!existsSync(target)) {
    copyFileSync(example, target);
    console.log(`Created ${target}`);
  }
}

console.log("\nSetup complete. Start the app with: npm run dev");
