"""Блок-схемы ПП.11 (этап 4), построены строго по коду PP.11/app.
Обозначения по ГОСТ 19.701-90: овал — начало/конец, прямоугольник — действие,
ромб — условие, параллелограмм — ввод/вывод, прямоугольник с двойной рамкой — вызов
подпрограммы. Запуск: python make_flowcharts.py (нужен Graphviz)."""
import subprocess
import textwrap


def wrap(text, kind):
    """Перенос длинных подписей, чтобы схема помещалась на страницу A4."""
    width = 16 if kind == "d" else 24
    lines = []
    for part in text.split("\\n"):
        lines += textwrap.wrap(part, width) or [""]
    return "\\n".join(lines)

HEAD = '''digraph G {
  graph [fontname="DejaVu Sans", nodesep=0.22, ranksep=0.28, splines=ortho, newrank=true];
  node  [fontname="DejaVu Sans", fontsize=13, shape=box, width=1.2, margin="0.08,0.04"];
  edge  [fontname="DejaVu Sans", fontsize=10, arrowsize=0.7];
'''
SHAPES = {"t": 'shape=box, style="rounded", peripheries=1',
          "p": "shape=box", "d": "shape=diamond, margin=0.01",
          "io": "shape=polygon, sides=4, skew=0.2, margin=\"0.04,0.04\"", "s": "shape=box, peripheries=2"}


def chart(name, nodes, edges, main=()):
    """main — узлы основного пути: выстраиваются в одну вертикаль (group)."""
    out = [HEAD]
    for nid, kind, text in nodes:
        grp = ', group="main"' if nid in main else ""
        out.append(f'  {nid} [{SHAPES[kind]}, label="{wrap(text, kind)}"{grp}];')
    for e in edges:
        a, b = e[0], e[1]
        attrs = []
        if len(e) > 2 and e[2]:
            attrs.append(f'xlabel="{e[2]}"')
        if len(e) > 3:
            attrs.append(e[3])
        out.append(f'  {a} -> {b} [{", ".join(attrs)}];')
    out.append("}")
    open(name + ".dot", "w").write("\n".join(out))
    cmd = ["dot", "-Tpng", "-Gdpi=130", name + ".dot", "-o", name + ".png"]
    if subprocess.run(cmd, stderr=subprocess.DEVNULL).returncode != 0:
        # у Graphviz бывает сбой ортогональной трассировки — тогда ломаные линии
        subprocess.run(cmd + ["-Gsplines=polyline"], check=True)


# 1. app.py: create_booking — проверка входных данных
chart("01_create_booking_validation", [
    ("s", "t", "Начало\\nPOST /api/bookings"),
    ("in", "io", "data = тело\\nзапроса (JSON)"),
    ("d0", "d", "data —\\nJSON-объект?"),
    ("e0", "io", "Ответ 400\\n«Ожидается\\nJSON-объект»"),
    ("p1", "s", "parse_interval(data):\\nдата, начало, конец"),
    ("d1", "d", "Дата ГГГГ-ММ-ДД\\nи не в прошлом,\\nвремя ЧЧ:ММ,\\nначало < конца?"),
    ("p2", "s", "parse_guests(guests)"),
    ("d2", "d", "Целое\\nот 1 до 50?"),
    ("p3", "p", "name, phone (без пробелов,\\nскобок, дефисов), email\\n(пустой → None)"),
    ("d3", "d", "ФИО не пустое\\nи ≤ 100?"),
    ("d4", "d", "Телефон\\n+7XXXXXXXXXX?"),
    ("d5", "d", "Email пуст\\nили корректен?"),
    ("d6", "d", "table_id —\\nцелое?"),
    ("e1", "io", "Ответ 400\\nс текстом\\nошибки"),
    ("a", "t", "К транзакции\\n(рисунок 2)"),
    ("end", "t", "Конец"),
], [
    ("s", "in"), ("in", "d0"), ("d0", "e0", "нет"), ("d0", "p1", "да"), ("p1", "d1"),
    ("d1", "e1", "нет"), ("d1", "p2", "да"), ("p2", "d2"), ("d2", "e1", "нет"), ("d2", "p3", "да"),
    ("p3", "d3"), ("d3", "e1", "нет"), ("d3", "d4", "да"), ("d4", "e1", "нет"), ("d4", "d5", "да"),
    ("d5", "e1", "нет"), ("d5", "d6", "да"), ("d6", "e1", "нет"), ("d6", "a", "да"),
    ("e0", "end"), ("e1", "end"),
], main=("s","in","d0","p1","d1","p2","d2","p3","d3","d4","d5","d6","a"))

