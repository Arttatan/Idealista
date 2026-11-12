const STATUSES = ["Новая", "Интересно", "Визит", "Отказ", "Оффер"];
const PRIORITIES = ["1 — смотреть первой", "2 — интересно", "3 — запасной вариант"];
const ENERGY_ORDER = ["A+", "A", "B", "C", "D", "E", "F", "G"];
const DEFAULT_DIR = { added: "desc", price: "asc", rent: "desc", yield: "desc", year: "desc" };

const state = {
  all: [],
  rates: {},
  view: localStorage.getItem("idealista-view") || "cards",
  theme: localStorage.getItem("idealista-theme") || "light",
  dir: "desc",
  selected: null,
  map: null,
  cluster: null,
  tiles: null,
  shared: false,
};

const timers = new Map();
let leafletPromise = null;

function el(tag, props, ...children) {
  const node = document.createElement(tag);
  Object.entries(props || {}).forEach(([key, value]) => {
    if (value == null || value === false) return;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (value === true) node.setAttribute(key, "");
    else node.setAttribute(key, String(value));
  });
  children.flat().forEach((child) => {
    if (child == null || child === false) return;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  });
  return node;
}

function fold(text) {
  return String(text || "").normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

function euroNumber(value) {
  return String(Math.round(value)).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

function euro(value) {
  if (value == null || value === "") return "—";
  return `${euroNumber(value)} €`;
}

function euroMonth(value) {
  return `${euroNumber(value)} €/мес`;
}

function pct(value) {
  if (value == null) return "";
  return `${value.toFixed(1).replace(".", ",")}%`;
}

function yearsLabel(value) {
  if (value == null) return "";
  const whole = Math.floor(value);
  const n10 = whole % 10;
  const n100 = whole % 100;
  let word = "лет";
  if (n10 === 1 && n100 !== 11) word = "год";
  else if (n10 >= 2 && n10 <= 4 && (n100 < 12 || n100 > 14)) word = "года";
  const text = Number.isInteger(value) ? String(value) : value.toFixed(1).replace(".", ",");
  return `${text} ${word}`;
}

function flats(count) {
  const n10 = count % 10;
  const n100 = count % 100;
  let word = "квартир";
  if (n10 === 1 && n100 !== 11) word = "квартира";
  else if (n10 >= 2 && n10 <= 4 && (n100 < 12 || n100 > 14)) word = "квартиры";
  return `${count} ${word}`;
}

function parseAdded(text) {
  if (!text) return null;
  const time = Date.parse(String(text).trim().replace(" ", "T"));
  return Number.isNaN(time) ? null : time;
}

function isNew(item) {
  const time = parseAdded(item.added);
  // Окно как у фильтра Idealista «последние 48 часов».
  return time != null && Date.now() - time < 48 * 60 * 60 * 1000;
}

function energyClass(letter) {
  if (!letter) return "";
  return letter === "A+" ? "e-Aplus" : `e-${letter}`;
}

function accClass(accuracy) {
  if (!accuracy) return "acc-mid";
  if (accuracy.startsWith("выс")) return "acc-high";
  if (accuracy.startsWith("низ")) return "acc-low";
  return "acc-mid";
}

function byId(id) {
  return state.all.find((item) => item.id === id);
}

function numOrNull(text) {
  const digits = String(text || "").replace(/[^\d]/g, "");
  if (!digits) return null;
  return Number(digits);
}

function blob(item) {
  const parts = [
    item.city, item.neighborhood, item.district, item.address, item.kind,
    item.agency, item.condition, item.year, item.energy, item.id, item.url,
    ...item.facts.map((fact) => `${fact.label} ${fact.value}`),
    ...Object.values(item.notes || {}),
  ];
  return fold(parts.join(" "));
}

function sortValue(item, key) {
  if (key === "price") return item.price;
  if (key === "rent") return item.rent && item.rent.rent;
  if (key === "yield") return item.rent && item.rent.yield_pct;
  if (key === "year") return item.year ? Number(item.year) : null;
  return parseAdded(item.added);
}

function filtered() {
  const query = fold(document.getElementById("q").value.trim());
  const cities = selectedValues("f-city");
  const min = numOrNull(document.getElementById("f-min").value);
  const max = numOrNull(document.getElementById("f-max").value);
  const energies = selectedValues("f-energy");
  const conditions = selectedValues("f-cond");
  const statuses = selectedValues("f-status");
  const years = selectedValues("f-year");
  const favOnly = document.getElementById("f-fav").checked;
  const newOnly = document.getElementById("f-new").checked;
  const park = document.getElementById("f-park").checked;
  const lift = document.getElementById("f-lift").checked;
  const sortKey = document.getElementById("sort").value;
  const direction = state.dir === "asc" ? 1 : -1;
  const items = state.all.filter((item) => {
    if (cities.length && !cities.includes(item.city)) return false;
    if (min != null && !(item.price >= min)) return false;
    if (max != null && !(item.price <= max)) return false;
    if (energies.length) {
      const match = energies.some((value) => (value === "__empty__" ? !item.energy : item.energy === value));
      if (!match) return false;
    }
    if (conditions.length && !conditions.includes(item.condition)) return false;
    if (statuses.length && !statuses.includes(item.notes.Статус || "")) return false;
    if (years.length) {
      const year = item.year ? String(item.year) : "";
      const match = years.some((value) => (value === "__empty__" ? !year : year === value));
      if (!match) return false;
    }
    if (favOnly && !item.notes["Избранное"]) return false;
    if (newOnly && !isNew(item)) return false;
    if (park && item.parking !== "Да") return false;
    if (lift && item.lift !== "Да") return false;
    if (query && !blob(item).includes(query)) return false;
    return true;
  });
  items.sort((a, b) => {
    const aFav = Boolean(a.notes && a.notes["Избранное"]);
    const bFav = Boolean(b.notes && b.notes["Избранное"]);
    if (aFav !== bFav) return aFav ? -1 : 1;
    const aNew = isNew(a);
    const bNew = isNew(b);
    if (aNew !== bNew) return aNew ? -1 : 1;
    const left = sortValue(a, sortKey);
    const right = sortValue(b, sortKey);
    const leftMissing = left == null || left === "";
    const rightMissing = right == null || right === "";
    if (leftMissing && rightMissing) return 0;
    if (leftMissing) return 1;
    if (rightMissing) return -1;
    if (left === right) return 0;
    return left > right ? direction : -direction;
  });
  return items;
}

function rentBlock(rent) {
  if (!rent || rent.rent == null) {
    return el("div", { class: "rent" },
      el("div", { class: "rent-kicker", text: "Оценка аренды" }),
      el("div", { class: "rent-main", text: "Нет ставки" }),
      el("span", { class: "acc acc-low", text: "низкая точность" }));
  }
  return el("div", { class: "rent" },
    el("div", { class: "rent-kicker", text: "Оценка аренды" }),
    el("div", { class: "rent-main", text: euroMonth(rent.rent) }),
    el("div", { class: "rent-range", text: `${euroNumber(rent.rent_min)} – ${euroNumber(rent.rent_max)} €` }),
    rent.yield_pct != null ? el("div", { class: "rent-yield", text: `${pct(rent.yield_pct)} валовых · окупаемость ${yearsLabel(rent.payback_years)}` }) : null,
    el("span", { class: `acc ${accClass(rent.accuracy)}`, text: rent.accuracy }));
}

function starButton(item) {
  const on = Boolean(item.notes && item.notes["Избранное"]);
  return el("button", {
    type: "button",
    class: "star",
    "data-star": item.id,
    "aria-pressed": on ? "true" : "false",
    "aria-label": on ? "Убрать из избранного" : "В избранное",
    text: on ? "★" : "☆",
    onClick: (event) => {
      event.stopPropagation();
      toggleFavorite(item);
    },
  });
}

function flags(item) {
  const nodes = [];
  if (isNew(item)) nodes.push(el("span", { class: "badge is-new-badge", text: "новая" }));
  if (item.tenant === "Да") nodes.push(el("span", { class: "warn", text: "сдана" }));
  const status = item.notes && item.notes["Статус"];
  if (status && status !== "Новая") nodes.push(el("span", { class: "status", text: status }));
  return nodes;
}

function metaRow(item) {
  return el("div", { class: "meta" },
    el("span", { text: item.condition || "состояние не указано" }),
    item.energy
      ? el("span", { class: `energy ${energyClass(item.energy)}`, text: item.energy })
      : el("span", { text: "класс не указан" }),
    el("span", { text: item.year ? String(item.year) : "год не указан" }));
}

function openLink(item, className) {
  if (!item.url) return null;
  return el("a", {
    class: className || "open",
    href: item.url,
    target: "_blank",
    rel: "noopener noreferrer",
    text: "Открыть на Idealista",
    onClick: (event) => event.stopPropagation(),
  });
}

function cardView(item) {
  const card = el("article", { class: isNew(item) ? "card is-new" : "card", tabindex: "0" },
    item.photo ? el("img", { class: "photo", src: item.photo, alt: "" }) : null,
    el("div", { class: "card-top" },
      el("div", {},
        el("p", { class: "kicker", text: item.district ? `округ ${item.district}` : "Португалия" }),
        el("div", { class: "flags" }, ...flags(item))),
      starButton(item)),
    el("h2", { class: "place-name", text: item.city || "Город не указан" }),
    el("p", { class: "neighborhood", text: [item.neighborhood, item.kind].filter(Boolean).join(" · ") }),
    el("p", { class: "price", text: euro(item.price) }),
    rentBlock(item.rent),
    metaRow(item),
    openLink(item));
  card.dataset.id = item.id;
  card.addEventListener("click", (event) => {
    const raw = event.target;
    const target = raw instanceof Element ? raw : raw && raw.parentElement;
    if (target && target.closest("a, button")) return;
    openPanel(item.id);
  });
  card.addEventListener("keydown", (event) => {
    if (event.key === "Enter") openPanel(item.id);
  });
  return card;
}

function tableLink(item) {
  if (!item.url) return el("span", { text: "—" });
  return el("a", {
    href: item.url,
    target: "_blank",
    rel: "noopener noreferrer",
    text: "Открыть",
    onClick: (event) => event.stopPropagation(),
  });
}

function rentCell(item) {
  const rent = item.rent || {};
  if (rent.rent == null) {
    return el("td", { class: "rent-cell", "data-label": "Оценка аренды" },
      "Нет ставки",
      el("small", { text: "низкая точность" }));
  }
  return el("td", { class: "rent-cell", "data-label": "Оценка аренды" },
    euroMonth(rent.rent),
    el("small", { text: `${euroNumber(rent.rent_min)} – ${euroNumber(rent.rent_max)} €` }),
    rent.yield_pct != null ? el("small", { text: `${pct(rent.yield_pct)} · ${yearsLabel(rent.payback_years)}` }) : null,
    el("small", { text: rent.accuracy }));
}

function nearCell(label, info) {
  const data = info || {};
  const text = data.text || "—";
  const cell = el("td", { class: "near-cell", "data-label": label, text });
  if (data.full) cell.title = data.full;
  return cell;
}

function statusSelect(item) {
  const current = (item.notes && item.notes["Статус"]) || "Новая";
  const values = [...STATUSES];
  if (current && !values.includes(current)) values.unshift(current);
  const select = el("select", {
    class: "table-status",
    "aria-label": "Статус",
    onClick: (event) => event.stopPropagation(),
    onChange: (event) => {
      event.stopPropagation();
      scheduleSave(item.id, { "Статус": event.target.value });
    },
  }, ...values.map((value) => el("option", { value, text: value })));
  select.value = current;
  return select;
}

function tableView(items) {
  const head = el("tr", {},
    el("th", { class: "col-fav", text: "★" }),
    el("th", { class: "col-status", text: "Статус" }),
    el("th", { class: "col-link", text: "Ссылка" }),
    el("th", { class: "col-place", text: "Город / район" }),
    el("th", { class: "col-price" }, el("button", { type: "button", text: "Цена", onClick: () => sortBy("price") })),
    el("th", { class: "col-rent" }, el("button", { type: "button", text: "Оценка аренды", onClick: () => sortBy("rent") })),
    el("th", { class: "col-near", text: "Метро" }),
    el("th", { class: "col-near", text: "Магазин" }),
    el("th", { class: "col-state", text: "Состояние" }),
    el("th", { class: "col-energy", text: "Класс" }),
    el("th", { class: "col-year" }, el("button", { type: "button", text: "Год", onClick: () => sortBy("year") })));
  const body = el("tbody");
  items.forEach((item) => {
    const row = el("tr", { class: isNew(item) ? "is-new" : "" },
      el("td", { class: "fav-cell", "data-label": "Избранное" }, starButton(item)),
      el("td", { "data-label": "Статус" }, statusSelect(item)),
      el("td", { "data-label": "Ссылка" }, tableLink(item)),
      el("td", { "data-label": "Город / район", text: item.place || item.city }),
      el("td", { "data-label": "Цена", text: euro(item.price) }),
      rentCell(item),
      nearCell("Метро", item.metro && item.metro.full ? item.metro : item.transit),
      nearCell("Магазин", item.shop),
      el("td", { "data-label": "Состояние", text: item.condition || "—" }),
      el("td", { "data-label": "Энергокласс" }, item.energy
        ? el("span", { class: `energy ${energyClass(item.energy)}`, text: item.energy })
        : "—"),
      el("td", { "data-label": "Год постройки", text: item.year || "—" }));
    row.addEventListener("click", (event) => {
      const raw = event.target;
      const target = raw instanceof Element ? raw : raw && raw.parentElement;
      if (target && target.closest("a, button, select, label")) return;
      openPanel(item.id);
    });
    body.append(row);
  });
  return el("div", { class: "table-wrap" }, el("table", {}, el("thead", {}, head), body));
}

function renderList(items) {
  const list = document.getElementById("list");
  if (state.view === "table") {
    list.replaceChildren(tableView(items));
    return;
  }
  const grid = el("div", { class: "cards" });
  items.forEach((item) => grid.append(cardView(item)));
  list.replaceChildren(grid);
}

function applyControls() {
  const items = filtered();
  const total = state.all.length;
  const count = document.getElementById("count");
  count.textContent = items.length === total
    ? `${flats(total)} · Порту и Брага`
    : `${items.length} из ${flats(total)}`;
  document.getElementById("empty").classList.toggle("hidden", items.length !== 0 || state.view === "map");
  if (state.view === "map") {
    document.getElementById("list").classList.add("hidden");
    rebuildMarkers(items);
  } else {
    document.getElementById("list").classList.remove("hidden");
    renderList(items);
  }
}

function sortBy(key) {
  const select = document.getElementById("sort");
  if (select.value === key) state.dir = state.dir === "asc" ? "desc" : "asc";
  else {
    select.value = key;
    state.dir = DEFAULT_DIR[key] || "desc";
  }
  paintDir();
  applyControls();
}

function paintDir() {
  const button = document.getElementById("sort-dir");
  const desc = state.dir !== "asc";
  button.textContent = desc ? "↓" : "↑";
  button.setAttribute("aria-label", desc ? "По убыванию" : "По возрастанию");
}

function selectedValues(id) {
  return [...document.querySelectorAll(`#${id} input[type="checkbox"]:checked`)].map((input) => input.value);
}

function paintMultiSummary(id, emptyLabel) {
  const picked = selectedValues(id);
  const summary = document.getElementById(`${id}-summary`);
  if (!picked.length) {
    summary.textContent = emptyLabel;
    return;
  }
  if (picked.length <= 2) {
    summary.textContent = picked.map((value) => (value === "__empty__" ? "не указан" : value)).join(", ");
    return;
  }
  summary.textContent = `Выбрано: ${picked.length}`;
}

function fillMulti(id, options, emptyLabel) {
  const box = document.getElementById(id);
  const kept = new Set(selectedValues(id));
  box.replaceChildren();
  options.forEach(({ value, label }) => {
    const input = el("input", { type: "checkbox", value });
    input.checked = kept.has(value);
    input.addEventListener("change", () => {
      paintMultiSummary(id, emptyLabel);
      applyControls();
    });
    box.append(el("label", {}, input, label));
  });
  paintMultiSummary(id, emptyLabel);
}

function clearMulti(id, emptyLabel) {
  document.querySelectorAll(`#${id} input[type="checkbox"]`).forEach((input) => {
    input.checked = false;
  });
  paintMultiSummary(id, emptyLabel);
}

function fillFilters() {
  const cities = [...new Set(state.all.map((item) => item.city).filter(Boolean))].sort((a, b) => a.localeCompare(b, "pt"));
  const conditions = [...new Set(state.all.map((item) => item.condition).filter(Boolean))].sort((a, b) => a.localeCompare(b, "ru"));
  const energies = ENERGY_ORDER.filter((letter) => state.all.some((item) => item.energy === letter));
  const extraEnergy = [...new Set(state.all.map((item) => item.energy).filter((letter) => letter && !energies.includes(letter)))];
  const statuses = [...new Set([...STATUSES, ...state.all.map((item) => item.notes.Статус).filter(Boolean)])];
  fillMulti("f-city", cities.map((value) => ({ value, label: value })), "Все города");
  fillMulti("f-cond", conditions.map((value) => ({ value, label: value })), "Любое");
  fillMulti("f-status", statuses.map((value) => ({ value, label: value })), "Любой");
  const energyOptions = [...energies, ...extraEnergy].map((letter) => ({ value: letter, label: letter }));
  if (state.all.some((item) => !item.energy)) energyOptions.push({ value: "__empty__", label: "не указан" });
  fillMulti("f-energy", energyOptions, "Любой");
  const years = [...new Set(state.all.map((item) => item.year).filter(Boolean).map(String))]
    .sort((a, b) => Number(b) - Number(a));
  const yearOptions = years.map((value) => ({ value, label: value }));
  if (state.all.some((item) => !item.year)) yearOptions.push({ value: "__empty__", label: "не указан" });
  fillMulti("f-year", yearOptions, "Любой");
}

function fieldSelect(name, label, values, current, wide) {
  const options = [];
  const list = [...values];
  if (current && !list.includes(current)) list.unshift(current);
  list.forEach((value) => options.push(el("option", { value, text: value || "не выбран" })));
  const select = el("select", { name }, ...options);
  select.value = current || "";
  return el("label", { class: wide ? "wide" : "" }, label, select);
}

function fieldText(name, label, value, wide, multiline) {
  const control = multiline
    ? el("textarea", { name, rows: "3" })
    : el("input", { name, type: "text", value: value || "" });
  if (multiline) control.value = value || "";
  return el("label", { class: wide ? "wide" : "" }, label, control);
}

function openPanel(id) {
  const item = byId(id);
  if (!item) return;
  state.selected = id;
  const notes = item.notes;
  const form = el("form", { class: "form-grid" },
    fieldSelect("Статус", "Статус", STATUSES, notes["Статус"], false),
    fieldSelect("Приоритет", "Приоритет", ["", ...PRIORITIES], notes["Приоритет"], false),
    fieldSelect("Запланирован визит", "Запланирован визит", ["Нет", "Да"], notes["Запланирован визит"] || "Нет", false),
    fieldText("Дата визита", "Дата визита", notes["Дата визита"], false, false),
    fieldText("Телефон", "Телефон", notes["Телефон"], false, false),
    fieldSelect("Просмотрено", "Просмотрено", ["Нет", "Да"], notes["Просмотрено"] || "Нет", false),
    fieldText("Заметки", "Заметки", notes["Заметки"], true, true),
    fieldText("Плюсы", "Плюсы", notes["Плюсы"], true, true),
    fieldText("Минусы", "Минусы", notes["Минусы"], true, true),
    fieldText("Причина отказа", "Причина отказа", notes["Причина отказа"], true, true));
  form.addEventListener("submit", (event) => event.preventDefault());
  form.addEventListener("input", (event) => {
    const field = event.target.name;
    if (!field) return;
    scheduleSave(item.id, { [field]: event.target.value });
  });

  const facts = el("dl", { class: "facts" });
  item.facts.forEach((fact) => {
    const value = fact.href
      ? el("a", { href: fact.href, target: "_blank", rel: "noopener noreferrer", text: "открыть" })
      : fact.value;
    facts.append(el("div", {}, el("dt", { text: fact.label }), el("dd", {}, value)));
  });

  const rent = item.rent || {};
  const panel = document.getElementById("panel");
  panel.replaceChildren(
    el("div", { class: "panel-head" },
      el("div", {},
        el("p", { class: "kicker", text: item.district ? `округ ${item.district}` : "" }),
        el("h2", { text: item.city || "Квартира" }),
        el("p", { class: "neighborhood", text: [item.neighborhood, item.kind].filter(Boolean).join(" · ") })),
      el("div", {}, starButton(item), el("button", {
        type: "button", class: "icon-btn", text: "×", "aria-label": "Закрыть", onClick: closePanel,
      }))),
    item.photo ? el("img", { class: "photo", src: item.photo, alt: "" }) : null,
    el("p", { class: "price", text: euro(item.price) }),
    rentBlock(rent),
    rent.reason ? el("p", { class: "reason", text: rent.reason }) : null,
    rent.source_url ? el("p", { class: "reason" }, el("a", {
      href: rent.source_url, target: "_blank", rel: "noopener noreferrer", text: "Источник ставки",
    })) : null,
    el("div", { class: "actions" },
      openLink(item),
      item.lat != null ? el("button", { type: "button", class: "ghost", text: "На карте", onClick: () => focusOnMap(item) }) : null),
    metaRow(item),
    el("div", { class: "flags" }, ...flags(item)),
    facts,
    el("h3", { class: "form-title", text: "Мои пометки" }),
    form,
    el("p", { class: "save-state", id: "save-state", text: "Правки сохраняются сами" }));
  panel.classList.remove("hidden");
  panel.setAttribute("aria-hidden", "false");
  document.getElementById("backdrop").classList.remove("hidden");
  document.body.classList.add("panel-open");
}

function closePanel() {
  flushSaves();
  state.selected = null;
  document.getElementById("panel").classList.add("hidden");
  document.getElementById("panel").setAttribute("aria-hidden", "true");
  document.getElementById("backdrop").classList.add("hidden");
  document.body.classList.remove("panel-open");
}

function setSaveState(text) {
  const node = document.getElementById("save-state");
  if (node) node.textContent = text;
}

function scheduleSave(id, patch) {
  const item = byId(id);
  if (!item) return;
  Object.assign(item.notes, patch);
  const pending = timers.get(id) || { patch: {} };
  clearTimeout(pending.timer);
  const merged = { ...pending.patch, ...patch };
  const timer = setTimeout(() => {
    timers.delete(id);
    commit(id, merged);
  }, 400);
  timers.set(id, { timer, patch: merged });
  setSaveState("Сохраняю…");
}

function flushSaves() {
  timers.forEach((job, id) => {
    clearTimeout(job.timer);
    commit(id, job.patch);
  });
  timers.clear();
}

function browserNotes() {
  try {
    const parsed = JSON.parse(localStorage.getItem("idealista-browser-notes") || "{}");
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (error) {
    return {};
  }
}

function rememberBrowserNote(id, patch) {
  const saved = browserNotes();
  saved[id] = { ...(saved[id] || {}), ...patch };
  localStorage.setItem("idealista-browser-notes", JSON.stringify(saved));
}

function applyBrowserNotes(listings) {
  const saved = browserNotes();
  listings.forEach((item) => {
    if (saved[item.id]) item.notes = { ...item.notes, ...saved[item.id] };
  });
}

async function commit(id, patch) {
  const item = byId(id);
  if (state.shared) {
    if (item) Object.assign(item.notes, patch);
    rememberBrowserNote(id, patch);
    setSaveState("Сохранено в этом браузере");
    paintStars(id, Boolean(item && item.notes["Избранное"]));
    if ("Статус" in patch || "Избранное" in patch) {
      const y = window.scrollY;
      applyControls();
      window.scrollTo(0, y);
    }
    return;
  }
  try {
    const response = await fetch("api/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, notes: patch }),
    });
    if (!response.ok) throw new Error("save");
    const data = await response.json();
    if (item && data.notes) item.notes = data.notes;
    setSaveState("Сохранено");
    paintStars(id, Boolean(item && item.notes["Избранное"]));
    if ("Статус" in patch || "Избранное" in patch) {
      const y = window.scrollY;
      applyControls();
      window.scrollTo(0, y);
    }
  } catch (error) {
    setSaveState("Не сохранилось");
  }
}

function paintStars(id, on) {
  document.querySelectorAll(`[data-star="${id}"]`).forEach((button) => {
    button.textContent = on ? "★" : "☆";
    button.setAttribute("aria-pressed", on ? "true" : "false");
    button.setAttribute("aria-label", on ? "Убрать из избранного" : "В избранное");
  });
}

function toggleFavorite(item) {
  const next = !item.notes["Избранное"];
  item.notes["Избранное"] = next;
  paintStars(item.id, next);
  commit(item.id, { "Избранное": next });
}

function loadCss(href) {
  if (document.querySelector(`link[href="${href}"]`)) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  document.head.append(link);
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.onload = resolve;
    script.onerror = reject;
    document.head.append(script);
  });
}

