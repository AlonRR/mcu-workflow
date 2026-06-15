// The "MCU Flow" tree view: three top-level groups.
//   Boards  - from `mcuflow --json ports` (device, role, serial, kind)
//   Actions - clickable verbs (build / flash / monitor / run / ...)
//   Doctor  - from `mcuflow --json doctor` (tools, modules, ports)
//
// Refreshed on demand and after commands run. Tree reads are best-effort: if the
// CLI can't be resolved or a call fails, the group shows a single status row
// rather than throwing.

import * as vscode from "vscode";
import { resolve, runJson, Resolved } from "./cli";

type NodeKind = "group" | "board" | "action" | "info" | "error";

export class Node extends vscode.TreeItem {
  constructor(
    label: string,
    kind: NodeKind,
    collapsible: vscode.TreeItemCollapsibleState,
    public readonly children?: Node[]
  ) {
    super(label, collapsible);
    this.contextValue = kind;
  }
}

interface PortRow {
  device: string;
  kind: string;
  role: string;
  serial: string | null;
  description: string;
}
interface PortsReport {
  ports: PortRow[];
  boards: number;
  reason: string;
  dut: string | null;
  satellite: string | null;
}
interface DoctorReport {
  ok: boolean;
  tools: Record<string, string | null>;
  modules: Record<string, boolean>;
  ports: string[];
}

const ACTIONS: { label: string; command: string; icon: string }[] = [
  { label: "New Project", command: "mcuflow.newProject", icon: "file-add" },
  { label: "Refine board.yml with Agent", command: "mcuflow.refineWithAgent", icon: "sparkle" },
  { label: "Build", command: "mcuflow.build", icon: "tools" },
  { label: "Flash", command: "mcuflow.flash", icon: "zap" },
  { label: "Monitor Serial", command: "mcuflow.monitor", icon: "pulse" },
  { label: "Run (build → flash → HIL)", command: "mcuflow.run", icon: "run-all" },
  { label: "Test (HIL)", command: "mcuflow.test", icon: "beaker" },
  { label: "Validate board.yml", command: "mcuflow.validate", icon: "check" },
  { label: "Scaffold Project", command: "mcuflow.scaffold", icon: "new-folder" },
  { label: "Start Workbench", command: "mcuflow.workbench", icon: "server-process" },
  { label: "Bridge over Network", command: "mcuflow.bridge", icon: "broadcast" },
  { label: "Debug Server (JTAG)", command: "mcuflow.debug", icon: "debug-alt" },
  { label: "Open Port Viewer", command: "mcuflow.ports", icon: "plug" },
];

export class McuflowTree implements vscode.TreeDataProvider<Node> {
  private _onDidChange = new vscode.EventEmitter<Node | undefined | void>();
  readonly onDidChangeTreeData = this._onDidChange.event;

  constructor(private getSelectedPort: () => string | undefined) {}

  refresh(): void {
    this._onDidChange.fire();
  }

  getTreeItem(n: Node): vscode.TreeItem {
    return n;
  }

  async getChildren(node?: Node): Promise<Node[]> {
    if (node) {
      return node.children ?? [];
    }
    const r = resolve();
    if (!r) {
      const setup = new Node("Set up project…", "action", vscode.TreeItemCollapsibleState.None);
      setup.command = { command: "mcuflow.setup", title: "Set Up Project" };
      setup.iconPath = new vscode.ThemeIcon("rocket");
      return [setup];
    }
    return [
      await this.boardsGroup(r),
      this.actionsGroup(),
      await this.doctorGroup(r),
    ];
  }

  private async boardsGroup(r: Resolved): Promise<Node> {
    const children: Node[] = [];
    try {
      const rep = await runJson<PortsReport>(r, ["ports"]);
      const sel = this.getSelectedPort();
      if (rep.ports.length === 0) {
        children.push(this.info("No serial ports found"));
      }
      for (const p of rep.ports) {
        const isBoard = p.kind === "board";
        const n = new Node(p.device, "board", vscode.TreeItemCollapsibleState.None);
        const bits = [p.role || (isBoard ? "board" : p.kind)];
        if (p.serial) {
          bits.push(p.serial);
        }
        n.description = bits.join(" · ");
        n.tooltip = `${p.device}\n${p.description}\nrole: ${p.role || "—"}\nserial: ${
          p.serial || "—"
        }`;
        n.iconPath = new vscode.ThemeIcon(
          p.device === sel ? "circle-filled" : isBoard ? "circuit-board" : "plug"
        );
        n.command = {
          command: "mcuflow.selectPortValue",
          title: "Select this port",
          arguments: [p.device],
        };
        children.push(n);
      }
      if (rep.reason) {
        children.push(this.info(rep.reason));
      }
    } catch (e: any) {
      children.push(this.error(`ports: ${e.message ?? e}`));
    }
    const label = "Boards";
    const g = new Node(label, "group", vscode.TreeItemCollapsibleState.Expanded, children);
    g.iconPath = new vscode.ThemeIcon("circuit-board");
    return g;
  }

  private actionsGroup(): Node {
    const children = ACTIONS.map((a) => {
      const n = new Node(a.label, "action", vscode.TreeItemCollapsibleState.None);
      n.command = { command: a.command, title: a.label };
      n.iconPath = new vscode.ThemeIcon(a.icon);
      return n;
    });
    const g = new Node("Actions", "group", vscode.TreeItemCollapsibleState.Expanded, children);
    g.iconPath = new vscode.ThemeIcon("list-unordered");
    return g;
  }

  private async doctorGroup(r: Resolved): Promise<Node> {
    const children: Node[] = [];
    let ok = false;
    try {
      const d = await runJson<DoctorReport>(r, ["doctor"]);
      ok = d.ok;
      const tools = Object.entries(d.tools);
      for (const [name, p] of tools) {
        const n = new Node(name, "info", vscode.TreeItemCollapsibleState.None);
        n.description = p ? "found" : "missing";
        n.iconPath = new vscode.ThemeIcon(p ? "pass" : "circle-slash");
        n.tooltip = p ?? `${name} not found on PATH`;
        children.push(n);
      }
      const mods = Object.entries(d.modules)
        .filter(([, v]) => !v)
        .map(([k]) => k);
      if (mods.length) {
        children.push(this.error(`python modules missing: ${mods.join(", ")}`));
      }
      const fix = new Node("Install prerequisites…", "action", vscode.TreeItemCollapsibleState.None);
      fix.command = { command: "mcuflow.doctorFix", title: "Doctor: Install Prerequisites" };
      fix.iconPath = new vscode.ThemeIcon("cloud-download");
      children.push(fix);
    } catch (e: any) {
      children.push(this.error(`doctor: ${e.message ?? e}`));
    }
    const g = new Node(
      "Doctor",
      "group",
      vscode.TreeItemCollapsibleState.Collapsed,
      children
    );
    g.iconPath = new vscode.ThemeIcon(ok ? "heart-filled" : "heart");
    g.description = ok ? "ready" : "needs attention";
    return g;
  }

  private info(text: string): Node {
    const n = new Node(text, "info", vscode.TreeItemCollapsibleState.None);
    n.iconPath = new vscode.ThemeIcon("info");
    return n;
  }

  private error(text: string): Node {
    const n = new Node(text, "error", vscode.TreeItemCollapsibleState.None);
    n.iconPath = new vscode.ThemeIcon("warning");
    return n;
  }
}
