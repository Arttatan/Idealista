const STATUSES = ["Новая", "Интересно", "Визит", "Отказ", "Оффер"];
const PRIORITIES = ["1 — смотреть первой", "2 — интересно", "3 — запасной вариант"];
const ENERGY_ORDER = ["A+", "A", "B", "C", "D", "E", "F", "G"];
const DEFAULT_DIR = { added: "desc", price: "asc", rent: "desc", yield: "desc", year: "desc" };

const TABLE_COLUMNS = [
  { id: "fav", label: "★", essential: true },
  { id: "status", label: "Статус", essential: true },
  { id: "link", label: "Ссылка", essential: true },
  { id: "place", label: "Город / район", essential: true },
  { id: "price", label: "Цена", essential: true },
  { id: "rent", label: "Оценка аренды", essential: true },
  { id: "yield", label: "Доходность", essential: false },
  { id: "payback", label: "Окупаемость", essential: false },
  { id: "metro", label: "Метро", essential: true },
  { id: "shop", label: "Магазин", essential: true },
  { id: "condition", label: "Состояние", essential: false },
  { id: "energy", label: "Энергокласс", essential: true },
  { id: "year", label: "Год", essential: true },
  { id: "kind", label: "Квартира", essential: false },
  { id: "address", label: "Адрес", essential: false },
  { id: "floor", label: "Этаж", essential: false },
  { id: "lift", label: "Лифт", essential: false },
  { id: "parking", label: "Парковка", essential: false },
  { id: "balcony", label: "Балкон / терраса", essential: false },
  { id: "tenant", label: "Сдана", essential: false },
  { id: "agency", label: "Агентство", essential: false },
  { id: "area", label: "Район по услугам", essential: false },
  { id: "score", label: "Балл удобства", essential: false },
  { id: "pharmacy", label: "Аптека", essential: false },
  { id: "school", label: "Школа", essential: false },
  { id: "kindergarten", label: "Детский сад", essential: false },
  { id: "transit", label: "Остановка", essential: false },
  { id: "park", label: "Парк", essential: false },
  { id: "health", label: "Медицина", essential: false },
  { id: "added", label: "Добавлено", essential: false },
];

const ESSENTIAL_COLS = TABLE_COLUMNS.filter((col) => col.essential).map((col) => col.id);
const ALL_COLS = TABLE_COLUMNS.map((col) => col.id);

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
  columns: loadColumns(),
  password: "",
  sync: null,
  syncBusy: false,
  syncTimer: null,
  pushTimer: null,
};

function loadColumns() {
  try {
    const saved = JSON.parse(localStorage.getItem("idealista-columns") || "null");
    if (Array.isArray(saved) && saved.length) {
      const allowed = new Set(ALL_COLS);
      const picked = saved.filter((id) => allowed.has(id));
      if (picked.length) return picked;
    }
  } catch (error) {
    /* default */
  }
  return [...ESSENTIAL_COLS];
}

function saveColumns() {
  localStorage.setItem("idealista-columns", JSON.stringify(state.columns));
}

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

function factValue(item, label) {
  const fact = (item.facts || []).find((entry) => entry.label === label);
  return fact ? fact.value : "";
}

function textCell(label, value, className) {
  return el("td", { class: className || "", "data-label": label, text: value || "—" });
}

function columnVisible(id) {
  return state.columns.includes(id);
}

function paintColumnsSummary() {
  const summary = document.getElementById("f-cols-summary");
  if (!summary) return;
  const n = state.columns.length;
  if (n === ALL_COLS.length) summary.textContent = "Все колонки";
  else if (n === ESSENTIAL_COLS.length && ESSENTIAL_COLS.every((id) => state.columns.includes(id))) {
    summary.textContent = "Только важное";
  } else summary.textContent = `Выбрано: ${n}`;
}

function fillColumnPicker() {
  const box = document.getElementById("f-cols");
  if (!box) return;
  box.replaceChildren();
  TABLE_COLUMNS.forEach((col) => {
    const input = el("input", { type: "checkbox", value: col.id });
    input.checked = columnVisible(col.id);
    input.addEventListener("change", () => {
      if (input.checked) {
        if (!state.columns.includes(col.id)) state.columns.push(col.id);
      } else {
        if (state.columns.length <= 1) {
          input.checked = true;
          return;
        }
        state.columns = state.columns.filter((id) => id !== col.id);
      }
      // keep order as in TABLE_COLUMNS
      state.columns = ALL_COLS.filter((id) => state.columns.includes(id));
      saveColumns();
      paintColumnsSummary();
      applyControls();
    });
    box.append(el("label", {}, input, col.label));
  });
  paintColumnsSummary();
}

