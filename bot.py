# ╔══════════════════════════════════════════════════════════════╗
# ║         ACTRESS FANZY LEAGUE — AUCTION BOT                  ║
# ║         pip install python-telegram-bot==20.7               ║
# ╚══════════════════════════════════════════════════════════════╝

import asyncio
import random
import time

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from config import TOKEN, STARTING_PURSE, MAX_PLAYERS, BID_TIMEOUT, ADMIN_IDS
from data import actresses as ACTRESSES_MASTER

# ── State ────────────────────────────────────────────────────────────────────
teams                  = {}
waiting_team_name      = set()
pending_reset_confirm  = set()
pending_kick_confirm   = {}
pending_cancel_confirm = {}

actress_queue  = []
unsold_queue   = []
last_pinned_id = None

auction = {
    "active":          False,
    "item":            None,
    "bid":             0,
    "bidder":          None,
    "chat_id":         None,
    "end_time":        0,
    "task":            None,
    "final_call_sent": False,
    "last_image":      None,
    "milestones":      set(),
}

# ── Fancy font converter ──────────────────────────────────────────────────────
def fancy(text: str) -> str:
    """Convert A-Z a-z 0-9 to Mathematical Bold Script Unicode block."""
    BOLD_SCRIPT_UPPER = (
        "𝓐𝓑𝓒𝓓𝓔𝓕𝓖𝓗𝓘𝓙𝓚𝓛𝓜𝓝𝓞𝓟𝓠𝓡𝓢𝓣𝓤𝓥𝓦𝓧𝓨𝓩"
    )
    BOLD_SCRIPT_LOWER = (
        "𝓪𝓫𝓬𝓭𝓮𝓯𝓰𝓱𝓲𝓳𝓴𝓵𝓶𝓷𝓸𝓹𝓺𝓻𝓼𝓽𝓾𝓿𝔀𝔁𝔂𝔃"
    )
    result = []
    for ch in text:
        if "A" <= ch <= "Z":
            result.append(BOLD_SCRIPT_UPPER[ord(ch) - ord("A")])
        elif "a" <= ch <= "z":
            result.append(BOLD_SCRIPT_LOWER[ord(ch) - ord("a")])
        else:
            result.append(ch)
    return "".join(result)


# ── Helpers ──────────────────────────────────────────────────────────────────
def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


def min_required_purse(team: dict) -> int:
    remaining_slots = MAX_PLAYERS - len(team["players"])
    if remaining_slots <= 1:
        return 0
    return (remaining_slots - 1) * 3


def divider() -> str:
    return "━━━━━━━━━━━━━━━━━━━━"


def pick_image(images: list):
    """Pick a random token, preferring one not shown last."""
    if not images:
        return None
    if len(images) == 1:
        return images[0]
    last    = auction.get("last_image")
    choices = [img for img in images if img != last]
    chosen  = random.choice(choices if choices else images)
    auction["last_image"] = chosen
    return chosen


# ── /start ───────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"{divider()}\n"
        f"🎭 <b>ACTRESS FANZY LEAGUE</b>\n"
        f"{divider()}\n\n"
        f"👤 /join — register your team\n"
        f"❓ /helpauction — rules &amp; help\n\n"
        f"<b>Admin Commands</b>\n"
        f"▶️ /startauction — begin auction\n"
        f"⏭ /next — next actress\n"
        f"📋 /list — remaining actresses\n"
        f"📜 /history — full squad list\n"
        f"♻️ /reset — full reset\n"
        f"❌ /cancel &lt;name&gt; — undo a sale\n"
        f"🔁 /auction &lt;name&gt; — re-queue unsold\n"
        f"🚀 /nextaccelerated &lt;name&gt; — prioritise\n"
        f"🚫 /kickauction @user — remove team\n"
        f"🏁 /endauction — close auction\n"
        f"📋 /unsoldlist — view unsold\n"
        f"⚡ /force &lt;name&gt; — force next actress\n\n"
        f"💰 <i>Reply with a plain number to bid</i>\n"
        f"{divider()}",
        parse_mode="HTML",
    )


