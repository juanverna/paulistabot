#!/usr/bin/env python3
from __future__ import print_function
import os
import base64
import json
import re

import pandas as pd
import openai
import gspread
from google.oauth2.service_account import Credentials as SACreds
from google.oauth2.credentials import Credentials as UserCreds
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ----------------------------------
# 0) CONFIGURACIÓN — REEMPLAZA ESTOS VALORES
# ----------------------------------
TEMPLATE_DOC_ID       = '1iu940gYHMmKwuiWIgFOFeX4vmJU31pKhcbS_k6z6zO8'
openai.api_key        = os.getenv("OPENAI_API_KEY")
SPREADSHEET_ID        = '1T-metdRbD-8An2_-urfK7_cAkPmmtmA004BPCyLeU9Q'
SHEET_NAME            = 'REPARACIONES'
MAPPING_CSV           = 'Articulos Python - Hoja 1.csv'
MAX_EMAILS            = 2

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly"
]
SERVICE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents"
]

# ----------------------------------
# Helper: Parseo robusto de números desde strings de Sheets
# ----------------------------------
def parse_sheet_number(val_str):
    if not isinstance(val_str, str):
        try:
            return float(val_str)
        except:
            return 0
    s = val_str.strip()
    # Miles separados por punto: e.g. "1.234.567"
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", s):
        return int(s.replace('.', ''))
    # Separador decimal coma o punto
    norm = s.replace(',', '.')
    try:
        if '.' in norm:
            return float(norm)
        return int(norm)
    except ValueError:
        return 0

# ----------------------------------
# 1) AUTENTICACIÓN
# ----------------------------------
# Las credenciales de Google se leen de variables de entorno con el JSON completo,
# nunca de archivos del repo:
#   GOOGLE_OAUTH_CLIENT_JSON     cliente OAuth de Gmail (antes credentials.json)
#   GMAIL_TOKEN_JSON             token de usuario de Gmail (antes token.json)
#   GOOGLE_SERVICE_ACCOUNT_JSON  cuenta de servicio para Sheets/Drive/Docs (antes service_account.json)
def _env_json(key):
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(f"Variable de entorno requerida no encontrada: {key}")
    return json.loads(value)


