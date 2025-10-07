import os
import io
import asyncio
import sqlite3
from typing import Tuple, Dict, Any
from PIL import Image, ImageDraw, ImageFont

from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.enums import ParseMode, ChatAction
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.client.default import DefaultBotProperties

bot_token = ""
admin_id = None

text_color_hex = "#EDEFEA"
dpi = 72

fonts: Dict[str, str] = {
    "OpenSans-Regular":  "fonts/OpenSans-Regular.ttf",
    "OpenSans-SemiBold": "fonts/OpenSans-SemiBold.ttf",
}

templates: Dict[str, Dict[str, Any]] = {
    "v1": {
        "png": "templates/v1.png",
        "overlay": None,
        "fields": {
            "NAME":       {"topleft": (129.72, 606.8), "font": "OpenSans-SemiBold", "size_pt": 18.21, "angle_deg": 0.0},
            "ACCOUNT":    {"topleft": (120.81, 703.1), "font": "OpenSans-Regular",  "size_pt": 15.65, "angle_deg": 0.0},
            "EXPIRATION": {"topleft": (472.81, 705.1), "font": "OpenSans-Regular",  "size_pt": 15.65, "angle_deg": 0.0},
        },
    },
    "v2": {
        "png": "templates/v2.png",
        "overlay": None,
        "fields": {
            "NAME":       {"topleft": (155.65, 616.18), "font": "OpenSans-SemiBold", "size_pt": 15.69, "angle_deg": 0.0},
            "ACCOUNT":    {"topleft": (140.03, 700.46), "font": "OpenSans-Regular",  "size_pt": 15.14, "angle_deg": 0.0},
            "EXPIRATION": {"topleft": (482.4,  700.72), "font": "OpenSans-Regular",  "size_pt": 15.14, "angle_deg": 0.0},
        },
    },
    "v3": {
        "png": "templates/v3.png",
        "overlay": None,
        "fields": {
            "NAME":       {"topleft": (120.05, 653.75), "font": "OpenSans-SemiBold", "size_pt": 18.14, "angle_deg": -5.00},
            "ACCOUNT":    {"topleft": (82.95,  760.48), "font": "OpenSans-Regular",  "size_pt": 17.26, "angle_deg": -5.08},
            "EXPIRATION": {"topleft": (472.41, 794.60), "font": "OpenSans-Regular",  "size_pt": 17.26, "angle_deg": -5.93},
        },
    },
    "v4": {
        "png": "templates/v4.png",
        "overlay": {
            "path": "templates/v4_overlay.png",
            "topleft": (115, 463),
        },
        "fields": {
            "NAME":       {"topleft": (155.65, 616.18), "font": "OpenSans-Regular", "size_pt": 15.69, "angle_deg": 0.0},
            "ACCOUNT":    {"topleft": (140.03, 700.46), "font": "OpenSans-Regular", "size_pt": 15.14, "angle_deg": 0.0},
            "EXPIRATION": {"topleft": (620.4,  700.72), "font": "OpenSans-Regular", "size_pt": 15.14, "angle_deg": 0.0},
        },
    },
}

db_path = "users.db"

router = Router()

class Form(StatesGroup):
    waiting_for_sticker_choice = State()
    waiting_for_version = State()
    waiting_for_name = State()
    waiting_for_account = State()
    waiting_for_expiration = State()

class AdminForm(StatesGroup):
    waiting_for_broadcast_media = State()

kb_start = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⚡️ Generate", callback_data="generate")]])
kb_sticker = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🧩 With sticker", callback_data="with_sticker"),
     InlineKeyboardButton(text="🧾 Without sticker", callback_data="without_sticker")]
])
kb_versions_no_sticker = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🟦 V1", callback_data="ver_v1"),
     InlineKeyboardButton(text="🟩 V2", callback_data="ver_v2"),
     InlineKeyboardButton(text="🟥 V3", callback_data="ver_v3")]
])
kb_cancel = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="cancel")]])

def init_db():
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

def add_user(user_id: int):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def get_user_count() -> int:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    (count,) = cur.fetchone()
    conn.close()
    return count

def get_all_user_ids():
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]

def pt_to_px(pt: float, dpi_val: int = dpi) -> int:
    return int(round(pt * dpi_val / 72.0))

def hex_to_rgb(h: str) -> Tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[:2], 16), int(h[2:4], 16), int(h[4:], 16)

def load_font(font_key: str, size_pt: float) -> ImageFont.FreeTypeFont:
    path = fonts.get(font_key)
    size_px = pt_to_px(size_pt * 1.50)
    try:
        return ImageFont.truetype(path, size=size_px) if path else ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()

