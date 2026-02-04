import os
import time
import pandas as pd
import warnings
from services.adp_session import ADPSession

class ADPService:
    """
    BOT WORKER (Business Logic)
    """
    
    ADP_QUICKLINKS_URL = "https://my.adp.com/?legacySOR=Vantage#/People_ttd_pracQuickLinks;simplePortlet=dHJ1ZQ....;title=UXVpY2tMaW5rcw..../pracQuickLinks"

    def __init__(self):
        self.session = ADPSession()
        self.download_dir = self.session.download_dir

    def navigate_to_quicklinks(self, status_callback=None):
        def notify(msg):
            if status_callback: status_callback(msg)
            print(f"🤖 (Bot) {msg}")

        notify("Verifying ADP Session...")
        success, status = self.session.ensure_dashboard_context()
        
        if not success and status == "LoginRequired":
            notify("⚠️ Session inactive. Waiting for Login...")
            self.session.focus_browser()
            
            max_wait = 300 
            start_time = time.time()
            
            while time.time() - start_time < max_wait:
                time.sleep(2)
                chk_success, chk_status = self.session.ensure_dashboard_context()
                if chk_success:
                    notify("✅ Login success detected! Resuming...")
                    success = True
                    break
                
                elapsed = int(time.time() - start_time)
                if elapsed % 10 == 0:
                    notify(f"Waiting for Login... ({max_wait - elapsed}s remaining)")

            if not success:
                notify("❌ Login timeout. Please try again.")
                return False

        if not success:
            notify(f"❌ Error connecting to browser: {status}")
            return False

        driver = self.session.get_driver()
        try:
            if "pracQuickLinks" in driver.current_url:
                notify("Already at Workstation. Ready.")
                return True
            
            notify("Navigating to QuickLinks via Direct URL...")
            driver.get(self.ADP_QUICKLINKS_URL)
            return True

        except Exception as e:
            notify(f"Navigation failed: {e}")
            return False

    def run_review_process(self, pc_number, pc_name_match, skip_nav=False):
        """
        Retorna: (success, msg, criticals, warnings_list, compliance_list, all_employees, detected_manager)
        """
        if not skip_nav:
            if not self.navigate_to_quicklinks():
                 return False, "No se pudo establecer sesión de trabajo.", [], [], [], [], None

        try:
            print(f"🚀 (Bot) Iniciando revisión para PC {pc_number}...")
            
            downloaded = self._wait_for_download("Pay Processing", timeout=180)
            
            if not downloaded: 
                return False, "Timeout esperando descarga de Excel.", [], [], [], [], None

            print(f"📊 (Bot) Procesando archivo: {os.path.basename(downloaded)}")
            
            criticals, warnings_list, compliance_list, all_employees = ["Error de lectura"], [], [], []
            detected_manager = None
            read_success = False

            for _ in range(3):
                if not os.path.exists(downloaded):
                    time.sleep(1)
                    continue
                try:
                    read_success, criticals, warnings_list, compliance_list, all_employees, detected_manager = self._analyze_excel_logic(downloaded)
                    break 
                except Exception as e:
                    criticals = [f"Error Excel: {e}"]
                    time.sleep(1)

            try: os.remove(downloaded)
            except: pass

            if not read_success:
                return False, "Falló análisis del archivo", criticals, [], [], [], None

            if criticals:
                return False, "Se encontraron Errores Críticos", criticals, warnings_list, compliance_list, all_employees, detected_manager
            elif warnings_list:
                return True, "Verificación Requerida (Warnings)", [], warnings_list, compliance_list, all_employees, detected_manager
            else:
                return True, "Revisión completada exitosamente", [], [], compliance_list, all_employees, detected_manager

        except Exception as e:
            return False, f"Excepción en Bot: {str(e)}", [], [], [], [], None

    def _wait_for_download(self, partial_name, timeout=180):
        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                files = os.listdir(self.download_dir)
                candidates = [f for f in files if partial_name in f and not f.endswith('.crdownload') and not f.endswith('.tmp')]
                if candidates:
                    candidates.sort(key=lambda x: os.path.getmtime(os.path.join(self.download_dir, x)), reverse=True)
                    full_path = os.path.join(self.download_dir, candidates[0])
                    if (time.time() - os.path.getmtime(full_path)) < timeout and os.path.getsize(full_path) > 0:
                        time.sleep(1.0)
                        return full_path
            except Exception: pass
            time.sleep(1)
        return None

    def _analyze_excel_logic(self, file_path):
        """
        Retorna: (success, criticals, warnings_dicts, compliance_dicts, all_employees_list, detected_manager_string)
        """
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")
                preview_df = pd.read_excel(file_path, header=None, nrows=10)
                header_row_idx = 0
                for idx, row in preview_df.iterrows():
                    row_str = row.astype(str).str.cat(sep=" ")
                    if "Pay Group" in row_str or "Pay Class" in row_str:
                        header_row_idx = idx
                        break
                df = pd.read_excel(file_path, header=header_row_idx)

            df.columns = [str(c).strip() for c in df.columns] 
            criticals = []
            warnings_list = []
            compliance_list = []
            all_employees_list = [] 
            
            # Usamos un SET para guardar managers únicos automáticamente
            unique_managers = set()
            
            def find_col(keywords):
                return next((c for c in df.columns if any(k.lower() in c.lower() for k in keywords)), None)

            pg_col = find_col(["Pay Group", "Pay Class"])
            ma_col = find_col(["Manager Approval", "Manager Apprv"])
            mp_col = find_col(["Missed Punch"])
            name_col = find_col(["Name", "Associate"])
            am_col = find_col(["Assigned Manager"])
            emp_id_col = find_col(["Person ID", "Employee ID"])
            file_num_col = find_col(["File Number", "File #", "ADP File Number"])
            reg_col = find_col(["Regular"])
            ot_col = find_col(["Overtime"])

            if not pg_col: return False, ["Excel Estructuralmente Inválido (No Pay Group)"], [], [], [], None

            group_h = df[df[pg_col].astype(str).str.contains('H', na=False, case=False)]
            
            if group_h.empty: return True, [], [], [], [], None

            for _, row in group_h.iterrows():
                # 1. Recolección de Managers
                if am_col:
                    raw_mgr = str(row.get(am_col, '')).strip()
                    if raw_mgr and raw_mgr.lower() != 'nan':
                        unique_managers.add(raw_mgr)

                name = row.get(name_col, 'Unknown')
                e_id_val = row.get(emp_id_col, 'N/A')
                f_num_val = row.get(file_num_col, 'N/A')
                
                emp_id = str(e_id_val).split('.')[0] if pd.notna(e_id_val) else "N/A"
                file_num = str(f_num_val).split('.')[0] if pd.notna(f_num_val) else "N/A"
                
                # --- CORRECCIÓN CRÍTICA PARA NaN ---
                r_val_raw = pd.to_numeric(row.get(reg_col), errors='coerce')
                o_val_raw = pd.to_numeric(row.get(ot_col), errors='coerce')
                
                r_val = 0.0 if pd.isna(r_val_raw) else float(r_val_raw)
                o_val = 0.0 if pd.isna(o_val_raw) else float(o_val_raw)
                # -----------------------------------
                
                all_employees_list.append({
                    "name": name,
                    "emp_id": emp_id,
                    "file_num": file_num
                })
                
                display_info = {
                    "name": name,
                    "emp_id": emp_id,
                    "file_num": file_num
                }

                if pd.notna(row.get(mp_col)) and str(row.get(mp_col)).strip() != '':
                    criticals.append(f"Missed Punch: {name} ({emp_id})")
                    continue 
                
                if not ma_col:
                     criticals.append(f"Columna Approval faltante para: {name}")
                     continue

                raw_approval = str(row.get(ma_col)).strip().lower()
                is_approved = raw_approval not in ['0', '', 'nan', 'false', 'none', 'nat']
                
                if not is_approved:
                    if r_val > 0 or o_val > 0:
                        criticals.append(f"Missing Approval (Has Time): {name} ({emp_id})")
                    else:
                        warnings_list.append(display_info)
                    continue 

                # Si ambos son 0 (o eran NaN y ahora 0), lo saltamos correctamente
                if r_val == 0 and o_val == 0:
                    continue

                rule_a_ok = (30 <= r_val <= 40)
                # CAMBIO: Regla de OT ajustada al 80% (0.8)
                rule_b_ok = (o_val < (0.8 * r_val))
                
                if not (rule_a_ok and rule_b_ok):
                    reason = []
                    if not rule_a_ok: reason.append(f"Reg Hours ({r_val}) out of range [30-40]")
                    if not rule_b_ok: reason.append(f"High OT ({o_val}) vs Reg ({r_val})")
                    
                    compliance_list.append({
                        "name": name,
                        "emp_id": emp_id,
                        "file_num": file_num, 
                        "regular": r_val,
                        "overtime": o_val,
                        "reason": "; ".join(reason)
                    })

            detected_manager_str = ";".join(list(unique_managers)) if unique_managers else None

            return True, criticals, warnings_list, compliance_list, all_employees_list, detected_manager_str
        except Exception as e:
            return False, [f"Error analizando datos: {str(e)}"], [], [], [], None