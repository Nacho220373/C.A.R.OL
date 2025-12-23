import flet as ft
import threading
import time
import os
import json # Necesario para persistencia de preferencias
import webbrowser
from datetime import datetime, timezone

from sharepoint_requests_reader import SharePointRequestsReader
from deadline_calculator import DeadlineCalculator
from notification_manager import NotificationManager
from services.request_data_service import RequestDataService
from services.location_service import LocationService
from services.remediation_service import RemediationService
from services.user_service import UserService
from services.payroll_cycle_service import PayrollCycleService
from services.category_rules_service import CategoryRulesService
from services.outlook_legacy_service import OutlookLegacyService
from ui.styles import *
from ui.components import LiveStatBadge
from ui.remediation_dialog import RemediationDialog
from ui.calendar_view import CalendarView
from ui.help_tour import HelpTourDialog 

# --- NUEVO: Importar decorador de errores ---
from error_tracking import track_errors

class DashboardManager:
    """
    Controlador principal de la lógica de UI.
    Aplica patrones de fachada para servicios y gestión de estado local.
    """
    PREFS_FILE = "user_prefs.json" # Archivo local para simulación de persistencia

    def __init__(self, page: ft.Page, tabs_control: ft.Tabs, loading_container: ft.Container, status_text_control: ft.Text, welcome_large_control: ft.Text, user_name_small_control: ft.Text):
        self.page = page
        self.tabs = tabs_control
        self.loading_container = loading_container
        self.status_text = status_text_control
        self.welcome_large = welcome_large_control
        self.user_name_small = user_name_small_control

        # --- INYECCIÓN DE SERVICIOS ---
        self.reader = SharePointRequestsReader()
        self.calculator = DeadlineCalculator()
        self.notifier = NotificationManager(page)
        self.data_service = RequestDataService(self.reader, self.calculator)
        self.location_service = LocationService()
        self.remediation_service = RemediationService(self.reader)
        self.user_service = UserService()
        self.payroll_service = PayrollCycleService()
        self.rules_service = CategoryRulesService()
        self.legacy_service = OutlookLegacyService()

        # --- GESTIÓN DE ESTADO ---
        self.ui_refs = {} 
        self.grids = {}
        self.tab_refs = {}
        self.current_user = None 
        
        # Filtros Activos
        self.active_limit_dates = 1
        self.active_date_range = None
        self.current_cycle_date = None
        self.current_cycle_folder_id = None 
        self.delta_link = None              
        
        # Calendario
        self.available_dates = []
        self.calendar_dialog = None
        self.calendar_btn_text = ft.Text("Select Period", size=12, color=SSA_GREY)
        
        # Cierre de Ciclo UI
        self.close_cycle_btn = None 
        self.close_confirm_dialog = None
        self.next_cycle_picker = None
        self.next_cycle_input = None
        
        # Diálogo de Confirmación de Propiedad
        self.ownership_confirm_dialog = None
        self.ownership_confirm_text = ft.Text("")
        self.ownership_pending_change = None 
        
        # Ayuda
        self.help_dialog = None 

        # Caches de Sincronización
        self.requests_state_cache = {}
        self.requests_meta_cache = {}
        self.requests_data_cache = {}
        
        self._polling_active = False
        self._is_first_load = True # Bandera para controlar el tour al inicio
        
        # Cargar reglas en segundo plano
        def delayed_load():
            time.sleep(2)
            self.rules_service.load_data()
        threading.Thread(target=delayed_load, daemon=True).start()

        self._init_dialogs()

    # --- GESTIÓN DE PREFERENCIAS (Simulación Local) ---
    def _load_prefs(self):
        """Carga preferencias del usuario desde un JSON local."""
        try:
            if os.path.exists(self.PREFS_FILE):
                with open(self.PREFS_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error cargando prefs: {e}")
        return {}

    def _save_pref(self, key, value):
        """Guarda una preferencia en el JSON local."""
        prefs = self._load_prefs()
        prefs[key] = value
        try:
            with open(self.PREFS_FILE, 'w') as f:
                json.dump(prefs, f)
        except Exception as e:
            print(f"Error guardando prefs: {e}")

    def check_and_show_tour(self):
        """Verifica si debe mostrar el tour y lo abre si corresponde."""
        prefs = self._load_prefs()
        # Si NO está marcado 'dont_show_tour', lo mostramos
        if not prefs.get("dont_show_tour", False):
            # Pequeño delay para asegurar que la UI principal ya se pintó
            time.sleep(0.5) 
            self.open_help_tour()

    def on_tour_dismiss(self, dont_show_again):
        """Callback ejecutado cuando el usuario cierra el tour."""
        if dont_show_again:
            self._save_pref("dont_show_tour", True)
            self.notifier.send("Preferences Saved", "You won't see the tour again.", "success")

    # --- MÉTODOS EXISTENTES (Modificados) ---

    def open_help_tour(self, e=None):
        # Lazy Loading con inyección del callback
        if not self.help_dialog:
            self.help_dialog = HelpTourDialog(self.page, on_dismiss_callback=self.on_tour_dismiss)
        
        # Resetear checkbox visualmente cada vez que se abre manualmente
        self.help_dialog.dont_show_checkbox.value = False 
        self.help_dialog.current_step = 0
        self.help_dialog.update_view()
        
        self.page.open(self.help_dialog)
        self.page.update()

    def _init_dialogs(self):
        self.mail_loading_dialog = ft.AlertDialog(
            modal=True, 
            title=ft.Text("Opening Mail...", size=18, weight=ft.FontWeight.BOLD, color=SSA_GREY),
            content=ft.Container(
                content=ft.Column([
                    ft.ProgressRing(color=SSA_GREEN), 
                    ft.Text("Downloading content...\nLaunching Outlook...", size=14, color=SSA_GREY)
                ], spacing=20, alignment=ft.MainAxisAlignment.CENTER, height=100), 
                padding=20, height=150
            ), 
            actions=[],
        )
        
        self.legacy_loading_dialog = ft.AlertDialog(
            modal=True, 
            title=ft.Text("Emergency Mode...", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_GREY_700),
            content=ft.Container(
                content=ft.Column([
                    ft.ProgressRing(color=ft.Colors.BLUE_GREY_400), 
                    ft.Text("Fixing issues of new outlook...\nLaunching Classic Outlook...", size=14, color=SSA_GREY)
                ], spacing=20, alignment=ft.MainAxisAlignment.CENTER, height=100), 
                padding=20, height=150
            ), 
            actions=[],
        )
        
        self.detail_title = ft.Text("", size=20, weight=ft.FontWeight.BOLD, color=SSA_GREY)
        self.detail_subtitle = ft.Text("", size=12, color=ft.Colors.GREY)
        self.detail_files_list = ft.ListView(expand=True, spacing=5, padding=10, height=300)
        
        self.status_dropdown = ft.Dropdown(
            label="Status", width=200, text_size=13, 
            options=[ft.dropdown.Option(s) for s in ["Pending", "In Progress", "Done", "No Action Needed"]]
        )
        self.priority_dropdown = ft.Dropdown(
            label="Priority", width=150, text_size=13, 
            options=[ft.dropdown.Option(p) for p in ["1", "2", "3", "4"]]
        )
        self.category_dropdown = ft.Dropdown(
            label="Category", width=200, text_size=13, 
            options=[ft.dropdown.Option(c) for c in ["Request", "Staff Movements", "Inquiry", "Information"]]
        )
        
        self.detail_dialog = ft.AlertDialog(
            title=ft.Column([
                self.detail_title, 
                self.detail_subtitle, 
                ft.Divider(), 
                ft.Text("Edit Properties:", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY), 
                ft.Row([self.status_dropdown, self.priority_dropdown, self.category_dropdown], alignment=ft.MainAxisAlignment.START, spacing=10)
            ], spacing=5), 
            content=ft.Container(content=self.detail_files_list, width=600, bgcolor=ft.Colors.WHITE, border_radius=8), 
            actions=[
                ft.TextButton("Close", on_click=lambda e: self.page.close(self.detail_dialog), style=ft.ButtonStyle(color=SSA_GREEN))
            ], 
            actions_alignment=ft.MainAxisAlignment.END
        )

        self.next_cycle_picker = ft.DatePicker(
            on_change=self.on_next_date_picked,
            first_date=datetime(2023, 1, 1),
            last_date=datetime(2030, 12, 31)
        )
        if self.next_cycle_picker not in self.page.overlay:
            self.page.overlay.append(self.next_cycle_picker)

        self.next_cycle_input = ft.TextField(
            label="Next Cycle Start Date",
            value="",
            read_only=True,
            width=180,
            text_size=14,
            border_color=SSA_GREEN
        )
        
        def open_date_picker(e):
            try: self.next_cycle_picker.pick_date()
            except: pass

        pick_date_btn = ft.IconButton(
            icon=ft.Icons.EDIT_CALENDAR,
            icon_color=SSA_GREEN,
            tooltip="Change Date",
            on_click=open_date_picker 
        )

        self.confirm_close_text = ft.Text("", size=14)
        self.close_confirm_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Confirm Cycle Closure", color=ft.Colors.BLUE_GREY_800, weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=ft.Column([
                    self.confirm_close_text,
                    ft.Divider(),
                    ft.Text("Verify NEXT cycle start date:", weight=ft.FontWeight.BOLD, size=12, color=SSA_GREY),
                    ft.Row([self.next_cycle_input, pick_date_btn], alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ], tight=True, spacing=15),
                width=450,
                height=240,
                padding=10
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self.page.close(self.close_confirm_dialog)),
                ft.ElevatedButton("Close Cycle", bgcolor=SSA_GREEN, color="white", on_click=self.execute_cycle_close)
            ],
            actions_alignment=ft.MainAxisAlignment.END
        )

        self.ownership_confirm_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("⚠️ Ownership Conflict", color=ft.Colors.ORANGE_800, weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=self.ownership_confirm_text,
                width=400,
                padding=10
            ),
            actions=[
                ft.TextButton("Cancel", on_click=self.cancel_ownership_change),
                ft.ElevatedButton("Yes, Change It", bgcolor=ft.Colors.ORANGE, color="white", on_click=self.confirm_ownership_change)
            ],
            actions_alignment=ft.MainAxisAlignment.END
        )

        self.reply_confirm_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Reply Detected", weight=ft.FontWeight.BOLD, color=SSA_GREY),
            content=ft.Text("Did you send a reply to the user?"),
            actions=[
                ft.TextButton("No (Just checking)", on_click=lambda e: self.page.close(self.reply_confirm_dialog)),
                ft.ElevatedButton("Yes, I Replied", bgcolor=SSA_GREEN, color="white", on_click=self.confirm_reply_action)
            ],
            actions_alignment=ft.MainAxisAlignment.END
        )
        self.pending_reply_req = None 

        self.no_action_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("No Action Needed", weight=ft.FontWeight.BOLD, color=SSA_GREY),
            content=ft.Text("Was a response sent to the user?"),
            actions=[
                ft.TextButton("No (Not needed)", on_click=lambda e: self.confirm_no_action(replied=False)),
                ft.ElevatedButton("Yes (Replied)", bgcolor=SSA_GREEN, color="white", on_click=lambda e: self.confirm_no_action(replied=True))
            ],
            actions_alignment=ft.MainAxisAlignment.END
        )
        self.pending_no_action_req = None

    def cancel_ownership_change(self, e):
        self.page.close(self.ownership_confirm_dialog)
        if self.ownership_pending_change:
            req_data = self.ownership_pending_change['req_data']
            self.status_dropdown.value = req_data.get('status')
            self.status_dropdown.update()
        self.ownership_pending_change = None

    def confirm_ownership_change(self, e):
        self.page.close(self.ownership_confirm_dialog)
        if self.ownership_pending_change:
            d = self.ownership_pending_change
            self._execute_property_change(
                d['req_data'], d['new_status'], d['new_priority'], d['new_category'],
                d.get('new_reply_limit'), d.get('new_resolve_limit'),
                new_reply_time=d.get('new_reply_time', ...) 
            )
        self.ownership_pending_change = None

    def on_next_date_picked(self, e):
        if self.next_cycle_picker.value:
            fmt_date = self.next_cycle_picker.value.strftime("%m/%d/%Y")
            self.next_cycle_input.value = fmt_date
            self.next_cycle_input.update()

    def build_help_button(self):
        return ft.IconButton(
            icon=ft.Icons.HELP_OUTLINE,
            icon_color=SSA_GREY,
            tooltip="Guía rápida / Ayuda",
            on_click=self.open_help_tour,
            bgcolor=ft.Colors.WHITE,
            style=ft.ButtonStyle(shape=ft.CircleBorder()) 
        )

    def build_calendar_button(self):
        return ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.CALENDAR_MONTH, color=SSA_GREEN, size=16), 
                self.calendar_btn_text
            ], spacing=5),
            padding=ft.padding.symmetric(horizontal=15, vertical=8), 
            border=ft.border.all(1, SSA_BORDER), 
            border_radius=8, 
            bgcolor=ft.Colors.WHITE, 
            ink=True, 
            on_click=self.open_calendar_dialog, 
            tooltip="Filter by Payroll Date Range"
        )

    def build_close_cycle_button(self):
        self.close_cycle_btn = ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.UPDATE, color=ft.Colors.WHITE, size=16), 
                ft.Text("Close Cycle", size=12, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD)
            ], spacing=5),
            padding=ft.padding.symmetric(horizontal=15, vertical=8), 
            border_radius=8, 
            bgcolor=ft.Colors.GREY_400, 
            ink=False,
            tooltip="Loading...",
            visible=False 
        )
        return self.close_cycle_btn

    def update_close_cycle_button(self):
        if self.current_cycle_date and self.close_cycle_btn:
            self.close_cycle_btn.visible = True
            self.close_cycle_btn.bgcolor = ft.Colors.BLUE_GREY_700 
            self.close_cycle_btn.ink = True
            self.close_cycle_btn.on_click = self.prompt_close_cycle
            self.close_cycle_btn.tooltip = "Close current payroll cycle"
            try:
                dt = datetime.strptime(self.current_cycle_date, "%Y%m%d")
                formatted_date = dt.strftime("%m/%d/%Y")
            except:
                formatted_date = self.current_cycle_date
            row = self.close_cycle_btn.content
            if len(row.controls) > 1:
                row.controls[1].value = f"{formatted_date} Payroll Cycle"
            self.close_cycle_btn.update()

    def prompt_close_cycle(self, e):
        if not self.current_cycle_date: return
        suggested_dt = self.payroll_service.calculate_next_cycle_date(self.current_cycle_date)
        self.next_cycle_picker.value = suggested_dt
        self.next_cycle_input.value = suggested_dt.strftime("%m/%d/%Y")
        
        try:
            curr_dt_obj = datetime.strptime(self.current_cycle_date, "%Y%m%d")
            curr_str_fmt = curr_dt_obj.strftime("%m/%d/%Y")
        except:
            curr_str_fmt = self.current_cycle_date

        user = self.user_name_small.value or "Unknown"
        msg = (
            f"Current Cycle: {curr_str_fmt}\n"
            f"Closing User: {user}\n\n"
            "This action will close the current period and create the next folder structure."
        )
        self.confirm_close_text.value = msg
        self.page.open(self.close_confirm_dialog)
        self.page.update()

    @track_errors("Executing Cycle Closure") # --- PROTEGIDO ---
    def execute_cycle_close(self, e):
        visual_date = self.next_cycle_input.value
        if not visual_date: return
        try:
            dt = datetime.strptime(visual_date, "%m/%d/%Y")
            system_date_str = dt.strftime("%Y%m%d")
        except ValueError:
            self.notifier.send("Error", "Invalid date format. Please use MM/DD/YYYY", "error")
            return

        self.page.close(self.close_confirm_dialog)
        self.loading_container.visible = True
        self.status_text.value = f"Closing {self.current_cycle_date}... Creating {system_date_str}..."
        self.page.update()
        
        def task():
            user = self.user_name_small.value or "Unknown User"
            result = self.payroll_service.execute_cycle_closure(self.current_cycle_date, system_date_str, user)
            if result['success']:
                self.notifier.send("Cycle Closed", result['message'], "success")
                time.sleep(2)
            else:
                self.notifier.send("Error", result['message'], "error")
            self.loading_container.visible = False
            self.page.update()
        threading.Thread(target=task, daemon=True).start()

    def open_calendar_dialog(self, e):
        if not self.calendar_dialog:
            self.calendar_dialog = ft.AlertDialog(
                content=CalendarView(
                    self.available_dates, 
                    self.on_calendar_range_selected, 
                    on_dismiss=lambda: self.page.close(self.calendar_dialog)
                ), 
                content_padding=0, 
                bgcolor=ft.Colors.TRANSPARENT, 
                modal=True
            )
        self.page.open(self.calendar_dialog)
        self.page.update()

    def on_calendar_range_selected(self, start_date, end_date):
        self.page.close(self.calendar_dialog)
        fmt = "%b %d"
        if start_date == end_date:
            label = f"{start_date.strftime(fmt)}"
        else:
            label = f"{start_date.strftime(fmt)} - {end_date.strftime(fmt)}"
        self.calendar_btn_text.value = label
        self.calendar_btn_text.update()
        self.load_data(date_range=(start_date, end_date), silent=True)

    def is_status_todo(self, status):
        s = str(status or "").lower()
        return "pending" in s or "progress" in s

    def resolve_category_key(self, raw_val):
        raw = str(raw_val or "").lower()
        for cat in ["Request", "Staff Movements", "Inquiry", "Information"]:
            if cat.lower() in raw: 
                return cat
        return "New Email"

    def _get_grid_config(self):
        return {
            "expand": 1, "runs_count": 4, "max_extent": 320, 
            "child_aspect_ratio": 0.95, "spacing": 20, "run_spacing": 20
        }

    def _ensure_category_tab(self, category_name):
        if category_name not in self.grids:
            grid = ft.GridView(**self._get_grid_config())
            self.grids[category_name] = grid
            tab = ft.Tab(text=f"{category_name}", content=ft.Container(content=grid, padding=20))
            self.tab_refs[category_name] = tab
            self.tabs.tabs.append(tab)
            self.tabs.update()

    def _remove_category_tab_if_empty(self, category_name):
        if category_name == "To Do": 
            return 
        if category_name in self.grids and len(self.grids[category_name].controls) == 0:
            tab = self.tab_refs.get(category_name)
            if tab and tab in self.tabs.tabs: 
                self.tabs.tabs.remove(tab)
            del self.grids[category_name]
            if category_name in self.tab_refs: 
                del self.tab_refs[category_name]
            self.tabs.update()

    def start(self):
        self._polling_active = True
        threading.Thread(target=self.background_poller, daemon=True).start()

    def stop_polling(self):
        self._polling_active = False

    @track_errors("Loading Initial Data") # --- PROTEGIDO ---
    def load_data(self, limit_dates: int = 1, date_range=None, silent=False):
        self.active_limit_dates = limit_dates
        self.active_date_range = date_range
        self.delta_link = None 
        
        self.loading_container.visible = True
        self.tabs.visible = False
        self.status_text.value = "Initializing..." if not silent else "Updating period..."
        self.page.update()

        def on_progress_update(processed, total, eta_sec):
            if not self.loading_container.visible: return
            msg = f"Scanning Payroll Cycle: {processed}/{total}"
            if eta_sec and eta_sec > 5:
                mins, secs = divmod(int(eta_sec), 60)
                msg += f"\nEstimated time left: {mins}m {secs}s" if mins > 0 else f"\nEstimated time left: {secs}s"
            self.status_text.value = msg
            self.page.update()

        def worker():
            try:
                if not silent: 
                    self.status_text.value = "Connecting to Microsoft..."
                    self.page.update()
                
                if not self.reader.drive_id: 
                    self.reader._get_drive_id()
                
                if not self.available_dates: 
                    self.available_dates = self.reader.get_available_date_folders()
                    if self.available_dates:
                        self.available_dates.sort(reverse=True)
                        if not date_range:
                            self.current_cycle_date = self.available_dates[0]
                
                # Obtener ID de carpeta activa para Delta
                if self.current_cycle_date:
                    folders = self.reader._get_items(path=self.reader.root_path)
                    for f in folders:
                        if f['name'] == self.current_cycle_date:
                            self.current_cycle_folder_id = f['id']
                            break
                            
                # Inicializar Delta
                if self.current_cycle_folder_id:
                    self.status_text.value = "Initializing Real-time Sync..."
                    self.page.update()
                    self.delta_link = self.reader.init_delta_link(self.current_cycle_folder_id)
                    print(f"📡 Delta Tracking activado para: {self.current_cycle_date}")

                if not silent and not self.current_user:
                    self.current_user = self.user_service.get_current_user()
                    if self.current_user:
                        self.welcome_large.value = f"Hello, {self.current_user.get('givenName', 'User')}!"
                        self.welcome_large.update()
                        time.sleep(2)
                        self.welcome_large.value = ""
                        self.user_name_small.value = self.current_user.get('displayName', '')
                        self.page.update()

                if not self.location_service.valid_locations: 
                    self.location_service.load_locations()
                
                dataset = self.data_service.load(
                    limit_dates=limit_dates, 
                    date_range=date_range, 
                    include_unread=True, 
                    progress_callback=on_progress_update
                )
                
                if not silent: 
                    self.status_text.value = "Rendering..."
                    self.page.update()
                
                self.render_dataset(dataset)
                self.update_close_cycle_button()
                
                # --- CHECK TOUR (Al finalizar la primera carga) ---
                if self._is_first_load:
                    self._is_first_load = False
                    # Ejecutar en hilo de UI para evitar conflictos
                    # No necesitamos threading extra aquí porque check_and_show_tour hace update seguro
                    self.check_and_show_tour()
                
            except Exception as e:
                self.notifier.send("Error", f"Could not load data: {e}", "error")
                print(f"Error en worker: {e}")
            finally:
                self.loading_container.visible = False
                self.tabs.visible = True
                self.page.update()

        threading.Thread(target=worker, daemon=True).start()

    def render_dataset(self, dataset):
        self.ui_refs.clear()
        self.grids.clear()
        self.tab_refs.clear()
        self.tabs.tabs.clear()
        
        self.requests_state_cache.update(dataset.state_cache)
        self.requests_meta_cache.update(dataset.meta_cache)
        
        for req in dataset.processed_requests: 
            self.requests_data_cache[req['id']] = req
            
        grid_config = self._get_grid_config()
        
        grid_todo = ft.GridView(**grid_config)
        for item in dataset.todo_requests: 
            grid_todo.controls.append(self.create_request_card(item, show_category_label=True))
        
        self.grids["To Do"] = grid_todo
        tab_todo = ft.Tab(
            text=f"To Do ({len(dataset.todo_requests)})", 
            icon=ft.Icons.CHECKLIST_RTL, 
            content=ft.Container(content=grid_todo, padding=20)
        )
        self.tab_refs["To Do"] = tab_todo
        self.tabs.tabs.append(tab_todo)
        
        for cat_name, items in dataset.grouped_requests.items():
            if not items: continue
            grid = ft.GridView(**grid_config)
            for item in items: 
                grid.controls.append(self.create_request_card(item))
            self.grids[cat_name] = grid
            tab_cat = ft.Tab(text=f"({len(items)}) {cat_name}", content=ft.Container(content=grid, padding=20))
            self.tab_refs[cat_name] = tab_cat
            self.tabs.tabs.append(tab_cat)
            
        self.page.update()

    def create_request_card(self, req, show_category_label=False):
        reply_stat = req.get('reply_status', {})
        resolve_stat = req.get('resolve_status', {})
        status_val = req.get('status', 'Unknown')
        priority_val = str(req.get('priority', ''))
        category_val = req.get('category', 'General')
        loc_code = req.get('location_code', '???')
        unread_count = req.get('unread_emails', 0)
        is_loc_valid = self.location_service.is_valid(loc_code)
        
        owner_text = ""
        owner_color = ft.Colors.GREY_500
        if status_val == "In Progress":
            owner_text = f"Working: {req.get('editor', 'Unknown')}"
            owner_color = ft.Colors.BLUE
        elif status_val == "Done":
            owner_text = f"Done by: {req.get('editor', 'Unknown')}"
            owner_color = SSA_GREEN

        owner_control = ft.Container()
        if owner_text:
            owner_control = ft.Container(
                content=ft.Text(owner_text, size=10, weight=ft.FontWeight.BOLD, color=owner_color, italic=True),
                padding=ft.padding.only(top=2)
            )

        badge_text_ctrl = ft.Text(str(unread_count), size=11, color="white", weight=ft.FontWeight.BOLD)
        badge_container_ctrl = ft.Container(
            content=badge_text_ctrl, bgcolor=SSA_RED_BADGE, 
            border_radius=10, padding=ft.padding.symmetric(horizontal=6, vertical=2), 
            visible=(unread_count > 0)
        )
        
        status_container_ctrl = ft.Container(
            content=ft.Text(status_val, size=11, color=SSA_WHITE, weight=ft.FontWeight.BOLD), 
            bgcolor=get_status_color(status_val), 
            padding=ft.padding.symmetric(horizontal=8, vertical=4), 
            border_radius=6
        )
        
        priority_text_ctrl = ft.Text(priority_val, size=12, weight=ft.FontWeight.BOLD, color=get_priority_color(priority_val))
        category_text_ctrl = ft.Text(category_val.upper(), size=9, weight=ft.FontWeight.BOLD, color=get_category_color(category_val))
        
        card_border_color = SSA_BORDER if is_loc_valid and reply_stat.get('color') != 'red' else ft.Colors.RED_400
        category_label = ft.Container(content=category_text_ctrl, padding=ft.padding.only(bottom=5)) if show_category_label else ft.Container()
        
        header_controls = [
            ft.Text(req.get('request_name', 'Unnamed'), size=16, weight=ft.FontWeight.W_600, color=SSA_GREY, expand=True, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
            ft.IconButton(icon=ft.Icons.OPEN_IN_NEW, icon_color=SSA_GREEN, data=req.get('web_url'), on_click=self.open_sharepoint_link)
        ]
        
        icon_action = ft.Icons.WARNING_ROUNDED if not is_loc_valid else ft.Icons.BUILD_CIRCLE_OUTLINED
        color_action = ft.Colors.RED if not is_loc_valid else ft.Colors.GREY_400
        action_btn = ft.IconButton(
            icon=icon_action, icon_color=color_action, 
            on_click=lambda e: self.open_remediation_dialog(self.requests_data_cache.get(req['id']))
        )
        header_controls.insert(1, action_btn)
        
        reply_badge = LiveStatBadge(self.calculator, reply_stat.get('limit_date'), ft.Icons.TIMER, reply_stat.get('text'), reply_stat.get('color'), completion_date=reply_stat.get('completion_date'))
        resolve_badge = LiveStatBadge(self.calculator, resolve_stat.get('limit_date'), ft.Icons.CHECK_CIRCLE_OUTLINE, resolve_stat.get('text'), resolve_stat.get('color'), completion_date=resolve_stat.get('completion_date'))

        card_content = ft.Container(
            padding=20, bgcolor=SSA_WHITE, border_radius=12, 
            border=ft.border.all(1, card_border_color), 
            on_click=lambda _: self.show_request_details(req['id']), 
            ink=True,
            content=ft.Column([
                category_label, 
                ft.Row(header_controls, alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.START),
                ft.Text(f"Loc: {loc_code} | Created: {req.get('created_at')[:10]}", size=12, color=ft.Colors.RED if not is_loc_valid else ft.Colors.GREY_500),
                ft.Divider(height=15, thickness=1, color=SSA_BORDER),
                ft.Row([
                    ft.Column([
                        ft.Text("Reply by:", size=11, color=ft.Colors.GREY_600), 
                        reply_badge 
                    ], expand=True),
                    ft.Column([
                        ft.Text("Resolve by:", size=11, color=ft.Colors.GREY_600), 
                        resolve_badge 
                    ], expand=True)
                ]),
                ft.Row([
                    ft.Column([
                        status_container_ctrl,
                        owner_control 
                    ]), 
                    ft.Row([ft.Text("Priority:", size=11, color=ft.Colors.GREY_600), priority_text_ctrl], spacing=5)
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
            ])
        )
        
        final_card = ft.Stack([card_content, ft.Container(content=badge_container_ctrl, right=0, top=0)])
        
        if req['id'] not in self.ui_refs: 
            self.ui_refs[req['id']] = []
            
        real_grid_key = self.resolve_category_key(category_val) if not show_category_label else "To Do"
        self.ui_refs[req['id']].append({
            'status_container': status_container_ctrl, 
            'owner_control': owner_control, 
            'priority_text': priority_text_ctrl, 
            'category_text': category_text_ctrl, 
            'badge_container': badge_container_ctrl, 
            'badge_text': badge_text_ctrl,
            'reply_badge': reply_badge,
            'resolve_badge': resolve_badge,
            'card_control': final_card, 
            'parent_grid': real_grid_key
        })
        return final_card

    def update_local_ui_card(self, req_id, new_status=None, new_priority=None, new_category=None, editor_name=None, 
                             new_reply_limit=..., new_resolve_limit=..., 
                             new_reply_time=..., new_resolve_time=...):
        if req_id in self.ui_refs:
            for refs in self.ui_refs[req_id]:
                try:
                    if new_status:
                        refs['status_container'].content.value = new_status
                        refs['status_container'].bgcolor = get_status_color(new_status)
                        if refs['status_container'].page: refs['status_container'].update()
                        
                        if 'owner_control' in refs:
                            txt = ""
                            col = ft.Colors.GREY
                            if new_status == "In Progress":
                                txt = f"Working: {editor_name or 'Unknown'}"
                                col = ft.Colors.BLUE
                            elif new_status == "Done":
                                txt = f"Done by: {editor_name or 'Unknown'}"
                                col = SSA_GREEN
                            
                            if txt:
                                refs['owner_control'].content = ft.Text(txt, size=10, weight=ft.FontWeight.BOLD, color=col, italic=True)
                            else:
                                refs['owner_control'].content = None
                            if refs['owner_control'].page: refs['owner_control'].update()

                    if new_priority:
                        refs['priority_text'].value = str(new_priority)
                        refs['priority_text'].color = get_priority_color(str(new_priority))
                        if refs['priority_text'].page: refs['priority_text'].update()
                        
                    if new_category and 'category_text' in refs:
                        refs['category_text'].value = new_category.upper()
                        refs['category_text'].color = get_category_color(new_category)
                        if refs['category_text'].page: refs['category_text'].update()
                    
                    if 'reply_badge' in refs:
                        badge = refs['reply_badge']
                        changed = False
                        if new_reply_limit is not ...: 
                            badge.limit_date = new_reply_limit
                            changed = True
                        if new_reply_time is not ...:
                            comp_val = new_reply_time
                            if isinstance(comp_val, str):
                                try: comp_val = datetime.fromisoformat(comp_val.replace('Z', '+00:00'))
                                except: pass
                            badge.completion_date = comp_val
                            changed = True
                        if changed:
                            now = datetime.now(timezone.utc)
                            new_stat = self.calculator.calculate_time_left(badge.limit_date, now, badge.completion_date)
                            badge.text_control.value = new_stat['text']
                            badge.text_control.color = SSA_GREEN if new_stat['color'] == "green" else new_stat['color']
                            badge.icon_control.color = badge.text_control.color
                            if badge.page: badge.update()

                    if 'resolve_badge' in refs:
                        badge = refs['resolve_badge']
                        changed = False
                        if new_resolve_limit is not ...: 
                            badge.limit_date = new_resolve_limit
                            changed = True
                        if new_resolve_time is not ...:
                            comp_val = new_resolve_time
                            if isinstance(comp_val, str):
                                try: comp_val = datetime.fromisoformat(comp_val.replace('Z', '+00:00'))
                                except: pass
                            badge.completion_date = comp_val
                            changed = True
                        if changed:
                            now = datetime.now(timezone.utc)
                            new_stat = self.calculator.calculate_time_left(badge.limit_date, now, badge.completion_date)
                            badge.text_control.value = new_stat['text']
                            badge.text_control.color = SSA_GREEN if new_stat['color'] == "green" else new_stat['color']
                            badge.icon_control.color = badge.text_control.color
                            if badge.page: badge.update()

                except Exception as e: 
                    print(f"Warning updating UI card: {e}")

    def _execute_property_change(self, req_data, new_s, new_p, new_c, 
                                 new_reply_limit=..., new_resolve_limit=...,
                                 new_reply_time=..., new_resolve_time=...):
        """Ejecuta la actualización con protección ETag y reintento inteligente."""
        old_s, old_p, old_c = req_data.get('status'), str(req_data.get('priority')), req_data.get('category')
        my_name = self.current_user.get('displayName') if self.current_user else "Me"
        
        # --- PREPARAR DATOS ---
        if new_s == "Done" and req_data.get('status') != "Done":
            if new_resolve_time is ...:
                new_resolve_time = datetime.now(timezone.utc).isoformat()
        
        if new_s in ["Pending", "In Progress"] and req_data.get('status') in ["Done", "No Action Needed"]:
            if new_resolve_time is ...:
                new_resolve_time = None
        
        # --- ACTUALIZACIÓN OPTIMISTA EN UI ---
        update_dict = {'status': new_s, 'priority': new_p, 'category': new_c, 'editor': my_name}
        if new_reply_limit is not ...: update_dict['reply_limit'] = new_reply_limit
        if new_resolve_limit is not ...: update_dict['resolve_limit'] = new_resolve_limit
        if new_reply_time is not ...: update_dict['reply_time'] = new_reply_time
        if new_resolve_time is not ...: update_dict['resolve_time'] = new_resolve_time
        
        req_data.update(update_dict)
        self.requests_data_cache[req_data['id']] = req_data
        
        self.update_local_ui_card(
            req_id=req_data['id'], 
            new_status=new_s, 
            new_priority=new_p, 
            new_category=new_c, 
            editor_name=my_name,
            new_reply_limit=new_reply_limit,
            new_resolve_limit=new_resolve_limit,
            new_reply_time=new_reply_time,
            new_resolve_time=new_resolve_time
        )
        self.move_card_visually(req_data, new_s, new_c)
        
        # --- SINCRONIZACIÓN CON ETAG Y REINTENTO ---
        def sync_task():
            # Intento 1: Usar el ETag actual (Concurrencia Optimista)
            current_etag = req_data.get('etag')
            
            success = self.reader.update_request_metadata(
                req_data['id'], 
                new_status=new_s, 
                new_priority=new_p, 
                new_category=new_c,
                new_reply_limit=new_reply_limit,     
                new_resolve_limit=new_resolve_limit,
                new_reply_time=new_reply_time,
                new_resolve_time=new_resolve_time,
                etag=current_etag 
            )
            
            if success:
                self.notifier.send("Saved", "Changes updated in SharePoint", "success")
                return

            # Si falló, verificamos si fue por conflicto (412)
            if self.reader.client.last_error_code == 412:
                print("⚠️ Conflicto de ETag (412). Aplicando escritura forzada inmediata (Force Write)...")
                
                # INTENTO 2: FUERZA BRUTA DIRECTA (Saltamos el reintento 'smart' que fallaba)
                # Borramos el ETag para que Graph ignore la versión
                force_success = self.reader.update_request_metadata(
                    req_data['id'], 
                    new_status=new_s, 
                    new_priority=new_p, 
                    new_category=new_c,
                    new_reply_limit=new_reply_limit,     
                    new_resolve_limit=new_resolve_limit,
                    new_reply_time=new_reply_time,
                    new_resolve_time=new_resolve_time,
                    etag=None 
                )
                
                if force_success:
                    # Refrescamos el etag después de forzar para sincronizar el estado local
                    try:
                        final_fresh = self.reader.get_latest_metadata(req_data['id'])
                        if final_fresh: 
                            req_data['etag'] = final_fresh.get('etag')
                            self.requests_data_cache[req_data['id']] = req_data
                    except: pass
                    
                    self.notifier.send("Saved (Forced)", "Changes updated (conflict resolved).", "success")
                    return

            # Si llegamos aquí, falló definitivamente (Error de red, permisos, etc.)
            print(f"❌ Fallo definitivo al guardar. Código: {self.reader.client.last_error_code}")
            self.notifier.send("Error", "Failed to update SharePoint. Reloading...", "error")
            
            # Revertir UI y recargar
            self._reload_single_item(req_data['id'])
                
        threading.Thread(target=sync_task, daemon=True).start()

    def _reload_single_item(self, req_id):
        """Recarga un solo ítem desde el servidor y actualiza la UI (Recuperación de conflicto)."""
        fresh_data = self.reader.get_latest_metadata(req_id)
        if fresh_data:
            fresh_data['location_code'] = self.requests_data_cache.get(req_id, {}).get('location_code', '???')
            self.requests_data_cache[req_id] = fresh_data
            
            # Recalcular tiempos
            processed = self.calculator.process_requests([fresh_data])[0]
            
            self.update_local_ui_card(
                req_id,
                new_status=processed.get('status'),
                new_priority=processed.get('priority'),
                new_category=processed.get('category'),
                editor_name=processed.get('editor'),
                new_reply_limit=processed.get('reply_limit'),
                new_resolve_limit=processed.get('resolve_limit'),
                new_reply_time=processed.get('reply_time'),
                new_resolve_time=processed.get('resolve_time')
            )
            self.move_card_visually(processed, processed.get('status'), processed.get('category'))
            
            # Actualizar dropdowns si el diálogo está abierto
            if self.detail_dialog.open and self.detail_title.value == processed.get('request_name'):
                self.status_dropdown.value = processed.get('status')
                self.priority_dropdown.value = str(processed.get('priority'))
                self.category_dropdown.value = processed.get('category')
                self.page.update()

    @track_errors("Background Polling") # --- PROTEGIDO ---
    def background_poller(self):
        """Hilo secundario INTELIGENTE: Usa Delta Query cada 5s."""
        POLL_INTERVAL = 5 # Mucho más rápido gracias a Delta
        
        while self._polling_active:
            if not self.reader.client.is_session_valid:
                time.sleep(5)
                continue

            time.sleep(POLL_INTERVAL)
            if not self._polling_active: break
            
            # Solo ejecutamos si tenemos un delta link activo (significa que la carga inicial terminó)
            if not self.delta_link: continue
            
            try:
                # 1. Consultar cambios ligeros
                new_delta_link, changes = self.reader.fetch_changes(self.delta_link)
                
                if new_delta_link:
                    self.delta_link = new_delta_link # Guardar token para la próxima
                else:
                    # Si devuelve None (410 Gone), hay que reiniciar Delta (re-cargar datos)
                    print("🔄 Token Delta expirado. Reiniciando sincronización completa...")
                    self.load_data(limit_dates=self.active_limit_dates, date_range=self.active_date_range, silent=True)
                    continue

                if not changes: continue # Nada pasó, dormir otros 5s

                print(f"⚡ Detectados {len(changes)} cambios en tiempo real.")
                
                # 2. Procesar cambios
                changes_detected_in_ui = False
                
                for change in changes:
                    item_id = change.get('id')
                    
                    # CASO A: ELIMINACIÓN
                    if 'deleted' in change:
                        if item_id in self.requests_data_cache:
                            print(f"🗑️ Eliminando solicitud {item_id} de la UI")
                            self._remove_card_from_ui(item_id)
                            changes_detected_in_ui = True
                        continue
                    
                    # CASO B: CARPETA (Solicitud Nueva o Modificada)
                    if 'folder' in change:
                        # Si ya existe, es una actualización de metadata (status, priority, etag)
                        if item_id in self.requests_data_cache:
                            self._reload_single_item(item_id)
                            changes_detected_in_ui = True
                        
                        # Si NO existe, podría ser una solicitud nueva... O una carpeta de Ubicación (FANTASMA)
                        else:
                            # 1. Ignorar la carpeta raíz del ciclo
                            if item_id == self.current_cycle_folder_id: continue
                            
                            # 2. Traer data completa para verificar
                            new_req = self.reader.get_latest_metadata(item_id)
                            
                            # 3. FILTRO DE FANTASMAS (Ubicaciones vs Solicitudes)
                            # Las ubicaciones NO suelen tener Status/Priority/Category definidos como columnas
                            # Las solicitudes SÍ tienen al menos Status (o por defecto Pending/New)
                            has_request_metadata = new_req.get('status') or new_req.get('priority')
                            
                            if not has_request_metadata:
                                # Es probable que sea una carpeta de ubicación (Padre), la ignoramos
                                print(f"👻 Ignorando posible carpeta de ubicación: {new_req.get('name')}")
                                continue

                            # Si pasamos el filtro, es una solicitud real.
                            # 4. RESOLVER PADRE (Ubicación real)
                            parent_id = change.get('parentReference', {}).get('id')
                            if parent_id and parent_id != self.current_cycle_folder_id:
                                # Hacemos una llamada rápida para saber el nombre del padre (la ubicación)
                                parent_meta = self.reader.get_latest_metadata(parent_id)
                                new_req['location_code'] = parent_meta.get('name') if parent_meta else "Unknown"
                            else:
                                new_req['location_code'] = "New/Syncing"
                                
                            new_req['date_folder'] = self.current_cycle_date
                            new_req['unread_emails'] = 0
                            
                            # Procesar y agregar
                            proc = self.calculator.process_requests([new_req])[0]
                            self.requests_data_cache[item_id] = proc
                            
                            # Agregar a "To Do" o Categoría
                            target_cat = self.resolve_category_key(proc.get('category', 'New Email'))
                            self._ensure_category_tab(target_cat)
                            if target_cat in self.grids:
                                self.grids[target_cat].controls.insert(0, self.create_request_card(proc))
                                self.grids[target_cat].update()
                                changes_detected_in_ui = True
                    
                    # CASO C: ARCHIVO (Correo nuevo -> Actualizar Badge)
                    if 'file' in change:
                        parent_id = change.get('parentReference', {}).get('id')
                        if parent_id and parent_id in self.requests_data_cache:
                            # Alguien agregó un archivo a una solicitud existente
                            # Forzamos recálculo de unread count
                            new_count = self.reader.get_unread_email_count(parent_id, force_refresh=True)
                            self.requests_state_cache[parent_id] = new_count
                            self.requests_data_cache[parent_id]['unread_emails'] = new_count
                            self.update_local_badge(parent_id, new_count)
                            if new_count > 0:
                                name = self.requests_data_cache[parent_id].get('request_name', 'Request')
                                self.notifier.send("New Email", f"Activity in: {name}")

                if changes_detected_in_ui:
                    self.update_tab_headers()
                    self.page.update()

            except Exception as e:
                print(f"Error en Smart Polling: {e}")
                time.sleep(5)

    def _remove_card_from_ui(self, req_id):
        if req_id in self.ui_refs:
            for ref in self.ui_refs[req_id]:
                card, grid_name = ref['card_control'], ref['parent_grid']
                if grid_name in self.grids and card in self.grids[grid_name].controls: 
                    grid = self.grids[grid_name]
                    if card in grid.controls:
                        grid.controls.remove(card)
                        grid.update()
                        self._remove_category_tab_if_empty(grid_name)
            del self.ui_refs[req_id]
        
        self.requests_data_cache.pop(req_id, None)
        self.requests_state_cache.pop(req_id, None)
        self.requests_meta_cache.pop(req_id, None)

    # ... Resto de métodos auxiliares (move_card, resolve_key, etc) se mantienen igual ...
    def move_card_visually(self, req_data, new_status, new_category):
        try:
            req_id = req_data['id']
            changes_made = False
            should_be_todo = self.is_status_todo(new_status)
            
            existing_todo_ref = next((r for r in self.ui_refs.get(req_id, []) if r['parent_grid'] == "To Do"), None)
            
            if should_be_todo and not existing_todo_ref and "To Do" in self.grids:
                self.grids["To Do"].controls.insert(0, self.create_request_card(req_data, show_category_label=True))
                self.grids["To Do"].update()
                changes_made = True
            elif not should_be_todo and existing_todo_ref:
                if existing_todo_ref['card_control'] in self.grids["To Do"].controls:
                    self.grids["To Do"].controls.remove(existing_todo_ref['card_control'])
                    self.grids["To Do"].update()
                    self.ui_refs[req_id].remove(existing_todo_ref)
                    changes_made = True
            
            target_grid_name = self.resolve_category_key(new_category)
            existing_cat_ref = next((r for r in self.ui_refs.get(req_id, []) if r['parent_grid'] != "To Do"), None)
            
            if existing_cat_ref and existing_cat_ref['parent_grid'] != target_grid_name:
                curr_grid = self.grids.get(existing_cat_ref['parent_grid'])
                if curr_grid and existing_cat_ref['card_control'] in curr_grid.controls:
                    curr_grid.controls.remove(existing_cat_ref['card_control'])
                    curr_grid.update()
                    self._remove_category_tab_if_empty(existing_cat_ref['parent_grid'])
                
                self._ensure_category_tab(target_grid_name)
                if target_grid_name in self.grids:
                    self.grids[target_grid_name].controls.insert(0, existing_cat_ref['card_control'])
                    self.grids[target_grid_name].update()
                    existing_cat_ref['parent_grid'] = target_grid_name
                    changes_made = True
                    
            elif not existing_cat_ref:
                self._ensure_category_tab(target_grid_name)
                if target_grid_name in self.grids:
                    self.grids[target_grid_name].controls.insert(0, self.create_request_card(req_data))
                    self.grids[target_grid_name].update()
                    changes_made = True
                    
            if changes_made: 
                self.update_tab_headers()
        except: 
            pass

    def open_remediation_dialog(self, req_data):
        dialog = RemediationDialog(self.page, req_data, self.remediation_service, self.location_service, self.on_remediation_success, self.available_dates)
        self.page.open(dialog)
        self.page.update()

    def on_remediation_success(self, req_id, new_loc_update=None):
        if new_loc_update and req_id in self.requests_data_cache: 
            self.requests_data_cache[req_id]['location_code'] = new_loc_update
        if req_id in self.ui_refs:
            current_refs = list(self.ui_refs[req_id])
            for ref in current_refs:
                card, grid_name = ref['card_control'], ref['parent_grid']
                if grid_name in self.grids:
                    grid = self.grids[grid_name]
                    if card in grid.controls:
                        if not new_loc_update: 
                            grid.controls.remove(card)
                            grid.update()
                            self._remove_category_tab_if_empty(grid_name)
                        else:
                            try:
                                idx = grid.controls.index(card)
                                new_card = self.create_request_card(self.requests_data_cache.get(req_id), show_category_label=(grid_name == "To Do"))
                                grid.controls[idx] = new_card
                                self.ui_refs[req_id].remove(ref)
                                grid.update()
                            except: pass
        if not new_loc_update:
            self._remove_card_from_ui(req_id)
            self.update_tab_headers()
        self.notifier.send("Fixed", "Request remediation applied successfully.", "success")
        self.page.update()

    def update_tab_headers(self):
        if "To Do" in self.grids and "To Do" in self.tab_refs: 
            self.tab_refs["To Do"].text = f"To Do ({len(self.grids['To Do'].controls)})"
        for cat_name, grid in self.grids.items():
            if cat_name != "To Do" and cat_name in self.tab_refs: 
                self.tab_refs[cat_name].text = f"({len(grid.controls)}) {cat_name}"
        self.tabs.update()

    @track_errors("Changing Property") # --- PROTEGIDO ---
    def handle_property_change(self, e, req_data):
        desired_status = self.status_dropdown.value
        desired_priority = self.priority_dropdown.value
        desired_category = self.category_dropdown.value
        
        if desired_status == "No Action Needed":
            self.pending_no_action_req = {'req': req_data, 'prio': desired_priority, 'cat': desired_category}
            self.page.open(self.no_action_dialog)
            self.page.update()
            return 

        new_reply_limit = ... 
        new_resolve_limit = ...
        new_reply_time = ...
        if desired_status == "In Progress" and not req_data.get('reply_time'):
            new_reply_time = datetime.now(timezone.utc).isoformat()
        
        if desired_category != req_data.get('category'):
            self.notifier.send("Calculating...", "Applying business rules...", "info")
            user_email = self.current_user.get('mail') if self.current_user else "Unknown"
            auto_prio, reply_iso, resolve_iso = self.rules_service.calculate_deadlines(
                req_data.get('created_at'), desired_category, user_email
            )
            if auto_prio:
                desired_priority = auto_prio 
                self.priority_dropdown.value = str(auto_prio)
                self.priority_dropdown.update()
                new_reply_limit = reply_iso
                new_resolve_limit = resolve_iso

        self.notifier.send("Checking...", "Verifying status with server...", "info")
        
        def worker_check():
            fresh_data = self.reader.get_latest_metadata(req_data['id'])
            check_data = fresh_data if fresh_data else req_data
            
            if fresh_data:
                self.requests_data_cache[req_data['id']].update(fresh_data)
            
            current_status = check_data.get('status')
            current_editor = check_data.get('editor', 'Unknown')
            my_name = self.current_user.get('displayName') if self.current_user else "Unknown"
            
            is_conflict = False
            conflict_msg = ""
            
            if current_status == "In Progress" and current_editor != my_name and desired_status != current_status:
                is_conflict = True
                conflict_msg = f"{current_editor} is already working on this.\nAre you sure you want to change it?"
            elif current_status == "Done" and current_editor != my_name and desired_status != current_status:
                is_conflict = True
                conflict_msg = f"{current_editor} already marked this as Done.\nAre you sure you want to reopen/change it?"

            if is_conflict:
                self.ownership_confirm_text.value = conflict_msg
                self.ownership_pending_change = {
                    'req_data': check_data,
                    'new_status': desired_status,
                    'new_priority': desired_priority,
                    'new_category': desired_category,
                    'new_reply_limit': new_reply_limit,     
                    'new_resolve_limit': new_resolve_limit,
                    'new_reply_time': new_reply_time
                }
                self.page.open(self.ownership_confirm_dialog)
                self.page.update()
                return

            self._execute_property_change(
                check_data, desired_status, desired_priority, desired_category,
                new_reply_limit, new_resolve_limit,
                new_reply_time=new_reply_time 
            )

        threading.Thread(target=worker_check, daemon=True).start()

    def confirm_reply_action(self, e):
        self.page.close(self.reply_confirm_dialog)
        if not self.pending_reply_req: return
        req = self.pending_reply_req
        now_iso = datetime.now(timezone.utc).isoformat()
        self._execute_property_change(req, new_s="In Progress", new_p=req.get('priority'), new_c=req.get('category'), new_reply_time=now_iso)
        self.pending_reply_req = None

    def confirm_no_action(self, replied):
        self.page.close(self.no_action_dialog)
        if not self.pending_no_action_req: return
        d = self.pending_no_action_req
        req = d['req']
        now_iso = datetime.now(timezone.utc).isoformat()
        
        if replied:
            val_reply = ... 
            if not req.get('reply_time'): val_reply = now_iso
            self._execute_property_change(req, new_s="No Action Needed", new_p=d['prio'], new_c=d['cat'], new_reply_time=val_reply, new_resolve_time=None, new_resolve_limit=None)
        else:
            self._execute_property_change(req, new_s="No Action Needed", new_p=d['prio'], new_c=d['cat'], new_reply_limit=None, new_resolve_limit=None, new_reply_time=None, new_resolve_time=None)
        self.pending_no_action_req = None

    # Métodos restantes sin cambios significativos se incluyen para mantener integridad
    def handle_file_click(self, e, file_data, req_data, title_control, icon_control):
        filename, download_url = file_data['name'], file_data.get('download_url')
        if filename.lower().endswith(('.eml', '.msg')):
            if file_data.get('status') == 'To Be Reviewed':
                if title_control: 
                    title_control.weight, title_control.color = ft.FontWeight.NORMAL, SSA_GREY
                curr = self.requests_state_cache.get(req_data['id'], 0)
                if curr > 0:
                    new_c = curr - 1
                    self.requests_state_cache[req_data['id']] = new_c
                    if req_data['id'] in self.requests_data_cache: 
                        self.requests_data_cache[req_data['id']]['unread_emails'] = new_c
                    self.update_local_badge(req_data['id'], new_c)
                file_data['status'] = 'Seen'
                threading.Thread(target=lambda: self.reader.update_request_metadata(file_data['id'], new_status="Seen"), daemon=True).start()
            
            trigger_question = False
            if req_data.get('status') == 'Pending':
                all_files = self.reader.get_request_files(req_data['id'])
                if all_files and all_files[0]['id'] == file_data['id']:
                    trigger_question = True
                    self.pending_reply_req = req_data

            self.page.open(self.mail_loading_dialog)
            self.page.update()

            def download_task():
                local_path = self.reader.download_file_locally(download_url, filename)
                self.page.close(self.mail_loading_dialog)
                self.page.update()
                if local_path: 
                    try: os.startfile(local_path)
                    except: pass
                if trigger_question:
                    time.sleep(0.5)
                    self.page.open(self.reply_confirm_dialog)
                    self.page.update()
            threading.Thread(target=download_task, daemon=True).start()
        else: 
            webbrowser.open(file_data['web_url'])

    def show_request_details(self, req_id):
        req_data = self.requests_data_cache.get(req_id)
        if not req_data: return
        self.detail_title.value = req_data.get('request_name', 'Details')
        self.detail_subtitle.value = f"Location: {req_data.get('location_code')}"
        self.status_dropdown.value = req_data.get('status')
        self.priority_dropdown.value = str(req_data.get('priority'))
        self.category_dropdown.value = req_data.get('category')
        self.status_dropdown.on_change = lambda e: self.handle_property_change(e, req_data)
        self.priority_dropdown.on_change = lambda e: self.handle_property_change(e, req_data)
        self.category_dropdown.on_change = lambda e: self.handle_property_change(e, req_data)
        self.detail_files_list.controls = [ft.ProgressRing(color=SSA_GREEN)]
        self.page.open(self.detail_dialog)
        def fetch_files():
            try:
                time.sleep(0.5)
                files = self.reader.get_request_files(req_data['id'])
                file_controls = []
                if not files: 
                    file_controls.append(ft.Text("No files found.", italic=True, color=ft.Colors.GREY))
                else:
                    for f in files:
                        name = f['name']
                        is_eml = name.lower().endswith(('.eml', '.msg'))
                        is_unread = f.get('status') == 'To Be Reviewed' and is_eml
                        if is_eml: icon, icon_color = ft.Icons.EMAIL, (SSA_RED_BADGE if is_unread else ft.Colors.BLUE)
                        elif name.lower().endswith('.pdf'): icon, icon_color = ft.Icons.PICTURE_AS_PDF, ft.Colors.RED
                        elif name.lower().endswith(('.xls', '.xlsx')): icon, icon_color = ft.Icons.TABLE_CHART, SSA_GREEN
                        else: icon, icon_color = ft.Icons.INSERT_DRIVE_FILE, ft.Colors.GREY
                        title_ctrl = ft.Text(name, weight=ft.FontWeight.BOLD if is_unread else ft.FontWeight.NORMAL, size=14, color=ft.Colors.BLACK if is_unread else SSA_GREY, overflow=ft.TextOverflow.ELLIPSIS)
                        row_content = [ft.Icon(icon, color=icon_color), ft.Column([title_ctrl, ft.Text(f.get('created_at', '')[:16], size=11, color=ft.Colors.GREY)], spacing=2, expand=True), ft.Container(width=10, height=10, border_radius=5, bgcolor=SSA_RED_BADGE if is_unread else ft.Colors.TRANSPARENT)]
                        if is_eml:
                            legacy_btn = ft.IconButton(icon=ft.Icons.MEDICAL_SERVICES, icon_color=ft.Colors.LIGHT_GREEN, icon_size=16, tooltip="Fix issues of New Outlook (Emergency)", on_click=lambda e, fd=f: self.launch_email_emergency(fd, req_data, title_ctrl))
                            row_content.append(ft.Container(width=5))
                            row_content.append(legacy_btn)
                        item_row = ft.Container(content=ft.Row(row_content), padding=10, border=ft.border.only(bottom=ft.BorderSide(1, "#eeeeee")), ink=True, on_click=lambda e, fd=f, tc=title_ctrl, ic=None: self.handle_file_click(e, fd, req_data, tc, ic))
                        file_controls.append(item_row)
                self.detail_files_list.controls = file_controls
                self.page.update()
            except: pass
        threading.Thread(target=fetch_files, daemon=True).start()

    def launch_email_emergency(self, file_data, req_data, title_control=None):
        filename, download_url = file_data['name'], file_data.get('download_url')
        if file_data.get('status') == 'To Be Reviewed':
            if title_control: title_control.weight, title_control.color = ft.FontWeight.NORMAL, SSA_GREY
            title_control.update()
            curr = self.requests_state_cache.get(req_data['id'], 0)
            if curr > 0:
                new_c = curr - 1
                self.requests_state_cache[req_data['id']] = new_c
                if req_data['id'] in self.requests_data_cache: self.requests_data_cache[req_data['id']]['unread_emails'] = new_c
                self.update_local_badge(req_data['id'], new_c)
            file_data['status'] = 'Seen'
            threading.Thread(target=lambda: self.reader.update_request_metadata(file_data['id'], new_status="Seen"), daemon=True).start()
        
        trigger_question = False
        if req_data.get('status') == 'Pending':
            all_files = self.reader.get_request_files(req_data['id'])
            if all_files and all_files[0]['id'] == file_data['id']:
                trigger_question = True
                self.pending_reply_req = req_data

        self.page.open(self.legacy_loading_dialog)
        self.page.update()
        def task():
            local_path = self.reader.download_file_locally(download_url, filename)
            success, msg = False, "Download failed"
            if local_path: success, msg = self.legacy_service.launch_classic(local_path)
            self.page.close(self.legacy_loading_dialog)
            self.page.update()
            if success:
                self.notifier.send("Emergency Mode", "Classic Outlook launched.", "success")
                if trigger_question:
                    time.sleep(1.0) 
                    self.page.open(self.reply_confirm_dialog)
                    self.page.update()
            else: self.notifier.send("Launch Failed", msg, "error")
        threading.Thread(target=task, daemon=True).start()

    def open_sharepoint_link(self, e):
        if e.control.data: webbrowser.open(e.control.data)

    def update_local_badge(self, req_id, new_count):
        if req_id in self.ui_refs:
            for refs in self.ui_refs[req_id]:
                try:
                    refs['badge_text'].value = str(new_count)
                    refs['badge_container'].visible = (new_count > 0)
                    if refs['badge_container'].page: refs['badge_container'].update()
                except: pass