function ensureLeaflet() {
  if (window.L && window.L.markerClusterGroup) return Promise.resolve();
  if (!leafletPromise) {
    leafletPromise = (async () => {
      loadCss("https://unpkg.com/leaflet@1.9.4/dist/leaflet.css");
      loadCss("https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css");
      loadCss("https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css");
      await loadScript("https://unpkg.com/leaflet@1.9.4/dist/leaflet.js");
      await loadScript("https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js");
    })().catch((error) => {
      leafletPromise = null;
      throw error;
    });
  }
  return leafletPromise;
}

function tileLayer() {
  return L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  });
}

async function ensureMap() {
  const error = document.getElementById("map-error");
  try {
    await ensureLeaflet();
  } catch (loadError) {
    error.textContent = "Карта не загрузилась. Для неё нужен интернет: подложка OpenStreetMap.";
    error.classList.remove("hidden");
    return false;
  }
  error.classList.add("hidden");
  if (!state.map) {
    state.map = L.map("map", { scrollWheelZoom: true });
    state.tiles = tileLayer(state.theme).addTo(state.map);
    state.cluster = L.markerClusterGroup({ showCoverageOnHover: false, maxClusterRadius: 42 });
    state.map.addLayer(state.cluster);
    state.map.setView([41.2, -8.45], 9);
  }
  return true;
}