function setColumns(ids) {
  state.columns = ALL_COLS.filter((id) => ids.includes(id));
  if (!state.columns.length) state.columns = [...ESSENTIAL_COLS];
  saveColumns();
  fillColumnPicker();
  applyControls();
}

function headerCell(col) {
  if (col.id === "price") {
    return el("th", { class: `col-${col.id}` }, el("button", { type: "button", text: col.label, onClick: () => sortBy("price") }));
  }
  if (col.id === "rent") {
    return el("th", { class: `col-${col.id}` }, el("button", { type: "button", text: col.label, onClick: () => sortBy("rent") }));
  }
  if (col.id === "year") {
    return el("th", { class: `col-${col.id}` }, el("button", { type: "button", text: col.label, onClick: () => sortBy("year") }));
  }
  if (col.id === "yield") {
    return el("th", { class: `col-${col.id}` }, el("button", { type: "button", text: col.label, onClick: () => sortBy("yield") }));
  }
  return el("th", { class: `col-${col.id}`, text: col.label });
}

function cellFor(col, item) {
  switch (col.id) {
    case "fav":
      return el("td", { class: "fav-cell", "data-label": "Избранное" }, starButton(item));
    case "status":
      return el("td", { "data-label": "Статус" }, statusSelect(item));
    case "link":
      return el("td", { "data-label": "Ссылка" }, tableLink(item));
    case "place":
      return textCell("Город / район", item.place || item.city);
    case "price":
      return textCell("Цена", euro(item.price));
    case "rent":
      return rentCell(item);
    case "yield":
      return textCell("Доходность", item.rent && item.rent.yield_pct != null ? pct(item.rent.yield_pct) : "—");
    case "payback":
      return textCell("Окупаемость", item.rent && item.rent.payback_years != null ? yearsLabel(item.rent.payback_years) : "—");
    case "metro":
      return nearCell("Метро", item.metro);
    case "shop":
      return nearCell("Магазин", item.shop);
    case "condition":
      return textCell("Состояние", item.condition);
    case "energy":
      return el("td", { "data-label": "Энергокласс" }, item.energy
        ? el("span", { class: `energy ${energyClass(item.energy)}`, text: item.energy })
        : "—");
    case "year":
      return textCell("Год постройки", item.year);
    case "kind":
      return textCell("Квартира", item.kind || factValue(item, "Квартира"));
    case "address":
      return textCell("Адрес", item.address || factValue(item, "Адрес или ориентир"));
    case "floor":
      return textCell("Этаж", factValue(item, "Этаж"));
    case "lift":
      return textCell("Лифт", item.lift || factValue(item, "Лифт"));
    case "parking":
      return textCell("Парковка", item.parking || factValue(item, "Парковка"));
    case "balcony":
      return textCell("Балкон / терраса", factValue(item, "Балкон или терраса"));
    case "tenant":
      return textCell("Сдана", item.tenant || factValue(item, "Сдана арендаторам"));
    case "agency":
      return textCell("Агентство", item.agency || factValue(item, "Агентство"));
    case "area":
      return textCell("Район по услугам", factValue(item, "Район по услугам"));
    case "score":
      return textCell("Балл удобства", factValue(item, "Балл удобства"));
    case "pharmacy":
      return textCell("Аптека", factValue(item, "Аптеки"));
    case "school":
      return textCell("Школа", factValue(item, "Школы"));
    case "kindergarten":
      return textCell("Детский сад", factValue(item, "Детские сады"));
    case "transit":
      return nearCell("Остановка", item.transit);
    case "park":
      return textCell("Парк", factValue(item, "Парк"));
    case "health":
      return textCell("Медицина", factValue(item, "Медицина"));
    case "added":
      return textCell("Добавлено", item.added || factValue(item, "Добавлено"));
    default:
      return textCell(col.label, "—");
  }
}

