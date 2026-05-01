#!/usr/bin/env python3
"""DSA Revision Bot — Spaced Repetition Reminders via Telegram"""

import logging
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import database as db

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")

# Conversation states
TITLE, NOTES, CATEGORY = range(3)

CATEGORIES = [
    ["Arrays", "Strings"],
    ["Trees", "Graphs"],
    ["DP", "Sorting"],
    ["Linked List", "Stack/Queue"],
    ["Binary Search", "Backtracking"],
    ["Heap", "Other"],
]

STAGE_LABELS = {0: "1st review (1 day)", 1: "2nd review (2 days)", 2: "3rd review (1 week)", 3: "4th review (1 month)"}


# ─── Helpers ────────────────────────────────────────────────────────────────

def category_keyboard():
    rows = []
    for row in CATEGORIES:
        rows.append([InlineKeyboardButton(c, callback_data=f"cat_{c}") for c in row])
    return InlineKeyboardMarkup(rows)


def review_keyboard(question_id: int):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Done — Revised!", callback_data=f"done_{question_id}"),
        ],
        [
            InlineKeyboardButton("⏰ Snooze 4h", callback_data=f"snooze4_{question_id}"),
            InlineKeyboardButton("📅 Tomorrow", callback_data=f"tomorrow_{question_id}"),
        ],
    ])


async def send_reminder(bot, chat_id: int, question: dict):
    review_count = question["review_count"]
    stage = min(review_count, len(db.INTERVALS) - 1)
    next_days = db.INTERVALS[min(review_count + 1, len(db.INTERVALS) - 1)]

    stage_emoji = ["1️⃣", "2️⃣", "3️⃣", "4️⃣+"][min(review_count, 3)]

    text = (
        f"🔔 *DSA Revision Time!* {stage_emoji}\n\n"
        f"📌 *{question['title']}*\n"
        f"🏷️ Category: {question['category']}\n"
    )
    if question.get("notes"):
        text += f"📝 Notes: {question['notes']}\n"

    if review_count < len(db.INTERVALS):
        text += f"\n✅ Mark done → next reminder in *{next_days} days*"
    else:
        text += "\n🏆 Fully mastered! Monthly maintenance review."

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=review_keyboard(question["id"]),
        )
        db.update_last_reminded(question["id"])
    except Exception as e:
        logger.error(f"Failed to send reminder for q#{question['id']}: {e}")


# ─── Command Handlers ────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *Welcome to DSA Revision Bot!*\n\n"
        "I help you retain DSA knowledge with spaced repetition:\n"
        "📅 *1 day → 2 days → 1 week → 1 month*\n\n"
        "I'll keep reminding you every 4 hours until you mark a question as done!\n\n"
        "*Commands:*\n"
        "/add — Add a DSA question you just studied\n"
        "/pending — See what's due for review now\n"
        "/list — Browse all your questions\n"
        "/stats — Your revision statistics\n"
        "/delete `<id>` — Remove a question\n"
        "/help — Show this message"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, context)


# ─── Add Question Flow ────────────────────────────────────────────────────────

async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📝 *Add New DSA Question*\n\n"
        "What's the question or topic title?\n"
        "_(e.g. 'Two Sum - LeetCode #1' or 'Binary Search pattern')_",
        parse_mode="Markdown",
    )
    return TITLE


async def add_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["title"] = update.message.text.strip()
    await update.message.reply_text(
        "📋 Add any notes, approach, or key insight?\n_(Type your notes or /skip)_",
        parse_mode="Markdown",
    )
    return NOTES


async def add_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["notes"] = update.message.text.strip()
    await update.message.reply_text("🏷️ Pick a category:", reply_markup=category_keyboard())
    return CATEGORY


async def skip_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["notes"] = ""
    await update.message.reply_text("🏷️ Pick a category:", reply_markup=category_keyboard())
    return CATEGORY


async def add_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    category = query.data.replace("cat_", "")
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    title = context.user_data.get("title", "")
    notes = context.user_data.get("notes", "")

    qid = db.add_question(user_id, chat_id, title, notes, category)

    await query.edit_message_text(
        f"✅ *Question added!* (ID: {qid})\n\n"
        f"📌 *{title}*\n"
        f"🏷️ {category}\n\n"
        f"📅 First reminder: *tomorrow*\n"
        f"Then: 2 days → 1 week → 1 month\n\n"
        f"I'll ping you every 4h until you mark it done!",
        parse_mode="Markdown",
    )
    context.user_data.clear()
    return ConversationHandler.END


