#!/usr/bin/env python3
"""H4XY XP TEAM Premium Hosting Bot — single-file Termux/Linux edition.

Install: pip install -U aiogram firebase-admin
Required environment: BOT_TOKEN, ADMIN_ID, and either
FIREBASE_SERVICE_ACCOUNT_JSON or GOOGLE_APPLICATION_CREDENTIALS.
Optional payment settings: UPI_ID, UPI_NAME, FAMGATEWAY_API_KEY.
FamGateway is an independent third-party integration, not an official FamPay API.
"""
import asyncio
import html
import json
import logging
import os
from dotenv import load_dotenv
import time
import uuid
import urllib.request
import urllib.error
from datetime import datetime, timezone

# Load local .env when present; hosted environments can inject variables directly.
load_dotenv()

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

import firebase_admin
from firebase_admin import credentials, firestore

# ===================== EDIT THESE SETTINGS =====================
# Put your own Telegram bot token and numeric Telegram user ID here.
# Never share a real bot token or Firebase service-account key.
BOT_TOKEN = "8759479683:AAEa343w43qD46uGCRIh5uxqht2Kng0isAM"
ADMIN_ID = 7784683312  # Replace with your numeric Telegram user ID
APP_NAME = "H4XY XP TEAM HOSTING BOT"
# Optional inline Firebase service-account dictionary. Paste the JSON contents here
# if you do not want to use GOOGLE_APPLICATION_CREDENTIALS / FIREBASE_SERVICE_ACCOUNT_JSON.
SERVICE_ACCOUNT_INFO = {}
# ===============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", BOT_TOKEN).strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", str(ADMIN_ID)) or "0")
ADMIN_CONTACT = os.getenv("ADMIN_CONTACT", "@H4XY_XP_TEAM_OWNER").strip()
UPI_ID = os.getenv("UPI_ID", "").strip()
UPI_NAME = os.getenv("UPI_NAME", "H4XY XP TEAM").strip()
PAYMENT_INSTRUCTIONS = os.getenv(
    "PAYMENT_INSTRUCTIONS",
    "UPI payment karne ke baad screenshot bhejein. Admin payment verify karega."
).strip()
CURRENCY = os.getenv("CURRENCY", "INR").upper()
# Optional independent third-party FamGateway checkout (not an official FamPay API).
FAMGATEWAY_API_KEY = os.getenv("FAMGATEWAY_API_KEY", "").strip()
FAMGATEWAY_API_URL = os.getenv("FAMGATEWAY_API_URL", "https://famgateway.in/api/create-order").strip()
FAMGATEWAY_REDIRECT_URL = os.getenv("FAMGATEWAY_REDIRECT_URL", "https://t.me").strip()
FAMGATEWAY_WEBHOOK_URL = os.getenv("FAMGATEWAY_WEBHOOK_URL", "").strip()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("h4xy-hosting")

if not BOT_TOKEN or BOT_TOKEN.startswith("PASTE_YOUR_"):
    raise SystemExit("Edit BOT_TOKEN near the top of this file before running the bot.")
if not ADMIN_ID or ADMIN_ID == 123456789:
    raise SystemExit("ADMIN_ID environment variable missing.")

def init_firebase():
    """Supports Railway secret env var or local service-account JSON file."""
    if firebase_admin._apps:
        app = firebase_admin.get_app()
    else:
        raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
        file_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
        if SERVICE_ACCOUNT_INFO and isinstance(SERVICE_ACCOUNT_INFO, dict) and SERVICE_ACCOUNT_INFO.get("private_key"):
            cred = credentials.Certificate(SERVICE_ACCOUNT_INFO)
        elif raw:
            try:
                service_account = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise SystemExit("FIREBASE_SERVICE_ACCOUNT_JSON must contain valid JSON.") from exc
            cred = credentials.Certificate(service_account)
        elif file_path:
            cred = credentials.Certificate(file_path)
        else:
            raise SystemExit(
                "Firebase credentials missing. Fill SERVICE_ACCOUNT_INFO in this file, "
                "or set GOOGLE_APPLICATION_CREDENTIALS / FIREBASE_SERVICE_ACCOUNT_JSON."
            )
        app = firebase_admin.initialize_app(cred)
    return firestore.client(app=app)

db = init_firebase()
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

def now_ts():
    return int(time.time())

def esc(value):
    return html.escape(str(value or ""), quote=False)

def money(value):
    return f"₹{float(value):,.2f}" if CURRENCY == "INR" else f"{float(value):,.2f} {CURRENCY}"

def fmt_time(ts):
    if not ts:
        return "N/A"
    return datetime.fromtimestamp(int(ts), timezone.utc).astimezone().strftime("%d %b %Y, %I:%M %p")

def doc(collection, doc_id):
    snap = db.collection(collection).document(str(doc_id)).get()
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    data["_id"] = snap.id
    return data

def all_docs(collection):
    result = []
    for snap in db.collection(collection).stream():
        data = snap.to_dict() or {}
        data["_id"] = snap.id
        result.append(data)
    return result

def save(collection, doc_id, data, merge=True):
    db.collection(collection).document(str(doc_id)).set(data, merge=merge)


def payment_config():
    """Read payment switches and credentials configured by the admin in Telegram."""
    cfg = doc("settings", "payment_config") or {}
    return {
        "upi_enabled": cfg.get("upi_enabled", bool(UPI_ID)),
        "upi_id": cfg.get("upi_id", UPI_ID),
        "upi_name": cfg.get("upi_name", UPI_NAME),
        "qr_file_id": cfg.get("qr_file_id", ""),
        "fam_enabled": cfg.get("fam_enabled", bool(cfg.get("fam_key") or FAMGATEWAY_API_KEY)),
        "fam_key": cfg.get("fam_key", FAMGATEWAY_API_KEY),
        "fam_url": cfg.get("fam_url", FAMGATEWAY_API_URL),
    }


def wallet_balance(uid):
    return float((doc("users", uid) or {}).get("balance", 0.0))

def new_id():
    return uuid.uuid4().hex[:10].upper()

def is_admin(uid):
    return int(uid) == ADMIN_ID

def bot_enabled():
    setting = doc("settings", "bot_status")
    return not setting or setting.get("value", "ON") == "ON"

def user_upsert(user):
    save("users", user.id, {
        "user_id": user.id,
        "username": user.username or "",
        "first_name": user.first_name or "",
        "joined_at": now_ts(),
        "last_seen": now_ts(),
        "balance": float((doc("users", user.id) or {}).get("balance", 0.0)),
    })

def user_orders(uid):
    rows = [o for o in all_docs("orders") if int(o.get("user_id", 0)) == int(uid)]
    return sorted(rows, key=lambda x: x.get("created_at", 0), reverse=True)

def active_plans():
    return sorted([p for p in all_docs("plans") if p.get("active", True)], key=lambda x: float(x.get("price", 0)))

def seed_plans():
    if all_docs("plans"):
        return
    starters = [
        ("Python Starter", "Python", "For small Python bots and scripts", 99, 30, "512 MB", "2 GB", "1 vCPU"),
        ("PHP Website", "PHP", "For PHP websites and small projects", 149, 30, "1 GB", "5 GB", "1 vCPU"),
        ("Node.js Basic", "Node.js", "For Node.js apps and bots", 199, 30, "1 GB", "5 GB", "1 vCPU"),
        ("Java Starter", "Java", "For Java apps and lightweight services", 249, 30, "1 GB", "5 GB", "1 vCPU"),
    ]
    for name, language, description, price, days, ram, storage, cpu in starters:
        pid = str(uuid.uuid4().hex[:8])
        save("plans", pid, {
            "name": name, "language": language, "description": description,
            "price": price, "duration_days": days, "ram": ram, "storage": storage,
            "cpu": cpu, "active": True, "created_at": now_ts()
        }, merge=False)
    save("settings", "bot_status", {"value": "ON"})

