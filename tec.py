import logging
import random
import hashlib
from telegram import Update, ReplyKeyboardMarkup
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
# Datos en memoria (prototipo)
# -------------------
players = {}  # user_id: {"commitment": str, "secret": str, ...}
votes_pending = {}  # user_id: esperando respuesta de votación
variations = [
    "Rock, Paper, Scissors, Fire, Well",
    "Rock, Paper, Scissors, Lizard, Spock",
    "Rock, Paper, Scissors, Fire, Water"
]

# -------------------
# Utilidades criptográficas
# -------------------
def create_commitment(secret: str, nonce: str) -> str:
    return hashlib.sha256((secret + nonce).encode()).hexdigest()

# -------------------
# Comandos
# -------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    if user_id in players:
        await update.message.reply_text("Ya estás registrado.")
        return

    secret = str(random.randint(100000, 999999))
    nonce = str(random.randint(100000, 999999))
    commitment = create_commitment(secret, nonce)

    players[user_id] = {
        "commitment": commitment,
        "secret": secret,
        "nonce": nonce
    }

    await update.message.reply_text(
        f"¡Bienvenido al torneo, {user.first_name}!\n"
        "Tu identidad ha sido registrada de forma anónima."
    )

async def vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in players:
        await update.message.reply_text("Primero debes registrarte con /start")
        return

    keyboard = [[v] for v in variations]
    markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("Elige tu variación favorita del juego:", reply_markup=markup)

    votes_pending[user_id] = True

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if user_id not in votes_pending:
        return

    if text not in variations:
        await update.message.reply_text("Opción inválida. Usa /vote para ver las opciones.")
        return

    nonce = str(random.randint(10000, 99999))
    vote_commit = create_commitment(text, nonce)

    players[user_id]["vote_commitment"] = vote_commit
    players[user_id]["vote_nonce"] = nonce
    players[user_id]["vote_plain"] = text

    votes_pending.pop(user_id)
    await update.message.reply_text("Tu voto ha sido registrado de forma anónima.")

async def reveal_votes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    results = {}
    for player in players.values():
        vote = player.get("vote_plain")
        if vote:
            results[vote] = results.get(vote, 0) + 1

    if not results:
        await update.message.reply_text("Aún no hay votos registrados.")
        return

    text = "📊 Resultados de la votación:\n"
    for var, count in results.items():
        text += f"• {var}: {count} votos\n"

    await update.message.reply_text(text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "/start - Registra al usuario en el torneo con una identidad anónima\n"
        "/vote - Inicia el proceso de votación por una variación del juego\n"
        "/reveal_votes - Muestra los resultados actuales de la votación\n"
        "/play - Realiza una jugada en una ronda del torneo (cuando sea tu turno)\n"
        "/reveal - Revela tu jugada después del compromiso\n"
        "/status - Consulta el estado actual del torneo y tus enfrentamientos\n"
        "/claim - Reclama el premio final si ganaste el torneo\n"
        "/help - Muestra todos los comandos disponibles y cómo funciona el torneo"
    )
    await update.message.reply_text(help_text)

# -------------------
# Main
# -------------------
def main():
    app = ApplicationBuilder().token("7952957091:AAEZyHmENpZ9TXqW8RaQYFYKiGVE0ZNh914").build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("vote", vote))
    app.add_handler(CommandHandler("reveal_votes", reveal_votes))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("🤖 Bot corriendo...")
    app.run_polling()

if __name__ == '__main__':
    main()