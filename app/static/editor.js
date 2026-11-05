// Страница мероприятия: вкладки и визуальный редактор данных/карточек.
// Источник правды — два textarea (колонки и JSON карточек): они уходят на сервер как есть.
// Редактор читает их при открытии и переписывает при каждой правке.
(() => {
  // ── вкладки страницы: «Рабочие места» / «Данные и страница участника» ──
  const root = document.getElementById("ptab-root");
  if (root) {
    const show = (name) => {
      if (!root.querySelector(`[data-ppane="${name}"]`)) name = root.dataset.default;
      document.querySelectorAll("[data-ptab]").forEach((t) => t.classList.toggle("active", t.dataset.ptab === name));
      root.querySelectorAll("[data-ppane]").forEach((p) => { p.hidden = p.dataset.ppane !== name; });
    };
    document.querySelectorAll("[data-ptab]").forEach((t) =>
      t.addEventListener("click", () => { history.replaceState(null, "", "#" + t.dataset.ptab); show(t.dataset.ptab); }));
    show(location.hash.slice(1) || root.dataset.default);
  }

  const form = document.getElementById("exam-form");
  if (!form) return;
  const colSrc = form.querySelector("#columns-src");
  const cardSrc = form.querySelector("#cards-src");
  const colBox = form.querySelector("#columns-ed");
  const cardBox = form.querySelector("#cards-ed");
  const preview = form.querySelector("#preview");
  const msg = form.querySelector("#editor-msg");
  let columns = [];
  let cards = [];

  const RU = { а:"a",б:"b",в:"v",г:"g",д:"d",е:"e",ё:"e",ж:"zh",з:"z",и:"i",й:"y",к:"k",л:"l",м:"m",н:"n",о:"o",п:"p",р:"r",с:"s",т:"t",у:"u",ф:"f",х:"h",ц:"c",ч:"ch",ш:"sh",щ:"sch",ъ:"",ы:"y",ь:"",э:"e",ю:"yu",я:"ya" };
  const toKey = (s) => {
    const k = s.toLowerCase().split("").map((c) => RU[c] ?? c).join("")
      .replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 28);
    return /^[a-z]/.test(k) ? k : (k ? "f_" + k : "field");
  };
  const uniqueKey = (base, self) => {
    let key = base, n = 2;
    while (columns.some((c) => c !== self && c.key === key)) key = `${base}_${n++}`;
    return key;
  };

  // ── мелкие помощники ────────────────────────────────────
  function h(tag, props = {}, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "class") n.className = v;
      else if (k === "value" || k === "checked") n[k] = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else if (v !== false && v != null) n.setAttribute(k, v === true ? "" : v);
    }
    n.append(...kids);
    return n;
  }
  const move = (arr, i, d) => {
    const j = i + d;
    if (j < 0 || j >= arr.length) return false;
    [arr[i], arr[j]] = [arr[j], arr[i]];
    return true;
  };
  const btn = (text, title, onclick, cls = "btn btn-ghost sm") =>
    h("button", { type: "button", class: cls, title, onclick }, text);
  const keyed = () => columns.filter((c) => c.key);

  // ── чтение / запись textarea ────────────────────────────
  function readColumns(text) {
    return text.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => {
      const [key, label, ...rest] = l.split(";").map((s) => s.trim());
      return { key, label: label || key, secret: rest.includes("secret"), prev: key };
    });
  }
  function finalizeKeys() {
    columns.forEach((c) => { if (!c.key && c.label.trim()) { c.key = uniqueKey(toKey(c.label), c); c.prev = c.key; } });
  }
  function sync() {
    colSrc.value = keyed().map((c) => [c.key, c.label || c.key, ...(c.secret ? ["secret"] : [])].join("; ")).join("\n");
    cardSrc.value = JSON.stringify(cards.map((c) => ({
      title: c.title,
      ...(c.subtitle && { subtitle: c.subtitle }),
      ...(c.icon && { icon: c.icon }),
      ...(c.badge && { badge: c.badge }),
      fields: c.fields.map((f) => ({
        label: f.label, value: f.value,
        ...(f.accent && { accent: true }), ...(f.link && { link: true }),
      })),
    })), null, 2);
    renderPreview();
  }
  const asColumn = (value) => {
    const m = /^\{(\w+)\}$/.exec(value);
    return m && columns.some((c) => c.key === m[1]) ? m[1] : null;
  };
  function load() {
    try {
      const parsed = JSON.parse(cardSrc.value || "[]");
      if (!Array.isArray(parsed)) throw new Error("ожидается список карточек");
      columns = readColumns(colSrc.value);
      cards = parsed.map((c) => ({
        title: c.title || "", subtitle: c.subtitle || "", icon: c.icon || "", badge: c.badge || "",
        fields: (c.fields || []).map((f) => ({
          label: f.label || "", value: f.value || "", accent: !!f.accent, link: !!f.link,
          text: asColumn(f.value || "") === null,                // «свой текст» или «данные места»
        })),
      }));
    } catch (e) {
      msg.textContent = "Карточки не удалось разобрать как JSON: " + e.message;
      msg.hidden = false;
      return false;
    }
    msg.hidden = true;
    renderColumns();
    renderCards();
    renderPreview();
    return true;
  }

  // ── превью: та же вёрстка, что у страницы участника ─────
  function renderPreview() {
    const label = (k) => columns.find((c) => c.key === k)?.label || k;
    const fill = (value) => {
      const out = [];
      value.split(/(\{\w+\})/).forEach((part) => {
        const m = /^\{(\w+)\}$/.exec(part);
        if (m) out.push(h("span", { class: "tok" }, `‹${label(m[1])}›`));
        else if (part) out.push(part);
      });
      return out;
    };
    if (!cards.length) {
      preview.replaceChildren(h("div", { class: "empty-note" }, "Добавьте карточку, и она появится здесь"));
      return;
    }
    preview.replaceChildren(h("div", { class: "grid" }, ...cards.map((c) =>
      h("section", { class: "card" },
        h("div", { class: "card-hdr" },
          ...(c.icon ? [h("div", { class: "card-icon" }, c.icon)] : []),
          h("div", {},
            h("div", { class: "card-title" }, c.title || "Без названия",
              ...(c.badge ? [h("span", { class: "card-badge" }, c.badge)] : [])),
            ...(c.subtitle ? [h("div", { class: "card-sub" }, c.subtitle)] : []))),
        h("div", { class: "card-body" }, ...c.fields.map((f) =>
          h("div", { class: "field" },
            h("div", { class: "field-lbl" }, f.label || "…"),
            h("div", { class: "field-val" + (f.accent ? " accent" : "") }, ...fill(f.value))))))
    )));
  }

  // ── колонки ─────────────────────────────────────────────
  function renameKey(from, to) {
    cards.forEach((c) => c.fields.forEach((f) => {
      f.value = f.value.split("{" + from + "}").join("{" + to + "}");
    }));
  }
  function renderColumns() {
    colBox.replaceChildren(...columns.map((c, i) => {
      const label = h("input", { class: "ed-grow", value: c.label, placeholder: "Название поля, например «Логин»",
        oninput: () => { c.label = label.value; if (c.key) { renderCards(); } sync(); },
        onchange: () => {                                   // ключ фиксируем, когда название дописано
          if (!c.key && c.label.trim()) { c.key = uniqueKey(toKey(c.label), c); c.prev = c.key; key.value = c.key; renderCards(); sync(); }
        } });
      const key = h("input", { class: "ed-key ed-key-in", value: c.key, placeholder: "ключ", maxlength: 32, spellcheck: "false",
        title: "Техническое имя: латиница, цифры, _",
        oninput: () => { c.key = key.value.trim(); sync(); },
        onchange: () => { if (c.prev && c.key && c.prev !== c.key) { renameKey(c.prev, c.key); } c.prev = c.key; renderCards(); sync(); } });
      const secret = h("input", { type: "checkbox", checked: c.secret, onchange: () => { c.secret = secret.checked; sync(); } });
      return h("div", { class: "ed-row" }, label, key,
        h("label", { class: "ed-check", title: "Пароль не показывается в списках админки" }, secret, " это пароль"),
        btn("↑", "Выше", () => { if (move(columns, i, -1)) { renderColumns(); renderCards(); sync(); } }),
        btn("↓", "Ниже", () => { if (move(columns, i, 1)) { renderColumns(); renderCards(); sync(); } }),
        btn("✕", "Удалить поле", () => { columns.splice(i, 1); renderColumns(); renderCards(); sync(); }, "btn btn-danger sm"));
    }), btn("+ поле данных", "Добавить поле", () => {
      columns.push({ key: "", label: "", secret: false, prev: "" });
      renderColumns(); sync();
      [...colBox.querySelectorAll(".ed-grow")].pop()?.focus();
    }, "btn btn-ghost sm ed-add"));
  }

  // ── карточки ────────────────────────────────────────────
  // Выбор источника значения: поле данных рабочего места или свой текст.
  function sourceSelect(f) {
    const sel = h("select", { "data-combo": "" });
    const group = h("optgroup", { label: "Данные рабочего места" });
    keyed().forEach((c) => group.append(new Option(c.label || c.key, "col:" + c.key)));
    sel.append(group, h("optgroup", { label: "Одинаково для всех" }, new Option("Свой текст", "text")));
    sel.value = f.text ? "text" : "col:" + asColumn(f.value);
    sel.addEventListener("change", () => {
      if (sel.value === "text") { f.text = true; if (asColumn(f.value)) f.value = ""; }
      else { f.text = false; f.value = "{" + sel.value.slice(4) + "}"; }
      renderCards(); sync();
    });
    return sel;
  }
  function fieldRow(card, f, i) {
    if (!f.text && asColumn(f.value) === null) f.text = true;   // колонку удалили — значение остаётся текстом
    const label = h("input", { class: "ed-label", value: f.label, placeholder: "Подпись поля",
      oninput: () => { f.label = label.value; sync(); } });
    const src = sourceSelect(f);
    let value = null, insert = null;
    if (f.text) {
      value = h("input", { class: "ed-mono ed-value", value: f.value, placeholder: "Текст, например адрес сервера", spellcheck: "false",
        oninput: () => { f.value = value.value; sync(); } });
      insert = h("select", { "data-combo": "", "data-placeholder": "＋ вставить данные места", title: "Вставить в текст данные места" });
      keyed().forEach((c) => insert.append(new Option(c.label || c.key, c.key)));
      insert.selectedIndex = -1;
      insert.addEventListener("change", () => {
        const at = value.selectionStart ?? value.value.length;
        value.value = value.value.slice(0, at) + "{" + insert.value + "}" + value.value.slice(value.selectionEnd ?? at);
        f.value = value.value; insert.selectedIndex = -1; insert.dataset.touched = ""; insert._combo.refresh(); sync(); value.focus();
      });
    }
    const toggle = (prop, text, title) => {
      const t = h("button", { type: "button", class: "tog" + (f[prop] ? " on" : ""), title, "aria-pressed": String(!!f[prop]),
        onclick: () => { f[prop] = !f[prop]; t.classList.toggle("on", f[prop]); t.setAttribute("aria-pressed", String(f[prop])); sync(); } }, text);
      return t;
    };
    const tools = h("div", { class: "ed-tools" },
      toggle("accent", "★", "Выделить значение цветом"),
      toggle("link", "🔗", "Показать как ссылку (только http/https)"),
      btn("↑", "Выше", () => { if (move(card.fields, i, -1)) { renderCards(); sync(); } }),
      btn("↓", "Ниже", () => { if (move(card.fields, i, 1)) { renderCards(); sync(); } }),
      btn("✕", "Удалить поле", () => { card.fields.splice(i, 1); renderCards(); sync(); }, "btn btn-danger sm"));
    return h("div", { class: "ed-field" }, label, src, tools, ...(value ? [value, h("div", { class: "ed-insert" }, insert)] : []));
  }
  const ICONS = ["🔑","🖥️","💻","🗄️","🌐","🔒","🛡️","🐞","⚙️","📦","🐳","🧪","📁","📝","🏆","⭐","🚀","🔧","📡","☁️","🐧","🪟","🐍","☕","🧠","📊","🔥","🎯"];
  function iconPicker(c) {
    const inp = h("input", { class: "ed-icon", value: c.icon, placeholder: "🙂", title: "Свой значок: вставьте любой эмодзи",
      oninput: () => { c.icon = inp.value; sync(); } });
    const pop = h("div", { class: "icon-pop", hidden: true },
      ...ICONS.map(ic => h("button", { type: "button", class: "icon-opt", onclick: () => { c.icon = ic; inp.value = ic; pop.hidden = true; sync(); } }, ic)),
      h("button", { type: "button", class: "icon-opt none", title: "Без значка", onclick: () => { c.icon = ""; inp.value = ""; pop.hidden = true; sync(); } }, "без"));
    const open = h("button", { type: "button", class: "btn btn-ghost sm", title: "Выбрать значок",
      onclick: (e) => { e.stopPropagation(); pop.hidden = !pop.hidden; } }, "▾");
    document.addEventListener("click", (e) => { if (!pop.contains(e.target)) pop.hidden = true; });
    return h("div", { class: "icon-pick" }, inp, open, pop);
  }
  function renderCards() {
    cardBox.replaceChildren(...cards.map((c, i) => {
      const bind = (prop, ph, cls) => {
        const el = h("input", { class: cls, value: c[prop], placeholder: ph, oninput: () => { c[prop] = el.value; sync(); } });
        return el;
      };
      return h("section", { class: "ed-card" },
        h("div", { class: "ed-row" },
          iconPicker(c), bind("title", "Название карточки", "ed-grow"),
          bind("subtitle", "Подзаголовок", "ed-grow"),
          btn("↑", "Карточку выше", () => { if (move(cards, i, -1)) { renderCards(); sync(); } }),
          btn("↓", "Карточку ниже", () => { if (move(cards, i, 1)) { renderCards(); sync(); } }),
          btn("✕", "Удалить карточку", () => { cards.splice(i, 1); renderCards(); sync(); }, "btn btn-danger sm")),
        ...c.fields.map((f, j) => fieldRow(c, f, j)),
        btn("+ поле", "Добавить поле в карточку", () => { c.fields.push({ label: "", value: "", accent: false, link: false, text: true }); renderCards(); sync(); }));
    }), btn("+ карточка", "Добавить карточку", () => {
      cards.push({ title: "", subtitle: "", icon: "", badge: "", fields: [{ label: "", value: "", accent: false, link: false, text: true }] });
      renderCards(); sync();
    }, "btn btn-ghost sm ed-add"));
    cardBox.querySelectorAll("select[data-combo]").forEach((s) => window.enhanceCombo(s));
  }

  // ── переключатели ───────────────────────────────────────
  form.querySelector("#show-keys").addEventListener("change", (e) => form.classList.toggle("show-keys", e.target.checked));
  form.addEventListener("submit", () => { if (!form.querySelector('[data-pane="visual"]').hidden) { finalizeKeys(); sync(); } });
  form.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => {
    const want = tab.dataset.tab;
    if (want === "visual" && !load()) return;       // JSON битый — остаёмся на вкладке JSON
    if (want === "json") { finalizeKeys(); sync(); }
    form.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    form.querySelectorAll("[data-pane]").forEach((p) => { p.hidden = p.dataset.pane !== want; });
  }));

  if (!load()) form.querySelector('[data-tab="json"]').click();   // сохранённый JSON не читается
})();
