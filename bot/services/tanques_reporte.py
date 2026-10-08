"""
tanques_reporte.py
------------------
Los tanques de un reporte de Limpieza o Presupuestos.

Un edificio puede tener más de un cuerpo (dos edificios en la misma dirección) y más de un
tanque de cada tipo (2 reservas, y a veces 2 cisternas). El operario los carga de a uno, todos
los que haya, y a cada uno se le dice de qué cuerpo es si el edificio tiene más de uno.

  user_data["tanques"] = [{"id": "t1", "tipo": "CISTERNA", "cuerpo": None}, ...]   (en orden)
  user_data["cuerpos"] = 1, 2 o 3
  datos de cada tanque: user_data[f"{campo}_{id}"], campo en CAMPOS (ej: "repairs_t2")
  fotos e ítems de reparación: user_data["fotos_reparaciones"][id], ["items_reparacion"][id]

Nombre para el operario, el mail y el informe: "Cisterna", "Reserva 2 (fondo)". El número va
solo si hay más de un tanque de ese tipo; el cuerpo, solo si el edificio tiene más de uno.
"""

TIPOS = ("CISTERNA", "RESERVA", "INTERMEDIARIO")
CUERPOS = {"frente": "frente", "fondo": "fondo", "izquierda": "izquierda", "derecha": "derecha"}

# campo -> etiqueta (en el orden en que se preguntan)
CAMPOS = {
    "measure":          "Medida",
    "tapas_inspeccion": "Tapas inspección",
    "tapas_acceso":     "Tapas acceso",
    "sealing":          "Sellado",
    "repairs":          "Reparaciones",
    "suggestions":      "Sugerencias",
}


def clave(campo: str, tanque_id: str) -> str:
    return f"{campo}_{tanque_id}"


def lista(user_data: dict) -> list:
    return user_data.setdefault("tanques", [])


def buscar(user_data: dict, tanque_id: str):
    return next((t for t in lista(user_data) if t["id"] == tanque_id), None)


def tipo(user_data: dict, tanque_id: str) -> str:
    t = buscar(user_data, tanque_id)
    return t["tipo"] if t else ""


def nuevo(user_data: dict, tipo_tanque: str, cuerpo: str = None) -> str:
    """Agrega un tanque y devuelve su id."""
    tanques = lista(user_data)
    numero = max((int(t["id"][1:]) for t in tanques), default=0) + 1
    tanque_id = f"t{numero}"
    tanques.append({"id": tanque_id, "tipo": tipo_tanque, "cuerpo": cuerpo})
    return tanque_id


def tiene_datos(user_data: dict, tanque_id: str) -> bool:
    return any(user_data.get(clave(c, tanque_id)) for c in CAMPOS) or \
        bool(user_data.get("fotos_reparaciones", {}).get(tanque_id))


def descartar_vacios(user_data: dict) -> None:
    """Saca los tanques que se empezaron y no tienen nada (ej: "atrás" desde la medida)."""
    user_data["tanques"] = [t for t in lista(user_data) if tiene_datos(user_data, t["id"])]


def nombre(user_data: dict, tanque_id: str) -> str:
    t = buscar(user_data, tanque_id)
    if not t:
        return ""
    texto = t["tipo"].capitalize()
    mismos = [x["id"] for x in lista(user_data) if x["tipo"] == t["tipo"]]
    if len(mismos) > 1:
        texto += f" {mismos.index(tanque_id) + 1}"
    if t.get("cuerpo"):
        texto += f" ({CUERPOS.get(t['cuerpo'], t['cuerpo'])})"
    return texto


def datos(user_data: dict, tanque_id: str) -> dict:
    """{campo: valor} de un tanque (solo los cargados)."""
    return {c: user_data[clave(c, tanque_id)] for c in CAMPOS if user_data.get(clave(c, tanque_id))}
