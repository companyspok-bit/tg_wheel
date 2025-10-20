# main.py — Telegram-бот «Колесо финансового баланса»
# Совместим с python-telegram-bot==13.15 (режим polling)

import logging
import os
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    ConversationHandler,
    CallbackContext,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

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

RECOMMENDATIONS = {
    "default": "Сфокусируйся на распределении бюджета, резервах и снижении долгов.",
    0: "Критично: начни с минимальной подушки (1–2 зарплаты) и базового учёта расходов.",
    1: "Очень низко: определи приоритеты и поищи 1–2 быстрых источника экономии/дохода.",
    2: "Ниже среднего: поставь автоперевод хоть 3–5% на резерв — важна регулярность.",
    3: "Средне: база есть — усилить резервы и конкретизировать цели.",
    4: "Хорошо: подумай о диверсификации и защите (страховки/налоги).",
    5: "Отлично: поддерживай режим и оптимизируй портфель/налоги.",
}

KEYBOARD = ReplyKeyboardMarkup([["0", "1", "2", "3", "4", "5"]],
                               resize_keyboard=True, one_time_keyboard=True)

# --- Персональные финальные сообщения ---

def band_message(avg: float) -> str:
    if avg < 1.5:
        return ("Это нормальный старт — ты уже сделал первый шаг. "
                "Сфокусируйся на базовых вещах: минимум лишних трат, простая таблица учёта "
                "и маленькая подушка. Маленькие шаги каждый день дают большой прогресс.")
    if avg < 2.5:
        return ("Есть быстрый потенциал роста. Выбери 1–2 шага на неделю "
                "(например, 5% дохода сразу переводить в резерв). "
                "Маленькие победы быстро накапливаются.")
    if avg < 3.5:
        return ("База уже есть. Добавь структуру: автопереводы на цели и лёгкий контроль «утечек». "
                "Немного дисциплины — и выйдешь на высокий уровень.")
    if avg < 4.5:
        return ("Отличный фундамент! Подумай о диверсификации и защите: страховки, пенсионный план, "
                "оптимизация налогов. Это усилит устойчивость и ускорит прогресс.")
    return ("Очень круто! Осталось отполировать детали: тонкая настройка портфеля, "
            "автопополнения и «техосмотр» финансов раз в квартал.")

def gentle_hints(answers: list) -> list:
    hints = []
    # индексы по QUESTIONS
    if answers[2] <= 2:  # Подушка безопасности
        hints.append("Подушка: цель 1–2 ежемесячных дохода, переводи фиксированный % сразу после зарплаты.")
    if answers[1] <= 2:  # Пенсия
        hints.append("Пенсия: запусти автоплатёж 3–5% на долгий счёт/ИИС — эффект накопления сильный.")
    if answers[5] <= 2:  # Долги
        hints.append("Долги: реестр + стратегия «снежный ком»/«лавина», зафиксируй ежемесячный платёж.")
    if answers[4] <= 2:  # Мелкие резервы
        hints.append("Мелкие резервы: отдельный «карман» для мелочей снижает стресс и срывы бюджета.")
    if answers[6] <= 2:  # Lifestyle
        hints.append("Lifestyle: запланируй маленькие радости в рамках бюджета — так курс держать легче.")
    if answers[0] <= 2 or answers[3] <= 2:  # Цели и короткие цели
        hints.append("Цели: разбей на 3–6–12 мес. и поставь автопереводы под каждую.")
    return hints

def build_personal_message(avg: float, answers: list) -> str:
    msg = band_message(avg)
    tips = gentle_hints(answers)
    if tips:
        msg += "\n\nЧто поможет прямо сейчас:\n• " + "\n• ".join(tips[:3])
    return msg

# --- Бизнес-логика ---

def interpret_average(avg: float) -> str:
    if avg < 1.5:
        return "Критическое состояние"
    if avg < 2.5:
        return "Нижний уровень"
    if avg < 3.5:
        return "Средний уровень"
    if avg < 4.5:
        return "Хороший уровень"
    return "Отличный уровень"

def start(update: Update, context: CallbackContext):
    context.user_data["answers"] = []
    context.user_data["q_idx"] = 0
    update.message.reply_text(
        "Привет! За пару минут оценим твои финансы по 8 сферам. Готов начать?\n\n" + QUESTIONS[0],
        reply_markup=KEYBOARD,
    )
    return GET_RATING

def help_cmd(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Как это работает:\n"
        "• 8 вопросов\n"
        "• Отвечай числами 0–5 (кнопки ниже)\n"
        "• В финале — средняя оценка, слабые зоны и советы\n\n"
        "Команды:\n/start — начать заново\n/cancel — отменить\n/help — помощь"
    )

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

    # финальный расчёт
    answers = context.user_data["answers"]
    avg = sum(answers) / len(answers)
    weakest_indices = sorted(range(len(answers)), key=lambda i: answers[i])[:3]
    weakest = "\n".join([f"- {QUESTIONS[i].split(')')[1].strip()} → {answers[i]}" for i in weakest_indices])

    personal = build_personal_message(avg, answers)

    update.message.reply_text(
        f"Готово!\n\n"
        f"Средняя оценка: {avg:.2f} / 5\n"
        f"Интерпретация: {interpret_average(avg)}\n\n"
        f"Три самых слабых пункта:\n{weakest}\n\n"
        f"{personal}\n\n"
        f"Чтобы пройти заново — /start",
        reply_markup=ReplyKeyboardRemove(),
    )
    context.user_data.clear()
    return ConversationHandler.END

def main():
    token = os.environ.get("TG_BOT_TOKEN")
    if not token:
        raise RuntimeError("Не задан TG_BOT_TOKEN в переменных окружения.")

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
    dp.add_handler(CommandHandler("cancel", cancel))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
