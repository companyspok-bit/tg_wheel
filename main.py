# -*- coding: utf-8 -*-
# Telegram-бот «Колесо финансового баланса» — WEBHOOK (Render Web Service)
# Требования: python-telegram-bot==13.15, urllib3==1.26.20, six==1.16.0, matplotlib==3.8.4, numpy==2.3.4

import os
import re
import uuid
import logging
from typing import List

# Графика (без GUI)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters,
    ConversationHandler, CallbackContext,
)

# ---------- ЛОГИ ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("wheel-bot")
logging.getLogger("telegram").setLevel(logging.INFO)
logging.getLogger("telegram.ext").setLevel(logging.INFO)

# ---------- ОПРОС ----------
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
KEYBOARD = ReplyKeyboardMarkup([["0","1","2","3","4","5"]], resize_keyboard=True, one_time_keyboard=True)

def interpret_average(avg: float) -> str:
    if avg < 1.5: return "Критическое состояние"
    if avg < 2.5: return "Нижний уровень"
    if avg < 3.5: return "Средний уровень"
    if avg < 4.5: return "Хороший уровень"
    return "Отличный уровень"

def band_message(avg: float) -> str:
    if avg < 1.5:
        return ("Нормальный старт: сфокусируйся на базовых вещах — минимум лишних трат, "
                "простая таблица учёта и маленькая подушка.")
    if avg < 2.5:
        return ("Есть быстрый потенциал роста. Выбери 1–2 шага на неделю "
                "(например, 5% дохода сразу переводить в резерв).")
    if avg < 3.5:
        return ("База уже есть. Добавь структуру: автопереводы на цели и контроль «утечек».")
    if avg < 4.5:
        return ("Отличный фундамент! Подумай о диверсификации и защите (страховки/ИИС/налоги).")
    return ("Очень круто! Дополируй детали: настройка портфеля, автопополнения, "
            "техосмотр финансов раз в квартал.")

def gentle_hints(ans: List[int]) -> List[str]:
    tips = []
    if ans[2] <= 2: tips.append("Подушка: цель 1–2 ежемес. дохода, фиксированный % после зарплаты.")
    if ans[1] <= 2: tips.append("Пенсия: автоплатёж 3–5% на долгий счёт/ИИС — сила сложного процента.")
    if ans[5] <= 2: tips.append("Долги: реестр и стратегия «снежный ком»/«лавина», фиксируй платёж.")
    if ans[4] <= 2: tips.append("Мелкие резервы: отдельный «карман» для непредвиденных трат.")
    if ans[6] <= 2: tips.append("Lifestyle: планируй радости в рамках лимита — так проще держать курс.")
    if ans[0] <= 2 or ans[3] <= 2: tips.append("Цели: разбей на 3–6–12 мес. и поставь автопереводы.")
    return tips

def build_personal(avg: float, ans: List[int]) -> str:
    msg = band_message(avg)
    tips = gentle_hints(ans)
    if tips: msg += "\n\nЧто поможет прямо сейчас:\n• " + "\n• ".join(tips[:3])
    return msg

CHECKLIST_MAP = {
    "Подушка": ["Открой отдельный счёт для подушки."],
    "Пенсия": ["Настрой автоплатёж 3–5% на долгий счёт/ИИС."],
    "Долги": ["Составь реестр и выбери «снежный ком»/«лавина»."],
    "Мелкие резервы": ["Создай «карман» для мелких непредвиденных трат."],
    "Lifestyle": ["Запланируй 1–2 радости в рамках фиксированного лимита."],
    "Среднеср. цели": ["Определи 1–2 цели на 6–18 мес. и поставь автоплатёж."],
    "Короткие цели": ["Сформулируй цель на 3–6 мес. и разбей на шаги."],
    "Уверенность": ["Сделай 1 маленький шаг, который повысит уверенность сегодня."],
}
def build_checklist(ans: List[int]) -> List[str]:
    weakest = sorted(range(len(ans)), key=lambda i: ans[i])[:3]
    items = [f"— {SHORT_TITLES[i]}: {CHECKLIST_MAP.get(SHORT_TITLES[i], ['Шаг по сфере.'])[0]}" for i in weakest]
    items.append("— Поставь автопереводы/напоминания — держи ритм.")
    return items[:4]