def main_kb(admin=False):
    rows = [
        [InlineKeyboardButton(text="🚀  EXPLORE HOSTING PLANS", callback_data="plans")],
        [InlineKeyboardButton(text="🧾 My Orders", callback_data="orders"),
         InlineKeyboardButton(text="🔄 Renew Hosting", callback_data="renew_list")],
        [InlineKeyboardButton(text="👛 Add Balance", callback_data="balance_add"),
         InlineKeyboardButton(text="👤 My Profile", callback_data="profile")],
        [InlineKeyboardButton(text="💳 Payments", callback_data="payment_help")],
        [InlineKeyboardButton(text="🎫 24/7 Support", callback_data="support")],
    ]
    if admin:
        rows.append([InlineKeyboardButton(text="🛠 Admin Panel", callback_data="admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Main Menu", callback_data="home")]
    ])

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Add Plan", callback_data="admin_add_plan"),
         InlineKeyboardButton(text="📦 Manage Plans", callback_data="admin_plans")],
        [InlineKeyboardButton(text="🧾 Pending Orders", callback_data="admin_pending"),
         InlineKeyboardButton(text="📋 All Orders", callback_data="admin_orders")],
        [InlineKeyboardButton(text="🎫 Open Tickets", callback_data="admin_tickets"),
         InlineKeyboardButton(text="📊 Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton(text="💳 Payment Settings", callback_data="admin_payments"),
         InlineKeyboardButton(text="👛 Balance Requests", callback_data="admin_balances")],
        [InlineKeyboardButton(text="🔁 Bot ON/OFF", callback_data="admin_toggle"),
         InlineKeyboardButton(text="⬅️ Main Menu", callback_data="home")],
    ])

class AddPlan(StatesGroup):
    name = State()
    language = State()
    description = State()
    price = State()
    duration = State()
    ram = State()
    storage = State()
    cpu = State()

class SupportState(StatesGroup):
    message = State()

class PaymentState(StatesGroup):
    note = State()

class DeliveryState(StatesGroup):
    info = State()

class BalanceState(StatesGroup):
    amount = State()
    screenshot = State()
    utr = State()

class AdminPaymentState(StatesGroup):
    fam_key = State()
    fam_url = State()
    upi_id = State()
    upi_name = State()
    qr_photo = State()

async def safe_edit(call, text, markup=None):
    try:
        await call.message.edit_text(text, reply_markup=markup)
    except Exception:
        await call.message.answer(text, reply_markup=markup)

async def notify_admin(text, markup=None):
    try:
        await bot.send_message(ADMIN_ID, text, reply_markup=markup)
    except Exception:
        log.exception("Admin notification failed")

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    user_upsert(message.from_user)
    if not bot_enabled() and not is_admin(message.from_user.id):
        await message.answer("🛠 Bot maintenance mein hai. Thodi der baad try karein.")
        return
    await message.answer(
        f"⚡ <b>{esc(APP_NAME)}</b>\n"
        "╭━━━━━━━━━━━━━━━━━━╮\n"
        "   <b>PREMIUM HOSTING HUB</b>\n"
        "╰━━━━━━━━━━━━━━━━━━╯\n\n"
        "🚀 <b>Deploy your next project.</b>\n"
        "🐍 Python  •  🌐 PHP\n🟩 Node.js  •  ☕ Java\n\n"
        "💎 Affordable plans  |  🛡️ Verified payments\n"
        "📦 Hosting details delivered after payment confirmation.\n\n"
        "<i>Choose an option below to get started.</i>",
        reply_markup=main_kb(is_admin(message.from_user.id))
    )

@dp.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer("/start — Main menu\n/plans — Hosting plans\n/orders — Your orders\n/cancel — Cancel action\n" + ("/admin — Admin panel" if is_admin(message.from_user.id) else ""))

@dp.message(Command("balance"))
async def balance_cmd(message: Message):
    await message.answer(f"👛 Wallet balance: <b>{money(wallet_balance(message.from_user.id))}</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Add Balance", callback_data="balance_add")], [InlineKeyboardButton(text="⬅️ Main Menu", callback_data="home")]]))


@dp.message(Command("plans"))
async def plans_cmd(message: Message):
    plans = active_plans()
    if not plans:
        await message.answer("Abhi plans available nahi hain.", reply_markup=back_kb())
        return
    for p in plans:
        await message.answer(
            f"🚀 <b>{esc(p.get('name'))}</b>\nLanguage: <b>{esc(p.get('language'))}</b>\n"
            f"{esc(p.get('description'))}\n\nRAM: {esc(p.get('ram'))} · CPU: {esc(p.get('cpu'))}\n"
            f"Storage: {esc(p.get('storage'))}\nDuration: {int(p.get('duration_days',30))} days\n"
            f"Price: <b>{money(p.get('price',0))}</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🛒 Buy this plan", callback_data=f"buy:{p['_id']}")]
            ])
        )

@dp.callback_query(F.data == "home")
async def home(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit(call, f"✨ <b>{esc(APP_NAME)}</b>\nChoose an option below.", main_kb(is_admin(call.from_user.id)))
    await call.answer()

@dp.callback_query(F.data == "plans")
async def plans_cb(call: CallbackQuery):
    plans = active_plans()
    kb = [[InlineKeyboardButton(text=f"{p['name']} · {money(p['price'])}", callback_data=f"plan:{p['_id']}")] for p in plans]
    kb.append([InlineKeyboardButton(text="⬅️ Main Menu", callback_data="home")])
    await safe_edit(call, "💎 <b>CHOOSE YOUR HOSTING PLAN</b>\n━━━━━━━━━━━━━━━━━━\nReliable plans for your next project.\nSelect a plan to view specs and pricing.", InlineKeyboardMarkup(inline_keyboard=kb))
    await call.answer()

@dp.callback_query(F.data.startswith("plan:"))
async def plan_detail(call: CallbackQuery):
    pid = call.data.split(":",1)[1]
    p = doc("plans", pid)
    if not p or not p.get("active", True):
        await call.answer("Plan unavailable.", show_alert=True); return
    text = (f"🚀 <b>{esc(p['name'])}</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"Runtime: {esc(p['language'])}\n{esc(p.get('description'))}\n\n"
            f"RAM: {esc(p.get('ram'))}\nStorage: {esc(p.get('storage'))}\nCPU: {esc(p.get('cpu'))}\n"
            f"Duration: {int(p.get('duration_days',30))} days\nPrice: <b>{money(p['price'])}</b>\n\n"
            "Payment verify hone ke baad admin hosting details deliver karega.")
    await safe_edit(call, text, InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Purchase", callback_data=f"buy:{pid}")],
        [InlineKeyboardButton(text="⬅️ All Plans", callback_data="plans")]
    ]))
    await call.answer()

@dp.callback_query(F.data.startswith("buy:"))
async def buy(call: CallbackQuery):
    pid = call.data.split(":",1)[1]
    p = doc("plans", pid)
    if not p or not p.get("active", True):
        await call.answer("Plan unavailable.", show_alert=True); return
    oid = new_id()
    order = {
        "user_id": call.from_user.id, "plan_id": pid, "plan_name": p["name"],
        "price": float(p["price"]), "duration_days": int(p.get("duration_days",30)),
        "status": "awaiting_payment", "payment_proof_file_id": "", "payment_note": "",
        "payment_gateway": "manual", "gateway_order_id": "", "gateway_checkout_url": "",
        "delivery_info": "", "created_at": now_ts(), "paid_at": 0, "expires_at": 0
    }
    save("orders", oid, order, merge=False)
    paycfg = payment_config()
    active_upi = paycfg.get("upi_enabled", bool(UPI_ID))
    active_upi_id = paycfg.get("upi_id", UPI_ID)
    active_upi_name = paycfg.get("upi_name", UPI_NAME)
    upi = ""
    if active_upi and active_upi_id:
        uri = f"upi://pay?pa={active_upi_id}&pn={active_upi_name.replace(' ','%20')}&am={float(p['price']):.2f}&cu=INR&tn=Hosting%20{oid}"
        upi = f"\n\nUPI ID: <code>{esc(active_upi_id)}</code>\n<a href=\"{esc(uri)}\">📲 Open UPI app</a>"
    order_text = (
        f"🧾 <b>ORDER CREATED SUCCESSFULLY</b>\n╭━━━━━━━━━━━━━━━━━━╮\n"
        f"Order ID: <code>{oid}</code>\nPlan: <b>{esc(p['name'])}</b>\n"
        f"Amount: <b>{money(p['price'])}</b>\nDuration: {p.get('duration_days',30)} days\n"
        f"╰━━━━━━━━━━━━━━━━━━╯\n\n{esc(PAYMENT_INSTRUCTIONS)}{upi}\n\n"
        f"Payment ke baad screenshot/UTR submit karein. Admin verification ke baad hi order paid mark hoga."
    )
    payment_rows = []
    if paycfg.get("fam_enabled", bool(paycfg.get("fam_key") or FAMGATEWAY_API_KEY)) and (paycfg.get("fam_key") or FAMGATEWAY_API_KEY):
        payment_rows.append([InlineKeyboardButton(text="⚡ Pay Online (Gateway)", callback_data=f"fam_pay:{oid}")])
    if active_upi and (active_upi_id or paycfg.get("qr_file_id")):
        payment_rows.append([InlineKeyboardButton(text="📝 Submit UPI Screenshot / UTR", callback_data=f"paynote:{oid}")])
    payment_rows.append([InlineKeyboardButton(text=f"👛 Pay from Wallet ({money(wallet_balance(call.from_user.id))})", callback_data=f"walletbuy:{oid}")])
    payment_rows.extend([
        [InlineKeyboardButton(text="🧾 My Orders", callback_data="orders"),
         InlineKeyboardButton(text="🏠 Main Menu", callback_data="home")]
    ])
    await safe_edit(call, order_text, InlineKeyboardMarkup(inline_keyboard=payment_rows))
    await call.answer("Order created.")

