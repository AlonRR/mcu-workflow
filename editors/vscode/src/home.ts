// MCU Flow "Home" - a PlatformIO-Home-style landing page (a webview panel).
//
// It's a thin launcher: every button posts a {type:"cmd", id} message that the
// extension runs via executeCommand, so the page never duplicates logic. It also
// shows a live status snapshot (doctor + connected boards) pulled from the CLI's
// --json output, and a "show on startup" toggle like PIO Home.

import * as vscode from "vscode";
import { resolve, runJson, detectIsProject } from "./cli";
import { esc, htmlShell, mediaUri } from "./webview";

let panel: vscode.WebviewPanel | undefined;

export async function showHome(context: vscode.ExtensionContext): Promise<void> {
  if (panel) {
    panel.reveal(vscode.ViewColumn.One);
    return;
  }
  panel = vscode.window.createWebviewPanel(
    "mcuflow.home",
    "MCU Flow",
    vscode.ViewColumn.One,
    {
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, "media")],
    }
  );
  panel.iconPath = vscode.Uri.joinPath(context.extensionUri, "media", "icon.png");
  panel.onDidDispose(
    () => {
      panel = undefined;
    },
    null,
    context.subscriptions
  );
  panel.webview.onDidReceiveMessage(
    async (msg) => {
      if (!panel) {
        return;
      }
      if (msg?.type === "cmd" && typeof msg.id === "string") {
        await vscode.commands.executeCommand(msg.id, ...(msg.args ?? []));
        // The command may have disposed the panel (e.g. New Project reloads the
        // window); re-render only if it's still alive.
        if (panel) {
          panel.webview.html = await render(panel.webview, context);
        }
      } else if (msg?.type === "refresh") {
        panel.webview.html = await render(panel.webview, context);
      } else if (msg?.type === "setStartup") {
        await vscode.workspace
          .getConfiguration("mcuflow")
          .update("home.showOnStartup", !!msg.value, vscode.ConfigurationTarget.Global);
      }
    },
    null,
    context.subscriptions
  );
  panel.webview.html = await render(panel.webview, context);
}

interface Status {
  cli: boolean;
  how?: string;
  doctorOk?: boolean;
  missingTools?: string[];
  ports?: { device: string; role: string; kind: string; serial: string | null }[];
  error?: string;
}

async function gatherStatus(): Promise<Status> {
  const r = resolve();
  if (!r) {
    return { cli: false };
  }
  try {
    const [doctor, portsRep] = await Promise.all([
      runJson<any>(r, ["doctor"]).catch((e) => ({ __err: String(e?.message ?? e) })),
      runJson<any>(r, ["ports"]).catch((e) => ({ __err: String(e?.message ?? e) })),
    ]);
    const s: Status = { cli: true, how: r.how };
    if (!doctor.__err) {
      s.doctorOk = doctor.ok;
      s.missingTools = Object.entries(doctor.tools)
        .filter(([, v]) => !v)
        .map(([k]) => k);
    }
    if (!portsRep.__err) {
      s.ports = portsRep.ports;
    }
    if (doctor.__err && portsRep.__err) {
      s.error = doctor.__err;
    }
    return s;
  } catch (e: any) {
    return { cli: true, error: String(e?.message ?? e) };
  }
}

function card(id: string, icon: string, title: string, desc: string, primary = false): string {
  return `<button class="card${primary ? " primary" : ""}" data-cmd="${id}">
    <span class="codicon-like">${icon}</span>
    <span class="card-title">${esc(title)}</span>
    <span class="card-desc">${esc(desc)}</span>
  </button>`;
}

