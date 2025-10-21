# Telegram-бот «Колесо финансового баланса»
# Режим: POLLING (без вебхуков) + генерация PNG и PDF с колесом (matplotlib)
# Требования: python-telegram-bot==13.15, urllib3==1.26.20, six==1.16.0, matplotlib==3.8.4, numpy==2.3.4

import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import List

# Headless backend для отрисовки (важно для сервера)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import uuid

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters,
    ConversationHandler, CallbackContext,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------- Мини health-сервер (не обязателен, но полезен для хостингов с health-check) ----------
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args, **kwargs):
        return

def start_health_server():
    port = int(os.environ.get("PORT", "8080"))
    try:
        srv = HTTPServer(("0.0.0.0", port), HealthHandler)
        logging.info(f"Health server on :{port}")
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    except Exception as e:
        logging.warning(f"Health server failed: {e}")

# ---------- Опросник ----------
GET_RATING = 1

QUESTIONS = [
    "1) Хватает ли на необходимые среднесрочные цели? (0–5)",
    "2) Заботишься ли о будущей пенсии? (0–5)",
    "3) Есть ли подушка безопасности? (0–5)",
    "4) Есть ли небольшие цели (до года)? (0–5)",
    "5) Есть ли резерв на мелкие расходы? (0–5)",
    "6) Нет ли долгов (кроме ипотеки)? (0–5)",
    "7) Хватает ли на lifestyle (удовольствия/образ жизни)? (0–5)",
    "8) Общая уверенность в своём финансовом состоянии? (0–5)",
]

SHORT_TITLES = [
    "Среднеср. цели","Пенсия","Подушка","Короткие цели",
    "Мелкие резервы","Долги","Lifestyle","Уверенность",
]

KEYBOARD = ReplyKeyboardMarkup([["0","1","2","3","4","5"]],
                               resize_keyboard=True, one_time_keyboard=True)

def interpret_average(avg: float) -> str:
    if avg < 1.5: return "Критическое состояние"
    if avg < 2.5: return "Нижний уровень"
    if avg < 3.5: return "Средний уровень"
    if avg < 4.5: return "Хороший уровень"
    return "Отличный уровень"

def band_message(avg: float) -> str:
    if avg < 1.5:
        return ("Это нормальный старт — ты уже сделал первый шаг. "
                "Сфокусируйся на базовых вещах: минимум лишних трат, простая таблица учёта "
                "и маленькая подушка. Маленькие шаги каждый день дают прогресс.")
    if avg < 2.5:
        return ("Есть быстрый потенциал роста. Выбери 1–2 шага на неделю "
                "(например, 5% дохода сразу переводить в резерв). "
                "Маленькие победы быстро накапливаются.")
    if avg < 3.5:
        return ("База уже есть. Добавь структуру: автопереводы на цели и лёгкий контроль «утечек». "
                "Немного дисциплины — и выйдешь на высокий уровень.")
    if avg < 4.5:
        return ("Отличный фундамент! Подумай о диверсификации и защите: страховки, пенсионный план, "
                "оптимизация налогов. Это усилит устойчивость и прогресс.")
    return ("Очень круто! Осталось отполировать детали: тонкая настройка портфеля, "
            "автопополнения и «техосмотр» финансов раз в квартал.")

def gentle_hints(ans: List[int]) -> List[str]:
    hints = []
    if ans[2] <= 2: hints.append("Подушка: цель 1–2 ежемес. дохода, переводи фиксированный % после зарплаты.")
    if ans[1] <= 2: hints.append("Пенсия: автоплатёж 3–5% на долгий счёт/ИИС — работает сложный процент.")
    if ans[5] <= 2: hints.append("Долги: реестр + стратегия «снежный ком»/«лавина», фиксируй ежемесячный платёж.")
    if ans[4] <= 2: hints.append("Мелкие резервы: отдельный «карман» для мелких непредвиденных трат.")
    if ans[6] <= 2: hints.append("Lifestyle: запланируй маленькие радости в рамках бюджета — держать курс легче.")
    if ans[0] <= 2 or ans[3] <= 2: hints.append("Цели: разбей на 3–6–12 мес. и поставь автопереводы под каждую.")
    return hints

def build_personal(avg: float, ans: List[int]) -> str:
    msg = band_message(avg)
    tips = gentle_hints(ans)
    if tips: msg += "\n\nЧто поможет прямо сейчас:\n• " + "\n• ".join(tips[:3])
    return msg

