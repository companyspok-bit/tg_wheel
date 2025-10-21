# main.py
# Python-telegram-bot 13.x
import os
import io
import logging
from math import pi
from typing import Dict, List

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InputMediaPhoto,
)
from telegram.ext import (
    Updater,
    CallbackContext,
    CommandHandler,
    MessageHandler,
    Filters,
    ConversationHandler,
)

# ----------------------------- ЛОГИ -----------------------------
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("wheel-bot")

# ---------------------- ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ --------------------
TOKEN = os.environ["TG_BOT_TOKEN"]

# Хост без завершающего слэша, например: https://tg-wheel-2.onrender.com
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "").rstrip("/")

# Если задать 443 — явно добавим его в URL вебхука. Можно оставить пустым.
FORCE_WEBHOOK_PORT = os.getenv("FORCE_WEBHOOK_PORT", "").strip()

# Render проксирует внешний :443 → внутрь на этот PORT (обычно 10000).
# В URL вебхука его НИКОГДА не вставляем.
RAW_PORT = os.getenv("PORT", "10000")
PORT = int(RAW_PORT) if RAW_PORT else 10000

# Путь вебхука — делаем коротким и «секретным» (по токену)
WEBHOOK_PATH = f"/{TOKEN}"

if not WEBHOOK_HOST.startswith("http"):
    raise RuntimeError(
        "WEBHOOK_HOST не задан или некорректен. Пример: https://tg-wheel-2.onrender.com"
    )

if FORCE_WEBHOOK_PORT:
    WEBHOOK_URL = f"{WEBHOOK_HOST}:{FORCE_WEBHOOK_PORT}{WEBHOOK_PATH}"
else:
    WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

log.info("Resolved local PORT=%s (raw=%r)", PORT, RAW_PORT)
log.info("Webhook URL will be set to: %s", WEBHOOK_URL)

# --------------------------- БИЗНЕС-ЛОГИКА -----------------------
QUESTIONS = [
    "1) Хватает ли на необходимые среднесрочные цели? (0–5)",
    "2) Есть ли подушка безопасности на 3–6 месяцев расходов? (0–5)",
    "3) Довольны ли вы учётом доходов/расходов? (0–5)",
    "4) Устраивает ли уровень долговой нагрузки? (0–5)",
    "5) Регулярно ли инвестируете по плану? (0–5)",
    "6) Чувствуете ли уверенность в пенсии/долгосроке? (0–5)",
    "7) Есть ли страхование ключевых рисков (жизнь/здоровье/имущество)? (0–5)",
    "8) Насколько финансовые вопросы согласованы в семье/партнёрстве? (0–5)",
]
NUM_Q = len(QUESTIONS)

ASKING, = range(1)

# Временное хранилище ответов по пользователю
user_answers: Dict[int, List[int]] = {}


def start(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    user_answers[user_id] = []

    kb = [["0", "1", "2", "3", "4", "5"]]
    update.message.reply_text(
        "Привет! Я помогу быстро оценить ваши финансы по 8 сферам.\n"
        "Отвечайте числами 0–5. Поехали!\n\n" + QUESTIONS[0],
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True, one_time_keyboard=True),
    )
    return ASKING


