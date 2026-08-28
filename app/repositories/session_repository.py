import logging
from enum import Enum

import requests

from app.config import MEGA_BASE
from app.utils.scraper.scrap import Scraper

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,es-AR;q=0.8,es;q=0.7",
    "Connection": "keep-alive",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": MEGA_BASE.rsplit("/megaweb", 1)[0],
    "Referer": f"{MEGA_BASE}/index.php",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
}

DEFAULT_TIMEOUT = 30


class ERROR(Enum):
    OK = "200 OK"
    PROXY_ERROR = "502 Proxy Error"
    SESSION_EXPIRED = "Login"


class SessionUnusableError(Exception):
    """
    La sesión contra Megaweb quedó inutilizable (expirada o bloqueada detrás
    del proxy). El llamador debe descartarla y forzar un nuevo login.
    """

    def __init__(self, reason: str):
        self.reason = reason  # "proxy_error" | "session_expired"
        super().__init__(reason)


class MegawebUnavailableError(Exception):
    """
    Megaweb respondió con un status HTTP real distinto de 200 y contenido no
    reconocible: problema de servidor/proxy más serio que una sesión vencida.
    """


session = requests.Session()
session.headers.update(DEFAULT_HEADERS)


def delete_session():
    session.cookies.clear()


def _verify_response(response: requests.Response) -> ERROR:
    title_page = Scraper(response.text).get_title_page()
    if title_page == ERROR.PROXY_ERROR.value:
        return ERROR.PROXY_ERROR
    if title_page == ERROR.SESSION_EXPIRED.value:
        return ERROR.SESSION_EXPIRED
    return ERROR.OK


def send_request(url, data=None, headers=None, timeout=None, counter=0) -> requests.Response:
    """POST contra Megaweb."""
    return _send_request("post", url, data, headers, timeout, counter)


def send_get_request(url, params=None, headers=None, timeout=None, counter=0) -> requests.Response:
    """GET contra Megaweb."""
    return _send_request("get", url, params, headers, timeout, counter)


def _send_request(method, url, data, headers, timeout, counter) -> requests.Response:
    """
    Clasificación de fallas:
    - Error de red transitorio (conexión o timeout): reintenta hasta 3 veces.
    - Página de Login o proxy bloqueado: SessionUnusableError, no se
      reintenta sobre la misma sesión, el llamador debe forzar un re-login.
    - Status != 200 con contenido no reconocible: MegawebUnavailableError.
    """
    if counter > 0:
        logger.warning("Reintento %d de send_request (%s)", counter, method)

    request_timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
    request_fn = session.get if method == "get" else session.post
    request_kwargs = {"params": data} if method == "get" else {"data": data}
    if headers:
        request_kwargs["headers"] = headers

    try:
        response = request_fn(url, timeout=request_timeout, **request_kwargs)
    except requests.exceptions.ConnectionError as e:
        logger.warning("Error de conexión: %s", e)
        if counter >= 3:
            logger.error("No se pudo conectar a Megaweb tras 3 intentos, abortando...")
            raise
        return _send_request(method, url, data, headers, timeout, counter + 1)
    except requests.exceptions.Timeout as e:
        logger.warning("Timeout de red tras %ss: %s", request_timeout, e)
        if counter >= 3:
            logger.error(
                "Megaweb no respondió dentro de %ss tras 3 intentos, abortando...",
                request_timeout,
            )
            raise MegawebUnavailableError(
                f"Megaweb no respondió dentro de {request_timeout}s tras 3 intentos"
            ) from e
        return _send_request(method, url, data, headers, timeout, counter + 1)

    match _verify_response(response):
        case ERROR.PROXY_ERROR:
            logger.warning("Sesión bloqueada detrás del proxy (502 Proxy Error)")
            raise SessionUnusableError("proxy_error")
        case ERROR.SESSION_EXPIRED:
            logger.warning("Sesión de Megaweb expirada (redirigido a Login)")
            raise SessionUnusableError("session_expired")
        case ERROR.OK:
            if response.status_code != 200:
                logger.error(
                    "Megaweb respondió status %s (title=%r) contra %s; "
                    "cuerpo (primeros 500 chars): %r",
                    response.status_code,
                    Scraper(response.text).get_title_page(),
                    url,
                    response.text[:500],
                )
                raise MegawebUnavailableError(
                    f"Megaweb respondió status {response.status_code}"
                )
            return response
