from __future__ import print_function
import os
import json

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from googleapiclient.discovery import build

# 1. Definimos el ámbito de permisos: solo lectura de Gmail
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def _env_json(key):
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(f"Variable de entorno requerida no encontrada: {key}")
    return json.loads(value)

def main():
    creds = None
    # 2. Si ya tenemos un token (autenticación previa), lo cargamos desde GMAIL_TOKEN_JSON
    if os.getenv('GMAIL_TOKEN_JSON'):
        creds = Credentials.from_authorized_user_info(_env_json('GMAIL_TOKEN_JSON'), SCOPES)

    # 3. Si no hay credenciales válidas, iniciamos el flujo de OAuth
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())  # refrescar token expirado
        else:
            flow = InstalledAppFlow.from_client_config(
                _env_json('GOOGLE_OAUTH_CLIENT_JSON'), SCOPES
            )
            creds = flow.run_local_server(port=0)  # abre navegador para logueo

            # 4. El token nuevo va a la variable de entorno, nunca a un archivo del repo
            print('Token nuevo: guardalo en la variable de entorno GMAIL_TOKEN_JSON:')
            print(creds.to_json())

    # 5. Construimos el servicio de la API de Gmail
    service = build('gmail', 'v1', credentials=creds)

    # 6. Hacemos una petición para listar los primeros 10 mensajes
    results = service.users().messages().list(userId='me', maxResults=10).execute()
    messages = results.get('messages', [])

    if not messages:
        print('No se encontraron mensajes.')
    else:
        print('IDs de los primeros 10 mensajes:')
        for msg in messages:
            print(msg['id'])

if __name__ == '__main__':
    main()
