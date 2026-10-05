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
