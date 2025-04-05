import logging
import os
import secrets
import hashlib
import hmac
import random
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

# Configuración criptográfica
EE_SECRET_KEY = "aG9sYWNhaXN0ZWVubGF0cmFtcGE"
TOKEN_BOT = "7544786769:AAGoRrdjgfHul35Fe7PxIM9vcl6UGtERH0U"
VARIATIONS = [
    "Rock, Paper, Scissors, Fire, Well",
    "Rock, Paper, Scissors, Lizard, Spock",
    "Rock, Paper, Scissors, Fire, Water"
]
SELECTED_VARIATION = None  # Variante ganadora seleccionada

# --- Estado del torneo ---
MIN_PLAYERS = 2
players = {}  # user_id: {...}
votes = {}    # anon_id: {...}
selected_variation = None
bracket = []
current_matches = []
match_results = {}
plays = {}  # anon_id: play

# --- Reglas de Rock, Paper, Scissors, Fire, Well ---
defeats = {
    "Rock":     ["Scissors", "Fire"],
    "Paper":    ["Rock", "Well"],
    "Scissors": ["Paper", "Fire"],
    "Fire":     ["Paper", "Well"],
    "Well":     ["Rock", "Scissors"]
}

# --- Criptografía ---
P = 115792089237316195423570985008687907853269984665640564039457584007908834671663
G = 2

def generate_anon_id(user_id: str) -> str:
    return hmac.new(EE_SECRET_KEY.encode(), str(user_id).encode(), hashlib.sha256).hexdigest()

def generate_mac(key: str, message: str) -> str:
    return hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()

def generate_zk_proof(secret: int) -> tuple:
    r = secrets.randbelow(P - 1)
    t = pow(G, r, P)
    c = int(hashlib.sha256(f"{t}".encode()).hexdigest(), 16) % P
    s = (r + c * secret) % (P - 1)
    return (t, s)

def verify_zk_proof(proof: tuple, public_key: int) -> bool:
    t, s = proof
    c = int(hashlib.sha256(f"{t}".encode()).hexdigest(), 16) % P
    left = pow(G, s, P)
    right = (t * pow(public_key, c, P)) % P
    return left == right

# --- Bot Commands ---
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not bracket:
        await update.message.reply_text("📋 El torneo aún no ha comenzado.")
        return

    msg = "🔍 Estado actual del torneo:"
    for i, (a1, a2) in enumerate(current_matches, 1):
        msg += f"Match {i}: {a1[:6]} vs {a2[:6]} "
    await update.message.reply_text(msg if current_matches else "✅ No hay emparejamientos pendientes. Esperando jugadas.")
async def claim_trophie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in players:
        await update.message.reply_text("❌ No estás registrado.")
        return

    player = players[user_id]
    secret = player["secret"]
    pubkey = player["public_key"]
    anon_id = player["anon_id"]
    proof = generate_zk_proof(secret)

    if not verify_zk_proof(proof, pubkey):
        await update.message.reply_text("🔐 No se pudo verificar tu identidad.")
        return

    # Verificar si el jugador fue el último ganador
    finalistas = list(match_results.values())
    if len(finalistas) == 1 and finalistas[0] == anon_id:
        await update.message.reply_text(f"🏅 Felicidades {anon_id[:6]}! Has reclamado tu trofeo con éxito.")
    else:
        await update.message.reply_text("❌ No eres el ganador del torneo o ya se reclamó el premio.")
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in players:
        await update.message.reply_text("✅ Ya estás registrado.")
        return

    anon_id = generate_anon_id(str(user_id))
    mac_key = secrets.token_hex(32)
    secret = secrets.randbelow(P - 1)
    public_key = pow(G, secret, P)

    players[user_id] = {
        "anon_id": anon_id,
        "mac_key": mac_key,
        "secret": secret,
        "public_key": public_key
    }

    await update.message.reply_text("🎉 Registro completo. Esperando votación de modalidad.")

async def vote_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in players:
        await update.message.reply_text("❌ Regístrate con /start")
        return

    proof = generate_zk_proof(players[user_id]["secret"])
    if not verify_zk_proof(proof, players[user_id]["public_key"]):
        await update.message.reply_text("🔐 Autenticación fallida")
        return

    keyboard = [[v] for v in VARIATIONS]
    markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    await update.message.reply_text("Elige la modalidad:", reply_markup=markup)

