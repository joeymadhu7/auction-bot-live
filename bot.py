# Complete working bot.py
# pip install python-telegram-bot==20.7

import asyncio
import random
import time
import os

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import TOKEN, STARTING_PURSE, MAX_PLAYERS, BID_TIMEOUT, ADMIN_IDS
from data import actresses as ACTRESSES_MASTER

teams = {}
waiting_team_name = set()
pending_reset_confirm = set()
pending_kick_confirm = {}
pending_cancel_confirm = {}

actress_queue = []
unsold_queue = []

auction = {
    "active": False,
    "item": None,
    "bid": 0,
    "bidder": None,
    "chat_id": None,
    "end_time": 0,
    "task": None,
    "final_call_sent": False,
}


def is_admin(uid):
    return uid in ADMIN_IDS


def min_required_purse(team):
    remaining_slots = MAX_PLAYERS - len(team["players"])
    if remaining_slots <= 1:
        return 0
    return (remaining_slots - 1) * 3

async def helpauction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎯 AUCTION HELP\n\n"
        "/join → Join team\n\n"
        "Reply only number to bid\n"
        "Correct: 25 ✅\n"
        "Wrong: 25cr / 25.5 / ₹25 ❌\n\n"
        "💰 Starting purse: 200 Cr\n"
        "🎭 Max players: 8\n"
        "👥 Max teams: 10\n"
        "🔒 Reserve rule: remaining slots × 3 Cr\n\n"
        "No spam please."
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎭 ACTRESS FANTASY AUCTION\n\n"
        "/join - join team\n"
        "/helpauction - rules\n"
        "/startauction - admin start\n"
        "/next - admin next actress\n"
        "/list - admin remaining actresses\n"
        "/history - admin full squads\n"
        "/reset - full reset\n"
        "/cancel actress name - reset sold actress\n"
        "/auction actress name - bring unsold actress back\n"
        "/kickauction @username - remove team\n\n"
        "💰 Reply only number to bid"
    )



async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if uid in teams:
        await update.message.reply_text("⚠️ Already joined")
        return

    if len(teams) >= 10:
        await update.message.reply_text(
            "⚠️ Already 10 teams joined\n\n"
            "Please join next auction and enjoy spectating the auction 🎭\n\n"
            "Follow rules and don't spam me."
        )
        return

    waiting_team_name.add(uid)
    await update.message.reply_text("📝 Send your team name")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    uid = update.effective_user.id
    text = update.message.text.strip()

    # Team registration
    if uid in waiting_team_name:
        for t in teams.values():
            if t["team_name"].lower() == text.lower():
                await update.message.reply_text("❌ Team name already taken")
                return

        teams[uid] = {
            "team_name": text,
            "owner": update.effective_user.username or update.effective_user.full_name,
            "purse": STARTING_PURSE,
            "players": [],
        }

        waiting_team_name.remove(uid)
        await update.message.reply_text(f"✅ {text} joined with {STARTING_PURSE} Cr")
        return

    # Reset confirmation
    if uid in pending_reset_confirm:
        pending_reset_confirm.remove(uid)

        if text.lower() in ["yes", "y"]:
            teams.clear()
            actress_queue.clear()
            unsold_queue.clear()
            auction["active"] = False
            await update.message.reply_text("♻️ Full reset complete. Teams removed.")
        else:
            await update.message.reply_text("Reset cancelled")
        return

    # Kick confirmation
    if uid in pending_kick_confirm:
        target = pending_kick_confirm.pop(uid)

        if text.lower() not in ["yes", "y"]:
            await update.message.reply_text("Kick cancelled")
            return

        for k, v in list(teams.items()):
            owner = str(v["owner"])

            if target.lower() in owner.lower() or target.lower() == f"@{owner}".lower():

                for player in v["players"]:
                    for actress in ACTRESSES_MASTER:
                        if actress["name"].lower() == player["name"].lower():
                            actress_queue.insert(0, actress)
                            break

                del teams[k]

                await update.message.reply_text(
                    f"🚫 Removed {target}\n🎭 Bought actresses returned to auction"
                )
                return

        await update.message.reply_text("❌ User not found")
        return

    # Cancel confirmation flow
    if uid in pending_cancel_confirm:
        session = pending_cancel_confirm[uid]

        if session["type"] == "select":
            if not text.isdigit():
                await update.message.reply_text("Reply with number 🔢")
                return

            idx = int(text) - 1
            options = session["options"]

            if idx < 0 or idx >= len(options):
                await update.message.reply_text("Invalid choice ❌")
                return

            chosen = options[idx]
            pending_cancel_confirm[uid] = {
                "type": "confirm",
                "name": chosen,
            }

            await update.message.reply_text(
                f"♻️ Confirm *{chosen}* ?\nReply YES / NO",
                parse_mode="Markdown"
            )
            return

        if session["type"] == "confirm":
            if text.lower() not in ["yes", "y"]:
                del pending_cancel_confirm[uid]
                await update.message.reply_text("Cancel aborted ❌")
                return

            target_name = session["name"]
            del pending_cancel_confirm[uid]

            for t in teams.values():
                for p in t["players"][:]:
                    if p["name"].lower() == target_name.lower():
                        t["players"].remove(p)
                        t["purse"] += p["price"]

                        for a in ACTRESSES_MASTER:
                            if a["name"].lower() == target_name.lower():
                                actress_queue.insert(0, a)
                                break

                        await update.message.reply_text(
                            f"♻️ {target_name} added back to auction 🎭"
                        )
                        return

            await update.message.reply_text("❌ Not found in sold list")
            return

    # Bidding
    if auction["active"] and uid in teams and text.isdigit():
        bid = int(text)
        team = teams[uid]

        if len(team["players"]) >= MAX_PLAYERS:
            await update.message.reply_text("🚫 Max players reached")
            return

        reserve_needed = min_required_purse(team)
        max_allowed = team["purse"] - reserve_needed

        if bid <= auction["bid"]:
            await update.message.reply_text(
                f"⬆️ Bid must be more than {auction['bid']} Cr"
            )
            return

        if bid > max_allowed:
            await update.message.reply_text(
                f"⚠️ Max allowed is {max_allowed} Cr"
            )
            return

        auction["bid"] = bid
        auction["bidder"] = uid
        auction["end_time"] = time.time() + BID_TIMEOUT
        auction["final_call_sent"] = False

        await update.message.reply_text(
            f"🔥 {team['team_name']} bids {bid} Cr 🔥"
        )


