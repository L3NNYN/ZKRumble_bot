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

# Configuración de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# -------------------
# Configuración
# -------------------
EE_SECRET_KEY = "aG9sYWNhaXN0ZWVubGF0cmFtcGE="  # Debe ser segura en producción
TOKEN_BOT = "8040129649:AAF-eJJxSP9EmVeR5mB2iysjGIiMZDG_6dg"

# Variantes del juego
VARIATIONS = [
    "Rock, Paper, Scissors, Fire, Well",
    "Rock, Paper, Scissors, Lizard, Spock",
    "Rock, Paper, Scissors, Fire, Water"
]

# -------------------
# Estructuras de datos
# -------------------
players = {}          # user_id: {anon_id, mac_key, mac_credential, ...}
votes = {}            # anon_id: {commitment, voto, nonce, mac}
pending_votes = set() # user_id de jugadores que deben votar

# -------------------
# Funciones criptográficas
# -------------------
def generate_anon_id(user_id: str) -> str:
    """Genera ID anónimo usando HMAC (Entidad Emisora)"""
    return hmac.new(
        EE_SECRET_KEY.encode(),
        user_id.encode(),
        hashlib.sha256
    ).hexdigest()

def generate_mac(key: str, message: str) -> str:
    """Genera MAC para autenticar mensajes"""
    return hmac.new(
        key.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

def create_commitment(message: str, nonce: str) -> str:
    """Crea un commitment criptográfico"""
    return hashlib.sha256(
        f"{message}{nonce}".encode()
    ).hexdigest()

# -------------------
# Comandos del Bot
# -------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Registro y anonimización de jugadores"""
    user_id = str(update.effective_user.id)
    
    if user_id in players:
        await update.message.reply_text("✅ Ya estás registrado.")
        return
    
    # 1. Entidad Emisora genera credenciales
    anon_id = generate_anon_id(user_id)
    mac_key = secrets.token_hex(16)  # Clave única por jugador
    mac_credential = generate_mac(EE_SECRET_KEY, f"{anon_id}||jugador_valido")
    
    # 2. Almacenar datos (sin user_id real)
    players[user_id] = {
        "anon_id": anon_id,
        "mac_key": mac_key,
        "mac_credential": mac_credential,
        "status": "registered"
    }
    
    await update.message.reply_text(
        "🎉 **Registro exitoso**\n"
        f"ID Anónimo: `{anon_id[:8]}...`\n"
        "Usa /vote para participar en la votación."
    )

async def vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia el proceso de votación"""
    user_id = str(update.effective_user.id)
    
    if user_id not in players:
        await update.message.reply_text("❌ Primero regístrate con /start")
        return
    
   # Mensaje con opciones numeradas
    opciones = "\n".join([f"{i+1}. {v}" for i, v in enumerate(VARIATIONS)])
    await update.message.reply_text(
        "🗳️ **Elige la variante para el torneo:**\n"
        f"{opciones}\n\n"
        "Responde con el número de tu opción (ej: '1')."
    )
    pending_votes.add(user_id)

async def handle_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesa el voto con commitments y MACs"""
    user_id = str(update.effective_user.id)
    
    if user_id not in pending_votes:
        return
    
    try:
        # Convertir entrada a número
        opcion = int(update.message.text.strip())
        if opcion < 1 or opcion > len(VARIATIONS):
            raise ValueError
        voto = VARIATIONS[opcion - 1]
    except (ValueError, IndexError):
        await update.message.reply_text("❌ Número inválido. Usa /vote para ver las opciones.")
        return
    
    # Generar commitment y MAC
    nonce = secrets.token_hex(16)
    player_data = players[user_id]
    commitment = create_commitment(voto, nonce)
    mac = generate_mac(player_data["mac_key"], f"{voto}{nonce}")
    
    # Almacenar voto (asociado a anon_id)
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
        "Espera a que todos voten y usa /results para ver los resultados."
    )

async def results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verifica y muestra resultados de la votación"""
    if not votes:
        await update.message.reply_text("📭 No hay votos registrados.")
        return
    
    # Verificar cada voto
    resultados = {}
    for anon_id, vote_data in votes.items():
        # Verificar commitment
        recalculated = create_commitment(vote_data["voto"], vote_data["nonce"])
        if recalculated != vote_data["commitment"]:
            logging.warning(f"⚠️ Commitment inválido para {anon_id[:8]}...")
            continue
        
        # Verificar MAC (opcional)
        player_id = next(uid for uid, p in players.items() if p["anon_id"] == anon_id)
        mac_key = players[player_id]["mac_key"]
        valid_mac = generate_mac(mac_key, f"{vote_data['voto']}{vote_data['nonce']}")
        
        if valid_mac != vote_data["mac"]:
            logging.warning(f"⚠️ MAC inválido para {anon_id[:8]}...")
            continue
        
        # Contar voto válido
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
    """Muestra ayuda"""
    help_text = """
    🤖 **Comandos Disponibles:**
    /start - Registro anónimo en el torneo
    /vote - Votar por la variante del juego
    /results - Mostrar resultados de la votación
    """
    await update.message.reply_text(help_text)

# -------------------
# Inicialización del Bot
# -------------------
def main():
    app = ApplicationBuilder().token(TOKEN_BOT).build()
    
    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("vote", vote))
    app.add_handler(CommandHandler("results", results))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_vote))
    
    logging.info("Bot iniciado...")
    app.run_polling()

if __name__ == "__main__":
    main()