function rebuildMarkers(items) {
  if (!state.cluster) return;
  state.cluster.clearLayers();
  const bounds = [];
  items.forEach((item) => {
    if (item.lat == null || item.lon == null) return;
    const low = !item.rent || item.rent.rent == null;
    const icon = L.divIcon({
      className: "pin-wrap",
      html: `<div class="pin${low ? " low" : ""}">${euro(item.price)}</div>`,
      iconSize: [96, 30],
      iconAnchor: [48, 30],
    });
    const marker = L.marker([item.lat, item.lon], { icon });
    const rentText = item.rent && item.rent.rent != null ? euroMonth(item.rent.rent) : "нет ставки";
    marker.bindTooltip(`${item.place || item.city}<br>${rentText}`, { direction: "top", offset: [0, -28] });
    marker.on("click", () => openPanel(item.id));
    state.cluster.addLayer(marker);
    bounds.push([item.lat, item.lon]);
  });
  if (bounds.length) state.map.fitBounds(bounds, { padding: [28, 28], maxZoom: 13 });
  setTimeout(() => state.map.invalidateSize(), 50);
}

async function setView(name) {
  state.view = name;
  localStorage.setItem("idealista-view", name);
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.setAttribute("aria-pressed", button.getAttribute("data-view") === name ? "true" : "false");
  });
  const list = document.getElementById("list");
  const map = document.getElementById("map");
  if (name === "map") {
    list.classList.add("hidden");
    map.classList.remove("hidden");
    const ready = await ensureMap();
    if (ready) {
      applyControls();
      setTimeout(() => state.map.invalidateSize(), 80);
    }
    return;
  }
  map.classList.add("hidden");
  document.getElementById("map-error").classList.add("hidden");
  list.classList.remove("hidden");
  applyControls();
}

