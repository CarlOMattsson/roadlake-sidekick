// Runs lint, typecheck and the unit tests in parallel. Each command's output is buffered
// and printed under a heading when that command finishes. Exit code 1 if any command failed.
//
//   npm run check        lint + tsc -b + vitest run + the MCP App views on Preact (test:mcp-app:preact)
//   npm run check:bail   same, but vitest stops after 5 failures (--bail=5)
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const bail = process.argv.includes("--bail");
const frontendDir = fileURLToPath(new URL("../", import.meta.url));

const steps = [
  { name: "lint", args: ["run", "lint"] },
  { name: "typecheck (tsc -b)", args: ["run", "typecheck"] },
  {
    name: "test (vitest run)",
    args: ["run", "test", ...(bail ? ["--", "--bail=5"] : [])],
  },
  {
    name: "test (MCP App views on Preact)",
    args: ["run", "test:mcp-app:preact", ...(bail ? ["--", "--bail=5"] : [])],
  },
];

function runStep(step) {
  return new Promise((resolve) => {
    const began = Date.now();
    const chunks = [];
    let finished = false;
    const child = spawn("npm", step.args, {
      cwd: frontendDir,
      env: process.env,
      shell: process.platform === "win32",
      stdio: ["ignore", "pipe", "pipe"],
    });
    child.stdout.on("data", (chunk) => chunks.push(chunk));
    child.stderr.on("data", (chunk) => chunks.push(chunk));
    child.on("error", (error) => {
      chunks.push(Buffer.from(`${error.message}\n`));
      finish(1);
    });
    child.on("close", (code) => finish(code ?? 1));

    function finish(code) {
      if (finished) return;
      finished = true;
      const seconds = ((Date.now() - began) / 1000).toFixed(1);
      const ok = code === 0;
      process.stdout.write(
        `\n===== ${step.name}: ${ok ? "OK" : "FAILED"} (exit ${code}, ${seconds} s) =====\n`,
      );
      process.stdout.write(Buffer.concat(chunks));
      resolve({ name: step.name, ok, seconds });
    }
  });
}

const started = Date.now();
const results = await Promise.all(steps.map(runStep));
const totalSeconds = ((Date.now() - started) / 1000).toFixed(1);

process.stdout.write("\n");
for (const result of results) {
  process.stdout.write(
    `${result.ok ? "ok    " : "FAIL  "} ${result.name} (${result.seconds} s)\n`,
  );
}
process.stdout.write(`total ${totalSeconds} s\n`);

const allOk = results.every((result) => result.ok);
process.exitCode = allOk ? 0 : 1;
