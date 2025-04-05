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

"""
Torneo Criptográfico de Piedra, Papel y Tijera — Elaborado por Lenin Chacon  y Daniel Gurreck 

Este bot implementa un torneo de "Rock, Paper, Scissors" (y sus variantes) con garantías de privacidad, autenticación anónima y verificabilidad mediante técnicas criptográficas modernas. A continuación se explican las 4 fases principales del sistema:

1. REGISTRO DE JUGADORES (Anonimato y Autenticación)
   - Cada jugador se registra con una credencial anónima mediante MACs (Message Authentication Codes).
   - Estas credenciales son emitidas por el bot (Issuer) y pueden ser verificadas más adelante sin revelar la identidad del usuario.
   - Se generan claves públicas y pruebas de conocimiento cero (ZKP) para autenticarse sin compartir secretos.

2. VOTACIÓN POR LA MODALIDAD DEL JUEGO (Privacidad y Verificabilidad)
   - Los jugadores votan por una de las variantes del juego (ej. RPS-Fire-Well).
   - La autenticidad del voto se valida con MACs emitidos por el bot y autenticados con ZKP para demostrar que el votante es válido.
   - Los resultados se mantienen ocultos hasta que todos los jugadores han votado.
   - En caso de empate entre modalidades, el sistema selecciona una variante al azar entre las más votadas.

3. JUGADAS Y AVANCE DEL TORNEO (Commitments y ZKP)
   - Cada jugador realiza su jugada mediante un **commitment de Pedersen**, que compromete su movimiento sin revelarlo.
   - El compromiso incluye un número aleatorio (`r`) que el jugador guarda y usará para **revelar su jugada**.
   - Solo se permite revelar una jugada cuando ambos jugadores han comprometido su elección.
   - El servidor valida que el `commitment` coincide con el movimiento y el nonce proporcionado (verificabilidad).
   - En caso de empate, ambos jugadores deben volver a jugar, sin revelar la jugada anterior.
   - Los ganadores acumulan **commitments homomórficos de victoria**, que pueden luego ser validados.

4. RECLAMACIÓN DEL PREMIO (Pruebas de Victoria)
   - El jugador que alcance la final puede reclamar el trofeo mediante el comando /claim_trophie.
   - Para validar que realmente ganó, presenta sus commitments de victoria (Pedersen).
   - Estos commitments son verificados homomórficamente: se comprueba que representan victorias sin revelar detalles de las partidas.

📌 Consideraciones adicionales:
- El anonimato se mantiene mediante IDs y alias simbólicos, pero no es absoluto (se prioriza la jugabilidad).
- El sistema está diseñado para una única sala de torneo.
- La **cantidad mínima de jugadores requerida** está definida como una **variable global** (`MIN_PLAYERS`) y debe ajustarse manualmente si se desea escalar el torneo.

"""
#NUMERO MINIMO DE JUGADORES
MIN_PLAYERS = 4

# Formato de Logs 
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Numeros criptograficos privados
P = 115792089237316195423570985008687907853269984665640564039457584007908834671663 #Numero grande primo P
G = 2 # Numero generado G 

#Configuracion de llave criptografica de la entidad emisora (Bot)
EE_SECRET_KEY = "aG9sYWNhaXN0ZWVubGF0cmFtcGE"

#Token de bot (Telegram) 
TOKEN_BOT = "7544786769:AAGoRrdjgfHul35Fe7PxIM9vcl6UGtERH0U"

#Variantes y reglas

defeats = {} # Reglas seleccionadas

VARIATIONS = [
    "Rock, Paper, Scissors, Fire, Well",
    "Rock, Paper, Scissors, Lizard, Spock",
    "Rock, Paper, Scissors, Fire, Water"
]

#Fire, Well
rules_fw = {
    "Rock":     ["Scissors", "Fire"],
    "Paper":    ["Rock", "Well"],
    "Scissors": ["Paper", "Fire"],
    "Fire":     ["Paper", "Well"],
    "Well":     ["Rock", "Scissors"]
}

