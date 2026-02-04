import flet as ft
import time
import threading
import os
import getpass
import json
import traceback
import pythoncom 
from datetime import datetime
from ui.styles import SSA_GREEN, SSA_GREY, SSA_WHITE, SSA_BG, SSA_BORDER
from services.timecard_service import TimecardService
from services.adp_service import ADPService
from ui.emergency_handler import EmergencyHandler

try:
    import win32com.client as win32
    HAS_OUTLOOK_LIB = True
except ImportError:
    HAS_OUTLOOK_LIB = False
    print("⚠️ 'pywin32' not found. Outlook integration disabled.")

class TimecardView(ft.Container):
    def __init__(self, page: ft.Page, watcher_service):
        super().__init__()
        self.page = page
        self.service = TimecardService()
        self.watcher = watcher_service
        self.adp_service = ADPService()
        self.expand = True
        self.padding = 20
        self.bgcolor = SSA_BG
        
        self.active_cycle_date = "Scanning..." # Mantenemos esto como fallback visual
        self.current_view_date = None          # Nueva variable para el control del estado
        self.available_cycles = []             # Cache de ciclos

        self._polling_active = False 
        self._paused_polling = False
        self._first_load = True
        
        self._ui_lock = threading.Lock()
        
        self.pending_signoff_item = None
        self.current_review_item = None 
        self.current_review_warnings = [] 
        self.current_review_compliance = [] 
        
        self.pending_verifications = {} 
        self.pending_compliance_item = None
        self.compliance_data_list = []
        self.compliance_results = {} 
        self.compliance_error_details = {} 
        
        self.active_dialog_ref = None
        self.compliance_progress_text = None
        self.verification_progress_text = None
        
        self.revoke_selection = {} 
        self.revoke_emp_list_data = [] 
        self.revoke_checkbox_container = None 
        self.revoke_filter_field = None

        self.notif_active_item_id = None
        self.notif_polling_active = False
        self.draft_subject_field = None
        self.draft_body_field = None
        self.draft_to_field = None
        self.refine_prompt_field = None
        self.notif_status_text = None
        self.ai_loading_bar = None
        self.btn_refine = None
        self.btn_outlook = None
        
        self.evidence_dropdown = None

        self.setup_ui()
        self.start_polling()

    def did_mount(self):
        EmergencyHandler.register(self._perform_emergency_reset)
        self.start_polling()

    def will_unmount(self):
        EmergencyHandler.unregister(self._perform_emergency_reset)
        self.stop_polling()
        self.notif_polling_active = False 

    def _perform_emergency_reset(self):
        print("   -> ☢️ NUCLEAR RESET TimecardView...")
        self._polling_active = False
        self._paused_polling = False
        self.notif_polling_active = False
        self.active_dialog_ref = None
        
        try:
            self.content = None 
            self.clean() 
            self.setup_ui()
            self.update() 
            self._first_load = True
            self.start_polling()
            self.show_snack("♻️ Vista de Timecards reconstruida correctamente.", ft.Colors.GREEN_800)
        except Exception as e:
            print(f"   ❌ Fallo crítico reconstruyendo TimecardView: {e}")
            traceback.print_exc()

    def setup_ui(self):
        self.context_title = ft.Text("No Active Task", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_500)
        self.context_subtitle = ft.Text("Select an item to start working", size=12, color=ft.Colors.GREY_400)
        self.context_icon = ft.Icon(ft.Icons.WORK_OFF, color=ft.Colors.GREY_400, size=30)
        
        self.active_context_card = ft.Container(
            content=ft.Row([
                self.context_icon,
                ft.Column([self.context_title, self.context_subtitle], spacing=2, expand=True)
            ], alignment=ft.MainAxisAlignment.START),
            padding=15,
            bgcolor=ft.Colors.WHITE,
            border_radius=10,
            border=ft.border.all(1, ft.Colors.GREY_200),
            visible=True
        )

        # REEMPLAZADO: Texto estático por Dropdown interactivo
        self.cycle_dropdown = ft.Dropdown(
            label="Payroll Cycle",
            width=200,
            text_size=13,
            border_color=SSA_GREEN,
            border_radius=8,
            content_padding=10,
            filled=True,
            bgcolor=ft.Colors.WHITE,
            options=[],
            on_change=self._on_cycle_change
        )

        header = ft.Row([
            ft.Column([
                ft.Text("Timecard Posting Center", size=24, weight=ft.FontWeight.BOLD, color=SSA_GREY),
                ft.Text("Monitor & Process Weekly Reports", size=12, color=ft.Colors.GREY_500)
            ], spacing=2),
            ft.Container(expand=True),
            # Contenedor del Dropdown
            ft.Row([
                ft.Icon(ft.Icons.DATE_RANGE, color=SSA_GREEN, size=16),
                self.cycle_dropdown
            ], alignment=ft.MainAxisAlignment.END, spacing=10),
            ft.IconButton(ft.Icons.REFRESH, icon_color=SSA_GREEN, tooltip="Force Refresh", on_click=self.force_refresh)
        ])

        self.table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("PC#")),
                ft.DataColumn(ft.Text("Location")),
                ft.DataColumn(ft.Text("Status")), 
                ft.DataColumn(ft.Text("Actions")), 
                ft.DataColumn(ft.Text("Signed Off")),
                ft.DataColumn(ft.Text("Report")), 
                ft.DataColumn(ft.Text("Processed By")),
                ft.DataColumn(ft.Text("Problems")),
            ],
            rows=[],
            heading_row_color=ft.Colors.GREY_200,
            expand=True,
            data_row_min_height=50
        )
        
        self.loading_indicator = ft.ProgressRing(width=30, height=30, color=SSA_GREEN, visible=False)
        
        self.content = ft.Column([
            header,
            ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
            self.active_context_card,
            ft.Divider(),
            ft.Row([self.loading_indicator], alignment=ft.MainAxisAlignment.CENTER),
            ft.Column([self.table], scroll=ft.ScrollMode.AUTO, expand=True)
        ], expand=True)

    def _on_cycle_change(self, e):
        """Maneja el cambio de selección en el dropdown de ciclos."""
        new_cycle = self.cycle_dropdown.value
        if new_cycle:
            self.current_view_date = new_cycle
            self.active_cycle_date = new_cycle # Mantenemos sincronizados
            self.show_snack(f"📅 Cambiando vista al ciclo: {new_cycle}...", ft.Colors.BLUE_GREY)
            # Forzamos refresh inmediato en hilo secundario
            threading.Thread(target=self._fetch_and_update_ui, daemon=True).start()

    def set_active_context(self, pc, location, mode="review"):
        self.context_title.value = f"Managing: {pc} - {location}"
        if mode == "review":
            self.context_subtitle.value = "Mode: BOT REVIEW - Analyzing data..."
            self.context_icon.name = ft.Icons.RATE_REVIEW
            self.context_icon.color = ft.Colors.BLUE
            self.active_context_card.border = ft.border.all(2, ft.Colors.BLUE)
            self.active_context_card.bgcolor = ft.Colors.BLUE_50
        elif mode == "posting":
            self.context_subtitle.value = "Mode: POSTING - ADP Sign Off & PDF Retrieval"
            self.context_icon.name = ft.Icons.UPLOAD_FILE
            self.context_icon.color = ft.Colors.ORANGE
            self.active_context_card.border = ft.border.all(2, ft.Colors.ORANGE)
            self.active_context_card.bgcolor = ft.Colors.ORANGE_50
        
        try: self.active_context_card.update()
        except: pass

    def clear_active_context(self):
        self.context_title.value = "No Active Task"
        self.context_subtitle.value = "Select an item to start working"
        self.context_icon.name = ft.Icons.WORK_OFF
        self.context_icon.color = ft.Colors.GREY_400
        self.active_context_card.border = ft.border.all(1, ft.Colors.GREY_200)
        self.active_context_card.bgcolor = ft.Colors.WHITE
        try: self.active_context_card.update()
        except: pass

    def show_snack(self, text, color, duration=4000):
        try:
            self.page.snack_bar = ft.SnackBar(ft.Text(text), bgcolor=color, duration=duration)
            self.page.snack_bar.open = True
            self.page.update()
        except: pass

    def start_polling(self):
        if self._polling_active: return
        self._polling_active = True
        threading.Thread(target=self._poll_data_loop, daemon=True).start()

    def stop_polling(self):
        self._polling_active = False

    def force_refresh(self, e):
        self.page.snack_bar = ft.SnackBar(ft.Text("Refreshing data..."), bgcolor=SSA_GREY, duration=1000)
        self.page.snack_bar.open = True
        self.page.update()
        threading.Thread(target=self._fetch_and_update_ui, daemon=True).start()

    def _poll_data_loop(self):
        while self._polling_active:
            if not self._paused_polling:
                try:
                    self._fetch_and_update_ui()
                    if self._first_load:
                        self._first_load = False
                        self.loading_indicator.visible = False
                        self.loading_indicator.update()
                except Exception as e:
                    pass
            for _ in range(30): 
                if not self._polling_active: break
                time.sleep(0.1)

    def _fetch_and_update_ui(self):
        try:
            # 1. Cargar lista de ciclos si no existe
            if not self.available_cycles:
                cycles = self.service.get_available_cycles()
                if cycles:
                    self.available_cycles = cycles
                    # Actualizar opciones del dropdown
                    with self._ui_lock:
                        self.cycle_dropdown.options = [ft.dropdown.Option(c) for c in cycles]
                        # Si no hay selección actual, seleccionar el primero (más reciente)
                        if not self.current_view_date:
                            self.current_view_date = cycles[0]
                            self.cycle_dropdown.value = cycles[0]
                        self.cycle_dropdown.update()

            # 2. Determinar qué fecha consultar (Historial o Actual)
            target_date = self.current_view_date
            
            # 3. Llamar al servicio con el filtro de fecha
            items, active_date_str = self.service.get_active_timecards(target_date=target_date)
            
            # Asegurar que la UI refleje la fecha real retornada por el servicio
            if active_date_str and not self.current_view_date:
                 self.current_view_date = active_date_str
                 self.active_cycle_date = active_date_str

            new_rows = []
            for item in items:
                new_rows.append(self._build_row(item))
            
            if self._paused_polling: return

            with self._ui_lock:
                self.table.rows = new_rows
                self.table.update()
                
        except Exception as e:
            pass

    def _build_row(self, item):
        status = str(item['status']).strip()
        is_signed_off = item.get('signed_off', False)
        is_approved = item.get('Approval', False)
        
        color = ft.Colors.GREY_400 
        s_lower = status.lower()
        if s_lower == 'not ready': color = ft.Colors.GREY_500
        elif s_lower == 'not started': color = ft.Colors.BLUE
        elif s_lower == 'in progress': color = ft.Colors.ORANGE
        elif s_lower == 'done': color = SSA_GREEN
        elif s_lower == 'blocked': color = ft.Colors.RED

        action_btn = None
        
        if s_lower == 'blocked':
            action_btn = ft.ElevatedButton(
                "Resolve",
                icon=ft.Icons.BUILD_CIRCLE,
                style=ft.ButtonStyle(bgcolor=ft.Colors.RED_400, color=SSA_WHITE, padding=10),
                on_click=lambda e, i=item: self.open_unlock_dialog(i)
            )
        elif s_lower == 'not started':
            action_btn = ft.ElevatedButton(
                "Start", 
                icon=ft.Icons.PLAY_ARROW, 
                style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE, color=SSA_WHITE, padding=10),
                on_click=lambda e, i=item: self.handle_start_click(i)
            )
        elif s_lower == 'in progress':
            if not is_signed_off:
                action_btn = ft.ElevatedButton(
                    "Sign Off", 
                    icon=ft.Icons.DRAW, 
                    style=ft.ButtonStyle(bgcolor=ft.Colors.ORANGE, color=SSA_WHITE, padding=10),
                    on_click=lambda e, i=item: self.open_signoff_dialog(i)
                )
            else:
                action_btn = ft.ElevatedButton(
                    "Waiting PDF...", 
                    icon=ft.Icons.DOWNLOADING, 
                    style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_400, color=SSA_WHITE, padding=10),
                    disabled=True
                )
        elif s_lower == 'done':
            action_btn = ft.IconButton(
                icon=ft.Icons.REPLAY,
                icon_color=ft.Colors.GREY_500,
                tooltip="Revoke Sign Off / Rework",
                on_click=lambda e, i=item: self.open_revoke_dialog(i)
            )

        review_btn = ft.Container()
        if not is_approved and s_lower not in ['done', 'blocked']:
            review_btn = ft.IconButton(
                icon=ft.Icons.RATE_REVIEW, 
                icon_color=SSA_GREEN, 
                tooltip="Run Bot Review (Smart Diff)",
                on_click=lambda e, i=item: self.handle_review_click(i)
            )

        has_report = item['report_uploaded']
        # MODIFICACIÓN: Se conecta el evento on_click al manejador de apertura de PDF
        pdf_icon = ft.IconButton(
            icon=ft.Icons.PICTURE_AS_PDF, 
            icon_color=SSA_GREEN if has_report else ft.Colors.GREY_300, 
            disabled=not has_report,
            tooltip="Open Saved PDF Report",
            on_click=lambda e, i=item: self.handle_open_pdf(i)
        )
        
        problems_txt = item.get('reported_problems')
        has_problems = bool(problems_txt)
        
        prob_icon = ft.IconButton(
            icon=ft.Icons.WARNING, 
            icon_color=ft.Colors.RED if has_problems else ft.Colors.TRANSPARENT,
            disabled=not has_problems,
            tooltip="View Problems / Notify Manager",
            on_click=lambda e, i=item: self.open_problems_dialog(i)
        )

        return ft.DataRow(cells=[
            ft.DataCell(ft.Text(item['pc_number'], weight=ft.FontWeight.BOLD)),
            ft.DataCell(ft.Text(item['location'] or "---", size=12)),
            ft.DataCell(ft.Container(content=ft.Text(status, color=SSA_WHITE, size=10, weight=ft.FontWeight.BOLD), bgcolor=color, padding=5, border_radius=5, width=100, alignment=ft.alignment.center)),
            ft.DataCell(ft.Row([action_btn if action_btn else ft.Container(), review_btn])),
            ft.DataCell(ft.Icon(ft.Icons.CHECK_CIRCLE, color=SSA_GREEN if is_signed_off else ft.Colors.GREY_300)),
            ft.DataCell(pdf_icon),
            ft.DataCell(ft.Text(item['processed_by'] or "", size=10, italic=True)),
            ft.DataCell(prob_icon),
        ])

    def handle_open_pdf(self, item):
        """
        Maneja el clic en el icono PDF para abrir el archivo localmente.
        Usa self.current_view_date para asegurar que se abre el PDF del ciclo histórico correcto.
        """
        pc = item.get('pc_number')
        
        # Usamos la fecha seleccionada en el dropdown (o la actual por defecto)
        target_cycle = self.current_view_date or self.active_cycle_date
        
        self.show_snack(f"🔍 Buscando reporte para {pc} (Ciclo: {target_cycle})...", ft.Colors.BLUE)
        
        def task():
            try:
                # Usamos la fecha activa actual del ciclo
                path = self.service.get_local_report_path(pc, target_cycle)
                
                if path and os.path.exists(path):
                    self.show_snack(f"📂 Abriendo reporte...", SSA_GREEN)
                    os.startfile(path)
                else:
                    self.show_snack(f"❌ No se encontró el archivo en la red para el ciclo {target_cycle}.", ft.Colors.RED)
            except Exception as e:
                self.show_snack(f"Error abriendo PDF: {e}", ft.Colors.RED)

        threading.Thread(target=task, daemon=True).start()

    def open_problems_dialog(self, item):
        problems_text = item.get('reported_problems', '')
        if not problems_text: return
        self._paused_polling = True
        
        lines = problems_text.split('\n')
        controls = []
        for line in lines:
            line = line.strip()
            if not line: continue
            if line.startswith('[') and ']' in line and len(line) < 15:
                controls.append(ft.Container(content=ft.Text(line, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_GREY, size=12), bgcolor=ft.Colors.GREY_100, padding=5, border_radius=4))
                continue
            icon = ft.Icons.ERROR_OUTLINE; color = ft.Colors.RED
            if "Check Required" in line: icon = ft.Icons.HELP_OUTLINE; color = ft.Colors.ORANGE
            controls.append(ft.Container(content=ft.Row([ft.Icon(icon, color=color, size=16), ft.Text(line, size=14, expand=True, font_family="monospace")], vertical_alignment=ft.CrossAxisAlignment.START), padding=ft.padding.only(left=10, bottom=5)))

        email_btn = ft.ElevatedButton(
            "Notify Manager with AI",
            icon=ft.Icons.AUTO_AWESOME,
            bgcolor=ft.Colors.INDIGO_500,
            color=SSA_WHITE,
            on_click=lambda e: self.initiate_notification_flow(item)
        )

        self.active_dialog_ref = ft.AlertDialog(
            title=ft.Text("Reported Problems"), 
            content=ft.Container(content=ft.Column(controls, scroll=ft.ScrollMode.AUTO), width=500, height=300), 
            actions=[email_btn, ft.TextButton("Close", on_click=lambda e: self.close_active_dialog())],
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN
        )
        with self._ui_lock: self.page.open(self.active_dialog_ref)

    def initiate_notification_flow(self, item):
        self.close_active_dialog() 
        self._paused_polling = True 
        self.notif_active_item_id = item['id']
        
        self.show_snack("🤖 Asking AI to generate draft...", ft.Colors.INDIGO_400)
        
        def initial_request():
            try:
                self.service.update_status(item['id'], {
                    "NotificationStatus": "Requested", 
                    "RefinementPrompt": "", 
                    "DraftSubject": "",     
                    "DraftBody": ""
                })
                self.show_notification_dialog_ui()
                self.notif_polling_active = True
                threading.Thread(target=self._notif_polling_worker, daemon=True).start()
            except Exception as e:
                self.show_snack(f"Error requesting AI: {e}", ft.Colors.RED)

        threading.Thread(target=initial_request, daemon=True).start()

    def show_notification_dialog_ui(self):
        self.draft_to_field = ft.TextField(label="To (Manager)", text_size=12, read_only=True)
        self.draft_subject_field = ft.TextField(label="Subject", text_size=12)
        self.draft_body_field = ft.TextField(label="Body (AI Generated)", multiline=True, height=200, text_size=12)
        
        self.refine_prompt_field = ft.TextField(label="Instructions for AI (e.g. 'Add that it was Monday at 2pm')", hint_text="Explain what to change...", text_size=12, expand=True)
        
        self.notif_status_text = ft.Text("Waiting for AI... (~20s)", color=ft.Colors.ORANGE, weight=ft.FontWeight.BOLD)
        self.ai_loading_bar = ft.ProgressBar(width=400, color=ft.Colors.INDIGO, bgcolor=ft.Colors.INDIGO_100)
        
        self.btn_refine = ft.ElevatedButton("Refine Draft", icon=ft.Icons.AUTO_FIX_HIGH, on_click=self.request_refinement, disabled=True)
        
        self.btn_outlook = ft.ElevatedButton(
            "Open in Outlook", 
            icon=ft.Icons.MAIL_OUTLINE, 
            bgcolor=SSA_GREEN, 
            color=SSA_WHITE, 
            on_click=self.launch_outlook,
            disabled=True,
            tooltip="Open real Outlook window to paste tables/images and Send"
        )

        content = ft.Column([
            ft.Row([self.notif_status_text, self.btn_refine], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            self.ai_loading_bar,
            ft.Divider(),
            self.draft_to_field,
            self.draft_subject_field,
            self.draft_body_field,
            ft.Divider(),
            ft.Row([self.refine_prompt_field], alignment=ft.MainAxisAlignment.CENTER),
            ft.Text("Tip: You can edit the text manually OR ask AI to change it.", size=10, italic=True, color=ft.Colors.GREY)
        ], width=600, height=550, spacing=10)

        self.active_dialog_ref = ft.AlertDialog(
            title=ft.Row([ft.Icon(ft.Icons.MARK_EMAIL_UNREAD, color=ft.Colors.INDIGO), ft.Text(" AI Notification Draft")]),
            content=content,
            actions=[ft.TextButton("Cancel", on_click=self.cancel_notification), self.btn_outlook],
        )
        
        with self._ui_lock:
            self.page.open(self.active_dialog_ref)

    def _notif_polling_worker(self):
        print(f"📡 [Notif] Iniciando polling para Item ID: {self.notif_active_item_id}")
        while self.notif_polling_active and self.active_dialog_ref:
            try:
                if not self.notif_active_item_id:
                    break

                data = self.service.get_single_item_status(self.notif_active_item_id)
                if not data: 
                    time.sleep(3)
                    continue
                
                raw_status = data.get('notif_status')
                status = str(raw_status).strip().lower()
                
                if status == "readyforreview":
                    print("✅ Draft received! Updating UI.")
                    self.notif_polling_active = False 
                    self._update_ui_with_draft(data)
                
                time.sleep(3)
            except Exception as e:
                print(f"❌ Notif Polling Error: {e}")
                time.sleep(3)

    def _update_ui_with_draft(self, data):
        try:
            self.draft_to_field.value = data.get('draft_to') or ""
            self.draft_subject_field.value = data.get('draft_subject') or ""
            self.draft_body_field.value = data.get('draft_body') or ""
            
            self.notif_status_text.value = "Draft Ready for Review"
            self.notif_status_text.color = SSA_GREEN
            self.ai_loading_bar.visible = False
            
            self.draft_to_field.update()
            self.draft_subject_field.update()
            self.draft_body_field.update()
            self.notif_status_text.update()
            self.ai_loading_bar.update()
            
            self.btn_refine.disabled = False
            self.btn_outlook.disabled = False
            self.btn_refine.update()
            self.btn_outlook.update()
        except Exception as ex:
            print(f"⚠️ Error actualizando controles UI: {ex}")

    def request_refinement(self, e):
        prompt = self.refine_prompt_field.value
        if not prompt:
            self.show_snack("Please enter instructions for the AI.", ft.Colors.ORANGE)
            return

        self.btn_refine.disabled = True
        self.btn_outlook.disabled = True
        self.ai_loading_bar.visible = True
        self.notif_status_text.value = "AI is refining (~20s)..."
        self.notif_status_text.color = ft.Colors.ORANGE
        self.active_dialog_ref.update()

        def send_refinement():
            self.service.update_status(self.notif_active_item_id, {
                "RefinementPrompt": prompt,
                "NotificationStatus": "RefinementRequested"
            })
            print("📤 [Notif] Enviado RefinementRequested")
            self.notif_polling_active = True 
            threading.Thread(target=self._notif_polling_worker, daemon=True).start()

        threading.Thread(target=send_refinement, daemon=True).start()
        self.refine_prompt_field.value = "" 
        self.refine_prompt_field.update()

    def launch_outlook(self, e):
        if not HAS_OUTLOOK_LIB:
            self.show_snack("❌ 'pywin32' library missing. Cannot open Outlook.", ft.Colors.RED)
            return

        to = self.draft_to_field.value
        subject = self.draft_subject_field.value
        body = self.draft_body_field.value
        
        self.show_snack("🚀 Opening Outlook...", ft.Colors.BLUE)
        
        # OBLIGATORIO: Cerrar la UI ANTES de ejecutar lógica pesada o en paralelo
        self.close_active_dialog()
        
        def open_in_thread():
            try:
                # INICIALIZACIÓN COM PARA HILOS - ESTO SOLUCIONA EL ERROR
                pythoncom.CoInitialize()
                
                try:
                    # Intento 1: Conectar a instancia existente
                    outlook = win32.GetActiveObject('Outlook.Application')
                except Exception:
                    # Intento 2: Crear nueva instancia si no hay
                    outlook = win32.Dispatch('Outlook.Application')
                
                mail = outlook.CreateItem(0)
                mail.To = to
                # --- AUTO-CC PARA CERRAR EL CICLO ---
                mail.CC = "railspayroll@ssamarine.com"
                
                mail.Subject = subject
                html_body = body.replace("\n", "<br>")
                mail.Display() 
                
                final_html = f"""
                <div style="font-family: Calibri, sans-serif; font-size: 11pt;">
                    {html_body}
                    <br><br>
                    <span style="background-color: yellow; color: red;">
                        [PASTE YOUR EXCEL TABLE OR IMAGE HERE]
                    </span>
                    <br>
                </div>
                """
                
                if mail.HTMLBody:
                    mail.HTMLBody = final_html + mail.HTMLBody
                else:
                    mail.HTMLBody = final_html

                self.service.append_history(self.notif_active_item_id, None, "OUTLOOK_OPENED", {"manager": to})
                self.service.update_status(self.notif_active_item_id, {"NotificationStatus": "SentWrapper"})

            except Exception as ex:
                print(f"Outlook Error: {ex}")
                # Como la UI ya cerró, imprimir en consola es lo más seguro o usar un snackbar tardío
            finally:
                # Liberar recursos COM
                pythoncom.CoUninitialize()
                self._paused_polling = False

        threading.Thread(target=open_in_thread, daemon=True).start()

    def cancel_notification(self, e):
        self.notif_polling_active = False
        self.close_active_dialog()
        self._paused_polling = False

    def close_active_dialog(self):
        with self._ui_lock:
            if self.active_dialog_ref:
                try: self.page.close(self.active_dialog_ref)
                except: pass
                self.active_dialog_ref = None
        self._paused_polling = False

    def handle_review_click(self, item):
        self._paused_polling = True
        pc = item['pc_number']; loc = item['location']
        self.set_active_context(pc, loc, mode="review")
        self.show_snack(f"🤖 Connecting to ADP for {pc}...", ft.Colors.BLUE_900)
        
        threading.Thread(target=self.service.append_history, args=(item['id'], item['history'], "REVIEW_RUN", {"status": "Started"}), daemon=True).start()
        
        def task_wrapper():
            try:
                success, msg, criticals, warnings_list, compliance_list, all_employees, detected_manager = self.adp_service.run_review_process(pc, pc)
                
                if detected_manager:
                    print(f"📝 Actualizando Manager en SP: {detected_manager}")
                    self.service.update_status(item['id'], {"Manager": detected_manager})

                if all_employees: self.service.save_employee_list(item['id'], all_employees)

                timestamp = datetime.now().strftime('%H:%M')
                if criticals:
                    self.show_snack(f"⚠️ {pc}: Found Critical Errors.", ft.Colors.RED)
                    final_problems = f"[{timestamp}]\n" + "\n".join(criticals)
                    self.service.update_status(item['id'], {"ReportedProblems": final_problems})
                    self.service.append_history(item['id'], item['history'], "REVIEW_FAIL", {"reason": "Critical Errors", "count": len(criticals)})
                    self.force_refresh(None); self._paused_polling = False; return

                cache_data = self._parse_bot_cache(item.get('bot_analysis_cache'))
                validated_snapshot = cache_data.get('review_snapshot', {})
                
                filtered_warnings = []
                for w in warnings_list:
                    w_key = f"{w['emp_id']}_{w['name']}"
                    if w_key in validated_snapshot and validated_snapshot[w_key] == "valid": continue
                    filtered_warnings.append(w)

                new_cache_struct = {'compliance': compliance_list, 'review_snapshot': validated_snapshot}

                if filtered_warnings:
                    self.current_review_item = item; self.current_review_warnings = filtered_warnings; self.current_review_compliance = compliance_list
                    # FIX: CORRECCIÓN PUNTO 1 (HILOS UI)
                    # Llamamos directamente a la UI, eliminando el hilo intermedio que causaba el crash.
                    self.show_verification_dialog_fresh()
                    return 

                if success:
                      cache_json = json.dumps(new_cache_struct)
                      update_payload = {"Status": "Not Started", "Approval": True, "ReportedProblems": "", "BotAnalysisCache": cache_json}
                      self.service.update_status(item['id'], update_payload)
                      self.service.append_history(item['id'], item['history'], "REVIEW_SUCCESS", {"warnings_ignored": len(warnings_list)})
                      self.show_snack(f"✅ {pc}: Review Clean! (Ready for Start).", SSA_GREEN, duration=5000)
                      self.force_refresh(None); self._paused_polling = False

            except Exception as e:
                print(f"Error review: {e}"); self.show_snack(f"Error: {e}", ft.Colors.RED); self._paused_polling = False
                
        threading.Thread(target=task_wrapper, daemon=True).start()

    def _parse_bot_cache(self, cache_str):
        if not cache_str or cache_str == 'nan': return {'compliance': [], 'review_snapshot': {}}
        try:
            data = json.loads(cache_str)
            if isinstance(data, list): return {'compliance': data, 'review_snapshot': {}}
            elif isinstance(data, dict): return {'compliance': data.get('compliance', []), 'review_snapshot': data.get('review_snapshot', {})}
            else: return {'compliance': [], 'review_snapshot': {}}
        except: return {'compliance': [], 'review_snapshot': {}}

    def _request_ui_dialog(self, dialog_func):
        """
        [DEPRECATED/FIXED]
        Método modificado para evitar threading anidado.
        Ahora simplemente ejecuta la función directamente.
        Esto soluciona el 'AssertionError: assert self.__uid is not None'.
        """
        dialog_func()

    def show_verification_dialog_fresh(self):
        self.pending_verifications = {d['name']: "pending" for d in self.current_review_warnings}
        total = len(self.current_review_warnings)
        self.verification_progress_text = ft.Text(f"Progress: 0/{total}", weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE)
        
        rows = [self._build_verify_row(emp) for emp in self.current_review_warnings]
        
        self.active_dialog_ref = ft.AlertDialog(
            modal=True,
            title=ft.Row([ft.Text("⚠️ Verification Required"), ft.Container(expand=True), self.verification_progress_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            content=ft.Container(content=ft.Column([
                ft.Text("The following employees have No Hours & No Approval.", weight=ft.FontWeight.BOLD),
                ft.Text("Mark as Valid (Absence) or Error. Validated items will be remembered.", size=12, color=ft.Colors.GREY_600),
                ft.Divider(),
                ft.Column(rows, spacing=10, scroll=ft.ScrollMode.AUTO, height=300)
            ]), width=600, height=400),
            actions=[ft.ElevatedButton("Finish Verification", on_click=self.finish_verification_process, bgcolor=SSA_GREEN, color=SSA_WHITE)],
        )
        with self._ui_lock: self.page.open(self.active_dialog_ref)

    def _build_verify_row(self, emp_data):
        name = emp_data.get('name', 'Unknown'); emp_id = emp_data.get('emp_id', 'N/A'); file_num = emp_data.get('file_num', 'N/A')
        status_icon = ft.Icon(ft.Icons.QUESTION_MARK, color=ft.Colors.GREY)
        
        def mark_valid(e): self.pending_verifications[name] = "valid"; status_icon.name = ft.Icons.CHECK_CIRCLE; status_icon.color = SSA_GREEN; status_icon.update(); self._update_verif_progress()
        def mark_error(e): self.pending_verifications[name] = "error"; status_icon.name = ft.Icons.CANCEL; status_icon.color = ft.Colors.RED; status_icon.update(); self._update_verif_progress()

        def copy_txt(txt):
            self.page.set_clipboard(txt)
            self.show_snack(f"Copied: {txt}", ft.Colors.BLUE, 1000)

        info_col = ft.Column([
            ft.Row([
                ft.Text(name, weight=ft.FontWeight.BOLD),
                ft.IconButton(ft.Icons.COPY, icon_size=14, tooltip="Copy Name", on_click=lambda e: copy_txt(name))
            ], spacing=5),
            ft.Row([
                ft.Text(f"ID: {emp_id}", size=11, color=ft.Colors.GREY_700),
                ft.IconButton(ft.Icons.COPY, icon_size=12, tooltip="Copy ID", on_click=lambda e: copy_txt(emp_id)),
                ft.Text("|", size=11, color=ft.Colors.GREY_400),
                ft.Text(f"File #: {file_num}", size=11, color=ft.Colors.GREY_600),
                ft.IconButton(ft.Icons.COPY, icon_size=12, tooltip="Copy File #", on_click=lambda e: copy_txt(file_num))
            ], spacing=2)
        ], spacing=2, expand=True)

        return ft.Container(content=ft.Row([
                ft.Icon(ft.Icons.PERSON, color=ft.Colors.BLUE, size=30),
                info_col,
                ft.IconButton(ft.Icons.THUMB_UP, icon_color=SSA_GREEN, tooltip="Correct (Valid Absence)", on_click=mark_valid),
                ft.IconButton(ft.Icons.THUMB_DOWN, icon_color=ft.Colors.RED, tooltip="Incorrect (Missing Time)", on_click=mark_error),
                status_icon
            ], alignment=ft.MainAxisAlignment.CENTER), bgcolor=ft.colors.with_opacity(0.1, ft.colors.GREY_500), padding=10, border_radius=8, border=ft.border.all(1, ft.Colors.GREY_300))

    def _update_verif_progress(self):
        if not self.verification_progress_text: return
        total = len(self.pending_verifications); completed = sum(1 for s in self.pending_verifications.values() if s != "pending")
        self.verification_progress_text.value = f"Progress: {completed}/{total}"; self.verification_progress_text.color = SSA_GREEN if completed == total else ft.Colors.BLUE; self.verification_progress_text.update()

    def finish_verification_process(self, e):
        if "pending" in self.pending_verifications.values(): self.show_snack("⚠️ Please review all employees.", ft.Colors.ORANGE); return
        with self._ui_lock:
            if self.active_dialog_ref: self.page.close(self.active_dialog_ref); self.active_dialog_ref = None
        self.show_snack("💾 Saving verification results...", ft.Colors.BLUE)
        threading.Thread(target=lambda: (time.sleep(0.5), self._finish_verification_background()), daemon=True).start()

    def _finish_verification_background(self):
        try:
            item = self.current_review_item
            if not item: return
            cache_data = self._parse_bot_cache(item.get('bot_analysis_cache'))
            snapshot = cache_data.get('review_snapshot', {})
            errors_confirmed = []
            
            for emp_data in self.current_review_warnings:
                name = emp_data['name']; res = self.pending_verifications.get(name); key = f"{emp_data['emp_id']}_{name}"
                if res == 'valid': snapshot[key] = "valid"
                else: errors_confirmed.append(name)
            
            new_cache = {'compliance': self.current_review_compliance, 'review_snapshot': snapshot}
            cache_json = json.dumps(new_cache)

            if errors_confirmed:
                timestamp = datetime.now().strftime('%H:%M'); msg = f"[{timestamp}] Check Required: " + ", ".join(errors_confirmed)
                self.service.update_status(item['id'], {"ReportedProblems": msg, "BotAnalysisCache": cache_json})
                self.service.append_history(item['id'], item['history'], "REVIEW_VERIF_FAIL", {"errors": errors_confirmed})
                self.show_snack(f"❌ Verification finished with errors.", ft.Colors.RED)
            else:
                self.service.update_status(item['id'], {"Status": "Not Started", "Approval": True, "ReportedProblems": "", "BotAnalysisCache": cache_json})
                self.service.append_history(item['id'], item['history'], "REVIEW_VERIF_SUCCESS", {"manual_validations": len(self.pending_verifications)})
                self.show_snack(f"✅ All verified as Valid Absences.", SSA_GREEN)
            self.force_refresh(None)
        except Exception as e: print(f"Error saving verif: {e}")
        finally: self.current_review_item = None; self.current_review_warnings = []; self._paused_polling = False

    def handle_start_click(self, item):
        self._paused_polling = True
        pc = item['pc_number']; loc = item['location']
        self.set_active_context(pc, loc, mode="posting")
        
        threading.Thread(target=self.service.update_status, args=(item['id'], {"Status": "In Progress", "SOStartTime": datetime.now().isoformat(), "ProcessedBy": getpass.getuser().upper()}), daemon=True).start()
        
        cache_data = self._parse_bot_cache(item.get('bot_analysis_cache'))
        candidates = cache_data.get('compliance', [])
        
        if candidates:
            print(f"🛑 Compliance Cache Detectado: {len(candidates)} items.")
            self.pending_compliance_item = item
            self.compliance_data_list = candidates
            self.compliance_results = {c['name']: "pending" for c in candidates}
            self.compliance_error_details = {}
            self._launch_adp_task(item)
            # FIX: CORRECCIÓN PUNTO 1 (HILOS UI) - Llamada directa
            self.show_compliance_dialog_fresh()
            return 
        
        self._launch_adp_task(item)

    # =========================================================================
    #  NUEVA LÓGICA DE RESOLUCIÓN INTELIGENTE (SMART RESOLVE)
    # =========================================================================
    
    def open_unlock_dialog(self, item):
        """Punto de entrada: Inicia análisis en segundo plano."""
        self._paused_polling = True
        self.show_snack("🔍 Analyzing evidence for smart resolution...", ft.Colors.BLUE)
        
        def analyze_worker():
            draft_subject = item.get('draft_subject')
            match = None
            
            # PLAN A: Buscamos coincidencia exacta usando SERVER-SIDE Filtering
            if draft_subject:
                match = self.service.find_exact_match_evidence(draft_subject, item.get('pc_number'))
            
            if match:
                self._show_auto_resolve_dialog(item, match)
            else:
                self._show_manual_resolve_dialog(item)
                
        threading.Thread(target=analyze_worker, daemon=True).start()

    def _show_auto_resolve_dialog(self, item, match):
        """Muestra confirmación si se encontró el correo exacto."""
        content = ft.Column([
            ft.Text("✨ Auto-Match Found!", size=16, weight=ft.FontWeight.BOLD, color=SSA_GREEN),
            ft.Text("We found the exact email notification for this block:", size=14),
            ft.Container(
                content=ft.Column([
                    ft.Text(match['text'], weight=ft.FontWeight.BOLD, size=13),
                    ft.Text(f"Date: {match['created'][:16]}", size=11, color=ft.Colors.GREY)
                ]),
                bgcolor=ft.Colors.BLUE_50, padding=10, border_radius=5, border=ft.border.all(1, ft.Colors.BLUE_200)
            ),
            ft.Divider(),
            ft.Text("Do you want to use this evidence to resolve?", size=14, weight=ft.FontWeight.BOLD)
        ], tight=True, width=450)

        actions = [
            ft.TextButton("No, search manual", on_click=lambda e: (self.close_active_dialog(), self._show_manual_resolve_dialog(item))),
            ft.ElevatedButton("Yes, Resolve", bgcolor=SSA_GREEN, color=SSA_WHITE, 
                              on_click=lambda e: self._execute_smart_resolution(item, match['key'], match['text'], "Auto-Match", "Auto-Resolved via Smart Match"))
        ]

        self.active_dialog_ref = ft.AlertDialog(title=ft.Text("Smart Resolution"), content=content, actions=actions)
        with self._ui_lock: self.page.open(self.active_dialog_ref)

    def _show_manual_resolve_dialog(self, item):
        """
        Versión mejorada del diálogo manual original.
        Filtra correos por Ubicación + Fecha del Ciclo Activo.
        """
        # 1. Detectar quién causó el bloqueo (Lógica original preservada)
        problems_text = item.get('reported_problems', '')
        blocked_users = []
        if problems_text:
            lines = problems_text.split('\n')
            for line in lines:
                if "Compliance Error:" in line:
                    parts = line.split("Compliance Error:")
                    if len(parts) > 1:
                        blocked_users.append(parts[1].strip())
        
        users_col = ft.Column(spacing=5, scroll=ft.ScrollMode.AUTO, height=150)
        if blocked_users:
            for u in blocked_users:
                users_col.controls.append(ft.Row([ft.Icon(ft.Icons.PERSON_OFF, color=ft.Colors.RED, size=16), ft.Text(u, color=ft.Colors.RED_900, weight=ft.FontWeight.BOLD)], spacing=5))
        else:
            users_col.controls.append(ft.Text("No specific users found in report.", italic=True, color=ft.Colors.GREY))

        resolution_field = ft.TextField(label="Resolution Note (Required)", hint_text="How was this solved?", multiline=True, min_lines=2)
        
        # --- DROPDOWN MEJORADO ---
        self.evidence_dropdown = ft.Dropdown(
            label="Evidence (Select Email Thread)",
            options=[],
            width=400,
            hint_text=f"Searching emails for {item.get('location')}...",
            disabled=True,
            text_size=12
        )
        
        # Cargar correos en segundo plano con FILTRO DE FECHA Y CORRECCIÓN DE PC_NUMBER
        def load_candidates():
            try:
                # Usamos 'pc_number' para filtrar por código (058)
                candidates = self.service.get_audit_candidates(
                    location_code=item.get('pc_number'), 
                    active_date_str=self.active_cycle_date
                )
                
                options = [ft.dropdown.Option(key=c['key'], text=c['text']) for c in candidates]
                if not options:
                    options.append(ft.dropdown.Option(key="none", text="No emails found for this cycle/loc", disabled=True))
                
                self.evidence_dropdown.options = options
                self.evidence_dropdown.disabled = False
                self.evidence_dropdown.hint_text = "Select related email..."
                self.evidence_dropdown.update()
            except Exception as e:
                print(f"Error fetching audit candidates: {e}")
                self.evidence_dropdown.hint_text = "Error loading emails"
                self.evidence_dropdown.update()

        threading.Thread(target=load_candidates, daemon=True).start()

        def confirm_resolve(e):
            if not resolution_field.value.strip():
                self.show_snack("⚠️ Resolution note is required.", ft.Colors.ORANGE)
                return
            
            # Recolectar evidencia
            evidence_id = self.evidence_dropdown.value
            evidence_text = next((opt.text for opt in self.evidence_dropdown.options if opt.key == evidence_id), "None") if evidence_id else "None"
            
            self._execute_smart_resolution(item, evidence_id, evidence_text, "Manual-Select", resolution_field.value, blocked_users)

        dialog = ft.AlertDialog(
            title=ft.Text("Manual Resolve"),
            content=ft.Container(
                content=ft.Column([
                    ft.Text("Blocking Issues:", weight=ft.FontWeight.BOLD),
                    ft.Container(content=users_col, bgcolor=ft.Colors.RED_50, padding=5, border_radius=5),
                    ft.Divider(),
                    ft.Text("Audit Evidence (Optional but Recommended):", weight=ft.FontWeight.BOLD, size=12),
                    self.evidence_dropdown,
                    ft.Text("Resolution:", weight=ft.FontWeight.BOLD),
                    resolution_field,
                    ft.Text("Note: Moves to 'In Progress'.", size=11, color=ft.Colors.GREY_600)
                ], spacing=10),
                width=500, height=500 
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self.close_active_dialog()),
                ft.ElevatedButton("Resolve & Continue", icon=ft.Icons.CHECK, bgcolor=ft.Colors.ORANGE, color=SSA_WHITE, on_click=confirm_resolve)
            ]
        )
        self.active_dialog_ref = dialog
        with self._ui_lock: self.page.open(dialog)

    def _execute_smart_resolution(self, item, evidence_id, evidence_summary, method, reason, previous_errors=None):
        self.close_active_dialog()
        self.show_snack("🔓 Resolving & Continuing...", ft.Colors.ORANGE)
        
        # CORRECCIÓN CRÍTICA: Eliminados campos EvidenceItemId y ResolutionMethod
        # que causaban el error 400 porque no existen en la lista de SharePoint.
        updates = {
            "Status": "In Progress", 
            "ReportedProblems": "", # Se limpia el campo
            "NotificationStatus": "Resolved"
        }
        
        # Guardar en historial (Esto SÍ funciona y persiste la evidencia)
        audit_details = {
            "reason": reason, 
            "previous_errors": previous_errors or [],
            "evidence_email_id": evidence_id,
            "evidence_summary": evidence_summary,
            "method": method
        }
        
        def save_task():
            self.service.update_status(item['id'], updates)
            self.service.append_history(item['id'], item['history'], "ITEM_UNBLOCKED", audit_details)
            self.force_refresh(None)
            self._paused_polling = False
            
        threading.Thread(target=save_task, daemon=True).start()

    # --- REVOKE DIALOG MEJORADO ---
    def open_revoke_dialog(self, item):
        self._paused_polling = True
        
        raw_list = item.get('employee_list', '[]')
        try: self.revoke_emp_list_data = json.loads(raw_list) if raw_list else []
        except: self.revoke_emp_list_data = []
        
        self.revoke_selection = {} # map: name -> Checkbox
        self.revoke_checkbox_container = ft.Column(spacing=5, scroll=ft.ScrollMode.AUTO, height=300)
        self.revoke_filter_field = ft.TextField(label="Filter Employees", prefix_icon=ft.Icons.SEARCH, height=40, text_size=12, content_padding=10, on_change=self._filter_revoke_list)

        self._render_revoke_list() # Render inicial

        def select_all(e):
            for chk in self.revoke_selection.values():
                if chk.visible: chk.value = True
            self.revoke_checkbox_container.update()

        def deselect_all(e):
            for chk in self.revoke_selection.values():
                if chk.visible: chk.value = False
            self.revoke_checkbox_container.update()

        def confirm_revoke(e):
            selected = [name for name, chk in self.revoke_selection.items() if chk.value]
            if not selected and self.revoke_emp_list_data:
                self.show_snack("Select at least one employee.", ft.Colors.ORANGE); return
            
            self.close_active_dialog()
            self.show_snack("Reverting Sign Off...", ft.Colors.RED)
            updates = {"Status": "In Progress", "SignedOff": False, "ReportUploaded": False, "SOFinishTime": None, "RUFinishTime": None}
            self.service.update_status(item['id'], updates)
            self.service.append_history(item['id'], item['history'], "SIGNOFF_REVOKED", {"employees": selected})
            self.force_refresh(None); self._paused_polling = False

        dialog = ft.AlertDialog(
            title=ft.Text("Revoke Sign Off / Rework"),
            content=ft.Container(
                content=ft.Column([
                    ft.Text("Select employees requiring rework:", weight=ft.FontWeight.BOLD),
                    self.revoke_filter_field,
                    ft.Row([
                        ft.TextButton("Select All", on_click=select_all),
                        ft.TextButton("Clear", on_click=deselect_all)
                    ], alignment=ft.MainAxisAlignment.END),
                    ft.Divider(height=1),
                    self.revoke_checkbox_container
                ]), width=450, height=500
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self.close_active_dialog()),
                ft.ElevatedButton("Revoke Sign Off", bgcolor=ft.Colors.RED, color=SSA_WHITE, on_click=confirm_revoke)
            ]
        )
        self.active_dialog_ref = dialog
        with self._ui_lock: self.page.open(dialog)

    def _render_revoke_list(self, filter_text=""):
        self.revoke_checkbox_container.controls.clear()
        if not self.revoke_emp_list_data:
            self.revoke_checkbox_container.controls.append(ft.Text("⚠️ No employee list saved.", color=ft.Colors.RED))
            return

        filter_lower = filter_text.lower()
        for emp in self.revoke_emp_list_data:
            name = emp.get('name', 'Unknown')
            emp_id = emp.get('emp_id', '')
            label = f"{name} ({emp_id})"
            
            if filter_lower in label.lower():
                if name not in self.revoke_selection:
                    self.revoke_selection[name] = ft.Checkbox(label=label, value=False)
                
                chk = self.revoke_selection[name]
                chk.visible = True
                self.revoke_checkbox_container.controls.append(chk)
            else:
                if name in self.revoke_selection:
                    self.revoke_selection[name].visible = False

        try: self.revoke_checkbox_container.update()
        except: pass

    def _filter_revoke_list(self, e):
        self._render_revoke_list(e.control.value)

    # --- COMPLIANCE DIALOG ---
    def show_compliance_dialog_fresh(self):
        if not self.compliance_results: self.compliance_results = {c['name']: "pending" for c in self.compliance_data_list}
        total = len(self.compliance_data_list)
        self.compliance_progress_text = ft.Text(f"Progress: 0/{total}", weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE)
        
        rows = [self._build_compliance_row(c) for c in self.compliance_data_list]
        
        self.active_dialog_ref = ft.AlertDialog(
            modal=True,
            title=ft.Row([ft.Text("🛡️ Compliance Check"), ft.Container(expand=True), self.compliance_progress_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            content=ft.Container(content=ft.Column([ft.Text("Employees violating 30-40h Rule or High Overtime.", weight=ft.FontWeight.BOLD, color=ft.Colors.RED_400), ft.Divider(), ft.Column(rows, spacing=10, scroll=ft.ScrollMode.AUTO, height=300)]), width=800, height=500),
            actions=[ft.ElevatedButton("Finish & Proceed", on_click=self.finish_compliance_process, bgcolor=SSA_GREEN, color=SSA_WHITE)]
        )
        with self._ui_lock: self.page.open(self.active_dialog_ref)

    def _update_compliance_progress(self):
        if not self.compliance_progress_text: return
        total = len(self.compliance_data_list); completed = sum(1 for res in self.compliance_results.values() if res != "pending")
        self.compliance_progress_text.value = f"Progress: {completed}/{total}"; self.compliance_progress_text.color = SSA_GREEN if completed == total else ft.Colors.BLUE; self.compliance_progress_text.update()

    def _build_compliance_row(self, candidate):
        name = candidate.get('name'); reason = candidate.get('reason'); reg = candidate.get('regular'); ot = candidate.get('overtime')
        emp_id = candidate.get('emp_id', 'N/A'); file_num = candidate.get('file_num', 'N/A')
        current_status = self.compliance_results.get(name, "pending")
        
        icon_name = ft.Icons.HELP; icon_col = ft.Colors.GREY
        if current_status == "valid": icon_name = ft.Icons.CHECK_CIRCLE; icon_col = SSA_GREEN
        elif current_status == "error": icon_name = ft.Icons.CANCEL; icon_col = ft.Colors.RED
        icon_status = ft.Icon(icon_name, color=icon_col)
        
        comment_field = ft.TextField(label="Explain Error found in ADP", visible=(current_status == "error"), value=self.compliance_error_details.get(name, ""), text_size=12, height=40, content_padding=10, expand=True)
        comment_field.on_change = lambda e: self.compliance_error_details.update({name: comment_field.value})

        def copy_txt(txt):
            self.page.set_clipboard(txt)
            self.show_snack(f"Copied: {txt}", ft.Colors.BLUE, 1000)

        def set_valid(e): self.compliance_results[name] = "valid"; icon_status.name = ft.Icons.CHECK_CIRCLE; icon_status.color = SSA_GREEN; comment_field.visible = False; container_ref.update(); self._update_compliance_progress()
        def set_error(e): self.compliance_results[name] = "error"; icon_status.name = ft.Icons.CANCEL; icon_status.color = ft.Colors.RED; comment_field.visible = True; comment_field.focus(); container_ref.update(); self._update_compliance_progress()

        info_col = ft.Column([
            ft.Row([
                ft.Text(name, weight=ft.FontWeight.BOLD),
                ft.IconButton(ft.Icons.COPY, icon_size=14, tooltip="Copy Name", on_click=lambda e: copy_txt(name))
            ], spacing=5),
            ft.Row([
                ft.Text(f"ID: {emp_id}", size=11, color=ft.Colors.GREY_700),
                ft.IconButton(ft.Icons.COPY, icon_size=12, tooltip="Copy ID", on_click=lambda e: copy_txt(emp_id)),
                ft.Text("|", size=11, color=ft.Colors.GREY_400),
                ft.Text(f"File #: {file_num}", size=11, color=ft.Colors.GREY_600),
                ft.IconButton(ft.Icons.COPY, icon_size=12, tooltip="Copy File #", on_click=lambda e: copy_txt(file_num))
            ], spacing=2),
            ft.Text(reason, size=12, color=ft.Colors.RED_400), 
            ft.Text(f"Reg: {reg}h | OT: {ot}h", size=11, color=ft.Colors.GREY_600)
        ], expand=True, spacing=2)

        content_col = ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.GAVEL, color=ft.Colors.ORANGE, size=24),
                info_col,
                ft.ElevatedButton("Valid", bgcolor=SSA_GREEN, color="white", height=30, style=ft.ButtonStyle(padding=5), on_click=set_valid),
                ft.ElevatedButton("Error", bgcolor=ft.Colors.RED, color="white", height=30, style=ft.ButtonStyle(padding=5), on_click=set_error),
                icon_status
            ]), ft.Row([comment_field], visible=True)
        ], spacing=5)

        container_ref = ft.Container(content=content_col, bgcolor=ft.colors.GREY_50, padding=10, border_radius=8, border=ft.border.all(1, ft.Colors.GREY_300))
        return container_ref

    def finish_compliance_process(self, e):
        if "pending" in self.compliance_results.values(): self.show_snack("⚠️ Verify ALL candidates.", ft.Colors.ORANGE); return
        with self._ui_lock:
            if self.active_dialog_ref: self.page.close(self.active_dialog_ref); self.active_dialog_ref = None
        self.show_snack("Saving compliance results...", ft.Colors.BLUE)
        threading.Thread(target=lambda: (time.sleep(0.5), self._finish_compliance_logic_background()), daemon=True).start()

    def _finish_compliance_logic_background(self):
        try:
            # FIX: CORRECCIÓN PUNTO 2 (SCOPE DE VARIABLE)
            # Definimos item ANTES de los bloques condicionales para evitar UnboundLocalError
            item = self.pending_compliance_item
            
            errors_found = [name for name, res in self.compliance_results.items() if res == "error"]
            
            if errors_found:
                timestamp = datetime.now().strftime('%H:%M')
                error_lines = [f"[{timestamp}] Compliance Error: {name} - {self.compliance_error_details.get(name,'')}" for name in errors_found]
                
                current_problems = item.get('reported_problems') or ""
                final_problems = current_problems + ("\n" if current_problems else "") + "\n".join(error_lines)
                
                self.service.update_status(item['id'], {"Status": "Blocked", "ReportedProblems": final_problems})
                self.service.append_history(item['id'], item['history'], "COMPLIANCE_BLOCK", {"errors": errors_found})
                self.show_snack("🛑 Process Blocked due to Compliance Errors.", ft.Colors.RED, duration=5000)
            else:
                self.show_snack("✅ Compliance Check Passed.", SSA_GREEN)
                self.service.append_history(item['id'], item.get('history'), "COMPLIANCE_PASS")
                
            self.pending_compliance_item = None
            self._fetch_and_update_ui()
        except Exception as e:
            print(f"Error finishing compliance: {e}")
        finally:
            self._paused_polling = False

    def _launch_adp_task(self, item):
        pc = item['pc_number']
        self.show_snack(f"🚀 Launching ADP for {pc}...", ft.Colors.BLUE)
        def open_adp_task():
            try: self.adp_service.navigate_to_quicklinks()
            except: pass
            finally: 
                if not self.active_dialog_ref: self._paused_polling = False
        threading.Thread(target=open_adp_task, daemon=True).start()

    def open_signoff_dialog(self, item):
        self._paused_polling = True
        self.pending_signoff_item = item
        self.set_active_context(item['pc_number'], item['location'], mode="posting")
        
        sign_off_dialog = ft.AlertDialog(modal=True, title=ft.Text("Confirm Sign Off"), content=ft.Column([ft.Text("Have you completed Sign Off in ADP?", weight=ft.FontWeight.BOLD), ft.Text("Clicking 'Confirm' will arm the watcher.", size=12, color=ft.Colors.GREY_500)], height=80, tight=True), actions=[ft.TextButton("Cancel", on_click=lambda e: (self.close_active_dialog(), setattr(self, 'pending_signoff_item', None))), ft.ElevatedButton("Confirm & Wait PDF", bgcolor=ft.Colors.ORANGE, color=SSA_WHITE, on_click=self.confirm_signoff_task)])
        with self._ui_lock: self.active_dialog_ref = sign_off_dialog; self.page.open(sign_off_dialog)

    def confirm_signoff_task(self, e):
        if not self.pending_signoff_item: return
        item = self.pending_signoff_item; self.close_active_dialog()
        threading.Thread(target=self._process_signoff_logic, args=(item['id'], item['pc_number'], item['location'], {"SignedOff": True, "SOFinishTime": datetime.now().isoformat()}), daemon=True).start()

    def _process_signoff_logic(self, item_id, pc, loc, updates):
        try:
            self.show_snack(f"✍️ Signing off {pc}...", ft.Colors.ORANGE)
            if self.service.update_status(item_id, updates):
                self.show_snack(f"👀 Waiting for PDF for {pc}...", SSA_GREEN, duration=5000)
                self.watcher.expect_report(pc_number=pc, location=loc, on_found_callback=lambda f_path: self._on_report_found(item_id, pc, loc, f_path))
                self.force_refresh(None)
            else: self.show_snack(f"❌ Failed to sign off {pc}", ft.Colors.RED)
        except Exception as e: print(f"Error sign off: {e}")

    def _on_report_found(self, item_id, pc, loc, file_path):
        self.show_snack(f"📎 Uploading report for {pc}...", ft.Colors.BLUE)
        try:
            active_date = self.service.get_active_date_from_folders() or "Unsorted_Cycle"
            if self.service.upload_report(file_path, loc, pc, active_date):
                self.service.update_status(item_id, {"Status": "Done", "ReportUploaded": True, "RUFinishTime": datetime.now().isoformat()})
                self.show_snack(f"✅ {pc} Finished!", SSA_GREEN); self.clear_active_context()
                try: os.remove(file_path)
                except: pass
                self.force_refresh(None)
            else: self.show_snack(f"❌ Failed upload for {pc}", ft.Colors.RED)
        except Exception as e: self.show_snack(f"Error uploading: {e}", ft.Colors.RED)