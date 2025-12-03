import os
import tempfile
import requests
from datetime import datetime
from dotenv import load_dotenv
from ms_graph_client import MSGraphClient
from sharepoint_config import COLUMN_MAP

load_dotenv()

class SharePointRequestsReader:
    def __init__(self):
        self.client = MSGraphClient()
        self.site_id = os.getenv('SHAREPOINT_SITE_ID')
        self.root_path = os.getenv('TARGET_FOLDER_PATH')
        self.drive_id = None

    def _get_drive_id(self):
        """Obtiene el ID del drive (cacheado en memoria de la instancia)."""
        if self.drive_id:
            return self.drive_id
            
        endpoint = f"/sites/{self.site_id}/drives"
        drives = self.client.get(endpoint)
        
        if not drives:
            print("❌ Error: No se encontraron drives.")
            return None

        for drive in drives.get('value', []):
            if drive['name'] in ["Documents", "Shared Documents", "Documentos"]:
                self.drive_id = drive['id']
                return self.drive_id
        
        self.drive_id = drives['value'][0]['id']
        return self.drive_id

    def _get_items(self, item_id=None, path=None):
        """Helper para obtener items de una ruta o ID."""
        drive_id = self._get_drive_id()
        if not drive_id: return []

        if item_id:
            endpoint = f"/sites/{self.site_id}/drives/{drive_id}/items/{item_id}/children?expand=listItem(expand=fields)"
        elif path:
            safe_path = path.strip("/")
            endpoint = f"/sites/{self.site_id}/drives/{drive_id}/root:/{safe_path}:/children?expand=listItem(expand=fields)"
        else:
            return []

        data = self.client.get(endpoint)
        return data.get('value', []) if data else []

    def _map_fields(self, sp_item):
        """Transforma los datos sucios de SharePoint en un diccionario limpio."""
        fields = sp_item.get('listItem', {}).get('fields', {})
        clean_item = {
            "id": sp_item.get('id'),
            "web_url": sp_item.get('webUrl'),
            "name": sp_item.get('name'), 
            "created_at": sp_item.get('createdDateTime'),
            "download_url": sp_item.get('@microsoft.graph.downloadUrl') 
        }

        # CAMBIO IMPORTANTE: Mapear campos tanto para Carpetas como para Archivos
        # Esto nos permite leer el "Status" de los .eml también
        for app_key, sp_key in COLUMN_MAP.items():
            val = fields.get(sp_key)
            if val is not None:
                clean_item[app_key] = val

        return clean_item

    def fetch_active_requests(self, limit_dates=5):
        """Recorre la estructura para obtener solicitudes y cuenta correos no leídos."""
        all_requests = []
        print("🔄 Iniciando escaneo de solicitudes...")

        date_folders = self._get_items(path=self.root_path)
        
        valid_date_folders = []
        for f in date_folders:
            name = f.get('name', '')
            if f.get('folder') and name.isdigit() and len(name) == 8:
                valid_date_folders.append(f)

        valid_date_folders.sort(key=lambda x: x['name'], reverse=True)
        recent_dates = valid_date_folders[:limit_dates]
        print(f"📅 Analizando {len(recent_dates)} carpetas de fecha.")

        for date_folder in recent_dates:
            location_folders = self._get_items(item_id=date_folder['id'])
            
            for loc_folder in location_folders:
                if not loc_folder.get('folder'): continue
                
                requests = self._get_items(item_id=loc_folder['id'])
                
                for req in requests:
                    if not req.get('folder'): continue 
                    
                    clean_req = self._map_fields(req)
                    clean_req['location_code'] = loc_folder['name']
                    clean_req['date_folder'] = date_folder['name']
                    
                    # --- ANÁLISIS DE CONTENIDO INTERNO (NUEVO) ---
                    # Obtenemos los archivos ahora para contar los no leídos
                    # Esto hace la carga inicial un poco más lenta, pero necesaria para los badges
                    files = self.get_request_files(clean_req['id'])
                    unread_count = 0
                    for f in files:
                        fname = f.get('name', '').lower()
                        status = f.get('status', '')
                        # Contamos si es email Y si el status es "To Be Reviewed"
                        if (fname.endswith('.eml') or fname.endswith('.msg')) and status == "To Be Reviewed":
                            unread_count += 1
                    
                    clean_req['unread_emails'] = unread_count
                    # ---------------------------------------------
                    
                    all_requests.append(clean_req)

        print(f"✅ Escaneo completado. {len(all_requests)} solicitudes encontradas.")
        return all_requests

    def get_request_files(self, request_id):
        """Obtiene archivos dentro de una solicitud, ordenados por fecha."""
        raw_files = self._get_items(item_id=request_id)
        clean_files = []

        for f in raw_files:
            if 'file' in f:
                clean_files.append(self._map_fields(f))

        clean_files.sort(key=lambda x: x.get('created_at', ''))
        return clean_files

    def download_file_locally(self, download_url, filename):
        """Descarga archivo temporalmente."""
        if not download_url: return None
        try:
            temp_dir = tempfile.gettempdir()
            file_path = os.path.join(temp_dir, filename)
            response = requests.get(download_url)
            if response.status_code == 200:
                with open(file_path, 'wb') as f:
                    f.write(response.content)
                return file_path
            return None
        except Exception as e:
            print(f"Excepción al descargar: {e}")
            return None

    def update_request_metadata(self, item_id, new_status=None, new_priority=None):
        """Actualiza Status o Priority de un item (Carpeta o Archivo)."""
        drive_id = self._get_drive_id()
        if not drive_id or not item_id: return False

        endpoint = f"/sites/{self.site_id}/drives/{drive_id}/items/{item_id}/listItem/fields"
        payload = {}
        
        # Usamos COLUMN_MAP para asegurar que el nombre interno sea correcto
        if new_status:
            payload[COLUMN_MAP['status']] = new_status
        if new_priority:
            payload[COLUMN_MAP['priority']] = new_priority
            
        if not payload: return False

        print(f"📝 Actualizando item {item_id}: {payload}")
        result = self.client.patch(endpoint, payload)
        return result is not None