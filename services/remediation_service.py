import os
import urllib.parse
from ms_graph_client import MSGraphClient

class RemediationService:
    def __init__(self, reader):
        self.client = MSGraphClient()
        self.reader = reader 
        self.site_id = os.getenv('SHAREPOINT_SITE_ID')
        self.list_name = "Email Conversation Tracker"

    def _find_tracker_item_id(self, conversation_id):
        if not conversation_id: return None
        safe_id = conversation_id.replace("'", "''") 
        endpoint = f"/sites/{self.site_id}/lists/{self.list_name}/items?filter=fields/Title eq '{safe_id}'"
        headers = {"Prefer": "HonorNonIndexedQueriesWarningMayFailRandomly"}
        data = self.client.get(endpoint, extra_headers=headers)
        if data and 'value' in data and len(data['value']) > 0:
            return data['value'][0]['id']
        return None

    def _clean_sharepoint_path(self, full_path):
        clean = full_path.replace("/Shared Documents/", "").strip("/")
        clean = clean.replace("Shared Documents/", "")
        return clean

    def get_folders_in_location(self, date_folder_name, location_code):
        """Devuelve una lista de nombres de carpetas dentro de una Ubicación/Fecha específica."""
        print(f"📂 Listando carpetas en: {date_folder_name}/{location_code}")
        drive_id = self.reader._get_drive_id()
        root_path = os.getenv('TARGET_FOLDER_PATH').strip("/")
        target_path = f"{root_path}/{date_folder_name}/{location_code}"
        endpoint = f"/sites/{self.site_id}/drives/{drive_id}/root:/{target_path}:/children"
        data = self.client.get(endpoint)
        
        folders = []
        if data and 'value' in data:
            for item in data['value']:
                if 'folder' in item:
                    folders.append({"name": item['name'], "id": item['id']})
        return folders

    # --- LÓGICA DE LIMPIEZA AUTOMÁTICA (SoC) ---
    def delete_location_if_empty(self, date_folder, location_code):
        """
        Verifica si una carpeta de ubicación quedó vacía y la elimina.
        Útil para mantener SharePoint limpio tras mover o borrar solicitudes.
        """
        try:
            drive_id = self.reader._get_drive_id()
            root_path = os.getenv('TARGET_FOLDER_PATH').strip("/")
            # Ruta a la carpeta de la ubicación (ej: Emails/20251212/847)
            loc_path = f"{root_path}/{date_folder}/{location_code}"
            
            # 1. Obtener contenido de la carpeta de ubicación
            endpoint = f"/sites/{self.site_id}/drives/{drive_id}/root:/{loc_path}:/children"
            data = self.client.get(endpoint)
            
            # 2. Si no hay ítems, borrar la carpeta
            if data and 'value' in data and len(data['value']) == 0:
                print(f"🧹 Ubicación {location_code} está vacía. Eliminando carpeta...")
                # Necesitamos el ID de la carpeta para borrarla de forma segura
                folder_meta = self.client.get(f"/sites/{self.site_id}/drives/{drive_id}/root:/{loc_path}")
                if folder_meta and 'id' in folder_meta:
                    delete_url = f"/sites/{self.site_id}/drives/{drive_id}/items/{folder_meta['id']}"
                    if self.client.delete(delete_url):
                        print(f"✅ Carpeta de ubicación {location_code} eliminada exitosamente.")
                        return True
            return False
        except Exception as e:
            print(f"⚠️ Error en limpieza de carpeta: {e}")
            return False

    def block_and_delete(self, folder_id, conversation_id, date_folder=None, location_code=None):
        print(f"\n--- ACCIÓN: BLOCK & DELETE ---")
        success_list = False
        success_folder = False
        item_id = self._find_tracker_item_id(conversation_id)
        
        if item_id:
            patch_url = f"/sites/{self.site_id}/lists/{self.list_name}/items/{item_id}/fields"
            if self.client.patch(patch_url, {"Include": "NO"}): success_list = True
            
        if folder_id:
            drive_id = self.reader._get_drive_id() 
            delete_url = f"/sites/{self.site_id}/drives/{drive_id}/items/{folder_id}"
            if self.client.delete(delete_url): success_folder = True
        
        # Intentar limpieza si se proveen los datos de ruta
        if (success_folder or success_list) and date_folder and location_code:
            self.delete_location_if_empty(date_folder, location_code)
            
        return success_folder or success_list

    def relocate_folder(self, folder_id, target_location_code, conversation_id, old_date_folder=None, old_location_code=None):
        print(f"\n--- ACCIÓN: RELOCATE a {target_location_code} ---")
        item_id = self._find_tracker_item_id(conversation_id)
        if not item_id: return False
        
        item_data = self.client.get(f"/sites/{self.site_id}/lists/{self.list_name}/items/{item_id}?expand=fields")
        fields = item_data.get('fields', {})
        current_active_path = fields.get('ActiveFolderPath')
        if not current_active_path: return False
        
        parts = current_active_path.strip("/").split("/")
        if len(parts) < 2: return False
        
        parts[-2] = str(target_location_code)
        new_active_path = "/" + "/".join(parts)
        
        new_parent_path_parts = parts[:-1]
        grandparent_path_parts = parts[:-2]
        relative_new_parent_path = self._clean_sharepoint_path("/".join(new_parent_path_parts))
        relative_grandparent_path = self._clean_sharepoint_path("/".join(grandparent_path_parts))
        
        success_move = False
        if folder_id:
            drive_id = self.reader._get_drive_id()
            parent_endpoint = f"/sites/{self.site_id}/drives/{drive_id}/root:/{relative_new_parent_path}"
            parent_data = self.client.get(parent_endpoint)
            new_parent_id = None
            if parent_data and 'id' in parent_data:
                new_parent_id = parent_data['id']
            else:
                grandparent_endpoint = f"/sites/{self.site_id}/drives/{drive_id}/root:/{relative_grandparent_path}"
                gp_data = self.client.get(grandparent_endpoint)
                if gp_data and 'id' in gp_data:
                    create_payload = {"name": str(target_location_code), "folder": {}, "@microsoft.graph.conflictBehavior": "rename"}
                    create_url = f"/sites/{self.site_id}/drives/{drive_id}/items/{gp_data['id']}/children"
                    create_resp = self.client.post(create_url, create_payload)
                    if create_resp and 'id' in create_resp: new_parent_id = create_resp['id']
            
            if new_parent_id:
                move_payload = {"parentReference": {"id": new_parent_id}}
                if self.client.patch(f"/sites/{self.site_id}/drives/{drive_id}/items/{folder_id}", move_payload):
                    success_move = True

        patch_url = f"/sites/{self.site_id}/lists/{self.list_name}/items/{item_id}/fields"
        update_payload = {"LocationCode": str(target_location_code), "ActiveFolderPath": new_active_path}
        final_success = self.client.patch(patch_url, update_payload)
        
        # Limpiar carpeta vieja si se movió con éxito
        if final_success and old_date_folder and old_location_code:
            self.delete_location_if_empty(old_date_folder, old_location_code)
            
        return final_success

    def change_request_cycle(self, folder_id, target_date, location_code, conversation_id, old_date):
        """Mueve la solicitud a un ciclo (carpeta de fecha) diferente."""
        print(f"\n--- ACCIÓN: CHANGE CYCLE a {target_date} ---")
        item_id = self._find_tracker_item_id(conversation_id)
        if not item_id: return False
        
        # 1. Obtener path actual
        item_data = self.client.get(f"/sites/{self.site_id}/lists/{self.list_name}/items/{item_id}?expand=fields")
        fields = item_data.get('fields', {})
        current_active_path = fields.get('ActiveFolderPath')
        if not current_active_path: return False
        
        # Estructura esperada path: /.../DateFolder/LocationCode/RequestName
        parts = current_active_path.strip("/").split("/")
        if len(parts) < 3: return False
        
        # Reemplazamos la parte de la fecha (antepenúltimo elemento)
        parts[-3] = str(target_date)
        new_active_path = "/" + "/".join(parts)
        
        # El nuevo padre es la carpeta de Ubicación dentro de la Nueva Fecha
        new_parent_path_parts = parts[:-1]
        relative_new_parent_path = self._clean_sharepoint_path("/".join(new_parent_path_parts))
        
        success_move = False
        if folder_id:
            drive_id = self.reader._get_drive_id()
            
            # Verificamos si existe el destino (Date/Loc)
            parent_endpoint = f"/sites/{self.site_id}/drives/{drive_id}/root:/{relative_new_parent_path}"
            parent_data = self.client.get(parent_endpoint)
            new_parent_id = None
            
            if parent_data and 'id' in parent_data:
                new_parent_id = parent_data['id']
            else:
                # Si no existe la carpeta Loc en la nueva Fecha, intentamos crearla
                # Obtenemos la carpeta de Fecha (abuelo)
                grandparent_path_parts = parts[:-2]
                relative_grandparent_path = self._clean_sharepoint_path("/".join(grandparent_path_parts))
                gp_data = self.client.get(f"/sites/{self.site_id}/drives/{drive_id}/root:/{relative_grandparent_path}")
                
                if gp_data and 'id' in gp_data:
                    create_payload = {"name": str(location_code), "folder": {}, "@microsoft.graph.conflictBehavior": "open"}
                    create_url = f"/sites/{self.site_id}/drives/{drive_id}/items/{gp_data['id']}/children"
                    create_resp = self.client.post(create_url, create_payload)
                    if create_resp and 'id' in create_resp: 
                        new_parent_id = create_resp['id']
            
            if new_parent_id:
                # Movemos la carpeta
                move_payload = {"parentReference": {"id": new_parent_id}}
                if self.client.patch(f"/sites/{self.site_id}/drives/{drive_id}/items/{folder_id}", move_payload):
                    success_move = True
            else:
                print("❌ No se pudo encontrar ni crear la estructura del nuevo ciclo.")
                return False

        # Actualizamos la lista
        patch_url = f"/sites/{self.site_id}/lists/{self.list_name}/items/{item_id}/fields"
        update_payload = {"ActiveFolderPath": new_active_path}
        final_success = self.client.patch(patch_url, update_payload)
        
        # Limpieza
        if final_success and old_date:
            self.delete_location_if_empty(old_date, location_code)
            
        return final_success

    def merge_folders(self, source_folder_id, target_folder_id, target_folder_name, source_conversation_id, target_location_code, date_folder, source_location_code):
        """Fusiona contenido y limpia origen."""
        print(f"\n--- ACCIÓN: MERGE ---")
        if not target_folder_id: return False

        drive_id = self.reader._get_drive_id()
        children_url = f"/sites/{self.site_id}/drives/{drive_id}/items/{source_folder_id}/children"
        children = self.client.get(children_url)
        
        if children and 'value' in children:
            for item in children['value']:
                payload = {"parentReference": {"id": target_folder_id}, "name": item['name'], "@microsoft.graph.conflictBehavior": "rename"}
                self.client.patch(f"/sites/{self.site_id}/drives/{drive_id}/items/{item['id']}", payload)

        source_item_id = self._find_tracker_item_id(source_conversation_id)
        if source_item_id:
            source_data = self.client.get(f"/sites/{self.site_id}/lists/{self.list_name}/items/{source_item_id}?expand=fields")
            old_path = source_data.get('fields', {}).get('ActiveFolderPath')
            if old_path:
                parts = old_path.strip("/").split("/")
                if len(parts) >= 2:
                    parts[-2] = str(target_location_code)
                    parts[-1] = str(target_folder_name)
                    new_path = "/" + "/".join(parts)
                    self.client.patch(f"/sites/{self.site_id}/lists/{self.list_name}/items/{source_item_id}/fields", {"ActiveFolderPath": new_path, "LocationCode": str(target_location_code)})

        # Borrar carpeta origen y luego verificar si la carpeta "Location" quedó vacía
        self.client.delete(f"/sites/{self.site_id}/drives/{drive_id}/items/{source_folder_id}")
        self.delete_location_if_empty(date_folder, source_location_code)
        return True