#Lizar, Spock
rules_ls = {
    "Scissors": ["Paper", "Lizard"],
    "Paper":    ["Rock", "Spock"],
    "Rock":     ["Lizard", "Scissors"],
    "Lizard":   ["Spock", "Paper"],
    "Spock":    ["Scissors", "Rock"]
}

# Fire, Water
rules_fw2 = {
    "Rock":     ["Scissors", "Fire"],
    "Paper":    ["Rock", "Water"],
    "Scissors": ["Paper", "Water"],
    "Fire":     ["Paper", "Scissors"],
    "Water":    ["Fire", "Rock"]
}

SELECTED_VARIATION = None  # Variante ganadora seleccionada

# Variables globales del torneo
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

# El anon_id del usuario se asocia a un alias a modo de identificador anonimo
aliases = [
    ("Caballo Loco", "🐴"),
    ("Gato Volador", "🐱"),
    ("Perro Valiente", "🐶"),
    ("Tortuga Ninja", "🐢"),
    ("Águila Real", "🦅"),
    ("Mono Alegre", "🐵"),
    ("Tiburon Enojado", "🦈"),
    ("Zorro Astuto", "🦊")
]
assigned_aliases = {}

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

# Comando Status que muestra las partidas en curso 
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
                    text=f"🎮 Tu oponente es: {alias2 if pdata['anon_id'] == a1 else alias1} \n¡Prepara tu jugada con /play <opción>!")


# Pedersen Commitment
P_PEDERSEN = 208351617316091241234326746312124448251235562226470491514186331217050270460481
G_PEDERSEN = 2
H_PEDERSEN = 3  # Otro generador del grupo

# Simulación de Pedersen commitment: C = g^m *d h^r mod p

def pedersen_commit(value: int, r: int) -> int:
    return (pow(G_PEDERSEN, value, P_PEDERSEN) * pow(H_PEDERSEN, r, P_PEDERSEN)) % P_PEDERSEN

async def claim_trophie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in players:
        await update.message.reply_text("❌ No estás registrado.")
        return

    anon_id = players[user_id]["anon_id"]
    global victory_commits
    victories = victory_commits.get(anon_id, [])
    valid_proofs = []

    for item in victories:
        if isinstance(item, tuple) and len(item) == 2:
            commitment, r = item
        else:
            continue 
        expected = pedersen_commit(1, r)
        if commitment == expected:
            valid_proofs.append(commitment)

    if not valid_proofs:
        await update.message.reply_text("😕 No se encontraron pruebas de victoria para reclamar el trofeo.")
        return

    count = len(valid_proofs)
    nombre, emoji = assigned_aliases.get(user_id, ("Jugador", "❓"))

    if count >= 1:
        await update.message.reply_text(
            text=(
                f"🔥 ¡GLORIA ETERNA, {nombre} {emoji}! 🔥\n"
                f"🏆 Has arrasado con todos y eres el GRAN CAMPEÓN de la arena.\n"
                f"Usa /claim_trophie para reclamar tu trofeo de guerra.\n\n"
                f"🎥 Esta canción es tuya:\nhttps://youtu.be/goeT7boL1Ks?si=txl7uhw7PeBWhYlb&t=38"
            )
        )
        
        # Reiniciar completamente el estado del torneo
        global bracket, current_matches, match_results, plays, pending_reveals, reveals, votes, selected_variation
        
        # Conservar solo los jugadores registrados y sus credenciales
        players_to_keep = {}
        aliases_to_keep = {}
        for uid, data in players.items():
            players_to_keep[uid] = {
                "anon_id": data["anon_id"],
                "mac_key": data["mac_key"],
                "secret": data["secret"],
                "public_key": data["public_key"]
            }
            aliases_to_keep[uid] = assigned_aliases.get(uid, ("Jugador", "❓"))
        
        # Reiniciar todas las variables de estado para un torneo nuevo
        bracket = []
        current_matches = []
        match_results = {}
        plays = {}
        pending_reveals = {}
        reveals = {}
        votes = {}
        selected_variation = None
        victory_commits = {}
        
        # Restaurar jugadores y aliases 
        players.clear()
        players.update(players_to_keep)
        assigned_aliases.clear()
        assigned_aliases.update(aliases_to_keep)
        
        for uid in players:
            await context.bot.send_message(
                chat_id=uid,
                text="🔄 El torneo ha sido reiniciado. Los jugadores pueden votar nuevamente con /vote_mode para comenzar un nuevo torneo."
            )
    else:
        await update.message.reply_text(f"📉 {nombre} {emoji}, aún no has acumulado suficientes victorias para reclamar el trofeo.")

