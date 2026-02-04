import os
import sys
import threading
import requests
from dotenv import load_dotenv
from azure.identity import InteractiveBrowserCredential

# --- LÓGICA DE CARGA DE .ENV COMPATIBLE CON PYINSTALLER (EXE) ---
if getattr(sys, 'frozen', False):
    application_path = sys._MEIPASS
else:
    application_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

load_dotenv(os.path.join(application_path, '.env'))
# ----------------------------------------------------------------

class MSGraphClient:
    """
    Cliente Graph con patrón Singleton y Thread-Safety.
    Gestiona la comunicación y rastrea el estado de la sesión de forma aislada por hilo.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(MSGraphClient, cls).__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized: return
        
        self.client_id = os.getenv('AZURE_CLIENT_ID')
        self.tenant_id = os.getenv('AZURE_TENANT_ID', 'common')
        self.scopes = ["User.Read", "Sites.Read.All", "Files.Read.All", "Sites.ReadWrite.All"]
        self.credential = None
        self.access_token = None
        
        # Estado Global
        self.is_session_valid = True
        self._token_lock = threading.Lock()
        
        # --- THREAD LOCAL STORAGE ---
        # Aquí guardamos variables que deben ser únicas para cada hilo (evita Race Conditions)
        self._thread_local = threading.local()
        
        self._initialized = True

    # --- PROPIEDADES THREAD-SAFE ---
    @property
    def last_error_code(self):
        """Devuelve el código de error de la última petición ESTE hilo."""
        return getattr(self._thread_local, 'last_error_code', 0)

    @last_error_code.setter
    def last_error_code(self, value):
        self._thread_local.last_error_code = value

    def _get_token(self):
        try:
            with self._token_lock:
                # Verificamos si el token actual sigue siendo válido (aprox)
                # Nota: last_error_code aquí es engañoso si usamos thread local, 
                # pero para 401 global usaremos una bandera simple si es necesario.
                # Por ahora, confiamos en la regeneración si es null.
                if self.access_token and self.is_session_valid:
                    return self.access_token

                if not self.credential:
                    print("🔄 Preparando inicio de sesión interactivo...")
                    self.credential = InteractiveBrowserCredential(
                        client_id=self.client_id, tenant_id=self.tenant_id
                    )
                
                token_data = self.credential.get_token("https://graph.microsoft.com/.default")
                self.access_token = token_data.token
                self.is_session_valid = True
                
                # Reiniciamos error en el hilo actual por limpieza
                self.last_error_code = 0
                return self.access_token
        except Exception as e:
            self.is_session_valid = False
            raise Exception(f"Error obteniendo token: {str(e)}")

    def _make_request(self, method, endpoint, json_data=None, return_raw=False, extra_headers=None):
        if not self.access_token: 
            try: self._get_token()
            except: return None

        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
        if extra_headers: headers.update(extra_headers)

        url = endpoint if endpoint.startswith("http") else f"https://graph.microsoft.com/v1.0{endpoint}"
        
        try:           
            if method == 'GET': response = requests.get(url, headers=headers, timeout=30)
            elif method == 'PATCH': response = requests.patch(url, headers=headers, json=json_data, timeout=30)
            elif method == 'POST': response = requests.post(url, headers=headers, json=json_data, timeout=30)
            elif method == 'DELETE': response = requests.delete(url, headers=headers, timeout=30)
            else: return None
            
            # --- GUARDADO SEGURO DEL CÓDIGO DE ESTADO ---
            # Esto ahora se guarda en self._thread_local.last_error_code
            self.last_error_code = response.status_code

            if response.status_code in [200, 201, 204]:
                return response if return_raw else (response.json() if response.content else {"success": True})
            
            elif response.status_code == 401:
                print("⚠️ Token expirado detectado en request.")
                self.is_session_valid = False
                # Intentar forzar refresh para la próxima
                self.access_token = None 
                return None
            else:
                # Imprimimos el error para debug, pero NO para 412 (Precondition Failed)
                # porque 412 es un flujo esperado que manejamos en el servicio.
                if response.status_code != 412:
                    print(f"❌ ERROR GRAPH API {response.status_code}: {response.text}")
                return None
                
        except Exception as e:
            print(f"❌ Error de conexión: {e}")
            self.is_session_valid = False
            return None

    def get(self, endpoint, extra_headers=None): return self._make_request('GET', endpoint, extra_headers=extra_headers)
    def patch(self, endpoint, json_data, extra_headers=None): return self._make_request('PATCH', endpoint, json_data, extra_headers=extra_headers)
    def post(self, endpoint, json_data, extra_headers=None): return self._make_request('POST', endpoint, json_data, extra_headers=extra_headers)
    def delete(self, endpoint, extra_headers=None): return self._make_request('DELETE', endpoint, extra_headers=extra_headers)
    
    def get_content(self, endpoint):
        response = self._make_request('GET', endpoint, return_raw=True)
        return response.content if response and response.status_code == 200 else None