// The "New Project" panel - an in-editor webview form (like PlatformIO's New
// Project dialog) for choosing a location + name, instead of the native folder
// dialog. Browse still uses the OS folder picker, but it's optional; the panel
// is the primary UI. On Create it writes a minimal project and opens it.

import * as vscode from "vscode";
import * as path from "path";
import * as os from "os";
import { buildBoardYaml, validateNewProject, CONFIGURE_MARKER } from "./newproject";
import { portableLauncher } from "./cli";

let panel: vscode.WebviewPanel | undefined;

function defaultLocation(): string {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  // The parent of the open folder is the usual place for a sibling project;
  // fall back to the home directory when no folder is open.
  return root ? path.dirname(root) : os.homedir();
}

export async function showNewProjectPanel(context: vscode.ExtensionContext): Promise<void> {
  if (panel) {
    panel.reveal(vscode.ViewColumn.One);
    return;
  }
  panel = vscode.window.createWebviewPanel(
    "mcuflow.newProject",
    "New MCU Flow Project",
    vscode.ViewColumn.One,
    { enableScripts: true, localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, "media")] }
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
      if (msg?.type === "browse") {
        const cur = String(msg.current ?? "").trim();
        const pick = await vscode.window.showOpenDialog({
          canSelectFolders: true,
          canSelectFiles: false,
          canSelectMany: false,
          openLabel: "Choose location",
          defaultUri: cur ? vscode.Uri.file(cur) : undefined,
        });
        if (pick && pick[0] && panel) {
          panel.webview.postMessage({ type: "location", value: pick[0].fsPath });
        }
      } else if (msg?.type === "create") {
        const name = String(msg.name ?? "").trim();
        const location = String(msg.location ?? "").trim();
        const err = validateNewProject(name, location);
        if (err) {
          panel.webview.postMessage({ type: "error", value: err });
          return;
        }
        const ok = await createProject(location, name);
        if (ok) {
          panel.dispose(); // the window reloads on openFolder anyway
        } else if (panel) {
          panel.webview.postMessage({ type: "error", value: "Could not create the project." });
        }
      } else if (msg?.type === "cancel") {
        panel.dispose();
      }
    },
    null,
    context.subscriptions
  );

  panel.webview.html = render(panel.webview, context, defaultLocation(), path.sep);
}

/** Create <location>/<name> with a minimal board.yml + settings + Configure marker, then open it. */
async function createProject(location: string, name: string): Promise<boolean> {
  const projDir = vscode.Uri.file(path.join(location, name));
  const boardFile = vscode.Uri.joinPath(projDir, "board.yml");
  try {
    await vscode.workspace.fs.createDirectory(projDir);
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
        return false;
      }
    }
    const yaml = buildBoardYaml({ project: name, chip: "esp32c3", devices: [], needs: ["serial"] });
    await vscode.workspace.fs.writeFile(boardFile, Buffer.from(yaml, "utf8"));

    const settings: Record<string, unknown> = { "mcuflow.boardFile": "board.yml" };
    const launcher = portableLauncher();
    if (launcher) {
      settings["mcuflow.path"] = launcher;
    }
    await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(projDir, ".vscode"));
    await vscode.workspace.fs.writeFile(
      vscode.Uri.joinPath(projDir, ".vscode", "settings.json"),
      Buffer.from(JSON.stringify(settings, null, 2) + "\n", "utf8")
    );
    await vscode.workspace.fs.writeFile(
      vscode.Uri.joinPath(projDir, ".vscode", CONFIGURE_MARKER),
      Buffer.from("board.yml\n", "utf8")
    );
  } catch (e: any) {
    vscode.window.showErrorMessage(`Could not create project: ${e.message ?? e}`);
    return false;
  }
  // Reuse the current window so the new folder inherits THIS window's profile;
  // on reload, activate() sees the marker and runs Configure.
  await vscode.commands.executeCommand("vscode.openFolder", projDir, { forceNewWindow: false });
  return true;
}

function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string
  );
}

