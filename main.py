import flet as ft
import webbrowser
import threading
import time
import os
from datetime import datetime, timezone
from sharepoint_requests_reader import SharePointRequestsReader
from deadline_calculator import DeadlineCalculator
from notification_manager import NotificationManager
from services.request_data_service import RequestDataService

# --- SSA MARINE STYLE GUIDE ---
SSA_GREEN = "#84BD00"
SSA_GREY = "#59595B"
SSA_BG = "#f0f2f5"
SSA_WHITE = "#ffffff"
SSA_BORDER = "#e0e0e0"
SSA_RED_BADGE = "#FF3B30" 
SSA_LIGHT_GREEN = "#f4f9e5"
SSA_BLUE_NOTIF = "#007AFF"

# --- HELPER FUNCTIONS FOR COLORS ---
def get_status_color(status):
    if not status: return ft.Colors.GREY
    status = str(status).lower()
    if "done" in status or "completed" in status: return SSA_GREEN
    elif "progress" in status: return ft.Colors.BLUE
    elif "pending" in status or "hold" in status: return ft.Colors.ORANGE
    elif "new" in status or "open" in status: return ft.Colors.RED
    return ft.Colors.BLUE_GREY

def get_priority_color(priority):
    if not priority: return ft.Colors.GREY
    p = str(priority)
    if "1" in p: return ft.Colors.RED
    if "2" in p: return ft.Colors.ORANGE
    if "3" in p: return ft.Colors.AMBER
    if "4" in p: return SSA_GREEN 
    return ft.Colors.GREY

# --- LIVE COMPONENT: SELF-UPDATING BADGE ---
class LiveStatBadge(ft.Container): 
    def __init__(self, calculator, limit_date, icon, default_text, default_color):
        super().__init__()
        self.calculator = calculator
        self.limit_date = limit_date
        
        final_icon_color = default_color
        if default_color == "green": final_icon_color = SSA_GREEN
        
        self.text_control = ft.Text(default_text, size=13, color=final_icon_color, weight=ft.FontWeight.BOLD, font_family="monospace")
        self.icon_control = ft.Icon(icon, size=14, color=final_icon_color)
        
        self.content = ft.Row(
            [self.icon_control, self.text_control],
            spacing=5,
            alignment=ft.MainAxisAlignment.START
        )
        self.padding = ft.padding.symmetric(horizontal=8, vertical=4)
        self.border_radius = 6
        self.bgcolor = ft.Colors.GREY_100
        self.border = ft.border.all(1, ft.Colors.TRANSPARENT)
        
        self.running = False

    def did_mount(self):
        if self.limit_date:
            self.running = True
            self.th = threading.Thread(target=self.update_timer, daemon=True)
            self.th.start()

    def will_unmount(self):
        self.running = False

    def update_timer(self):
        while self.running:
            try:
                if not self.page:
                    self.running = False
                    break
                now = datetime.now(timezone.utc)
                new_stat = self.calculator.calculate_time_left(self.limit_date, now)
                
                final_color = new_stat['color']
                if final_color == "green": final_color = SSA_GREEN
                
                self.text_control.value = new_stat['text']
                self.text_control.color = final_color
                self.icon_control.color = final_color
                
                if new_stat['color'] == "red":
                    self.bgcolor = ft.Colors.RED_50
                    self.border = ft.border.all(1, ft.Colors.RED_200)
                else:
                    self.bgcolor = ft.Colors.GREY_100
                    self.border = ft.border.all(1, ft.Colors.TRANSPARENT)
                self.update()
                time.sleep(1)
            except Exception:
                self.running = False

# --- MAIN APP ---

