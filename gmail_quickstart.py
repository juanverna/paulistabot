from __future__ import print_function
import os.path
import json

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from googleapiclient.discovery import build

# 1. Definimos el ámbito de permisos: solo lectura de Gmail
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def main():
    creds = None
    # 2. Si ya tenemos un token (autenticación previa), lo cargamos
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    # 3. Si no hay credenciales válidas, iniciamos el flujo de OAuth
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())  # refrescar token expirado
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES
            )
            creds = flow.run_local_server(port=0)  # abre navegador para logueo

        # 4. Guardamos el token para futuros usos
        with open('token.json', 'w') as token_file:
            token_file.write(creds.to_json())

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
