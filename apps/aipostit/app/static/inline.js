// Progressive enhancement, no build step. Without this script the forms post and redirect as
// before; with it:
// - A form marked data-inline="<id>" posts with fetch. The server answers as for a plain post
//   (the page, or a redirect to it, which fetch follows), and the element with that id is
//   swapped in from the answer, so the page neither reloads nor jumps. Focus goes to the new
//   [data-focus] element (the server's status message). A confirm() in onsubmit runs first.
// - A button with data-copy copies that text, shows data-copied for a moment and announces it;
//   where the clipboard isn't available it shows the text selected, to copy by hand.
(function () {
  var turkish = document.documentElement.lang === "tr";
  var live = document.createElement("p");
  live.className = "sr-only";
  live.setAttribute("aria-live", "polite");
  document.body.appendChild(live);

  function fail(form, status) {
    var note = form.nextElementSibling;
    if (!note || !note.hasAttribute("data-inline-error")) {
      note = document.createElement("p");
      note.setAttribute("data-inline-error", "");
      note.setAttribute("role", "alert");
      note.tabIndex = -1;
      note.className = "basis-full mt-2 text-sm text-red-700";
      form.after(note);
    }
    note.textContent = (turkish ? "Olmadı" : "That didn't work") + (status ? " (" + status + ")" : "") +
      (turkish ? ". Sayfayı yenileyip yeniden deneyin." : ". Reload the page and try again.");
    note.focus({ preventScroll: true });
  }

  document.addEventListener("submit", function (event) {
    var form = event.target, id = form.dataset.inline;
    if (!id || event.defaultPrevented) return;  // not ours, or confirm() said no
    event.preventDefault();
    var buttons = form.querySelectorAll("button");
    buttons.forEach(function (b) { b.disabled = true; });
    fetch(form.action, { method: "POST", body: new FormData(form) })
      .then(function (response) {
        if (!(response.headers.get("content-type") || "").startsWith("text/html")) {
          return fail(form, response.status);
        }
        return response.text().then(function (html) {
          var fresh = new DOMParser().parseFromString(html, "text/html").getElementById(id);
          if (!fresh) return location.assign(response.url);  // e.g. signed out: show that page
          var old = document.getElementById(id), y = window.scrollY;
          var open = Array.from(old.querySelectorAll("details[open][id]"), function (d) { return d.id; });
          old.outerHTML = fresh.outerHTML;
          open.forEach(function (o) { var d = document.getElementById(o); if (d) d.open = true; });
          window.scrollTo(window.scrollX, y);
          var focus = document.getElementById(id).querySelector("[data-focus]");
          if (focus) focus.focus({ preventScroll: true });
        });
      })
      .catch(function () { fail(form); })
      .finally(function () { buttons.forEach(function (b) { b.disabled = false; }); });
  });

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-copy]");
    if (!button) return;
    var text = button.dataset.copy;
    button.dataset.label = button.dataset.label || button.textContent;
    var copy = navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject();
    copy.then(function () {
      button.textContent = button.dataset.copied;
      live.textContent = button.dataset.copied;
      setTimeout(function () { button.textContent = button.dataset.label; live.textContent = ""; }, 2000);
    }, function () {
      var field = button.nextElementSibling;
      if (!field || !field.hasAttribute("data-copy-field")) {
        field = document.createElement("input");
        field.setAttribute("data-copy-field", "");
        field.readOnly = true;
        field.value = text;
        field.setAttribute("aria-label", button.dataset.label);
        field.className = "basis-full w-full mt-1 border border-gray-300 rounded px-2 py-1 text-sm";
        button.after(field);
      }
      field.focus();
      field.select();
    });
  });
})();
