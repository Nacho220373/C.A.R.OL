import os
import pandas as pd
import io
from datetime import datetime, timedelta, time
import pytz
from ms_graph_client import MSGraphClient

# Asumimos zona horaria de México para interpretar las horas del Excel
LOCAL_TIMEZONE = 'America/Mexico_City'

class CategoryRulesService:
    """
    Servicio (SRP) que:
    1. Lee reglas de SLA (tiempos y prioridad) desde 'Category Prioritation Matrix'.
    2. Lee horarios de usuarios desde la hoja 'User'.
    3. Calcula fechas límite respetando esos horarios específicos.
    """
    def __init__(self):
        self.client = MSGraphClient()
        self.site_id = os.getenv('SHAREPOINT_SITE_ID')
        self.file_path = os.getenv('LOCATIONS_FILE_PATH', 'General/locations.xlsx')
        
        # Caches en memoria
        self.rules_db = {}      
        self.schedules_db = {}  
        
        self.drive_id = None

    def _get_drive_id(self):
        if self.drive_id: return self.drive_id
        drives = self.client.get(f"/sites/{self.site_id}/drives")
        if not drives: return None
        for drive in drives.get('value', []):
            if drive['name'] in ["Documents", "Shared Documents", "Documentos"]:
                self.drive_id = drive['id']
                return self.drive_id
        if drives.get('value'):
            self.drive_id = drives['value'][0]['id']
            return self.drive_id
        return None

    def load_data(self):
        """Descarga el Excel y procesa ambas hojas: Reglas y Usuarios."""
        print("🧠 Cargando Reglas y Horarios desde Excel...")
        try:
            drive_id = self._get_drive_id()
            if not drive_id: return

            clean_path = self.file_path.strip("/")
            endpoint = f"/sites/{self.site_id}/drives/{drive_id}/root:/{clean_path}:/content"
            content_bytes = self.client.get_content(endpoint)

            if not content_bytes:
                print("❌ No se pudo descargar el archivo de reglas.")
                return

            excel_file = io.BytesIO(content_bytes)
            
            # --- 1. CARGAR REGLAS (Matrix) ---
            df_rules = pd.read_excel(excel_file, sheet_name="Category Prioritation Matrix")
            df_rules.columns = df_rules.columns.str.strip()
            
            self.rules_db = {}
            for _, row in df_rules.iterrows():
                cat_key = str(row.get('category_key', '')).strip()
                if not cat_key or cat_key.lower() == 'nan': continue
                
                self.rules_db[cat_key.lower()] = {
                    'priority_level': str(row.get('priority_level', '4')).replace('.0', ''),
                    'reply_limit_min': int(row.get('reply_limit_min', 0) or 0),
                    'resolve_limit_min': int(row.get('resolve_limit_min', 0) or 0)
                }

            # --- 2. CARGAR HORARIOS (User) ---
            df_users = pd.read_excel(excel_file, sheet_name="User")
            df_users.columns = df_users.columns.str.strip()
            
            self.schedules_db = {}
            for _, row in df_users.iterrows():
                email = str(row.get('User', '')).strip().lower()
                if not email or email == 'nan': continue
                
                in_val = row.get('In')
                out_val = row.get('Out')
                
                parsed_in = self._parse_time(in_val, time(9, 0))  # Default 9 AM
                parsed_out = self._parse_time(out_val, time(18, 0)) # Default 6 PM
                
                self.schedules_db[email] = {'in': parsed_in, 'out': parsed_out}

            print(f"✅ Datos cargados: {len(self.rules_db)} Reglas, {len(self.schedules_db)} Usuarios.")
            
        except Exception as e:
            # Capturamos excepciones para no romper la sesión del cliente Graph
            print(f"⚠️ Error procesando Excel de reglas (La app seguirá funcionando con defaults): {e}")

    def _parse_time(self, val, default):
        """Intenta convertir valor de celda Excel a objeto time."""
        if not val: return default
        try:
            if isinstance(val, time): return val
            if isinstance(val, datetime): return val.time()
            if isinstance(val, str):
                try: return datetime.strptime(val, "%H:%M:%S").time()
                except: pass
                try: return datetime.strptime(val, "%H:%M").time()
                except: pass
        except:
            pass
        return default

    def get_rule(self, category):
        if not self.rules_db: self.load_data()
        cat_lower = str(category).lower()
        if cat_lower in self.rules_db:
            return self.rules_db[cat_lower]
        
        for key, rule in self.rules_db.items():
            if key in cat_lower:
                return rule
        return None

    def get_user_schedule(self, email):
        if not self.schedules_db: self.load_data()
        email_key = str(email).strip().lower()
        return self.schedules_db.get(email_key, {'in': time(9,0), 'out': time(18,0)})

    def calculate_deadlines(self, creation_date_iso, category, user_email):
        """
        Calcula Reply y Resolve deadlines basados en la fecha de creación (UTC)
        y el horario del usuario específico.
        """
        rule = self.get_rule(category)
        if not rule: 
            return None, None, None

        priority = rule['priority_level']
        schedule = self.get_user_schedule(user_email)
        
        try:
            # 1. Parsear fecha creación (UTC)
            utc_created = datetime.fromisoformat(creation_date_iso.replace('Z', '+00:00'))
        except:
            return priority, None, None

        # 2. Calcular usando el horario del usuario
        # MODIFICADO: Si el tiempo asignado es 0, la fecha límite es None (NA)
        reply_mins = rule['reply_limit_min']
        if reply_mins > 0:
            reply_dt = self._add_minutes_with_schedule(utc_created, reply_mins, schedule)
        else:
            reply_dt = None

        resolve_mins = rule['resolve_limit_min']
        if resolve_mins > 0:
            resolve_dt = self._add_minutes_with_schedule(utc_created, resolve_mins, schedule)
        else:
            resolve_dt = None

        # 3. Formato ISO para SharePoint (UTC)
        reply_str = reply_dt.isoformat().replace('+00:00', 'Z') if reply_dt else None
        resolve_str = resolve_dt.isoformat().replace('+00:00', 'Z') if resolve_dt else None

        return priority, reply_str, resolve_str

    def _add_minutes_with_schedule(self, start_dt_utc, minutes_to_add, schedule):
        """
        Suma minutos respetando el horario In/Out del usuario específico.
        Salta noches y fines de semana.
        """
        if minutes_to_add <= 0: return start_dt_utc

        work_start = schedule['in']
        work_end = schedule['out']
        
        try:
            local_tz = pytz.timezone(LOCAL_TIMEZONE)
            current = start_dt_utc.astimezone(local_tz)
        except:
            current = start_dt_utc
        
        minutes_left = minutes_to_add
        max_loops = 1000 
        loops = 0

        while minutes_left > 0 and loops < max_loops:
            loops += 1
            
            if current.weekday() >= 5:
                days_to_add = 7 - current.weekday()
                current += timedelta(days=days_to_add)
                current = current.replace(hour=work_start.hour, minute=work_start.minute, second=0)
                continue

            if current.time() < work_start:
                current = current.replace(hour=work_start.hour, minute=work_start.minute, second=0)

            if current.time() >= work_end:
                current += timedelta(days=1)
                current = current.replace(hour=work_start.hour, minute=work_start.minute, second=0)
                continue

            day_end_dt = current.replace(hour=work_end.hour, minute=work_end.minute, second=0)
            minutes_available_today = (day_end_dt - current).total_seconds() / 60

            if minutes_available_today <= 0:
                 current += timedelta(days=1)
                 current = current.replace(hour=work_start.hour, minute=work_start.minute, second=0)
                 continue

            if minutes_left <= minutes_available_today:
                current += timedelta(minutes=minutes_left)
                minutes_left = 0
            else:
                minutes_left -= minutes_available_today
                current += timedelta(days=1)
                current = current.replace(hour=work_start.hour, minute=work_start.minute, second=0)

        return current.astimezone(pytz.utc)