def handle_score(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    text = (update.message.text or "").strip()

    # валидируем число
    if text not in {"0", "1", "2", "3", "4", "5"}:
        update.message.reply_text("Пожалуйста, введите число от 0 до 5.")
        return ASKING

    score = int(text)
    user_answers.setdefault(user_id, []).append(score)
    idx = len(user_answers[user_id])

    if idx < NUM_Q:
        kb = [["0", "1", "2", "3", "4", "5"]]
        update.message.reply_text(
            QUESTIONS[idx],
            reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True, one_time_keyboard=True),
        )
        return ASKING

    # все ответы есть — считаем и отдаем колесо
    scores = user_answers[user_id][:NUM_Q]
    del user_answers[user_id]  # почистим

    png_bytes = render_wheel_png(scores)
    caption = make_summary_text(scores)

    # отправим картинку (и сразу текст)
    update.message.reply_photo(
        photo=png_bytes,
        caption=caption,
        reply_markup=ReplyKeyboardRemove(),
    )

    # чек-лист
    checklist = make_checklist(scores)
    update.message.reply_text(checklist)

    update.message.reply_text(
        "Готово! Чтобы пройти ещё раз — /start",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


def cancel(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    user_answers.pop(user_id, None)
    update.message.reply_text("Окей, остановил. Жду вас в любой момент — /start")
    return ConversationHandler.END


def make_summary_text(scores: List[int]) -> str:
    avg = sum(scores) / len(scores)
    if avg >= 4.5:
        mood = "Очень мощно! Вы круто управляете деньгами 👏"
    elif avg >= 3.5:
        mood = "Хороший уровень. Немного точек роста — и будет топ ✨"
    elif avg >= 2.5:
        mood = "Средне: уже есть база, стоит подтянуть слабые места 💪"
    else:
        mood = "Есть куда расти — начните с самого низкого сектора 👍"

    return (
        f"Ваши баллы: {', '.join(map(str, scores))}\n"
        f"Средний балл: {avg:.2f}/5\n\n{mood}"
    )


def make_checklist(scores: List[int]) -> str:
    items = [
        "Среднесрочные цели",
        "Подушка безопасности",
        "Учёт доходов/расходов",
        "Долговая нагрузка",
        "Инвестиции по плану",
        "Пенсия/долгосрок",
        "Страхование ключевых рисков",
        "Согласованность в семье",
    ]
    # Сортировка от слабых к сильным
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    lines = ["Топ-приоритеты на 30 дней (сначала слабые):"]
    for i in order[:3]:
        s = scores[i]
        label = items[i]
        lines.append(f"• {label}: сейчас {s}/5 — выберите 1–2 шага для улучшения")
    return "\n".join(lines)


# ------------------- Отрисовка «колеса» (PNG) -------------------
def render_wheel_png(values: List[int]) -> io.BytesIO:
    """
    Отрисовывает «колесо» как радиальную диаграмму (0–5).
    Возвращает BytesIO (готово для send_photo).
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    labels = [
        "Цели",
        "Подушка",
        "Учёт",
        "Долги",
        "Инвест.",
        "Долгосрок",
        "Страховки",
        "Семья",
    ]

    # нормируем в 0..1 для радиальной диаграммы
    v = np.array(values, dtype=float) / 5.0
    angles = np.linspace(0, 2 * pi, len(labels), endpoint=False)
    v = np.concatenate([v, [v[0]]])
    angles = np.concatenate([angles, [angles[0]]])

    fig = plt.figure(figsize=(6, 6), dpi=160)
    ax = fig.add_subplot(111, polar=True)
    ax.set_theta_offset(pi / 2)
    ax.set_theta_direction(-1)

    ax.set_thetagrids(angles[:-1] * 180/pi, labels, fontsize=10)
    ax.set_rgrids([0.2, 0.4, 0.6, 0.8, 1.0], labels=["1", "2", "3", "4", "5"], angle=0)

    # Радиальный «полигоник»
    ax.plot(angles, v, linewidth=2)
    ax.fill(angles, v, alpha=0.25)

    ax.set_ylim(0, 1.0)
    ax.grid(True, alpha=0.25)

    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf


# --------------------------- TELEGRAM BOT -----------------------
def build_conv() -> ConversationHandler:
    kb = [["0", "1", "2", "3", "4", "5"]]
    return ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASKING: [
                MessageHandler(Filters.text & ~Filters.command, handle_score)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=True,
        per_message=False,
    )


def main() -> None:
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    # Хендлеры
    dp.add_handler(build_conv())
    dp.add_handler(CommandHandler("cancel", cancel))

    # Чистим старый вебхук и выставляем новый
    try:
        updater.bot.delete_webhook()
    except Exception as e:
        log.warning("delete_webhook() warning: %s", e)

    ok = updater.bot.set_webhook(WEBHOOK_URL, timeout=30)
    log.info("set_webhook(): %s", ok)

    # Поднимаем локальный HTTP-сервер на нужном порту (Render сам проксирует 443 → этот порт)
    updater.start_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,   # должен совпадать с WEBHOOK_PATH
        # webhook_url не передаём тут, т.к. уже выставили выше через set_webhook()
    )
    log.info("Webhook server started on 0.0.0.0:%d path=%s", PORT, WEBHOOK_PATH)

    # Готово
    updater.idle()


if __name__ == "__main__":
    main()
