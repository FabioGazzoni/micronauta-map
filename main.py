import logging

from flask import Flask

from app.api.map_router import bp as map_router
from app.services import auth_service
from app.utils.network import local_lan_ip

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def create_app() -> Flask:
    flask_app = Flask(__name__, static_folder="static", static_url_path="/static")
    flask_app.register_blueprint(map_router)
    return flask_app


app = create_app()


if __name__ == "__main__":
    # Login inicial contra Megaweb; si falla queda logueado el motivo y los
    # endpoints /api/* reintentan solos en la primera consulta.
    auth_service.ensure_logged_in()

    lan_ip = local_lan_ip()

    print("")
    print("===================================================")
    print(" MAPA MEGAWEB · MOBILE TESTING")
    print(" PC:     http://127.0.0.1:5000")
    if lan_ip:
        print(f" MOBILE: http://{lan_ip}:5000")
        print("         (celular y PC deben estar en la misma red)")
    else:
        print(" MOBILE: consultá la IPv4 de esta PC y usá :5000")
    print("===================================================")
    print("")

    # 0.0.0.0 permite acceder desde otros dispositivos de la red local.
    # La aplicación sigue siendo de testing y no debe exponerse a Internet.
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
