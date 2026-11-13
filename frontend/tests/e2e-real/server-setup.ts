// Playwright runs this file outside Vitest: it starts the real backend the specs talk to.
import { spawn, type ChildProcess } from "node:child_process";
import { createInterface } from "node:readline";
import { resolve } from "node:path";

/** Longest wait for the server: the first start migrates and empties the test database. */
const START_TIMEOUT_MS = 120_000;

/**
 * Starts backend/tests/support/e2e_server.py, which serves the whole application on a free loopback
 * port and prints its URL and a token that lives for this run only. Both reach the workers through the
 * environment. The test database comes from SIDEKICK_TEST_* (`eval "$(bash tools/test-db-pool.sh env K)"`),
 * and E2E_BACKEND_PYTHON names the Python of the backend environment (default backend/.venv/bin/python).
 */
export default async function startServer(): Promise<() => Promise<void>> {
  const root = resolve(process.cwd(), "..");
  const python =
    process.env.E2E_BACKEND_PYTHON ?? resolve(root, "backend/.venv/bin/python");
  const child = spawn(python, ["-m", "tests.support.e2e_server"], {
    cwd: resolve(root, "backend"),
    env: {
      ...process.env,
      PYTHONPATH: [resolve(root, "backend/src"), resolve(root, "backend")].join(
        ":",
      ),
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  // The server logs every request to stderr; keep the tail and show it only when the server fails to start.
  let log = "";
  child.stderr.on("data", (chunk: Buffer) => {
    log = (log + chunk.toString()).slice(-4000);
  });
  const { url, token } = await announced(child).catch((error: Error) => {
    throw new Error(`${error.message}\n${log}`);
  });
  process.env.E2E_BACKEND_URL = url;
  process.env.E2E_BACKEND_TOKEN = token;
  return async () => {
    if (child.exitCode !== null) return;
    const exited = new Promise((done) => child.once("exit", done));
    child.kill("SIGTERM");
    await exited;
  };
}

/** The `{url, token}` line the server prints once it listens; log lines before it are ignored. */
async function announced(
  child: ChildProcess,
): Promise<{ url: string; token: string }> {
  return new Promise((done, fail) => {
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      fail(new Error("The e2e server did not start in time"));
    }, START_TIMEOUT_MS);
    child.once("exit", (code) => {
      clearTimeout(timer);
      fail(new Error(`The e2e server exited with code ${code}`));
    });
    createInterface({ input: child.stdout! }).on("line", (line) => {
      if (!line.startsWith('{"url"')) return;
      clearTimeout(timer);
      done(JSON.parse(line) as { url: string; token: string });
    });
  });
}
