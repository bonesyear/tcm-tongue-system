function tcmFlashWarnings(warnings, date) {
  if (!Array.isArray(warnings) || !warnings.length) return true;
  try {
    sessionStorage.setItem("tcm-record-warnings", JSON.stringify({date: date, messages: warnings}));
    return true;
  } catch (error) {
    alert(warnings.join("\n"));
    return false;
  }
}

function tcmShowWarnings(date, box) {
  var saved;
  try {
    saved = JSON.parse(sessionStorage.getItem("tcm-record-warnings") || "null");
    sessionStorage.removeItem("tcm-record-warnings");
  } catch (error) {
    return;
  }
  if (!saved || saved.date !== date || !Array.isArray(saved.messages)) return;
  var messages = saved.messages.filter(function (message) { return typeof message === "string"; });
  if (!messages.length) return;
  box.className = "alert-note";
  box.setAttribute("role", "status");
  box.setAttribute("aria-live", "polite");
  var title = document.createElement("strong");
  title.textContent = "保存成功，但请注意：";
  box.replaceChildren(title);
  messages.forEach(function (message) {
    var line = document.createElement("div");
    line.textContent = message;
    box.appendChild(line);
  });
  box.style.display = "";
}
