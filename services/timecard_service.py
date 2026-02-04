import os
import shutil
import json
import getpass
from datetime import datetime, timezone
import dateutil.parser
from ms_graph_client import MSGraphClient
from sharepoint_requests_reader import SharePointRequestsReader

class TimecardService:
    """
    Servicio para gestionar la lista 'Timecard Tracking'.
    MODO DIAGNÓSTICO ACTIVO: Logs detallados de lectura/escritura y formato de fechas.
    """
    
    # MAPEO DE COLUMNAS SHAREPOINT
    COL_MAP = {
        "PC_NUM": "Title",           
        "PAY_GROUP": "PayGroup",     
        "LOCATION": "Location",
        "ACTIVE_DATE": "ActiveDate", 
        "STATUS": "Status",            
        "APPROVAL": "Approval",
        "MANAGER": "Manager",
        "SEC_MANAGER": "SecondaryManager",
        "SO_START": "SOStartTime",      
        "SIGNED_OFF": "SignedOff",      
        "SO_FINISH": "SOFinishTime",    
        "REPORT_UPLOADED": "ReportUploaded",
        "RU_FINISH": "RUFinishTime",    
        "WEEK_OF": "WeekOf",
        "PROCESSED_BY": "ProcessedBy",
        "PROBLEMS": "ReportedProblems",
        "BOT_CACHE": "BotAnalysisCache",
        "HISTORY": "ProcessingHistory",
        "EMP_LIST": "Employee_list",
        
        # --- COLUMNAS IA & OUTLOOK ---
        "NOTIF_STATUS": "NotificationStatus", 
        "DRAFT_TO": "DraftTo",                
        "DRAFT_SUBJECT": "DraftSubject",      
        "DRAFT_BODY": "DraftBody",            
        "REFINE_PROMPT": "RefinementPrompt"
    }

    def __init__(self):
        self.client = MSGraphClient()
        self.site_id = os.getenv('SHAREPOINT_SITE_ID')
        self.list_name = "Timecard Tracking"
        self.email_tracker_list = "Email Conversation Tracker"
        self.drive_id = None 
        self._cached_active_date = None
        self._folder_reader = SharePointRequestsReader()

    def get_available_cycles(self):
        """
        Retorna una lista de cadenas de fecha (YYYYMMDD) encontradas en la estructura de carpetas.
        Usado para poblar el dropdown de historial en la UI.
        """
        try:
            dates = self._folder_reader.get_available_date_folders()
            if dates:
                # Ordenar descendente (más reciente primero)
                dates.sort(reverse=True)
            return dates or []
        except Exception as e:
            print(f"⚠️ Error listando ciclos disponibles: {e}")
            return []

    def generate_cycle_timecards(self, active_date, locations_data):
        """
        Genera filas en la lista Timecard Tracking para el nuevo ciclo.
        Crea items automáticamente basándose en los datos del Excel de Locations.
        """
        print(f"🚀 Iniciando generación masiva de Timecards para el ciclo {active_date}...")
        
        # 1. Ordenar por PayGroup para inserción en bloques ordenados (H, luego V...)
        # Usamos 'Z' como fallback para que los vacíos queden al final
        sorted_locs = sorted(locations_data, key=lambda x: str(x.get('pay_group', 'Z')))
        
        success_count = 0
        total = len(sorted_locs)
        
        # Iteramos e insertamos
        for i, loc in enumerate(sorted_locs):
            try:
                # Construimos el payload POST para SharePoint
                payload = {
                    "fields": {
                        "Title": loc['code'],           # Location Code
                        "PayGroup": loc['pay_group'],   # Pay Group (H/V)
                        "Location": loc['description'], # Description
                        "ActiveDate": str(active_date), # Nueva fecha del ciclo
                        
                        # Valores Iniciales
                        # NOTA: Eliminado 'Status' para que SharePoint use su valor default ("Not Ready")
                        "Approval": False,
                        "SignedOff": False,
                        "ReportUploaded": False
                    }
                }
                
                # Petición de creación
                endpoint = f"/sites/{self.site_id}/lists/{self.list_name}/items"
                resp = self.client.post(endpoint, payload)
                
                if resp and 'id' in resp:
                    success_count += 1
                    # Feedback en consola cada 10 items para no saturar logs
                    if success_count % 10 == 0:
                        print(f"   -> Generado {success_count}/{total}...")
                else:
                    print(f"⚠️ Falló creación para {loc['code']} ({loc['description']})")
                    
            except Exception as e:
                print(f"❌ Error generando card para {loc['code']}: {e}")
        
        print(f"🏁 Generación finalizada. Éxito: {success_count}/{total} tarjetas creadas.")
        return success_count

    def get_active_date_from_folders(self):
        """Detecta el ciclo activo (el más reciente) basado en la estructura de carpetas."""
        if self._cached_active_date: return self._cached_active_date
        try:
            dates = self._folder_reader.get_available_date_folders()
            if dates:
                dates.sort(reverse=True)
                latest = dates[0]
                self._cached_active_date = latest
                print(f"🗓️ [Timecards] Ciclo activo detectado: {latest}")
                return latest
        except Exception as e:
            print(f"⚠️ Error detectando fecha de carpetas: {e}")
        return None

    def _format_date_for_sharepoint_iso(self, yyyymmdd_str):
        """
        Convierte '20260130' a '2026-01-30' (Formato ISO estándar para OData).
        Esto suele funcionar mejor si la columna es de tipo 'Fecha y Hora'.
        """
        if not yyyymmdd_str or len(yyyymmdd_str) != 8: return None
        try:
            # Asumimos input YYYYMMDD
            s = yyyymmdd_str
            return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
        except:
            return None

    def get_active_timecards(self, target_date=None):
        """
        Recupera las timecards.
        Si target_date es None, busca la fecha más reciente automáticamente.
        Si target_date tiene valor, filtra por esa fecha específica (historial).
        """
        if target_date:
            active_date = target_date
            print(f"🗓️ [Timecards] Consultando ciclo histórico/específico: {active_date}")
        else:
            active_date = self.get_active_date_from_folders()
            if not active_date:
                print("⚠️ No se pudo determinar un ciclo activo.")
                return [], "Scanning..."

        filter_query = f"fields/{self.COL_MAP['ACTIVE_DATE']} eq '{active_date}'"
        
        endpoint = (
            f"/sites/{self.site_id}/lists/{self.list_name}/items"
            f"?expand=fields"
            f"&$filter={filter_query}"
            f"&$top=500" 
        )
        
        headers = {"Prefer": "HonorNonIndexedQueriesWarningMayFailRandomly"}
        data = self.client.get(endpoint, extra_headers=headers)
        
        items = []
        if data and 'value' in data:
            for raw in data['value']:
                f = raw.get('fields', {})
                
                status_val = f.get(self.COL_MAP['STATUS'])
                if not status_val: status_val = 'Not Ready' 

                item = {
                    "id": raw['id'],
                    "pc_number": f.get(self.COL_MAP['PC_NUM']),
                    "pay_group": f.get(self.COL_MAP['PAY_GROUP']),
                    "location": f.get(self.COL_MAP['LOCATION']), 
                    "status": status_val,
                    "Approval": f.get(self.COL_MAP['APPROVAL'], False),
                    "manager": f.get(self.COL_MAP['MANAGER'], ''),
                    "signed_off": f.get(self.COL_MAP['SIGNED_OFF'], False),
                    "report_uploaded": f.get(self.COL_MAP['REPORT_UPLOADED'], False),
                    "processed_by": f.get(self.COL_MAP['PROCESSED_BY'], ''),
                    "reported_problems": f.get(self.COL_MAP['PROBLEMS'], ''),
                    "active_date": f.get(self.COL_MAP['ACTIVE_DATE']),
                    "bot_analysis_cache": f.get(self.COL_MAP['BOT_CACHE'], ''),
                    "history": f.get(self.COL_MAP['HISTORY'], ''),
                    "employee_list": f.get(self.COL_MAP['EMP_LIST'], ''),
                    
                    # Datos críticos para la resolución inteligente
                    "notif_status": f.get(self.COL_MAP['NOTIF_STATUS'], 'None'),
                    "draft_to": f.get(self.COL_MAP['DRAFT_TO'], ''),
                    "draft_subject": f.get(self.COL_MAP['DRAFT_SUBJECT'], ''),
                    "draft_body": f.get(self.COL_MAP['DRAFT_BODY'], '')
                }
                items.append(item)
                
        items.sort(key=lambda x: x['pc_number'] if x['pc_number'] else "ZZZ")
        return items, active_date

    def get_single_item_status(self, item_id):
        """Recupera el estado de un solo item para polling eficiente."""
        endpoint = f"/sites/{self.site_id}/lists/{self.list_name}/items/{item_id}?expand=fields"
        data = self.client.get(endpoint)
        if data and 'fields' in data:
            f = data['fields']
            return {
                "notif_status": f.get(self.COL_MAP['NOTIF_STATUS'], 'None'),
                "draft_to": f.get(self.COL_MAP['DRAFT_TO'], ''),
                "draft_subject": f.get(self.COL_MAP['DRAFT_SUBJECT'], ''),
                "draft_body": f.get(self.COL_MAP['DRAFT_BODY'], '')
            }
        return None

    # -------------------------------------------------------------------------
    #  PLAN A: RESOLUCIÓN AUTOMÁTICA (Server-Side Filter)
    # -------------------------------------------------------------------------
    def find_exact_match_evidence(self, subject_str, location_code):
        if not subject_str or not location_code: return None
        
        # Variantes de asunto
        variants = [subject_str]
        if "//" in subject_str:
            variants.append(subject_str.replace("//", "--"))
        if "--" in subject_str:
            variants.append(subject_str.replace("--", "//"))
            
        print(f"🤖 [Auto-Resolve] Consultando al servidor por Loc='{location_code}' y {len(variants)} variantes...")

        safe_loc = location_code.replace("'", "''")
        subject_filters = []
        for v in variants:
            safe_sub = v.replace("'", "''")
            subject_filters.append(f"fields/OriginalSubject eq '{safe_sub}'")
        
        or_clause = " or ".join(subject_filters)
        filter_query = f"fields/LocationCode eq '{safe_loc}' and ({or_clause})"
        
        endpoint = (
            f"/sites/{self.site_id}/lists/{self.email_tracker_list}/items"
            f"?expand=fields"
            f"&$filter={filter_query}"
            f"&$top=1"
        )
        
        headers = {"Prefer": "HonorNonIndexedQueriesWarningMayFailRandomly"}
        
        try:
            data = self.client.get(endpoint, extra_headers=headers)
            if data and 'value' in data and len(data['value']) > 0:
                item = data['value'][0]
                f = item.get('fields', {})
                print(f"✅ [Auto-Resolve] ¡Match encontrado! ID: {item['id']}")
                return {
                    "key": item['id'],
                    "text": f.get('OriginalSubject', 'No Subject'),
                    "body": f.get('OriginalBody', ''),
                    "created": f.get('Created', '')
                }
        except Exception as e:
            print(f"⚠️ Error en Auto-Resolve: {e}")
        
        return None

    # -------------------------------------------------------------------------
    #  PLAN B: BÚSQUEDA MANUAL (Diagnóstico Activo)
    # -------------------------------------------------------------------------
    def get_audit_candidates(self, location_code, active_date_str=None):
        """
        Realiza diagnóstico del formato de fecha real en SharePoint y luego intenta filtrar.
        """
        print(f"🔎 [Manual-Resolve] Consultando servidor: Loc='{location_code}' | Ciclo='{active_date_str}'")
        safe_loc = str(location_code).replace("'", "''")

        # --- FASE 1: DIAGNÓSTICO (MODO ESPÍA) ---
        # Traemos 1 item reciente de esta ubicación SIN filtro de fecha para ver qué formato usa SP
        try:
            spy_endpoint = (
                f"/sites/{self.site_id}/lists/{self.email_tracker_list}/items"
                f"?expand=fields"
                f"&$filter=fields/LocationCode eq '{safe_loc}'"
                # CORRECCIÓN: Eliminado orderby para evitar error 400
                f"&$top=1"
            )
            spy_data = self.client.get(spy_endpoint)
            if spy_data and 'value' in spy_data and len(spy_data['value']) > 0:
                raw_date = spy_data['value'][0]['fields'].get('ActiveWeekEndingDate')
                print(f"🕵️ [SPY] El formato REAL de fecha en SharePoint es: '{raw_date}' (Tipo: {type(raw_date)})")
            else:
                print(f"🕵️ [SPY] No se encontraron items previos para espiar el formato.")
        except Exception as e:
            print(f"🕵️ [SPY] Error en diagnóstico: {e}")

        # --- FASE 2: INTENTO DE FILTRO ISO ---
        filters = []
        if location_code:
            filters.append(f"fields/LocationCode eq '{safe_loc}'")
        
        # Probamos con formato ISO YYYY-MM-DD
        iso_date = self._format_date_for_sharepoint_iso(active_date_str)
        if iso_date:
            filters.append(f"fields/ActiveWeekEndingDate eq '{iso_date}'")
            print(f"   -> Probando filtro ISO OData: ActiveWeekEndingDate eq '{iso_date}'")
        
        filter_query = " and ".join(filters)
        
        endpoint = (
            f"/sites/{self.site_id}/lists/{self.email_tracker_list}/items"
            f"?expand=fields"
            f"&$filter={filter_query}"
            # CORRECCIÓN: Eliminado orderby para evitar error 400
            f"&$top=50"
        )
        
        headers = {"Prefer": "HonorNonIndexedQueriesWarningMayFailRandomly"}
        data = self.client.get(endpoint, extra_headers=headers)
        
        candidates = []
        if data and 'value' in data:
            print(f"   -> Servidor devolvió {len(data['value'])} items.")
            
            # Procesamos items
            for item in data['value']:
                f = item.get('fields', {})
                subject = f.get('OriginalSubject', 'No Subject')
                created_iso = f.get('Created', '')
                try:
                    dt = dateutil.parser.parse(created_iso)
                    date_display = dt.strftime("%d/%m %H:%M")
                except:
                    date_display = created_iso[:16]

                label = f"[{date_display}] {subject[:50]}..."
                candidates.append({
                    "key": item['id'], 
                    "text": label,
                    "full_subject": subject,
                    "created_iso": created_iso # Guardamos para ordenar en Python
                })
            
            # CORRECCIÓN: Ordenamiento en memoria (Python)
            candidates.sort(key=lambda x: x['created_iso'], reverse=True)
            
        else:
            print("   -> Servidor devolvió 0 items con filtro ISO. Revisa el log [SPY] arriba.")
        
        return candidates

    # -------------------------------------------------------------------------
    #  ACTUALIZACIÓN Y UTC (Logs de Escritura)
    # -------------------------------------------------------------------------
    def ensure_utc_timestamp(self, dt_value):
        if not dt_value: return None
        try:
            if isinstance(dt_value, str): dt_value = dateutil.parser.parse(dt_value)
            if isinstance(dt_value, datetime):
                if dt_value.tzinfo is None: dt_value = dt_value.astimezone(timezone.utc)
                else: dt_value = dt_value.astimezone(timezone.utc)
                return dt_value.strftime("%Y-%m-%dT%H:%M:%SZ")
        except: return None
        return None

    def update_time_columns(self, item_id, so_start=None, so_finish=None, ru_finish=None, extra_updates=None):
        updates = extra_updates or {}
        if so_start: updates[self.COL_MAP['SO_START']] = self.ensure_utc_timestamp(so_start)
        if so_finish: updates[self.COL_MAP['SO_FINISH']] = self.ensure_utc_timestamp(so_finish)
        if ru_finish: updates[self.COL_MAP['RU_FINISH']] = self.ensure_utc_timestamp(ru_finish)
        return self.update_status(item_id, updates)

    def update_status(self, item_id, updates: dict):
        if not updates: return False
        
        # --- LOGS DE ESCRITURA ---
        print(f"📤 [PATCH] Enviando actualización a Item {item_id}...")
        
        # ELIMINADO: La conversión forzada de "" a None.
        # Ahora permitimos enviar "" tal como lo hacen Review y Start.
        
        # 1. Interceptor UTC
        time_cols = [
            self.COL_MAP['SO_START'], 
            self.COL_MAP['SO_FINISH'], 
            self.COL_MAP['RU_FINISH']
        ]
        
        for col, val in updates.items():
            if col in time_cols and val:
                # Si parece una fecha/hora, intentamos convertirla
                if isinstance(val, (datetime, str)) and len(str(val)) > 10:
                    utc_val = self.ensure_utc_timestamp(val)
                    if utc_val:
                        updates[col] = utc_val
                        # print(f"🕒 Tiempo corregido a UTC: {val} -> {utc_val}")

        endpoint = f"/sites/{self.site_id}/lists/{self.list_name}/items/{item_id}/fields"
        
        try:
            result = self.client.patch(endpoint, updates)
            if result:
                print(f"✅ [PATCH] Éxito. SharePoint aceptó el cambio.")
                return True
            else:
                print(f"❌ [PATCH] Error. SharePoint rechazó el cambio (o devolvió vacío).")
                return False
        except Exception as e:
            print(f"❌ [PATCH] Excepción crítica: {e}")
            return False

    def append_history(self, item_id, current_history_str, event_type, details=None):
        history = []
        if current_history_str:
            try:
                history = json.loads(current_history_str)
                if not isinstance(history, list): history = []
            except: history = []

        new_entry = {
            "timestamp": datetime.now().isoformat(),
            "event": event_type,
            "user": getpass.getuser().upper(),
            "details": details or {}
        }
        history.append(new_entry)
        
        try:
            json_str = json.dumps(history)
            self.update_status(item_id, {self.COL_MAP['HISTORY']: json_str})
        except Exception as e:
            print(f"⚠️ Error history: {e}")

    def save_employee_list(self, item_id, employee_list):
        if not employee_list: return
        try:
            json_str = json.dumps(employee_list)
            self.update_status(item_id, {self.COL_MAP['EMP_LIST']: json_str})
        except Exception as e:
            print(f"⚠️ Error save list: {e}")

    # =========================================================================
    #  PATH CALCULATION HELPERS (DRY Principle)
    # =========================================================================

    def _calculate_network_path(self, cycle_date):
        """
        Calcula la ruta de red objetivo basada en la fecha del ciclo.
        Lógica extraída para ser reutilizada en Subida y Apertura.
        """
        formatted_date = cycle_date
        year = str(datetime.now().year)
        
        if cycle_date and len(cycle_date) == 8 and cycle_date.isdigit():
            try:
                dt_obj = datetime.strptime(cycle_date, "%Y%m%d")
                formatted_date = dt_obj.strftime("%m.%d.%Y")
                year = dt_obj.strftime("%Y")
            except ValueError: pass 
        elif cycle_date and len(cycle_date.split('.')) == 3:
            parts = cycle_date.split('.')
            if len(parts[2]) == 4: year = parts[2]

        network_base = r"\\usa.int\userdata\PNW\Seattle\Main Office\Payroll\Payroll Runs"
        
        # Nota: La estructura de carpetas aquí es fija según la lógica original.
        return os.path.join(network_base, year, "PRS - VGH, VGI", "Weekly", formatted_date, "EPIP, eTime", "Time Post")

    def get_local_report_path(self, pc_number, cycle_date):
        """
        Retorna la ruta absoluta del reporte PDF si existe en la red.
        Usado por la UI para abrir el archivo.
        """
        try:
            base_path = self._calculate_network_path(cycle_date)
            expected_path = os.path.join(base_path, f"{pc_number}.pdf")
            
            if os.path.exists(expected_path):
                return expected_path
            return None
        except Exception as e:
            print(f"⚠️ Error verificando ruta local: {e}")
            return None

    def upload_report(self, local_path, location_name, pc_number, cycle_date):
        # ... (Logica de upload intacta) ...
        upload_success = False
        try:
            # USAMOS LA LÓGICA CENTRALIZADA
            network_path = self._calculate_network_path(cycle_date)
            parent_dir = os.path.dirname(network_path)

            if os.path.exists(parent_dir):
                if not os.path.exists(network_path): os.makedirs(network_path, exist_ok=True)
                destination = os.path.join(network_path, f"{pc_number}.pdf")
                shutil.copy2(local_path, destination)
                if os.path.exists(destination): return True
        except Exception: pass

        if not upload_success:
            if not self.drive_id:
                drives = self.client.get(f"/sites/{self.site_id}/drives")
                if drives and 'value' in drives: self.drive_id = drives['value'][0]['id']
            if not self.drive_id: return False
            
            file_name = f"{pc_number}.pdf"
            safe_date = cycle_date.strip()
            base_path = os.getenv('TARGET_FOLDER_PATH', '').strip('/')
            target_path = f"{base_path}/{safe_date}/Timepost/{file_name}"
            try:
                with open(local_path, 'rb') as f: content = f.read()
                import requests
                endpoint = f"/sites/{self.site_id}/drives/{self.drive_id}/root:/{target_path}:/content"
                headers = {'Authorization': f'Bearer {self.client.access_token}', 'Content-Type': 'application/pdf'}
                url = f"https://graph.microsoft.com/v1.0{endpoint}"
                resp = requests.put(url, headers=headers, data=content)
                if resp.status_code in [200, 201]: return True
            except Exception: return False
        return False