# ── /helpauction ─────────────────────────────────────────────────────────────
async def helpauction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"{divider()}\n"
        f"🎯 <b>AUCTION RULES</b>\n"
        f"{divider()}\n\n"
        f"📌 /join — register your team\n\n"
        f"💬 <b>How to bid:</b>\n"
        f"  ✅ Just type: <code>25</code>\n"
        f"  ❌ Not: 25cr / 25.5 / ₹25\n\n"
        f"💰 Starting purse: <b>{STARTING_PURSE} Cr</b>\n"
        f"🎭 Max players/team: <b>{MAX_PLAYERS}</b>\n"
        f"👥 Max teams: <b>10</b>\n"
        f"🔒 Reserve rule: remaining slots × 3 Cr\n\n"
        f"<i>No spam. Play fair. Have fun!</i>\n"
        f"{divider()}",
        parse_mode="HTML",
    )


# ── /join ────────────────────────────────────────────────────────────────────
async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if uid in teams:
        await update.message.reply_text("⚠️ You have already joined.")
        return

    if len(teams) >= 10:
        await update.message.reply_text(
            "⚠️ <b>10 teams already joined.</b>\n\n"
            "Please join the next auction and enjoy spectating 🎭\n"
            "Follow the rules and don't spam.",
            parse_mode="HTML",
        )
        return

    waiting_team_name.add(uid)
    await update.message.reply_text(
        "📝 <b>Send your team name</b>",
        parse_mode="HTML",
    )


# ── Text handler (bids + all confirmation flows) ─────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    uid  = update.effective_user.id
    text = update.message.text.strip()

    # ── Team registration ────────────────────────────────────────────────────
    if uid in waiting_team_name:
        for t in teams.values():
            if t["team_name"].lower() == text.lower():
                await update.message.reply_text("❌ Team name already taken. Try another.")
                return

        teams[uid] = {
            "team_name": text,
            "owner":     update.effective_user.username or update.effective_user.full_name,
            "purse":     STARTING_PURSE,
            "players":   [],
        }
        waiting_team_name.remove(uid)
        await update.message.reply_text(
            f"✅ <b>{text}</b> joined!\n💰 Starting purse: <b>{STARTING_PURSE} Cr</b>",
            parse_mode="HTML",
        )
        return

    # ── Reset confirmation ───────────────────────────────────────────────────
    if uid in pending_reset_confirm:
        pending_reset_confirm.remove(uid)
        if text.lower() in ("yes", "y"):
            teams.clear()
            actress_queue.clear()
            unsold_queue.clear()
            auction["active"] = False
            auction["task"]   = None
            await update.message.reply_text("♻️ Full reset complete. All teams removed.")
        else:
            await update.message.reply_text("Reset cancelled.")
        return

    # ── Kick confirmation ────────────────────────────────────────────────────
    if uid in pending_kick_confirm:
        target = pending_kick_confirm.pop(uid)
        if text.lower() not in ("yes", "y"):
            await update.message.reply_text("Kick cancelled.")
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
                    f"🚫 <b>{target}</b> removed.\n"
                    f"🎭 Their actresses returned to auction.",
                    parse_mode="HTML",
                )
                return

        await update.message.reply_text("❌ User not found.")
        return

    # ── Cancel confirmation flow ─────────────────────────────────────────────
    if uid in pending_cancel_confirm:
        session = pending_cancel_confirm[uid]

        if session["type"] == "select":
            if not text.isdigit():
                await update.message.reply_text("Please reply with a number 🔢")
                return
            idx     = int(text) - 1
            options = session["options"]
            if idx < 0 or idx >= len(options):
                await update.message.reply_text("Invalid choice ❌")
                return
            chosen = options[idx]
            pending_cancel_confirm[uid] = {"type": "confirm", "name": chosen}
            await update.message.reply_text(
                f"♻️ Confirm cancel for <b>{chosen}</b>?\nReply <b>YES</b> / <b>NO</b>",
                parse_mode="HTML",
            )
            return

        if session["type"] == "confirm":
            if text.lower() not in ("yes", "y"):
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
                            f"♻️ <b>{target_name}</b> returned to auction 🎭",
                            parse_mode="HTML",
                        )
                        return

            await update.message.reply_text("❌ Not found in sold list.")
            return

    # ── Bidding ──────────────────────────────────────────────────────────────
    if auction["active"] and uid in teams and text.isdigit():
        bid  = int(text)
        team = teams[uid]

        if len(team["players"]) >= MAX_PLAYERS:
            await update.message.reply_text("🚫 You have reached the max player limit.")
            return

        reserve_needed = min_required_purse(team)
        max_allowed    = team["purse"] - reserve_needed

        if bid <= auction["bid"]:
            await update.message.reply_text(
                f"⬆️ Bid must be <b>more than {auction['bid']} Cr</b>",
                parse_mode="HTML",
            )
            return

        if bid > max_allowed:
            await update.message.reply_text(
                f"⚠️ Your max allowed bid is <b>{max_allowed} Cr</b>",
                parse_mode="HTML",
            )
            return

        auction["bid"]             = bid
        auction["bidder"]          = uid
        auction["end_time"]        = time.time() + BID_TIMEOUT
        auction["final_call_sent"] = False

        await update.message.reply_text(
            f"💎 <b>{team['team_name']}</b> bids <b>{bid} Cr</b> 🔥",
            parse_mode="HTML",
        )

        # ── Milestone Images ──────────────────────────────────────────────────
        current_bid = auction["bid"]

        milestones = [
            (15, "15"),
            (22, "22"),
            (35, "35"),
        ]

        texts = {
            "15": "🔥 Bidding getting serious",
            "22": "⚡ Auction heating up",
            "35": "👑 Elite bidding war",
        }

        for amount_needed, key in milestones:
            if current_bid >= amount_needed and key not in auction["milestones"]:
                auction["milestones"].add(key)
                item   = auction["item"]
                images = item.get("images", [])
                chosen = pick_image(images)
                if chosen:
                    try:
                        await context.bot.send_photo(
                            auction["chat_id"],
                            photo=chosen,
                            caption=(
                                f"{divider()}\n"
                                f"<b>{fancy(item['name'])}</b>\n\n"
                                f"{texts[key]}\n\n"
                                f"💰 Current Bid: <b>{current_bid} Cr</b>\n"
                                f"🏷 Team: <b>{team['team_name']}</b>\n"
                                f"{divider()}"
                            ),
                            parse_mode="HTML",
                        )
                    except Exception:
                        pass


