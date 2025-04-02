import logging
import random
import hashlib
import hmac
import base64
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

# Configuración del log
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# -------------------
# Clave secreta del bot para MACs
# -------------------
BOT_SECRET_KEY = b"aG9sYWNhaXN0ZWVubGF0cmFtcGE="

# -------------------
# Almacenamiento temporal en memoria
# -------------------
registered_users = {}  # user_id: attr_hash
issued_credentials = {}  # attr_hash: credential

# -------------------
# Función para generar MAC
# -------------------
def generate_mac(attr_hash: str) -> str:
    mac = hmac.new(BOT_SECRET_KEY, attr_hash.encode(), hashlib.sha256).digest()
    return base64.b64encode(mac).decode()

# -------------------
# Comandos del bot
# -------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id in registered_users:
        await update.message.reply_text("Ya estás registrado.")
        return

    # Generar attr_hash usando user_id + timestamp
    timestamp = str(random.randint(100000, 999999))
    raw_attr = f"{user_id}:{timestamp}"
    attr_hash = hashlib.sha256(raw_attr.encode()).hexdigest()

    # Generar credencial (MAC)
    credential = generate_mac(attr_hash)

    # Guardar registro anónimo
    registered_users[user_id] = attr_hash
    issued_credentials[attr_hash] = credential

    await update.message.reply_text(
        f"✅ Registro exitoso.\nTu credencial anónima es:\n\n"
        f"attr_hash: {attr_hash}\n"
        f"credential: {credential}\n\n"
        "Guarda esta información. La necesitarás para votar o reclamar el premio."
    )

async def validate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("Uso: /validate <attr_hash> <credential>")
        return

    attr_hash, credential = args
    expected = generate_mac(attr_hash)

    if hmac.compare_digest(expected, credential):
        await update.message.reply_text("✅ Credenciales válidas. Puedes participar en el torneo.")
    else:
        await update.message.reply_text("❌ Credenciales inválidas. Verifica tu attr_hash y credential.")

# -------------------
# Main
# -------------------
def main():
    app = ApplicationBuilder().token("7952957091:AAEZyHmENpZ9TXqW8RaQYFYKiGVE0ZNh914").build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("validate", validate))

    print("🤖 Bot corriendo...")
    app.run_polling()

if __name__ == '__main__':
    main()
