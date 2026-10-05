import json
import logging
import threading
import time

from app.config import COCHES_CACHE_TTL_SECONDS, COCHES_MAX_STALE_SECONDS
from app.models.trazas_cache import TrazasCache
from app.repositories import megaweb_repository, session_repository
from app.services import auth_service

logger = logging.getLogger(__name__)

_trazas_cache = TrazasCache()

# Caché compartida de coches. Se guarda la lista ya recortada y serializada
# para no re-procesar nada por cada cliente. Se reemplaza la tupla entera
# (asignación atómica), así que se puede leer sin tomar el lock.
_coches_entry = None  # (coches_json: bytes, fetched_at: float) | None
_coches_error = None  # (body, status) del último refresco fallido | None
_coches_last_attempt = 0.0
_coches_lock = threading.Lock()

# Con Megaweb fallando, no reintentar en segundo plano más seguido que esto.
_COCHES_ERROR_RETRY_SECONDS = 10
# Si se devolvió un dato vencido mientras se refresca en segundo plano, el
# cliente vuelve a pedir en este tiempo para levantar el dato nuevo.
_COCHES_REFRESHING_POLL_SECONDS = 3

# Megaweb manda ~55 campos por coche (itinerarios ITV, indicadores de
# puntualidad, etc.) de los que el mapa solo usa estos. Cuando un mismo dato
# viene duplicado bajo dos claves (coche_id/nc, id/sn, empresa_nombre/em,
# linea_nombre/li) se conserva solo la clave larga.
_COCHE_FIELDS = (
    "cl",
    "coche_id",
    "id",
    "linea_id",
    "empresa_nombre",
    "linea_nombre",
    "patente",
    "lat",
    "lng",
    "cur",
    "vl",
    "sentido",
    "ruta",
    "recorrido",
    "ub",
    "ti",
    "ve",
    "sc",
    "emergencia",
    "problema",
    "sin_conexion",
    "notransmite",
    "singps",
    "detenido",
    "activo",
)


def _slim_coche(raw):
    return {field: raw.get(field) for field in _COCHE_FIELDS}

_SESSION_ERROR_RESPONSE = (
    {
        "ok": False,
        "error": "No se pudo restablecer la sesión con Megaweb.",
        "needs_login": True,
    },
    401,
)


def _call_with_retry(fn):
    if not auth_service.is_logged_in():
        auth_service.ensure_logged_in()

    try:
        return fn()
    except session_repository.SessionUnusableError:
        if auth_service.ensure_logged_in(force=True):
            return fn()
        raise


def _fetch_coches():
    """Pide coches a Megaweb y actualiza la caché. Devuelve (body, status) si falla."""
    global _coches_entry

    try:
        parsed = _call_with_retry(megaweb_repository.get_coches_raw)
    except session_repository.SessionUnusableError:
        return _SESSION_ERROR_RESPONSE
    except session_repository.MegawebUnavailableError as exc:
        return {"ok": False, "error": str(exc)}, 502
    except ValueError:
        return {"ok": False, "error": "Megaweb no devolvió JSON válido."}, 502
    except Exception:
        logger.exception("Refresco de coches contra Megaweb falló.")
        return {"ok": False, "error": "Error inesperado consultando Megaweb."}, 502

    if not isinstance(parsed, dict) or not parsed.get("ok"):
        return {
            "ok": False,
            "error": "Megaweb no devolvió una respuesta válida.",
            "remote": parsed,
        }, 502

    data = parsed.get("data") or {}
    coches = [_slim_coche(c) for c in (data.get("coches") or [])]

    _coches_entry = (
        json.dumps(coches, ensure_ascii=False, separators=(",", ":")).encode(),
        time.time(),
    )
    return None


def _refresh_coches(blocking: bool):
    """
    Refresca la caché con un único pedido a Megaweb a la vez. Quien espera el
    lock y encuentra que otro hilo ya intentó mientras tanto, usa ese
    resultado (bueno o malo) en vez de repetir el pedido.
    """
    global _coches_error, _coches_last_attempt

    waiting_since = time.time()
    if not _coches_lock.acquire(blocking=blocking):
        return
    try:
        if _coches_last_attempt >= waiting_since:
            return
        _coches_error = _fetch_coches()
        _coches_last_attempt = time.time()
    finally:
        _coches_lock.release()


def _coches_response(entry):
    coches_json, fetched_at = entry
    age = time.time() - fetched_at

    if age < COCHES_CACHE_TTL_SECONDS:
        proximo_en = COCHES_CACHE_TTL_SECONDS - age
    elif _coches_error is not None:
        proximo_en = COCHES_CACHE_TTL_SECONDS
    else:
        proximo_en = _COCHES_REFRESHING_POLL_SECONDS

    head = json.dumps({
        "ok": True,
        "actualizado": fetched_at,
        "proximo_en": round(proximo_en, 1),
        # True = el último pedido a Megaweb falló y estos son los últimos
        # datos buenos que se tienen.
        "stale": _coches_error is not None,
    })
    # Se empalma la lista ya serializada en vez de volver a serializarla.
    return head[:-1].encode() + b',"coches":' + coches_json + b"}", 200


def get_coches():
    """Devuelve (body_json_bytes, status)."""
    entry = _coches_entry
    age = time.time() - entry[1] if entry else None

    if entry is None or age >= COCHES_MAX_STALE_SECONDS:
        _refresh_coches(blocking=True)
        entry = _coches_entry
        if entry is None or time.time() - entry[1] >= COCHES_MAX_STALE_SECONDS:
            body, status = _coches_error or (
                {"ok": False, "error": "No hay datos de coches disponibles."},
                502,
            )
            return json.dumps(body).encode(), status

    elif age >= COCHES_CACHE_TTL_SECONDS:
        retry_after = _COCHES_ERROR_RETRY_SECONDS if _coches_error else 0
        if (
            not _coches_lock.locked()
            and time.time() - _coches_last_attempt >= retry_after
        ):
            threading.Thread(
                target=_refresh_coches, args=(False,), daemon=True
            ).start()

    return _coches_response(entry)


def get_trazas():
    cached = _trazas_cache.get()
    if cached is not None:
        return {"ok": True, "trazas": cached, "cached": True}, 200

    try:
        parsed = _call_with_retry(megaweb_repository.get_trazas_raw)
    except session_repository.SessionUnusableError:
        return _SESSION_ERROR_RESPONSE
    except session_repository.MegawebUnavailableError as exc:
        return {"ok": False, "error": str(exc)}, 502
    except ValueError:
        return {"ok": False, "error": "Megaweb no devolvió JSON válido."}, 502

    if not isinstance(parsed, list):
        return {
            "ok": False,
            "error": "Megaweb no devolvió el catálogo de trazas esperado.",
            "remote_type": type(parsed).__name__,
        }, 502

    _trazas_cache.set(parsed)
    return {"ok": True, "trazas": parsed, "cached": False}, 200


def get_clientes():
    try:
        parsed = _call_with_retry(megaweb_repository.get_clientes_raw)
    except session_repository.SessionUnusableError:
        return _SESSION_ERROR_RESPONSE
    except session_repository.MegawebUnavailableError as exc:
        return {"ok": False, "error": str(exc)}, 502
    except ValueError:
        return {"ok": False, "error": "Megaweb no devolvió JSON válido."}, 502

    return {"ok": True, "data": parsed}, 200