async def startauction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    actress_queue.clear()
    actress_queue.extend(ACTRESSES_MASTER.copy())
    random.shuffle(actress_queue)
    unsold_queue.clear()

    await update.message.reply_text(
        f"🚀 Auction started with {len(actress_queue)} actresses"
    )

    await next_item(update.effective_chat.id, context)


async def next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    await next_item(update.effective_chat.id, context)


async def next_item(chat_id, context):
    if auction["active"]:
        return

    if not actress_queue:
        if unsold_queue:
            actress_queue.extend(unsold_queue)
            unsold_queue.clear()
            random.shuffle(actress_queue)
        else:
            await context.bot.send_message(chat_id, "🏁 Auction completed")
            return

    item = actress_queue.pop(0)

    auction.update({
        "active": True,
        "item": item,
        "bid": int(item.get("base_price", 2)),
        "bidder": None,
        "chat_id": chat_id,
        "end_time": time.time() + BID_TIMEOUT,
        "final_call_sent": False,
    })

    msg = (
        f"🎬 {item['name']}\n"
        f"💰 Base Price: {auction['bid']} Cr\n"
        f"⏳ Timer: 15 seconds\n"
        f"🔥 Reply your bid now"
    )

    path = item.get("image", "")

    if path and os.path.exists(path):
        try:
            with open(path, "rb") as img:
                await context.bot.send_photo(
                    chat_id,
                    photo=img,
                    caption=msg
                )
        except Exception:
            await context.bot.send_message(
                chat_id,
                msg + "\n\n⚠️ Image failed, sent as text only"
            )
    else:
        await context.bot.send_message(
            chat_id,
            msg
        )

    auction["task"] = asyncio.create_task(countdown(context))


async def countdown(context):
    while auction["active"]:
        remain = int(auction["end_time"] - time.time())

        if remain <= 5 and not auction["final_call_sent"]:
            auction["final_call_sent"] = True

            if auction["bidder"]:
                t = teams[auction["bidder"]]
                await context.bot.send_message(
                    auction["chat_id"],
                    f"🔔 FINAL CALL!\n\n"
                    f"Any more bids?\n"
                    f"Can I sell to {t['team_name']} for {auction['bid']} Cr? 🎯"
                )
            else:
                await context.bot.send_message(
                    auction["chat_id"],
                    f"⚠️ FINAL CALL!\n\n"
                    f"No bids yet for {auction['item']['name']}\n"
                    f"Otherwise she will go UNSOLD ❌"
                )

        if remain <= 0:
            break

        await asyncio.sleep(1)

    await finalize(context)


async def finalize(context):
    if not auction["active"]:
        return

    item = auction["item"]
    bidder = auction["bidder"]
    bid = auction["bid"]
    chat_id = auction["chat_id"]

    auction["active"] = False

    if bidder:
        t = teams[bidder]
        t["purse"] -= bid
        t["players"].append({
            "name": item["name"],
            "price": bid
        })

        await context.bot.send_message(
            chat_id,
            f"🏆 SOLD\n"
            f"{item['name']} → {t['team_name']}\n"
            f"💰 {bid} Cr\n"
            f"💼 Remaining: {t['purse']} Cr"
        )
    else:
        unsold_queue.append(item)

        await context.bot.send_message(
            chat_id,
            f"❌ UNSOLD: {item['name']}\n"
            f"She returns for unsold round later 🔁"
        )