def render_text_rgba(text: str, font: ImageFont.FreeTypeFont, color: Tuple[int, int, int]) -> Image.Image:
    probe = Image.new("L", (1, 1), 0)
    d = ImageDraw.Draw(probe)
    l, t, r, b = d.textbbox((0, 0), text, font=font)
    w, h = max(1, r - l), max(1, b - t)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d2 = ImageDraw.Draw(layer)
    alpha = int(round(255 * 0.6))
    d2.text((-l, -t), text, font=font, fill=color + (alpha,))
    return layer


def paste_rotated_at_topleft(base: Image.Image, text_layer: Image.Image, topleft_xy: Tuple[float, float], angle_deg: float):
    x, y = int(round(topleft_xy[0])), int(round(topleft_xy[1]))
    w, h = base.size
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    canvas.alpha_composite(text_layer, dest=(x, y))
    try:
        rotated = canvas.rotate(angle=angle_deg, resample=Image.BICUBIC, expand=False, center=(x, y))
    except TypeError:
        rotated = canvas.rotate(angle=angle_deg, resample=Image.BICUBIC, expand=False)
    base.alpha_composite(rotated)

def generate_image_bytes(template_key: str, name_text: str, account_text: str, expiration_text: str) -> bytes:
    if template_key not in templates:
        raise ValueError(f"Unknown template key: {template_key}")
    cfg = templates[template_key]
    base_path = cfg["png"]
    if not os.path.exists(base_path):
        raise FileNotFoundError(f"Base template not found: {base_path}")
    base = Image.open(base_path).convert("RGBA")
    color = hex_to_rgb(text_color_hex)
    values = {"NAME": name_text, "ACCOUNT": account_text, "EXPIRATION": expiration_text}
    for field_key, field_cfg in cfg["fields"].items():
        text_value = values[field_key]
        font = load_font(field_cfg["font"], field_cfg["size_pt"])
        layer = render_text_rgba(text_value, font, color)
        paste_rotated_at_topleft(base, layer, field_cfg["topleft"], field_cfg["angle_deg"])
    overlay_cfg = cfg.get("overlay")
    if overlay_cfg:
        if isinstance(overlay_cfg, dict):
            overlay_path = overlay_cfg.get("path")
            pos = overlay_cfg.get("topleft", (0, 0))
            if not overlay_path or not os.path.exists(overlay_path):
                raise FileNotFoundError(f"Overlay file not found: {overlay_path}")
            overlay_img = Image.open(overlay_path).convert("RGBA")
            base.alpha_composite(overlay_img, dest=(int(pos[0]), int(pos[1])))
        else:
            overlay_path = overlay_cfg
            if not os.path.exists(overlay_path):
                raise FileNotFoundError(f"Overlay file not found: {overlay_path}")
            overlay_img = Image.open(overlay_path).convert("RGBA")
            if overlay_img.size != base.size:
                overlay_img = overlay_img.resize(base.size, resample=Image.BICUBIC)
            base.alpha_composite(overlay_img)
    bio = io.BytesIO()
    base.convert("RGB").save(bio, "PNG")
    bio.seek(0)
    return bio.read()

@router.message(Command("start"))
async def start_cmd(m: types.Message):
    add_user(m.from_user.id)
    await m.answer("👋 <b>Welcome!</b>\nTap <b>⚡️ Generate</b> to start.", parse_mode=ParseMode.HTML, reply_markup=kb_start)

@router.callback_query(F.data == "generate")
async def generate_cb(c: types.CallbackQuery, state: FSMContext):
    await c.message.answer("🧩 Choose mode:", reply_markup=kb_sticker)
    await state.set_state(Form.waiting_for_sticker_choice)
    await c.answer()

@router.callback_query(F.data == "with_sticker", Form.waiting_for_sticker_choice)
async def with_sticker_cb(c: types.CallbackQuery, state: FSMContext):
    await state.update_data(version="v4")
    await state.set_state(Form.waiting_for_name)
    await c.message.answer("✍️ Enter full name:", reply_markup=kb_cancel)
    await c.answer()

@router.callback_query(F.data == "without_sticker", Form.waiting_for_sticker_choice)
async def without_sticker_cb(c: types.CallbackQuery, state: FSMContext):
    await state.set_state(Form.waiting_for_version)
    await c.message.answer("🎨 Select version:", reply_markup=kb_versions_no_sticker)
    await c.answer()

@router.callback_query(F.data.startswith("ver_"), Form.waiting_for_version)
async def version_cb(c: types.CallbackQuery, state: FSMContext):
    version = c.data.split("_", 1)[1]
    if version not in ("v1", "v2", "v3"):
        await c.answer("Unknown version", show_alert=True)
        return
    await state.update_data(version=version)
    await state.set_state(Form.waiting_for_name)
    await c.message.answer("✍️ Enter full name:", reply_markup=kb_cancel)
    await c.answer()

