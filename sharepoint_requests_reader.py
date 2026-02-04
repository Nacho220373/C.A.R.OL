import os
import tempfile
import threading
import time
from datetime import datetime, date
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from dotenv import load_dotenv

from ms_graph_client import MSGraphClient
from sharepoint_config import COLUMN_MAP

load_dotenv()

class SharePointRequestsReader:
    def __init__(self, *, max_workers: int = 6, file_cache_ttl: int = 180, root_paths: list = None):
        print("🔧 [Reader] Inicializando SharePointRequestsReader v3.0 (Multi-Root)") # DEBUG MARKER
        self.client = MSGraphClient()
        self.site_id = os.getenv('SHAREPOINT_SITE_ID')
        
        # [NUEVO] Soporte Multi-Path
        env_path = os.getenv('TARGET_FOLDER_PATH')
        if root_paths:
            self.target_paths = root_paths
        elif env_path:
            self.target_paths = [env_path]
        else:
            self.target_paths = []
            print("⚠️ ADVERTENCIA: No hay rutas de SharePoint configuradas.")

        self.root_path = self.target_paths[0] if self.target_paths else None

        self.drive_id = None
        self.max_workers = max_workers

        # In-memory cache for per-request files
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
        
        if drives.get('value'):
            self.drive_id = drives['value'][0]['id']
            return self.drive_id
        return None

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
            "etag": sp_item.get('eTag'),
            "web_url": sp_item.get('webUrl'),
            "name": sp_item.get('name'), 
            "created_at": sp_item.get('createdDateTime'),
            "download_url": sp_item.get('@microsoft.graph.downloadUrl'),
            "outlook_fails": fields.get('OutlookFails'),
            "status": fields.get('Status') 
        }

        for app_key, sp_key in COLUMN_MAP.items():
            val = fields.get(sp_key)
            if app_key == "editor":
                if isinstance(val, dict):
                    val = val.get('LookupValue')
                elif isinstance(val, list) and len(val) > 0:
                    val = val[0].get('LookupValue')
            if val is not None:
                clean_item[app_key] = val

        if 'editor' not in clean_item or not clean_item['editor']:
            try:
                editor_fallback = sp_item.get('lastModifiedBy', {}).get('user', {}).get('displayName')
                if editor_fallback:
                    clean_item['editor'] = editor_fallback
            except:
                pass

        return clean_item

    # --- MÉTODO DELTA QUERY MULTI-ROOT (MODIFICADO FASE 3) ---
    def init_delta_links(self, date_folder_name):
        """
        [NUEVO] Genera un diccionario de {ruta_base: delta_link} para TODAS las rutas configuradas
        que contengan la carpeta de fecha especificada.
        """
        drive_id = self._get_drive_id()
        if not drive_id or not date_folder_name: return {}
        
        links_map = {}
        
        print(f"📡 Inicializando monitoreo Multi-Root para ciclo: {date_folder_name}")
        
        for root_path in self.target_paths:
            # 1. Buscar el ID de la carpeta de fecha dentro de ESTA ruta raíz
            # Usamos _get_items con path específico
            full_path = f"{root_path.strip('/')}/{date_folder_name}"
            
            # Buscamos el ID de esa carpeta específica
            try:
                # Una llamada directa para obtener el ID de la carpeta fecha
                folder_endpoint = f"/sites/{self.site_id}/drives/{drive_id}/root:/{full_path}"
                folder_data = self.client.get(folder_endpoint)
                
                if folder_data and 'id' in folder_data:
                    folder_id = folder_data['id']
                    
                    # 2. Pedir Delta Token para esa carpeta
                    endpoint = f"/sites/{self.site_id}/drives/{drive_id}/items/{folder_id}/delta?token=latest"
                    delta_data = self.client.get(endpoint)
                    
                    token = None
                    if delta_data and '@odata.deltaLink' in delta_data:
                        token = delta_data['@odata.deltaLink']
                    else:
                        # Fallback pagination
                        endpoint_page = f"/sites/{self.site_id}/drives/{drive_id}/items/{folder_id}/delta"
                        while True:
                            p_data = self.client.get(endpoint_page)
                            if not p_data: break
                            if '@odata.deltaLink' in p_data:
                                token = p_data['@odata.deltaLink']
                                break
                            if '@odata.nextLink' in p_data:
                                endpoint_page = p_data['@odata.nextLink']
                            else:
                                break
                    
                    if token:
                        links_map[root_path] = token
                        print(f"   -> Watcher armado para: {root_path} (ID: {folder_id})")
                else:
                    print(f"   -> Saltando ruta {root_path} (No contiene ciclo {date_folder_name})")
                    
            except Exception as e:
                print(f"⚠️ Error armando watcher para {root_path}: {e}")
                
        return links_map

    def fetch_changes_multi(self, links_map):
        """
        [NUEVO] Consulta cambios para múltiples tokens.
        Retorna: (nuevo_mapa_links, lista_combinada_cambios)
        """
        all_changes = []
        new_map = links_map.copy()
        
        for root_path, delta_url in links_map.items():
            try:
                current_url = delta_url
                local_changes = []
                
                while True:
                    response = requests.get(current_url, headers={'Authorization': f'Bearer {self.client.access_token}'})
                    
                    if response.status_code == 410: # Gone (Token expirado)
                        print(f"⚠️ Token expirado para {root_path}. Se requiere reinicio.")
                        return None, [] # Forzar resync global
                    
                    if response.status_code != 200:
                        print(f"⚠️ Error polling {root_path}: {response.status_code}")
                        break 
                        
                    data = response.json()
                    items = data.get('value', [])
                    
                    # Inyectar origen para trazabilidad
                    for item in items:
                        item['_source_root'] = root_path
                        
                    local_changes.extend(items)
                    
                    if '@odata.nextLink' in data:
                        current_url = data['@odata.nextLink']
                    elif '@odata.deltaLink' in data:
                        new_map[root_path] = data['@odata.deltaLink']
                        break
                    else:
                        break
                
                all_changes.extend(local_changes)
                
            except Exception as e:
                print(f"Error polling ruta {root_path}: {e}")
                
        return new_map, all_changes

    # Mantenemos métodos legacy por si acaso, pero fetch_active_requests es el principal
    def get_latest_metadata(self, item_id):
        drive_id = self._get_drive_id()
        if not drive_id or not item_id: return None
        endpoint = f"/sites/{self.site_id}/drives/{drive_id}/items/{item_id}?expand=listItem(expand=fields)"
        data = self.client.get(endpoint)
        if data:
            return self._map_fields(data)
        return None

    def get_available_date_folders(self) -> list[str]:
        valid_dates = set()
        for root_path in self.target_paths:
            try:
                date_folders = self._get_items(path=root_path)
                for f in date_folders:
                    name = f.get('name', '')
                    if f.get('folder') and name.isdigit() and len(name) == 8:
                        valid_dates.add(name)
            except Exception as e:
                print(f"⚠️ Error escaneando fechas en {root_path}: {e}")
        return sorted(list(valid_dates), reverse=True)

    def fetch_active_requests(self, limit_dates=1, date_range: tuple[date, date] = None, *, include_unread: bool = True, progress_callback=None):
        all_requests = []
        print(f"🔄 Iniciando escaneo Multi-Root ({len(self.target_paths)} rutas)...")

        start_time = time.time()
        total_steps = len(self.target_paths) * limit_dates 
        steps_done = 0

        for i, root_path in enumerate(self.target_paths):
            print(f"   📂 Escaneando raíz: {root_path}")
            
            raw_folders = self._get_items(path=root_path)
            valid_date_folders = []
            for f in raw_folders:
                name = f.get('name', '')
                if f.get('folder') and name.isdigit() and len(name) == 8:
                    valid_date_folders.append(f)

            target_folders = []
            if date_range:
                start_input, end_input = date_range
                start_d = start_input if not isinstance(start_input, datetime) else start_input.date()
                end_d = end_input if not isinstance(end_input, datetime) else end_input.date()

                for f in valid_date_folders:
                    try:
                        folder_dt = datetime.strptime(f['name'], "%Y%m%d")
                        folder_d = folder_dt.date()
                        if start_d <= folder_d <= end_d:
                            target_folders.append(f)
                    except ValueError:
                        continue
                if i == 0: 
                    print(f"📅 Filtrando por rango: {start_d} - {end_d}. Carpetas encontradas: {len(target_folders)}")
            else:
                valid_date_folders.sort(key=lambda x: x['name'], reverse=True)
                target_folders = valid_date_folders[:limit_dates]
                if i == 0:
                    print(f"📅 Analizando últimas {len(target_folders)} carpetas de fecha.")

            for j, date_folder in enumerate(target_folders):
                if progress_callback:
                    steps_done += 1
                    elapsed = time.time() - start_time
                    if steps_done > 0:
                        avg_time = elapsed / steps_done
                        remaining = total_steps - steps_done
                        eta = avg_time * remaining
                        progress_callback(steps_done, total_steps, eta)

                location_folders = self._get_items(item_id=date_folder['id'])
                
                for loc_folder in location_folders:
                    if not loc_folder.get('folder'): continue
                    
                    requests_items = self._get_items(item_id=loc_folder['id'])
                    
                    for req in requests_items:
                        if not req.get('folder'): continue 
                        
                        clean_req = self._map_fields(req)
                        clean_req['location_code'] = loc_folder['name']
                        clean_req['date_folder'] = date_folder['name']
                        clean_req['_source_root'] = root_path 
                        
                        all_requests.append(clean_req)

        if include_unread and all_requests:
            self._hydrate_unread_counts(all_requests)
        else:
            for req in all_requests:
                req['unread_emails'] = 0
                req['has_outlook_failure'] = False

        print(f"✅ Escaneo Multi-Root completado. {len(all_requests)} solicitudes encontradas.")
        return all_requests

    def _hydrate_unread_counts(self, requests_batch: list[dict]):
        def task(req_id: str):
            return self.get_folder_metrics(req_id, force_refresh=True)

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_map = {executor.submit(task, req['id']): req for req in requests_batch}
            for future in as_completed(future_map):
                req = future_map[future]
                try:
                    metrics = future.result()
                    req['unread_emails'] = metrics['unread']
                    req['has_outlook_failure'] = metrics['has_failure']
                except Exception as exc:
                    print(f"⚠️ Error calculando métricas para {req['id']}: {exc}")
                    req['unread_emails'] = 0
                    req['has_outlook_failure'] = False

    def get_request_files(self, request_id, *, use_cache: bool = True):
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
        metrics = self.get_folder_metrics(request_id, force_refresh=force_refresh)
        return metrics['unread']

    def get_folder_metrics(self, request_id: str, *, force_refresh: bool = False) -> dict:
        files = self.get_request_files(request_id, use_cache=not force_refresh)
        unread_count = 0
        has_failure = False
        
        for f in files:
            fname = f.get('name', '').lower()
            status = f.get('status', '')
            if (fname.endswith('.eml') or fname.endswith('.msg')) and status == "To Be Reviewed":
                unread_count += 1
            if f.get('outlook_fails'):
                has_failure = True
                
        return {"unread": unread_count, "has_failure": has_failure}

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

    def update_request_metadata(self, item_id, new_status=None, new_priority=None, new_category=None, 
                                new_reply_limit=..., new_resolve_limit=...,
                                new_reply_time=..., new_resolve_time=...,
                                new_comments=None, 
                                etag=None): 
        drive_id = self._get_drive_id()
        if not drive_id or not item_id: return False

        endpoint = f"/sites/{self.site_id}/drives/{drive_id}/items/{item_id}/listItem/fields"
        payload = {}
        
        if new_status: payload[COLUMN_MAP['status']] = new_status
        if new_priority: payload[COLUMN_MAP['priority']] = new_priority
        if new_category: payload[COLUMN_MAP['category']] = new_category
        if new_reply_limit is not ...: payload[COLUMN_MAP['reply_limit']] = new_reply_limit
        if new_resolve_limit is not ...: payload[COLUMN_MAP['resolve_limit']] = new_resolve_limit
        if new_reply_time is not ...: payload[COLUMN_MAP['reply_time']] = new_reply_time
        if new_resolve_time is not ...: payload[COLUMN_MAP['resolve_time']] = new_resolve_time
        if new_comments is not None: payload[COLUMN_MAP['comments']] = new_comments
            
        if not payload: return False

        print(f"🔄 Actualizando item {item_id}: {payload}")
        
        headers = {}
        if etag: headers['If-Match'] = etag
            
        result = self.client.patch(endpoint, payload, extra_headers=headers)
        return result is not None