# 2. app.py: create_booking — транзакция создания брони
chart("02_create_booking_transaction", [
    ("a", "t", "Данные проверены\\n(рисунок 1)"),
    ("p4", "p", "BEGIN IMMEDIATE\\nSELECT столик\\nпо table_id"),
    ("d7", "d", "Столик\\nнайден?"),
    ("e2", "io", "ROLLBACK\\nОтвет 404"),
    ("d8", "d", "Гостей больше\\nвместимости?"),
    ("e3", "io", "ROLLBACK\\nОтвет 400"),
    ("d9", "d", "has_overlap:\\nесть бронь new/\\nconfirmed на этот\\nстолик и дату,\\nпересекающаяся\\nпо времени?"),
    ("e4", "io", "ROLLBACK\\nОтвет 409"),
    ("d10", "d", "Гость с таким\\nтелефоном есть?"),
    ("p5", "p", "UPDATE guests:\\nФИО, email\\n(если указан)"),
    ("p6", "p", "INSERT INTO\\nguests"),
    ("p7", "p", "INSERT INTO bookings\\n(status = 'new')\\nCOMMIT"),
    ("e5", "io", "ROLLBACK,\\nответ 500"),
    ("p8", "s", "booking =\\ndb.get_booking(id)"),
    ("p9", "s", "booking.notified =\\nnotify_admins(booking)"),
    ("out", "io", "Ответ 201\\nс данными брони"),
    ("end", "t", "Конец"),
], [
    ("a", "p4"), ("p4", "d7"), ("d7", "e2", "нет"), ("d7", "d8", "да"), ("d8", "e3", "да"), ("d8", "d9", "нет"),
    ("d9", "e4", "да"), ("d9", "d10", "нет"), ("d10", "p5", "да"), ("d10", "p6", "нет"),
    ("p5", "p7"), ("p6", "p7"), ("p7", "e5", "исключение", "style=dashed"), ("p7", "p8"), ("p8", "p9"), ("p9", "out"),
    ("out", "end"), ("e2", "end"), ("e3", "end"), ("e4", "end"), ("e5", "end"),
], main=("a","p4","d7","d8","d9","d10","p7","p8","p9","out","end"))

# 3. app.py notify_admins + vk.py VkNotifier.send_booking и VkApi.call
chart("03_notify_vk", [
    ("s", "t", "Начало\\nnotify_admins(booking)"),
    ("d0", "d", "notifier\\nнастроен?"),
    ("rf", "io", "Вернуть False"),
    ("p1", "p", "send_booking: текст format_booking,\\nклавиатура booking_keyboard,\\nrandom_id (один на все повторы)"),
    ("p2", "p", "VkApi.call(«messages.send»)\\nattempt = 1"),
    ("p3", "io", "POST https://api.vk.ru/method/messages.send\\n(timeout = VK_TIMEOUT)"),
    ("d1", "d", "Сбой сети, тайм-аут\\nили ответ не JSON?"),
    ("d2", "d", "Ответ — объект\\nс response или error?"),
    ("pn", "p", "err = VkError(«network»)"),
    ("d3", "d", "В ответе\\nесть error?"),
    ("pe", "p", "err = VkError(код, текст)"),
    ("d4", "d", "Код 6, 9 или 10\\n(временная ошибка)?"),
    ("d5", "d", "attempt =\\nattempts (3)?"),
    ("p4", "p", "Журнал: предупреждение;\\nпауза attempt секунд;\\nattempt = attempt + 1"),
    ("ok", "p", "Журнал: «Бронь №N отправлена»"),
    ("rt", "io", "Вернуть True"),
    ("err", "p", "Исключение VkError →\\nжурнал: «Бронь №N не отправлена в ВК»"),
    ("unk", "p", "Другое исключение →\\nжурнал: непредвиденная ошибка"),
    ("rf2", "io", "Вернуть False\\n(бронь остаётся «новой»)"),
    ("end", "t", "Конец"),
], [
    ("s", "d0"), ("d0", "rf", "нет"), ("d0", "p1", "да"), ("p1", "p2"), ("p2", "p3"), ("p3", "d1"),
    ("d1", "pn", "да"), ("d1", "d2", "нет"), ("d2", "pn", "нет"), ("d2", "d3", "да"),
    ("d3", "ok", "нет"), ("d3", "pe", "да"), ("pe", "d4"), ("d4", "err", "нет"), ("d4", "d5", "да"),
    ("pn", "d5"), ("d5", "err", "да"), ("d5", "p4", "нет"), ("p4", "p3"),
    ("ok", "rt"), ("p1", "unk", "исключение", "style=dashed"), ("err", "rf2"), ("unk", "rf2"),
    ("rt", "end"), ("rf", "end"), ("rf2", "end"),
], main=("s","d0","p1","p2","p3","d1","d2","d3","ok","rt","end"))