async def add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END


# ─── List / Pending ──────────────────────────────────────────────────────────

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    questions = db.get_user_questions(user_id)

    if not questions:
        await update.message.reply_text("📭 No questions yet. Use /add to get started!")
        return

    now = datetime.now()
    lines = ["📚 *Your DSA Questions:*\n"]
    for q in questions:
        q = dict(q)
        nxt = datetime.strptime(q["next_review"], "%Y-%m-%d %H:%M")
        overdue = nxt <= now
        status = "🔴 DUE NOW" if overdue else f"📅 {nxt.strftime('%b %d')}"
        stage = min(q["review_count"], len(db.INTERVALS) - 1)
        lines.append(
            f"*{q['id']}.* {q['title']}\n"
            f"   🏷️ {q['category']} | {status} | Review #{q['review_count'] + 1}"
        )

    await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")


async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    questions = db.get_due_for_user(user_id, now_str)

    if not questions:
        await update.message.reply_text("🎉 You're all caught up! No pending reviews.")
        return

    await update.message.reply_text(
        f"⏰ *{len(questions)} question(s) due for review:*",
        parse_mode="Markdown",
    )
    for q in questions:
        await send_reminder(context.bot, q["chat_id"], dict(q))


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    s = db.get_stats(user_id)
    text = (
        f"📊 *Your DSA Revision Stats*\n\n"
        f"📚 Total Questions: *{s['total']}*\n"
        f"🏆 Fully Mastered: *{s['mastered']}*\n"
        f"🔄 Total Reviews Done: *{s['total_reviews']}*\n"
        f"⏰ Due Right Now: *{s['due_now']}*\n\n"
        f"Keep grinding! 💪"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /delete <question_id>\nFind IDs with /list")
        return
    qid = int(args[0])
    removed = db.delete_question(qid, user_id)
    if removed:
        await update.message.reply_text(f"🗑️ Question #{qid} removed.")
    else:
        await update.message.reply_text(f"❌ Question #{qid} not found or doesn't belong to you.")


# ─── Button Callbacks ─────────────────────────────────────────────────────────

async def handle_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Great work! Marked as revised ✅")

    qid = int(query.data.split("_")[1])
    result = db.mark_reviewed(qid)

    if not result:
        await query.edit_message_text("❌ Question not found.")
        return

    new_count = result["review_count"]
    if new_count < len(db.INTERVALS):
        next_days = db.INTERVALS[min(new_count, len(db.INTERVALS) - 1)]
        next_msg = f"📅 Next reminder in *{next_days} days*"
    else:
        next_msg = "🏆 All stages complete! Monthly refresher scheduled."

    await query.edit_message_text(
        f"🎉 *Revision #{new_count} complete!*\n\n"
        f"📌 {result['title']}\n\n"
        f"{next_msg}",
        parse_mode="Markdown",
    )


async def handle_snooze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split("_")
    action = parts[0]
    qid = int(parts[1])

    if action == "snooze4":
        until = datetime.now() + timedelta(hours=4)
        label = "4 hours"
    else:  # tomorrow
        until = datetime.now() + timedelta(days=1)
        label = "tomorrow"

    await query.answer(f"Snoozed for {label}")
    db.snooze_question(qid, until)
    await query.edit_message_text(
        f"⏰ Got it! I'll remind you again in *{label}*.",
        parse_mode="Markdown",
    )


# ─── Scheduler Job ───────────────────────────────────────────────────────────

async def job_send_reminders(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M")
    four_hours_ago = (now - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M")

    questions = db.get_due_questions(now_str, four_hours_ago)
    logger.info(f"Reminder job: {len(questions)} question(s) due")

    for q in questions:
        await send_reminder(context.bot, q["chat_id"], dict(q))


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    db.init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
        states={
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_title)],
            NOTES: [
                CommandHandler("skip", skip_notes),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_notes),
            ],
            CATEGORY: [CallbackQueryHandler(add_category, pattern=r"^cat_")],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
        per_message=False,
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("pending", cmd_pending))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("delete", cmd_delete))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(handle_done, pattern=r"^done_"))
    app.add_handler(CallbackQueryHandler(handle_snooze, pattern=r"^(snooze4|tomorrow)_"))

    # Check every hour; re-remind every 4h until marked done
    app.job_queue.run_repeating(job_send_reminders, interval=3600, first=10)

    logger.info("DSA Revision Bot is running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    import asyncio
    asyncio.set_event_loop(asyncio.new_event_loop())
    main()
