import os
import hashlib
import traceback
import json
import threading
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
    Patrón: Singleton (gestionado implícitamente) + Lógica de Reintento Offline.
    """
    
    LIST_NAME = "AppErrorLog"
    OFFLINE_FILE = "pending_errors.json"

    def __init__(self):
        self.client = MSGraphClient()
        self.site_id = os.getenv('SHAREPOINT_SITE_ID')
        # Versión hardcoded o desde env
        self.app_version = "v1.0" 
        
        # Intentar enviar errores pendientes al iniciar (en segundo plano)
        threading.Thread(target=self._flush_offline_queue, daemon=True).start()

    def log_error(self, exception, context_msg="", user="Unknown"):
        """
        Punto de entrada principal para registrar un error.
        No lanza excepciones (Fail-Safe).
        """
        try:
            # 1. Preparar datos del error
            tb_str = "".join(traceback.format_exception(None, exception, exception.__traceback__))
            error_msg = f"{context_msg}: {str(exception)}" if context_msg else str(exception)
            
            # Generar firma única (Hash) basada en el tipo de error y el lugar donde ocurrió
            # Esto agrupa errores idénticos aunque ocurran en momentos distintos
            if exception.__traceback__:
                tb_last = traceback.extract_tb(exception.__traceback__)[-1]
                signature_base = f"{type(exception).__name__}|{tb_last.filename}:{tb_last.lineno}"
            else:
                signature_base = f"{type(exception).__name__}|{str(exception)}"
                
            error_signature = hashlib.md5(signature_base.encode()).hexdigest()

            payload = {
                "Title": error_signature,
                "ErrorMessage": error_msg[:250], # Cortar para evitar límites simples
                "StackTrace": tb_str[:1000],     # Cortar para evitar límites
                "LastUser": str(user),
                "AppVersion": self.app_version,
                "OccurrenceCount": 1
            }

            # 2. Intentar enviar a SharePoint
            if self.client.is_session_valid:
                threading.Thread(target=self._worker_log_to_sharepoint, args=(payload,), daemon=True).start()
            else:
                self._save_offline(payload)
                
        except Exception as e:
            # Si falla el logger, solo imprimimos en consola local para no ciclar
            print(f"❌ CRITICAL: Falló el sistema de logs: {e}")

    def _worker_log_to_sharepoint(self, payload):
        """Lógica de Upsert (Actualizar si existe, Crear si no)."""
        try:
            signature = payload['Title']
            
            # A. Buscar si ya existe este error
            endpoint = f"/sites/{self.site_id}/lists/{self.LIST_NAME}/items?$expand=fields&$filter=fields/Title eq '{signature}'"
            headers = {"Prefer": "HonorNonIndexedQueriesWarningMayFailRandomly"}
            
            existing = self.client.get(endpoint, extra_headers=headers)
            
            if existing and 'value' in existing and len(existing['value']) > 0:
                # B. EXISTE -> Actualizar (PATCH)
                item_id = existing['value'][0]['id']
                current_fields = existing['value'][0].get('fields', {})
                current_count = current_fields.get('OccurrenceCount', 1) or 1
                
                patch_payload = {
                    "OccurrenceCount": int(current_count) + 1,
                    "LastUser": payload['LastUser'],
                    "ErrorMessage": payload['ErrorMessage'] # Actualizamos mensaje por si varió un poco
                }
                
                self.client.patch(f"/sites/{self.site_id}/lists/{self.LIST_NAME}/items/{item_id}/fields", patch_payload)
                print(f"📝 Error registrado (Count: {int(current_count) + 1})")
            
            else:
                # C. NO EXISTE -> Crear (POST)
                # Graph requiere envolver los campos personalizados en 'fields'
                create_payload = {"fields": payload}
                self.client.post(f"/sites/{self.site_id}/lists/{self.LIST_NAME}/items", create_payload)
                print(f"📝 Nuevo tipo de error registrado en SharePoint.")

        except Exception as e:
            print(f"⚠️ No se pudo subir el log a SharePoint: {e}")
            self._save_offline(payload)

    def _save_offline(self, payload):
        """Guarda el error en disco si no hay internet."""
        try:
            queue = []
            if os.path.exists(self.OFFLINE_FILE):
                with open(self.OFFLINE_FILE, 'r') as f:
                    try: queue = json.load(f)
                    except: pass
            
            queue.append(payload)
            
            with open(self.OFFLINE_FILE, 'w') as f:
                json.dump(queue, f)
            print("💾 Error guardado localmente (Offline).")
        except:
            pass

    def _flush_offline_queue(self):
        """Intenta subir errores guardados localmente."""
        if not os.path.exists(self.OFFLINE_FILE): return
        
        try:
            with open(self.OFFLINE_FILE, 'r') as f:
                queue = json.load(f)
            
            if not queue: return
            
            print(f"🔄 Sincronizando {len(queue)} errores offline...")
            
            # Limpiamos el archivo primero para evitar bucles si falla de nuevo
            os.remove(self.OFFLINE_FILE)
            
            for payload in queue:
                self._worker_log_to_sharepoint(payload)
                
        except Exception:
            pass