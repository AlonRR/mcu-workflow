// MCU Flow - a thin GUI over the `mcuflow` CLI.
//
// Quick, structured reads (ports, doctor) go through cli.runJson and feed the
// tree + status bar. Verbs that stream output or are interactive/long-running
// run in a named VS Code terminal so the user sees live progress (PlatformIO
// style). The CLI remains the single source of truth; this never reimplements
// its logic.

import * as vscode from "vscode";
import * as path from "path";
import { resolve, runJson, isWorkspaceMcuflow, portableLauncher, Resolved } from "./cli";
import { McuflowTree } from "./tree";
import { buildBoardYaml, CHIPS, DEVICE_CATALOG, NewProjectOpts } from "./newproject";

let selectedPort: string | undefined;
let portStatus: vscode.StatusBarItem;
const terminals = new Map<string, vscode.Terminal>();

export function activate(context: vscode.ExtensionContext) {
  selectedPort = context.workspaceState.get<string>("mcuflow.port");

  const tree = new McuflowTree(() => selectedPort);
  const view = vscode.window.createTreeView("mcuflow.view", { treeDataProvider: tree });
  context.subscriptions.push(view);

  // --- status bar: Build · Flash · Monitor · Port ---------------------------
  const items: vscode.StatusBarItem[] = [];
  const mk = (text: string, tip: string, cmd: string, priority: number) => {
    const it = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, priority);
    it.text = text;
    it.tooltip = tip;
    it.command = cmd;
    it.show();
    items.push(it);
    context.subscriptions.push(it);
    return it;
  };
  mk("$(rocket) MCU", "MCU Flow: set up project", "mcuflow.setup", 100);
  mk("$(tools) Build", "mcuflow build", "mcuflow.build", 99);
  mk("$(zap) Flash", "mcuflow flash", "mcuflow.flash", 98);
  mk("$(pulse) Monitor", "mcuflow monitor", "mcuflow.monitor", 97);
  portStatus = mk("$(plug) Port", "Select board / port", "mcuflow.pickPort", 96);
  updatePortStatus();

  const refreshAll = () => {
    tree.refresh();
    updatePortStatus();
  };

  // --- helpers --------------------------------------------------------------
  const need = (): Resolved | undefined => {
    const r = resolve();
    if (!r) {
      vscode.window
        .showWarningMessage(
          "mcuflow not found in this workspace.",
          "Set Up Project",
          "Open Settings"
        )
        .then((c) => {
          if (c === "Set Up Project") {
            vscode.commands.executeCommand("mcuflow.setup");
          } else if (c === "Open Settings") {
            vscode.commands.executeCommand("workbench.action.openSettings", "mcuflow.path");
          }
        });
    }
    return r;
  };

  const reg = (id: string, fn: (...a: any[]) => any) =>
    context.subscriptions.push(vscode.commands.registerCommand(id, fn));

  // --- one-per-verb commands ------------------------------------------------
  // Terminal verbs: run in a named terminal, refresh the tree afterward.
  const term = (name: string, args: string[]) => {
    const r = need();
    if (!r) {
      return;
    }
    runInTerminal(name, r, args);
    setTimeout(refreshAll, 1500);
  };

  const cfg = () => vscode.workspace.getConfiguration("mcuflow");
  const board = () => cfg().get<string>("boardFile") || "examples/board-c3.yml";
  const simFlag = () => (cfg().get<boolean>("simulate") ? ["--sim"] : []);
  const portArgs = () => (selectedPort ? ["--port", selectedPort] : []);

  reg("mcuflow.build", () => term("build", [...simFlag(), "build"]));
  reg("mcuflow.flash", () => term("flash", [...simFlag(), "flash", ...portArgs()]));
  reg("mcuflow.monitor", () => term("monitor", ["monitor", ...portArgs()]));
  reg("mcuflow.run", () =>
    term("run", [...simFlag(), "run", board(), ...portArgs()])
  );
  reg("mcuflow.test", () => term("test", [...simFlag(), "test"]));
  reg("mcuflow.hil", () => term("hil", [...simFlag(), "hil"]));
  reg("mcuflow.validate", () => term("validate", ["validate", board()]));
  reg("mcuflow.scaffold", () => term("scaffold", ["scaffold", board()]));
  reg("mcuflow.workbench", () => term("workbench", ["workbench"]));
  reg("mcuflow.up", () => term("up", ["up"]));

  reg("mcuflow.bridge", async () => {
    const r = need();
    if (!r) {
      return;
    }
    const port = selectedPort ?? (await pickPortQuick(r));
    if (!port) {
      return;
    }
    const tcp =
      (await vscode.window.showInputBox({
        prompt: "TCP port to serve on",
        value: "4000",
      })) || "4000";
    runInTerminal("bridge", r, ["bridge", "--port", port, "--tcp", tcp]);
  });

  reg("mcuflow.debug", async () => {
    const r = need();
    if (!r) {
      return;
    }
    const chip =
      (await vscode.window.showInputBox({ prompt: "Target chip", value: "esp32c3" })) ||
      "esp32c3";
    runInTerminal("debug", r, ["debug", "--chip", chip]);
  });

  // ports viewer (its own tkinter window) - run detached in a terminal
  reg("mcuflow.ports", () => term("ports", ["ports"]));

  // --- doctor (structured) --------------------------------------------------
  reg("mcuflow.doctor", async () => {
    const r = need();
    if (!r) {
      return;
    }
    try {
      const d = await runJson<any>(r, ["doctor"]);
      const missing = Object.entries(d.tools)
        .filter(([, v]) => !v)
        .map(([k]) => k);
      const modsMissing = Object.entries(d.modules)
        .filter(([, v]) => !v)
        .map(([k]) => k);
      const lines = [
        `Doctor: ${d.ok ? "ready ✓" : "needs attention"}`,
        `ports: ${d.ports.join(", ") || "none"}`,
        missing.length ? `missing tools: ${missing.join(", ")}` : "all tools found",
        modsMissing.length ? `missing modules: ${modsMissing.join(", ")}` : "all modules present",
      ];
      const pick = await vscode.window.showInformationMessage(
        lines.join("   |   "),
        ...(d.ok ? [] : ["Install Prerequisites"])
      );
      if (pick === "Install Prerequisites") {
        vscode.commands.executeCommand("mcuflow.doctorFix");
      }
    } catch (e: any) {
      vscode.window.showErrorMessage(`mcuflow doctor failed: ${e.message ?? e}`);
    }
    refreshAll();
  });

  reg("mcuflow.doctorFix", () => term("doctor --fix", ["doctor", "--fix"]));

  // --- port picker ----------------------------------------------------------
  reg("mcuflow.pickPort", async () => {
    const r = need();
    if (!r) {
      return;
    }
    const port = await pickPortQuick(r);
    if (port !== undefined) {
      selectedPort = port || undefined;
      await context.workspaceState.update("mcuflow.port", selectedPort);
      updatePortStatus();
      tree.refresh();
    }
  });

  // clicking a board row in the tree selects it
  reg("mcuflow.selectPortValue", async (device: string) => {
    selectedPort = device;
    await context.workspaceState.update("mcuflow.port", selectedPort);
    updatePortStatus();
    tree.refresh();
  });

  reg("mcuflow.refresh", refreshAll);

  // --- new project (step 0: form -> skeleton board.yml -> refine) -----------
  reg("mcuflow.newProject", () => runNewProject(context));
  reg("mcuflow.refineWithAgent", (fileArg?: string) => runRefineWithAgent(fileArg));

  // --- onboarding -----------------------------------------------------------
  reg("mcuflow.setup", () => runSetup());

  // First-run: if this looks like an mcuflow project but the venv/CLI isn't
  // ready, nudge toward setup once.
  maybeFirstRun(context);
}