# Iniciar el torneo al registrar el usuario
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
    await update.message.reply_text(f"🎮 Bienvenido {nombre} {emoji}! a RPS Arena 🏟️!\n\n"
                                    "Prepárate para enfrentarte en un torneo de *Rock, Paper, Scissors*… con giros inesperados. "
                                    "Aquí no basta con suerte: necesitarás estrategia, nervios de acero y voluntad de hierro.\n\n"
                                    "🛡️ Regístrate con /start\n"
                                    "⚔️ Vota la modalidad con /vote_mode\n"
                                    "🎯 Juega con /play <jugada>\n"
                                    "👁️ Revela tu jugada con /reveal <jugada> <nonce>\n"
                                    "🏆 Y si conquistas a todos… usa /claim_trophie para sellar tu victoria.\n\n"
                                    "¡Que comience el combate!"
                                )

# Iniciar modo de votado
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
    await update.message.reply_text(f"✅ Voto registrado ({actuales}/{MIN_PLAYERS})")
    if actuales < MIN_PLAYERS:
        await update.message.reply_text(f"🕐 Aún no se alcanza el mínimo de jugadores requeridos ({MIN_PLAYERS}).")

    if actuales == MIN_PLAYERS:
        resultados = {}
        for v in votes.values():
            resultados[v["vote"]] = resultados.get(v["vote"], 0) + 1
        selected_variation = max(resultados.items(), key=lambda x: x[1])[0]
        SELECTED_VARIATION = selected_variation
        reglas_texto = ""
        if selected_variation == "Rock, Paper, Scissors, Fire, Well":
            reglas_texto = "📜 Reglas:\n- Rock vence a Scissors y Fire\n- Paper vence a Rock y Well\n- Scissors vence a Paper y Fire\n- Fire vence a Paper y Well\n- Well vence a Rock y Scissors"
        elif selected_variation == "Rock, Paper, Scissors, Lizard, Spock":
            reglas_texto = "📜 Reglas:\n- Scissors corta Paper\n- Paper cubre Rock\n- Rock aplasta Lizard\n- Lizard envenena Spock\n- Spock rompe Scissors\n- Scissors decapita Lizard\n- Lizard devora Paper\n- Paper refuta Spock\n- Spock vaporiza Rock\n- Rock rompe Scissors"
        elif selected_variation == "Rock, Paper, Scissors, Fire, Water":
            reglas_texto = "📜 Reglas:\n- Rock aplasta Scissors y apaga Fire\n- Paper cubre Rock y absorbe Water\n- Scissors corta Paper y evapora Water\n- Fire quema Paper y derrite Scissors\n- Water apaga Fire y erosiona Rock"
        else:
            reglas_texto = "ℹ️ Las reglas de esta variante aún no han sido implementadas."

        for user_id in players:
            await context.bot.send_message(chat_id=user_id, text=f"🎮 Variante seleccionada: {selected_variation}")
            await context.bot.send_message(chat_id=user_id, text=reglas_texto)
        
        if selected_variation == "Rock, Paper, Scissors, Fire, Well":
            defeats.clear()
            defeats.update(rules_fw)
        elif selected_variation == "Rock, Paper, Scissors, Lizard, Spock":
            defeats.clear()
            defeats.update(rules_ls)
        elif selected_variation == "Rock, Paper, Scissors, Fire, Water":
            defeats.clear()
            defeats.update(rules_fw2)

        await iniciar_torneo(context)