@dp.callback_query(F.data.startswith("walletbuy:"))
async def wallet_buy(call: CallbackQuery):
    oid = call.data.split(":", 1)[1]
    order = doc("orders", oid)
    if not order or int(order.get("user_id", 0)) != call.from_user.id or order.get("status") != "awaiting_payment":
        await call.answer("Order available nahi hai.", show_alert=True); return
    amount = round(float(order.get("price", 0)), 2)
    @firestore.transactional
    def spend_once(transaction, user_ref, order_ref):
        us = user_ref.get(transaction=transaction)
        osnap = order_ref.get(transaction=transaction)
        if not us.exists or not osnap.exists or osnap.to_dict().get("status") != "awaiting_payment": return False
        bal = round(float((us.to_dict() or {}).get("balance", 0)), 2)
        if bal < amount: return False
        transaction.set(user_ref, {"balance": round(bal - amount, 2), "last_balance_update": now_ts()}, merge=True)
        transaction.set(order_ref, {"status": "paid", "paid_at": now_ts(), "payment_gateway": "wallet"}, merge=True)
        return True
    try:
        ok = spend_once(db.transaction(), db.collection("users").document(str(call.from_user.id)), db.collection("orders").document(oid))
    except Exception:
        log.exception("Wallet purchase failed for order %s", oid)
        await call.answer("Wallet payment error. Admin se contact karein.", show_alert=True); return
    if not ok:
        await call.answer("Wallet balance kam hai ya order already processed hai. Add Balance karein.", show_alert=True); return
    await notify_admin(f"👛 <b>WALLET ORDER PAID</b>\nOrder: <code>{oid}</code>\nUser: <code>{call.from_user.id}</code>\nPlan: {esc(order.get('plan_name'))}\nAmount: <b>{money(amount)}</b>\nAb hosting details deliver karein.", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📦 Deliver Hosting", callback_data=f"review:{oid}")]]))
    await safe_edit(call, f"✅ Wallet se {money(amount)} deduct ho gaya.\nOrder: <code>{oid}</code>\n⏳ Admin hosting details deliver karega.\nWallet balance: <b>{money(wallet_balance(call.from_user.id))}</b>", main_kb(is_admin(call.from_user.id)))
    await call.answer("Wallet payment successful.")


def _famgateway_create_order(amount: float, customer_name: str, api_key: str = "", api_url: str = "") -> dict:
    """Call the optional third-party FamGateway checkout API."""
    payload = {
        "amount": round(float(amount), 2),
        "customer_name": (customer_name or "Hosting Customer")[:100],
        "redirect_url": FAMGATEWAY_REDIRECT_URL,
        "webhook_url": FAMGATEWAY_WEBHOOK_URL,
    }
    request = urllib.request.Request(
        api_url or FAMGATEWAY_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Api-Key": api_key or FAMGATEWAY_API_KEY},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=18) as response:
        raw = response.read(1_000_000).decode("utf-8", "replace")
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Payment provider returned invalid JSON") from exc
    if not isinstance(result, dict) or result.get("status") != "success":
        message = result.get("message", "Checkout could not be created") if isinstance(result, dict) else "Unexpected provider response"
        raise RuntimeError(str(message)[:250])
    data = result.get("data") or {}
    checkout_url = data.get("checkout_url") or data.get("payment_url")
    if not isinstance(checkout_url, str) or not checkout_url.startswith("https://"):
        raise RuntimeError("Provider response did not include a valid HTTPS checkout URL")
    return {"checkout_url": checkout_url, "order_id": str(data.get("order_id", ""))[:120]}


@dp.callback_query(F.data.startswith("fam_pay:"))
async def famgateway_payment(call: CallbackQuery):
    paycfg = payment_config()
    gateway_key = (paycfg.get("fam_key") or FAMGATEWAY_API_KEY).strip()
    gateway_url = (paycfg.get("fam_url") or FAMGATEWAY_API_URL).strip()
    if not gateway_key or not paycfg.get("fam_enabled", bool(gateway_key)):
        await call.answer("Online checkout disabled hai; available payment method use karein.", show_alert=True)
        return
    oid = call.data.split(":", 1)[1]
    order = doc("orders", oid)
    if not order or int(order.get("user_id", 0)) != call.from_user.id or order.get("status") != "awaiting_payment":
        await call.answer("Yeh order payment ke liye available nahi hai.", show_alert=True)
        return
    await call.answer("Secure checkout create ho raha hai…")
    try:
        checkout = await asyncio.to_thread(
            _famgateway_create_order, float(order["price"]), call.from_user.full_name,
            gateway_key, gateway_url
        )
        save("orders", oid, {
            "payment_gateway": "famgateway",
            "gateway_order_id": checkout["order_id"],
            "gateway_checkout_url": checkout["checkout_url"],
        })
        await call.message.answer(
            "⚡ <b>ONLINE CHECKOUT READY</b>\n"
            f"Order: <code>{oid}</code>\nAmount: <b>{money(order['price'])}</b>\n\n"
            "Checkout open karke payment complete karein. Is single-file bot mein payment ko admin provider dashboard se verify karega; sirf checkout khulne se order paid/hosting active nahi hoti. Payment ke baad manual UPI screenshot/UTR bhi submit kar sakte hain.\n\n"
            "<i>FamGateway independent third-party service hai, official FamPay API nahi.</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔐 Open Secure Checkout", url=checkout["checkout_url"])],
                [InlineKeyboardButton(text="📝 Submit UPI Screenshot / UTR", callback_data=f"paynote:{oid}")],
                [InlineKeyboardButton(text="🧾 My Orders", callback_data="orders")],
            ])
        )
    except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError) as exc:
        log.warning("FamGateway checkout failed for order %s: %s", oid, exc)
        await call.message.answer(
            "⚠️ Online checkout abhi create nahi ho saka. Aapka order safe hai; manual UPI payment aur screenshot/UTR submit option use karein.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📝 Submit UPI Screenshot / UTR", callback_data=f"paynote:{oid}")],
                [InlineKeyboardButton(text="🧾 My Orders", callback_data="orders")],
            ])
        )


@dp.callback_query(F.data.startswith("paynote:"))
async def paynote_start(call: CallbackQuery, state: FSMContext):
    oid = call.data.split(":",1)[1]
    o = doc("orders", oid)
    if not o or int(o.get("user_id",0)) != call.from_user.id or o.get("status") != "awaiting_payment":
        await call.answer("Pending order nahi mila.", show_alert=True); return
    await state.set_state(PaymentState.note)
    await state.update_data(order_id=oid)
    await call.message.answer("Payment UTR/reference number ya note bhejein. Screenshot ko Order ID caption ke saath bhej sakte hain.")
    await call.answer()

@dp.message(PaymentState.note)
async def paynote_receive(message: Message, state: FSMContext):
    data = await state.get_data()
    oid = data.get("order_id")
    o = doc("orders", oid) if oid else None
    if not o or int(o.get("user_id",0)) != message.from_user.id:
        await state.clear(); await message.answer("Order nahi mila."); return
    note = (message.text or message.caption or "")[:1000]
    save("orders", oid, {"payment_note": note})
    await state.clear()
    await message.answer(f"📨 Note submit ho gaya. Order <code>{oid}</code> admin verification ka wait kar raha hai.")
    await notify_admin(f"💳 <b>PAYMENT NOTE</b>\nOrder: <code>{oid}</code>\nUser: <code>{message.from_user.id}</code>\nAmount: {money(o['price'])}\nNote: {esc(note)}",
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Approve", callback_data=f"approve:{oid}"),
             InlineKeyboardButton(text="❌ Reject", callback_data=f"reject:{oid}")]
        ]))

