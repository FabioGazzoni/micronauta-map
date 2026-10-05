import json
import logging
import re
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

# Solo lo usa el hilo ticker de coches (megaweb_service), así que no hace
# falta lock.
_index = None  # (por_nombre: {nombre normalizado: cuit}, etiquetas: {cuit: nombre visible})
_loaded_at = 0.0
_next_attempt = 0.0
_cache_file_checked = False
_last_report = None


def normalize_name(name) -> str:
    """
    Misma regla para Megaweb y para la tabla: sin acentos, minúsculas, sin
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
    """Lista vigente; la relee cada hora y, si falla, sigue con la última buena."""
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


def _report(sin_match, habilitadas_sin_coches):
    """Loguea solo cuando cambia, para no repetirlo en cada tick de 30s."""
    global _last_report

    report = (frozenset(sin_match), frozenset(habilitadas_sin_coches))
    if report == _last_report:
        return
    _last_report = report

    logger.info(
        "Empresas de Megaweb no habilitadas o sin coincidencia (%d): %s",
        len(sin_match), sorted(sin_match),
    )
    if habilitadas_sin_coches:
        logger.warning(
            "Empresas habilitadas sin coches en Megaweb (sin unidades activas o "
            "nombre que no coincide; ver EMPRESAS_ALIASES): %s",
            sorted(habilitadas_sin_coches),
        )


def filtrar_coches(coches):
    """
    Deja solo los coches de empresas habilitadas y les agrega empresa_cuit y
    empresa_grupo (nombre visible). Con el filtro desactivado se agrupa por
    empresa_nombre, como antes.
    """
    if not EMPRESAS_FILTER_ENABLED:
        for c in coches:
            c["empresa_cuit"] = None
            c["empresa_grupo"] = c.get("empresa_nombre")
        return coches

    index = _get_index()
    if index is None:
        logger.error("Sin lista de empresas habilitadas: no se muestra ningún coche.")
        return []

    por_nombre, etiquetas = index
    aliases = {normalize_name(k): str(v) for k, v in EMPRESAS_ALIASES.items()}

    filtrados = []
    sin_match = set()
    for c in coches:
        nombre = normalize_name(c.get("empresa_nombre"))
        cuit = por_nombre.get(nombre) or aliases.get(nombre)
        if cuit not in etiquetas:
            sin_match.add(c.get("empresa_nombre") or "")
            continue
        c["empresa_cuit"] = cuit
        c["empresa_grupo"] = etiquetas[cuit]
        filtrados.append(c)

    con_coches = {c["empresa_cuit"] for c in filtrados}
    _report(sin_match, {etiquetas[cuit] for cuit in etiquetas if cuit not in con_coches})

    return filtrados
