"""Ensayo HTTP real sobre una instalación DEMO. No usar contra producción.

Requiere seed_demo previo, DEMO_PASSWORD y BASE_URL (default localhost:8002).
Crea una adjudicación de un recurso demo y la termina antes de salir.
"""

import json
import os
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

base = os.environ.get("BASE_URL", "http://127.0.0.1:8002").rstrip("/")
password = os.environ.get("DEMO_PASSWORD")
if not password:
    raise SystemExit("Defina DEMO_PASSWORD para la instalación demo.")


def call(method, path, payload=None, token=None, key=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if key:
        headers["Idempotency-Key"] = key
    body = None if payload is None else json.dumps(payload).encode()
    request = Request(base + path, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=40) as response:
            data = response.read()
            return response.status, json.loads(data) if data else None
    except HTTPError as exc:
        raise SystemExit(f"HTTP {exc.code} en {method} {path}: {exc.read().decode()}") from exc


def login(username):
    return call("POST", "/login", {"username": username, "password": password})[1]["access"]


assert call("GET", "/health/ready/")[0] == 200
service = login("bonita_demo")
ngo = login("ong_demo")
org_id = call("GET", "/api/v1/auth/me/", token=ngo)[1]["organization"]
inventory_path = "/api/v1/inventory/?organization=" + org_id + "&resource_code=food-ration"
before = call("GET", inventory_path, token=ngo)[1]["results"][0]
if before["available_quantity"] < 1:
    raise SystemExit("La ONG demo no tiene una ración disponible.")
reference = "smoke-" + uuid.uuid4().hex
item = {
    "organization": org_id,
    "resource_code": "food-ration",
    "lot_ref": "smoke-lot",
    "quantity": 1,
    "risk_level": "low",
}
evaluation = call("POST", "/api/v1/validations/", {"items": [item]}, service)[1]
assert evaluation["reserves_resources"] is False
assignment = evaluation["items"][0]["recommended_assignment"]
if assignment not in ("main", "support"):
    raise SystemExit("La ONG demo no tiene habilitación vigente para esta tarea.")
award = {
    "project": {"external_id": reference, "title": "Ensayo HTTP de integración", "risk_level": "low"},
    "items": [{**item, "assignment": assignment}],
}
code, project = call("POST", "/api/v1/commitments/", award, service, reference)
assert code == 201
code, repeated = call("POST", "/api/v1/commitments/", award, service, reference)
assert code == 200 and repeated["id"] == project["id"]
commitment_id = project["commitments"][0]["id"]
for _ in range(2):
    assert (
        call("POST", f"/api/v1/commitments/{commitment_id}/complete/", {"notes": "Ensayo terminado"}, ngo)[0]
        == 200
    )
for _ in range(2):
    closed = call("POST", f"/api/v1/projects/{project['id']}/close/", {}, service)[1]
    assert closed["status"] == "completed"
after = call("GET", inventory_path, token=ngo)[1]["results"][0]
assert after["reserved_quantity"] == before["reserved_quantity"]
print("HTTP OK: JWT, consulta, validación, compromiso, reintento, liberación y cierre bilateral.")