@router.callback_query(F.data == "cancel")
async def cancel_cb(c: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.answer("❌ Cancelled. Start again anytime.", reply_markup=kb_start)
    await c.answer()

@router.message(Form.waiting_for_name)
async def name_msg(m: types.Message, state: FSMContext):
    name = (m.text or "").strip()
    if not name:
        await m.reply("⚠️ Please send a valid name or press Cancel.")
        return
    add_user(m.from_user.id)
    await state.update_data(name=name)
    await state.set_state(Form.waiting_for_account)
    await m.answer("💳 Enter account text:", reply_markup=kb_cancel)

@router.message(Form.waiting_for_account)
async def account_msg(m: types.Message, state: FSMContext):
    acc = (m.text or "").strip()
    if not acc:
        await m.reply("⚠️ Please send a valid account text or press Cancel.")
        return
    await state.update_data(account=acc)
    await state.set_state(Form.waiting_for_expiration)
    await m.answer("⏳ Enter expiration text:", reply_markup=kb_cancel)

@router.message(Form.waiting_for_expiration)
async def expiration_msg(m: types.Message, state: FSMContext, bot: Bot):
    exp = (m.text or "").strip()
    if not exp:
        await m.reply("⚠️ Please send a valid expiration text or press Cancel.")
        return
    data = await state.get_data()
    version = data.get("version")
    name = data.get("name")
    account = data.get("account")
    status = await m.answer("⚙️ <i>Generating…</i>", parse_mode=ParseMode.HTML)
    try:
        loop = asyncio.get_running_loop()
        img_bytes = await loop.run_in_executor(None, generate_image_bytes, version, name, account, exp)
        await bot.send_chat_action(m.chat.id, ChatAction.UPLOAD_PHOTO)
        file = BufferedInputFile(img_bytes, filename=f"{version}.png")
        await m.answer_photo(file, caption=f"✅ Done • {version.upper()} • {'🧩 Sticker' if version=='v4' else '🧾 No sticker'}")
        await status.delete()
    except Exception as e:
        await status.edit_text(f"❌ Generation failed: {e}")
    finally:
        await state.clear()

@router.message(Command("admin"))
async def admin_cmd(m: types.Message):
    if admin_id and m.from_user.id != admin_id:
        await m.reply("⛔ Unauthorized.")
        return
    count = get_user_count()
    await m.reply(f"🛠 Admin Panel\n👥 Users: {count}\n\n📢 /broadcast <text>\n🖼️ /broadcast_media")

@router.message(Command("broadcast"))
async def broadcast_cmd(m: types.Message):
    if admin_id and m.from_user.id != admin_id:
        await m.reply("⛔ Unauthorized.")
        return
    parts = m.text.split(" ", 1)
    if len(parts) < 2 or not parts[1].strip():
        await m.reply("Usage: /broadcast <text>")
        return
    msg = parts[1].strip()
    user_ids = get_all_user_ids()
    sent = 0
    failed = 0
    for uid in user_ids:
        try:
            await m.bot.send_message(uid, msg)
            sent += 1
            await asyncio.sleep(0.03)
        except Exception:
            failed += 1
    await m.reply(f"📡 Broadcast done\n✅ Sent: {sent}\n⚠️ Failed: {failed}")

@router.message(Command("broadcast_media"))
async def broadcast_media_start(m: types.Message, state: FSMContext):
    if admin_id and m.from_user.id != admin_id:
        await m.reply("⛔ Unauthorized.")
        return
    await state.set_state(AdminForm.waiting_for_broadcast_media)
    await m.reply("📸 Send the media to broadcast (photo/video/document) with optional caption.")

@router.message(AdminForm.waiting_for_broadcast_media)
async def broadcast_media_receive(m: types.Message, state: FSMContext):
    if admin_id and m.from_user.id != admin_id:
        await m.reply("⛔ Unauthorized.")
        return
    user_ids = get_all_user_ids()
    sent = 0
    failed = 0
    for uid in user_ids:
        try:
            await m.bot.copy_message(chat_id=uid, from_chat_id=m.chat.id, message_id=m.message_id)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1
    await state.clear()
    await m.reply(f"📡 Media broadcast done\n✅ Sent: {sent}\n⚠️ Failed: {failed}")

@router.message()
async def fallback_msg(m: types.Message):
    add_user(m.from_user.id)
    await m.reply("ℹ️ Use /start to begin.", reply_markup=kb_start)

async def main():
    init_db()
    bot = Bot(bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
