// Выпадающий список вместо нативного <select>: с группами и поиском.
// Исходный <select> остаётся в форме (скрытый) и по-прежнему отправляет значение.
(() => {
  let current = null;                                   // открытый сейчас список

  const make = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };

  function enhance(select) {
    if (select._combo) return select._combo.refresh();
    if (select.dataset.placeholder && !select.dataset.touched) select.selectedIndex = -1;

    const btn = make("button", "combo-btn");
    btn.type = "button";
    const label = make("span", "combo-label");
    btn.append(label, make("span", "combo-caret", "▾"));
    select.after(btn);
    select.hidden = true;

    const refresh = () => {
      const o = select.options[select.selectedIndex];
      label.textContent = o ? o.textContent : (select.dataset.placeholder || "Выбрать…");
      label.classList.toggle("placeholder", !o);
    };

    function open() {
      if (current) current.close();
      const panel = make("div", "combo-panel");
      const list = make("div", "combo-list");
      let items = [];
      const total = select.options.length;
      const search = total > 7 ? make("input", "combo-search") : null;

      const build = (q = "") => {
        list.replaceChildren();
        items = [];
        const add = (parent, o) => {
          if (q && !o.textContent.toLowerCase().includes(q)) return false;
          const it = make("div", "combo-item", o.textContent);
          it.classList.toggle("selected", o.selected);
          it.addEventListener("mousedown", (e) => { e.preventDefault(); pick(o); });
          parent.append(it);
          items.push(it);
          it._opt = o;
          return true;
        };
        for (const child of select.children) {
          if (child.tagName === "OPTGROUP") {
            const box = make("div");
            const head = make("div", "combo-group", child.label);
            box.append(head);
            const any = [...child.children].map((o) => add(box, o)).some(Boolean);
            if (any) list.append(box);
          } else {
            add(list, child);
          }
        }
        if (!items.length) list.append(make("div", "combo-empty", "Ничего не найдено"));
        setActive(items.findIndex((i) => i.classList.contains("selected")));
      };

      let active = -1;
      const setActive = (i) => {
        items[active]?.classList.remove("active");
        active = items.length ? Math.max(0, Math.min(i < 0 ? 0 : i, items.length - 1)) : -1;
        items[active]?.classList.add("active");
        items[active]?.scrollIntoView({ block: "nearest" });
      };
      const pick = (o) => {
        select.value = o.value;
        select.dataset.touched = "1";
        refresh();
        close();
        select.dispatchEvent(new Event("change", { bubbles: true }));
      };
      const close = () => {
        panel.remove();
        document.removeEventListener("mousedown", outside, true);
        window.removeEventListener("resize", onScroll);
        window.removeEventListener("scroll", onScroll, true);
        current = null;
        btn.focus({ preventScroll: true });
      };
      const outside = (e) => { if (!panel.contains(e.target) && !btn.contains(e.target)) close(); };
      let reposition = () => {};
      const onScroll = (e) => { if (!panel.contains(e.target)) reposition(); };
      const onKey = (e) => {
        if (e.key === "ArrowDown") { e.preventDefault(); setActive(active + 1); }
        else if (e.key === "ArrowUp") { e.preventDefault(); setActive(active - 1); }
        else if (e.key === "Enter") { e.preventDefault(); if (items[active]) pick(items[active]._opt); }
        else if (e.key === "Escape") { e.preventDefault(); close(); }
      };

      panel.append(...(search ? [search] : []), list);
      document.body.append(panel);
      build();

      // позиция: под кнопкой, а если внизу тесно — над ней; при прокрутке страницы следует за кнопкой
      const place = () => {
        const r = btn.getBoundingClientRect();
        if (r.bottom < 0 || r.top > window.innerHeight) return close();
        const below = window.innerHeight - r.bottom - 12;
        const above = r.top - 12;
        const up = below < 220 && above > below;
        panel.style.left = r.left + "px";
        panel.style.minWidth = Math.max(r.width, 220) + "px";
        panel.style.maxHeight = Math.min(340, up ? above : below) + "px";
        panel.style.top = up ? "auto" : r.bottom + 4 + "px";
        panel.style.bottom = up ? window.innerHeight - r.top + 4 + "px" : "auto";
      };
      place();
      reposition = place;

      if (search) {
        search.placeholder = "Поиск…";
        search.addEventListener("input", () => build(search.value.trim().toLowerCase()));
        search.addEventListener("keydown", onKey);
        search.focus();
      } else {
        panel.tabIndex = -1;
        panel.addEventListener("keydown", onKey);
        panel.focus();
      }
      document.addEventListener("mousedown", outside, true);
      window.addEventListener("resize", onScroll);
      window.addEventListener("scroll", onScroll, true);
      current = { close };
    }

    btn.addEventListener("click", () => (current ? current.close() : open()));
    select._combo = { refresh };
    refresh();
  }

  window.enhanceCombo = enhance;
  document.querySelectorAll("select[data-combo]").forEach(enhance);
})();
