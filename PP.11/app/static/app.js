// ПП.11, этапы 3–4. Веб-форма брони: шаги «дата и время» → «схема зала» → «контакты» → «готово».
// Данные берутся из API бэкенда (этап 2), бронь создаётся запросом POST /api/bookings.
const $ = (id) => document.getElementById(id);
const state = { query: null, hall: null, table: null };

function showStep(n) {
  for (let i = 1; i <= 4; i++) $("step" + i).classList.toggle("hidden", i !== n);
  document.querySelectorAll(".steps div").forEach((d) => d.classList.toggle("on", +d.dataset.step === n));
}

function showError(text) {
  $("error").textContent = text || "";
  $("error").classList.toggle("hidden", !text);
}

async function api(url, options) {
  let resp;
  try { resp = await fetch(url, options); }
  catch (e) { throw Object.assign(new Error("Сервер недоступен. Проверьте соединение и попробуйте ещё раз"), { status: 0 }); }
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw Object.assign(new Error(data.error || "Ошибка сервера"), { status: resp.status });
  return data;
}

function seats(n) {
  if (n % 10 === 1 && n % 100 !== 11) return n + " место";
  if ([2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100)) return n + " места";
  return n + " мест";
}

const ruDate = (iso) => iso.split("-").reverse().join(".");
// Экранирование данных гостя перед вставкой в HTML (защита от XSS).
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// ---------- шаг 1 ----------
async function loadHalls() {
  const halls = await api("/api/halls");
  $("hall").innerHTML = halls.map((h) => `<option value="${h.id}">${h.name}</option>`).join("");
  const tomorrow = new Date(Date.now() + 864e5);
  $("date").value = tomorrow.toISOString().slice(0, 10);
}

$("searchForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  state.query = { date: $("date").value, start: $("start").value, end: $("end").value,
                  guests: +$("guests").value, hall_id: +$("hall").value };
  state.hall = $("hall").selectedOptions[0].textContent;
  try { await loadScheme(); showError(""); showStep(2); }
  catch (err) { showError(err.message); }
});

// ---------- шаг 2: схема зала ----------
// Столики расставлены сеткой по 4 в ряд по номеру; координаты в базе не хранятся.
function position(number) {
  const i = number - 1;
  return { left: 40 + (i % 4) * 140, top: 40 + Math.floor(i / 4) * 160 };
}

async function loadScheme() {
  const q = state.query;
  const params = new URLSearchParams(q).toString();
  const [all, free] = await Promise.all([
    api("/api/tables?hall_id=" + q.hall_id), api("/api/tables/free?" + params)]);
  const freeIds = new Set(free.map((t) => t.id));
  state.table = null;
  $("toContacts").disabled = true;
  $("tableInfo").innerHTML = free.length ? "<p>Выберите свободный столик на схеме.</p>"
    : "<p class='err'>Свободных столиков нет. Измените время или количество гостей.</p>";
  $("hallHeader").textContent = `${state.hall} · ${ruDate(q.date)}, ${q.start}–${q.end} · гостей: ${q.guests}`;
  const map = $("hallMap");
  map.innerHTML = '<div style="position:absolute;right:20px;bottom:14px;font-size:12px;color:#777">вход ▸</div>';
  for (const t of all) {
    const el = document.createElement("div");
    const isFree = freeIds.has(t.id);
    const p = position(t.number);
    el.className = "t " + (isFree ? "free" : "busy");
    el.style.left = p.left + "px"; el.style.top = p.top + "px";
    el.innerHTML = `<b>${t.number}</b>${isFree ? seats(t.capacity) : (t.capacity < q.guests ? "мало мест" : "занят")}`;
    if (isFree) el.addEventListener("click", () => selectTable(t, el));
    map.appendChild(el);
  }
}

function selectTable(t, el) {
  document.querySelectorAll(".t.sel").forEach((x) => x.classList.replace("sel", "free"));
  el.classList.replace("free", "sel");
  state.table = t;
  $("tableInfo").innerHTML = `<p><b>Столик №${t.number}</b></p><p>Вместимость: ${t.capacity}</p><p>Зал: ${t.hall}</p>`;
  $("toContacts").disabled = false;
}

$("toContacts").addEventListener("click", () => {
  const q = state.query, t = state.table;
  $("summary").innerHTML = `<b>${t.hall}, столик №${t.number}</b> · ${ruDate(q.date)}, ${q.start}–${q.end} · гостей: ${q.guests}`;
  showStep(3);
});

// ---------- шаг 3: контакты и отправка ----------
function fieldError(field, text) {
  document.querySelector(`.err[data-for="${field}"]`).textContent = text || "";
}

$("contactForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  fieldError("name"); fieldError("phone"); showError("");
  const body = { ...state.query, table_id: state.table.id,
                 name: $("name").value.trim(), phone: $("phone").value.trim(), email: $("email").value.trim() };
  if (!body.name) return fieldError("name", "Укажите ФИО");
  $("bookBtn").disabled = true;
  try {
    const b = await api("/api/bookings", { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    $("doneTitle").textContent = `Заявка №${b.id} принята`;
    $("doneInfo").innerHTML = `<p>${b.table.hall}, столик №${b.table.number} · ${ruDate(b.date)}, ${b.start}–${b.end}</p>
      <p>Гость: ${esc(b.guest.name)}, ${esc(b.guest.phone)}</p><p>Статус: новая</p>`;
    showStep(4);
  } catch (err) {
    if (err.status === 409) {           // столик успели занять — назад к схеме
      await loadScheme(); showStep(2); showError(err.message + ". Выберите другой столик.");
    } else if (/ФИО/.test(err.message)) fieldError("name", err.message);
    else if (/Телефон/.test(err.message)) fieldError("phone", err.message);
    else showError(err.message);
  } finally { $("bookBtn").disabled = false; }
});

document.querySelectorAll("[data-back]").forEach((b) =>
  b.addEventListener("click", () => { showError(""); showStep(+b.dataset.back); }));
$("again").addEventListener("click", () => { $("contactForm").reset(); showStep(1); });

loadHalls().catch((err) => showError(err.message));
showStep(1);
