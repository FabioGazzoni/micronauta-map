import json

import requests

from app.config import LOGIN_CMD_URL, LOGIN_PAGE_URL, SESSION_CHECK_URL
from app.repositories.session_repository import (
    send_get_request,
    send_request,
    session as global_session,
)


def refresh_session_cookie():
    """
    GET a index.php para inicializar la cookie PHPSESSID antes de loguear.
    Sin sesión todavía, esa página siempre tiene título "Login" — es el
    resultado esperado, no una sesión vencida — así que se pega directo
    con la sesión (bypass de send_get_request/_verify_response, que
    interpretaría ese título como SessionUnusableError).
    """
    global_session.get(LOGIN_PAGE_URL, allow_redirects=True, timeout=30)


def login(username: str, password: str) -> requests.Response:
    payload = json.dumps({
        "cmd": "login",
        "form_login": {"username": username, "password": password},
        "device_token": None,
    })
    return send_request(LOGIN_CMD_URL, data=payload)


def is_login_response_ok(response: requests.Response) -> bool:
    try:
        data = response.json()
    except ValueError:
        data = json.loads(response.content.decode("utf-8", errors="ignore"))
    return data.get("ok") is not False


def has_active_session() -> bool:
    response = send_get_request(SESSION_CHECK_URL)
    try:
        return response.json().get("valid") is True
    except ValueError:
        return False
