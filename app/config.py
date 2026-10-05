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

# Cada cuánto se le piden coches a Megaweb, sin importar cuántos clientes
# haya: dentro de este lapso todos reciben la misma respuesta cacheada.
COCHES_CACHE_TTL_SECONDS = 30
# Pasado el TTL se sigue devolviendo el dato anterior mientras se refresca
# en segundo plano, pero nunca uno más viejo que esto (ej. tras horas sin uso
# o con Megaweb caído): en ese caso se espera el pedido nuevo o se da error.
COCHES_MAX_STALE_SECONDS = 120