def authenticate_gmail():
    creds = None
    if os.getenv("GMAIL_TOKEN_JSON"):
        creds = UserCreds.from_authorized_user_info(_env_json("GMAIL_TOKEN_JSON"), GMAIL_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_config(
                _env_json("GOOGLE_OAUTH_CLIENT_JSON"), GMAIL_SCOPES
            )
            creds = flow.run_local_server(port=0)
            print("Token nuevo: guardalo en la variable de entorno GMAIL_TOKEN_JSON (no en un archivo del repo):")
            print(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def _service_account_creds():
    return SACreds.from_service_account_info(
        _env_json("GOOGLE_SERVICE_ACCOUNT_JSON"), scopes=SERVICE_SCOPES
    )


def get_sheets_client():
    return gspread.authorize(_service_account_creds())


def get_drive_client():
    return build('drive', 'v3', credentials=_service_account_creds())


def get_docs_client():
    return build('docs', 'v1', credentials=_service_account_creds())

# ----------------------------------
# 2) AUXILIARES
# ----------------------------------
def extract_plain_text(msg):
    data = None
    for part in msg.get('payload', {}).get('parts', []):
        if part.get('mimeType') == 'text/plain':
            data = part['body']['data']
            break
    if not data:
        data = msg.get('payload', {}).get('body', {}).get('data')
    return base64.urlsafe_b64decode(data).decode('utf-8') if data else ''


def get_description_map():
    client = get_sheets_client()
    ws     = client.open_by_key(SPREADSHEET_ID).worksheet("DESCRIPCIONES")
    # Obtener todas las filas con datos (columnas A y B)
    all_values = ws.get_all_values()
    description_map = {}
    
    for row in all_values[1:]:  # Saltar encabezados
        if len(row) >= 2 and str(row[0]).strip() and str(row[1]).strip():
            codigo = str(row[0]).strip().upper()
            descripcion = str(row[1]).strip()
            description_map[codigo] = descripcion
    
    return description_map


def copy_template(drive_srv, report_dict):
    title = f"Presupuesto {report_dict['Dirección']} - {report_dict['Fecha']}"
    body  = {'name': title}
    new   = drive_srv.files().copy(fileId=TEMPLATE_DOC_ID, body=body).execute()
    drive_srv.permissions().create(
        fileId=new['id'],
        body={'type':'user','role':'writer','emailAddress':'jvergniaud17@gmail.com'}
    ).execute()
    return new['id']

# ----------------------------------
# 3) RELLENO DE DOCS
# ----------------------------------
def fill_placeholders(docs_srv, doc_id, report_dict, summary):
    requests = []
    
    # Extraer solo la fecha (sin hora) del campo Fecha
    fecha_original = report_dict.get("Fecha", "")
    fecha_solo_dia = fecha_original.split(" ")[0] if " " in fecha_original else fecha_original
    
    for ph, val in {
        "{{Dirección}}": report_dict["Dirección"],
        "{{Fecha}}": fecha_solo_dia,  # Solo el día, sin la hora
        "{{PrecioTotal}}": summary["total"],
        "{{Anticipo}}": summary["anticipo"],
        "{{Cuotas}}": summary["cuotas"],
        "{{NumCuotas}}": summary["num_cuotas"]
    }.items():
        requests.append({
            "replaceAllText": {
                "containsText": {"text": ph, "matchCase": True},
                "replaceText": str(val)
            }
        })
    
    # Usar las descripciones mejoradas para los items
    if len(summary['items']) == 1 and 'revoque' in summary['items'][0]['descripción'].lower():
        items_text = summary['items'][0]['descripción_final']
    else:
        items_text = "\n".join(f"- {itm['descripción_final']}" for itm in summary['items'])
    
    requests.append({
        "replaceAllText": {
            "containsText": {"text": "{{TablaItems}}", "matchCase": True},
            "replaceText": items_text
        }
    })
    docs_srv.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

# ----------------------------------
# 4) MAPEOS
# ----------------------------------
# Comentamos la línea del CSV que falta
# mapping_df = pd.read_csv(MAPPING_CSV)
PRICE_CELL_MAP = {
    ('CISTERNA','30'):'C4',('CISTERNA','40'):'C4',
    ('CISTERNA','50'):'C5',('CISTERNA','60'):'C5',('CISTERNA','80'):'C6',
    ('RESERVA','30'):'C4',('RESERVA','40'):'C4',
    ('RESERVA','50'):'C5',('RESERVA','60'):'C5',('RESERVA','80'):'C6',
    ('CISTERNA','47'):'C8',('CISTERNA','48'):'C8',('CISTERNA','49'):'C8',
    ('CISTERNA','50'):'C8',('CISTERNA','52'):'C8',
    ('RESERVA','47'):'C8',('RESERVA','48'):'C8',('RESERVA','49'):'C8',
    ('RESERVA','50'):'C8',('RESERVA','52'):'C8',
    ('CISTERNA','53.5'):'C11',('CISTERNA','56.5'):'C11',
    ('CISTERNA','54'):'C11',('CISTERNA','12'):'C11',('CISTERNA','49.5'):'C11',('CISTERNA','56'):'C11',
    ('RESERVA','53.5'):'C11',('RESERVA','56.5'):'C11',
    ('RESERVA','54'):'C11',('RESERVA','12'):'C11',('RESERVA','49.5'):'C11',('RESERVA','56'):'C11',
    ('CISTERNA','62'):'C13',('CISTERNA','69'):'C13',
    ('RESERVA','62'):'C13',('RESERVA','69'):'C13',
    ('CISTERNA','48'):'C15',('CISTERNA','49'):'C15',('CISTERNA','50'):'C15',
    ('CISTERNA','52'):'C15',('CISTERNA','54'):'C15',('CISTERNA','60'):'C15',
    ('RESERVA','48'):'C15',('RESERVA','49'):'C15',('RESERVA','50'):'C15',
    ('RESERVA','52'):'C15',('RESERVA','54'):'C15',('RESERVA','60'):'C15',
    ('CISTERNA','48'):'C18',('CISTERNA','49'):'C18',('CISTERNA','50'):'C18',
    ('CISTERNA','52'):'C18',('CISTERNA','54'):'C18',('CISTERNA','60'):'C18',
    ('RESERVA','48'):'C18',('RESERVA','49'):'C18',('RESERVA','50'):'C18',
    ('RESERVA','52'):'C18',('RESERVA','54'):'C18',('RESERVA','60'):'C18',
    ('AUTOMATICO',''):'C20',('BACTERIOLOGICO',''):'C22',
    ('FÍSICO QUÍMICO',''):'C23',('BAQ+FQ',''):'C24'
}

# ----------------------------------
# 5) PARSEO DE CORREOS
# ----------------------------------
def parse_report(text: str) -> dict:
    report, current = {}, None
    for line in text.splitlines():
        l = line.strip()
        if not l: continue
        if ':' in l:
            k, v = l.split(':', 1)
            report[k.strip()] = v.strip()
            current = k.strip()
        elif current:
            report[current] += ' ' + l
    return report


def get_repair_fields(report: dict) -> dict:
    return {k: v for k, v in report.items() if k.lower().startswith('reparaciones')}

# ----------------------------------
# 6) EXTRAER ÍTEMS CON OpenAI
# ----------------------------------
def find_product_description(detected_item: str, description_map: dict) -> str:
    """
    Busca la descripción adecuada para un producto detectado
    """
    detected_lower = detected_item.lower().strip()
    detected_upper = detected_item.upper().strip()
    
    # 1. Búsqueda exacta por código completo
    if detected_upper in description_map:
        return description_map[detected_upper]
    
    # 2. Búsqueda por códigos que contengan el texto detectado
    for codigo, descripcion in description_map.items():
        if detected_upper in codigo:
            return descripcion
    
    # 3. Búsqueda por palabras clave en el texto detectado
    for codigo, descripcion in description_map.items():
        # Extraer palabras del código para buscar coincidencias
        codigo_words = codigo.lower().split()
        detected_words = detected_lower.split()
        
        # Si alguna palabra del código aparece en el texto detectado
        for word in codigo_words:
            if len(word) >= 3 and word in detected_lower:
                return descripcion
    
    # 4. Búsqueda específica para casos comunes
    keyword_mappings = {
        'revoque': 'REVOQUE',
        'revocar': 'REVOQUE',
        'pintura': 'PINTURA',
        'limpieza': 'LIMPIEZA',
        'desinfeccion': 'DESINFECCIÓN',
        'clorado': 'CLORADO',
        'bacteriológico': 'BACTERIOLÓGICO',
        'bacteriologico': 'BACTERIOLÓGICO',
        'fisico': 'FÍSICO',
        'químico': 'QUÍMICO',
        'quimico': 'QUÍMICO',
        'automatico': 'AUTOMÁTICO',
        'automático': 'AUTOMÁTICO'
    }
    
    for keyword, codigo_buscar in keyword_mappings.items():
        if keyword in detected_lower:
            # Buscar códigos que contengan esta palabra clave
            for codigo, descripcion in description_map.items():
                if codigo_buscar in codigo:
                    return descripcion
    
    # 5. Si no encuentra coincidencia, devolver el texto original
    return detected_item


def extract_budget_items(repair_fields: dict) -> list:
    if not repair_fields or all(
        re.fullmatch(r'\s*nada\s*', v, flags=re.IGNORECASE)
        for v in repair_fields.values()
    ):
        return []
    
    # Fixed the f-string formatting error by using proper string concatenation
    examples = """Ejemplo 1:
Reparaciones CISTERNA: Presupuestar TITREA30
""" + '→ [{"subtanque":"CISTERNA","descripción":"TITREA30"}]' + """

Ejemplo 2:
Reparaciones RESERVA: revoque pared izquierda EA
""" + '→ [{"subtanque":"RESERVA","descripción":"revoque pared izquierda EA"}]' + """

Ejemplo 3 (múltiples ítems):
Reparaciones CISTERNA: Presupuestar TITCEA30 y revoque lateral derecho
""" + '''→ [
    {"subtanque":"CISTERNA","descripción":"TITCEA30"},
    {"subtanque":"CISTERNA","descripción":"revoque lateral derecho"}
]''' + """

Ahora convierte estos campos:
""" + json.dumps(repair_fields, ensure_ascii=False, indent=2) + """

Devuélvelo sólo como JSON lista de objetos con claves 'subtanque' y 'descripción'."""

    resp = openai.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role":"system","content":"Eres un asistente que extrae ítems a presupuestar."},
            {"role":"user","content":examples}
        ],
        temperature=0
    )
    try:
        content = resp.choices[0].message.content
        if content:
            return json.loads(content)
        return []
    except:
        return []

