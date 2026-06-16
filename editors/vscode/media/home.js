// Client script for the MCU Flow Home panel (see src/home.ts).
//
// The webview is untrusted: it never does privileged work itself, it only posts
// the user's intent to the extension host, which runs the matching command.
(function () {
  const vscode = acquireVsCodeApi();

  // Every card/link carries the command id (and optional arg) it should run.
  for (const el of document.querySelectorAll("[data-cmd]")) {
    el.addEventListener("click", () => {
      const id = el.getAttribute("data-cmd");
      const arg = el.getAttribute("data-arg");
      vscode.postMessage({ type: "cmd", id, args: arg ? [arg] : [] });
    });
  }

  const refresh = document.getElementById("refresh");
  if (refresh) {
    refresh.addEventListener("click", () => vscode.postMessage({ type: "refresh" }));
  }

  const startup = document.getElementById("startup");
  if (startup) {
    startup.addEventListener("change", (e) =>
      vscode.postMessage({ type: "setStartup", value: e.target.checked })
    );
  }
})();
