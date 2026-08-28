from flask import Blueprint, current_app, jsonify

from app.services import megaweb_service

bp = Blueprint("map", __name__)


@bp.route("/")
def index():
    return current_app.send_static_file("index.html")


@bp.route("/api/coches")
def coches():
    body, status = megaweb_service.get_coches()
    return jsonify(body), status


@bp.route("/api/trazas")
def trazas():
    body, status = megaweb_service.get_trazas()
    return jsonify(body), status


@bp.route("/api/clientes")
def clientes():
    body, status = megaweb_service.get_clientes()
    return jsonify(body), status
