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
pending_reveals = {}  # anon_id: {'commitment': str, 'move': str, 'nonce': str}
reveals = {}          # anon_id: {'move': str, 'nonce': str}
victory_commits = {}  # anon_id: [H(1||nonce) or H(0||nonce)]

# --- Alias de animales para jugadores ---
aliases = [
    ("Caballo Loco", "🐴"),
    ("Gato Ninja", "🐱"),
    ("Perro Valiente", "🐶"),
    ("Tortuga Zen", "🐢"),
    ("Águila Real", "🦅"),
    ("Mono Alegre", "🐵"),
    ("Tiburón Azul", "🦈"),
    ("Zorro Astuto", "🦊")
]
assigned_aliases = {}  # user_id: (nombre, emoji)


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

# --- Comando /status usando alias ---
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not bracket:
        await update.message.reply_text("📋 El torneo aún no ha comenzado.")
        return

    msg = "🔍 Estado actual del torneo:\n"
    for i, (a1, a2) in enumerate(current_matches, 1):
        alias1 = get_alias_from_anon(a1)
        alias2 = get_alias_from_anon(a2)
        msg += f"Match {i}: {alias1} vs {alias2}\n"

    await update.message.reply_text(msg if current_matches else "✅ No hay emparejamientos pendientes. Esperando jugadas.")

# --- Función para mostrar alias dado un anon_id ---
async def anunciar_enfrentamientos(context):
    for a1, a2 in current_matches:
        alias1 = get_alias_from_anon(a1)
        alias2 = get_alias_from_anon(a2)
        for uid, pdata in players.items():
            if pdata["anon_id"] in (a1, a2):
                await context.bot.send_message(
                    chat_id=uid,
                    text=f"🎮 Tu oponente es: {alias2 if pdata['anon_id'] == a1 else alias1} ¡Prepara tu jugada con /play <opción>!")


# --- Implementación básica de Pedersen Commitment ---
P_PEDERSEN = 208351617316091241234326746312124448251235562226470491514186331217050270460481
G_PEDERSEN = 2
H_PEDERSEN = 3  # Otro generador del grupo

# Simulación de Pedersen commitment: C = g^m * h^r mod p

def pedersen_commit(value: int, r: int) -> int:
    return (pow(G_PEDERSEN, value, P_PEDERSEN) * pow(H_PEDERSEN, r, P_PEDERSEN)) % P_PEDERSEN

async def claim_trophie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in players:
        await update.message.reply_text("❌ No estás registrado.")
        return

    anon_id = players[user_id]["anon_id"]
    victories = victory_commits.get(anon_id, [])
    valid_proofs = []

    for item in victories:
        if isinstance(item, tuple) and len(item) == 2:
            commitment, r = item
        else:
            continue  # Skip malformed entries
        expected = pedersen_commit(1, r)
        if commitment == expected:
            valid_proofs.append(commitment)

    if not valid_proofs:
        await update.message.reply_text("😕 No se encontraron pruebas de victoria para reclamar el trofeo.")
        return

    count = len(valid_proofs)
    nombre, emoji = assigned_aliases.get(user_id, ("Jugador", "❓"))

    if count >= 1:  # Puedes ajustar este valor según el tamaño del torneo
        await update.message.reply_text(f"🏆 Felicidades {nombre} {emoji}! Has ganado el torneo con {count} victoria(s) verificadas.")
    else:
        await update.message.reply_text(f"📉 {nombre} {emoji}, aún no has acumulado suficientes victorias para reclamar el trofeo.")

# --- Al registrar el jugador (/start) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in players:
        nombre, emoji = assigned_aliases[user_id]
        await update.message.reply_text(f"✅ Ya estás registrado como {nombre} {emoji}.")
        return

    # Asignar alias único
    available = [a for a in aliases if a not in assigned_aliases.values()]
    if not available:
        await update.message.reply_text("❌ No hay alias disponibles.")
        return
    alias = random.choice(available)
    assigned_aliases[user_id] = alias

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

    nombre, emoji = alias
    await update.message.reply_text(f"🎉 Bienvenido {nombre} {emoji}! \nUsa /vote_mode para elegir la modalidad del torneo.")

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
/reveal - Revelar jugada
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
    await anunciar_enfrentamientos(context)
    match_results.clear()
    plays.clear()

    for user_id in players:
        await context.bot.send_message(chat_id=user_id, text="🏁 ¡El torneo ha comenzado! Realiza tu jugada con /play <opción> (Rock, Paper, etc.)")