async def receive_proof(message: Message, file_id: str, kind: str):
    import re
    caption = (message.caption or "").strip()
    match = re.search(r"\b([A-F0-9]{10})\b", caption.upper())
    oid = match.group(1) if match else ""
    if not oid:
        pending = [o for o in user_orders(message.from_user.id) if o.get("status") == "awaiting_payment"]
        if len(pending) == 1:
            oid = pending[0]["_id"]
    o = doc("orders", oid) if oid else None
    if not o or int(o.get("user_id",0)) != message.from_user.id or o.get("status") != "awaiting_payment":
        await message.answer("Caption mein pending Order ID likhein. Example: ORDER: ABC123DE45")
        return
    save("orders", oid, {"payment_proof_file_id": file_id, "payment_note": caption})
    await message.answer(f"📨 Payment proof order <code>{oid}</code> ke liye submit ho gaya. Admin verify karega.")
    await notify_admin(f"💳 <b>PAYMENT PROOF ({kind})</b>\nOrder: <code>{oid}</code>\nUser: <code>{message.from_user.id}</code>\nAmount: {money(o['price'])}\nCaption: {esc(caption)}",
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Approve", callback_data=f"approve:{oid}"),
             InlineKeyboardButton(text="❌ Reject", callback_data=f"reject:{oid}")]
        ]))
    try:
        if kind == "photo":
            await bot.send_photo(ADMIN_ID, file_id, caption=f"Proof for {oid} | user {message.from_user.id}")
        else:
            await bot.send_document(ADMIN_ID, file_id, caption=f"Proof for {oid} | user {message.from_user.id}")
    except Exception:
        log.exception("Could not forward payment proof")

@dp.message(F.photo)
async def photo_proof(message: Message, state: FSMContext):
    current = await state.get_state()
    if current == BalanceState.screenshot.state:
        data = await state.get_data(); rid = data.get("balance_request_id")
        req = doc("balance_requests", rid) if rid else None
        if not req or int(req.get("user_id",0)) != message.from_user.id or req.get("status") != "awaiting_proof":
            await state.clear(); await message.answer("Top-up request nahi mila. Add Balance dobara try karein."); return
        save("balance_requests", rid, {"proof_file_id": message.photo[-1].file_id, "proof_kind":"photo", "proof_received_at":now_ts()})
        await state.set_state(BalanceState.utr)
        await message.answer("✅ Screenshot receive ho gaya.\n\n🧾 <b>Step 2/2:</b> Ab payment ka UTR / transaction reference ID bhejein.")
        return
    if current == AdminPaymentState.qr_photo.state:
        cfg = payment_config(); cfg["qr_file_id"] = message.photo[-1].file_id; cfg["upi_enabled"] = True
        save("settings", "payment_config", cfg); await state.clear()
        await message.answer("✅ UPI QR save ho gaya.", reply_markup=admin_kb()); return
    await receive_proof(message, message.photo[-1].file_id, "photo")

@dp.message(F.document)
async def document_proof(message: Message, state: FSMContext):
    current = await state.get_state()
    if current == BalanceState.screenshot.state:
        data = await state.get_data(); rid = data.get("balance_request_id")
        req = doc("balance_requests", rid) if rid else None
        if not req or int(req.get("user_id",0)) != message.from_user.id or req.get("status") != "awaiting_proof":
            await state.clear(); await message.answer("Top-up request nahi mila. Add Balance dobara try karein."); return
        save("balance_requests", rid, {"proof_file_id": message.document.file_id, "proof_kind":"document", "proof_received_at":now_ts()})
        await state.set_state(BalanceState.utr)
        await message.answer("✅ Screenshot/file receive ho gayi.\n\n🧾 <b>Step 2/2:</b> Ab payment ka UTR / transaction reference ID bhejein.")
        return
    await receive_proof(message, message.document.file_id, "document")

@dp.callback_query(F.data == "orders")
async def orders_cb(call: CallbackQuery):
    rows = user_orders(call.from_user.id)[:10]
    if not rows:
        await safe_edit(call, "🧾 Abhi koi order nahi hai.", back_kb())
    else:
        lines = ["🧾 <b>MY ORDERS</b>"]
        for o in rows:
            lines.append(f"\n<b>{esc(o.get('plan_name'))}</b> · {money(o.get('price',0))}\nID: <code>{o['_id']}</code>\nStatus: <b>{esc(o.get('status','unknown').replace('_',' ').title())}</b>\n" + (f"Expires: {fmt_time(o.get('expires_at'))}\n" if o.get("expires_at") else ""))
        await safe_edit(call, "\n".join(lines), back_kb())
    await call.answer()

@dp.callback_query(F.data == "renew_list")
async def renew_list(call: CallbackQuery):
    rows = [o for o in user_orders(call.from_user.id) if o.get("status") in ("delivered","active","expired")]
    if not rows:
        await safe_edit(call, "Renewal ke liye koi delivered hosting order nahi mila.", back_kb())
    else:
        kb = [[InlineKeyboardButton(text=f"🔄 {o.get('plan_name')} · {money(o.get('price',0))}", callback_data=f"renew:{o['_id']}")] for o in rows[:10]]
        kb.append([InlineKeyboardButton(text="⬅️ Main Menu", callback_data="home")])
        await safe_edit(call, "🔄 <b>Choose hosting to renew</b>", InlineKeyboardMarkup(inline_keyboard=kb))
    await call.answer()