CHECKLIST_MAP = {
    "Подушка": ["Открой отдельный счёт для подушки."],
    "Пенсия": ["Настрой автоплатёж 3–5% на долгий счёт/ИИС."],
    "Долги": ["Составь реестр долгов и выбери «снежный ком»/«лавина»."],
    "Мелкие резервы": ["Создай «карман» для мелких непредвиденных трат."],
    "Lifestyle": ["Запланируй 1–2 радости в рамках фиксированного лимита."],
    "Среднеср. цели": ["Определи 1–2 цели на 6–18 мес. и поставь автоплатёж."],
    "Короткие цели": ["Сформулируй цель на 3–6 мес. и разбей на шаги."],
    "Уверенность": ["Сделай 1 маленький шаг, который повысит уверенность сегодня."],
}
def build_checklist(ans: List[int]) -> List[str]:
    weakest = sorted(range(len(ans)), key=lambda i: ans[i])[:3]
    items = [f"— {SHORT_TITLES[i]}: {CHECKLIST_MAP.get(SHORT_TITLES[i], ['Шаг по этой сфере.'])[0]}" for i in weakest]
    items.append("— Поставь автопереводы/напоминания — держи ритм.")
    return items[:4]

# ---------- Рисуем колесо ----------
def make_wheel_images(scores: List[int], titles: List[str], style: str = "radar"):
    """
    Рисует колесо в стиле 'radar' (по умолчанию) или 'donut' (если передать style='donut').
    Возвращает (png_path, pdf_path).
    """
    safe_id = uuid.uuid4().hex
    png_path = f"/tmp/wheel_{safe_id}.png"
    pdf_path = f"/tmp/wheel_{safe_id}.pdf"

    n = len(scores)
    data = np.array(scores, dtype=float)
    maxv = 5.0

    plt.rcParams.update({
        "figure.figsize": (6, 6),      # компактнее
        "savefig.bbox": "tight",
        "font.size": 10,
    })

    if style == "donut":
        theta = np.linspace(0.0, 2*np.pi, n, endpoint=False)
        width = 2*np.pi / n * 0.9
        fig, ax = plt.subplots(subplot_kw=dict(polar=True))
        ax.set_theta_offset(np.pi / 2)
        ax.set_theta_direction(-1)
        # фон максимума
        ax.bar(theta, [maxv]*n, width=width, bottom=0, color="#F1F3F5", edgecolor="#E6E8EB", linewidth=1, zorder=1)
        # значения
        ax.bar(theta, data, width=width, bottom=0, color="#7C4DFF", alpha=0.8, zorder=2)
        for ang, lab in zip(theta, titles):
            ax.text(ang, maxv + 0.3, lab, ha="center", va="center", fontsize=9)
        ax.set_rticks([1,2,3,4,5])
        ax.grid(color="#E6E8EB")
        ax.set_title("Колесо финансового баланса", pad=16)
    else:
        # RADAR (паук)
        angles = np.linspace(0, 2*np.pi, n, endpoint=False).tolist()
        data_closed = np.concatenate([data, [data[0]]])
        angles_closed = angles + [angles[0]]
        fig, ax = plt.subplots(subplot_kw=dict(polar=True))
        ax.set_theta_offset(np.pi / 2)
        ax.set_theta_direction(-1)
        ax.set_rgrids([1,2,3,4,5], labels=["1","2","3","4","5"])
        ax.set_ylim(0, maxv)
        ax.yaxis.grid(color="#E6E8EB"); ax.xaxis.grid(color="#E6E8EB")
        ax.plot(angles_closed, data_closed, color="#7C4DFF", linewidth=2)
        ax.fill(angles_closed, data_closed, color="#7C4DFF", alpha=0.28)
        ax.set_xticks(angles); ax.set_xticklabels(titles, fontsize=9)
        ax.set_title("Колесо финансового баланса", pad=16)

    fig.savefig(png_path, dpi=180)  # PNG
    fig.savefig(pdf_path)           # PDF
    plt.close(fig)
    return png_path, pdf_path

# ---------- Диалог ----------
def start(update: Update, context: CallbackContext):
    context.user_data["answers"] = []
    context.user_data["q_idx"] = 0
    style_env = os.environ.get("WHEEL_STYLE", "radar").strip().lower()
    context.user_data["style"] = "donut" if style_env == "donut" else "radar"
    update.message.reply_text(
        "Привет! За пару минут оценим твои финансы по 8 сферам. Готов начать?\n\n" + QUESTIONS[0],
        reply_markup=KEYBOARD,
    )
    return GET_RATING

