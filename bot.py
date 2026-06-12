# xc.py
import random
import hashlib
import sqlite3
import requests
import re
import os
import asyncio
from io import BytesIO
from datetime import datetime
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
import threading

# ================= FLASK APP =================
app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"status": "running", "message": "Insta Analyzer Bot is active!"})

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8740135346"))
API_URL = "https://snipy-insta-info.snipy-owner.workers.dev/info?username="
BANNER_URL = "https://i.ibb.co/N6VzyBLf/N3RDq5RE.jpg"
FORCE_CHANNELS = os.getenv("FORCE_CHANNELS", "@midnight_xaura,@proxydominates,@noruleclub").split(",")

# ================= DATABASE =================
DB_NAME = "insta_analyzer_fixed.db"
db = sqlite3.connect(DB_NAME, check_same_thread=False, timeout=30)
db.execute("PRAGMA journal_mode=WAL")
db.execute("PRAGMA busy_timeout=30000")
cur = db.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT,
    join_date TEXT,
    referral_count INTEGER DEFAULT 0,
    referred_by INTEGER DEFAULT NULL
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS methods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    content TEXT,
    media_url TEXT,
    media_type TEXT,
    uploaded_at TEXT
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS vpns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    file_id TEXT,
    uploaded_at TEXT
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS premium_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    app_name TEXT,
    status TEXT,
    requested_at TEXT
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS explore_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    link TEXT
)
""")
db.commit()

def save_user(uid, username=None):
    try:
        cur.execute("INSERT OR IGNORE INTO users (id, username, join_date) VALUES (?, ?, ?)",
                    (uid, username, datetime.now().isoformat()))
        db.commit()
    except Exception as e:
        print(f"Error saving user: {e}")

def get_referral_count(user_id):
    cur.execute("SELECT referral_count FROM users WHERE id = ?", (user_id,))
    result = cur.fetchone()
    return result[0] if result else 0

def update_referral_count(user_id):
    cur.execute("UPDATE users SET referral_count = referral_count + 1 WHERE id = ?", (user_id,))
    db.commit()

# ================= FORCE JOIN =================
async def is_joined(bot, user_id):
    if user_id == ADMIN_ID:
        return True
    async def check_one(ch):
        try:
            member = await bot.get_chat_member(ch, user_id)
            return member.status not in ["left", "kicked"]
        except Exception as e:
            print(f"Force join check failed for {ch}: {e}")
            return False
    results = await asyncio.gather(*(check_one(ch) for ch in FORCE_CHANNELS))
    return all(results)

def join_kb():
    btns = [[InlineKeyboardButton(f"⚠️ Join {c}", url=f"https://t.me/{c[1:]}")] for c in FORCE_CHANNELS]
    btns.append([InlineKeyboardButton("✅ Check Again", callback_data="check")])
    return InlineKeyboardMarkup(btns)

def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 DEEP ANALYSIS", callback_data="deep"), InlineKeyboardButton("📝 CB METHOD", callback_data="cb_method")],
        [InlineKeyboardButton("📋 FORMS WITH TEXT", callback_data="forms"), InlineKeyboardButton("🆕 LATEST METH", callback_data="latest_meth")],
        [InlineKeyboardButton("🔒 VPNS", callback_data="vpns"), InlineKeyboardButton("🎁 GET UNC", callback_data="get_unc")],
        [InlineKeyboardButton("📱 PREMIUM APP REQUEST", callback_data="premium_app"), InlineKeyboardButton("🔗 EXPLORE MORE", callback_data="explore_more")]
    ])

# ================= ANALYSIS ENGINE =================
def calc_risk(profile):
    username = profile.get("username", "user")
    bio = (profile.get("biography") or "").lower()
    private = profile.get("is_private", False)
    posts = int(profile.get("posts") or 0)
    seed = int(hashlib.sha256(username.encode()).hexdigest(), 16)
    rnd = random.Random(seed)
    pool = [
        "SCAM", "SPAM", "NUDITY",
        "HATE", "HARASSMENT",
        "BULLYING", "VIOLENCE",
        "TERRORISM"
    ]
    if any(x in bio for x in ["music", "rapper", "artist", "singer"]):
        pool += ["DRUGS", "DRUGS"]
    if private and posts == 0:
        pool += ["SCAM", "SCAM", "SCAM"]
    include_self = private and rnd.choice([True, False])
    if include_self:
        pool.append("SELF")
        pool = [i for i in pool if i != "HATE"]
    if rnd.random() < 0.15:
        pool.append("WEAPONS")
    rnd.shuffle(pool)
    selected = list(dict.fromkeys(pool))[:rnd.randint(1, 3)]
    issues, intensity = [], 0
    for i in selected:
        count = rnd.randint(3, 4) if i == "WEAPONS" else rnd.randint(1, 4)
        intensity += count
        issues.append(f"{count}x {i}")
    risk = min(95, 40 + intensity * 6 + (10 if private else 0) + (10 if posts == 0 else 0))
    return risk, issues

# ================= DEEP ANALYSIS FETCH =================
def fetch_profile_sync(username):
    try:
        r = requests.get(API_URL + username, timeout=20)
        if r.status_code != 200:
            return None
        data = r.json()
        if data.get("error"):
            return None
        return {
            "username": data.get("username", "user"),
            "biography": data.get("bio", ""),
            "is_private": data.get("private", False),
            "posts": data.get("posts", 0),
            "name": data.get("name", "N/A"),
            "verified": data.get("verified", False),
            "followers": data.get("followers", 0),
            "following": data.get("following", 0),
            "pic": data.get("pic", ""),
            "recent": data.get("recent", [])
        }
    except Exception as e:
        print(f"Fetch profile error: {e}")
        return None

async def fetch_profile(username):
    return await asyncio.to_thread(fetch_profile_sync, username)

def download_img(url):
    try:
        r = requests.get(url, timeout=15)
        bio = BytesIO(r.content)
        bio.name = "pfp.jpg"
        return bio
    except:
        return None

def report_text(username, profile, risk, issues):
    t = f"⚠️ <b>DEEP ANALYSIS REPORT</b>\nProfile: <code>@{username}</code>\n\n"
    t += f"📛 <b>Name:</b> {profile.get('name','')}\n"
    t += f"👥 <b>Followers:</b> {profile.get('followers',0)}\n"
    t += f"📸 <b>Posts:</b> {profile.get('posts',0)}\n"
    t += f"🔒 <b>Private:</b> {'Yes' if profile.get('is_private') else 'No'}\n"
    t += f"✅ <b>Verified:</b> {'Yes' if profile.get('verified') else 'No'}\n\n"
    t += "⚠️ <b>DETECTED ISSUES</b>\n"
    for i in issues:
        t += f"• {i}\n"
    t += f"\n📊 <b>OVERALL RISK:</b> {risk}%"
    return t

def after_kb(username):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Full Report", callback_data=f"report|{username}")],
        [InlineKeyboardButton("🔄 Analyze Again", callback_data="deep")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu")]
    ])

# ================= CB METHOD =================
def analyze_content(text):
    text_lower = text.lower()
    hate_words = ["hate", "bhenchod", "madarchod", "bc", "mc", "chutiya", "bhosdike", "bsdk", "gandu", "lauda", "lund"]
    violence_words = ["kill", "murder", "marunga", "maar", "attack", "bomb", "gun", "weapon", "knife", "blood"]
    self_harm_words = ["suicide", "kill myself", "die", "end life", "depression", "selfharm"]
    scam_words = ["scam", "fraud", "fake", "cheat", "money", "paytm", "upi"]
    nudity_words = ["nude", "sex", "porn", "xxx", "hot", "18+", "adult", "naked"]
    hate_count = sum(1 for word in hate_words if word in text_lower)
    violence_count = sum(1 for word in violence_words if word in text_lower)
    self_count = sum(1 for word in self_harm_words if word in text_lower)
    scam_count = sum(1 for word in scam_words if word in text_lower)
    nudity_count = sum(1 for word in nudity_words if word in text_lower)
    if self_count > 0:
        self_count = random.randint(1, 2)
    issues = []
    if hate_count > 0:
        issues.append(f"{min(hate_count * 2, 5)}x HATE")
    if violence_count > 0:
        issues.append(f"{min(violence_count * 2, 4)}x VIOLENCE")
    if self_count > 0:
        issues.append(f"{self_count}x SELF")
    if scam_count > 0:
        issues.append(f"{min(scam_count, 3)}x SCAM")
    if nudity_count > 0:
        issues.append(f"{min(nudity_count, 3)}x NUDITY")
    if not issues:
        issues = ["1x SPAM", "1x FAKE"]
    risk = min(95, 30 + hate_count * 8 + violence_count * 10 + self_count * 15 + scam_count * 5)
    return risk, issues

# ================= FORMS =================
def forms_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔒 Hacked Account", callback_data="form_hacked"), InlineKeyboardButton("🎭 Fake Account", callback_data="form_fake")],
        [InlineKeyboardButton("©️ Copyright", callback_data="form_copyright"), InlineKeyboardButton("⚠️ Harassment", callback_data="form_harassment")],
        [InlineKeyboardButton("🔞 Nudity/Sexual", callback_data="form_nudity"), InlineKeyboardButton("👶 Underage User", callback_data="form_underage")],
        [InlineKeyboardButton("📊 Spam Account", callback_data="form_spam"), InlineKeyboardButton("🚫 Shadowban", callback_data="form_shadowban")],
        [InlineKeyboardButton("💼 Business Issue", callback_data="form_business"), InlineKeyboardButton("🔒 Privacy Violation", callback_data="form_privacy")],
        [InlineKeyboardButton("💀 Terrorism", callback_data="form_terrorism"), InlineKeyboardButton("💔 Self-Harm", callback_data="form_selfharm")],
        [InlineKeyboardButton("®️ Trademark", callback_data="form_trademark"), InlineKeyboardButton("🗑️ Delete My Data", callback_data="form_gdpr")],
        [InlineKeyboardButton("❌ CANCEL", callback_data="menu")]
    ])

form_data = {
    "hacked": {"link": "https://instagram.com/hacked", "text": "📝 WHAT TO WRITE:\n• Your Instagram username\n• Email/Phone linked to account\n• When did you lose access?\n• New email for recovery"},
    "fake": {"link": "https://help.instagram.com/contact/1652567838289083", "text": "📝 WHAT TO WRITE:\n• Your original username\n• Fake account username\n• Attach screenshot"},
    "copyright": {"link": "https://help.instagram.com/contact/289384114573421", "text": "📝 WHAT TO WRITE:\n• Your copyrighted work link\n• Infringing content link\n• 'I declare under penalty of perjury'"},
    "harassment": {"link": "https://help.instagram.com/contact/180279000514263", "text": "📝 WHAT TO WRITE:\n• Attach screenshots\n• Usernames of harassers\n• Date/time of incident"},
    "nudity": {"link": "https://help.instagram.com/contact/180279000514263", "text": "📝 WHAT TO WRITE:\n• Content link\n• Screenshot\n• 'This violates Community Guidelines'"},
    "underage": {"link": "https://help.instagram.com/contact/1652486631959717", "text": "📝 WHAT TO WRITE:\n• Username of minor\n• 'This user is below 13 years old'"},
    "spam": {"link": "https://help.instagram.com/contact/186215381720304", "text": "📝 WHAT TO WRITE:\n• Spam username\n• Screenshot of spam"},
    "shadowban": {"link": "https://instagram.com/accounts/contact/111111111111111", "text": "📝 WHAT TO WRITE:\n• Your username\n• When shadowban started\n• Request manual review"},
    "business": {"link": "https://help.instagram.com/contact/165252632431920", "text": "📝 WHAT TO WRITE:\n• Business username\n• Issue description"},
    "privacy": {"link": "https://help.instagram.com/contact/186113021420369", "text": "📝 WHAT TO WRITE:\n• Content link\n• 'My personal information is exposed'"},
    "terrorism": {"link": "https://help.instagram.com/contact/180246434974734", "text": "📝 WHAT TO WRITE:\n• Content link\n• 'URGENT - Violent content'"},
    "selfharm": {"link": "https://help.instagram.com/contact/155565807260214", "text": "📝 WHAT TO WRITE:\n• Username\n• Content link\n• 'URGENT - Person in danger'"},
    "trademark": {"link": "https://help.instagram.com/contact/349410550021406", "text": "📝 WHAT TO WRITE:\n• Your trademark number\n• Infringing account"},
    "gdpr": {"link": "https://help.instagram.com/contact/186114793129616", "text": "📝 WHAT TO WRITE:\n• 'I request deletion of my data under GDPR'\n• Your username"}
}

def vpns_kb():
    cur.execute("SELECT id, name FROM vpns ORDER BY id DESC LIMIT 8")
    vpns = cur.fetchall()
    keyboard = []
    row = []
    for i, (vid, name) in enumerate(vpns):
        row.append(InlineKeyboardButton(name[:15], callback_data=f"vpn|{vid}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("❌ CANCEL", callback_data="menu")])
    return InlineKeyboardMarkup(keyboard)

def latest_meth_kb():
    cur.execute("SELECT id, title FROM methods ORDER BY id DESC LIMIT 10")
    methods = cur.fetchall()
    keyboard = []
    for mid, title in methods:
        keyboard.append([InlineKeyboardButton(f"📌 {title[:30]}", callback_data=f"meth|{mid}")])
    keyboard.append([InlineKeyboardButton("❌ CANCEL", callback_data="menu")])
    return InlineKeyboardMarkup(keyboard)

def unc_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 My Referrals", callback_data="my_referrals")],
        [InlineKeyboardButton("🔗 Referral Link", callback_data="referral_link")],
        [InlineKeyboardButton("🎁 UNC Rewards", callback_data="unc_rewards")],
        [InlineKeyboardButton("❌ CANCEL", callback_data="menu")]
    ])

def premium_request_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Request App", callback_data="request_app")],
        [InlineKeyboardButton("📋 My Requests", callback_data="my_requests")],
        [InlineKeyboardButton("❌ CANCEL", callback_data="menu")]
    ])

def explore_kb():
    cur.execute("SELECT id, title, link FROM explore_links")
    links = cur.fetchall()
    keyboard = []
    row = []
    for i, (lid, title, link) in enumerate(links):
        row.append(InlineKeyboardButton(f"🔗 {title}", url=link))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("❌ CANCEL", callback_data="menu")])
    return InlineKeyboardMarkup(keyboard)

# ================= Helper =================
async def edit_menu_message(q, text, reply_markup, parse_mode=None):
    try:
        if q.message.photo:
            await q.message.edit_caption(caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            await q.message.edit_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        await q.message.reply_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username
    save_user(uid, username)
    if context.args and context.args[0].startswith("ref_"):
        try:
            referrer_id = int(context.args[0].replace("ref_", ""))
            if referrer_id != uid:
                cur.execute("SELECT referred_by FROM users WHERE id = ?", (uid,))
                result = cur.fetchone()
                if result and result[0] is None:
                    cur.execute("UPDATE users SET referred_by = ? WHERE id = ?", (referrer_id, uid))
                    update_referral_count(referrer_id)
                    db.commit()
        except:
            pass
    if not await is_joined(context.bot, uid):
        await update.message.reply_photo(photo=BANNER_URL, caption="⚠️ Please join all channels first!", reply_markup=join_kb())
        return
    await update.message.reply_photo(photo=BANNER_URL, caption="✨ WELCOME TO INSTA ANALYZER PRO ✨ \n\n👑 DEV: @REVULET", reply_markup=main_menu_kb())

# ================= CALLBACK HANDLER =================
async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id
    if q.data != "check" and not await is_joined(context.bot, user_id):
        await q.message.reply_text("⚠️ Please join all channels first!", reply_markup=join_kb())
        return
    if q.data == "check":
        if await is_joined(context.bot, user_id):
            await edit_menu_message(q, "✨ WELCOME TO INSTA ANALYZER PRO ✨ \n\n👑 DEV: @REVULET", main_menu_kb())
        else:
            await q.message.reply_text("⚠️ Join all channels!", reply_markup=join_kb())
    elif q.data == "menu":
        await edit_menu_message(q, "✨ WELCOME TO INSTA ANALYZER PRO ✨ \n\n👑 DEV: @REVULET", main_menu_kb())
    elif q.data == "deep":
        context.user_data["waiting_for_username"] = True
        await q.message.reply_text("📛 Send Instagram username, link or @username:")
    elif q.data == "cb_method":
        context.user_data["cb_method"] = True
        await q.message.reply_text("📝 Send text or photo for analysis:")
    elif q.data == "forms":
        await edit_menu_message(q, "📋 SELECT A PROBLEM TO REPORT:", forms_kb())
    elif q.data.startswith("form_"):
        form_type = q.data.replace("form_", "")
        info = form_data.get(form_type, form_data["hacked"])
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="forms")], [InlineKeyboardButton("🏠 MENU", callback_data="menu")]])
        await edit_menu_message(q, f"🔗 {info['link']}\n\n─────────────────────\n\n{info['text']}\n\n─────────────────────\n👑 DEV: @REVULET", kb)
    elif q.data == "latest_meth":
        kb = latest_meth_kb()
        await edit_menu_message(q, "🆕 LATEST METHODS & TUTORIALS:", kb)
    elif q.data.startswith("meth|"):
        mid = int(q.data.split("|")[1])
        cur.execute("SELECT title, content, media_url, media_type FROM methods WHERE id = ?", (mid,))
        meth = cur.fetchone()
        if meth:
            title, content, media_url, media_type = meth
            text = f"📌 {title}\n\n{content}\n\n─────────────────────\n👑 DEV: @REVULET"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="latest_meth")], [InlineKeyboardButton("🏠 MENU", callback_data="menu")]])
            if media_url and media_type == "photo":
                await q.message.reply_photo(photo=media_url, caption=text, reply_markup=kb)
            elif media_url and media_type == "document":
                await q.message.reply_document(document=media_url, caption=text, reply_markup=kb)
            else:
                await edit_menu_message(q, text, kb)
    elif q.data == "vpns":
        kb = vpns_kb()
        await edit_menu_message(q, "🔒 SELECT VPN:", kb)
    elif q.data.startswith("vpn|"):
        vid = int(q.data.split("|")[1])
        cur.execute("SELECT name, file_id FROM vpns WHERE id = ?", (vid,))
        vpn = cur.fetchone()
        if vpn:
            name, file_id = vpn
            await q.message.reply_document(document=file_id, caption=f"🔒 {name}\n\n─────────────────────\n👑 DEV: @REVULET", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="vpns")]]))
    elif q.data == "get_unc":
        ref_count = get_referral_count(user_id)
        await edit_menu_message(q, f"🎁 GET UNC SYSTEM\n\n👥 Your Referrals: {ref_count}\n\n🏆 REWARDS:\n• 2x Refer → 1x Post UNC\n• 5x Refer → 3x Post UNC\n• 10x Refer → 6x Post UNC", unc_kb())
    elif q.data == "my_referrals":
        ref_count = get_referral_count(user_id)
        await edit_menu_message(q, f"👥 YOUR REFERRALS: {ref_count}", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="get_unc")]]))
    elif q.data == "referral_link":
        bot_info = await context.bot.get_me()
        bot_username = bot_info.username
        link = f"https://t.me/{bot_username}?start=ref_{user_id}"
        await edit_menu_message(q, f"🔗 YOUR REFERRAL LINK:\n{link}", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="get_unc")]]))
    elif q.data == "unc_rewards":
        ref_count = get_referral_count(user_id)
        if ref_count >= 10:
            reward = "6x Post UNC"
        elif ref_count >= 5:
            reward = "3x Post UNC"
        elif ref_count >= 2:
            reward = "1x Post UNC"
        else:
            reward = f"Need {2 - ref_count} more referrals"
        await edit_menu_message(q, f"🏆 UNC REWARDS\n\nYour referrals: {ref_count}\nEligible reward: {reward}\n\nTo claim, DM admin with proof!", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="get_unc")]]))
    elif q.data == "premium_app":
        await edit_menu_message(q, "📱 PREMIUM APP REQUEST\n\nRequest any paid/mod app!", premium_request_kb())
    elif q.data == "request_app":
        context.user_data["waiting_for_app"] = True
        await q.message.reply_text("📱 Send the app name you want:")
    elif q.data == "my_requests":
        cur.execute("SELECT id, app_name, status FROM premium_requests WHERE user_id = ? ORDER BY id DESC", (user_id,))
        reqs = cur.fetchall()
        if reqs:
            text = "📋 YOUR REQUESTS:\n\n"
            for rid, app_name, status in reqs:
                text += f"• {app_name} - {status}\n"
            await edit_menu_message(q, text, InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="premium_app")]]))
        else:
            await q.message.reply_text("No requests yet!", reply_markup=main_menu_kb())
    elif q.data == "explore_more":
        kb = explore_kb()
        await edit_menu_message(q, "🔗 EXPLORE MORE\n\nOur other bots & channels:", kb)
    elif q.data.startswith("report|"):
        username = q.data.split("|")[1]
        profile = await fetch_profile(username)
        if not profile:
            await q.message.reply_text("❌ Profile not found!")
            return
        risk, issues = calc_risk(profile)
        await q.message.reply_text(report_text(username, profile, risk, issues), reply_markup=after_kb(username), parse_mode="HTML")

# ================= TEXT HANDLER =================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if not await is_joined(context.bot, user_id):
        await update.message.reply_text("⚠️ Please join all channels first!", reply_markup=join_kb())
        return
    if context.user_data.get("waiting_for_username"):
        context.user_data["waiting_for_username"] = False
        username = text
        if "instagram.com" in text:
            clean = text.split("?")[0]
            username = clean.rstrip("/").split("/")[-1]
        username = username.replace("@", "").strip().lower()
        if not username or " " in username:
            await update.message.reply_text("❌ Invalid Username pattern.", reply_markup=main_menu_kb())
            return
        await update.message.reply_text("🔍 Analyzing Profile...")
        profile = await fetch_profile(username)
        if not profile:
            await update.message.reply_text("❌ Instagram user not found.", reply_markup=main_menu_kb())
            return
        risk, issues = calc_risk(profile)
        if profile.get("is_private"):
            caption = (
                "🔒 <b>Private Instagram Account Detected</b>\n\n"
                f"📛 <b>Name:</b> {profile.get('name')}\n"
                f"🆔 <b>Username:</b> <code>@{profile.get('username')}</code>\n"
                f"✅ <b>Verified:</b> {'✅ Yes' if profile.get('verified') else '❌ No'}\n\n"
                f"📊 <b>OVERALL RISK:</b> {risk}%\n"
                "─────────────────────\n"
                "👑 DEV: @REVULET"
            )
            if profile.get("pic"):
                try:
                    await update.message.reply_photo(photo=profile["pic"], caption=caption, reply_markup=after_kb(username), parse_mode="HTML")
                    return
                except:
                    pass
            await update.message.reply_text(caption, reply_markup=after_kb(username), parse_mode="HTML")
            return
        caption = report_text(username, profile, risk, issues)
        if profile.get("pic"):
            try:
                await update.message.reply_photo(photo=profile["pic"], caption=caption, reply_markup=after_kb(username), parse_mode="HTML")
                return
            except:
                pass
        await update.message.reply_text(caption, reply_markup=after_kb(username), parse_mode="HTML")
        return
    if context.user_data.get("cb_method"):
        context.user_data["cb_method"] = False
        risk, issues = analyze_content(text)
        issues_text = "\n".join([f"• {i}" for i in issues])
        await update.message.reply_text(f"📝 CB METHOD ANALYSIS\n\n⚠️ DETECTED ISSUES:\n{issues_text}\n\n📊 OVERALL RISK: {risk}%\n\n─────────────────────\n👑 DEV: @REVULET", reply_markup=main_menu_kb())
        return
    if context.user_data.get("waiting_for_app"):
        context.user_data["waiting_for_app"] = False
        cur.execute("INSERT INTO premium_requests (user_id, app_name, status, requested_at) VALUES (?, ?, ?, ?)", (user_id, text, "pending", datetime.now().isoformat()))
        db.commit()
        await context.bot.send_message(ADMIN_ID, f"📱 NEW APP REQUEST!\n\nUser: @{update.effective_user.username or user_id}\nUser ID: {user_id}\nApp: {text}")
        await update.message.reply_text("✅ Request sent to admin! You'll get the app soon.", reply_markup=main_menu_kb())

# ================= PHOTO HANDLER =================
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_joined(context.bot, user_id):
        await update.message.reply_text("⚠️ Please join all channels first!", reply_markup=join_kb())
        return
    if context.user_data.get("cb_method"):
        context.user_data["cb_method"] = False
        caption = update.message.caption or ""
        risk, issues = analyze_content(caption)
        issues_text = "\n".join([f"• {i}" for i in issues])
        await update.message.reply_text(f"📝 CB METHOD ANALYSIS (Photo)\n\n⚠️ DETECTED ISSUES:\n{issues_text}\n\n📊 OVERALL RISK: {risk}%\n\n─────────────────────\n👑 DEV: @REVULET", reply_markup=main_menu_kb())

# ================= ADMIN COMMANDS =================
async def add_vpn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Admin only!")
        return
    if not context.args:
        await update.message.reply_text("Usage: /addvpn Name (reply to APK file)")
        return
    name = " ".join(context.args)
    if update.message.reply_to_message and update.message.reply_to_message.document:
        file_id = update.message.reply_to_message.document.file_id
        cur.execute("INSERT INTO vpns (name, file_id, uploaded_at) VALUES (?, ?, ?)", (name, file_id, datetime.now().isoformat()))
        db.commit()
        await update.message.reply_text(f"✅ VPN '{name}' added!")
    else:
        await update.message.reply_text("❌ Reply to an APK file!")

async def add_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Admin only!")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /addmethod Title | Content")
        return
    parts = " ".join(context.args).split("|")
    title = parts[0].strip()
    content = parts[1].strip() if len(parts) > 1 else ""
    media_url = None
    media_type = None
    if update.message.reply_to_message:
        if update.message.reply_to_message.photo:
            media_url = update.message.reply_to_message.photo[-1].file_id
            media_type = "photo"
        elif update.message.reply_to_message.document:
            media_url = update.message.reply_to_message.document.file_id
            media_type = "document"
    cur.execute("INSERT INTO methods (title, content, media_url, media_type, uploaded_at) VALUES (?, ?, ?, ?, ?)", (title, content, media_url, media_type, datetime.now().isoformat()))
    db.commit()
    await update.message.reply_text(f"✅ Method '{title}' added!")

async def add_explore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Admin only!")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /addexplore Title | Link")
        return
    parts = " ".join(context.args).split("|")
    title = parts[0].strip()
    link = parts[1].strip() if len(parts) > 1 else ""
    cur.execute("INSERT INTO explore_links (title, link) VALUES (?, ?)", (title, link))
    db.commit()
    await update.message.reply_text(f"✅ Explore link '{title}' added!")

async def send_app(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Admin only!")
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /sendapp user_id (reply to APK)")
        return
    target_id = int(context.args[0])
    if update.message.reply_to_message and update.message.reply_to_message.document:
        file_id = update.message.reply_to_message.document.file_id
        cur.execute("UPDATE premium_requests SET status = 'completed' WHERE user_id = ? AND status = 'pending'", (target_id,))
        db.commit()
        await context.bot.send_document(chat_id=target_id, document=file_id, caption="📱 Here's your requested app!\n\n👑 DEV: @REVULET")
        await update.message.reply_text(f"✅ App sent to user {target_id}!")
    else:
        await update.message.reply_text("❌ Reply to an APK file!")

async def users_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Admin only!")
        return
    cur.execute("SELECT COUNT(*) FROM users")
    count = cur.fetchone()[0]
    await update.message.reply_text(f"👥 Total Users: {count}")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Admin only!")
        return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast message")
        return
    msg = " ".join(context.args)
    cur.execute("SELECT id FROM users")
    sent = 0
    for (uid,) in cur.fetchall():
        try:
            await context.bot.send_message(uid, msg)
            sent += 1
        except:
            pass
    await update.message.reply_text(f"✅ Sent to {sent} users")

# ================= RUN BOT =================
def run_bot():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable not set!")
    
    telegram_app = Application.builder().token(BOT_TOKEN).build()
    
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("addvpn", add_vpn))
    telegram_app.add_handler(CommandHandler("addmethod", add_method))
    telegram_app.add_handler(CommandHandler("addexplore", add_explore))
    telegram_app.add_handler(CommandHandler("sendapp", send_app))
    telegram_app.add_handler(CommandHandler("users", users_count))
    telegram_app.add_handler(CommandHandler("broadcast", broadcast))
    telegram_app.add_handler(CallbackQueryHandler(callbacks))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    telegram_app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    print("=" * 50)
    print("✅ BOT IS RUNNING!")
    print(f"👑 Admin ID: {ADMIN_ID}")
    print(f"⚠️ Force Channels: {FORCE_CHANNELS}")
    print("=" * 50)
    
    telegram_app.run_polling()

# ================= MAIN =================
if __name__ == "__main__":
    # Run Flask in a separate thread
    def run_flask():
        port = int(os.getenv("PORT", 8080))
        app.run(host="0.0.0.0", port=port)
    
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    
    # Run the bot
    run_bot()