# ── /startauction ────────────────────────────────────────────────────────────
async def startauction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    actress_queue.clear()
    actress_queue.extend(list(ACTRESSES_MASTER))
    random.shuffle(actress_queue)
    unsold_queue.clear()

    await update.message.reply_text(
        f"{divider()}\n"
        f"🚀 <b>AUCTION STARTED</b>\n"
        f"{divider()}\n\n"
        f"🎭 <b>{len(actress_queue)}</b> actresses in the pool\n"
        f"💰 Purse: <b>{STARTING_PURSE} Cr</b> per team\n"
        f"⏳ Bid timer: <b>{BID_TIMEOUT}s</b>\n\n"
        f"<i>First actress coming up…</i>",
        parse_mode="HTML",
    )
    await next_item(update.effective_chat.id, context)


# ── /next ────────────────────────────────────────────────────────────────────
async def next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await next_item(update.effective_chat.id, context)


# ── Core: next_item ──────────────────────────────────────────────────────────
async def next_item(chat_id: int, context):
    global last_pinned_id

    if auction["active"]:
        return

    # Pick next item: live queue → unsold queue → done
    if actress_queue:
        item = actress_queue.pop(0)
    elif unsold_queue:
        actress_queue.extend(unsold_queue)
        unsold_queue.clear()
        random.shuffle(actress_queue)
        item = actress_queue.pop(0)
        await context.bot.send_message(
            chat_id,
            f"{divider()}\n🔁 <b>UNSOLD ROUND BEGINS</b>\n{divider()}",
            parse_mode="HTML",
        )
    else:
        await context.bot.send_message(
            chat_id,
            f"{divider()}\n🏁 <b>AUCTION FULLY COMPLETED!</b>\n{divider()}",
            parse_mode="HTML",
        )
        return

    auction.update({
        "active":          True,
        "item":            item,
        "bid":             int(item.get("base_price", 2)),
        "bidder":          None,
        "chat_id":         chat_id,
        "end_time":        time.time() + BID_TIMEOUT,
        "final_call_sent": False,
        "last_image":      None,
        "milestones":      set(),
    })

    remaining = len(actress_queue) + len(unsold_queue)

    msg = (
        f"{divider()}\n"
        f"🎭 <b>AUCTION LIVE</b>\n"
        f"{divider()}\n\n"
        f"🌟 {fancy(item['name'])}\n\n"
        f"💰 Base Price: <b>{auction['bid']} Cr</b>\n"
        f"⏳ Timer: <b>{BID_TIMEOUT}s</b>\n"
        f"📦 Remaining: <b>{remaining}</b>\n\n"
        f"<i>Send your bid now!</i>"
    )

    images = item.get("images", [])
    chosen = pick_image(images)

    try:
        if chosen:
            msg_obj = await context.bot.send_photo(
                chat_id,
                photo=chosen,
                caption=msg,
                parse_mode="HTML",
            )
        else:
            msg_obj = await context.bot.send_message(
                chat_id,
                msg,
                parse_mode="HTML",
            )
    except Exception:
        msg_obj = await context.bot.send_message(
            chat_id,
            msg,
            parse_mode="HTML",
        )

    # Unpin previous card, pin new one
    if last_pinned_id:
        try:
            await context.bot.unpin_chat_message(chat_id, last_pinned_id)
        except Exception:
            pass

    try:
        await context.bot.pin_chat_message(
            chat_id, msg_obj.message_id, disable_notification=True
        )
        last_pinned_id = msg_obj.message_id
    except Exception:
        pass

    # Cancel stale countdown task
    if auction.get("task") and not auction["task"].done():
        auction["task"].cancel()

    auction["task"] = asyncio.create_task(countdown(context))