# ---------- РИСОВАНИЕ КОЛЕСА ----------
def _apply_theme(ax, theme: str):
    light = (theme != "dark")
    bg = "#0B0F14" if not light else "#FFFFFF"
    grid = "#223444" if not light else "#E6E8EB"
    label = "#E8F1FF" if not light else "#1F2430"
    ax.figure.set_facecolor(bg)
    ax.set_facecolor(bg)
    ax.tick_params(colors=label)
    ax.yaxis.grid(color=grid)
    ax.xaxis.grid(color=grid)
    return bg, grid, label

def make_wheel_images(scores: List[int], titles: List[str], style: str = "radar",
                      theme: str = "light", color: str = "#7C4DFF"):
    """
    style: radar | donut | rose | neon
    theme: light | dark
    color: HEX (#RRGGBB)
    """
    if not re.match(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$", color or ""):
        color = "#7C4DFF"

    sid = uuid.uuid4().hex
    png_path = f"/tmp/wheel_{sid}.png"
    pdf_path = f"/tmp/wheel_{sid}.pdf"

    n = len(scores)
    data = np.array(scores, dtype=float)
    maxv = 5.0

    plt.rcParams.update({"figure.figsize": (6.3, 6.3), "savefig.bbox": "tight", "font.size": 10})

    if style == "donut":
        theta = np.linspace(0.0, 2*np.pi, n, endpoint=False)
        width = 2*np.pi / n * 0.9
        fig, ax = plt.subplots(subplot_kw=dict(polar=True))
        _apply_theme(ax, theme)
        ax.set_theta_offset(np.pi / 2); ax.set_theta_direction(-1)
        base = "#314559" if theme == "dark" else "#F1F3F5"
        edge = "#1E2B38" if theme == "dark" else "#E6E8EB"
        ax.bar(theta, [maxv]*n, width=width, bottom=0, color=base, edgecolor=edge, linewidth=1, zorder=1)
        ax.bar(theta, data, width=width, bottom=0, color=color, alpha=0.86, zorder=2)
        for ang, lab in zip(theta, titles):
            ax.text(ang, maxv + 0.35, lab, ha="center", va="center",
                    fontsize=9, color=("#E8F1FF" if theme=="dark" else "#1F2430"))
        ax.set_rticks([1,2,3,4,5]); ax.set_title("Колесо финансового баланса", pad=16)

    elif style == "rose":
        theta = np.linspace(0.0, 2*np.pi, n, endpoint=False)
        width = 2*np.pi / n * 0.9
        fig, ax = plt.subplots(subplot_kw=dict(polar=True))
        _apply_theme(ax, theme)
        ax.set_theta_offset(np.pi / 2); ax.set_theta_direction(-1)
        base = "#2C3E50" if theme == "dark" else "#EDF2F7"
        ax.bar(theta, [maxv]*n, width=width, bottom=0, color=base, alpha=0.35, zorder=1)
        alpha_vals = 0.35 + 0.65 * (data / maxv)
        for ang, r, a in zip(theta, data, alpha_vals):
            ax.bar([ang], [r], width=width, bottom=0, color=color, alpha=float(a), zorder=2)
        for ang, lab in zip(theta, titles):
            ax.text(ang, maxv + 0.35, lab, ha="center", va="center",
                    fontsize=9, color=("#E8F1FF" if theme=="dark" else "#1F2430"))
        ax.set_rticks([1,2,3,4,5]); ax.set_title("Колесо финансового баланса", pad=16)

    elif style == "neon":
        angles = np.linspace(0, 2*np.pi, n, endpoint=False).tolist()
        data_closed = np.concatenate([data, [data[0]]])
        angles_closed = angles + [angles[0]]
        fig, ax = plt.subplots(subplot_kw=dict(polar=True))
        _apply_theme(ax, "dark")
        ax.set_theta_offset(np.pi / 2); ax.set_theta_direction(-1)
        ax.set_rgrids([1,2,3,4,5], labels=["1","2","3","4","5"], color="#8AF6FF")
        ax.set_ylim(0, maxv)
        ax.yaxis.grid(color="#123A4A"); ax.xaxis.grid(color="#123A4A")
        ax.plot(angles_closed, data_closed, color="#00E5FF", linewidth=2.4)
        ax.fill(angles_closed, data_closed, color="#00E5FF", alpha=0.18)
        ax.set_xticks(angles); ax.set_xticklabels(titles, fontsize=9, color="#CDEBFF")
        ax.set_title("Колесо финансового баланса", pad=16, color="#CDEBFF")

    else:  # radar
        angles = np.linspace(0, 2*np.pi, n, endpoint=False).tolist()
        data_closed = np.concatenate([data, [data[0]]])
        angles_closed = angles + [angles[0]]
        fig, ax = plt.subplots(subplot_kw=dict(polar=True))
        _apply_theme(ax, theme)
        ax.set_theta_offset(np.pi / 2); ax.set_theta_direction(-1)
        ax.set_rgrids([1,2,3,4,5], labels=["1","2","3","4","5"])
        ax.set_ylim(0, maxv)
        ax.plot(angles_closed, data_closed, color=color, linewidth=2)
        ax.fill(angles_closed, data_closed, color=color, alpha=0.28)
        ax.set_xticks(angles); ax.set_xticklabels(titles, fontsize=9,
            color=("#E8F1FF" if theme=="dark" else "#1F2430"))
        ax.set_title("Колесо финансового баланса", pad=16)

    fig.savefig(png_path, dpi=180)
    fig.savefig(pdf_path)
    plt.close(fig)
    return png_path, pdf_path

# ---------- ХЕНДЛЕРЫ ----------
def start(update: Update, context: CallbackContext):
    context.user_data.clear()
    context.user_data["answers"] = []
    context.user_data["q_idx"] = 0
    context.user_data["style"] = (os.environ.get("WHEEL_STYLE", "radar").strip().lower() or "radar")
    context.user_data["theme"] = (os.environ.get("WHEEL_THEME", "light").strip().lower() or "light")
    context.user_data["color"] = (os.environ.get("WHEEL_COLOR", "#7C4DFF").strip() or "#7C4DFF")
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
        "Команды:\n"
        "/start — начать заново\n"
        "/style radar|donut|rose|neon — стиль\n"
        "/theme light|dark — тема\n"
        "/color #HEX — цвет\n"
        "/cancel — отменить"
    )

