import os
import io
import logging
from math import pi
from typing import Dict, List

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, ConversationHandler

# Логирование
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TOKEN = os.getenv("TG_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("TG_BOT_TOKEN не задан!")  # обязательно!

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
user_answers: Dict[int, List[int]] = {}

def start(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    user_answers[user_id] = []
    kb = [["0", "1", "2", "3", "4", "5"]]
    update.message.reply_text(
        "Привет! Сейчас оценим ваши финансы по 8 сферам.\nОтвечайте числами 0–5.\n\n" + QUESTIONS[0],
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
    )
    return ASKING

def handle_score(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    ans = update.message.text.strip()
    if ans not in ("0", "1", "2", "3", "4", "5"):
        update.message.reply_text("Введите число 0–5.")
        return ASKING

    user_answers[user_id].append(int(ans))
    idx = len(user_answers[user_id])
    if idx < NUM_Q:
        kb = [["0", "1", "2", "3", "4", "5"]]
        update.message.reply_text(
            QUESTIONS[idx],
            reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
        )
        return ASKING
    
    update.message.reply_text("Готово! Скоро пришлю результат.", reply_markup=ReplyKeyboardRemove())
    user_answers.pop(user_id, None)
    return ConversationHandler.END

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={ASKING: [MessageHandler(Filters.text & ~Filters.command, handle_score)]},
        fallbacks=[]
    ))
    updater.start_polling()  # <-- ВОТ КЛЮЧ !!!
    updater.idle()

if __name__ == "__main__":
    main()