# 4. vk_bot.py: BookingBot.run — цикл Bots Long Poll
chart("04_bot_run", [
    ("s", "t", "Начало\\nBookingBot.run(group_id)"),
    ("p0", "io", "server = groups.getLongPollServer"),
    ("x0", "t", "VkError (например, 15 — нет права\\n«Управление сообществом»): выход"),
    ("d0", "d", "stop()?"),
    ("p1", "io", "GET server: act=a_check, key, ts, wait=25\\n(timeout 35 с)"),
    ("d1", "d", "Сбой сети\\nили не JSON?"),
    ("w1", "p", "Журнал: «Long Poll недоступен»\\nпауза 3 с"),
    ("d2", "d", "В ответе\\nесть failed?"),
    ("d3", "d", "failed = 1?"),
    ("p2", "p", "ts = r.ts"),
    ("p3", "io", "server = groups.getLongPollServer"),
    ("w2", "p", "VkError → журнал: «Не удалось обновить\\nсервер Long Poll», пауза 3 с"),
    ("p4", "p", "ts = r.ts"),
    ("d4", "d", "Есть ещё\\nсобытие в updates?"),
    ("d5", "d", "type =\\nmessage_event?"),
    ("p5", "s", "handle_event(событие)"),
    ("d6", "d", "Исключение VkError\\nили sqlite3.Error?"),
    ("l1", "p", "Журнал: ошибка обработки кнопки"),
    ("l2", "p", "Журнал: итог обработки"),
    ("end", "t", "Конец"),
], [
    ("s", "p0"), ("p0", "x0", "ошибка", "style=dashed"), ("p0", "d0"), ("d0", "end", "да"), ("d0", "p1", "нет"),
    ("p1", "d1"), ("d1", "w1", "да"), ("w1", "d0"), ("d1", "d2", "нет"), ("d2", "d3", "да"),
    ("d3", "p2", "да"), ("d3", "p3", "нет"), ("p3", "w2", "ошибка", "style=dashed"), ("p3", "d0"), ("w2", "d0"), ("p2", "d0"),
    ("d2", "p4", "нет"), ("p4", "d4"), ("d4", "d0", "нет"), ("d4", "d5", "да"), ("d5", "d4", "нет"),
    ("d5", "p5", "да"), ("p5", "d6"), ("d6", "l1", "да"), ("d6", "l2", "нет"), ("l1", "d4"), ("l2", "d4"),
], main=("s","p0","d0","p1","d1","d2","p4","d4","d5","p5","d6","l2"))