function tableView(items) {
  const visible = TABLE_COLUMNS.filter((col) => columnVisible(col.id));
  const head = el("tr", {}, ...visible.map((col) => headerCell(col)));
  const body = el("tbody");
  items.forEach((item) => {
    const row = el("tr", { class: isNew(item) ? "is-new" : "" },
      ...visible.map((col) => cellFor(col, item)));
    row.addEventListener("click", (event) => {
      const raw = event.target;
      const target = raw instanceof Element ? raw : raw && raw.parentElement;
      if (target && target.closest("a, button, select, label")) return;
      openPanel(item.id);
    });
    body.append(row);
  });
  const wrap = el("div", { class: visible.length > 10 ? "table-wrap wide" : "table-wrap" });
  wrap.append(el("table", { class: visible.length > 10 ? "table-wide" : "" }, el("thead", {}, head), body));
  return wrap;
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

const NOTE_FIELDS = [
  "Статус", "Избранное", "Приоритет", "Просмотрено", "Запланирован визит",
  "Дата визита", "Телефон", "Заметки", "Плюсы", "Минусы", "Причина отказа",
];

function fieldTs(note, field) {
  if (!note || typeof note !== "object") return 0;
  return Number(note[`_ts_${field}`] || note._ts || 0);
}

function stampNotePatch(patch) {
  const now = Date.now();
  const stamped = { ...patch, _ts: now };
  Object.keys(patch).forEach((key) => {
    if (NOTE_FIELDS.includes(key)) stamped[`_ts_${key}`] = now;
  });
  return stamped;
}

function rememberBrowserNote(id, patch) {
  const saved = browserNotes();
  saved[id] = { ...(saved[id] || {}), ...patch };
  localStorage.setItem("idealista-browser-notes", JSON.stringify(saved));
}

function applyNotesMap(listings, notesMap) {
  listings.forEach((item) => {
    if (!notesMap[item.id]) return;
    item.notes = { ...item.notes, ...notesMap[item.id] };
  });
}

function notesSnapshot() {
  const out = {};
  state.all.forEach((item) => {
    out[item.id] = { ...item.notes };
  });
  return out;
}

function mergeOneNote(left, right) {
  const a = left && typeof left === "object" ? left : {};
  const b = right && typeof right === "object" ? right : {};
  const merged = { ...a, ...b };
  NOTE_FIELDS.forEach((field) => {
    const aTs = fieldTs(a, field);
    const bTs = fieldTs(b, field);
    if (bTs > aTs) {
      if (field in b) merged[field] = b[field];
      if (b[`_ts_${field}`] != null) merged[`_ts_${field}`] = b[`_ts_${field}`];
      else if (b._ts) merged[`_ts_${field}`] = b._ts;
    } else if (aTs > bTs) {
      if (field in a) merged[field] = a[field];
      if (a[`_ts_${field}`] != null) merged[`_ts_${field}`] = a[`_ts_${field}`];
      else if (a._ts) merged[`_ts_${field}`] = a._ts;
    } else if (bTs === aTs && bTs > 0) {
      // одинаковое время: не даём «Новая» затереть осмысленный статус
      if (field === "Статус") {
        const aStatus = a.Статус || "Новая";
        const bStatus = b.Статус || "Новая";
        if (aStatus !== "Новая" && bStatus === "Новая") merged.Статус = aStatus;
        else if (bStatus !== "Новая" && aStatus === "Новая") merged.Статус = bStatus;
        else if (field in b) merged.Статус = bStatus;
      } else if (field === "Избранное") {
        merged.Избранное = Boolean(a.Избранное) || Boolean(b.Избранное);
      } else if (field in b) {
        const aVal = a[field];
        const bVal = b[field];
        merged[field] = (bVal != null && bVal !== "") ? bVal : aVal;
      }
    } else {
      // оба без метки: предпочитаем непустое / не «Новая»
      if (field === "Статус") {
        const aStatus = a.Статус || "Новая";
        const bStatus = b.Статус || "Новая";
        merged.Статус = aStatus !== "Новая" ? aStatus : bStatus;
      } else if (field === "Избранное") {
        merged.Избранное = Boolean(a.Избранное) || Boolean(b.Избранное);
      } else {
        const aVal = a[field];
        const bVal = b[field];
        merged[field] = (aVal != null && aVal !== "") ? aVal : bVal;
      }
    }
  });
  merged._ts = Math.max(Number(a._ts) || 0, Number(b._ts) || 0, ...NOTE_FIELDS.map((field) => fieldTs(merged, field)));
  return merged;
}

function mergeNoteRecords(local, remote) {
  const out = {};
  const ids = new Set([...Object.keys(local || {}), ...Object.keys(remote || {})]);
  ids.forEach((id) => {
    out[id] = mergeOneNote(local[id], remote[id]);
  });
  return out;
}

function b64ToBytes(text) {
  return Uint8Array.from(atob(text), (char) => char.charCodeAt(0));
}

async function deriveKey(password, salt, iterations) {
  const baseKey = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveKey"],
  );
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", salt, iterations, hash: "SHA-256" },
    baseKey,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
}

