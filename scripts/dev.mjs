// Starts the FastAPI backend and the Next.js frontend together for local development.
// Usage (from the project root): npm run dev
import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const isWindows = process.platform === "win32";
const python = join(root, "backend", ".venv", isWindows ? "Scripts/python.exe" : "bin/python");

if (!existsSync(python)) {
  console.error("Backend virtual environment not found. Run `npm run setup` first.");
  process.exit(1);
}
if (!existsSync(join(root, "frontend", "node_modules"))) {
  console.error("Frontend dependencies not installed. Run `npm run setup` first.");
  process.exit(1);
}

const children = [];

function start(name, color, command, args, cwd) {
  const child = spawn(command, args, { cwd, shell: isWindows && command === "npm", env: process.env });
  const prefix = `\x1b[${color}m[${name}]\x1b[0m `;
  const pipe = (stream, out) => {
    let buffer = "";
    stream.on("data", (chunk) => {
      buffer += chunk;
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop();
      for (const line of lines) out.write(prefix + line + "\n");
    });
  };
  pipe(child.stdout, process.stdout);
  pipe(child.stderr, process.stderr);
  child.on("exit", (code) => {
    console.log(`${prefix}exited with code ${code}`);
    shutdown(code ?? 0);
  });
  children.push(child);
}

let stopping = false;
function shutdown(code) {
  if (stopping) return;
  stopping = true;
  for (const child of children) {
    if (child.exitCode !== null) continue;
    if (isWindows) spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore" });
    else child.kill("SIGTERM");
  }
  process.exit(code);
}
process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));

start("api", "36", python, ["-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"], join(root, "backend"));
start("web", "35", "npm", ["run", "dev"], join(root, "frontend"));
