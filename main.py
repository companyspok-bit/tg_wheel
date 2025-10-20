# main.py — «Колесо финансового баланса»
# PTB 13.15, режим POLLING. Кнопки 0–5, персональный финал и чек-лист.

import logging
import os
from typing import List
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters,
    ConversationHandler, CallbackContext,
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

def gentle_hints(answers: List[int]) -> List[str]:
    hints = []
    if answers[2] <= 2: hints.append("Подушка: цель 1–2 ежемес. дохода, переводи фиксированный % после зарплаты.")
    if answers[1] <= 2: hints.append("Пенсия: автоплатёж 3–5% на долгий счёт/ИИС — работает сложный процент.")
    if answers[5] <= 2: hints.append("Долги: реестр + стратегия «снежный ком»/«лавина», фиксируй ежемесячный платёж.")
    if answers[4] <= 2: hints.append("Мелкие резервы: отдельный «карман» для мелочей снижает стресс.")
    if answers[6] <= 2: hints.append("Lifestyle: запланируй маленькие радости в рамках бюджета — держать курс легче.")
    if answers[0] <= 2 or answers[3] <= 2: hints.append("Цели: разбей на 3–6–12 мес. и поставь автопереводы под каждую.")
    return hints

def build_personal_message(avg: float, answers: List[int]) -> str:
    msg = band_message(avg)
    tips = gentle_hints(answers)
    if tips:
        msg += "\n\nЧто поможет прямо сейчас:\n• " + "\n• ".join(tips[:3])
    return msg

CHECKLIST_MAP = {
    "Подушка": [
        "Открой отдельный счёт для подушки.",
        "Поставь автоперевод 5–10% после зарплаты.",
        "Цель: 1–2 ежемес. дохода, отметь дедлайн.",
    ],
    "Пенсия": [
        "Выбери долгосрочный счёт/ИИС.",
        "Настрой автоплатёж 3–5% от дохода.",
        "Раз в квартал проверяй распределение активов.",
    ],
    "Долги": [
        "Составь реестр долгов (ставка/сумма/минимум).",
        "Выбери «снежный ком» или «лавина».",
        "Зафиксируй ежемесячный платёж в календаре.",
    ],
    "Мелкие резервы": [
        "Создай «карман» для мелких непредвиденных.",
        "Определи месячный лимит, пополняй в начале месяца.",
        "Раз в неделю сверяй остаток.",
    ],
    "Lifestyle": [
        "Запланируй 1–2 радости в рамках бюджета.",
        "Выдели для них фиксированный лимит.",
        "Убери то, что не радует реально.",
    ],
    "Среднеср. цели": [
        "Определи 1–2 цели на 6–18 мес.",
        "Поставь автоплатёж под каждую.",
        "Раз в месяц сверяй прогресс.",
    ],
    "Короткие цели": [
        "Сформулируй цель на 3–6 мес.",
        "Разбей на 3–4 шага с датами.",
        "Отмечай выполнение еженедельно.",
    ],
    "Уверенность": [
        "Определи, что сильнее даст уверенность (подушка/план/страховка).",
        "Сделай один маленький шаг сегодня.",
        "Назначь повторную самопроверку через 30 дней.",
    ],
}

def build_checklist(answers: List[int]) -> List[str]:
    weakest = sorted(range(len(answers)), key=lambda i: answers[i])[:3]
    items = []
    for idx in weakest:
        title = SHORT_TITLES[idx]
        first = CHECKLIST_MAP.get(title, ["Сделай 1 маленький шаг по этой сфере."])[0]
        items.append(f"— {title}: {first}")
    items.append("— Поставь автопереводы/напоминания, чтобы держать ритм.")
    return items[:4]

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
        "• В финале — средняя оценка, слабые зоны, персональный совет и чек-лист\n\n"
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

    answers = context.user_data["answers"]
    avg = sum(answers) / len(answers)
    weakest_indices = sorted(range(len(answers)), key=lambda i: answers[i])[:3]
    weakest = "\n".join([f"- {SHORT_TITLES[i]} → {answers[i]}" for i in weakest_indices])

    personal = build_personal_message(avg, answers)
    checklist = build_checklist(answers)

    update.message.reply_text(
        f"Готово!\n\n"
        f"Средняя оценка: {avg:.2f} / 5\n"
        f"Интерпретация: {interpret_average(avg)}\n\n"
        f"Три самые слабые зоны:\n{weakest}\n\n"
        f"{personal}\n\n"
        f"Чек-лист на неделю:\n" + "\n".join(checklist) + "\n\n"
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

    # Только POLLING (без вебхуков)
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