async function decryptBundle(password, bundle) {
  const salt = b64ToBytes(bundle.salt);
  const iv = b64ToBytes(bundle.iv);
  const packed = b64ToBytes(bundle.data);
  const key = await deriveKey(password, salt, bundle.iter || 250000);
  const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv }, key, packed);
  return new TextDecoder().decode(plain);
}

async function encryptBundle(password, plainText) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const key = await deriveKey(password, salt, 250000);
  const packed = new Uint8Array(await crypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    key,
    new TextEncoder().encode(plainText),
  ));
  const toB64 = (bytes) => {
    let out = "";
    bytes.forEach((value) => {
      out += String.fromCharCode(value);
    });
    return btoa(out);
  };
  return {
    v: 1,
    iter: 250000,
    salt: toB64(salt),
    iv: toB64(iv),
    data: toB64(packed),
  };
}

async function unlockSync(password, vault) {
  if (!vault.sync || !vault.sync.gistId || !vault.sync.token) return null;
  const token = await decryptBundle(password, vault.sync.token);
  return {
    gistId: vault.sync.gistId,
    fileName: vault.sync.fileName || "notes.vault.json",
    token: token.trim(),
  };
}

async function gistGet() {
  const response = await fetch(`https://api.github.com/gists/${state.sync.gistId}`, {
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${state.sync.token}`,
    },
  });
  if (!response.ok) throw new Error("gist get");
  return response.json();
}

async function pullSharedNotes() {
  if (!state.sync || state.syncBusy) return false;
  state.syncBusy = true;
  try {
    const gist = await gistGet();
    const file = gist.files && gist.files[state.sync.fileName];
    if (!file || !file.content) return false;
    const bundle = JSON.parse(file.content);
    const payload = JSON.parse(await decryptBundle(state.password, bundle));
    const remote = payload.notes || {};
    const merged = mergeNoteRecords(notesSnapshot(), remote);
    applyNotesMap(state.all, merged);
    localStorage.setItem("idealista-browser-notes", JSON.stringify(merged));
    return true;
  } catch (error) {
    return false;
  } finally {
    state.syncBusy = false;
  }
}

async function pushSharedNotes() {
  if (!state.sync || state.syncBusy) return false;
  state.syncBusy = true;
  try {
    const gist = await gistGet();
    const file = gist.files && gist.files[state.sync.fileName];
    let remote = {};
    if (file && file.content) {
      try {
        const bundle = JSON.parse(file.content);
        const payload = JSON.parse(await decryptBundle(state.password, bundle));
        remote = payload.notes || {};
      } catch (error) {
        remote = {};
      }
    }
    const merged = mergeNoteRecords(remote, notesSnapshot());
    applyNotesMap(state.all, merged);
    const encrypted = await encryptBundle(state.password, JSON.stringify({
      v: 1,
      updated: new Date().toISOString(),
      notes: merged,
    }));
    const response = await fetch(`https://api.github.com/gists/${state.sync.gistId}`, {
      method: "PATCH",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${state.sync.token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        files: {
          [state.sync.fileName]: { content: JSON.stringify(encrypted) },
        },
      }),
    });
    if (!response.ok) throw new Error("gist put");
    localStorage.setItem("idealista-browser-notes", JSON.stringify(merged));
    return true;
  } catch (error) {
    return false;
  } finally {
    state.syncBusy = false;
  }
}

function scheduleSharedPush() {
  clearTimeout(state.pushTimer);
  state.pushTimer = setTimeout(async () => {
    setSaveState("Синхронизирую…");
    const ok = await pushSharedNotes();
    setSaveState(ok ? "Сохранено у обоих" : "Не удалось синхронизировать");
  }, 700);
}