async function focusOnMap(item) {
  closePanel();
  await setView("map");
  if (state.map && item.lat != null) state.map.setView([item.lat, item.lon], 16);
}

function applyTheme(theme) {
  state.theme = theme;
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("idealista-theme", theme);
  document.getElementById("theme").textContent = theme === "dark" ? "Светлая" : "Тёмная";
  if (state.map) state.map.invalidateSize();
}

function bind() {
  document.getElementById("q").addEventListener("input", applyControls);
  ["f-min", "f-max"].forEach((id) => document.getElementById(id).addEventListener("input", applyControls));
  document.getElementById("f-fav").addEventListener("change", applyControls);
  document.getElementById("f-new").addEventListener("change", applyControls);
  document.getElementById("f-park").addEventListener("change", applyControls);
  document.getElementById("f-lift").addEventListener("change", applyControls);
  document.addEventListener("click", (event) => {
    document.querySelectorAll(".filters details[open]").forEach((details) => {
      if (!details.contains(event.target)) details.open = false;
    });
  });
  document.getElementById("f-reset").addEventListener("click", () => {
    document.getElementById("q").value = "";
    document.getElementById("f-min").value = "";
    document.getElementById("f-max").value = "";
    clearMulti("f-city", "Все города");
    clearMulti("f-energy", "Любой");
    clearMulti("f-cond", "Любое");
    clearMulti("f-status", "Любой");
    clearMulti("f-year", "Любой");
    document.getElementById("f-fav").checked = false;
    document.getElementById("f-new").checked = false;
    document.getElementById("f-park").checked = false;
    document.getElementById("f-lift").checked = false;
    applyControls();
  });
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => setView(button.getAttribute("data-view")));
  });
  document.getElementById("sort").addEventListener("change", () => {
    state.dir = DEFAULT_DIR[document.getElementById("sort").value] || "desc";
    paintDir();
    applyControls();
  });
  document.getElementById("sort-dir").addEventListener("click", () => {
    state.dir = state.dir === "asc" ? "desc" : "asc";
    paintDir();
    applyControls();
  });
  document.getElementById("theme").addEventListener("click", () => {
    applyTheme(state.theme === "dark" ? "light" : "dark");
  });
  document.getElementById("backdrop").addEventListener("click", closePanel);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closePanel();
  });
}

