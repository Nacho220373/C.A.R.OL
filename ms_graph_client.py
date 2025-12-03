import os
import threading

import requests
from dotenv import load_dotenv
from azure.identity import InteractiveBrowserCredential

# Cargar variables de entorno
load_dotenv()

class MSGraphClient:
    """
    Cliente usando 'InteractiveBrowserCredential'.
    Abre el navegador local para aprovechar la sesión corporativa existente.
    """

    def __init__(self):
        self.client_id = os.getenv('AZURE_CLIENT_ID')
        self.tenant_id = os.getenv('AZURE_TENANT_ID', 'common')
        
        # Scopes que necesitamos
        self.scopes = [
            "User.Read",
            "Sites.Read.All",
            "Files.Read.All",
            "Sites.ReadWrite.All" # Agregado para permisos de escritura
        ]
        self.credential = None
        self.access_token = None
        self._token_lock = threading.Lock()

    def _get_token(self):
        """Obtiene token abriendo el navegador del sistema."""
        try:
            with self._token_lock:
                if not self.credential:
                    print("🔄 Preparando inicio de sesión interactivo...")
                    # Esto abrirá tu navegador predeterminado
                    self.credential = InteractiveBrowserCredential(
                        client_id=self.client_id,
                        tenant_id=self.tenant_id
                    )

                # Solicitamos el token. El scope debe ir completo con el prefijo de Graph
                print("⏳ Solicitando token a Microsoft (mira tu navegador)...")
                token_data = self.credential.get_token("https://graph.microsoft.com/.default")
                
                self.access_token = token_data.token
                print("✅ ¡Token obtenido correctamente!")
                return self.access_token

        except Exception as e:
            raise Exception(f"Error obteniendo token: {str(e)}")

    def _make_request(self, method, endpoint, json_data=None):
        """Helper interno para manejar auth y reintentos."""
        if not self.access_token:
            self._get_token()

        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }

        url = endpoint if endpoint.startswith("http") else f"https://graph.microsoft.com/v1.0{endpoint}"
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers)
            elif method == 'PATCH':
                response = requests.patch(url, headers=headers, json=json_data)
            
            if response.status_code in [200, 201, 204]:
                return response.json() if response.content else {}
            elif response.status_code == 401:
                print("⚠️ Token expirado o inválido. Reintentando...")
                self._get_token() # Reintentar una vez
                headers['Authorization'] = f'Bearer {self.access_token}'
                if method == 'GET':
                    response = requests.get(url, headers=headers)
                elif method == 'PATCH':
                    response = requests.patch(url, headers=headers, json=json_data)
                return response.json() if response.status_code in [200, 201, 204] else None
            else:
                print(f"❌ Error HTTP {response.status_code}: {response.text}")
                return None
        except Exception as e:
            print(f"❌ Error de conexión: {e}")
            return None

    def get(self, endpoint):
        """Petición GET genérica."""
        return self._make_request('GET', endpoint)

    def patch(self, endpoint, json_data):
        """Petición PATCH para actualizaciones."""
        return self._make_request('PATCH', endpoint, json_data)

# --- BLOQUE DE PRUEBA ---
if __name__ == "__main__":
    try:
        print("🚀 Iniciando prueba de conexión con Azure Identity...")
        client = MSGraphClient()
        
        # 1. Prueba de Sitio
        hostname = os.getenv('SHAREPOINT_HOSTNAME')
        site_path = os.getenv('SHAREPOINT_SITE_PATH')
        
        print(f"🔍 Buscando sitio: {hostname}{site_path}")
        endpoint = f"/sites/{hostname}:{site_path}"
        
        data = client.get(endpoint)
        
        if data and 'id' in data:
            print("\n" + "="*40)
            print("✅ ¡CONEXIÓN CONFIRMADA CON SHAREPOINT!")
            print("="*40)
            print(f"📌 Nombre del Sitio: {data.get('displayName')}")
            print(f"🔑 Site ID: {data.get('id')}")
            print("-" * 30)
            print("¡Guarda este ID! Lo logramos.")
        else:
            print("\n❌ No se pudo conectar. Revisa el log de errores.")
            
    except Exception as e:
        print(f"\n❌ Ocurrió un error crítico: {e}")