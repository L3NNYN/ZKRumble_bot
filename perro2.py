import logging
import secrets
import hashlib
import hmac
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# --- Configuración ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

EE_SECRET_KEY = "aG9sYWNhaXN0ZWVubGF0cmFtcGE"
TOKEN_BOT = "7544786769:AAGoRrdjgfHul35Fe7PxIM9vcl6UGtERH0U"
VARIATIONS = [
    "Rock, Paper, Scissors, Fire, Well",
    "Rock, Paper, Scissors, Lizard, Spock",
    "Rock, Paper, Scissors, Fire, Water"
]

# --- Parámetros ZKP (Schnorr) ---
P = 115792089237316195423570985008687907853269984665640564039457584007908834671663
G = 2

# --- Estructuras de datos ---
players = {}          # user_id: {anon_id, mac_key, mac_credential, zkp_t, zkp_s}
votes = {}            # anon_id: {commitment, voto, nonce, mac}
pending_votes = set() # user_id en proceso de votación

# --- Funciones criptográficas ---
def generate_anon_id(user_id: str) -> str:
    return hmac.new(EE_SECRET_KEY.encode(), user_id.encode(), hashlib.sha256).hexdigest()

def generate_mac(key: str, message: str) -> str:
    return hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()

def create_commitment(message: str, nonce: str) -> str:
    return hashlib.sha256(f"{message}{nonce}".encode()).hexdigest()

def generate_zk_proof(mac: str, secret: str) -> tuple:
    r = secrets.randbelow(P-1) + 1
    t = pow(G, r, P)
    c = int(hashlib.sha256(f"{t}{mac}".encode()).hexdigest(), 16) % P
    s = (r + c * int(mac, 16)) % (P-1)
    return (t, s)

def verify_zk_proof(t: int, s: int, mac_credential: str) -> bool:
    c = int(hashlib.sha256(f"{t}{mac_credential}".encode()).hexdigest(), 16) % P
    left = pow(G, s, P)
    right = (t * pow(int(mac_credential, 16), c, P)) % P
    return left == right

# --- Comandos del Bot ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id in players:
        await update.message.reply_text("✅ Ya estás registrado.")
        return

    # 1. Generar credenciales
    anon_id = generate_anon_id(user_id)
    mac_key = secrets.token_hex(16)
    mac_credential = generate_mac(EE_SECRET_KEY, f"{anon_id}||jugador_valido")

    # 2. Generar y almacenar ZKP
    t, s = generate_zk_proof(mac_credential, secrets.token_hex(16))
    
    players[user_id] = {
        "anon_id": anon_id,
        "mac_key": mac_key,
        "mac_credential": mac_credential,
        "zkp_t": t,  # Almacenar t
        "zkp_s": s   # Almacenar s
    }

    await update.message.reply_text(
        "🎉 **Registro exitoso**\n"
        f"ID Anónimo: `{anon_id[:8]}...`\n"
        "Usa /vote para votar (se verificará tu credencial)."
    )

async def vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    
    # 1. Verificar registro
    if user_id not in players:
        await update.message.reply_text("❌ Primero regístrate con /start")
        return

    # 2. Obtener y verificar ZKP almacenado
    player_data = players[user_id]
    t = player_data.get("zkp_t")
    s = player_data.get("zkp_s")
    mac_credential = player_data["mac_credential"]

    if t is None or s is None or not verify_zk_proof(t, s, mac_credential):
        await update.message.reply_text("❌ Credencial inválida. Usa /start para regenerarla.")
        return

    # 3. Mostrar opciones de voto
    keyboard = [[v] for v in VARIATIONS]
    markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    await update.message.reply_text(
        "🗳️ **Elige la variante para el torneo:**",
        reply_markup=markup
    )
    pending_votes.add(user_id)

async def handle_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in pending_votes:
        return

    voto = update.message.text
    if voto not in VARIATIONS:
        await update.message.reply_text("❌ Opción inválida. Usa /vote")
        return

    # 1. Generar commitment y MAC
    nonce = secrets.token_hex(16)
    player_data = players[user_id]
    commitment = create_commitment(voto, nonce)
    mac = generate_mac(player_data["mac_key"], f"{voto}{nonce}")

    # 2. Almacenar voto
    votes[player_data["anon_id"]] = {
        "commitment": commitment,
        "voto": voto,
        "nonce": nonce,
        "mac": mac
    }

    pending_votes.remove(user_id)
    await update.message.reply_text(
        "🔒 **Voto registrado**\n"
        f"Commitment: `{commitment[:8]}...`\n"
        "Usa /results para ver los resultados."
    )

async def results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not votes:
        await update.message.reply_text("📭 No hay votos registrados.")
        return

    # Verificar y contar votos válidos
    resultados = {}
    for anon_id, vote_data in votes.items():
        # Verificar commitment
        recalculated = create_commitment(vote_data["voto"], vote_data["nonce"])
        if recalculated != vote_data["commitment"]:
            logging.warning(f"⚠️ Commitment inválido para {anon_id[:8]}...")
            continue

        # Verificar MAC
        player_id = next(uid for uid, p in players.items() if p["anon_id"] == anon_id)
        valid_mac = generate_mac(players[player_id]["mac_key"], f"{vote_data['voto']}{vote_data['nonce']}")
        if valid_mac != vote_data["mac"]:
            logging.warning(f"⚠️ MAC inválido para {anon_id[:8]}...")
            continue

        resultados[vote_data["voto"]] = resultados.get(vote_data["voto"], 0) + 1

    # Mostrar resultados
    if not resultados:
        await update.message.reply_text("🔍 No hay votos válidos.")
        return

    msg = "📊 **Resultados de la Votación:**\n"
    for variante, count in resultados.items():
        msg += f"• {variante}: {count} voto(s)\n"
    
    ganadora = max(resultados.items(), key=lambda x: x[1])[0]
    msg += f"\n🎉 **Variante seleccionada:** {ganadora}"
    await update.message.reply_text(msg)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
    🤖 **Comandos Disponibles:**
    /start - Registro anónimo en el torneo
    /vote - Votar por la variante del juego
    /results - Mostrar resultados de la votación
    """
    await update.message.reply_text(help_text)

# --- Main ---
def main():
    app = ApplicationBuilder().token(TOKEN_BOT).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("vote", vote))
    app.add_handler(CommandHandler("results", results))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_vote))
    
    logging.info("Bot iniciado...")
    app.run_polling()

if __name__ == "__main__":
    main()