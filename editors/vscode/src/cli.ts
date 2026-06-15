// Locating and invoking the `mcuflow` CLI.
//
// Two invocation paths, deliberately:
//   * runJson()  - execFile (no shell), parses the --json envelope. Used for the
//                  Boards tree and Doctor status. Prefers the venv python + the
//                  mcuflow.py script directly, so there's no shell quoting and no
//                  re-exec hop (MCUFLOW_NO_REEXEC=1).
//   * terminalCommand() - a command line for a VS Code terminal, used for verbs
//                  that stream or are interactive (build/flash/monitor/run/...).
//                  Prefers the `bin` launcher placed on the terminal's PATH so a
//                  bare `mcuflow ...` works in both PowerShell and cmd.
//
// Resolution order (both paths): the `mcuflow.path` setting, then a workspace
// .venv + src/mcuflow/mcuflow.py, then bin/mcuflow[.bat], then `mcuflow` on PATH.

import * as vscode from "vscode";
import { execFile } from "child_process";
import * as fs from "fs";
import * as path from "path";

const isWin = process.platform === "win32";

export interface Resolved {
  /** Repo/workspace root the CLI runs from (cwd). */
  cwd: string;
  /** For execFile: the executable and its leading args. */
  exec: { file: string; baseArgs: string[]; shell: boolean };
  /** For terminals: a directory to prepend to PATH so `mcuflow` resolves, or "". */
  binDir: string;
  /** For terminals: the command token to call (e.g. "mcuflow" or a full path). */
  term: string;
  /** Environment overrides applied to both paths. */
  env: NodeJS.ProcessEnv;
  /** Human note on how mcuflow was found (shown in the tree / on errors). */
  how: string;
}

function workspaceRoot(): string | undefined {
  return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
}

function exists(p: string): boolean {
  try {
    fs.accessSync(p);
    return true;
  } catch {
    return false;
  }
}

/** The venv python for a given root, if present. */
function venvPython(root: string): string | undefined {
  const p = isWin
    ? path.join(root, ".venv", "Scripts", "python.exe")
    : path.join(root, ".venv", "bin", "python");
  return exists(p) ? p : undefined;
}

function binLauncher(root: string): string | undefined {
  const p = isWin ? path.join(root, "bin", "mcuflow.bat") : path.join(root, "bin", "mcuflow");
  return exists(p) ? p : undefined;
}

/**
 * Resolve how to call mcuflow, or undefined if nothing was found and no explicit
 * path is configured (callers offer onboarding in that case).
 */
export function resolve(): Resolved | undefined {
  const root = workspaceRoot() ?? process.cwd();
  const cfg = vscode.workspace.getConfiguration("mcuflow");
  const explicit = (cfg.get<string>("path") ?? "").trim();
  const env: NodeJS.ProcessEnv = { ...process.env, MCUFLOW_NO_REEXEC: "1" };

  // 1) Explicit setting wins. If it points at a .py, run it with the venv python
  //    (or system python); otherwise treat it as a launcher executable.
  if (explicit) {
    const abs = path.isAbsolute(explicit) ? explicit : path.join(root, explicit);
    if (explicit.endsWith(".py")) {
      const py = venvPython(root) ?? (isWin ? "python" : "python3");
      return {
        cwd: root,
        exec: { file: py, baseArgs: [abs], shell: false },
        binDir: "",
        term: termCmd([py, abs]),
        env,
        how: `setting mcuflow.path → ${explicit}`,
      };
    }
    return {
      cwd: root,
      exec: { file: abs, baseArgs: [], shell: isWin },
      binDir: path.dirname(abs),
      term: termCmd([abs]),
      env,
      how: `setting mcuflow.path → ${explicit}`,
    };
  }

  // 2) Workspace .venv + the script (no shell, no re-exec hop).
  const script = path.join(root, "src", "mcuflow", "mcuflow.py");
  const vpy = venvPython(root);
  const bin = binLauncher(root);
  if (vpy && exists(script)) {
    return {
      cwd: root,
      exec: { file: vpy, baseArgs: [script], shell: false },
      // Prefer the bin launcher for terminals (bare `mcuflow` token); fall back
      // to the python+script form if there's no bin/ dir.
      binDir: bin ? path.dirname(bin) : "",
      term: bin ? "mcuflow" : termCmd([vpy, script]),
      env,
      how: "workspace .venv + src/mcuflow/mcuflow.py",
    };
  }

  // 3) bin/ launcher (handles venv selection itself).
  if (bin) {
    return {
      cwd: root,
      exec: { file: bin, baseArgs: [], shell: isWin },
      binDir: path.dirname(bin),
      term: "mcuflow",
      env,
      how: "bin/ launcher",
    };
  }

  // 4) `mcuflow` on PATH - only if it's actually there. Returning undefined
  //    otherwise lets the tree show a clean "set up" state instead of running a
  //    non-existent CLI and rendering error rows.
  if (mcuflowOnPath()) {
    return {
      cwd: root,
      exec: { file: "mcuflow", baseArgs: [], shell: isWin },
      binDir: "",
      term: "mcuflow",
      env,
      how: "mcuflow on PATH",
    };
  }
  return undefined;
}