function startSharedPolling() {
  clearInterval(state.syncTimer);
  const refreshFromCloud = async () => {
    if (!state.sync || state.syncBusy) return;
    const before = JSON.stringify(notesSnapshot());
    const ok = await pullSharedNotes();
    if (!ok) return;
    if (before !== JSON.stringify(notesSnapshot())) {
      const y = window.scrollY;
      applyControls();
      window.scrollTo(0, y);
      setSaveState("Обновлено с другого устройства");
    }
  };
  state.syncTimer = setInterval(() => {
    if (document.hidden) return;
    refreshFromCloud();
  }, 5000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshFromCloud();
  });
}

async function commit(id, patch) {
  const item = byId(id);
  const stamped = stampNotePatch(patch);
  if (item) Object.assign(item.notes, stamped);
  if (state.shared) {
    rememberBrowserNote(id, stamped);
    paintStars(id, Boolean(item && item.notes["Избранное"]));
    if ("Статус" in patch || "Избранное" in patch) {
      const y = window.scrollY;
      applyControls();
      window.scrollTo(0, y);
    }
    if (state.sync) {
      setSaveState("Сохраняю…");
      scheduleSharedPush();
    } else {
      setSaveState("Сохранено только в этом браузере");
    }
    return;
  }
  try {
    const response = await fetch("api/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, notes: stamped }),
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
  document.getElementById("columns-bar").classList.toggle("hidden", name !== "table");
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
    document.querySelectorAll(".filters details[open], .columns-bar details[open]").forEach((details) => {
      if (!details.contains(event.target)) details.open = false;
    });
  });
  document.getElementById("cols-essential").addEventListener("click", () => setColumns(ESSENTIAL_COLS));
  document.getElementById("cols-all").addEventListener("click", () => setColumns(ALL_COLS));
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
  const response = await fetch(`vault.json?cb=${Date.now()}`);
  if (!response.ok) throw new Error("vault");
  const vault = await response.json();
  const plain = await decryptBundle(password, vault);
  const data = JSON.parse(plain);
  state.password = password;
  try {
    state.sync = await unlockSync(password, vault);
  } catch (error) {
    state.sync = null;
  }
  return data;
}

function askPassword() {
  const lock = document.getElementById("lock");
  const error = document.getElementById("lock-error");
  const form = document.getElementById("lock-form");
  const input = document.getElementById("lock-pass");
  lock.classList.remove("hidden");
  document.querySelector(".top").classList.add("hidden");
  document.querySelector("main").classList.add("hidden");
  input.value = "";
  input.focus();
  return new Promise((resolve) => {
    const onSubmit = async (event) => {
      event.preventDefault();
      error.textContent = "";
      const password = String(input.value || "").trim();
      if (!password) {
        error.textContent = "Введите пароль";
        return;
      }
      const button = form.querySelector("button[type='submit']");
      if (button) {
        button.disabled = true;
        button.textContent = "Открываю…";
      }
      try {
        const data = await decryptVault(password);
        sessionStorage.setItem("idealista-password", password);
        form.removeEventListener("submit", onSubmit);
        showSite();
        resolve(data);
      } catch (err) {
        error.textContent = "Пароль не подошёл. Скопируйте его целиком, без пробелов в начале и в конце.";
        if (button) {
          button.disabled = false;
          button.textContent = "Открыть";
        }
      }
    };
    form.addEventListener("submit", onSubmit);
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

async function start(data) {
  state.all = data.listings || [];
  if (state.shared) {
    // Сначала подтягиваем то, что уже было в этом браузере (в т.ч. правки жены).
    applyNotesMap(state.all, browserNotes());
    if (state.sync) {
      try {
        // Только читаем облако при входе. Пишем лишь после реального изменения пометки.
        await pullSharedNotes();
        startSharedPolling();
      } catch (error) {
        /* вход важнее синхронизации: сайт должен открыться даже если gist недоступен */
      }
    }
  }
  state.rates = data.rates || {};
  const checked = state.rates.checked ? `, сверено ${state.rates.checked}` : "";
  const where = state.shared
    ? (state.sync
      ? " Пометки общие: что отмечает жена, видно и вам (синхронизация каждые несколько секунд)."
      : " Пометки пока только в этом браузере.")
    : " Правки: data/rent_rates.json.";
  document.getElementById("source").textContent =
    `Оценка аренды — индекс Idealista, октябрь 2026${checked}. Где ставки нет, стоит «низкая точность» и цифра не подставляется.${where}`;
  if (state.shared) document.getElementById("export").classList.add("hidden");
  fillFilters();
  fillColumnPicker();
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