@dp.callback_query(F.data.startswith("renew:"))
async def renew(call: CallbackQuery):
    old_id = call.data.split(":",1)[1]
    old = doc("orders", old_id)
    if not old or int(old.get("user_id",0)) != call.from_user.id:
        await call.answer("Order nahi mila.", show_alert=True); return
    oid = new_id()
    save("orders", oid, {
        "user_id": call.from_user.id, "plan_id": old.get("plan_id"),
        "plan_name": old.get("plan_name") + " (Renewal)", "price": float(old.get("price",0)),
        "duration_days": int(old.get("duration_days",30)), "status": "awaiting_payment",
        "payment_proof_file_id": "", "payment_note": "", "delivery_info": "",
        "created_at": now_ts(), "paid_at": 0, "expires_at": 0
    }, merge=False)
    await safe_edit(call, f"🔄 <b>Renewal order created</b>\nOrder: <code>{oid}</code>\nAmount: <b>{money(old.get('price',0))}</b>\n\n{esc(PAYMENT_INSTRUCTIONS)}\nPayment proof caption mein Order ID <code>{oid}</code> likhein.",
        InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📝 Submit payment note", callback_data=f"paynote:{oid}")],[InlineKeyboardButton(text="⬅️ Main Menu", callback_data="home")]]))
    await call.answer()

@dp.callback_query(F.data == "profile")
async def profile(call: CallbackQuery):
    user = doc("users", call.from_user.id) or {}
    rows = user_orders(call.from_user.id)
    paid = sum(float(o.get("price",0)) for o in rows if o.get("status") in ("paid","delivered","active","expired"))
    active = sum(1 for o in rows if o.get("status") in ("delivered","active") and (not o.get("expires_at") or o["expires_at"] > now_ts()))
    await safe_edit(call, f"👤 <b>MY PROFILE</b>\nName: {esc(user.get('first_name',call.from_user.first_name))}\nUser ID: <code>{call.from_user.id}</code>\nWallet balance: <b>{money(user.get('balance', 0))}</b>\nOrders: {len(rows)}\nActive hosting: {active}\nVerified sales: {money(paid)}", back_kb())
    await call.answer()

@dp.callback_query(F.data == "payment_help")
async def payment_help(call: CallbackQuery):
    cfg = payment_config()
    txt = f"💳 <b>PAYMENT HELP</b>\n{esc(PAYMENT_INSTRUCTIONS)}"
    if cfg.get("upi_enabled", bool(UPI_ID)) and cfg.get("upi_id", UPI_ID):
        txt += f"\nUPI ID: <code>{esc(cfg.get('upi_id', UPI_ID))}</code>\nName: {esc(cfg.get('upi_name', UPI_NAME))}"
    if cfg.get("qr_file_id"):
        txt += "\n\nUPI QR available hai. Add Balance ya payment screen se QR dekhein."
    txt += "\n\nPayment screenshot automatic verification nahi hai; admin proof check karega."
    await safe_edit(call, txt, back_kb()); await call.answer()

@dp.callback_query(F.data == "support")
async def support_start(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(SupportState.message)
    await state.update_data(mode="new_ticket")
    await call.message.answer("Apna support message ek text message mein bhejein.")
    await call.answer()

@dp.message(SupportState.message)
async def support_receive(message: Message, state: FSMContext):
    data = await state.get_data()
    msg = (message.text or message.caption or "").strip()
    if not msg:
        await message.answer("Text message bhejein."); return
    if data.get("mode") == "ticket_reply" and is_admin(message.from_user.id):
        tid, uid = data.get("ticket_id"), data.get("ticket_user")
        save("tickets", tid, {"reply": msg[:3000], "status": "closed"})
        await state.clear()
        try:
            await bot.send_message(int(uid), f"💬 <b>Support reply — Ticket #{tid}</b>\n\n{esc(msg[:3000])}")
        except Exception:
            pass
        await message.answer(f"✅ Reply sent; ticket #{tid} closed.", reply_markup=admin_kb())
        return
    tid = new_id()
    save("tickets", tid, {"user_id": message.from_user.id, "message": msg[:3000], "status": "open", "created_at": now_ts(), "reply": ""}, merge=False)
    await state.clear()
    await message.answer(f"🎫 Ticket <code>#{tid}</code> create ho gaya.")
    await notify_admin(f"🎫 <b>NEW SUPPORT TICKET #{tid}</b>\nUser: <code>{message.from_user.id}</code>\n{esc(msg[:3000])}",
        InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Reply", callback_data=f"ticket_reply:{tid}")]]))

@dp.callback_query(F.data == "balance_add")
async def balance_add_start(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(BalanceState.amount)
    bal = wallet_balance(call.from_user.id)
    await call.message.answer(
        f"👛 <b>WALLET TOP-UP</b>\nCurrent balance: <b>{money(bal)}</b>\n\n"
        "Kitna balance add karna hai? Amount INR mein bhejein (minimum ₹10, maximum ₹50,000)."
    )
    await call.answer()


@dp.message(BalanceState.amount)
async def balance_amount_receive(message: Message, state: FSMContext):
    try:
        amount = round(float((message.text or "").strip()), 2)
        if not 10 <= amount <= 50000:
            raise ValueError
    except (TypeError, ValueError):
        await message.answer("Valid amount bhejein: ₹10 se ₹50,000 tak.")
        return
    cfg = payment_config()
    methods = []
    if cfg.get("upi_enabled") and (cfg.get("upi_id") or cfg.get("qr_file_id")):
        methods.append([InlineKeyboardButton(text="📲 UPI / QR", callback_data="balmethod:upi")])
    if cfg.get("fam_enabled") and cfg.get("fam_key"):
        methods.append([InlineKeyboardButton(text="⚡ Online Gateway", callback_data="balmethod:gateway")])
    if not methods:
        await state.clear()
        await message.answer("⚠️ Abhi admin ne koi payment method enable nahi kiya. Baad mein try karein.", reply_markup=main_kb(is_admin(message.from_user.id)))
        return
    rid = new_id()
    save("balance_requests", rid, {
        "user_id": message.from_user.id, "amount": amount, "status": "choosing_method",
        "method": "", "proof_file_id": "", "utr": "", "created_at": now_ts(), "credited_at": 0
    }, merge=False)
    await state.update_data(balance_request_id=rid)
    await state.clear()
    await message.answer(
        f"👛 <b>TOP-UP REQUEST</b>\nRequest ID: <code>{rid}</code>\nAmount: <b>{money(amount)}</b>\n\nPayment method choose karein:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=methods + [[InlineKeyboardButton(text="⬅️ Main Menu", callback_data="home")]])
    )


@dp.callback_query(F.data.startswith("balmethod:"))
async def balance_method(call: CallbackQuery, state: FSMContext):
    method = call.data.split(":", 1)[1]
    requests = [r for r in all_docs("balance_requests") if int(r.get("user_id", 0)) == call.from_user.id and r.get("status") == "choosing_method"]
    if not requests:
        await call.answer("Top-up request nahi mila. Add Balance dobara kholein.", show_alert=True)
        return
    req = sorted(requests, key=lambda r: r.get("created_at", 0), reverse=True)[0]
    cfg = payment_config()
    if method == "upi" and not (cfg.get("upi_enabled") and (cfg.get("upi_id") or cfg.get("qr_file_id"))):
        await call.answer("UPI abhi disabled hai.", show_alert=True); return
    if method == "gateway" and not (cfg.get("fam_enabled") and cfg.get("fam_key")):
        await call.answer("Gateway abhi disabled hai.", show_alert=True); return
    save("balance_requests", req["_id"], {"method": method, "status": "awaiting_proof"})
    await state.clear()
    await state.set_state(BalanceState.screenshot)
    await state.update_data(balance_request_id=req["_id"])
    text = (f"💳 <b>PAYMENT DETAILS</b>\nRequest: <code>{req['_id']}</code>\nAmount: <b>{money(req['amount'])}</b>\n\n")
    if method == "upi":
        if cfg.get("upi_id"):
            text += f"UPI ID: <code>{esc(cfg['upi_id'])}</code>\nName: <b>{esc(cfg.get('upi_name') or UPI_NAME)}</b>\n"
            uri = f"upi://pay?pa={cfg['upi_id']}&pn={(cfg.get('upi_name') or UPI_NAME).replace(' ','%20')}&am={float(req['amount']):.2f}&cu=INR&tn=Balance%20{req['_id']}"
            text += f"<a href=\"{esc(uri)}\">📲 Open UPI app</a>\n"
        text += "\nPayment karne ke baad pehle screenshot bhejein. Uske baad bot UTR/reference ID maangega."
        await call.message.answer(text)
        if cfg.get("qr_file_id"):
            try:
                await bot.send_photo(call.from_user.id, cfg["qr_file_id"], caption=f"Scan karke exactly {money(req['amount'])} pay karein. Request: {req['_id']}")
            except Exception:
                log.exception("Could not send configured UPI QR")
    else:
        text += "Online checkout create karne ki koshish ho rahi hai. Screenshot aur UTR submit karna na bhoolein; admin provider dashboard se payment verify karega."
        await call.message.answer(text)
        try:
            checkout = await asyncio.to_thread(_famgateway_create_order, float(req["amount"]), call.from_user.full_name, cfg["fam_key"], cfg.get("fam_url") or FAMGATEWAY_API_URL)
            save("balance_requests", req["_id"], {"gateway_order_id": checkout["order_id"], "gateway_checkout_url": checkout["checkout_url"]})
            await call.message.answer("Secure checkout:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔐 Open Checkout", url=checkout["checkout_url"])]]))
        except Exception as exc:
            log.warning("Gateway top-up checkout failed: %s", exc)
            await call.message.answer("Gateway checkout abhi unavailable hai. Admin se contact karein ya UPI method use karein.")
    await call.message.answer("📸 <b>Step 1/2:</b> Ab payment ka screenshot/photo bhejein.")
    await call.answer()


@dp.message(BalanceState.utr)
async def balance_utr_receive(message: Message, state: FSMContext):
    data = await state.get_data()
    rid = data.get("balance_request_id")
    req = doc("balance_requests", rid) if rid else None
    utr = (message.text or "").strip()
    if not req or int(req.get("user_id", 0)) != message.from_user.id or req.get("status") != "awaiting_proof":
        await state.clear(); await message.answer("Pending top-up request nahi mila. /start se dobara try karein."); return
    if len(utr) < 5 or len(utr) > 120:
        await message.answer("Valid UTR/reference ID bhejein (5–120 characters).")
        return
    save("balance_requests", rid, {"utr": utr, "status": "pending_review", "submitted_at": now_ts()})
    await state.clear()
    await message.answer(f"✅ Screenshot aur UTR submit ho gaya.\nRequest: <code>{rid}</code>\nAmount: <b>{money(req['amount'])}</b>\n\n⏳ Admin payment verify karega. Approval se pehle balance add nahi hoga.", reply_markup=main_kb(is_admin(message.from_user.id)))
    await notify_admin(
        f"👛 <b>WALLET TOP-UP REVIEW</b>\nRequest: <code>{rid}</code>\nUser: <code>{message.from_user.id}</code>\nAmount: <b>{money(req['amount'])}</b>\nMethod: {esc(req.get('method'))}\nUTR: <code>{esc(utr)}</code>",
        InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Approve & Credit", callback_data=f"balapprove:{rid}"), InlineKeyboardButton(text="❌ Reject", callback_data=f"balreject:{rid}")], [InlineKeyboardButton(text="🔎 Review", callback_data=f"balreview:{rid}")]])
    )
    if req.get("proof_file_id"):
        try:
            if req.get("proof_kind") == "document":
                await bot.send_document(ADMIN_ID, req["proof_file_id"], caption=f"Wallet proof {rid} | user {message.from_user.id}")
            else:
                await bot.send_photo(ADMIN_ID, req["proof_file_id"], caption=f"Wallet proof {rid} | user {message.from_user.id}")
        except Exception:
            log.exception("Could not forward balance proof")


