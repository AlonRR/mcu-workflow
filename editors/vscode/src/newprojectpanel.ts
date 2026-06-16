// The "New Project" panel - an in-editor webview form (like PlatformIO's New
// Project dialog) for choosing a location + name, instead of the native folder
// dialog. Browse still uses the OS folder picker, but it's optional; the panel
// is the primary UI. On Create it writes a minimal project and opens it.

import * as vscode from "vscode";
import * as path from "path";
import * as os from "os";
import { buildBoardYaml, validateNewProject, CONFIGURE_MARKER } from "./newproject";
import { portableLauncher } from "./cli";
import { esc, htmlShell, mediaUri } from "./webview";

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
    const yaml = buildBoardYaml({
      project: name,
      platform: "",
      chip: "",
      framework: "",
      devices: [],
      needs: [],
    });
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

function render(
  webview: vscode.Webview,
  context: vscode.ExtensionContext,
  defaultLoc: string,
  sep: string
): string {
  const iconUri = mediaUri(webview, context.extensionUri, "icon.png");
  const body = `
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
  </div>`;

  // The path separator is host-OS-specific; hand it to the client script via a
  // data attribute so the "Will create: …" preview matches the platform.
  return htmlShell(webview, context.extensionUri, {
    title: "New MCU Flow Project",
    style: "newproject.css",
    script: "newproject.js",
    body,
    bodyAttrs: `data-sep="${esc(sep)}"`,
  });
}