# ── Countdown ────────────────────────────────────────────────────────────────
async def countdown(context):
    while True:
        await asyncio.sleep(1)

        if not auction["active"]:
            return

        # Safety: item may have been cleared by finalize/reset/force
        if auction["item"] is None:
            return

        remain = int(auction["end_time"] - time.time())

        # Final call at ≤5 seconds
        if remain <= 5 and not auction["final_call_sent"]:
            auction["final_call_sent"] = True
            if auction["bidder"]:
                t = teams[auction["bidder"]]
                await context.bot.send_message(
                    auction["chat_id"],
                    f"🔔 <b>FINAL CALL!</b>\n\n"
                    f"Any more bids?\n"
                    f"Going to <b>{t['team_name']}</b> for <b>{auction['bid']} Cr</b> 🎯",
                    parse_mode="HTML",
                )
            else:
                await context.bot.send_message(
                    auction["chat_id"],
                    f"⚠️ <b>FINAL CALL!</b>\n\n"
                    f"No bids yet for {fancy(auction['item']['name'])}\n"
                    f"Going <b>UNSOLD</b> unless someone bids! ❌",
                    parse_mode="HTML",
                )

        if remain <= 0:
            break

    await finalize(context)


# ── Finalize ─────────────────────────────────────────────────────────────────
async def finalize(context):
    global last_pinned_id

    if not auction["active"]:
        return

    item    = auction["item"]
    bidder  = auction["bidder"]
    bid     = auction["bid"]
    chat_id = auction["chat_id"]

    auction["active"] = False
    auction["item"]   = None

    if bidder:
        t = teams[bidder]
        t["purse"] -= bid
        t["players"].append({"name": item["name"], "price": bid})

        caption = (
            f"{divider()}\n"
            f"🏆 𝓢𝓞𝓛𝓓!\n"
            f"{divider()}\n\n"
            f"🌟 {fancy(item['name'])}\n\n"
            f"👑 {fancy('Team')}: <b>{t['team_name']}</b>\n"
            f"💰 {fancy('Price')}: <b>{bid} Cr</b>\n"
            f"💼 {fancy('Remaining Purse')}: <b>{t['purse']} Cr</b>\n"
            f"👥 {fancy('Squad')}: <b>{len(t['players'])}/{MAX_PLAYERS}</b>\n"
            f"{divider()}"
        )

        images = item.get("images", [])
        chosen = pick_image(images)

        # Unpin the live auction card
        if last_pinned_id:
            try:
                await context.bot.unpin_chat_message(chat_id, last_pinned_id)
            except Exception:
                pass
            last_pinned_id = None

        try:
            if chosen:
                sold_msg = await context.bot.send_photo(
                    chat_id, photo=chosen, caption=caption, parse_mode="HTML"
                )
            else:
                sold_msg = await context.bot.send_message(
                    chat_id, caption, parse_mode="HTML"
                )
        except Exception:
            sold_msg = await context.bot.send_message(
                chat_id, caption, parse_mode="HTML"
            )

        # Pin the SOLD card
        try:
            await context.bot.pin_chat_message(
                chat_id, sold_msg.message_id, disable_notification=True
            )
            last_pinned_id = sold_msg.message_id
        except Exception:
            pass

    else:
        unsold_queue.append(item)
        await context.bot.send_message(
            chat_id,
            f"❌ <b>UNSOLD</b>: {fancy(item['name'])}\n"
            f"<i>She returns for the unsold round later 🔁</i>",
            parse_mode="HTML",
        )


