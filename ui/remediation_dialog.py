import flet as ft
import threading
from ui.styles import SSA_RED_BADGE, SSA_GREY, SSA_GREEN

class RemediationDialog(ft.AlertDialog):
    """
    Diálogo de interfaz para la gestión de errores de ubicación y cambio de ciclo.
    """
    def __init__(self, page, request_data, remediation_service, location_service, on_success_callback, available_dates):
        super().__init__()
        self.page_ref = page
        self.req = request_data
        self.service = remediation_service
        self.loc_service = location_service
        self.on_success = on_success_callback
        self.available_dates = available_dates # Lista de ciclos disponibles
        
        self.modal = True
        self.title = ft.Text("⚠️ Remediation Required", color=SSA_RED_BADGE, weight=ft.FontWeight.BOLD)
        
        # --- CONTROLES PARA RELOCATE ---
        # CAMBIO: Usamos key=item['code'] para lógica y text=item['display'] para el usuario
        self.loc_dropdown = ft.Dropdown(
            label="Select Correct Location",
            options=[
                ft.dropdown.Option(key=item['code'], text=item['display']) 
                for item in self.loc_service.get_all_locations()
            ],
            width=300, text_size=13, visible=False
        )

        # --- CONTROLES PARA MERGE ---
        # CAMBIO: Igualmente aquí para la fusión
        self.merge_loc_dropdown = ft.Dropdown(
            label="Target Location",
            options=[
                ft.dropdown.Option(key=item['code'], text=item['display']) 
                for item in self.loc_service.get_all_locations()
            ],
            width=300, text_size=13, visible=False,
            on_change=self.on_merge_loc_change
        )
        self.merge_folder_dropdown = ft.Dropdown(
            label="Select Target Request",
            options=[], 
            width=300, text_size=13, visible=False,
            disabled=True,
            hint_text="Select location first..."
        )
        self.loading_folders = ft.ProgressRing(width=20, height=20, visible=False)

        # --- CONTROLES PARA CAMBIO DE CICLO ---
        self.cycle_dropdown = ft.Dropdown(
            label="Select Target Cycle",
            options=[ft.dropdown.Option(d) for d in self.available_dates],
            width=300, text_size=13, visible=False
        )

        self.info_text = ft.Column([
            ft.Text(f"Request: {self.req.get('request_name')}", size=13, weight=ft.FontWeight.BOLD),
            ft.Text(f"Invalid Loc: {self.req.get('location_code')}", size=12, color="red"),
            ft.Text(f"Date Folder: {self.req.get('date_folder')}", size=11, color="grey"),
            ft.Divider(),
            ft.Text("Choose an action:", size=14),
        ], spacing=5)

        self.content = ft.Container(
            content=ft.Column([
                self.info_text,
                self.loc_dropdown,
                self.merge_loc_dropdown,
                ft.Row([self.merge_folder_dropdown, self.loading_folders], spacing=10),
                self.cycle_dropdown
            ], tight=True),
            width=400, height=350
        )

        self.btn_block = ft.ElevatedButton(
            "Not Mine", 
            icon=ft.Icons.BLOCK, 
            on_click=self.do_block_delete, 
            bgcolor=SSA_RED_BADGE, 
            color="white"
        )
        self.btn_move = ft.ElevatedButton(
            "Wrong Loc", 
            icon=ft.Icons.DRIVE_FILE_MOVE, 
            on_click=self.show_relocate_options, 
            bgcolor=ft.Colors.BLUE, 
            color="white"
        )
        self.btn_merge = ft.ElevatedButton(
            "Merge", 
            icon=ft.Icons.MERGE_TYPE, 
            on_click=self.show_merge_options, 
            bgcolor=ft.Colors.ORANGE, 
            color="white"
        )
        self.btn_cycle = ft.ElevatedButton(
            "Change Cycle",
            icon=ft.Icons.CALENDAR_MONTH,
            on_click=self.show_cycle_options,
            bgcolor=ft.Colors.TEAL,
            color="white"
        )

        self.actions = [
            ft.Column([
                ft.Row([self.btn_block, self.btn_move], alignment=ft.MainAxisAlignment.CENTER),
                ft.Row([self.btn_merge, self.btn_cycle], alignment=ft.MainAxisAlignment.CENTER),
                ft.TextButton("Cancel", on_click=self.close)
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=10)
        ]
        self.actions_alignment = ft.MainAxisAlignment.CENTER

    def close(self, e=None):
        self.open = False
        try: self.page_ref.close(self)
        except: pass
        self.page_ref.update()

    def _hide_other_actions(self, keep_btn):
        btns = [self.btn_block, self.btn_move, self.btn_merge, self.btn_cycle]
        for btn in btns:
            if btn != keep_btn: btn.visible = False

    def _disable_all(self):
        self.btn_block.disabled = True
        self.btn_move.disabled = True
        self.btn_merge.disabled = True
        self.btn_cycle.disabled = True

    def _show_error(self, btn):
        btn.text = "Error"
        btn.bgcolor = ft.Colors.RED_900
        btn.disabled = False
        self.page_ref.update()

    # --- ACCIÓN 1: BLOCK & DELETE ---
    def do_block_delete(self, e):
        self.btn_block.text = "Deleting..."
        self._disable_all()
        self.page_ref.update()
        threading.Thread(target=self._worker_block).start()

    def _worker_block(self):
        success = self.service.block_and_delete(
            self.req['id'], 
            self.req.get('conversation_id'),
            date_folder=self.req.get('date_folder'),
            location_code=self.req.get('location_code')
        )
        if success: 
            self.close()
            self.on_success(self.req['id'])
        else: 
            self._show_error(self.btn_block)

    # --- ACCIÓN 2: RELOCATE ---
    def show_relocate_options(self, e):
        if not self.loc_dropdown.visible:
            self._hide_other_actions(self.btn_move)
            self.loc_dropdown.visible = True
            self.btn_move.text = "Confirm Move"
            self.btn_move.icon = ft.Icons.CHECK
            self.btn_move.bgcolor = SSA_GREEN
            self.page_ref.update()
        else:
            new_loc = self.loc_dropdown.value
            if new_loc:
                self.btn_move.text = "Updating..."
                self._disable_all()
                self.page_ref.update()
                threading.Thread(target=self._worker_relocate, args=(new_loc,)).start()

    def _worker_relocate(self, new_loc):
        success = self.service.relocate_folder(
            self.req['id'], 
            new_loc, 
            self.req.get('conversation_id'),
            old_date_folder=self.req.get('date_folder'),
            old_location_code=self.req.get('location_code')
        )
        if success: 
            self.close()
            self.on_success(self.req['id'], new_loc_update=new_loc)
        else: 
            self._show_error(self.btn_move)

    # --- ACCIÓN 3: MERGE ---
    def show_merge_options(self, e):
        if not self.merge_loc_dropdown.visible:
            self._hide_other_actions(self.btn_merge)
            self.merge_loc_dropdown.visible = True
            self.merge_folder_dropdown.visible = True
            self.btn_merge.text = "Confirm Merge"
            self.btn_merge.icon = ft.Icons.CHECK
            self.btn_merge.bgcolor = SSA_GREEN
            self.btn_merge.disabled = True
            self.page_ref.update()
        else:
            target_id = self.merge_folder_dropdown.value
            target_name = ""
            for opt in self.merge_folder_dropdown.options:
                if opt.key == target_id: 
                    target_name = opt.text
                    break
            
            if target_id:
                self.btn_merge.text = "Merging..."
                self._disable_all()
                self.page_ref.update()
                threading.Thread(target=self._worker_merge, args=(target_id, target_name)).start()

    def on_merge_loc_change(self, e):
        loc = self.merge_loc_dropdown.value
        date_folder = self.req.get('date_folder')
        if not loc or not date_folder: return

        self.merge_folder_dropdown.options = []
        self.merge_folder_dropdown.disabled = True
        self.loading_folders.visible = True
        self.page_ref.update()

        def fetch():
            folders = self.service.get_folders_in_location(date_folder, loc)
            opts = [ft.dropdown.Option(key=f['id'], text=f['name']) for f in folders if f['id'] != self.req['id']]
            
            self.merge_folder_dropdown.options = opts
            self.merge_folder_dropdown.disabled = False
            self.merge_folder_dropdown.hint_text = "Select Target Folder"
            self.loading_folders.visible = False
            self.btn_merge.disabled = False
            self.page_ref.update()
        
        threading.Thread(target=fetch).start()

    def _worker_merge(self, target_id, target_name):
        loc = self.merge_loc_dropdown.value
        date = self.req.get('date_folder')
        
        success = self.service.merge_folders(
            self.req['id'], 
            target_id, 
            target_name, 
            self.req.get('conversation_id'), 
            loc, 
            date,
            source_location_code=self.req.get('location_code')
        )
        
        if success: 
            self.close()
            self.on_success(self.req['id']) 
        else: 
            self._show_error(self.btn_merge)

    # --- ACCIÓN 4: CHANGE CYCLE ---
    def show_cycle_options(self, e):
        if not self.cycle_dropdown.visible:
            self._hide_other_actions(self.btn_cycle)
            self.cycle_dropdown.visible = True
            self.btn_cycle.text = "Confirm Cycle"
            self.btn_cycle.icon = ft.Icons.CHECK
            self.btn_cycle.bgcolor = SSA_GREEN
            self.page_ref.update()
        else:
            target_date = self.cycle_dropdown.value
            if target_date:
                self.btn_cycle.text = "Moving..."
                self._disable_all()
                self.page_ref.update()
                threading.Thread(target=self._worker_change_cycle, args=(target_date,)).start()

    def _worker_change_cycle(self, target_date):
        success = self.service.change_request_cycle(
            self.req['id'],
            target_date,
            self.req.get('location_code'),
            self.req.get('conversation_id'),
            old_date=self.req.get('date_folder')
        )
        if success:
            self.close()
            # Al cambiar de ciclo, la tarjeta desaparece de la vista actual (si está filtrada por fecha)
            self.on_success(self.req['id'])
        else:
            self._show_error(self.btn_cycle)