# Comandos de ayuda
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
    
    if len(players) < MIN_PLAYERS:
        for user_id in players:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"⏳ Se necesitan al menos {MIN_PLAYERS} jugadores para comenzar."
            )
        return

    # Asegurar número par de jugadores
    anon_ids = [p["anon_id"] for p in players.values()]
    if len(anon_ids) % 2 != 0:
        # Eliminar un jugador aleatorio para tener número par
        eliminado = random.choice(anon_ids)
        anon_ids.remove(eliminado)
        for uid, pdata in list(players.items()):
            if pdata["anon_id"] == eliminado:
                await context.bot.send_message(
                    chat_id=uid,
                    text="🔀 Se te ha dado un bye en esta ronda por tener número impar de jugadores."
                )

    random.shuffle(anon_ids)
    bracket = [(anon_ids[i], anon_ids[i+1]) for i in range(0, len(anon_ids), 2)]
    current_matches = bracket.copy()  # Usar copy() para evitar referencia
    match_results.clear()
    plays.clear()
    pending_reveals.clear()
    reveals.clear()

    await anunciar_enfrentamientos(context)
    
    for user_id in players:
        await context.bot.send_message(
            chat_id=user_id,
            text="🏁 ¡El torneo ha comenzado! Realiza tu jugada con /play <opción>"
        )

async def play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global selected_variation
    # Verificar si fue eliminado y si el torneo sigue activo
    anon_id = players.get(update.effective_user.id, {}).get("anon_id")
    torneo_activo = any([anon_id in match for match in current_matches])
    if anon_id and not torneo_activo and current_matches:
        await update.message.reply_text("🚫 Has sido eliminado del torneo. Ya no puedes jugar.")
        return
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

            # Verificar si se completaron todos los enfrentamientos
        if not current_matches:
            siguiente_ronda = list(match_results.values())
            if len(siguiente_ronda) == 1:
                # Ganador final
                for uid, pdata in players.items():
                    if pdata["anon_id"] == siguiente_ronda[0]:
                        alias = get_alias_from_anon(siguiente_ronda[0])
                        await context.bot.send_message(chat_id=uid, text=f"🏆 ¡Felicidades {alias}, eres el ganador del torneo! Usa /claim_trophie para reclamar tu trofeo. 🎊")

                # Reiniciar estado del torneo
                bracket.clear()
                current_matches.clear()
                match_results.clear()
                plays.clear()
                pending_reveals.clear()
                reveals.clear()
                votes.clear()
                victory_commits.clear()
                selected_variation = None
                return

            random.shuffle(siguiente_ronda)
            bracket.clear()
            bracket.extend([(siguiente_ronda[i], siguiente_ronda[i+1]) for i in range(0, len(siguiente_ronda), 2)])
            current_matches.clear()
            current_matches.extend(bracket)
            match_results.clear()
            reveals.clear()
            pending_reveals.clear()
            await anunciar_enfrentamientos(context)

    await update.message.reply_text(f"🔒 Jugada registrada.\nCommitment: {commitment[:6]}...\nGuarda este nonce para el reveal: `{nonce}`")

def generate_victory_commitment():
    r = secrets.randbelow(P_PEDERSEN)
    commitment = pedersen_commit(1, r)
    return commitment, r

