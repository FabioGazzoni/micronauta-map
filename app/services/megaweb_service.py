from app.models.trazas_cache import TrazasCache
from app.repositories import megaweb_repository, session_repository
from app.services import auth_service

_trazas_cache = TrazasCache()

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


def get_coches():
    try:
        parsed = _call_with_retry(megaweb_repository.get_coches_raw)
    except session_repository.SessionUnusableError:
        return _SESSION_ERROR_RESPONSE
    except session_repository.MegawebUnavailableError as exc:
        return {"ok": False, "error": str(exc)}, 502
    except ValueError:
        return {"ok": False, "error": "Megaweb no devolvió JSON válido."}, 502

    if not isinstance(parsed, dict) or not parsed.get("ok"):
        return {
            "ok": False,
            "error": "Megaweb no devolvió una respuesta válida.",
            "remote": parsed,
        }, 502

    data = parsed.get("data") or {}
    coches = [_slim_coche(c) for c in (data.get("coches") or [])]

    return {
        "ok": True,
        "coches": coches,
        "refresco": data.get("refresco", "20"),
    }, 200


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
