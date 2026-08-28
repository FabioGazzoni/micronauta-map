import logging
import threading

from app.config import MEGAWEB_PASSWORD, MEGAWEB_USERNAME
from app.repositories import auth_repository, megaweb_repository, session_repository

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_logged_in = False


def _perform_login() -> bool:
    global _logged_in

    if not MEGAWEB_USERNAME or not MEGAWEB_PASSWORD:
        logger.error(
            "Faltan MEGAWEB_USERNAME/MEGAWEB_PASSWORD (configuralas en .env)."
        )
        _logged_in = False
        return False

    try:
        session_repository.delete_session()
        auth_repository.refresh_session_cookie()

        response = auth_repository.login(MEGAWEB_USERNAME, MEGAWEB_PASSWORD)
        if not auth_repository.is_login_response_ok(response):
            logger.error("Login contra Megaweb rechazado (credenciales inválidas).")
            _logged_in = False
            return False

        # Sin este warm-up, Megaweb no deja pedir gmap_xml.php (ver MIGRATION_PLAN.md).
        megaweb_repository.get_clientes_raw()
    except Exception:
        # Nunca debe tumbar el arranque del server ni una request: si el
        # login falla (red, proxy, Megaweb caído), se loguea y se reintenta
        # en la próxima consulta.
        logger.exception("Login/warm-up contra Megaweb falló.")
        _logged_in = False
        return False

    logger.info("Login contra Megaweb exitoso.")
    _logged_in = True
    return True


def ensure_logged_in(force: bool = False) -> bool:
    with _lock:
        if _logged_in and not force:
            return True
        return _perform_login()


def is_logged_in() -> bool:
    return _logged_in