# ----------------------------------
# 7) ESCRIBIR IMPORTE EN I9:I…
# ----------------------------------
def update_presupuesto_online(items: list, reports: list):
   client    = get_sheets_client()
   sheet     = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
   start_row = 9
   updates   = []
   only_rev  = all(itm['descripción'].lower().strip().startswith('revoque') for itm in items)
   for idx, (itm, report) in enumerate(zip(items, reports)):
       sub = itm['subtanque'].upper(); raw = itm['descripción'].lower().strip(); row = start_row + idx
       if raw.startswith('revoque'):
           field = 'Medida principal' if sub == 'CISTERNA' else f"Medida {sub.capitalize()}"
           medidas = re.split(r'[/\s]+', report.get(field, '').strip())[:3]
           if len(medidas) >= 3:
               alto_m, ancho_m, prof_m = float(medidas[0])/100, float(medidas[1])/100, float(medidas[2])/100
               sheet.update('O5', [[alto_m]])
               sheet.update('O6', [[ancho_m]]) 
               sheet.update('O7', [[prof_m]])
           cell_map = {'frente':'R12','lateral':'R13','piso':'R14'} if only_rev else {'frente':'P12','lateral':'P13','piso':'P14'}
           surfaces = []
           if re.search(r'\b(f|frente|fondo|contrafrente)\b', raw): surfaces.append('frente')
           if re.search(r'\b(ld|li|lateral|lado)\b', raw): surfaces.append('lateral')
           if re.search(r'\b(p|piso)\b', raw): surfaces.append('piso')
           for surf in surfaces:
               val_str = sheet.acell(cell_map[surf]).value or ''
               num = parse_sheet_number(val_str)
               updates.append({'range': f'I{row}', 'values': [[num]]}); row += 1
           continue
       m = re.search(r'(\d+(\.\d+)?)', raw)
       if not m: continue
       measure = m.group(1)
       cell = PRICE_CELL_MAP.get((sub, measure))
       if not cell:
           print(f"⚠️ No mapping para ({sub}, {measure})")
           continue
       val_str = sheet.acell(cell).value or ''
       num = parse_sheet_number(val_str)
       updates.append({'range': f'I{row}', 'values': [[num]]})
   if updates:
       sheet.batch_update(updates)
   print(f"✅ Escribí {len(updates)} importes en I9:I{start_row + len(updates) - 1}")

