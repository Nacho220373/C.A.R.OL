import os
import hashlib
import traceback
import json
import threading
import time
from datetime import datetime

# Importamos desde el módulo raíz porque main.py agrega la raíz al path
try:
    from ms_graph_client import MSGraphClient
except ImportError:
    # Fallback por si acaso se ejecuta desde otro contexto
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from ms_graph_client import MSGraphClient

class ErrorLoggerService:
    """
    Servicio dedicado a la telemetría de errores (SoC).
    Responsabilidad: Registrar errores en SharePoint List 'AppErrorLog'.
    Patrón: Singleton implícito + Resolución Dinámica de ID + Cola Offline.
    """
    
    LIST_NAME = "AppErrorLog"
    OFFLINE_FILE = "pending_errors.json"

    def __init__(self):
        self.client = MSGraphClient()
        self.site_id = os.getenv('SHAREPOINT_SITE_ID')
        self.app_version = "v1.1" 
        self.list_id = None # Aquí guardaremos el GUID real de la lista
        
        # Inicialización en segundo plano para no bloquear el arranque de la UI
        threading.Thread(target=self._init_service, daemon=True).start()

    def _init_service(self):
        """Tarea de arranque: Resolver ID y vaciar cola."""
        if self._resolve_list_id():
            self._flush_offline_queue()

    def _resolve_list_id(self):
        """
        CRÍTICO: Busca el GUID de la lista usando su nombre visible.
        La API de Graph a veces falla si usas el nombre directamente en la URL.
        """
        try:
            if self.list_id: return True
            
            # Buscamos la lista por su nombre visible (Display Name)
            # Nota: filter=displayName eq 'Name' es más seguro
            endpoint = f"/sites/{self.site_id}/lists?filter=displayName eq '{self.LIST_NAME}'&select=id,name"
            data = self.client.get(endpoint)
            
            if data and 'value' in data and len(data['value']) > 0:
                self.list_id = data['value'][0]['id']
                print(f"✅ [Logger] Conectado exitosamente a la lista: {self.list_id}")
                return True
            else:
                print(f"⚠️ [Logger] No se encontró la lista '{self.LIST_NAME}' en el sitio. Verifica el nombre en SharePoint.")
                return False
        except Exception as e:
            print(f"❌ [Logger] Error fatal resolviendo ID de lista: {e}")
            return False

    def log_error(self, exception, context_msg="", user="Unknown"):
        """
        Punto de entrada principal. 
        Guarda en local INMEDIATAMENTE y luego intenta subir a la nube.
        """
        try:
            # 1. Preparar datos
            tb_str = "".join(traceback.format_exception(None, exception, exception.__traceback__))
            error_msg = f"{context_msg}: {str(exception)}" if context_msg else str(exception)
            
            # Firma única para agrupar errores repetidos
            if exception.__traceback__:
                tb_last = traceback.extract_tb(exception.__traceback__)[-1]
                signature_base = f"{type(exception).__name__}|{tb_last.filename}:{tb_last.lineno}"
            else:
                signature_base = f"{type(exception).__name__}|{str(exception)}"
                
            error_signature = hashlib.md5(signature_base.encode()).hexdigest()

            payload = {
                "Title": error_signature,
                "ErrorMessage": error_msg[:250], 
                "StackTrace": tb_str[:1500], # Aumenté un poco el límite
                "LastUser": str(user),
                "AppVersion": self.app_version,
                "OccurrenceCount": 1,
                "Timestamp": datetime.now().isoformat()
            }

            # 2. Intentar subir a SharePoint
            # Lanzamos hilo para no congelar la UI si internet está lento
            threading.Thread(target=self._worker_log_to_sharepoint, args=(payload,), daemon=True).start()
                
        except Exception as e:
            # Si falla el propio logger, imprimimos en consola de emergencia
            print(f"❌ CRITICAL LOGGER FAILURE: {e}")
            # Intento desesperado de log local simple
            with open("panic.log", "a") as f:
                f.write(f"{datetime.now()}: {str(e)}\n")

    def _worker_log_to_sharepoint(self, payload):
        """Lógica de subida usando el ID resuelto."""
        try:
            # Asegurarnos de tener el ID
            if not self.list_id:
                if not self._resolve_list_id():
                    self._save_offline(payload)
                    return

            signature = payload['Title']
            
            # A. Buscar error existente
            # Usamos self.list_id en lugar de self.LIST_NAME
            endpoint = f"/sites/{self.site_id}/lists/{self.list_id}/items?filter=fields/Title eq '{signature}'"
            headers = {"Prefer": "HonorNonIndexedQueriesWarningMayFailRandomly"}
            
            existing = self.client.get(endpoint, extra_headers=headers)
            
            if existing and 'value' in existing and len(existing['value']) > 0:
                # B. EXISTE -> Actualizar contador
                item_id = existing['value'][0]['id']
                current_fields = existing['value'][0].get('fields', {})
                current_count = current_fields.get('OccurrenceCount', 1) or 1
                
                patch_payload = {
                    "OccurrenceCount": int(current_count) + 1,
                    "LastUser": payload['LastUser'],
                    "ErrorMessage": payload['ErrorMessage'], # Actualizar mensaje
                    "AppVersion": self.app_version
                }
                
                self.client.patch(f"/sites/{self.site_id}/lists/{self.list_id}/items/{item_id}/fields", patch_payload)
                print(f"☁️ [Logger] Error actualizado en SharePoint (x{int(current_count) + 1})")
            
            else:
                # C. NO EXISTE -> Crear nuevo
                # Quitamos campos que no son columnas de SP para evitar error 400
                sp_payload = {
                    "Title": payload['Title'],
                    "ErrorMessage": payload['ErrorMessage'],
                    "StackTrace": payload['StackTrace'],
                    "LastUser": payload['LastUser'],
                    "AppVersion": payload['AppVersion'],
                    "OccurrenceCount": 1
                }
                
                create_payload = {"fields": sp_payload}
                resp = self.client.post(f"/sites/{self.site_id}/lists/{self.list_id}/items", create_payload)
                
                if resp and 'id' in resp:
                    print(f"☁️ [Logger] Nuevo error registrado en SharePoint.")
                else:
                    raise Exception("La API no devolvió ID de creación.")

        except Exception as e:
            print(f"⚠️ [Logger] Fallo subida a SP: {e}. Guardando offline.")
            self._save_offline(payload)

    def _save_offline(self, payload):
        """Guarda en JSON estructurado para reintento futuro."""
        try:
            queue = []
            if os.path.exists(self.OFFLINE_FILE):
                with open(self.OFFLINE_FILE, 'r') as f:
                    try: queue = json.load(f)
                    except: pass
            
            queue.append(payload)
            
            with open(self.OFFLINE_FILE, 'w') as f:
                json.dump(queue, f)
        except: pass

    def _flush_offline_queue(self):
        """Reintenta subir la cola."""
        if not os.path.exists(self.OFFLINE_FILE) or not self.list_id: return
        
        try:
            with open(self.OFFLINE_FILE, 'r') as f:
                queue = json.load(f)
            
            if not queue: return
            
            print(f"🔄 [Logger] Procesando {len(queue)} errores offline...")
            
            # Vaciar archivo
            with open(self.OFFLINE_FILE, 'w') as f:
                json.dump([], f)
            
            for payload in queue:
                self._worker_log_to_sharepoint(payload)
                
        except Exception:
            pass