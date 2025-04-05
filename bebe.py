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

TOKEN_BOT = "7544786769:AAGoRrdjgfHul35Fe7PxIM9vcl6UGtERH0U"
VARIATIONS = [    
    "Rock, Paper, Scissors, Fire, Well",
    "Rock, Paper, Scissors, Lizard, Spock",
    "Rock, Paper, Scissors, Fire, Water"
    ]

# --- Parámetros ZKP (Schnorr) ---
P = 115792089237316195423570985008687907853269984665640564039457584007908834671663  # primo seguro
G = 2  # generador

# --- Clave maestra del Bot (como Issuer y Verifier) ---
BOT_SECRET_KEY = secrets.token_hex(32)  # Guardar en entorno real!

# --- Estructuras de datos ---
players = {}  # {user_id: {"anon_id": str, "secret": int, "public_key": int, "mac_key": str, "mac_credential": str}}
votes = {}    # {anon_id: {"vote": str, "nonce": str, "mac": str}}
pending_votes = set() # user_id de jugadores que deben votar

# --- Funciones criptográficas ---
def generate_anon_id(user_id: str) -> str:
    """Genera ID anónimo con la clave del Bot (Issuer)"""
    return hmac.new(BOT_SECRET_KEY.encode(), str(user_id).encode(), hashlib.sha256).hexdigest()

def generate_mac(key: str, message: str) -> str:
    """Genera HMAC-SHA256 para integridad"""
    return hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()

def create_zk_proof(secret: int) -> tuple:
    """Genera prueba ZKP no interactiva (Fiat-Shamir)"""
    r = secrets.randbelow(P-1)
    t = pow(G, r, P)
    c = int(hashlib.sha256(f"{t}".encode()).hexdigest(), 16) % P  # Challenge autogenerado
    s = (r + c * secret) % (P-1)
    return (t, s)

def verify_zk_proof(proof: tuple, public_key: int) -> bool:
    """Verifica una prueba ZKP"""
    t, s = proof
    c = int(hashlib.sha256(f"{t}".encode()).hexdigest(), 16) % P
    left = pow(G, s, P)
    right = (t * pow(public_key, c, P)) % P
    return left == right

# --- Comandos del Bot ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Registro: Bot como Issuer genera credenciales"""
    user_id = update.effective_user.id
    if user_id in players:
        await update.message.reply_text("✅ Ya estás registrado. Usa /vote")
        return

    # 1. Generar ID anónimo
    anon_id = generate_anon_id(str(user_id))
    
    # 2. Generar claves ZKP
    secret = secrets.randbelow(P-1)
    public_key = pow(G, secret, P)
    
    # 3. Generar MAC credential (firma del Bot como Issuer)
    mac_key = secrets.token_hex(32)
    mac_credential = generate_mac(BOT_SECRET_KEY, f"{anon_id}:{public_key}")
    
    players[user_id] = {
        "anon_id": anon_id,
        "secret": secret,
        "public_key": public_key,
        "mac_key": mac_key,
        "mac_credential": mac_credential  # ¡Firma del Issuer!
    }
    print(user_id)
    print(players[user_id])

    await update.message.reply_text(
        "🎉 Credenciales generadas:\n"
        f"• ID Anónimo: `{anon_id[:8]}...`\n"
        f"• MAC Credential: `{mac_credential[:8]}...`\n"
        "Usa /vote para participar"
    )
    pending_votes.add(user_id)

async def vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Votación: Bot como Verifier chequea ZKP y MAC credential"""
    user_id = update.effective_user.id
    if user_id not in players:
        await update.message.reply_text("🤓 Usa /start para registrarte primero")
        return

    player_data = players[user_id]
    
    # 1. Verificar MAC credential (Bot como Verifier)
    expected_mac = generate_mac(BOT_SECRET_KEY, f"{player_data['anon_id']}:{player_data['public_key']}")
    if not hmac.compare_digest(expected_mac, player_data["mac_credential"]):
        await update.message.reply_text("🔒 Error: Credencial inválida")
        return

    # 2. Generar y verificar ZKP
    proof = create_zk_proof(player_data["secret"])
    if not verify_zk_proof(proof, player_data["public_key"]):
        await update.message.reply_text("🔒 Error: Prueba ZKP inválida")
        return

    # 3. Mostrar opciones de voto para la modalidad de juego (si todo es válido)
    # Mensaje con opciones numeradas
    opciones = "\n".join([f"{i+1}. {v}" for i, v in enumerate(VARIATIONS)])
    await update.message.reply_text(
        "🗳️ **Elige la variante para el torneo:**\n"
        f"{opciones}\n\n"
        "Responde con el número de tu opción (ej: '1')."
    )

async def handle_vote_variant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesa el voto con MAC de integridad"""
    user_id = update.effective_user.id
    if user_id not in players:
        return
    if user_id not in pending_votes:
        return

    try:
        # Convertir entrada a número
        opcion = int(update.message.text.strip())
        if opcion < 1 or opcion > len(VARIATIONS):
            raise ValueError
        vote = VARIATIONS[opcion - 1]
    except (ValueError, IndexError):
        await update.message.reply_text("❌ Número inválido. Usa /vote para ver las opciones.")
        return

    player_data = players[user_id]
    nonce = secrets.token_hex(16)
    
    # Generar MAC para el voto (usando la mac_key del jugador)
    vote_mac = generate_mac(player_data["mac_key"], f"{vote}:{nonce}")
    
    # Almacenar voto con ID anónimo
    votes[player_data["anon_id"]] = {
        "vote": vote,
        "nonce": nonce,
        "mac": vote_mac
    }

    pending_votes.remove(user_id)
    await update.message.reply_text(
        f"✅ Voto registrado para: {vote}\n"
        f"Nonce: `{nonce[:8]}...`\n"
        f"MAC: `{vote_mac[:8]}...`"
    )

async def results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verifica MACs y muestra resultados"""
    if not votes:
        await update.message.reply_text("📭 No hay votos")
        return
    if  len(players)==1:
        await update.message.reply_text(
        f"❌ Faltan personas por votar"
        )
        return
    elif len(pending_votes) > 0:
        await update.message.reply_text(
        f"❌ Faltan personas por votar"
        )
        return

    resultados = {}
    for anon_id, data in votes.items():
        # Buscar al jugador por anon_id
        player = next((p for p in players.values() if p["anon_id"] == anon_id), None)
        if not player:
            continue

        # Verificar MAC del voto
        expected_mac = generate_mac(player["mac_key"], f"{data['vote']}:{data['nonce']}")
        if not hmac.compare_digest(expected_mac, data["mac"]):
            continue

        resultados[data["vote"]] = resultados.get(data["vote"], 0) + 1

    # Mostrar resultados
    if not resultados:
        await update.message.reply_text("🔍 No hay votos válidos")
        return

    msg = "🏆 **Resultados del Torneo**\n"
    for option, count in sorted(resultados.items()):
        msg += f"• {option}: {count} voto(s)\n"

    winner = max(resultados.items(), key=lambda x: x[1])[0]
    msg += f"\n🎉 **Variante elegida:** {winner}"
    await update.message.reply_text(msg)

# --- Main ---
def main():
    app = ApplicationBuilder().token(TOKEN_BOT).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("vote", vote))
    app.add_handler(CommandHandler("results", results))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_vote_variant))
    app.run_polling()

if __name__ == "__main__":
    main()