async def handle_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global selected_variation, SELECTED_VARIATION

    user_id = update.effective_user.id
    if user_id not in players:
        return

    vote = update.message.text
    if vote not in VARIATIONS:
        await update.message.reply_text("❌ Opción inválida")
        return

    anon_id = players[user_id]["anon_id"]
    nonce = secrets.token_hex(16)
    mac = generate_mac(players[user_id]["mac_key"], f"{vote}{nonce}")

    votes[anon_id] = {"vote": vote, "nonce": nonce, "mac": mac}

    total = len(players)
    actuales = len(votes)
    await update.message.reply_text(f"✅ Voto registrado ({actuales}/{total})")
    if actuales < MIN_PLAYERS:
        await update.message.reply_text(f"🕐 Aún no se alcanza el mínimo de jugadores requeridos ({MIN_PLAYERS}).")

    if actuales >= MIN_PLAYERS and actuales == total:
        resultados = {}
        for v in votes.values():
            resultados[v["vote"]] = resultados.get(v["vote"], 0) + 1
        selected_variation = max(resultados.items(), key=lambda x: x[1])[0]
        SELECTED_VARIATION = selected_variation
        await update.message.reply_text(f"🎮 Variante seleccionada: {selected_variation} Preparando el torneo automáticamente...")
        await iniciar_torneo(context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
🤖 Comandos disponibles:
/start - Registro anónimo con credenciales
/vote_mode - Votar por la modalidad del torneo
/play <jugada> - Enviar jugada en tu turno
/claim_trophie - Reclamar el trofeo si ganaste
/status - Ver el estado actual del torneo
/help - Mostrar esta ayuda
    """
    await update.message.reply_text(help_text)

async def iniciar_torneo(context):
    global bracket, current_matches, match_results, plays

    if SELECTED_VARIATION != "Rock, Paper, Scissors, Fire, Well":
        for user_id in players:
            await context.bot.send_message(chat_id=user_id, text="🛑 Solo se ha implementado 'Rock, Paper, Scissors, Fire, Well'.")
        return

    if len(players) % 2 != 0:
        for user_id in players:
            await context.bot.send_message(chat_id=user_id, text="⏳ Esperando número par de jugadores para iniciar el torneo.")
        return

    anon_ids = [p["anon_id"] for p in players.values()]
    random.shuffle(anon_ids)
    bracket = [(anon_ids[i], anon_ids[i+1]) for i in range(0, len(anon_ids), 2)]
    current_matches = bracket[:]
    match_results.clear()
    plays.clear()

    for user_id in players:
        await context.bot.send_message(chat_id=user_id, text="🏁 ¡El torneo ha comenzado! Realiza tu jugada con /move <opción> (Rock, Paper, etc.)")

async def move(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in players:
        await update.message.reply_text("❌ No estás registrado.")
        return

    try:
        jugada = context.args[0].capitalize()
    except:
        await update.message.reply_text("Uso: /play <jugada>")
        return

    if jugada not in defeats:
        await update.message.reply_text("❌ Jugada inválida")
        return

    anon_id = players[user_id]["anon_id"]
    plays[anon_id] = jugada

    for a1, a2 in current_matches:
        if a1 in plays and a2 in plays:
            j1, j2 = plays[a1], plays[a2]
            if j2 in defeats[j1]:
                ganador = a1
            elif j1 in defeats[j2]:
                ganador = a2
            else:
                await update.message.reply_text(f"🤝 Empate entre {a1[:6]} y {a2[:6]}. Vuelvan a jugar.")
                plays.pop(a1)
                plays.pop(a2)
                return
            match_results[(a1, a2)] = ganador
            current_matches.remove((a1, a2))
            await update.message.reply_text(f"🎉 Resultado: {j1} vs {j2} Ganador: {ganador[:6]}")
            break

    if not current_matches:
        if len(match_results) == 1:
            finalista = list(match_results.values())[0]
            await update.message.reply_text(f"🏆 El ganador del torneo es: {finalista[:6]} Usa /claim_trophie para reclamar tu premio.")
        else:
            siguiente_ronda = list(match_results.values())
            random.shuffle(siguiente_ronda)
            bracket.clear()
            current_matches.clear()
            match_results.clear()
            plays.clear()
            bracket.extend([(siguiente_ronda[i], siguiente_ronda[i+1]) for i in range(0, len(siguiente_ronda), 2)])
            current_matches.extend(bracket)
            for user_id in players:
                await context.bot.send_message(chat_id=user_id, text="➡️ Nueva ronda comenzada. Usa /play <jugada> para participar.")

# --- Main ---
def main():
    app = ApplicationBuilder().token(TOKEN_BOT).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("vote_mode", vote_mode))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("claim_trophie", claim_trophie))
    app.add_handler(CommandHandler("play", move))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_vote))
    app.run_polling()

if __name__ == "__main__":
    main()