export function deactivate() {
  for (const t of terminals.values()) {
    t.dispose();
  }
}

// --- terminal execution ------------------------------------------------------

function runInTerminal(name: string, r: Resolved, args: string[]): void {
  const key = `mcuflow: ${name}`;
  let t = terminals.get(key);
  if (!t || (t.exitStatus !== undefined)) {
    const env: { [k: string]: string } = {};
    if (r.binDir) {
      // Prepend the bin dir so a bare `mcuflow` token resolves in the terminal.
      env.PATH = r.binDir + (process.platform === "win32" ? ";" : ":") + (process.env.PATH ?? "");
    }
    t = vscode.window.createTerminal({ name: key, cwd: r.cwd, env });
    terminals.set(key, t);
  }
  t.show();
  const line = `${r.term} ${args.map(shellQuote).join(" ")}`;
  t.sendText(line, true);
}

function shellQuote(s: string): string {
  return /[\s"]/.test(s) ? `"${s.replace(/"/g, '\\"')}"` : s;
}

// --- port picker -------------------------------------------------------------

async function pickPortQuick(r: Resolved): Promise<string | undefined> {
  let rep: any;
  try {
    rep = await runJson<any>(r, ["ports"]);
  } catch (e: any) {
    vscode.window.showErrorMessage(`Could not list ports: ${e.message ?? e}`);
    return undefined;
  }
  const items: vscode.QuickPickItem[] = (rep.ports as any[]).map((p) => ({
    label: p.device,
    description: [p.role, p.serial].filter(Boolean).join(" · "),
    detail: p.description,
  }));
  items.push({ label: "$(clear-all) Clear selection", description: "use auto-detect" });
  const pick = await vscode.window.showQuickPick(items, {
    placeHolder: "Select the board / serial port (used for flash, monitor, run)",
  });
  if (!pick) {
    return undefined;
  }
  if (pick.label.includes("Clear selection")) {
    return "";
  }
  return pick.label;
}

function updatePortStatus(): void {
  if (!portStatus) {
    return;
  }
  portStatus.text = selectedPort ? `$(plug) ${selectedPort}` : "$(plug) Port: auto";
  portStatus.tooltip = selectedPort
    ? `Selected port: ${selectedPort} (click to change)`
    : "No port selected - mcuflow auto-detects the DUT. Click to choose.";
}

// --- new project: step 0 -----------------------------------------------------

async function runNewProject(context: vscode.ExtensionContext): Promise<void> {
  // 1) Where it lives: pick a parent folder, then a project name.
  const parentPick = await vscode.window.showOpenDialog({
    canSelectFolders: true,
    canSelectFiles: false,
    canSelectMany: false,
    openLabel: "Create project here",
    title: "MCU Flow: choose a parent folder for the new project",
  });
  if (!parentPick || parentPick.length === 0) {
    return;
  }
  const parent = parentPick[0].fsPath;

  const name = (
    await vscode.window.showInputBox({
      prompt: "Project name (folder + board.yml meta.project)",
      value: "my-mcu-project",
      validateInput: (v) =>
        /^[A-Za-z0-9._-]+$/.test(v.trim()) ? null : "Use letters, digits, dot, dash, underscore.",
    })
  )?.trim();
  if (!name) {
    return;
  }

  // 2) The form: chip, devices, test needs.
  const chip = await vscode.window.showQuickPick(CHIPS, {
    placeHolder: "Target chip (esp32c3 = your Super Mini)",
  });
  if (!chip) {
    return;
  }

  const devItems: (vscode.QuickPickItem & { key: string })[] = Object.entries(DEVICE_CATALOG).map(
    ([key, d]) => ({ key, label: d.part, description: d.desc })
  );
  const devPick = await vscode.window.showQuickPick(devItems, {
    placeHolder: "Add devices (optional — refine more with the agent later)",
    canPickMany: true,
  });
  const devices = (devPick ?? []).map((d) => d.key);

  const needItems: vscode.QuickPickItem[] = [
    { label: "serial", description: "boot string over USB serial", picked: true },
    { label: "wifi", description: "join WiFi in the HIL test (needs the satellite board)" },
  ];
  const needPick = await vscode.window.showQuickPick(needItems, {
    placeHolder: "What should the HIL test check?",
    canPickMany: true,
  });
  const needs = (needPick ?? []).map((n) => n.label);

  // 3) Generate the skeleton board.yml into <parent>/<name>/.
  const opts: NewProjectOpts = { project: name, chip, devices, needs };
  const yaml = buildBoardYaml(opts);
  const projDir = vscode.Uri.file(path.join(parent, name));
  const boardFile = vscode.Uri.joinPath(projDir, "board.yml");
  try {
    await vscode.workspace.fs.createDirectory(projDir);
    // Don't clobber an existing board.yml.
    let clobber = false;
    try {
      await vscode.workspace.fs.stat(boardFile);
      clobber = true;
    } catch {
      /* doesn't exist - good */
    }
    if (clobber) {
      const go = await vscode.window.showWarningMessage(
        `board.yml already exists in ${name}. Overwrite?`,
        { modal: true },
        "Overwrite"
      );
      if (go !== "Overwrite") {
        return;
      }
    }
    await vscode.workspace.fs.writeFile(boardFile, Buffer.from(yaml, "utf8"));

    // 4) Make the new folder a usable mcuflow workspace: point it at this CLI
    //    install and at board.yml, written into its .vscode/settings.json.
    const settings: Record<string, unknown> = { "mcuflow.boardFile": "board.yml" };
    const launcher = portableLauncher();
    if (launcher) {
      settings["mcuflow.path"] = launcher;
    }
    const settingsUri = vscode.Uri.joinPath(projDir, ".vscode", "settings.json");
    await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(projDir, ".vscode"));
    await vscode.workspace.fs.writeFile(
      settingsUri,
      Buffer.from(JSON.stringify(settings, null, 2) + "\n", "utf8")
    );
  } catch (e: any) {
    vscode.window.showErrorMessage(`Could not create project: ${e.message ?? e}`);
    return;
  }

  // 5) Open the file, then offer the agent-refine / open-folder actions.
  const doc = await vscode.workspace.openTextDocument(boardFile);
  await vscode.window.showTextDocument(doc, { preview: false });
  const choice = await vscode.window.showInformationMessage(
    `Created ${name}/board.yml (skeleton). Refine it with the agent, then open the folder to build & flash.`,
    "Refine with Agent",
    "Open Folder"
  );
  if (choice === "Refine with Agent") {
    runRefineWithAgent(boardFile.fsPath);
  } else if (choice === "Open Folder") {
    // Reuse the current window so the new folder inherits THIS window's profile
    // (the one the extension is installed in). Opening a brand-new folder in a
    // forced new window would land in the Default profile - no MCU Flow GUI.
    vscode.commands.executeCommand("vscode.openFolder", projDir, { forceNewWindow: false });
  }
}

async function runRefineWithAgent(fileArg?: string): Promise<void> {
  // Resolve the board.yml to refine: explicit arg, active editor, or workspace.
  let file = fileArg;
  if (!file) {
    const active = vscode.window.activeTextEditor?.document;
    if (active && active.fileName.endsWith(".yml")) {
      file = active.fileName;
    }
  }
  if (!file) {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (root) {
      const cand = path.join(root, "board.yml");
      try {
        await vscode.workspace.fs.stat(vscode.Uri.file(cand));
        file = cand;
      } catch {
        /* none */
      }
    }
  }
  if (!file) {
    vscode.window.showWarningMessage(
      "No board.yml found to refine. Create one with 'MCU Flow: New Project' first."
    );
    return;
  }
  const dir = path.dirname(file);
  const base = path.basename(file);
  try {
    const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(file));
    await vscode.window.showTextDocument(doc, { preview: false });
  } catch {
    /* still launch the agent even if the open fails */
  }
  const t = vscode.window.createTerminal({ name: "mcuflow: agent", cwd: dir });
  terminals.set("mcuflow: agent", t);
  t.show();
  const prompt =
    `Help me complete ${base} for my mcuflow firmware project. ` +
    `Open ${base}, then ask me about the chip, the wiring/pin assignments, the sensors/devices, ` +
    `and what the boot/HIL test should verify. Fill in the pins (avoid strap/UART pins for the chip), ` +
    `write a correct board.yml, and run \`mcuflow validate ${base}\` until it passes.`;
  t.sendText(`claude ${shellQuote(prompt)}`, true);
  vscode.window.showInformationMessage(
    "Launched the agent in the 'mcuflow: agent' terminal. (Requires the `claude` CLI on PATH.)"
  );
}

// --- onboarding --------------------------------------------------------------

async function runSetup(): Promise<void> {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  if (!root) {
    vscode.window.showWarningMessage("Open a folder (your mcuflow project) first, then run setup.");
    return;
  }
  const choice = await vscode.window.showInformationMessage(
    "Set up mcuflow in this workspace? This creates a uv-managed .venv, installs dependencies, and runs doctor --fix in a terminal.",
    { modal: true },
    "Run Setup"
  );
  if (choice !== "Run Setup") {
    return;
  }
  const t = vscode.window.createTerminal({ name: "mcuflow: setup", cwd: root });
  terminals.set("mcuflow: setup", t);
  t.show();
  const isWin = process.platform === "win32";
  // uv-managed venv + editable install + self-install of prerequisites.
  const mcuflow = isWin ? ".\\bin\\mcuflow.bat" : "./bin/mcuflow";
  const lines = [
    "uv venv",
    'uv pip install -e ".[dev]"',
    `${mcuflow} doctor --fix`,
    `${mcuflow} doctor`,
  ];
  for (const l of lines) {
    t.sendText(l, true);
  }
  vscode.window.showInformationMessage(
    "Setup is running in the 'mcuflow: setup' terminal. When it finishes, click Refresh in the MCU Flow view."
  );
}

function maybeFirstRun(context: vscode.ExtensionContext): void {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  if (!root || !isWorkspaceMcuflow(root)) {
    return;
  }
  if (resolve()) {
    return; // CLI usable already; nothing to nudge
  }
  if (context.globalState.get("mcuflow.firstRunPrompted")) {
    return;
  }
  context.globalState.update("mcuflow.firstRunPrompted", true);
  vscode.window
    .showInformationMessage("This looks like an mcuflow project. Set it up now?", "Set Up Project")
    .then((c) => {
      if (c === "Set Up Project") {
        vscode.commands.executeCommand("mcuflow.setup");
      }
    });
}