# ── /list ────────────────────────────────────────────────────────────────────
async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    names  = [a["name"] for a in actress_queue]
    names += [f"{a['name']} (unsold)" for a in unsold_queue]

    if not names:
        await update.message.reply_text("✅ No actresses remaining in queue.")
        return

    await update.message.reply_text(
        f"🎭 <b>REMAINING ({len(names)})</b>\n\n" + "\n".join(names[:100]),
        parse_mode="HTML",
    )


# ── /history ─────────────────────────────────────────────────────────────────
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    msg = f"📜 <b>SQUAD HISTORY</b>\n{divider()}\n\n"
    for t in teams.values():
        msg += (
            f"🏟 <b>{t['team_name']}</b> — @{t['owner']}\n"
            f"💼 Purse: {t['purse']} Cr  |  "
            f"👥 {len(t['players'])}/{MAX_PLAYERS}\n"
        )
        for i in range(MAX_PLAYERS):
            if i < len(t["players"]):
                p = t["players"][i]
                msg += f"  {i+1}. {p['name']} — {p['price']} Cr\n"
            else:
                msg += f"  {i+1}. —\n"
        msg += "\n"

    await update.message.reply_text(msg, parse_mode="HTML")


# ── /reset ───────────────────────────────────────────────────────────────────
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    pending_reset_confirm.add(update.effective_user.id)
    await update.message.reply_text(
        "⚠️ <b>Full reset</b> will remove all teams and clear all data.\n"
        "Reply <b>YES</b> to confirm.",
        parse_mode="HTML",
    )


# ── /cancel ──────────────────────────────────────────────────────────────────
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if auction["active"]:
        await update.message.reply_text("⚠️ Cannot cancel during live bidding.")
        return

    query = " ".join(context.args).strip().lower()
    if not query:
        await update.message.reply_text("❌ Usage: /cancel actress name")
        return

    sold_names = [p["name"] for t in teams.values() for p in t["players"]]
    matches    = [n for n in sold_names if query in n.lower()]

    if not matches:
        await update.message.reply_text("❌ No sold actress matched that name.")
        return

    uid = update.effective_user.id

    if len(matches) == 1:
        pending_cancel_confirm[uid] = {"type": "confirm", "name": matches[0]}
        await update.message.reply_text(
            f"♻️ Did you mean <b>{matches[0]}</b>?\nReply <b>YES</b> / <b>NO</b>",
            parse_mode="HTML",
        )
        return

    pending_cancel_confirm[uid] = {"type": "select", "options": matches}
    msg = "✨ <b>Multiple matches found:</b>\n\n"
    for i, m in enumerate(matches, 1):
        msg += f"{i}. {m}\n"
    msg += "\nReply with the number 🔢"
    await update.message.reply_text(msg, parse_mode="HTML")


# ── /auction (re-queue unsold) ───────────────────────────────────────────────
async def reauction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    name = " ".join(context.args).lower()
    for a in unsold_queue[:]:
        if name in a["name"].lower():
            unsold_queue.remove(a)
            actress_queue.insert(0, a)
            await update.message.reply_text(
                f"🔁 <b>{a['name']}</b> moved back to live queue.",
                parse_mode="HTML",
            )
            return

    await update.message.reply_text("❌ Not found in unsold list.")


# ── /kickauction ─────────────────────────────────────────────────────────────
async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    target = " ".join(context.args).strip()
    if not target:
        await update.message.reply_text("Usage: /kickauction @username")
        return

    pending_kick_confirm[update.effective_user.id] = target
    await update.message.reply_text(
        f"⚠️ Kick <b>{target}</b>? Reply <b>YES</b> to confirm.",
        parse_mode="HTML",
    )