# 5. vk_bot.py: BookingBot.handle_event — нажатие «Подтвердить»/«Отклонить»
chart("05_bot_handle_event", [
    ("s", "t", "Начало\\nhandle_event(event)"),
    ("d0", "d", "peer_id = беседа\\nадминистраторов?"),
    ("r0", "io", "Вернуть «чужая беседа, пропуск»"),
    ("p1", "p", "payload: если строка — json.loads\\n(ошибка разбора → пустой)"),
    ("p2", "p", "decision = DECISIONS[action]\\nbooking_id = int(payload.booking_id)"),
    ("d1", "d", "decision и\\nbooking_id есть?"),
    ("a1", "io", "sendMessageEventAnswer:\\n«Неизвестная кнопка»"),
    ("p3", "s", "db.decide_booking: UPDATE bookings\\nSET status WHERE id AND status = 'new'"),
    ("p4", "s", "booking = db.get_booking(booking_id)"),
    ("d2", "d", "Бронь\\nнайдена?"),
    ("a2", "io", "sendMessageEventAnswer:\\n«Бронь №N не найдена»"),
    ("d3", "d", "Статус\\nизменён?"),
    ("a3", "io", "sendMessageEventAnswer:\\n«Бронь №N уже <статус>»"),
    ("p5", "s", "who = admin_name(user_id)\\n(users.get; ошибка → «id<user_id>»)"),
    ("p6", "io", "messages.edit: текст брони +\\n«✅ Подтверждено/❌ Отклонено: who»,\\nпустая клавиатура"),
    ("a4", "io", "sendMessageEventAnswer:\\n«Бронь №N подтверждена/отклонена»"),
    ("end", "t", "Конец"),
], [
    ("s", "d0"), ("d0", "r0", "нет"), ("d0", "p1", "да"), ("p1", "p2"), ("p2", "d1"),
    ("d1", "a1", "нет"), ("d1", "p3", "да"), ("p3", "p4"), ("p4", "d2"), ("d2", "a2", "нет"),
    ("d2", "d3", "да"), ("d3", "a3", "нет"), ("d3", "p5", "да"), ("p5", "p6"), ("p6", "a4"),
    ("a4", "end"), ("a3", "end"), ("a2", "end"), ("a1", "end"), ("r0", "end"),
], main=("s","d0","p1","p2","d1","p3","p4","d2","d3","p5","p6","a4","end"))

# 6. static/app.js: отправка формы контактов (шаг 3)
chart("06_form_submit", [
    ("s", "t", "Начало\\nотправка формы контактов"),
    ("p0", "p", "Очистить ошибки; body = запрос шага 1\\n+ table_id, ФИО, телефон, email"),
    ("d0", "d", "ФИО\\nпустое?"),
    ("e0", "io", "Ошибка у поля ФИО\\n«Укажите ФИО»"),
    ("p1", "p", "Кнопка «Забронировать» неактивна"),
    ("p2", "io", "fetch POST /api/bookings"),
    ("d1", "d", "Сервер\\nответил?"),
    ("e1", "p", "Ошибка «Сервер недоступен. Проверьте\\nсоединение и попробуйте ещё раз»"),
    ("d2", "d", "resp.ok\\n(код 2xx)?"),
    ("ok", "io", "Шаг 4: «Заявка №N принята»,\\nданные гостя экранированы (esc)"),
    ("d3", "d", "Код 409?"),
    ("e2", "p", "loadScheme(), шаг 2 (схема зала),\\n«…Выберите другой столик»"),
    ("d4", "d", "В тексте\\n«ФИО»?"),
    ("e3", "io", "Ошибка у поля ФИО"),
    ("d5", "d", "В тексте\\n«Телефон»?"),
    ("e4", "io", "Ошибка у поля «Телефон»"),
    ("e5", "io", "Общее сообщение об ошибке"),
    ("p3", "p", "Кнопка «Забронировать» снова активна"),
    ("end", "t", "Конец"),
], [
    ("s", "p0"), ("p0", "d0"), ("d0", "e0", "да"), ("e0", "end"), ("d0", "p1", "нет"), ("p1", "p2"),
    ("p2", "d1"), ("d1", "e1", "нет"), ("d1", "d2", "да"), ("d2", "ok", "да"), ("d2", "d3", "нет"),
    ("e1", "d3"), ("d3", "e2", "да"), ("d3", "d4", "нет"), ("d4", "e3", "да"), ("d4", "d5", "нет"),
    ("d5", "e4", "да"), ("d5", "e5", "нет"), ("ok", "p3"), ("e2", "p3"), ("e3", "p3"), ("e4", "p3"),
    ("e5", "p3"), ("p3", "end"),
], main=("s","p0","d0","p1","p2","d1","d2","ok","p3","end"))
