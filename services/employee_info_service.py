import os
import json
import unicodedata
import datetime
from ms_graph_client import MSGraphClient


class EmployeeInfoService:
    """
    Servicio de información de empleados contra la lista 'Employee Information'.

    - Resuelve list_id por displayName.
    - Descubre columnas dinámicamente y mapea internal_name -> displayName.
    - Filtra inteligentemente columnas de sistema.
    - Oculta Change History de la vista general.
    - Soporta filtro por Pay Group y Status, y extracción de valores únicos.
    """

    SEARCH_LIMIT = 100 # Límite de resultados para seguridad

    # Mapeo mínimo "core" (usa tus internal names)
    COL_MAP = {
        "EE_ID": "Title",                # Employee ID (Title)
        "FILE_NUMBER": "field_1",        # File Number
        "LAST_NAME": "field_2",          # Last Name
        "FIRST_NAME": "field_3",         # First Name
        "EMPLOYEE_STATUS": "field_4",    # Employee Status
        "PAY_GROUP": "field_5",          # Pay Group
        "COMPANY_CODE": "field_6",       # Company Code
        "JOB_TITLE": "field_7",          # Job Title
        "DEPARTMENT_CODE": "field_11",   # Department Code

        # Emails
        "WORK_EMAIL": "field_26",        # Work Email
        "PERSONAL_EMAIL": "field_27",    # Personal Email

        # Pay related
        "PAY_RATE": "field_23",          # Pay Rate (Annual/Hourly)
        "PRIMARY_PAY_RATE": "field_24",  # Primary Pay Rate
        "HOURLY_RATE_2": "field_25",     # Hourly Rate 2

        # Change history
        "CHANGE_HISTORY": "ChangeHistory",
    }

    # Campos técnicos a ocultar en el detalle genérico
    HIDDEN_FIELD_PREFIXES = ("_", "@") 
    HIDDEN_FIELD_EXACT = {
        "ID", "id", "odata.type", "odata.etag",
        "Created", "Modified", "Author", "Editor", "Version", "_UIVersionString",
        "Attachments", "FolderChildCount", "ItemChildCount",
        "ComplianceAssetId", "HashData", "DocIcon",
        "LinkTitle", "LinkTitleNoMenu", "ContentType", "AppAuthor", "AppEditor",
        "_ComplianceTag", "_ComplianceFlags", "_ComplianceTagUserId", "_ComplianceTagWrittenTime"
    }

    def __init__(self):
        self.client = MSGraphClient()
        self.site_id = os.getenv('SHAREPOINT_SITE_ID')
        self.list_display_name = "Employee Information"
        self.list_id = self._resolve_list_id_by_name(self.list_display_name)
        # Mapa de columnas y sus metadatos para filtrado inteligente
        self.columns_map, self.columns_meta = self._load_columns_metadata()

    # --------------------- Resolución de lista y columnas -------------------

    def _resolve_list_id_by_name(self, display_name: str) -> str:
        resp = self.client.get(
            f"/sites/{self.site_id}/lists?$filter=displayName eq '{display_name}'&$top=1"
        )
        items = resp.get("value", []) if resp else []
        if not items:
            raise RuntimeError(f"SharePoint list '{display_name}' not found")
        return items[0]["id"]

    def _load_columns_metadata(self) -> tuple:
        resp = self.client.get(
            f"/sites/{self.site_id}/lists/{self.list_id}/columns?$select=name,displayName,readOnly,calculated&$top=200"
        )
        cols = {}
        meta = {}
        for c in (resp.get("value") or []):
            name = c.get("name")
            cols[name] = c.get("displayName") or name
            meta[name] = {
                "readOnly": c.get("readOnly", False),
                "calculated": c.get("calculated") is not None
            }
        
        cols["Title"] = "Employee ID"
        return cols, meta

    # -------------------------------- Búsqueda & Filtros --------------------

    def get_unique_pay_groups(self):
        """Obtiene una lista única de Pay Groups escaneando una muestra de empleados."""
        # Field_5 es Pay Group según COL_MAP
        pg_field = self.COL_MAP['PAY_GROUP']
        endpoint = f"/sites/{self.site_id}/lists/{self.list_id}/items?expand=fields($select={pg_field})&$top=1000"
        try:
            r = self.client.get(endpoint)
            items = r.get("value") or []
            unique = set()
            for i in items:
                val = i.get("fields", {}).get(pg_field)
                if val: unique.add(val)
            return sorted(list(unique))
        except Exception as e:
            print(f"Warning fetching pay groups: {e}")
            return []

    def get_unique_statuses(self):
        """Obtiene una lista única de Status (Active, Terminated, etc.) escaneando una muestra."""
        st_field = self.COL_MAP['EMPLOYEE_STATUS'] # field_4
        endpoint = f"/sites/{self.site_id}/lists/{self.list_id}/items?expand=fields($select={st_field})&$top=1000"
        try:
            r = self.client.get(endpoint)
            items = r.get("value") or []
            unique = set()
            for i in items:
                val = i.get("fields", {}).get(st_field)
                if val: unique.add(val)
            return sorted(list(unique))
        except Exception as e:
            print(f"Warning fetching statuses: {e}")
            return []

    def _esc(self, s: str) -> str:
        return s.replace("'", "''")

    def _norm(self, s: str) -> str:
        if not s: return ""
        s = "".join(ch for ch in unicodedata.normalize("NFD", str(s)) if unicodedata.category(ch) != "Mn")
        return s.lower().strip()

    def search_employee(self, query: str, pay_group_filter: str = None, status_filter: str = None):
        """
        Busca empleados.
        Retorna: (lista_resultados, limite_alcanzado_bool)
        """
        # Permitir búsqueda vacía SOLO si hay filtro activo (Pay Group o Status)
        has_query = query and len(query.strip()) >= 2
        has_pg_filter = pay_group_filter and pay_group_filter.strip()
        has_st_filter = status_filter and status_filter.strip()

        if not has_query and not has_pg_filter and not has_st_filter:
            return [], False

        q = query.strip() if query else ""
        c = self.COL_MAP
        found = {}

        # Construcción dinámica de filtros adicionales (AND)
        extra_filters = ""
        
        if has_pg_filter:
            pg_val = self._esc(pay_group_filter.strip())
            pg_col = c['PAY_GROUP']
            # Usamos 'eq' (igual exacto) porque viene de un Dropdown
            extra_filters += f" and fields/{pg_col} eq '{pg_val}'"
            
        if has_st_filter:
            st_val = self._esc(status_filter.strip())
            st_col = c['EMPLOYEE_STATUS']
            extra_filters += f" and fields/{st_col} eq '{st_val}'"

        # ESTRATEGIA 1: Si no hay texto, buscamos solo por Filtros
        if not has_query and (has_pg_filter or has_st_filter):
            # Eliminamos el primer " and " para que la query sea sintácticamente válida
            base_filter = extra_filters.lstrip(" and ")
            self._atomic_search(base_filter, found)
        
        # ESTRATEGIA 2: Si hay texto, usamos la lógica de tokens + filtros
        else:
            if q.isdigit():
                self._atomic_search(f"startswith(fields/{c['EE_ID']}, '{self._esc(q)}'){extra_filters}", found)
                self._atomic_search(f"startswith(fields/{c['FILE_NUMBER']}, '{self._esc(q)}'){extra_filters}", found)
            else:
                tokens = [t for t in q.split() if t]
                for t in tokens:
                    et = self._esc(t)
                    self._atomic_search(f"startswith(fields/{c['FIRST_NAME']}, '{et}'){extra_filters}", found)
                    self._atomic_search(f"startswith(fields/{c['LAST_NAME']}, '{et}'){extra_filters}", found)
                    self._atomic_search(f"startswith(fields/{c['EE_ID']}, '{et}'){extra_filters}", found)

                if len(tokens) >= 2:
                    a, b = self._esc(tokens[0]), self._esc(tokens[1])
                    self._atomic_search(f"(startswith(fields/{c['FIRST_NAME']}, '{a}') and startswith(fields/{c['LAST_NAME']}, '{b}')){extra_filters}", found)
                    self._atomic_search(f"(startswith(fields/{c['LAST_NAME']}, '{a}') and startswith(fields/{c['FIRST_NAME']}, '{b}')){extra_filters}", found)

        results = list(found.values())

        # Post-filtro si usamos tokens (para mejorar precisión de nombre completo)
        if has_query and not q.isdigit():
            try:
                tokens = [t for t in q.split() if t]
                nqs = [self._norm(t) for t in tokens]
                if len(tokens) >= 2:
                    def match_two(r):
                        fn = self._norm(r.get("first_name"))
                        ln = self._norm(r.get("last_name"))
                        return (fn.startswith(nqs[0]) and ln.startswith(nqs[1])) or \
                               (ln.startswith(nqs[0]) and fn.startswith(nqs[1]))
                    results = [r for r in results if match_two(r)]
            except: pass

        # Detectar si alcanzamos el límite (indicador de que hay más resultados)
        limit_reached = len(results) >= self.SEARCH_LIMIT
        return results, limit_reached

    def _atomic_search(self, filter_clause: str, results_dict: dict):
        endpoint = (
            f"/sites/{self.site_id}/lists/{self.list_id}/items"
            f"?expand=fields&$filter={filter_clause}&$top={self.SEARCH_LIMIT}"
        )
        headers = {"Prefer": "HonorNonIndexedQueriesWarningMayFailRandomly"}
        try:
            result = self.client.get(endpoint, extra_headers=headers)
            for item in (result.get("value") or []):
                sp_id = item["id"]
                if sp_id not in results_dict:
                    results_dict[sp_id] = self._map_employee_item(item)
        except Exception as e:
            print(f"⚠️ Error en sub-búsqueda ({filter_clause}): {e}")

    # ------------------------------ Mapeo -----------------------------------

    def _map_employee_item(self, item: dict) -> dict:
        f = item.get("fields", {}) or {}
        c = self.COL_MAP

        first = f.get(c["FIRST_NAME"], "") or ""
        last = f.get(c["LAST_NAME"], "") or ""
        full_name = f"{first} {last}".strip() or "Name Not Available"
        email = f.get(c["WORK_EMAIL"]) or f.get(c["PERSONAL_EMAIL"]) or "N/A"

        pay_info = self._compute_pay_info(
            f.get(c["PAY_RATE"]),
            f.get(c["PRIMARY_PAY_RATE"]),
            f.get(c["HOURLY_RATE_2"])
        )

        raw_history = f.get(c["CHANGE_HISTORY"], "")
        change_history = self._parse_change_history(raw_history)

        return {
            "id": f.get(c["EE_ID"], "N/A"),
            "file_number": f.get(c["FILE_NUMBER"], "N/A"),
            "first_name": first,
            "last_name": last,
            "full_name": full_name,
            "job_title": f.get(c["JOB_TITLE"], "N/A"),
            "department": f.get(c["DEPARTMENT_CODE"], "N/A"),
            "status": f.get(c["EMPLOYEE_STATUS"], "Active") or "Active",
            "email": email,
            "pay_group": f.get(c["PAY_GROUP"], "N/A"),
            "company": f.get(c["COMPANY_CODE"], "N/A"),
            "pay_info": pay_info,
            "change_history": change_history,
            "_raw_fields": f,          
            "_raw_history_json": raw_history, 
            "sp_item_id": item.get("id"),
        }

    def _compute_pay_info(self, pay_rate, primary_rate, hourly2):
        def split_opts(val):
            if val is None: return []
            s = str(val).strip()
            return [p.strip() for p in s.split("/") if p.strip()] if "/" in s else ([s] if s else [])

        pr, ppr, hr2 = split_opts(pay_rate), split_opts(primary_rate), split_opts(hourly2)
        needs_conf = (len(pr) > 1) or (len(ppr) > 1) or (len(hr2) > 1)
        
        grouped = {
            "field_23": {"label": "Pay Rate (Annual/Hourly)", "values": pr},
            "field_24": {"label": "Primary Pay Rate", "values": ppr},
            "field_25": {"label": "Hourly Rate 2", "values": hr2},
        }
        return {"needs_confirmation": needs_conf, "grouped": grouped}

    def _parse_change_history(self, raw):
        if not raw: return {"parsed": [], "raw": ""}
        s = str(raw)
        try:
            data = json.loads(s)
            timeline = []
            if isinstance(data, dict): data = data.get("history") or data.get("changes") or []
            if isinstance(data, list):
                for ev in data:
                    timeline.append({
                        "date": ev.get("date") or ev.get("timestamp"),
                        "user": ev.get("user") or ev.get("by"),
                        "field": ev.get("field") or ev.get("column"),
                        "old": ev.get("old") or ev.get("from"),
                        "new": ev.get("new") or ev.get("to"),
                    })
            timeline.sort(key=lambda x: x.get("date", ""), reverse=True)
            return {"parsed": timeline, "raw": s}
        except Exception: return {"parsed": [], "raw": s}

    # ------------------------------ Update & Append -------------------------

    def append_history_entry(self, current_raw_json, user_display_name, field_label, old_value, new_value):
        history_list = []
        if current_raw_json:
            try:
                data = json.loads(str(current_raw_json))
                if isinstance(data, dict):
                    history_list = data.get("history") or data.get("changes") or []
                elif isinstance(data, list):
                    history_list = data
            except:
                pass 
        
        new_event = {
            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "user": user_display_name,
            "field": field_label,
            "old": str(old_value),
            "new": str(new_value)
        }
        history_list.append(new_event)
        return json.dumps({"history": history_list})

    def update_employee_fields(self, sp_item_id: str, updates: dict):
        endpoint = f"/sites/{self.site_id}/lists/{self.list_id}/items/{sp_item_id}/fields"
        result = self.client.patch(endpoint, updates)
        return result or {}

    # --------------------- Utilidad para detalle dinámico -------------------

    def get_pretty_fields_for_detail(self, raw_fields: dict):
        rows = []
        core_internal_names = set(self.COL_MAP.values())
        change_history_col_name = self.COL_MAP["CHANGE_HISTORY"]

        for key, val in raw_fields.items():
            if any(key.startswith(pref) for pref in self.HIDDEN_FIELD_PREFIXES): continue
            if key.endswith("LookupId"): continue
            if key in self.HIDDEN_FIELD_EXACT: continue
            if key == change_history_col_name: continue

            c_meta = self.columns_meta.get(key)
            if c_meta:
                if c_meta.get("readOnly") and not c_meta.get("calculated") and key not in core_internal_names:
                    continue

            label = self.columns_map.get(key, key)
            if isinstance(val, (dict, list)):
                try: val = json.dumps(val, ensure_ascii=False)
                except: val = str(val)
            
            rows.append((label, str(val)))

        def sort_key(row):
            label_lower = row[0].lower()
            if label_lower == "employee id": return (0, label_lower)
            return (1, label_lower)

        rows.sort(key=sort_key)
        return rows