function showSite() {
  document.getElementById("lock").classList.add("hidden");
  document.querySelector(".top").classList.remove("hidden");
  document.querySelector("main").classList.remove("hidden");
}

async function decryptVault(password) {
  const response = await fetch("vault.json");
  if (!response.ok) throw new Error("vault");
  const vault = await response.json();
  const salt = Uint8Array.from(atob(vault.salt), (char) => char.charCodeAt(0));
  const iv = Uint8Array.from(atob(vault.iv), (char) => char.charCodeAt(0));
  const packed = Uint8Array.from(atob(vault.data), (char) => char.charCodeAt(0));
  const baseKey = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveKey"],
  );
  const key = await crypto.subtle.deriveKey(
    { name: "PBKDF2", salt, iterations: vault.iter, hash: "SHA-256" },
    baseKey,
    { name: "AES-GCM", length: 256 },
    false,
    ["decrypt"],
  );
  const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv }, key, packed);
  return JSON.parse(new TextDecoder().decode(plain));
}

function askPassword() {
  const lock = document.getElementById("lock");
  const error = document.getElementById("lock-error");
  lock.classList.remove("hidden");
  document.querySelector(".top").classList.add("hidden");
  document.querySelector("main").classList.add("hidden");
  const input = document.getElementById("lock-pass");
  input.focus();
  return new Promise((resolve) => {
    document.getElementById("lock-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      error.textContent = "";
      try {
        const data = await decryptVault(input.value);
        sessionStorage.setItem("idealista-password", input.value);
        showSite();
        resolve(data);
      } catch (err) {
        error.textContent = "Пароль не подошёл";
      }
    });
  });
}