# ── /nextaccelerated ─────────────────────────────────────────────────────────
async def nextaccelerated(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text("Usage: /nextaccelerated actress name")
        return

    query = " ".join(context.args).lower()

    for t in teams.values():
        for p in t["players"]:
            if query in p["name"].lower():
                await update.message.reply_text(
                    f"❌ <b>{p['name']}</b> is already SOLD.",
                    parse_mode="HTML",
                )
                return

    for actress in unsold_queue:
        if query in actress["name"].lower():
            if auction["active"]:
                await update.message.reply_text("⚠️ Finish the current auction first.")
                return
            unsold_queue.remove(actress)
            actress_queue.insert(0, actress)
            await update.message.reply_text(
                f"🚀 <b>{actress['name']}</b> queued as <b>NEXT</b>.",
                parse_mode="HTML",
            )
            return

    await update.message.reply_text("❌ Actress not found in unsold list.")


# ── /endauction ──────────────────────────────────────────────────────────────
async def endauction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    auction["active"] = False

    mentions = [f"@{t['owner']}" for t in teams.values() if t.get("owner")]
    await update.message.reply_text(
        f"{divider()}\n"
        f"🏁 <b>AUCTION CLOSED</b>\n"
        f"{divider()}\n\n"
        + "\n".join(mentions)
        + f"\n\n❤️ Thanks for participating!\n"
        f"🤖 Results will be declared soon.\n"
        f"{divider()}",
        parse_mode="HTML",
    )


# ── /unsoldlist ──────────────────────────────────────────────────────────────
async def unsoldlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not unsold_queue:
        await update.message.reply_text("✅ No unsold actresses right now.")
        return

    msg = f"📋 <b>UNSOLD ACTRESSES ({len(unsold_queue)})</b>\n\n"
    for i, actress in enumerate(unsold_queue, 1):
        msg += f"{i}. {actress['name']}\n"
    await update.message.reply_text(msg, parse_mode="HTML")


# ── /force ───────────────────────────────────────────────────────────────────
async def force_actress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text("Usage: /force actress name")
        return

    name  = " ".join(context.args).lower()
    found = None
    for a in ACTRESSES_MASTER:
        if a["name"].lower() == name:
            found = a
            break

    if not found:
        await update.message.reply_text("❌ Actress not found.")
        return

    # Stop current auction cleanly if running
    if auction["active"]:
        if auction.get("task") and not auction["task"].done():
            auction["task"].cancel()
        auction.update({
            "active": False,
            "item":   None,
            "bidder": None,
        })

    # Remove duplicates from both queues then inject at front
    actress_queue[:] = [a for a in actress_queue if a["name"] != found["name"]]
    unsold_queue[:]  = [a for a in unsold_queue  if a["name"] != found["name"]]
    actress_queue.insert(0, found)

    await update.message.reply_text(
        f"⚡ Forcing auction: <b>{found['name']}</b>",
        parse_mode="HTML",
    )
    await next_item(update.effective_chat.id, context)




# ── Inline button callbacks ──────────────────────────────────────────────────
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "teams":
        if not teams:
            await query.message.reply_text("No teams joined yet.")
            return
        msg = f"👥 <b>TEAMS</b>\n{divider()}\n\n"
        for t in teams.values():
            msg += (
                f"🏟 <b>{t['team_name']}</b> — @{t['owner']}\n"
                f"💼 {t['purse']} Cr  |  {len(t['players'])}/{MAX_PLAYERS} players\n\n"
            )
        await query.message.reply_text(msg, parse_mode="HTML")

    elif query.data == "history":
        if not teams:
            await query.message.reply_text("No history yet.")
            return
        msg = f"📜 <b>SQUADS</b>\n{divider()}\n\n"
        for t in teams.values():
            msg += f"🏟 <b>{t['team_name']}</b>\n"
            for i, p in enumerate(t["players"], 1):
                msg += f"  {i}. {p['name']} — {p['price']} Cr\n"
            msg += "\n"
        await query.message.reply_text(msg, parse_mode="HTML")


# ── main ─────────────────────────────────────────────────────────────────────
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

    app.add_handler(CommandHandler("start",           start))
    app.add_handler(CommandHandler("join",            join))
    app.add_handler(CommandHandler("startauction",    startauction))
    app.add_handler(CommandHandler("next",            next))
    app.add_handler(CommandHandler("list",            list_cmd))
    app.add_handler(CommandHandler("history",         history))
    app.add_handler(CommandHandler("reset",           reset))
    app.add_handler(CommandHandler("cancel",          cancel))
    app.add_handler(CommandHandler("auction",         reauction))
    app.add_handler(CommandHandler("kickauction",     kick))
    app.add_handler(CommandHandler("helpauction",     helpauction))
    app.add_handler(CommandHandler("nextaccelerated", nextaccelerated))
    app.add_handler(CommandHandler("endauction",      endauction))
    app.add_handler(CommandHandler("unsoldlist",      unsoldlist))
    app.add_handler(CommandHandler("force",           force_actress))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("🔥 Actress Fanzy League — Auction Bot running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