/** Is an `mcuflow` launcher on PATH? A cheap filesystem scan, no spawn. */
export function mcuflowOnPath(): boolean {
  const names = isWin ? ["mcuflow.bat", "mcuflow.cmd", "mcuflow.exe", "mcuflow"] : ["mcuflow"];
  const dirs = (process.env.PATH ?? "").split(isWin ? ";" : ":");
  for (const d of dirs) {
    if (!d) {
      continue;
    }
    for (const n of names) {
      if (exists(path.join(d, n))) {
        return true;
      }
    }
  }
  return false;
}

/**
 * Does the open workspace look like an MCU project? Drives the `mcuflow.isProject`
 * context key that reveals the view (PlatformIO-style: show only when a project
 * is detected). True if any workspace-folder root has mcuflow markers, or a
 * board.yml exists anywhere in the tree.
 */
export async function detectIsProject(): Promise<boolean> {
  for (const f of vscode.workspace.workspaceFolders ?? []) {
    if (isWorkspaceMcuflow(f.uri.fsPath)) {
      return true;
    }
  }
  const hits = await vscode.workspace.findFiles(
    "**/board.yml",
    "**/{node_modules,.venv,.git,build-out,managed_components}/**",
    1
  );
  return hits.length > 0;
}

/**
 * An absolute reference to *this* mcuflow install that a different folder can use
 * as its `mcuflow.path`, so a freshly-created project elsewhere can call the CLI.
 * Prefers the bin launcher (resolves the repo's .venv itself), then an explicit
 * setting, then the script. Returns undefined when mcuflow is only on PATH (in
 * which case a new project needs nothing - PATH is global).
 */
export function portableLauncher(): string | undefined {
  const root = workspaceRoot() ?? process.cwd();
  const bin = binLauncher(root);
  if (bin) {
    return bin;
  }
  const explicit = (vscode.workspace.getConfiguration("mcuflow").get<string>("path") ?? "").trim();
  if (explicit) {
    return path.isAbsolute(explicit) ? explicit : path.join(root, explicit);
  }
  const script = path.join(root, "src", "mcuflow", "mcuflow.py");
  return exists(script) ? script : undefined;
}

/** Heuristic: does this folder look like the mcuflow project / a board project? */
export function isWorkspaceMcuflow(root: string): boolean {
  return (
    exists(path.join(root, "src", "mcuflow", "mcuflow.py")) ||
    exists(path.join(root, "bin", "mcuflow")) ||
    exists(path.join(root, "bin", "mcuflow.bat")) ||
    exists(path.join(root, "board.yml")) ||
    exists(path.join(root, "examples", "board-c3.yml"))
  );
}

function quote(s: string): string {
  return /\s/.test(s) ? `"${s}"` : s;
}

/**
 * Build a terminal command line from tokens (command first, then leading args).
 * On Windows the integrated terminal defaults to PowerShell, which treats a
 * quoted path in command position as a string literal - so it needs the call
 * operator `&`. cmd doesn't use `&`, but PowerShell is the default; cmd/bash
 * users with a spaced path can set `mcuflow.path` to a bare token. When the
 * command needs no quoting (e.g. `mcuflow` on PATH) no `&` is added.
 */
function termCmd(tokens: string[]): string {
  const needsCall = isWin && /\s/.test(tokens[0]);
  return (needsCall ? "& " : "") + tokens.map(quote).join(" ");
}

/** Run a verb with --json and return the parsed envelope. Rejects on bad JSON. */
export function runJson<T = any>(r: Resolved, args: string[]): Promise<T> {
  const full = [...r.exec.baseArgs, "--json", ...args];
  return new Promise((resolve, reject) => {
    execFile(
      r.exec.file,
      full,
      { cwd: r.cwd, env: r.env, shell: r.exec.shell, windowsHide: true, maxBuffer: 4 * 1024 * 1024 },
      (err, stdout, stderr) => {
        const text = (stdout || "").trim();
        // Many verbs exit non-zero on a failed check but still emit valid JSON;
        // prefer the JSON if we can parse it, fall back to the error otherwise.
        // The CLI prints exactly one JSON object; if anything brackets it, slice
        // from the first "{" to the last "}".
        try {
          resolve(JSON.parse(text) as T);
        } catch {
          const a = text.indexOf("{");
          const b = text.lastIndexOf("}");
          if (a >= 0 && b > a) {
            try {
              resolve(JSON.parse(text.slice(a, b + 1)) as T);
              return;
            } catch {
              /* fall through */
            }
          }
          reject(new Error((stderr || err?.message || "no output").trim()));
        }
      }
    );
  });
}
