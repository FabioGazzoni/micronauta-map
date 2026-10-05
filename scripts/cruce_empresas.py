"""
Valida el cruce entre empresas de Megaweb y empresas habilitadas de
micronauta_businesses, con la misma normalización que usa el backend.

  En la EC2 (con acceso a la tabla y el backend con EMPRESAS_FILTER_ENABLED=false):
     docker compose run --rm -v "$PWD/scripts:/app/scripts" backend \\
       python scripts/cruce_empresas.py --dynamo http://backend:5000/api/coches

  Sin acceso a la tabla:
  1) Exportar habilitadas (alguien con acceso a la cuenta 417755752792):
     aws dynamodb scan --region us-east-2 --table-name micronauta_businesses \\
       --filter-expression "is_downloaded = :t" \\
       --expression-attribute-values '{":t":{"BOOL":true}}' \\
       --projection-expression "id, #n, download_data.sub_empresas" \\
       --expression-attribute-names '{"#n":"name"}' > habilitadas.json

  2) Con el backend corriendo con EMPRESAS_FILTER_ENABLED=false:
     python scripts/cruce_empresas.py habilitadas.json [http://localhost:5000/api/coches]
     (el segundo argumento también puede ser un archivo con la respuesta de /api/coches)
"""
import difflib
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import EMPRESAS_TABLE_ARN  # noqa: E402
from app.repositories.empresas_repository import deserialize, scan_habilitadas  # noqa: E402
from app.services.empresas_service import build_index, normalize_name  # noqa: E402


def main():
    habilitadas_path = sys.argv[1]
    coches_source = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:5000/api/coches"

    if habilitadas_path == "--dynamo":
        businesses = scan_habilitadas(EMPRESAS_TABLE_ARN)
    else:
        items = json.loads(Path(habilitadas_path).read_text())["Items"]
        businesses = [deserialize(i) for i in items]
    por_nombre, etiquetas = build_index(businesses)

    if coches_source.startswith("http"):
        coches = json.load(urllib.request.urlopen(coches_source))["coches"]
    else:
        coches = json.loads(Path(coches_source).read_text())["coches"]

    nombres_megaweb = sorted({c.get("empresa_nombre") or "" for c in coches} - {""})

    por_cuit = {cuit: [] for cuit in etiquetas}
    sin_match = []
    for nombre in nombres_megaweb:
        cuit = por_nombre.get(normalize_name(nombre))
        if cuit:
            por_cuit[cuit].append(nombre)
        else:
            sin_match.append(nombre)

    print(f"Habilitadas: {len(businesses)} business, {len(etiquetas)} empresas (CUIT)")
    print(f"Megaweb: {len(nombres_megaweb)} nombres de empresa\n")

    print("== Empresas habilitadas CON coincidencia en Megaweb")
    for cuit, nombres in sorted(por_cuit.items(), key=lambda x: etiquetas[x[0]]):
        if nombres:
            print(f"  {etiquetas[cuit]}  (CUIT {cuit}) <- {nombres}")

    print("\n== Empresas habilitadas SIN coincidencia (revisar: ¿alias?)")
    normalizados = {normalize_name(n): n for n in sin_match}
    for cuit, nombres in sorted(por_cuit.items(), key=lambda x: etiquetas[x[0]]):
        if nombres:
            continue
        propios = [n for n, c in por_nombre.items() if c == cuit]
        parecidos = {
            normalizados[m]
            for n in propios
            for m in difflib.get_close_matches(n, normalizados, n=3, cutoff=0.6)
        }
        print(f"  {etiquetas[cuit]}  (CUIT {cuit})  nombres en tabla: {propios}")
        if parecidos:
            print(f"      parecidos en Megaweb: {sorted(parecidos)}")

    print(f"\n== Nombres de Megaweb sin coincidencia ({len(sin_match)}; incluye no habilitadas)")
    for nombre in sin_match:
        print(f"  {nombre}")


if __name__ == "__main__":
    main()
