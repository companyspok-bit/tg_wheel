# main.py — Telegram бот «Колесо финансового баланса» (polling, без webhook)
import logging, os
from telegram import ReplyKeyboardRemove, Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, ConversationHandler, CallbackContext

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

GET_RATING = 1

QUESTIONS = [
    "1) Хватает ли на необходимые среднесрочные цели? (0–5)",
    "2) Забочусь ли я о будущей пенсии? (0–5)",
    "3) Есть ли подушка безопасности? (0–5)",
    "4) Есть ли небольшие цели (до года)? (0–5)",
    "5) Есть ли резерв на мелкие расходы? (0–5)",
    "6) Нет ли долгов (кроме ипотеки)? (0–5)",
    "7) Хватает ли на lifestyle (удовольствия/образ жизни)? (0–5)",
    "8) Общая уверенность в своём финансовом состоянии? (0–5)"
]

RECOMMENDATIONS = {
    'default': "Подумайте о распределении бюджета, создании резервов и сокращении долгов.",
    0: "Критично: начните с минимального резерва (1–2 зарплаты) и планирования бюджета.",
    1: "Очень плохо: составьте список расходов и приоритетов, ищите варианты дополнительного дохода.",
    2: "Ниже среднего: усиливайте контроль расходов и начните откладывать пусть маленькие суммы.",
    3: "Средне: есть база, но стоит улучшить резервы и цели.",
    4: "Хорошо: держите план, подумайте о диверсификации вложений.",
    5: "Отлично: продолжайте в том же духе и оптимизируйте налоги/инвестиции."
}

def interpret_average(avg: float) -> str:
    if avg < 1.5: return "Критическое состояние"
    if avg < 2.5: return "Нижний уровень"
    if avg < 3.5: return "Средний уровень"
    if avg < 4.5: return "Хороший уровень"
    return "Отличный уровень"

def start(update: Update, context: CallbackContext):
    user = update.effective_user
    context.user_data['answers'] = []
    context.user_data['q_idx'] = 0
    update.message.reply_text(
        "Привет! Я помогу вам за пару минут оценить ваше финансовое состояние по 8 ключевым сферам. "
        "Готовы начать?\n\n" + QUESTIONS[0]
    )
    return GET_RATING

def help_cmd(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Как это работает:\n"
        "• Я задаю 8 вопросов.\n"
        "• Отвечайте числами от 0 до 5.\n"
        "• В финале — ваша оценка и рекомендации.\n\n"
        "Команды:\n"
        "/start — начать заново\n"
        "/cancel — отменить\n"
        "/help — помощь"
    )

def handle_rating(update: Update, context: CallbackContext):
    text = update.message.text.strip()
    q_idx = context.user_data.get('q_idx', 0)
    try:
        val = int(text)
        if val < 0 or val > 5:
            raise ValueError()
    except ValueError:
        update.message.reply_text("Пожалуйста, введите число от 0 до 5.")
        return GET_RATING

    context.user_data.setdefault('answers', []).append(val)
    q_idx += 1
    context.user_data['q_idx'] = q_idx

    if q_idx < len(QUESTIONS):
        update.message.reply_text(QUESTIONS[q_idx])
        return GET_RATING

    answers = context.user_data['answers']
    avg = sum(answers) / len(answers)
    weakest_indices = sorted(range(len(answers)), key=lambda i: answers[i])[:3]
    weakest = "\n".join([f"- {QUESTIONS[i].split(')')[1].strip()} → {answers[i]}" for i in weakest_indices])

    recs = []
    for i, a in enumerate(answers):
        if a <= 2:
            recs.append(f"{i+1}) {QUESTIONS[i].split(')')[1].strip()}: {RECOMMENDATIONS.get(a, RECOMMENDATIONS['default'])}")
    recs_text = "Слабых мест мало — продолжайте в том же духе!" if not recs else "\n".join(recs)

    update.message.reply_text(
        f"Готово!\n\n"
        f"Средняя оценка: {avg:.2f} / 5\n"
        f"Три самых слабых пункта:\n{weakest}\n\n"
        f"Рекомендации:\n{recs_text}",
        reply_markup=ReplyKeyboardRemove()
    )
    context.user_data.clear()
    return ConversationHandler.END

def cancel(update: Update, context: CallbackContext):
    update.message.reply_text("Оценка отменена. Чтобы начать — /start", reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    return ConversationHandler.END

def main():
    token = os.environ.get("TG_BOT_TOKEN")
    if not token:
        raise RuntimeError("Не задан TG_BOT_TOKEN в переменных окружения.")

    updater = Updater(token=token, use_context=True)
    dp = updater.dispatcher

    conv = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={1: [MessageHandler(Filters.text & ~Filters.command, handle_rating)]},
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True
    )

    dp.add_handler(conv)
    dp.add_handler(CommandHandler('help', help_cmd))
    dp.add_handler(CommandHandler('cancel', cancel))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
