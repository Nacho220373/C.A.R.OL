import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from dotenv import load_dotenv

from ms_graph_client import MSGraphClient
from sharepoint_config import COLUMN_MAP

load_dotenv()

class SharePointRequestsReader:
    def __init__(self, *, max_workers: int = 6, file_cache_ttl: int = 180):
        self.client = MSGraphClient()
        self.site_id = os.getenv('SHAREPOINT_SITE_ID')
        self.root_path = os.getenv('TARGET_FOLDER_PATH')
        self.drive_id = None
        self.max_workers = max_workers

        # In-memory cache for per-request files to reduce repeated round-trips.
        self._file_cache: dict[str, tuple[float, list[dict]]] = {}
        self._cache_lock = threading.Lock()
        self._file_cache_ttl = max(file_cache_ttl, 10)

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

    def fetch_active_requests(self, limit_dates=5, *, include_unread: bool = True):
        """Recorre la estructura para obtener solicitudes y (opcional) cuenta correos no leídos."""
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
                    
                    all_requests.append(clean_req)

        if include_unread and all_requests:
            self._hydrate_unread_counts(all_requests)
        else:
            for req in all_requests:
                req['unread_emails'] = 0

        print(f"✅ Escaneo completado. {len(all_requests)} solicitudes encontradas.")
        return all_requests

    def _hydrate_unread_counts(self, requests_batch: list[dict]):
        """Populates unread_emails on each request using a worker pool."""
        def task(req_id: str):
            return self.get_unread_email_count(req_id, force_refresh=True)

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_map = {executor.submit(task, req['id']): req for req in requests_batch}
            for future in as_completed(future_map):
                req = future_map[future]
                try:
                    req['unread_emails'] = future.result()
                except Exception as exc:
                    print(f"⚠️ Error calculando correos no leídos para {req['id']}: {exc}")
                    req['unread_emails'] = 0

    def get_request_files(self, request_id, *, use_cache: bool = True):
        """Obtiene archivos dentro de una solicitud, ordenados por fecha."""
        if use_cache:
            cached = self._get_cached_files(request_id)
            if cached is not None:
                return cached

        raw_files = self._get_items(item_id=request_id)
        clean_files = []

        for f in raw_files:
            if 'file' in f:
                clean_files.append(self._map_fields(f))

        clean_files.sort(key=lambda x: x.get('created_at', ''))

        if use_cache:
            self._set_cached_files(request_id, clean_files)
        return clean_files

    def get_unread_email_count(self, request_id: str, *, force_refresh: bool = False) -> int:
        """Returns unread email count, leveraging the cached file metadata."""
        files = self.get_request_files(request_id, use_cache=not force_refresh)
        unread_count = 0
        for f in files:
            fname = f.get('name', '').lower()
            status = f.get('status', '')
            if (fname.endswith('.eml') or fname.endswith('.msg')) and status == "To Be Reviewed":
                unread_count += 1
        return unread_count

    def _get_cached_files(self, request_id: str):
        with self._cache_lock:
            cached = self._file_cache.get(request_id)
            if not cached:
                return None
            ts, files = cached
            if time.time() - ts > self._file_cache_ttl:
                self._file_cache.pop(request_id, None)
                return None
            return files

    def _set_cached_files(self, request_id: str, files: list[dict]):
        with self._cache_lock:
            self._file_cache[request_id] = (time.time(), files)

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