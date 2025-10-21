import os
import io
import logging
from math import pi
from typing import Dict, List, Tuple

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InputMediaPhoto
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
    ConversationHandler,
)

# =============== ЛОГИ ===============
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("finance-wheel")

# =============== ТОКЕН ===============
TOKEN = os.getenv("TG_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("TG_BOT_TOKEN не задан в переменных окружения.")

# =============== ДАННЫЕ ОПРОСА ===============
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
FACETS = [
    "Цели", "Подушка", "Учёт", "Долги",
    "Инвест.", "Долгосрок", "Страховки", "Семья",
]
NUM_Q = len(QUESTIONS)

ASKING, = range(1)

# Простое хранение ответов на время сессии
user_answers: Dict[int, List[int]] = {}


# =============== ХЕЛПЕРЫ ТЕКСТА ===============
def make_summary_text(scores: List[int]) -> str:
    avg = sum(scores) / len(scores)
    if avg >= 4.5:
        mood = "Очень мощно! Вы круто управляете деньгами 👏"
    elif avg >= 3.5:
        mood = "Хороший уровень. Немного точек роста — и будет топ ✨"
    elif avg >= 2.5:
        mood = "Средне: база есть, подтяните слабые места 💪"
    else:
        mood = "Есть куда расти — начните с самого низкого сектора 👍"
    return (
        f"Ваши баллы: {', '.join(map(str, scores))}\n"
        f"Средний балл: {avg:.2f}/5\n\n{mood}"
    )


def make_checklist(scores: List[int]) -> str:
    # Отсортируем индексы сфер по возрастанию баллов
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    lines = ["ТОП-приоритеты на 30 дней:"]
    for i in order[:3]:
        lines.append(f"• {FACETS[i]} — сейчас {scores[i]}/5 → выберите 1–2 простых шага для улучшения")
    return "\n".join(lines)


# =============== ОТРИСОВКА КОЛЕСА (НОВЫЙ СТИЛЬ) ===============
def _build_figure(scores: List[int]):
    """
    Возвращает (fig, ax) — уже настроенную радиальную диаграмму
    в спокойной пастельной палитре с мягкими тенями.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    # Нормируем к 0..1
    vals = (np.array(scores, dtype=float) / 5.0).clip(0, 1)
    angles = np.linspace(0, 2 * pi, len(FACETS), endpoint=False)
    vals = np.concatenate([vals, [vals[0]]])
    angles = np.concatenate([angles, [angles[0]]])

    # Фигура
    fig = plt.figure(figsize=(7, 7), dpi=160)
    ax = fig.add_subplot(111, polar=True)

    # Стиль: светлый фон + мягкая сетка
    fig.patch.set_facecolor("#FFFFFF")
    ax.set_facecolor("#FBFBFD")

    # Наклон «сверху» и по часовой
    ax.set_theta_offset(pi / 2)
    ax.set_theta_direction(-1)

    # Подписи секторов
    ax.set_thetagrids(angles[:-1] * 180/pi, FACETS, fontsize=11, color="#2C2C2C")

    # Радиальные круги (лёгкая сетка)
    ax.set_rgrids([0.2, 0.4, 0.6, 0.8, 1.0], labels=["1", "2", "3", "4", "5"], angle=0, color="#A0A0A0")
    ax.set_ylim(0, 1.0)
    for gridline in ax.yaxis.get_gridlines():
        gridline.set_linestyle("-")
        gridline.set_linewidth(0.6)
        gridline.set_alpha(0.25)

    # Цветовая тема
    fill_color = "#7C9CF3"   # васильковый
    line_color = "#3D6AF2"   # насыщённый синий
    point_color = "#2B56E0"

    # «Тень» (слегка расширенная прозрачная заливка)
    ax.fill(angles, (vals * 0.98), color="#1E3A8A", alpha=0.07, zorder=1)

    # Основной полигон
    ax.plot(angles, vals, color=line_color, linewidth=2.2, zorder=3)
    ax.fill(angles, vals, color=fill_color, alpha=0.28, zorder=2)

    # Точки
    ax.scatter(angles[:-1], (vals[:-1] + 0.02).clip(0, 1), s=25, color=point_color, zorder=4)

    # Центр + подзаголовок
    ax.text(0.5, 0.5, "Финансовое колесо", transform=ax.transAxes,
            ha="center", va="center", fontsize=12, color="#555", alpha=0.8)

    # Отступы
    plt.tight_layout()
    return fig, ax


def render_png_and_pdf(scores: List[int]) -> Tuple[io.BytesIO, io.BytesIO]:
    """
    Рисует колесо, возвращает (png_bytes, pdf_bytes)
    """
    import matplotlib.pyplot as plt

    fig, ax = _build_figure(scores)

    # PNG
    png_buf = io.BytesIO()
    fig.savefig(png_buf, format="png", bbox_inches="tight")
    png_buf.seek(0)

    # PDF (тот же рисунок)
    pdf_buf = io.BytesIO()
    fig.savefig(pdf_buf, format="pdf", bbox_inches="tight")
    pdf_buf.seek(0)

    plt.close(fig)
    return png_buf, pdf_buf


# =============== ХЕНДЛЕРЫ БОТА ===============
def cmd_start(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    user_answers[user_id] = []

    kb = [["0", "1", "2", "3", "4", "5"]]
    update.message.reply_text(
        "Привет! Оценим ваше финансовое колесо по 8 сферам.\n"
        "Отвечайте числами от 0 до 5. Поехали!\n\n" + QUESTIONS[0],
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True, one_time_keyboard=True),
    )
    return ASKING


def handle_score(update: Update, context: CallbackContext) -> int:
    text = (update.message.text or "").strip()
    user_id = update.effective_user.id

    if text not in {"0", "1", "2", "3", "4", "5"}:
        update.message.reply_text("Пожалуйста, введите число от 0 до 5.")
        return ASKING

    user_answers.setdefault(user_id, []).append(int(text))
    idx = len(user_answers[user_id])

    if idx < NUM_Q:
        kb = [["0", "1", "2", "3", "4", "5"]]
        update.message.reply_text(
            QUESTIONS[idx],
            reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True, one_time_keyboard=True),
        )
        return ASKING

    # Все ответы собраны
    scores = user_answers[user_id][:NUM_Q]
    user_answers.pop(user_id, None)

    # 1) PNG + PDF
    png_buf, pdf_buf = render_png_and_pdf(scores)

    # 2) Краткое резюме
    summary = make_summary_text(scores)

    # 3) Отправляем PNG с подписью
    update.message.reply_photo(png_buf, caption=summary, reply_markup=ReplyKeyboardRemove())

    # 4) Чек-лист
    checklist = make_checklist(scores)
    update.message.reply_text(checklist)

    # 5) PDF-документ (удобно шарить)
    pdf_buf.name = "finance_wheel.pdf"  # чтобы у получателя имя файла было красивым
    update.message.reply_document(pdf_buf, filename="finance_wheel.pdf")

    update.message.reply_text("Готово. Повторить — /start")
    return ConversationHandler.END


def cmd_cancel(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    user_answers.pop(user_id, None)
    update.message.reply_text("Окей, остановил. Вернуться — /start", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# =============== MAIN (polling) ===============
def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={ASKING: [MessageHandler(Filters.text & ~Filters.command, handle_score)]},
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_user=True,
        per_chat=True,
        per_message=False,
    )
    dp.add_handler(conv)
    dp.add_handler(CommandHandler("cancel", cmd_cancel))

    # НИКАКИХ вебхуков — только polling
    updater.start_polling(clean=True)
    log.info("Polling started ✅")
    updater.idle()


if __name__ == "__main__":
    main()
