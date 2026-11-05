// Подсветка пункта бокового меню: плавно переезжает между пунктами.
// Страницы грузятся заново, поэтому прошлое положение помним в sessionStorage
// и на новой странице «доезжаем» от него до текущего пункта.
(() => {
  const nav = document.getElementById("side-nav");
  const hl = nav && nav.querySelector(".side-hl");
  if (!hl) return;
  const links = [...nav.querySelectorAll("a")];
  const current = nav.querySelector("a.on");
  const KEY = "adm-nav-pos";
  const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;

  const place = (el) => {
    hl.style.height = el.offsetHeight + "px";
    hl.style.transform = `translateY(${el.offsetTop}px)`;
  };
  const save = () => { try { sessionStorage.setItem(KEY, String(hl.offsetTop)); } catch (e) {} };

  nav.dataset.hl = "1";
  if (!current) { hl.style.opacity = "0"; return; }

  let from = null;
  try { from = sessionStorage.getItem(KEY); } catch (e) {}
  if (from !== null && !calm) {
    hl.style.transition = "none";
    hl.style.height = current.offsetHeight + "px";
    hl.style.transform = `translateY(${Number(from)}px)`;
    hl.getBoundingClientRect();                      // зафиксировать стартовое положение
    hl.style.transition = "";
  }
  place(current);
  save();

  links.forEach((a) => {
    a.addEventListener("mouseenter", () => place(a));
    a.addEventListener("focus", () => place(a));
    a.addEventListener("click", () => { place(a); try { sessionStorage.setItem(KEY, String(a.offsetTop)); } catch (e) {} });
  });
  nav.addEventListener("mouseleave", () => place(current));
})();