# ----------------------------------
# 8) FLUJO PRINCIPAL
# ----------------------------------
def main():
    gmail_srv       = authenticate_gmail()
    sheets_cl       = get_sheets_client()
    drive_srv       = get_drive_client()
    docs_srv        = get_docs_client()
    description_map = get_description_map()

    resp = gmail_srv.users().messages().list(
        userId='me', q='subject:"Reporte de Servicio:"', maxResults=MAX_EMAILS
    ).execute()
    msgs = resp.get('messages', [])

    for m in msgs:
        msg           = gmail_srv.users().messages().get(
            userId='me', id=m['id'], format='full'
        ).execute()
        texto         = extract_plain_text(msg)
        report        = parse_report(texto)
        repair_fields = get_repair_fields(report)
        items         = extract_budget_items(repair_fields)

        if not items:
            print(f"📭 Mail {m['id']} sin ítems, salto.")
            continue

        # Agregar descripciones finales a cada item
        for item in items:
            item['descripción_final'] = find_product_description(item['descripción'], description_map)

        ws = sheets_cl.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
        ws.batch_clear(['O5:O7','I9:I18','R12:R14'])

        update_presupuesto_online(items, [report] * len(items))

        total      = ws.acell("C8").value
        anticipo   = ws.acell("J5").value
        num_cuotas = ws.acell("K5").value
        cuotas     = ws.acell("L5").value

        summary = {
            "items": items,
            "total": total,
            "anticipo": anticipo,
            "num_cuotas": num_cuotas,
            "cuotas": cuotas
        }

        doc_id = copy_template(drive_srv, report)
        fill_placeholders(docs_srv, doc_id, report, summary)

        print(f"✅ Presupuesto creado: https://docs.google.com/document/d/{doc_id}")
        print(f"📧 Items procesados: {len(items)}")
        for itm in items:
            print(f"   - {itm['subtanque']}: {itm['descripción']} → {itm['descripción_final']}")

if __name__ == "__main__":
    main()