async def play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in players:
        await update.message.reply_text("❌ No estás registrado.")
        return

    try:
        move = context.args[0].capitalize()
    except:
        await update.message.reply_text("Uso: /play <jugada>")
        return

    if move not in defeats:
        await update.message.reply_text("❌ Jugada inválida")
        return

    nonce = secrets.token_hex(8)
    commitment = hashlib.sha256(f"{move}{nonce}".encode()).hexdigest()
    anon_id = players[user_id]["anon_id"]

    pending_reveals[anon_id] = {
        "commitment": commitment,
        "move": move,
        "nonce": nonce
    }

    # Notificar si ambos han jugado
    for a1, a2 in current_matches:
        if anon_id in (a1, a2):
            opponent = a2 if a1 == anon_id else a1
            if opponent in pending_reveals:
                for uid in players:
                    if players[uid]["anon_id"] in (a1, a2):
                        await context.bot.send_message(chat_id=uid, text="🔓 Ambos jugadores han hecho su jugada. Usa /reveal <jugada> <nonce> para revelar.")
            break

    await update.message.reply_text(f"🔒 Jugada registrada.\nCommitment: {commitment[:6]}...\nGuarda este nonce para el reveal: `{nonce}`")

def generate_victory_commitment():
    r = secrets.randbelow(P_PEDERSEN)
    commitment = pedersen_commit(1, r)
    return commitment, r

async def reveal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in players:
        await update.message.reply_text("❌ No estás registrado.")
        return

    try:
        move = context.args[0].capitalize()
        nonce = context.args[1]
    except:
        await update.message.reply_text("Uso: /reveal <jugada> <nonce>")
        return

    anon_id = players[user_id]["anon_id"]
    stored = pending_reveals.get(anon_id)
    if not stored:
        await update.message.reply_text("❌ No se encontró una jugada previa.")
        return

    expected = stored["commitment"]
    actual = hashlib.sha256(f"{move}{nonce}".encode()).hexdigest()
    if actual != expected:
        await update.message.reply_text("🚫 La jugada no coincide con el compromiso enviado.")
        return

    reveals[anon_id] = {"move": move, "nonce": nonce}

    for a1, a2 in current_matches:
        if anon_id in (a1, a2) and a1 in reveals and a2 in reveals:
            j1, j2 = reveals[a1]["move"], reveals[a2]["move"]
            uid1 = next(uid for uid, p in players.items() if p["anon_id"] == a1)
            uid2 = next(uid for uid, p in players.items() if p["anon_id"] == a2)
            result = f"{j1} vs {j2}\n"

            if j2 in defeats[j1]:
                winner = a1
                commitment, r = generate_victory_commitment()
                victory_commits.setdefault(winner, []).append((commitment, r))
            elif j1 in defeats[j2]:
                winner = a2
                commitment, r = generate_victory_commitment()
                victory_commits.setdefault(winner, []).append((commitment, r))
            else:
                await update.message.reply_text("🤝 Empate. Vuelvan a jugar.")
                reveals.pop(a1)
                reveals.pop(a2)
                return

            match_results[(a1, a2)] = winner
            current_matches.remove((a1, a2))

            for uid in [uid1, uid2]:
                await context.bot.send_message(chat_id=uid, text=f"🎮 Resultado: {get_alias_from_anon(a1)} vs {get_alias_from_anon(a2)} 🏆 Ganador: {get_alias_from_anon(winner)}")
            break

# --- Función para mostrar alias dado un anon_id ---
def get_alias_from_anon(anon_id):
    for uid, pdata in players.items():
        if pdata["anon_id"] == anon_id:
            nombre, emoji = assigned_aliases.get(uid, ("Jugador", "❓"))
            return f"{nombre} {emoji}"
    return "Desconocido 🤖"

# --- Main ---
def main():
    app = ApplicationBuilder().token(TOKEN_BOT).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("vote_mode", vote_mode))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("claim_trophie", claim_trophie))
    app.add_handler(CommandHandler("play", play))
    app.add_handler(CommandHandler("reveal", reveal))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_vote))
    app.run_polling()

if __name__ == "__main__":
    main()
