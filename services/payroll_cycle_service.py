import os
from datetime import datetime, timedelta, timezone
from ms_graph_client import MSGraphClient

class PayrollCycleService:
    """
    Servicio dedicado a la gestión del ciclo de vida de la nómina.
    Responsabilidad (SRP): Calcular fechas y actualizar la lista de configuración en SharePoint.
    """
    def __init__(self):
        self.client = MSGraphClient()
        self.site_id = os.getenv('SHAREPOINT_SITE_ID')
        # Nombre exacto de la lista de configuración
        self.config_list_name = "Config_Payroll_Date" 

    def get_pay_group_from_env(self) -> str:
        """
        Extrae el PayGroup (ej: 'VGH-VGI') basado en la ruta de carpetas configurada.
        """
        path = os.getenv('TARGET_FOLDER_PATH', '').replace("\\", "/").strip("/")
        if not path:
            return "Unknown-Group"
        
        parts = path.split("/")
        # Si la ruta termina en "Emails for payroll adjustments", el grupo es el anterior
        if len(parts) >= 2:
            return parts[-2]
        return parts[-1]

    def calculate_next_cycle_date(self, current_date_str: str) -> datetime:
        """
        Calcula la fecha SUGERIDA del próximo viernes (Ciclo actual + 7 días).
        Retorna objeto datetime para facilitar manipulación en UI.
        """
        try:
            dt = datetime.strptime(str(current_date_str), "%Y%m%d")
            next_dt = dt + timedelta(days=7)
            return next_dt
        except ValueError:
            return datetime.now() # Fallback seguro

    def execute_cycle_closure(self, current_date_str: str, next_date_str: str, closing_user_name: str):
        """
        Orquesta el cierre del ciclo actual y la apertura del siguiente MANUALMENTE seleccionado.
        1. Busca el ítem del ciclo actual.
        2. Actualiza (Cierra) el ciclo actual.
        3. Crea el nuevo ciclo con la fecha provista por el usuario.
        """
        print(f"🔄 Iniciando cierre de ciclo: {current_date_str} -> Siguiente: {next_date_str}")
        pay_group = self.get_pay_group_from_env()
        
        if not next_date_str:
            return {"success": False, "message": "Invalid next cycle date provided"}

        # 1. Buscar el ítem correspondiente al ciclo actual
        endpoint_query = (
            f"/sites/{self.site_id}/lists/{self.config_list_name}/items"
            f"?expand=fields&$filter=fields/PayGroup eq '{pay_group}' and fields/ActiveDate eq '{current_date_str}'"
        )
        headers = {"Prefer": "HonorNonIndexedQueriesWarningMayFailRandomly"}
        
        query_result = self.client.get(endpoint_query, extra_headers=headers)
        
        current_item_id = None
        if query_result and 'value' in query_result and len(query_result['value']) > 0:
            current_item_id = query_result['value'][0]['id']
        
        # 2. Cerrar ciclo actual (PATCH)
        if current_item_id:
            now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            close_payload = {
                "ClosingTime": now_iso,
                "ClosingUser": closing_user_name
            }
            patch_url = f"/sites/{self.site_id}/lists/{self.config_list_name}/items/{current_item_id}/fields"
            if not self.client.patch(patch_url, close_payload):
                return {"success": False, "message": "Failed to update closing info in SharePoint."}
            print(f"✅ Ciclo {current_date_str} cerrado correctamente.")
        else:
            print(f"⚠️ No se encontró registro previo para {current_date_str}. Creando nuevo de todos modos.")

        # 3. Crear nuevo ciclo (POST) con la fecha VALIDADA por el usuario
        create_payload = {
            "fields": {
                "Title": next_date_str, 
                "PayGroup": pay_group,
                "ActiveDate": next_date_str
            }
        }
        create_url = f"/sites/{self.site_id}/lists/{self.config_list_name}/items"
        create_result = self.client.post(create_url, create_payload)
        
        if create_result and 'id' in create_result:
            return {
                "success": True, 
                "message": f"Closed {current_date_str}. Created {next_date_str}.",
                "next_cycle": next_date_str
            }
        else:
            return {"success": False, "message": "Failed to create next cycle in SharePoint."}