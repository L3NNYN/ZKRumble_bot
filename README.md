# Torneo Criptográfico RPS Arena Bot

Un bot de Telegram para organizar torneos anónimos y verificables de Rock, Paper, Scissors (y variantes extendidas), utilizando técnicas avanzadas de criptografía.  
Desarrollado como una demostración práctica de aplicación de Zero-Knowledge Proofs (ZKP), commitments homomórficos y anonimización de identidades.

## Descripción del sistema criptográfico

Este bot implementa un torneo de Rock, Paper, Scissors (y variantes) garantizando privacidad, autenticación anónima y verificabilidad. Las 4 fases esenciales son:

1. Registro de jugadores

- Cada jugador se registra anónimamente mediante MACs + ZKP.
- Se emiten credenciales anónimas verificables que permiten interactuar sin revelar identidad.

2. Votación de modalidad

- Los jugadores votan por la variante del torneo.
- Se valida la autenticidad del voto usando MACs y ZKP.
- Si hay empate, se selecciona aleatoriamente entre las opciones más votadas.

3. Jugadas y avance del torneo

- Los jugadores realizan su jugada mediante un commitment de Pedersen que compromete su jugada sin revelarla.
- Solo pueden revelar su jugada con /reveal <jugada> <nonce> cuando ambos jugadores han jugado.
- En caso de empate, se reinicia la jugada de ambos jugadores.
- Se acumulan commitments homomórficos de victorias.

4. Reclamación del premio

- El ganador final usa /claim_trophie para reclamar su trofeo.
- Se verifica homomórficamente que sus victorias son válidas sin revelar detalles de cada partida.

Nota: El sistema está diseñado para una única sala de torneo. La variable global MIN_PLAYERS debe ser ajustada manualmente si se quiere cambiar el tamaño mínimo del torneo.

## Funcionalidades principales

- Registro de jugadores anónimo mediante MACs + ZKP
- Votación confiable de la modalidad del juego
- Soporte para variantes:
  - Rock, Paper, Scissors, Fire, Well
  - Rock, Paper, Scissors, Lizard, Spock
  - Rock, Paper, Scissors, Fire, Water
- Sistema de torneo por eliminatorias automáticas
- Commitments de Pedersen para asegurar jugadas inalterables
- Verificación homomórfica de victorias para evitar fraudes
- Notificaciones y experiencia estilo arena competitiva
- Alias temáticos para mejorar la jugabilidad y preservar anonimato
- Automatización completa de rondas y control de empates

## Por qué este proyecto es relevante

Este bot no es solo un juego, es una prueba de concepto profesional para:

- Mostrar cómo la criptografía moderna puede aplicarse a procesos de votación y competiciones digitales.
- Demostrar conocimientos prácticos en diseño de sistemas seguros distribuidos.
- Exponer la capacidad de desarrollar bots autónomos y robustos para comunidades.

Ideal para ser incluido en un portafolio técnico.

## Cómo funciona

1. Los jugadores se registran anónimamente con /start.
2. Votan la modalidad del torneo con /vote_mode.
3. Cuando se alcanza el número mínimo de jugadores (MIN_PLAYERS), el torneo inicia automáticamente.
4. Los jugadores realizan sus jugadas con /play <opción>, comprometiendo su jugada mediante commitments de Pedersen.
5. Una vez ambos jugadores han jugado, cada uno debe revelar su jugada con /reveal <jugada> <nonce>.
6. El sistema resuelve los enfrentamientos y genera las siguientes rondas automáticamente.
7. El jugador que gane la final puede reclamar su trofeo con /claim_trophie. El bot valida criptográficamente que los compromisos registrados correspondan a victorias reales.

## Cómo usarlo

git clone https://github.com/tu_usuario/rps-arena-bot.git
cd rps-arena-bot
pip install -r requirements.txt

Edita el archivo de configuración para añadir el token de tu bot de Telegram:

TOKEN_BOT = "TU_TELEGRAM_BOT_TOKEN"

Inicia el bot:

python rps_arena_bot.py

## Recomendaciones

La cantidad mínima de jugadores está definida en la variable global MIN_PLAYERS. Ajusta este valor si deseas torneos más grandes o pequeños.

Recomendado utilizar Python 3.10 o superior.

Este proyecto puede ser fácilmente extendido para soportar múltiples salas o generar tarjetas digitales de campeón en futuras versiones.

## Tecnologías utilizadas

- Python 3.10+
- python-telegram-bot
- cryptography
- Pillow (opcional, para futuras extensiones de imagen)

## Licencia

Este proyecto está licenciado bajo la licencia MIT.

## Autor

Desarrollado como proyecto académico y portafolio profesional de criptografía aplicada.

Autor: Lenin Chacon
Email: lenchaber@outlook.com  
LinkedIn: https://www.linkedin.com/in/lenchaber/

Autor: Daniel Gurreck
Email: danigurreck7@gmail.com  
LinkedIn: https://www.linkedin.com/in/daniel-gurreck-gonz%C3%A1lez-2563b5252/