@dp.callback_query(F.data == "admin_payments")
async def admin_payments(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Admin only.", show_alert=True); return
    cfg = payment_config()
    upi_status = "ON" if cfg.get("upi_enabled") else "OFF"
    fam_status = "ON" if cfg.get("fam_enabled") else "OFF"
    txt = ("💳 <b>PAYMENT CONTROL CENTER</b>\n\n"
           f"UPI / QR: <b>{upi_status}</b>\nUPI ID: <code>{esc(cfg.get('upi_id') or 'Not set')}</code>\n"
           f"UPI name: {esc(cfg.get('upi_name') or UPI_NAME)}\nQR: {'Uploaded' if cfg.get('qr_file_id') else 'Not uploaded'}\n\n"
           f"Gateway checkout: <b>{fam_status}</b>\nAPI key: {'Configured' if cfg.get('fam_key') else 'Not configured'}\n"
           f"API URL: <code>{esc(cfg.get('fam_url') or FAMGATEWAY_API_URL)}</code>\n\n"
           "API key admin-only settings mein save hoti hai. Yeh independent gateway integration hai; official FamPay API hone ka claim nahi hai.")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📲 UPI {'ON' if cfg.get('upi_enabled') else 'OFF'} — Toggle", callback_data="paytoggle:upi")],
        [InlineKeyboardButton(text=f"⚡ Gateway {'ON' if cfg.get('fam_enabled') else 'OFF'} — Toggle", callback_data="paytoggle:fam")],
        [InlineKeyboardButton(text="✏️ Set UPI ID", callback_data="payset:upi_id"), InlineKeyboardButton(text="✏️ Set UPI Name", callback_data="payset:upi_name")],
        [InlineKeyboardButton(text="🖼 Upload / Replace QR", callback_data="payset:qr")],
        [InlineKeyboardButton(text="🔑 Set Gateway API Key", callback_data="payset:fam_key")],
        [InlineKeyboardButton(text="🌐 Set Gateway API URL", callback_data="payset:fam_url")],
        [InlineKeyboardButton(text="⬅️ Admin Panel", callback_data="admin")]
    ])
    await safe_edit(call, txt, kb); await call.answer()


