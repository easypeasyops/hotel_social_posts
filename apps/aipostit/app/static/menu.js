// The user menu is a <details data-menu>, which opens and closes without this script. This
// adds what people expect of a menu: Esc, a click outside it, or tabbing out of it closes it.
(function () {
  function closeAll(except, refocus) {
    document.querySelectorAll("details[data-menu][open]").forEach(function (menu) {
      if (menu.contains(except)) return;
      menu.open = false;
      if (refocus) menu.querySelector("summary").focus();
    });
  }
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeAll(null, true);
  });
  document.addEventListener("click", function (event) { closeAll(event.target, false); });
  document.addEventListener("focusin", function (event) { closeAll(event.target, false); });
})();