async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    names = [a['name'] for a in actress_queue]
    names += [f"{a['name']} (unsold)" for a in unsold_queue]

    if not names:
        await update.message.reply_text("No actresses remaining")
        return

    await update.message.reply_text(
        "🎭 Remaining\n\n" + "\n".join(names[:100])
    )


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    msg = "📜 HISTORY\n\n"

    for t in teams.values():
        msg += f"{t['team_name']} - @{t['owner']} - Rem {t['purse']} Cr ({len(t['players'])}/{MAX_PLAYERS})\n"

        for i in range(MAX_PLAYERS):
            if i < len(t['players']):
                p = t['players'][i]
                msg += f"{i+1}. {p['name']} - {p['price']} Cr\n"
            else:
                msg += f"{i+1}.\n"

        msg += "\n"

    await update.message.reply_text(msg)


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    pending_reset_confirm.add(update.effective_user.id)
    await update.message.reply_text(
        "⚠️ Full reset removes teams also. Reply YES to confirm"
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if auction["active"]:
        await update.message.reply_text("⚠️ Cannot cancel during live bidding")
        return

    query = " ".join(context.args).strip().lower()
    if not query:
        await update.message.reply_text("❌ Use /cancel actress name")
        return

    sold_names = []
    for t in teams.values():
        for p in t["players"]:
            sold_names.append(p["name"])

    matches = [n for n in sold_names if query in n.lower()]

    if not matches:
        await update.message.reply_text("❌ No sold actress match found")
        return

    uid = update.effective_user.id

    if len(matches) == 1:
        pending_cancel_confirm[uid] = {
            "type": "confirm",
            "name": matches[0],
        }

        await update.message.reply_text(
            f"♻️ Did you mean *{matches[0]}* ?\nReply YES / NO",
            parse_mode="Markdown"
        )
        return

    pending_cancel_confirm[uid] = {
        "type": "select",
        "options": matches,
    }

    msg = "✨ Multiple matches found:\n\n"
    for i, m in enumerate(matches, 1):
        msg += f"{i}. {m}\n"
    msg += "\nReply with number 🔢"

    await update.message.reply_text(msg)

async def nextaccelerated(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "Use: /nextaccelerated actress name"
        )
        return

    query = " ".join(context.args).lower()

    # check sold first
    for t in teams.values():
        for p in t["players"]:
            if query in p["name"].lower():
                await update.message.reply_text(
                    f"❌ {p['name']} is already SOLD"
                )
                return

    # search unsold queue
    for actress in unsold_queue:
        if query in actress["name"].lower():
            if auction["active"]:
                await update.message.reply_text(
                    "⚠️ Current auction running first"
                )
                return

            unsold_queue.remove(actress)
            actress_queue.insert(0, actress)

            await update.message.reply_text(
                f"🔥 {actress['name']} moved as NEXT auction"
            )
            return

    await update.message.reply_text(
        "❌ Actress not found in unsold list"
    )

async def endauction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    auction["active"] = False

    mentions = []

    for t in teams.values():
        owner = t.get("owner", "")
        if owner:
            mentions.append(f"@{owner}")

    msg = (
        "🏁 AUCTION CLOSED\n\n"
        + "\n".join(mentions)
        + "\n\n❤️ Thanks for participating\n\n"
        "🤖 Results will be declared soon with the help of AI"
    )

    await update.message.reply_text(msg)


async def reauction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    name = " ".join(context.args).lower()

    for a in unsold_queue[:]:
        if name in a["name"].lower():
            unsold_queue.remove(a)
            actress_queue.insert(0, a)
            await update.message.reply_text(
                f"🔁 {a['name']} moved back to live queue"
            )
            return

    await update.message.reply_text("Not found in unsold list")


async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    target = " ".join(context.args).strip()
    if not target:
        await update.message.reply_text("Use /kickauction @username")
        return

    pending_kick_confirm[update.effective_user.id] = target
    await update.message.reply_text(
        f"⚠️ Kick {target}? Reply YES to confirm"
    )

async def unsoldlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not unsold_queue:
        await update.message.reply_text(
            "✅ No unsold actresses right now"
        )
        return

    msg = "📋 UNSOLD ACTRESSES\n\n"

    for i, actress in enumerate(unsold_queue, 1):
        msg += f"{i}. {actress['name']}\n"

    await update.message.reply_text(msg)

def main():
    app = (
        Application.builder()
        .token(TOKEN)
        .read_timeout(60)
        .write_timeout(60)
        .connect_timeout(60)
        .pool_timeout(60)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("join", join))
    app.add_handler(CommandHandler("startauction", startauction))
    app.add_handler(CommandHandler("next", next))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("auction", reauction))
    app.add_handler(CommandHandler("kickauction", kick))
    app.add_handler(CommandHandler("helpauction", helpauction))
    app.add_handler(CommandHandler("nextaccelerated", nextaccelerated))
    app.add_handler(CommandHandler("endauction", endauction))
    app.add_handler(CommandHandler("unsoldlist", unsoldlist))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("🔥 Auction bot running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
