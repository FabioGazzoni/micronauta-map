import json
import logging
import re
import threading
import time
import unicodedata

from app.config import (
    EMPRESAS_ALIASES,
    EMPRESAS_CACHE_FILE,
    EMPRESAS_FILTER_ENABLED,
    EMPRESAS_REFRESH_SECONDS,
    EMPRESAS_RETRY_SECONDS,
    EMPRESAS_TABLE_ARN,
)
from app.repositories import empresas_repository

logger = logging.getLogger(__name__)

# Lo leen los pedidos a /api/empresas (varios hilos de Flask a la vez).
_lock = threading.Lock()
_index = None  # (por_nombre: {nombre normalizado: cuit}, etiquetas: {cuit: nombre visible})
_loaded_at = 0.0
_next_attempt = 0.0
_cache_file_checked = False


def normalize_name(name) -> str:
    """
    Misma regla para Megaweb y para la tabla (y la misma que
    normalizeEmpresaName en static/app.js): sin acentos, minúsculas, sin
    puntos ni comillas ("S.A.T." -> "sat") y cualquier otro signo como
    espacio, colapsando espacios. "S.A.T. - HIGUERAS" -> "sat higueras".
    """
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = text.encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[.,'`\"]", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


def _business_order(business):
    business_id = str(business.get("id", ""))
    return (len(business_id), business_id)  # "98" antes que "100"


def build_index(businesses):
    """
    Mismo CUIT = misma empresa. Nombre visible: el del business si todas sus
    sub-empresas comparten CUIT; si no, el de la primera sub-empresa de cada
    CUIT. Se mapean al CUIT los nombres de las sub-empresas y, si es único,
    también el del business.
    """
    por_nombre = {}
    etiquetas = {}

    def map_name(name, cuit):
        key = normalize_name(name)
        if not key:
            return
        previous = por_nombre.setdefault(key, cuit)
        if previous != cuit:
            logger.warning(
                "Nombre %r aparece con dos CUIT (%s y %s); se usa %s.",
                name, previous, cuit, previous,
            )

    for business in sorted(businesses, key=_business_order):
        subs = [
            s for s in (business.get("download_data") or {}).get("sub_empresas") or []
            if s.get("cuit") is not None
        ]
        cuits = [str(int(s["cuit"])) for s in subs]
        unico = len(set(cuits)) == 1 and business.get("name")

        for sub, cuit in zip(subs, cuits):
            etiquetas.setdefault(cuit, business["name"] if unico else sub.get("name"))
            map_name(sub.get("name"), cuit)

        if unico:
            map_name(business["name"], cuits[0])

    return por_nombre, etiquetas


def _load_cache_file():
    global _index, _loaded_at

    try:
        cached = json.loads(EMPRESAS_CACHE_FILE.read_text())
        _index = build_index(cached["businesses"])
        _loaded_at = cached["loaded_at"]
        logger.info("Empresas habilitadas: cargada la última lista buena de disco.")
    except FileNotFoundError:
        pass
    except Exception:
        logger.exception("No se pudo leer %s.", EMPRESAS_CACHE_FILE)


def _save_cache_file(businesses, loaded_at):
    try:
        EMPRESAS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        EMPRESAS_CACHE_FILE.write_text(
            json.dumps({"loaded_at": loaded_at, "businesses": businesses}, default=str)
        )
    except Exception:
        logger.exception("No se pudo guardar %s.", EMPRESAS_CACHE_FILE)


def _get_index():
    """Lista vigente; la relee una vez por día y, si falla, sigue con la última buena."""
    global _index, _loaded_at, _next_attempt, _cache_file_checked

    if not _cache_file_checked:
        _cache_file_checked = True
        _load_cache_file()

    now = time.time()
    if now - _loaded_at < EMPRESAS_REFRESH_SECONDS or now < _next_attempt:
        return _index

    try:
        businesses = empresas_repository.scan_habilitadas(EMPRESAS_TABLE_ARN)
    except Exception:
        logger.exception(
            "No se pudo leer empresas habilitadas de DynamoDB; se sigue con la última lista buena."
        )
        _next_attempt = now + EMPRESAS_RETRY_SECONDS
        return _index

    _index = build_index(businesses)
    _loaded_at = now
    _save_cache_file(businesses, now)
    logger.info(
        "Empresas habilitadas: %d business, %d empresas (CUIT), %d nombres.",
        len(businesses), len(_index[1]), len(_index[0]),
    )
    return _index


def get_empresas():
    """
    Devuelve (body, status) para /api/empresas: solo las habilitadas, cada una
    con sus nombres ya normalizados (incluidos los alias de config) para que
    el front cruce los coches por empresa_nombre. Con el filtro desactivado,
    empresas = None y el front agrupa por empresa_nombre.
    """
    if not EMPRESAS_FILTER_ENABLED:
        return {"ok": True, "empresas": None}, 200

    with _lock:
        index = _get_index()
        loaded_at = _loaded_at

    if index is None:
        return {"ok": False, "error": "No hay lista de empresas habilitadas disponible."}, 503

    por_nombre, etiquetas = index
    nombres = {cuit: set() for cuit in etiquetas}
    for nombre, cuit in por_nombre.items():
        nombres[cuit].add(nombre)
    for alias, cuit in EMPRESAS_ALIASES.items():
        if str(cuit) in nombres:
            nombres[str(cuit)].add(normalize_name(alias))

    empresas = [
        {"cuit": cuit, "nombre": etiquetas[cuit], "nombres": sorted(nombres[cuit])}
        for cuit in sorted(etiquetas, key=lambda c: normalize_name(etiquetas[c]))
    ]
    return {"ok": True, "actualizado": loaded_at, "empresas": empresas}, 200