def help_cmd(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Как это работает:\n"
        "• 8 вопросов (оценка 0–5)\n"
        "• В конце: резюме + PNG и PDF с колесом\n\n"
        "Команды:\n/start — начать заново\n/style radar|donut — стиль колеса\n/cancel — отменить"
    )

def style_cmd(update: Update, context: CallbackContext):
    parts = (update.message.text or "").strip().split()
    if len(parts) == 2 and parts[1].lower() in ("radar","donut"):
        context.user_data["style"] = parts[1].lower()
        update.message.reply_text(f"Стиль сохранён: {parts[1].lower()}. Продолжаем!")
    else:
        update.message.reply_text("Используй: /style radar или /style donut")

def cancel(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Оценка отменена. Чтобы начать заново — /start.",
        reply_markup=ReplyKeyboardRemove(),
    )
    context.user_data.clear()
    return ConversationHandler.END

def handle_rating(update: Update, context: CallbackContext):
    text = (update.message.text or "").strip()
    q_idx = context.user_data.get("q_idx", 0)

    try:
        val = int(text)
        if val < 0 or val > 5:
            raise ValueError()
    except ValueError:
        update.message.reply_text("Пожалуйста, выбери число от 0 до 5 на клавиатуре ниже.", reply_markup=KEYBOARD)
        return GET_RATING

    context.user_data.setdefault("answers", []).append(val)
    q_idx += 1
    context.user_data["q_idx"] = q_idx

    if q_idx < len(QUESTIONS):
        update.message.reply_text(QUESTIONS[q_idx], reply_markup=KEYBOARD)
        return GET_RATING

    # финал
    answers = context.user_data["answers"]
    avg = sum(answers) / len(answers)
    weakest_indices = sorted(range(len(answers)), key=lambda i: answers[i])[:3]
    weakest = "\n".join([f"- {SHORT_TITLES[i]} → {answers[i]}" for i in weakest_indices])

    personal = build_personal(avg, answers)
    checklist = build_checklist(answers)

    style = context.user_data.get("style", "radar")
    png_path, pdf_path = make_wheel_images(answers, SHORT_TITLES, style=style)

    update.message.reply_text(
        f"Готово!\n\n"
        f"Средняя оценка: {avg:.2f} / 5\n"
        f"Интерпретация: {interpret_average(avg)}\n\n"
        f"Три самые слабые зоны:\n{weakest}\n\n"
        f"{personal}\n\n"
        f"Чек-лист на неделю:\n" + "\n".join(checklist) + "\n\n"
        f"Стиль колеса: {style}. Сейчас пришлю PNG + PDF.",
        reply_markup=ReplyKeyboardRemove(),
    )

    # отправка файлов
    send_errors = []
    try:
        with open(png_path, "rb") as f:
            update.message.reply_photo(photo=f, caption="Ваше колесо (PNG)")
    except Exception as e:
        logger.exception("send_photo failed")
        send_errors.append(f"PNG: {e}")

    try:
        with open(pdf_path, "rb") as f:
            update.message.reply_document(document=f, filename="finance_wheel.pdf", caption="Ваше колесо (PDF)")
    except Exception as e:
        logger.exception("send_document failed")
        send_errors.append(f"PDF: {e}")

    if send_errors:
        update.message.reply_text(
            "Не удалось отправить файлы автоматически. " +
            "\n".join(f"• {err}" for err in send_errors)
        )

    # очистка tmp
    for p in (png_path, pdf_path):
        try:
            if os.path.exists(p): os.remove(p)
        except Exception:
            pass

    context.user_data.clear()
    return ConversationHandler.END

def main():
    token = os.environ.get("TG_BOT_TOKEN")
    if not token:
        raise RuntimeError("Не задан TG_BOT_TOKEN в переменных окружения.")

    # Health-сервер (безопасно оставить)
    start_health_server()

    updater = Updater(token=token, use_context=True)
    dp = updater.dispatcher

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={GET_RATING: [MessageHandler(Filters.text & ~Filters.command, handle_rating)]},
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    dp.add_handler(conv)
    dp.add_handler(CommandHandler("help", help_cmd))
    dp.add_handler(CommandHandler("style", style_cmd))
    dp.add_handler(CommandHandler("cancel", cancel))

    updater.start_polling(drop_pending_updates=True)
    updater.idle()

if __name__ == "__main__":
    main()
