// Client script for the New MCU Flow Project panel (see src/newprojectpanel.ts).
//
// The webview only collects input and posts it; the extension host validates and
// creates the project. The path separator is passed in via body[data-sep] so the
// "Will create: …" preview matches the host OS.
(function () {
  const vscode = acquireVsCodeApi();
  const SEP = document.body.dataset.sep || "/";

  const nameEl = document.getElementById("name");
  const locEl = document.getElementById("loc");
  const preview = document.getElementById("preview");
  const error = document.getElementById("error");

  function trimSep(s) {
    return s.replace(/[\\/]+$/, "");
  }

  function updatePreview() {
    const n = nameEl.value.trim();
    const l = trimSep(locEl.value.trim());
    // Build with textContent so a typed name/location can never inject markup.
    preview.textContent = "";
    if (n && l) {
      preview.append("Will create: ");
      const b = document.createElement("b");
      b.textContent = l + SEP + n + SEP + "board.yml";
      preview.append(b);
    }
  }

  function clearError() {
    error.textContent = "";
  }

  nameEl.addEventListener("input", () => {
    clearError();
    updatePreview();
  });
  locEl.addEventListener("input", () => {
    clearError();
    updatePreview();
  });

  document.getElementById("browse").addEventListener("click", () =>
    vscode.postMessage({ type: "browse", current: locEl.value.trim() })
  );
  document.getElementById("create").addEventListener("click", () =>
    vscode.postMessage({
      type: "create",
      name: nameEl.value.trim(),
      location: trimSep(locEl.value.trim()),
    })
  );
  document.getElementById("cancel").addEventListener("click", () =>
    vscode.postMessage({ type: "cancel" })
  );
  nameEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      document.getElementById("create").click();
    }
  });

  window.addEventListener("message", (e) => {
    const m = e.data;
    if (m.type === "location") {
      locEl.value = m.value;
      clearError();
      updatePreview();
    } else if (m.type === "error") {
      error.textContent = m.value;
    }
  });

  updatePreview();
})();