function statusHtml(s: Status): string {
  if (!s.cli) {
    return `<div class="status warn">mcuflow CLI not found for this folder.
      <button class="link" data-cmd="mcuflow.setup">Set Up Project</button> ·
      <button class="link" data-cmd="workbench.action.openSettings" data-arg="mcuflow.path">Set mcuflow.path</button></div>`;
  }
  if (s.error) {
    return `<div class="status warn">CLI error: ${esc(s.error)}</div>`;
  }
  const doctor =
    s.doctorOk === undefined
      ? ""
      : s.doctorOk
        ? `<span class="ok">● Doctor: ready</span>`
        : `<span class="bad">● Doctor: ${
            s.missingTools?.length ? "missing " + esc(s.missingTools.join(", ")) : "needs attention"
          }</span>`;
  const boards = (s.ports ?? []).filter((p) => p.kind === "board");
  const boardsHtml = boards.length
    ? boards
        .map(
          (p) =>
            `<li><b>${esc(p.device)}</b> — ${esc(p.role || "board")}${
              p.serial ? ` <span class="dim">(${esc(p.serial)})</span>` : ""
            }</li>`
        )
        .join("")
    : `<li class="dim">no boards detected</li>`;
  return `<div class="status">
      <div class="status-row">${doctor}<span class="dim">via ${esc(s.how ?? "")}</span></div>
      <div class="status-row"><b>Boards</b><ul class="boards">${boardsHtml}</ul></div>
    </div>`;
}

async function render(webview: vscode.Webview, context: vscode.ExtensionContext): Promise<string> {
  const s = await gatherStatus();
  const isProject = await detectIsProject();
  const iconUri = mediaUri(webview, context.extensionUri, "icon.png");
  const showOnStartup = vscode.workspace
    .getConfiguration("mcuflow")
    .get<boolean>("home.showOnStartup", true);

  const start = [
    card("mcuflow.newProject", "✚", "New Project", "Folder + name, then configure inside it", true),
    card("workbench.action.files.openFolder", "📁", "Open Folder", "Open an existing project folder"),
    // Configure/Refine act on a project - only when one is open.
    ...(isProject
      ? [
          card("mcuflow.configureProject", "⚙", "Configure Parameters", "Chip, devices, test needs"),
          card("mcuflow.refineWithAgent", "✦", "Refine with Agent", "Fill pins/devices with the agent"),
        ]
      : []),
  ].join("");

  const build = [
    card("mcuflow.scaffold", "▣", "Scaffold", "Generate the ESP-IDF project"),
    card("mcuflow.build", "🔧", "Build", "Compile (cage or native)"),
    card("mcuflow.flash", "⚡", "Flash", "Onto the selected board"),
    card("mcuflow.monitor", "〜", "Monitor", "Serial output"),
    card("mcuflow.run", "▶", "Run", "validate → build → flash → HIL"),
  ].join("");

  const tools = [
    card("mcuflow.doctor", "♥", "Doctor", "Preflight: deps, ports, satellite"),
    card("mcuflow.ports", "🔌", "Port Viewer", "Which board is on which COM"),
    card("mcuflow.pickPort", "☑", "Select Port", "Pick the DUT/board port"),
    card("mcuflow.bridge", "📡", "Bridge", "Share a serial port over the network"),
    card("mcuflow.debug", "🐞", "Debug", "OpenOCD GDB server (JTAG)"),
  ].join("");

  const body = `
  <header>
    <img src="${iconUri}" alt="MCU Flow">
    <div>
      <h1>MCU Flow</h1>
      <p>Contract-first ESP32 workflow — one board.yml drives scaffold, build, flash, and HIL.</p>
    </div>
  </header>

  ${statusHtml(s)}
  <div class="toolbar"><button class="link" id="refresh">↻ Refresh</button></div>

  <h2>Start</h2>
  <div class="grid">${start}</div>

  ${isProject ? `<h2>This project</h2>\n  <div class="grid">${build}</div>` : ""}

  <h2>Tools</h2>
  <div class="grid">${tools}</div>

  <footer>
    <label><input type="checkbox" id="startup" ${showOnStartup ? "checked" : ""}> Show this page on startup</label>
  </footer>`;

  return htmlShell(webview, context.extensionUri, {
    title: "MCU Flow",
    style: "home.css",
    script: "home.js",
    body,
  });
}