@dp.callback_query(F.data.startswith("paytoggle:"))
async def payment_toggle(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Admin only.", show_alert=True); return
    which = call.data.split(":", 1)[1]
    cfg = payment_config()
    key = "upi_enabled" if which == "upi" else "fam_enabled"
    cfg[key] = not bool(cfg.get(key))
    save("settings", "payment_config", cfg)
    # Refresh the panel; admin_payments also answers the callback query.
    await admin_payments(call, dp.fsm.get_context(bot=bot, chat_id=call.message.chat.id, user_id=call.from_user.id))


@dp.callback_query(F.data.startswith("payset:"))
async def payment_set_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Admin only.", show_alert=True); return
    field = call.data.split(":", 1)[1]
    if field == "qr":
        await state.clear(); await state.set_state(AdminPaymentState.qr_photo)
        await call.message.answer("🖼 Apna UPI QR image/photo yahan bhejein. Naya QR purane ko replace kar dega.")
    elif field in ("upi_id", "upi_name", "fam_key", "fam_url"):
        await state.clear()
        state_map = {"upi_id": AdminPaymentState.upi_id, "upi_name": AdminPaymentState.upi_name, "fam_key": AdminPaymentState.fam_key, "fam_url": AdminPaymentState.fam_url}
        await state.set_state(state_map[field])
        prompts = {"upi_id": "Apna UPI ID bhejein, e.g. name@bank", "upi_name": "Payment receiver name bhejein", "fam_key": "Gateway API key bhejein. Message sirf admin ko process hoga; key ko kisi aur se share na karein.", "fam_url": "Gateway ke official create-order API endpoint ka HTTPS URL bhejein."}
        await call.message.answer(prompts[field])
    await call.answer()


async def admin_payment_text(message: Message, state: FSMContext, field: str):
    if not is_admin(message.from_user.id):
        await state.clear(); await message.answer("Admin only."); return
    value = (message.text or "").strip()
    if not value or len(value) > 1000:
        await message.answer("Valid value bhejein."); return
    cfg = payment_config()
    if field == "upi_id":
        if "@" not in value or " " in value:
            await message.answer("UPI ID format sahi nahi lag raha. Example: name@bank"); return
        cfg["upi_id"] = value[:120]
        cfg["upi_enabled"] = True
    elif field == "upi_name": cfg["upi_name"] = value[:100]
    elif field == "fam_key":
        cfg["fam_key"] = value[:500]
        cfg["fam_enabled"] = True
    elif field == "fam_url":
        if not value.startswith("https://"):
            await message.answer("Security ke liye HTTPS URL hi use karein."); return
        cfg["fam_url"] = value[:500]
    save("settings", "payment_config", cfg)
    await state.clear()
    if field == "fam_key":
        try: await message.delete()
        except Exception: pass
    await message.answer("✅ Payment setting save ho gayi.", reply_markup=admin_kb())


@dp.message(AdminPaymentState.upi_id)
async def set_upi_id(message: Message, state: FSMContext): await admin_payment_text(message, state, "upi_id")
@dp.message(AdminPaymentState.upi_name)
async def set_upi_name(message: Message, state: FSMContext): await admin_payment_text(message, state, "upi_name")
@dp.message(AdminPaymentState.fam_key)
async def set_fam_key(message: Message, state: FSMContext): await admin_payment_text(message, state, "fam_key")
@dp.message(AdminPaymentState.fam_url)
async def set_fam_url(message: Message, state: FSMContext): await admin_payment_text(message, state, "fam_url")


@dp.message(AdminPaymentState.qr_photo, F.photo)
async def set_payment_qr(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear(); await message.answer("Admin only."); return
    cfg = payment_config(); cfg["qr_file_id"] = message.photo[-1].file_id; cfg["upi_enabled"] = True
    save("settings", "payment_config", cfg); await state.clear()
    await message.answer("✅ UPI QR save ho gaya. Enabled payment screens par users ko yahi QR bheja jayega.", reply_markup=admin_kb())


@dp.callback_query(F.data == "admin_balances")
async def admin_balances(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Admin only.", show_alert=True); return
    rows = sorted([r for r in all_docs("balance_requests") if r.get("status") == "pending_review"], key=lambda r:r.get("created_at",0))
    kb = [[InlineKeyboardButton(text=f"{r['_id']} · {money(r.get('amount',0))} · {r.get('user_id')}", callback_data=f"balreview:{r['_id']}")] for r in rows[:20]]
    kb.append([InlineKeyboardButton(text="⬅️ Admin Panel", callback_data="admin")])
    await safe_edit(call, f"👛 <b>PENDING BALANCE REQUESTS</b>\nPending: {len(rows)}\nSelect request to review.", InlineKeyboardMarkup(inline_keyboard=kb)); await call.answer()


@dp.callback_query(F.data.startswith("balreview:"))
async def balance_review(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Admin only.", show_alert=True); return
    rid = call.data.split(":",1)[1]; req = doc("balance_requests", rid)
    if not req:
        await call.answer("Request not found.", show_alert=True); return
    text = (f"👛 <b>TOP-UP REVIEW</b>\nRequest: <code>{rid}</code>\nUser: <code>{req.get('user_id')}</code>\n"
            f"Amount: <b>{money(req.get('amount',0))}</b>\nMethod: {esc(req.get('method'))}\nUTR: <code>{esc(req.get('utr') or 'Not submitted')}</code>\n"
            f"Status: <b>{esc(req.get('status'))}</b>")
    kb = []
    if req.get("status") == "pending_review":
        kb.append([InlineKeyboardButton(text="✅ Approve & Credit", callback_data=f"balapprove:{rid}"), InlineKeyboardButton(text="❌ Reject", callback_data=f"balreject:{rid}")])
    kb.append([InlineKeyboardButton(text="⬅️ Pending Requests", callback_data="admin_balances")])
    await safe_edit(call, text, InlineKeyboardMarkup(inline_keyboard=kb))
    if req.get("proof_file_id"):
        try:
            if req.get("proof_kind") == "document":
                await bot.send_document(call.from_user.id, req["proof_file_id"], caption=f"Payment proof for {rid}")
            else:
                await bot.send_photo(call.from_user.id, req["proof_file_id"], caption=f"Payment proof for {rid}")
        except Exception: pass
    await call.answer()


@dp.callback_query(F.data.startswith("balapprove:"))
async def balance_approve(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Admin only.", show_alert=True); return
    rid = call.data.split(":",1)[1]; req = doc("balance_requests", rid)
    if not req or req.get("status") != "pending_review":
        await call.answer("Already reviewed or not pending.", show_alert=True); return
    uid = int(req.get("user_id",0)); amount = round(float(req.get("amount",0)),2)
    # Firestore transaction makes crediting idempotent against double-clicks.
    @firestore.transactional
    def credit_once(transaction, request_ref, user_ref):
        rs = request_ref.get(transaction=transaction)
        if not rs.exists or rs.to_dict().get("status") != "pending_review": return False
        us = user_ref.get(transaction=transaction)
        current = float((us.to_dict() or {}).get("balance",0)) if us.exists else 0.0
        transaction.set(user_ref, {"balance": round(current + amount,2), "last_balance_update": now_ts()}, merge=True)
        transaction.set(request_ref, {"status":"approved", "credited_at":now_ts(), "credited_by":call.from_user.id}, merge=True)
        return True
    try:
        transaction = db.transaction()
        ok = credit_once(transaction, db.collection("balance_requests").document(rid), db.collection("users").document(str(uid)))
    except Exception:
        log.exception("Wallet credit transaction failed for %s", rid)
        await call.answer("Credit failed; logs check karein.", show_alert=True); return
    if not ok:
        await call.answer("Request already processed.", show_alert=True); return
    new_balance = wallet_balance(uid)
    try: await bot.send_message(uid, f"✅ <b>WALLET TOP-UP APPROVED</b>\nRequest: <code>{rid}</code>\nCredited: <b>{money(amount)}</b>\nNew balance: <b>{money(new_balance)}</b>")
    except Exception: pass
    await safe_edit(call, f"✅ Request <code>{rid}</code> approved. {money(amount)} wallet mein credit hua.", admin_kb())
    await call.answer("Balance credited exactly once.")


@dp.callback_query(F.data.startswith("balreject:"))
async def balance_reject(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Admin only.", show_alert=True); return
    rid = call.data.split(":",1)[1]; req = doc("balance_requests", rid)
    if not req or req.get("status") != "pending_review":
        await call.answer("Already reviewed or not pending.", show_alert=True); return
    save("balance_requests", rid, {"status":"rejected", "reviewed_at":now_ts(), "reviewed_by":call.from_user.id})
    try: await bot.send_message(int(req.get("user_id",0)), f"❌ Top-up request <code>{rid}</code> reject hui. Agar payment kiya hai to {esc(ADMIN_CONTACT)} se contact karein.")
    except Exception: pass
    await safe_edit(call, f"❌ Request <code>{rid}</code> rejected; balance add nahi hua.", admin_kb()); await call.answer("Rejected.")


@dp.callback_query(F.data == "admin")
async def admin_home(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Admin only.", show_alert=True); return
    status = (doc("settings","bot_status") or {}).get("value","ON")
    await safe_edit(call, f"🛠 <b>ADMIN CONTROL CENTER</b>\nBot status: <b>{status}</b>", admin_kb()); await call.answer()

@dp.message(Command("admin"))
async def admin_cmd(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Admin only."); return
    await message.answer("🛠 <b>ADMIN CONTROL CENTER</b>", reply_markup=admin_kb())

@dp.callback_query(F.data == "admin_toggle")
async def admin_toggle(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Admin only.", show_alert=True); return
    current = (doc("settings","bot_status") or {}).get("value","ON")
    new = "OFF" if current == "ON" else "ON"
    save("settings","bot_status",{"value":new})
    await safe_edit(call, f"Bot status: <b>{new}</b>", admin_kb()); await call.answer("Updated.")

@dp.callback_query(F.data == "admin_add_plan")
async def add_plan_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Admin only.", show_alert=True); return
    await state.clear(); await state.set_state(AddPlan.name)
    await call.message.answer("Plan name bhejein, e.g. Python Pro"); await call.answer()

@dp.message(AddPlan.name)
async def add_name(message: Message, state: FSMContext):
    await state.update_data(name=(message.text or "").strip()[:80]); await state.set_state(AddPlan.language)
    await message.answer("Runtime/language: Python, PHP, Node.js, Java etc.")

@dp.message(AddPlan.language)
async def add_language(message: Message, state: FSMContext):
    await state.update_data(language=(message.text or "").strip()[:40]); await state.set_state(AddPlan.description)
    await message.answer("Plan description bhejein.")

@dp.message(AddPlan.description)
async def add_description(message: Message, state: FSMContext):
    await state.update_data(description=(message.text or "").strip()[:500]); await state.set_state(AddPlan.price)
    await message.answer("Price number mein bhejein, e.g. 199")

@dp.message(AddPlan.price)
async def add_price(message: Message, state: FSMContext):
    try:
        price = float((message.text or "").strip())
        if not 0 <= price <= 10000000: raise ValueError
    except ValueError:
        await message.answer("Valid price bhejein, e.g. 199."); return
    await state.update_data(price=price); await state.set_state(AddPlan.duration)
    await message.answer("Duration days mein bhejein, e.g. 30")

@dp.message(AddPlan.duration)
async def add_duration(message: Message, state: FSMContext):
    try:
        days = int((message.text or "").strip())
        if not 1 <= days <= 3650: raise ValueError
    except ValueError:
        await message.answer("Duration 1–3650 days hona chahiye."); return
    await state.update_data(duration=days); await state.set_state(AddPlan.ram)
    await message.answer("RAM, e.g. 1 GB")

@dp.message(AddPlan.ram)
async def add_ram(message: Message, state: FSMContext):
    await state.update_data(ram=(message.text or "").strip()[:40]); await state.set_state(AddPlan.storage)
    await message.answer("Storage, e.g. 5 GB")

@dp.message(AddPlan.storage)
async def add_storage(message: Message, state: FSMContext):
    await state.update_data(storage=(message.text or "").strip()[:40]); await state.set_state(AddPlan.cpu)
    await message.answer("CPU, e.g. 1 vCPU")

@dp.message(AddPlan.cpu)
async def add_cpu(message: Message, state: FSMContext):
    data = await state.get_data()
    pid = uuid.uuid4().hex[:8]
    save("plans", pid, {"name":data["name"],"language":data["language"],"description":data["description"],
         "price":data["price"],"duration_days":data["duration"],"ram":data["ram"],"storage":data["storage"],
         "cpu":(message.text or "").strip()[:40],"active":True,"created_at":now_ts()}, merge=False)
    await state.clear(); await message.answer(f"✅ Plan <b>{esc(data['name'])}</b> add ho gaya.", reply_markup=admin_kb())

@dp.callback_query(F.data == "admin_plans")
async def admin_plans(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Admin only.", show_alert=True); return
    plans = sorted(all_docs("plans"), key=lambda p:p.get("name","").lower())
    kb = [[InlineKeyboardButton(text=f"{'🟢' if p.get('active') else '🔴'} {p.get('name')} · {money(p.get('price',0))}", callback_data=f"plan_toggle:{p['_id']}")] for p in plans]
    kb.append([InlineKeyboardButton(text="⬅️ Admin", callback_data="admin")])
    await safe_edit(call, "📦 <b>PLAN MANAGER</b>\nTap a plan to toggle active/inactive.", InlineKeyboardMarkup(inline_keyboard=kb)); await call.answer()

@dp.callback_query(F.data.startswith("plan_toggle:"))
async def plan_toggle(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Admin only.", show_alert=True); return
    pid = call.data.split(":",1)[1]; p = doc("plans",pid)
    if not p:
        await call.answer("Plan not found.", show_alert=True); return
    save("plans",pid,{"active":not p.get("active",True)})
    await call.answer("Plan updated.")
    await admin_plans(call)

@dp.callback_query(F.data == "admin_pending")
async def admin_pending(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Admin only.", show_alert=True); return
    rows = sorted([o for o in all_docs("orders") if o.get("status")=="awaiting_payment"], key=lambda o:o.get("created_at",0))
    kb = [[InlineKeyboardButton(text=f"{o['_id']} · {money(o.get('price',0))} · user {o.get('user_id')}", callback_data=f"review:{o['_id']}")] for o in rows[:20]]
    kb.append([InlineKeyboardButton(text="⬅️ Admin", callback_data="admin")])
    await safe_edit(call, "🧾 <b>PENDING ORDERS</b>\nSelect an order to review.", InlineKeyboardMarkup(inline_keyboard=kb)); await call.answer()

@dp.callback_query(F.data.startswith("review:"))
async def review_order(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Admin only.", show_alert=True); return
    oid=call.data.split(":",1)[1]; o=doc("orders",oid)
    if not o:
        await call.answer("Order not found.",show_alert=True); return
    text=(f"🧾 <b>ORDER REVIEW</b>\nID: <code>{oid}</code>\nUser: <code>{o.get('user_id')}</code>\n"
          f"Plan: {esc(o.get('plan_name'))}\nAmount: <b>{money(o.get('price',0))}</b>\n"
          f"Status: {esc(o.get('status'))}\nPayment note: {esc(o.get('payment_note') or 'None')}")
    if o.get("status") == "paid":
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📦 Deliver Hosting", callback_data=f"deliver:{oid}")], [InlineKeyboardButton(text="⬅️ Admin", callback_data="admin")]])
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Approve payment",callback_data=f"approve:{oid}"),InlineKeyboardButton(text="❌ Reject",callback_data=f"reject:{oid}")], [InlineKeyboardButton(text="⬅️ Pending",callback_data="admin_pending")]])
    await safe_edit(call,text,kb); await call.answer()

@dp.callback_query(F.data.startswith("deliver:"))
async def deliver_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Admin only.", show_alert=True); return
    oid = call.data.split(":", 1)[1]; order = doc("orders", oid)
    if not order or order.get("status") != "paid":
        await call.answer("Order paid state mein nahi hai.", show_alert=True); return
    await state.clear(); await state.set_state(DeliveryState.info); await state.update_data(delivery_order=oid)
    await call.message.answer(f"Order {oid} ke hosting details bhejein.")
    await call.answer()


@dp.callback_query(F.data.startswith("approve:"))
async def approve(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Admin only.",show_alert=True); return
    oid=call.data.split(":",1)[1]; o=doc("orders",oid)
    if not o or o.get("status")!="awaiting_payment":
        await call.answer("Order is not pending.",show_alert=True); return
    save("orders",oid,{"status":"paid","paid_at":now_ts()})
    await state.clear(); await state.set_state(DeliveryState.info); await state.update_data(delivery_order=oid)
    await call.message.answer(f"✅ Payment {oid} approved.\nAb hosting delivery details bhejein. Ye details user ko forward hongi.")
    await call.answer("Approved; send delivery details.")

@dp.message(DeliveryState.info)
async def delivery_info(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("Admin only."); return
    data=await state.get_data(); oid=data.get("delivery_order"); o=doc("orders",oid) if oid else None
    info=(message.text or message.caption or "").strip()
    if not o or not info:
        await message.answer("Order ya delivery details missing hain."); return
    expires=now_ts()+int(o.get("duration_days",30))*86400
    save("orders",oid,{"status":"delivered","delivery_info":info[:4000],"expires_at":expires})
    await state.clear()
    try:
        await bot.send_message(int(o["user_id"]),f"🎉 <b>HOSTING DETAILS</b>\nOrder: <code>{oid}</code>\nPlan: <b>{esc(o.get('plan_name'))}</b>\nExpires: <b>{fmt_time(expires)}</b>\n\n<pre>{esc(info[:3500])}</pre>\nKeep credentials private.")
    except Exception:
        log.exception("Delivery message failed")
    await message.answer(f"✅ Order {oid} delivered.",reply_markup=admin_kb())

@dp.callback_query(F.data.startswith("reject:"))
async def reject(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Admin only.",show_alert=True); return
    oid=call.data.split(":",1)[1]; o=doc("orders",oid)
    if not o or o.get("status")!="awaiting_payment":
        await call.answer("Order is not pending.",show_alert=True); return
    save("orders",oid,{"status":"payment_rejected"})
    try:
        await bot.send_message(int(o["user_id"]),f"❌ Order <code>{oid}</code> ka payment verify nahi hua. {esc(ADMIN_CONTACT)} se contact karein.")
    except Exception: pass
    await safe_edit(call,f"❌ Order <code>{oid}</code> rejected.",admin_kb()); await call.answer("Rejected.")

@dp.callback_query(F.data == "admin_orders")
async def admin_orders(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Admin only.",show_alert=True); return
    rows=sorted(all_docs("orders"),key=lambda o:o.get("created_at",0),reverse=True)[:20]
    lines=["📋 <b>RECENT ORDERS</b>"]
    for o in rows:
        lines.append(f"\n<code>{o['_id']}</code> · {esc(o.get('plan_name'))}\nUser: <code>{o.get('user_id')}</code> · {money(o.get('price',0))}\nStatus: <b>{esc(o.get('status'))}</b>")
    await safe_edit(call,"\n".join(lines),back_kb()); await call.answer()

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Admin only.",show_alert=True); return
    users=len(all_docs("users")); plans=sum(1 for p in all_docs("plans") if p.get("active"))
    orders=all_docs("orders"); pending=sum(1 for o in orders if o.get("status")=="awaiting_payment")
    sales=sum(float(o.get("price",0)) for o in orders if o.get("status") in ("paid","delivered","active","expired"))
    await safe_edit(call,f"📊 <b>STATISTICS</b>\nUsers: {users}\nActive plans: {plans}\nOrders: {len(orders)}\nPending payments: {pending}\nVerified sales: {money(sales)}",admin_kb()); await call.answer()

@dp.callback_query(F.data == "admin_tickets")
async def admin_tickets(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Admin only.",show_alert=True); return
    rows=[t for t in all_docs("tickets") if t.get("status")=="open"]
    kb=[[InlineKeyboardButton(text=f"Ticket {t['_id']} · user {t.get('user_id')}",callback_data=f"ticket_view:{t['_id']}")] for t in rows[:20]]
    kb.append([InlineKeyboardButton(text="⬅️ Admin",callback_data="admin")])
    await safe_edit(call,"🎫 <b>OPEN TICKETS</b>",InlineKeyboardMarkup(inline_keyboard=kb)); await call.answer()

@dp.callback_query(F.data.startswith("ticket_view:"))
async def ticket_view(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Admin only.",show_alert=True); return
    tid=call.data.split(":",1)[1]; t=doc("tickets",tid)
    if not t:
        await call.answer("Ticket not found.",show_alert=True); return
    await safe_edit(call,f"🎫 <b>TICKET {tid}</b>\nUser: <code>{t.get('user_id')}</code>\n\n{esc(t.get('message'))}",
        InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Reply",callback_data=f"ticket_reply:{tid}"),InlineKeyboardButton(text="✅ Close",callback_data=f"ticket_close:{tid}")],[InlineKeyboardButton(text="⬅️ Tickets",callback_data="admin_tickets")]]))
    await call.answer()

@dp.callback_query(F.data.startswith("ticket_reply:"))
async def ticket_reply_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Admin only.",show_alert=True); return
    tid=call.data.split(":",1)[1]; t=doc("tickets",tid)
    if not t:
        await call.answer("Ticket not found.",show_alert=True); return
    await state.clear(); await state.set_state(SupportState.message)
    await state.update_data(mode="ticket_reply",ticket_id=tid,ticket_user=t.get("user_id"))
    await call.message.answer(f"Ticket {tid} ka reply bhejein."); await call.answer()

@dp.callback_query(F.data.startswith("ticket_close:"))
async def ticket_close(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Admin only.",show_alert=True); return
    tid=call.data.split(":",1)[1]; save("tickets",tid,{"status":"closed"})
    await safe_edit(call,f"Ticket {tid} closed.",admin_kb()); await call.answer()

@dp.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Action cancel kar diya.",reply_markup=main_kb(is_admin(message.from_user.id)))

@dp.message()
async def fallback(message: Message, state: FSMContext):
    if await state.get_state():
        await message.answer("Current step ka valid input bhejein, ya /cancel karke dobara start karein.")
        return
    user_upsert(message.from_user)
    if not bot_enabled() and not is_admin(message.from_user.id):
        await message.answer("🛠 Bot maintenance mein hai."); return
    await message.answer("Menu se option choose karein ya /help type karein.",reply_markup=main_kb(is_admin(message.from_user.id)))

async def main():
    seed_plans()
    log.info("Starting %s with Firebase Firestore", APP_NAME)
    await dp.start_polling(bot,allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt,SystemExit):
        log.info("Bot stopped.")