def style_cmd(update: Update, context: CallbackContext):
    parts = (update.message.text or "").split()
    if len(parts) == 2 and parts[1].lower() in ("radar","donut","rose","neon"):
        context.user_data["style"] = parts[1].lower()
        update.message.reply_text(f"Стиль сохранён: {parts[1].lower()}. Продолжаем!")
    else:
        update.message.reply_text("Используй: /style radar|donut|rose|neon")

def theme_cmd(update: Update, context: CallbackContext):
    parts = (update.message.text or "").split()
    if len(parts) == 2 and parts[1].lower() in ("light","dark"):
        context.user_data["theme"] = parts[1].lower()
        update.message.reply_text(f"Тема сохранена: {parts[1].lower()}.")
    else:
        update.message.reply_text("Используй: /theme light или /theme dark")

def color_cmd(update: Update, context: CallbackContext):
    parts = (update.message.text or "").split()
    if len(parts) == 2 and parts[1].startswith("#") and len(parts[1]) in (4,7):
        context.user_data["color"] = parts[1]
        update.message.reply_text(f"Цвет сохранён: {parts[1]}")
    else:
        update.message.reply_text("Используй HEX, пример: /color #7C4DFF")

def cancel(update: Update, context: CallbackContext):
    update.message.reply_text("Оценка отменена. Чтобы начать заново — /start.", reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    return ConversationHandler.END

def handle_rating(update: Update, context: CallbackContext):
    text = (update.message.text or "").strip()
    try:
        val = int(text)
        if val < 0 or val > 5: raise ValueError()
    except ValueError:
        update.message.reply_text("Выбери число 0–5 на клавиатуре ниже.", reply_markup=KEYBOARD)
        return GET_RATING

    context.user_data.setdefault("answers", []).append(val)
    context.user_data["q_idx"] = q_idx = context.user_data.get("q_idx", 0) + 1

    if q_idx < len(QUESTIONS):
        update.message.reply_text(QUESTIONS[q_idx], reply_markup=KEYBOARD)
        return GET_RATING

    # --- Финал ---
    answers = context.user_data["answers"]
    avg = float(sum(answers)) / len(answers)
    weakest_idx = sorted(range(len(answers)), key=lambda i: answers[i])[:3]
    weakest_txt = "\n".join([f"- {SHORT_TITLES[i]} → {answers[i]}" for i in weakest_idx])

    personal = build_personal(avg, answers)
    checklist = build_checklist(answers)

    style = context.user_data.get("style", "radar")
    theme = context.user_data.get("theme", "light")
    color = context.user_data.get("color", "#7C4DFF")
    png_path, pdf_path = make_wheel_images(answers, SHORT_TITLES, style=style, theme=theme, color=color)

    update.message.reply_text(
        f"Готово!\n\nСредняя оценка: {avg:.2f} / 5\n"
        f"Интерпретация: {interpret_average(avg)}\n\n"
        f"Три самые слабые зоны:\n{weakest_txt}\n\n"
        f"{personal}\n\n"
        f"Чек-лист на неделю:\n" + "\n".join(checklist) + "\n\n"
        f"Стиль: {style}, тема: {theme}. Сейчас пришлю PNG + PDF.",
        reply_markup=ReplyKeyboardRemove(),
    )

    errs = []
    try:
        with open(png_path, "rb") as f:
            update.message.reply_photo(photo=f, caption="Ваше колесо (PNG)")
    except Exception as e:
        logger.exception("send_photo failed"); errs.append(f"PNG: {e}")
    try:
        with open(pdf_path, "rb") as f:
            update.message.reply_document(document=f, filename="finance_wheel.pdf", caption="Ваше колесо (PDF)")
    except Exception as e:
        logger.exception("send_document failed"); errs.append(f"PDF: {e}")
    if errs:
        update.message.reply_text("Не удалось отправить файлы:\n" + "\n".join(f"• {x}" for x in errs))

    for p in (png_path, pdf_path):
        try:
            if os.path.exists(p): os.remove(p)
        except: pass

    context.user_data.clear()
    return ConversationHandler.END

# ---------- MAIN (WEBHOOK) ----------
def main():
    # 1) Токен
    token = os.environ.get("TG_BOT_TOKEN")
    if not token:
        raise RuntimeError("Не задан TG_BOT_TOKEN")

    # 2) Внешний HTTPS-URL Render (без порта!)
    host = os.environ.get("WEBHOOK_HOST")
    if not host:
        raise RuntimeError("Не задан WEBHOOK_HOST (например, https://tg-wheel-2.onrender.com)")
    host = host.strip().rstrip("/")  # без завершающего /

    # 3) Путь вебхука
    path = os.environ.get("WEBHOOK_PATH", f"/{token}")
    if not path.startswith("/"): path = "/" + path

    # 4) Порт: не задавай вручную в Render. Если всё-таки есть — берём число, иначе 10000.
    raw_port = (os.environ.get("PORT") or "").strip()
    port = int(raw_port) if raw_port.isdigit() else 10000
    logger.info("Resolved PORT=%s (raw=%r)", port, raw_port)

    # --- Telegram Updater/Dispatcher ---
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
    dp.add_handler(CommandHandler("theme", theme_cmd))
    dp.add_handler(CommandHandler("color", color_cmd))
    dp.add_handler(CommandHandler("cancel", cancel))

    # Снимаем старый webhook (на всякий случай)
    try:
        updater.bot.delete_webhook()
    except Exception as e:
        logger.warning("delete_webhook failed: %s", e)

    # Локальный сервер PTB
    logger.info("Starting webhook server on 0.0.0.0:%s url_path=%s", port, path)
    updater.start_webhook(listen="0.0.0.0", port=port, url_path=path)

    # Вешаем вебхук на внешний домен (без порта!)
    webhook_url = f"{host}{path}"
    logger.info("Setting webhook to %s", webhook_url)
    ok = updater.bot.set_webhook(url=webhook_url, max_connections=40)
    logger.info("set_webhook(): %s", ok)

    logger.info("Webhook started ✔ (idle)")
    updater.idle()

if __name__ == "__main__":
    main()