async function openShared() {
  const saved = sessionStorage.getItem("idealista-password");
  if (saved) {
    try {
      return await decryptVault(saved);
    } catch (error) {
      sessionStorage.removeItem("idealista-password");
    }
  }
  return askPassword();
}

function start(data) {
  state.all = data.listings || [];
  if (state.shared) applyBrowserNotes(state.all);
  state.rates = data.rates || {};
  const checked = state.rates.checked ? `, сверено ${state.rates.checked}` : "";
  const where = state.shared ? " Пометки с этого телефона остаются в его браузере." : " Правки: data/rent_rates.json.";
  document.getElementById("source").textContent =
    `Оценка аренды — индекс Idealista, октябрь 2026${checked}. Где ставки нет, стоит «низкая точность» и цифра не подставляется.${where}`;
  if (state.shared) document.getElementById("export").classList.add("hidden");
  fillFilters();
  return setView(state.view);
}

async function boot() {
  bind();
  applyTheme(state.theme);
  paintDir();
  try {
    const response = await fetch("api/listings");
    if (response.ok) {
      await start(await response.json());
      return;
    }
  } catch (error) {
    /* на странице GitHub сервера нет, откроется сейф */
  }
  try {
    state.shared = true;
    await start(await openShared());
  } catch (error) {
    document.getElementById("count").textContent = "Не удалось загрузить объявления";
    showSite();
  }
}

boot();