def main(page: ft.Page):
    page.title = "Payroll Monitor Center"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = SSA_BG
    page.padding = 0 
    page.window_width = 1200
    page.window_height = 850
    page.window_icon = "assets/Icono.png"
    
    # --- INYECCIÓN DE DEPENDENCIAS ---
    reader = SharePointRequestsReader()
    calculator = DeadlineCalculator()
    notifier = NotificationManager(page)
    data_service = RequestDataService(reader, calculator)
    category_options = data_service.get_categories()
    
    # --- STATE REFERENCES ---
    ui_refs = {} 
    grids = {}
    requests_state_cache = {}
    requests_meta_cache = {}
    requests_refresh_tracker = {}

    # --- UI COMPONENTS ---

    mail_loading_dialog = ft.AlertDialog(
        modal=True, 
        title=ft.Text("Opening Mail...", size=18, weight=ft.FontWeight.BOLD, color=SSA_GREY),
        content=ft.Container(
            content=ft.Column([
                ft.ProgressRing(color=SSA_GREEN), 
                ft.Text("Downloading content...\nLaunching Outlook...", size=14, color=SSA_GREY)
            ], spacing=20, alignment=ft.MainAxisAlignment.CENTER, height=100),
            padding=20,
            height=150
        ),
        actions=[],
    )

    detail_title = ft.Text("", size=20, weight=ft.FontWeight.BOLD, color=SSA_GREY)
    detail_subtitle = ft.Text("", size=12, color=ft.Colors.GREY)
    detail_files_list = ft.ListView(expand=True, spacing=5, padding=10, height=300)
    
    status_dropdown = ft.Dropdown(
        label="Status", width=200, text_size=13, content_padding=10,
        options=[ft.dropdown.Option("Pending"), ft.dropdown.Option("In Progress"), ft.dropdown.Option("Done"), ft.dropdown.Option("Hold")]
    )
    priority_dropdown = ft.Dropdown(
        label="Priority", width=150, text_size=13, content_padding=10,
        options=[ft.dropdown.Option("1"), ft.dropdown.Option("2"), ft.dropdown.Option("3"), ft.dropdown.Option("4")]
    )
    category_dropdown = ft.Dropdown(
        label="Category", width=220, text_size=13, content_padding=10,
        options=[ft.dropdown.Option(cat) for cat in category_options]
    )

    def ensure_category_option(value):
        if not value:
            return
        for opt in category_dropdown.options:
            opt_value = getattr(opt, "key", None) or getattr(opt, "text", None)
            if opt_value == value:
                return
        category_dropdown.options.append(ft.dropdown.Option(value))

    def close_detail_dialog(e):
        page.close(detail_dialog)

    detail_dialog = ft.AlertDialog(
        title=ft.Column([
            detail_title, detail_subtitle, ft.Divider(),
            ft.Text("Edit Properties:", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY),
            ft.Row(
                [status_dropdown, priority_dropdown, category_dropdown],
                alignment=ft.MainAxisAlignment.START,
                spacing=10,
                run_spacing=10,
                wrap=True
            )
        ], spacing=5),
        content=ft.Container(content=detail_files_list, width=600, bgcolor=ft.Colors.WHITE, border_radius=8),
        actions=[ft.TextButton("Close", on_click=close_detail_dialog, style=ft.ButtonStyle(color=SSA_GREEN))],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    # --- LOGIC ---
    _UNSET = object()

    def update_local_ui_card(req_id, new_status=_UNSET, new_priority=_UNSET, new_category=_UNSET):
        if req_id in ui_refs:
            for refs in ui_refs[req_id]:
                try:
                    if new_status is not _UNSET:
                        status_value = new_status or "Unknown"
                        refs['status_text'].value = status_value
                        refs['status_container'].bgcolor = get_status_color(status_value)
                        refs['status_container'].update()
                    if new_priority is not _UNSET:
                        priority_value = str(new_priority) if new_priority else ""
                        refs['priority_text'].value = priority_value
                        refs['priority_text'].color = get_priority_color(priority_value)
                        refs['priority_text'].update()
                    if refs.get('category_text') and new_category is not _UNSET:
                        category_value = str(new_category) if new_category else "General"
                        refs['category_text'].value = category_value.upper()
                        refs['category_text'].update()
                except Exception:
                    pass

    def update_local_badge(req_id, new_count):
        if req_id in ui_refs:
            for refs in ui_refs[req_id]:
                try:
                    badge_container = refs['badge_container']
                    badge_text = refs['badge_text']
                    
                    if new_count > 0:
                        badge_text.value = str(new_count)
                        badge_container.visible = True
                    else:
                        badge_container.visible = False
                    
                    badge_container.update()
                except Exception:
                    pass

    def handle_property_change(e, req_data):
        """
        Maneja el cambio de propiedades con lógica Optimistic UI + Rollback.
        """
        # 1. Guardar valores anteriores por si falla
        old_status = req_data.get('status')
        raw_old_priority = req_data.get('priority')
        old_priority = str(raw_old_priority) if raw_old_priority is not None else None
        old_category = req_data.get('category')
        
        # 2. Obtener nuevos valores
        new_status = status_dropdown.value
        new_priority = priority_dropdown.value
        new_category = category_dropdown.value

        if (
            new_status == old_status
            and new_priority == old_priority
            and new_category == old_category
        ):
            return
        
        # 3. Actualización Optimista (UI Inmediata)
        req_data['status'] = new_status
        req_data['priority'] = new_priority
        req_data['category'] = new_category
        update_local_ui_card(req_data['id'], new_status, new_priority, new_category)
        
        notifier.send("Saving...", "Syncing with SharePoint...", "info")

        # 4. Sincronización en segundo plano con Rollback
        def sync_task():
            success = data_service.update_request_properties(
                req_data['id'],
                status=new_status,
                priority=new_priority,
                category=new_category,
            )
            
            if success:
                notifier.send("Saved", "Changes updated in SharePoint", "success")
            else:
                print(f"❌ Error actualizando {req_data['id']}. Revirtiendo...")
                req_data['status'] = old_status
                req_data['priority'] = old_priority
                req_data['category'] = old_category
                
                update_local_ui_card(req_data['id'], old_status, old_priority, old_category)
                
                if detail_dialog.open:
                    status_dropdown.value = old_status
                    priority_dropdown.value = old_priority
                    category_dropdown.value = old_category
                    page.update()
                
                notifier.send("Error", "Failed to update SharePoint. Changes reverted.", "error")

        threading.Thread(target=sync_task, daemon=True).start()

    def handle_file_click(e, file_data, req_data, title_control=None, icon_control=None):
        filename = file_data['name']
        download_url = file_data.get('download_url')
        is_email = filename.lower().endswith('.eml') or filename.lower().endswith('.msg')
        
        if is_email and download_url:
            page.open(mail_loading_dialog)
            page.update()
            
            if file_data.get('status') == 'To Be Reviewed':
                if title_control: 
                    title_control.weight = ft.FontWeight.NORMAL
                    title_control.color = SSA_GREY
                if icon_control: 
                    icon_control.color = ft.Colors.BLUE 
                
                current_count = requests_state_cache.get(req_data['id'], 0)
                if current_count > 0:
                    new_count = current_count - 1
                    requests_state_cache[req_data['id']] = new_count
                    update_local_badge(req_data['id'], new_count)
                
                file_data['status'] = 'Seen' 
                
                # Actualizar status de archivo en segundo plano
                threading.Thread(target=lambda: reader.update_request_metadata(file_data['id'], new_status="Seen"), daemon=True).start()

            def download_and_open():
                local_path = reader.download_file_locally(download_url, filename)
                page.close(mail_loading_dialog)
                if local_path:
                    try:
                        os.startfile(local_path)
                    except AttributeError:
                        pass 
                page.update()
            
            threading.Thread(target=download_and_open, daemon=True).start()
        else:
            webbrowser.open(file_data['web_url'])

    def open_sharepoint_link(e):
        url = e.control.data
        if url: webbrowser.open(url)

    def show_request_details(req_data):
        detail_title.value = req_data.get('request_name', 'Details')
        detail_subtitle.value = f"Location: {req_data.get('location_code')}"
        status_dropdown.value = req_data.get('status')
        priority_value = req_data.get('priority')
        priority_dropdown.value = str(priority_value) if priority_value is not None else None
        current_category = req_data.get('category')
        ensure_category_option(current_category)
        category_dropdown.value = current_category
        
        # Asignar handlers
        status_dropdown.on_change = lambda e: handle_property_change(e, req_data)
        priority_dropdown.on_change = lambda e: handle_property_change(e, req_data)
        category_dropdown.on_change = lambda e: handle_property_change(e, req_data)

        detail_files_list.controls = [ft.ProgressRing(color=SSA_GREEN)]
        page.open(detail_dialog)
        
        def fetch_files_background():
            try:
                time.sleep(0.5) 
                files = reader.get_request_files(req_data['id'])
                
                file_controls = []
                if not files:
                    file_controls.append(ft.Text("No files found.", italic=True, color=ft.Colors.GREY))
                else:
                    for f in files:
                        name = f['name']
                        is_eml = name.lower().endswith('.eml') or name.lower().endswith('.msg')
                        is_unread = f.get('status') == 'To Be Reviewed' and is_eml
                        
                        icon = ft.Icons.INSERT_DRIVE_FILE
                        icon_color = ft.Colors.GREY
                        if is_eml: 
                            icon = ft.Icons.EMAIL
                            icon_color = SSA_RED_BADGE if is_unread else ft.Colors.BLUE
                        elif name.lower().endswith('.pdf'): icon, icon_color = ft.Icons.PICTURE_AS_PDF, ft.Colors.RED
                        elif name.lower().endswith('.xls') or name.lower().endswith('.xlsx'): icon, icon_color = ft.Icons.TABLE_CHART, SSA_GREEN

                        text_weight = ft.FontWeight.BOLD if is_unread else ft.FontWeight.NORMAL
                        text_color = ft.Colors.BLACK if is_unread else SSA_GREY
                        
                        date_str = ""
                        if f.get('created_at'):
                            try: date_str = datetime.fromisoformat(f['created_at'].replace('Z', '+00:00')).strftime("%Y-%m-%d %H:%M")
                            except: pass

                        title_ctrl = ft.Text(name, weight=text_weight, size=14, color=text_color, overflow=ft.TextOverflow.ELLIPSIS)
                        icon_ctrl = ft.Icon(icon, color=icon_color)

                        item_row = ft.Container(
                            content=ft.Row([
                                icon_ctrl,
                                ft.Column([
                                    title_ctrl,
                                    ft.Text(date_str, size=11, color=ft.Colors.GREY)
                                ], spacing=2, expand=True),
                                ft.Container(
                                    width=10, height=10, border_radius=5, 
                                    bgcolor=SSA_RED_BADGE if is_unread else ft.Colors.TRANSPARENT
                                ),
                                ft.Icon(ft.Icons.OPEN_IN_NEW if not is_eml else ft.Icons.EMAIL, size=16, color=ft.Colors.GREY_400)
                            ]),
                            padding=10,
                            border=ft.border.only(bottom=ft.BorderSide(1, "#eeeeee")),
                            ink=True,
                            on_click=lambda e, fd=f, tc=title_ctrl, ic=icon_ctrl: handle_file_click(e, fd, req_data, tc, ic)
                        )
                        file_controls.append(item_row)
                
                detail_files_list.controls = file_controls
                page.update()
            except Exception as e: 
                print(f"Error: {e}")

        threading.Thread(target=fetch_files_background, daemon=True).start()

    def create_request_card(req, show_category_label=False):
        reply_stat = req.get('reply_status', {})
        resolve_stat = req.get('resolve_status', {})
        status_val = req.get('status') or 'Unknown'
        raw_priority = req.get('priority')
        priority_val = str(raw_priority) if raw_priority is not None else ""
        
        unread_count = req.get('unread_emails', 0)
        
        badge_text_ctrl = ft.Text(str(unread_count), size=11, color="white", weight=ft.FontWeight.BOLD)
        badge_container_ctrl = ft.Container(
            content=badge_text_ctrl,
            bgcolor=SSA_RED_BADGE,
            border_radius=10,
            padding=ft.padding.symmetric(horizontal=6, vertical=2),
            alignment=ft.alignment.center,
            visible=(unread_count > 0),
            shadow=ft.BoxShadow(blur_radius=2, color=ft.Colors.with_opacity(0.3, ft.Colors.BLACK), offset=ft.Offset(1, 1))
        )

        status_text_ctrl = ft.Text(status_val, size=11, color=SSA_WHITE, weight=ft.FontWeight.BOLD)
        status_container_ctrl = ft.Container(
            content=status_text_ctrl,
            bgcolor=get_status_color(status_val), 
            padding=ft.padding.symmetric(horizontal=8, vertical=4), 
            border_radius=6
        )
        priority_text_ctrl = ft.Text(priority_val, size=12, weight=ft.FontWeight.BOLD, color=get_priority_color(priority_val))

        if req['id'] not in ui_refs:
            ui_refs[req['id']] = []
        
        refs_entry = {
            'status_container': status_container_ctrl, 
            'status_text': status_text_ctrl, 
            'priority_text': priority_text_ctrl,
            'badge_container': badge_container_ctrl,
            'badge_text': badge_text_ctrl
        }
        ui_refs[req['id']].append(refs_entry)

        card_border_color = SSA_BORDER
        if reply_stat.get('color') == 'red' or resolve_stat.get('color') == 'red':
            card_border_color = ft.Colors.RED_400
        
        category_label = ft.Container()
        if show_category_label:
            category_value = req.get('category', 'General') or 'General'
            category_text_ctrl = ft.Text(category_value.upper(), size=9, weight=ft.FontWeight.BOLD, color=SSA_GREEN)
            category_label = ft.Container(
                content=category_text_ctrl,
                padding=ft.padding.only(bottom=5)
            )
            refs_entry['category_text'] = category_text_ctrl

        card_content = ft.Container(
            padding=20,
            bgcolor=SSA_WHITE,
            border_radius=12,
            shadow=ft.BoxShadow(spread_radius=0, blur_radius=10, color=ft.Colors.with_opacity(0.07, ft.Colors.BLACK), offset=ft.Offset(0, 4)),
            border=ft.Border(top=ft.BorderSide(1, card_border_color), bottom=ft.BorderSide(1, card_border_color), left=ft.BorderSide(1, card_border_color), right=ft.BorderSide(1, card_border_color)),
            on_click=lambda _: show_request_details(req),
            ink=True,
            margin=ft.margin.only(top=8, right=8), 
            content=ft.Column([
                category_label,
                
                ft.Row([
                    ft.Text(
                        req.get('request_name', 'Unnamed'), 
                        size=16, 
                        weight=ft.FontWeight.W_600, 
                        color=SSA_GREY, 
                        expand=True,
                        max_lines=2, 
                        overflow=ft.TextOverflow.ELLIPSIS,
                        tooltip=req.get('request_name')
                    ),
                    ft.IconButton(icon=ft.Icons.OPEN_IN_NEW, icon_color=SSA_GREEN, tooltip="Open Folder", data=req.get('web_url'), on_click=open_sharepoint_link)
                ], alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.START), 
                
                ft.Text(f"Loc: {req.get('location_code')} | Created: {req.get('created_at')[:10]}", size=12, color=ft.Colors.GREY_500),
                ft.Divider(height=15, thickness=1, color=SSA_BORDER),
                ft.Row([
                    ft.Column([
                        ft.Text("Reply by:", size=11, color=ft.Colors.GREY_600),
                        LiveStatBadge(calculator, reply_stat.get('limit_date'), ft.Icons.TIMER, reply_stat.get('text'), reply_stat.get('color'))
                    ], expand=True),
                    ft.Column([
                        ft.Text("Resolve by:", size=11, color=ft.Colors.GREY_600),
                        LiveStatBadge(calculator, resolve_stat.get('limit_date'), ft.Icons.CHECK_CIRCLE_OUTLINE, resolve_stat.get('text'), resolve_stat.get('color'))
                    ], expand=True)
                ]),
                ft.Divider(height=15, color="transparent"),
                ft.Row([
                    status_container_ctrl,
                    ft.Row([
                        ft.Text("Priority:", size=11, color=ft.Colors.GREY_600),
                        priority_text_ctrl
                    ], spacing=5)
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
            ])
        )

        return ft.Stack([
            card_content,
            ft.Container(
                content=badge_container_ctrl,
                right=0,
                top=0,
            )
        ])

    def background_poller():
        """
        Monitorea cambios en SharePoint y notifica al usuario.
        """
        REFRESH_INTERVAL = 300  # seconds
        while True:
            time.sleep(60) 
            try:
                # 1. Obtener estado actual (metadatos ligeros, sin adjuntos)
                new_requests = reader.fetch_active_requests(limit_dates=1, include_unread=False)
                new_processed = calculator.process_requests(new_requests)
                
                for req in new_processed:
                    req_id = req['id']
                    req_name = req.get('request_name', 'Unknown')
                    last_modified = req.get('modified_at')
                    old_unread = requests_state_cache.get(req_id, 0)
                    need_refresh = req_id not in requests_state_cache
                    if not need_refresh:
                        cached_modified = requests_meta_cache.get(req_id)
                        need_refresh = last_modified and cached_modified != last_modified
                        if not need_refresh:
                            last_refresh = requests_refresh_tracker.get(req_id, 0)
                            need_refresh = (time.time() - last_refresh) > REFRESH_INTERVAL

                    if need_refresh:
                        new_unread = reader.get_unread_email_count(req_id, force_refresh=True)
                        requests_refresh_tracker[req_id] = time.time()
                    else:
                        new_unread = old_unread

                    requests_state_cache[req_id] = new_unread
                    requests_meta_cache[req_id] = last_modified

                    req['unread_emails'] = new_unread
                    
                    if req_id in ui_refs:
                        # --- CASO 1: ACTUALIZACIÓN ---
                        if new_unread > old_unread:
                            notifier.send(
                                title="New Reply Received",
                                message=f"Review request: {req_name}",
                                type="info"
                            )
                        
                        update_local_badge(req_id, new_unread)
                        update_local_ui_card(req_id, req.get('status'), req.get('priority'), req.get('category'))
                    
                    else:
                        # --- CASO 2: NUEVA SOLICITUD ---
                        if len(requests_state_cache) > 0:
                            notifier.send(
                                title="New Payroll Request",
                                message=f"Location: {req.get('location_code')} - {req_name}",
                                type="success"
                            )

                        requests_refresh_tracker[req_id] = time.time()
                        
                        cat = req.get('category', 'Others')
                        target_category = "Others"
                        for key in ["Request", "Staff Movement", "Inquiry", "Information"]:
                            if key.lower() in str(cat).lower():
                                target_category = key
                                break
                        is_todo = "pending" in str(req.get('status', '')).lower() or "progress" in str(req.get('status', '')).lower()

                        if target_category in grids:
                            new_card = create_request_card(req)
                            grids[target_category].controls.insert(0, new_card)
                            grids[target_category].update()
                        
                        if is_todo and "To Do" in grids:
                            new_todo_card = create_request_card(req, show_category_label=True)
                            grids["To Do"].controls.insert(0, new_todo_card)
                            grids["To Do"].update()

            except Exception as e:
                print(f"Error en polling: {e}")

    # --- INICIO ---
    
    poll_thread = threading.Thread(target=background_poller, daemon=True)
    poll_thread.start()

    def render_dataset(dataset):
        """Rebuilds tabs and local caches from a RequestDataset."""
        ui_refs.clear()
        grids.clear()
        tabs.tabs.clear()

        requests_state_cache.clear()
        requests_state_cache.update(dataset.state_cache)

        requests_meta_cache.clear()
        requests_meta_cache.update(dataset.meta_cache)

        requests_refresh_tracker.clear()
        now_ts = time.time()
        for req_id in dataset.state_cache.keys():
            requests_refresh_tracker[req_id] = now_ts

        grid_config = {
            "expand": 1,
            "runs_count": 4,
            "max_extent": 320,
            "child_aspect_ratio": 0.95,
            "spacing": 20,
            "run_spacing": 20,
        }

        grid_todo = ft.GridView(**grid_config)
        for item in dataset.todo_requests:
            grid_todo.controls.append(create_request_card(item, show_category_label=True))
        grids["To Do"] = grid_todo

        tabs.tabs.append(
            ft.Tab(
                text=f"To Do ({len(dataset.todo_requests)})",
                icon=ft.Icons.CHECKLIST_RTL,
                content=ft.Container(content=grid_todo, padding=20),
            )
        )

        for cat_name, items in dataset.grouped_requests.items():
            if not items:
                continue
            grid = ft.GridView(**grid_config)
            for item in items:
                grid.controls.append(create_request_card(item))
            grids[cat_name] = grid

            tabs.tabs.append(
                ft.Tab(
                    text=f"{cat_name} ({len(items)})",
                    content=ft.Container(content=grid, padding=20),
                )
            )

        page.update()

    def load_data(limit_dates: int = 1):
        loading_container.visible = True
        status_text.value = "Initializing..."
        tabs.visible = False
        page.update()

        stop_loading_event = threading.Event()

        def cycle_messages():
            time.sleep(0.5)
            status_text.value = "Scanning emails for this payroll period..."
            page.update()
            time.sleep(10)

            messages = [
                "I'm still standing...",
                "Let Carol work...",
                "Just a moment, organizing the chaos...",
                "Reviewing the Matrix...",
                "Leave me alone...",
                "Almost there...",
                "Asking the server nicely...",
                "Deciphering payroll hieroglyphs...",
                "Beep boop... calculating deadlines...",
                "This is taking longer than my coffee break...",
            ]

            idx = 0
            while not stop_loading_event.is_set():
                status_text.value = messages[idx % len(messages)]
                page.update()
                idx += 1
                time.sleep(10)

        def worker():
            try:
                status_text.value = "Connecting to Microsoft... \nPlease check your browser window."
                page.update()

                _ = reader._get_drive_id()

                threading.Thread(target=cycle_messages, daemon=True).start()

                dataset = data_service.load(limit_dates=limit_dates, include_unread=True)

                stop_loading_event.set()
                status_text.value = "Rendering..."
                page.update()

                render_dataset(dataset)
            except Exception as e:
                stop_loading_event.set()
                notifier.send("Error", f"Could not load data: {e}", "error")
                print(e)
            finally:
                loading_container.visible = False
                tabs.visible = True
                page.update()

        threading.Thread(target=worker, daemon=True).start()

    
    header = ft.Container(
        bgcolor=SSA_WHITE, padding=ft.padding.symmetric(horizontal=30, vertical=15),
        border=ft.border.only(bottom=ft.BorderSide(1, "#e9ecef")),
        shadow=ft.BoxShadow(spread_radius=0, blur_radius=5, color=ft.Colors.with_opacity(0.05, ft.Colors.BLACK), offset=ft.Offset(0, 2)),
        content=ft.Row([ft.Image(src="assets/logo.png", height=100, fit=ft.ImageFit.CONTAIN), ft.Container(expand=True)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
    )

    loading_spinner = ft.ProgressRing(color=SSA_GREEN)
    status_text = ft.Text("", color=SSA_GREY, text_align=ft.TextAlign.CENTER)
    
    loading_container = ft.Container(
        content=ft.Column([
            loading_spinner,
            ft.Container(height=10), 
            status_text
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER), 
        alignment=ft.Alignment(0, 0), 
        expand=True, 
        visible=False
    )

    tabs = ft.Tabs(
        selected_index=0,
        animation_duration=300,
        expand=True,
        indicator_color=SSA_GREEN,
        label_color=SSA_GREEN,
        unselected_label_color=ft.Colors.GREY_500,
        divider_color=SSA_BORDER
    )

    page.add(
        header,
        ft.Container(
            content=ft.Stack([
                loading_container,
                tabs
            ]),
            expand=True,
            padding=0
        )
    )
    
    load_data()

ft.app(target=main, assets_dir="assets")