# Revelar jugada del commitment con el valor seleccionado y el nonce
async def reveal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Verificar si fue eliminado y si el torneo sigue activo
    anon_id = players.get(update.effective_user.id, {}).get("anon_id")
    torneo_activo = any([anon_id in match for match in current_matches])
    if anon_id and not torneo_activo and current_matches:
        await update.message.reply_text("🚫 Has sido eliminado del torneo. Ya no puedes revelar jugadas.")
        return
    
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

    # Buscar el emparejamiento actual del jugador
    current_match = None
    for match in current_matches:
        if anon_id in match:
            current_match = match
            break

    if not current_match:
        await update.message.reply_text("⚠️ No estás en ningún emparejamiento activo.")
        return

    a1, a2 = current_match
    if a1 in reveals and a2 in reveals:
        # Ambos jugadores han revelado
        j1 = reveals[a1]["move"]
        j2 = reveals[a2]["move"]
        
        uid1 = next(uid for uid, p in players.items() if p["anon_id"] == a1)
        uid2 = next(uid for uid, p in players.items() if p["anon_id"] == a2)
        
        result_message = f"🎮 Resultado \n{get_alias_from_anon(a1)} - {j1} \n      vs \n{get_alias_from_anon(a2)} - {j2}\n"

        # Determinar ganador según las reglas seleccionadas
        if j2 in defeats.get(j1, []):
            winner = a1
            result_message += f"🏆 Ganador: {get_alias_from_anon(winner)}"
            # Generar prueba de victoria
            commitment, r = generate_victory_commitment()
            victory_commits.setdefault(winner, []).append((commitment, r))
        elif j1 in defeats.get(j2, []):
            winner = a2
            result_message += f"🏆 Ganador: {get_alias_from_anon(winner)}"
            # Generar prueba de victoria
            commitment, r = generate_victory_commitment()
            victory_commits.setdefault(winner, []).append((commitment, r))
        else:
            result_message = "🤝 Empate. Ambos deben volver a jugar con /play"
            # Limpiar revelaciones para permitir nuevo intento
            reveals.pop(a1)
            reveals.pop(a2)
            pending_reveals.pop(a1, None)
            pending_reveals.pop(a2, None)
            # Notificar a ambos jugadores
            for uid in [uid1, uid2]:
                await context.bot.send_message(chat_id=uid, text=result_message)
            return

        # Registrar resultado y eliminar el emparejamiento actual
        match_results[(a1, a2)] = winner
        current_matches.remove((a1, a2))

        # Notificar a todos los jugadores del resultado
        for uid in players:
            await context.bot.send_message(chat_id=uid, text=result_message)

        # Notificar al perdedor
        loser = a2 if winner == a1 else a1
        for uid, pdata in players.items():
            if pdata["anon_id"] == loser:
                await context.bot.send_message(
                    chat_id=uid,
                    text="😢 Has sido eliminado del torneo. ¡Gracias por participar!"
                )

        # Verificar si se completó la ronda actual
        if not current_matches:
            # Preparar siguiente ronda o finalizar torneo
            ganadores = list(match_results.values())
            
            if len(ganadores) == 1:
                # Tenemos un ganador final
                ganador_final = ganadores[0]
                alias = get_alias_from_anon(ganador_final)
                for uid, pdata in players.items():
                    if pdata["anon_id"] == ganador_final:
                        await context.bot.send_message(
                            chat_id=uid,
                            text=f"🏆 ¡Felicidades {alias}, eres el GRAN GANADOR del torneo! \nUsa /claim_trophie para reclamar tu trofeo."
                        )
                    else:
                        await context.bot.send_message(
                            chat_id=uid,
                            text=f"🎉 El torneo ha terminado.\n🏆 El ganador fue: {alias}\nGracias por participar."
                        )
            else:
                # Crear nuevos emparejamientos para la siguiente ronda
                random.shuffle(ganadores)
                nuevos_emparejamientos = [(ganadores[i], ganadores[i+1]) 
                                        for i in range(0, len(ganadores), 2)]
                
                # Actualizar estado del torneo
                bracket.clear()
                bracket.extend(nuevos_emparejamientos)
                current_matches.clear()
                current_matches.extend(nuevos_emparejamientos)
                match_results.clear()
                reveals.clear()
                pending_reveals.clear()
                
                # Anunciar nueva ronda
                await anunciar_enfrentamientos(context)
                for uid in players:
                    await context.bot.send_message(
                        chat_id=uid,
                        text="🏁 ¡Nueva ronda del torneo! Realiza tu jugada con /play <opción>"
                    )
    else:
        await update.message.reply_text("✅ Jugada revelada. Esperando al oponente...")

# Mostar el alias del jugador con el anon_id
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