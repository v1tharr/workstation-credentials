// Тема админки: выбор хранится в браузере, без выбора берём настройку системы.
// Скрипт подключён в <head> без defer, чтобы тема применялась до отрисовки (без мигания).
(function () {
  const root = document.documentElement;
  let saved = null;
  try { saved = localStorage.getItem("adm-theme"); } catch (e) {}
  const system = matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  root.dataset.theme = saved === "light" || saved === "dark" ? saved : system;

  document.addEventListener("click", (e) => {
    if (!e.target.closest("[data-theme-toggle]")) return;
    const next = root.dataset.theme === "light" ? "dark" : "light";
    root.dataset.theme = next;
    try { localStorage.setItem("adm-theme", next); } catch (err) {}
  });
})();
