import json
import logging
import threading
import time

from app.config import (
    COCHES_IDLE_TICKS,
    COCHES_MAX_STALE_SECONDS,
    COCHES_MAX_WAIT_SECONDS,
    COCHES_REFRESH_SECONDS,
)
from app.models.trazas_cache import TrazasCache
from app.repositories import megaweb_repository, session_repository
from app.services import auth_service, empresas_service

logger = logging.getLogger(__name__)

_trazas_cache = TrazasCache()

# --- Coches: caché compartida + ticker ---------------------------------------
#
# Un único hilo (el "ticker") le pide coches a Megaweb cada
# COCHES_REFRESH_SECONDS mientras haya pedidos del front: cada pedido marca
# _coches_requested y, si en un tick no hubo ninguno desde el anterior, el
# ticker se detiene (tras COCHES_IDLE_TICKS ticks así). El primer pedido con
# el ticker detenido lo arranca y espera el pedido a Megaweb (arranque en
# frío). Los demás responden siempre desde la caché.
#
# Al front se le devuelve proximo_en = (próximo tick − ahora) + D_est + 0.5,
# para que vuelva justo cuando el ticker ya dejó el dato nuevo en la caché.
#
# Todo el estado se lee/escribe bajo _coches_cond.

_coches_cond = threading.Condition()
# Pide un tick inmediato (arranque en frío).
_coches_wake = threading.Event()

_coches_entry = None  # (json recortado y serializado: bytes, fetched_at) | None
_coches_error = None  # (body, status) del último pedido fallido | None
_coches_requested = False  # hubo pedidos del front desde el último tick
_coches_next_tick = None  # timestamp del próximo tick | None = ticker detenido
_coches_fetching = False
_coches_generation = 0  # +1 al terminar cada pedido a Megaweb (ok o no)
# Duración del último pedido exitoso a Megaweb (D_est).
_coches_fetch_seconds = 3.0

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
    """Pide coches a Megaweb, recorta y serializa. Devuelve (json, None) o (None, error)."""
    try:
        parsed = _call_with_retry(megaweb_repository.get_coches_raw)
    except session_repository.SessionUnusableError:
        return None, _SESSION_ERROR_RESPONSE
    except session_repository.MegawebUnavailableError as exc:
        return None, ({"ok": False, "error": str(exc)}, 502)
    except ValueError:
        return None, ({"ok": False, "error": "Megaweb no devolvió JSON válido."}, 502)
    except Exception:
        logger.exception("Pedido de coches contra Megaweb falló.")
        return None, (
            {"ok": False, "error": "Error inesperado consultando Megaweb."},
            502,
        )

    if not isinstance(parsed, dict) or not parsed.get("ok"):
        return None, (
            {
                "ok": False,
                "error": "Megaweb no devolvió una respuesta válida.",
                "remote": parsed,
            },
            502,
        )

    data = parsed.get("data") or {}
    coches = empresas_service.filtrar_coches(
        [_slim_coche(c) for c in (data.get("coches") or [])]
    )
    coches_json = json.dumps(coches, ensure_ascii=False, separators=(",", ":"))
    return coches_json.encode(), None


def _ticker_loop():
    global _coches_entry, _coches_error, _coches_requested, _coches_next_tick
    global _coches_fetching, _coches_generation, _coches_fetch_seconds

    idle_ticks = 0
    while True:
        with _coches_cond:
            delay = _coches_next_tick - time.time()

        woken = _coches_wake.wait(timeout=max(0, delay))
        _coches_wake.clear()

        with _coches_cond:
            if woken:
                # Arranque en frío: tick ya, y el ciclo se ancla a este momento.
                _coches_next_tick = time.time() + COCHES_REFRESH_SECONDS
            else:
                if _coches_requested:
                    idle_ticks = 0
                else:
                    idle_ticks += 1
                    if idle_ticks >= COCHES_IDLE_TICKS:
                        _coches_next_tick = None
                        logger.info("Sin pedidos del front: ticker de coches detenido.")
                        return
                # Desde el tick anterior (no desde ahora) para que el ciclo no
                # se corra con lo que tarda Megaweb.
                _coches_next_tick += COCHES_REFRESH_SECONDS
                _coches_requested = False
            _coches_fetching = True

        started = time.time()
        coches_json, error = _fetch_coches()
        elapsed = time.time() - started
        logger.info(
            "Pedido de coches a Megaweb: %s en %.1fs",
            "ok" if error is None else "falló",
            elapsed,
        )

        with _coches_cond:
            if error is None:
                _coches_entry = (coches_json, time.time())
                _coches_fetch_seconds = elapsed
            _coches_error = error
            _coches_fetching = False
            _coches_generation += 1
            _coches_cond.notify_all()


def _proximo_en():
    if _coches_next_tick is None:
        return COCHES_REFRESH_SECONDS
    return max(
        1.0,
        (_coches_next_tick - time.time()) + _coches_fetch_seconds + 0.5,
    )


def _error_response(body, status):
    return json.dumps({**body, "proximo_en": round(_proximo_en(), 1)}).encode(), status


def get_coches():
    """Devuelve (body_json_bytes, status)."""
    global _coches_requested, _coches_next_tick

    with _coches_cond:
        _coches_requested = True

        ticker_running = _coches_next_tick is not None
        if not ticker_running:
            # Valor provisorio: el arranque en frío lo re-ancla.
            _coches_next_tick = time.time() + COCHES_REFRESH_SECONDS
            threading.Thread(target=_ticker_loop, daemon=True).start()

        entry = _coches_entry
        age = time.time() - entry[1] if entry else None
        cold = not ticker_running and (
            entry is None or age >= COCHES_REFRESH_SECONDS
        )
        if cold:
            _coches_wake.set()

        # En frío (propio o de otro pedido que todavía no arrancó), o si llegó
        # mientras el ticker está pidiendo (Megaweb tardó más que D_est):
        # esperar ese pedido, con tope por los 30s de timeout de API
        # Gateway/CloudFront.
        if cold or _coches_wake.is_set() or _coches_fetching:
            generation = _coches_generation
            _coches_cond.wait_for(
                lambda: _coches_generation > generation,
                timeout=COCHES_MAX_WAIT_SECONDS,
            )

        entry = _coches_entry
        if entry is None or time.time() - entry[1] >= COCHES_MAX_STALE_SECONDS:
            return _error_response(*(_coches_error or (
                {"ok": False, "error": "Megaweb está tardando en responder."},
                504,
            )))

        coches_json, fetched_at = entry
        head = json.dumps({
            "ok": True,
            "actualizado": fetched_at,
            "proximo_en": round(_proximo_en(), 1),
            # True = el último pedido a Megaweb falló y estos son los últimos
            # datos buenos que se tienen.
            "stale": _coches_error is not None,
        })

    # Se empalma la lista ya serializada en vez de volver a serializarla.
    return head[:-1].encode() + b',"coches":' + coches_json + b"}", 200


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
