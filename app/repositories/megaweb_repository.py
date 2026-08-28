import json

from app.config import CLIENTES_URL, GMAP_URL, TOPFRAME_URL, TRAZA_URL
from app.repositories.session_repository import (
    SessionUnusableError,
    send_get_request,
    send_request,
)

# Distintos de los headers de login: capturados de requests reales del
# navegador contra topframe_inter.php / gmap_xml.php (ver MIGRATION_PLAN.md).
DATA_HEADERS = {
    "Accept": "*/*",
    "Referer": TOPFRAME_URL,
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
}

# gmap_xml.php y traza.php no redirigen a una página de login cuando la
# sesión no es válida (a diferencia de lo que detecta session_repository por
# HTML): devuelven 200 OK con este JSON. Confirmado contra Megaweb real.
NOT_LOGGED_IN_MESSAGE = "No esta logueado"


def _raise_if_not_logged_in(parsed):
    if (
        isinstance(parsed, dict)
        and parsed.get("ok") is False
        and parsed.get("error_msg") == NOT_LOGGED_IN_MESSAGE
    ):
        raise SessionUnusableError("session_expired")
    return parsed


def get_clientes_raw():
    response = send_get_request(CLIENTES_URL, headers=DATA_HEADERS)
    return _raise_if_not_logged_in(response.json())


def get_coches_raw():
    payload = {
        "formato": "json",
        "filtro": json.dumps(["T", "show_ruta"]),
    }
    response = send_request(GMAP_URL, data=payload, headers=DATA_HEADERS)
    return _raise_if_not_logged_in(response.json())


def get_trazas_raw():
    payload = {"filtro": "T"}
    response = send_request(TRAZA_URL, data=payload, headers=DATA_HEADERS, timeout=45)
    return _raise_if_not_logged_in(response.json())
