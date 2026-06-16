// Shared webview plumbing for the extension's panels (Home, New Project).
//
// Every panel needs the same hardening: a strict Content-Security-Policy, a
// per-render nonce for the one <script>, escaped interpolation, and webview-safe
// URIs for assets. Centralizing it here keeps each panel to just its body markup
// and lets the CSS/JS live in their own files under media/ (separation of
// concerns) instead of being inlined as template-literal blobs.

import * as vscode from "vscode";

const NONCE_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";

/** HTML-escape a value before interpolating it into webview markup. */
export function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string
  );
}

/** A random nonce authorizing this render's single <script> under the CSP. */
export function nonce(): string {
  let t = "";
  for (let i = 0; i < 32; i++) {
    t += NONCE_CHARS.charAt(Math.floor(Math.random() * NONCE_CHARS.length));
  }
  return t;
}

/** webview-safe URI for a file under the extension's media/ folder. */
export function mediaUri(
  webview: vscode.Webview,
  extensionUri: vscode.Uri,
  file: string
): vscode.Uri {
  return webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, "media", file));
}

export interface ShellOptions {
  /** document <title>. */
  title: string;
  /** stylesheet filename under media/, e.g. "home.css". */
  style: string;
  /** client script filename under media/, e.g. "home.js". */
  script: string;
  /** the <body> inner HTML (escape any interpolated values yourself). */
  body: string;
  /** extra attributes for the <body> tag, already escaped (e.g. data-* state). */
  bodyAttrs?: string;
}

/**
 * Assemble a full webview document with the standard hardening: a strict CSP
 * (no inline script; styles and images only from the extension/webview), an
 * external stylesheet, and an external script authorized by a per-render nonce.
 * Callers supply only the body and the asset filenames, so markup, style, and
 * behavior each live in their own file.
 */
export function htmlShell(
  webview: vscode.Webview,
  extensionUri: vscode.Uri,
  opts: ShellOptions
): string {
  const n = nonce();
  const styleUri = mediaUri(webview, extensionUri, opts.style);
  const scriptUri = mediaUri(webview, extensionUri, opts.script);
  const csp =
    `default-src 'none'; img-src ${webview.cspSource}; ` +
    `style-src ${webview.cspSource}; script-src 'nonce-${n}';`;
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<link href="${styleUri}" rel="stylesheet">
<title>${esc(opts.title)}</title>
</head>
<body${opts.bodyAttrs ? " " + opts.bodyAttrs : ""}>
${opts.body}
<script nonce="${n}" src="${scriptUri}"></script>
</body>
</html>`;
}
