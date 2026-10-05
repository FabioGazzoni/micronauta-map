import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

MEGA_BASE = "https://micronauta.dnsalias.net/megaweb"

LOGIN_PAGE_URL = f"{MEGA_BASE}/index.php"
LOGIN_CMD_URL = f"{MEGA_BASE}/psw/login_cmd.php"
SESSION_CHECK_URL = f"{MEGA_BASE}/psw/session_check.php"
TOPFRAME_URL = f"{MEGA_BASE}/vista/topframe_inter.php"
CLIENTES_URL = f"{TOPFRAME_URL}?cmd=get_clientes"
GMAP_URL = f"{MEGA_BASE}/vista/gmap_xml.php"
TRAZA_URL = f"{MEGA_BASE}/vista/traza.php?cmd=traza"

MEGAWEB_USERNAME = os.getenv("MEGAWEB_USERNAME")
MEGAWEB_PASSWORD = os.getenv("MEGAWEB_PASSWORD")

TRAZAS_CACHE_TTL_SECONDS = 180

# Cada cuánto el ticker le pide coches a Megaweb mientras haya pedidos del
# front (1 pedido por ciclo sin importar cuántos clientes haya).
COCHES_REFRESH_SECONDS = 30
# Ticks seguidos sin ningún pedido del front tras los cuales el ticker se
# detiene. Con 1, se detiene en el primer tick sin pedidos; subirlo evita el
# arranque en frío tras pausas cortas, a costa de pedidos de más a Megaweb.
COCHES_IDLE_TICKS = 1
# Tope de espera de un pedido del front por el pedido a Megaweb en curso
# (arranque en frío o Megaweb más lento que lo estimado). Debe quedar por
# debajo del timeout de 30s de API Gateway/CloudFront.
COCHES_MAX_WAIT_SECONDS = 20
# Nunca se devuelven datos más viejos que esto (ej. Megaweb caído): error.
COCHES_MAX_STALE_SECONDS = 120

# --- Empresas habilitadas ------------------------------------------------------
# Solo se muestran los coches de empresas habilitadas para descargar
# (is_downloaded=true) en la tabla micronauta_businesses de la otra cuenta
# AWS. Desactivado por defecto: en local (Docker en la PC) la tabla rechaza la
# lectura porque su política solo admite la IP de la EC2.
EMPRESAS_FILTER_ENABLED = os.getenv("EMPRESAS_FILTER_ENABLED", "false").lower() == "true"
EMPRESAS_TABLE_ARN = os.getenv(
    "EMPRESAS_TABLE_ARN",
    "arn:aws:dynamodb:us-east-2:417755752792:table/micronauta_businesses",
)
# Se agregan empresas muy de vez en cuando: alcanza con releer cada hora.
EMPRESAS_REFRESH_SECONDS = 3600
# Si la lectura falla, no reintentar más seguido que esto.
EMPRESAS_RETRY_SECONDS = 300
# Última lista buena en disco, para sobrevivir reinicios del contenedor
# aunque DynamoDB no responda (en Docker, ./data está montado como volumen).
EMPRESAS_CACHE_FILE = BASE_DIR / "data" / "empresas_habilitadas.json"
# Para nombres de Megaweb que no coinciden con ninguna sub-empresa de la
# tabla: nombre de Megaweb (tal cual) -> CUIT.
EMPRESAS_ALIASES = {}