function nonceStr(): string {
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  let t = "";
  for (let i = 0; i < 32; i++) {
    t += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return t;
}

function render(
  webview: vscode.Webview,
  context: vscode.ExtensionContext,
  defaultLoc: string,
  sep: string
): string {
  const iconUri = webview.asWebviewUri(
    vscode.Uri.joinPath(context.extensionUri, "media", "icon.png")
  );
  const nonce = nonceStr();
  const csp = `default-src 'none'; img-src ${webview.cspSource}; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}';`;
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<style nonce="${nonce}">
  body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); padding: 0 24px 24px; }
  header { display:flex; align-items:center; gap:12px; padding: 22px 0 8px; }
  header img { width: 38px; height: 38px; }
  header h1 { font-size: 20px; margin: 0; }
  p.sub { color: var(--vscode-descriptionForeground); font-size: 13px; margin: 0 0 18px; }
  label { display:block; font-size: 12px; margin: 14px 0 4px; color: var(--vscode-descriptionForeground); }
  input[type=text] { width: 100%; box-sizing: border-box; padding: 7px 9px; font: inherit;
    color: var(--vscode-input-foreground); background: var(--vscode-input-background);
    border: 1px solid var(--vscode-input-border, #8884); border-radius: 4px; }
  input[type=text]:focus { outline: 1px solid var(--vscode-focusBorder); border-color: var(--vscode-focusBorder); }
  .row { display:flex; gap:8px; }
  .row input { flex:1; }
  button { font: inherit; padding: 7px 14px; border-radius: 4px; cursor: pointer; border: 1px solid transparent; }
  button.primary { background: var(--vscode-button-background); color: var(--vscode-button-foreground); }
  button.primary:hover { background: var(--vscode-button-hoverBackground); }
  button.secondary { background: var(--vscode-button-secondaryBackground, #3a3d41);
    color: var(--vscode-button-secondaryForeground, #fff); }
  button.secondary:hover { background: var(--vscode-button-secondaryHoverBackground, #45494e); }
  .preview { margin: 16px 0 4px; font-size: 12px; color: var(--vscode-descriptionForeground);
    font-family: var(--vscode-editor-font-family, monospace); word-break: break-all; }
  .preview b { color: var(--vscode-foreground); }
  .error { color: var(--vscode-inputValidation-errorForeground, #f85149); font-size: 12px; min-height: 16px; margin-top: 10px; }
  .actions { display:flex; gap:10px; margin-top: 20px; }
</style>
</head>
<body>
  <header>
    <img src="${iconUri}" alt="">
    <h1>New Project</h1>
  </header>
  <p class="sub">Create a folder with a starter <code>board.yml</code>. You'll choose the chip, devices, and test parameters right after it opens.</p>

  <label for="name">Project name</label>
  <input type="text" id="name" placeholder="my-mcu-project" autofocus>

  <label for="loc">Location</label>
  <div class="row">
    <input type="text" id="loc" value="${esc(defaultLoc)}">
    <button class="secondary" id="browse">Browse…</button>
  </div>

  <div class="preview" id="preview"></div>
  <div class="error" id="error"></div>

  <div class="actions">
    <button class="primary" id="create">Create</button>
    <button class="secondary" id="cancel">Cancel</button>
  </div>

<script nonce="${nonce}">
  const vscode = acquireVsCodeApi();
  const SEP = ${JSON.stringify(sep)};
  const nameEl = document.getElementById('name');
  const locEl = document.getElementById('loc');
  const preview = document.getElementById('preview');
  const error = document.getElementById('error');
  function trimSep(s){ return s.replace(/[\\\\/]+$/, ''); }
  function updatePreview(){
    const n = nameEl.value.trim(), l = trimSep(locEl.value.trim());
    preview.innerHTML = (n && l) ? 'Will create: <b>' + l + SEP + n + SEP + 'board.yml</b>' : '';
  }
  nameEl.addEventListener('input', () => { error.textContent=''; updatePreview(); });
  locEl.addEventListener('input', () => { error.textContent=''; updatePreview(); });
  document.getElementById('browse').addEventListener('click', () =>
    vscode.postMessage({ type:'browse', current: locEl.value.trim() }));
  document.getElementById('create').addEventListener('click', () =>
    vscode.postMessage({ type:'create', name: nameEl.value.trim(), location: trimSep(locEl.value.trim()) }));
  document.getElementById('cancel').addEventListener('click', () => vscode.postMessage({ type:'cancel' }));
  nameEl.addEventListener('keydown', (e) => { if (e.key === 'Enter') document.getElementById('create').click(); });
  window.addEventListener('message', (e) => {
    const m = e.data;
    if (m.type === 'location') { locEl.value = m.value; error.textContent=''; updatePreview(); }
    else if (m.type === 'error') { error.textContent = m.value; }
  });
  updatePreview();
</script>
</body>
</html>`;
}
