// копирование значений из карточек
document.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-copy]");
  if (!btn) return;
  const text = btn.dataset.copy;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
    } else {
      // http без TLS: clipboard API недоступен, копируем через textarea
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.cssText = "position:fixed;top:-9999px";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    btn.classList.add("copied");
    setTimeout(() => btn.classList.remove("copied"), 700);
  } catch (_) { /* не получилось — значение можно выделить руками */ }
});

// подтверждение опасных действий: <form data-confirm="...">
document.addEventListener("submit", (e) => {
  const msg = e.target.dataset.confirm;
  if (msg && !window.confirm(msg)) e.preventDefault();
});

// фильтр таблиц: <input data-filter="#table-id">
document.addEventListener("input", (e) => {
  const sel = e.target.dataset.filter;
  if (!sel) return;
  const q = e.target.value.trim().toLowerCase();
  document.querySelectorAll(sel + " tbody tr").forEach((tr) => {
    tr.hidden = !tr.textContent.toLowerCase().includes(q);
  });
});

// страница ожидания: как только статус сменился — перезагружаем
const pollUrl = document.body.dataset.poll;
if (pollUrl) {
  setInterval(async () => {
    try {
      const d = await (await fetch(pollUrl, { cache: "no-store" })).json();
      if (d.status !== "pending") {
        document.getElementById("status-text").textContent = "Готово, загружаем данные…";
        location.reload();
      }
    } catch (_) { /* сеть моргнула — попробуем на следующем тике */ }
  }, 2000);
}

// выбор файла: показываем имя рядом с кнопкой
document.addEventListener("change", (e) => {
  const input = e.target;
  if (input.type === "file" && input.closest(".file-pick")) {
    input.closest(".file-pick").querySelector(".file-name").textContent =
      input.files[0] ? input.files[0].name : "Файл не выбран";
  }
});

// глазик у полей с паролем: по умолчанию показаны точки, настоящее значение лежит в кнопке копирования
document.addEventListener("click", (e) => {
  const eye = e.target.closest("[data-reveal]");
  if (!eye) return;
  const row = eye.closest(".field-row");
  const val = row.querySelector(".field-val");
  const shown = val.dataset.shown === "1";
  val.textContent = shown ? "••••••••" : row.querySelector("[data-copy]").dataset.copy;
  val.dataset.shown = shown ? "0" : "1";
  eye.classList.toggle("on", !shown);
});
