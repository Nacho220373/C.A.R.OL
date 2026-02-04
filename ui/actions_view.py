import flet as ft
import json
import threading
from ui.styles import SSA_GREEN, SSA_GREY, SSA_WHITE, SSA_BG, SSA_BORDER
from services.employee_info_service import EmployeeInfoService
from services.user_service import UserService
from ui.timecard_view import TimecardView


class ActionsView(ft.Container):
    def __init__(self, page: ft.Page, watcher_service=None):
        super().__init__()
        self.page = page
        self.watcher_service = watcher_service
        self._employee_service = None 
        self._user_service = None
        self._cached_user_name = None

        self.expand = True
        self.padding = 20
        self.bgcolor = SSA_BG

        self.current_subview = None
        self.detail_sheet = None
        
        # --- FILTRO DE ESTADO (CHIPS) ---
        self.selected_status = None
        self.status_chips_row = ft.Row(scroll=ft.ScrollMode.HIDDEN, spacing=8)
        
        self._build_main_ui()
        
        # NOTA: No iniciamos los loaders aquí para evitar "Control not added to page"
        # Se inician en did_mount

    def did_mount(self):
        """Se ejecuta cuando el control es agregado a la página. Seguro para iniciar cargas."""
        self._init_pay_group_loader()
        self._init_status_loader()

    @property
    def employee_service(self):
        if self._employee_service is None:
            self._employee_service = EmployeeInfoService()
        return self._employee_service

    @property
    def user_service(self):
        if self._user_service is None:
            self._user_service = UserService()
        return self._user_service

    def _get_current_user_name(self):
        if self._cached_user_name: return self._cached_user_name
        try:
            user_data = self.user_service.get_current_user()
            if user_data and 'displayName' in user_data:
                self._cached_user_name = user_data['displayName']
                return self._cached_user_name
        except: pass
        return "Unknown User"

    def _init_pay_group_loader(self):
        def load():
            try:
                groups = self.employee_service.get_unique_pay_groups()
                # Agregamos opción "Any" para poder limpiar el filtro desde el dropdown
                options = [ft.dropdown.Option("Any")] + [ft.dropdown.Option(g) for g in groups]
                self.pay_group_dropdown.options = options
                self.pay_group_dropdown.disabled = False
                
                # UPDATE SEGURO: Solo si el control sigue vivo en la página
                if self.pay_group_dropdown.page:
                    self.pay_group_dropdown.update()
            except Exception as e:
                print(f"Error loading pay groups: {e}")

        threading.Thread(target=load, daemon=True).start()

    def _init_status_loader(self):
        def load():
            try:
                statuses = self.employee_service.get_unique_statuses()
                if not statuses: return
                
                chips = []
                for s in statuses:
                    chips.append(
                        ft.Chip(
                            label=ft.Text(s, size=12, weight=ft.FontWeight.W_500),
                            data=s,
                            on_select=self._on_status_chip_select,
                            bgcolor=ft.Colors.WHITE,
                            selected_color=SSA_GREEN,
                            label_style=ft.TextStyle(color=SSA_GREY), # Color por defecto
                            check_color=ft.Colors.WHITE,
                            shape=ft.RoundedRectangleBorder(radius=6),
                        )
                    )
                
                self.status_chips_row.controls = chips
                
                # UPDATE SEGURO: Solo si el control sigue vivo en la página
                if self.status_chips_row.page:
                    self.status_chips_row.update()
            except Exception as e:
                print(f"Error loading statuses: {e}")

        threading.Thread(target=load, daemon=True).start()

    def _on_status_chip_select(self, e):
        clicked_chip = e.control
        
        # Lógica de selección única (Radio Button behavior)
        if clicked_chip.selected:
            self.selected_status = clicked_chip.data
        else:
            self.selected_status = None
        
        # Actualizar visualmente todos los chips
        for chip in self.status_chips_row.controls:
            if chip != clicked_chip:
                chip.selected = False # Desmarcar los otros
            
            # Estilos condicionales
            if chip.selected:
                chip.label_style.color = ft.Colors.WHITE
            else:
                chip.label_style.color = SSA_GREY
        
        if self.status_chips_row.page:
            self.status_chips_row.update()

    # ----------------------------- UI base ----------------------------------

    def _build_main_ui(self):
        apps_row = ft.Row(
            [
                self._build_app_card("Timecard Posting", ft.Icons.ACCESS_TIME, self.go_to_timecards),
                self._build_app_card("Coming Soon", ft.Icons.BUILD, None),
            ],
            spacing=20,
        )

        self.results_column = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO, expand=True)
        self.loading_indicator = ft.ProgressRing(color=SSA_GREEN, width=20, height=20, visible=False)
        self.results_count = ft.Text("", size=12, color=SSA_GREY)
        
        self.results_warning = ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.WARNING_AMBER, color="black"),
                ft.Text("Showing first 100 matches. Please refine your search for accurate information.", weight="bold")
            ]),
            bgcolor=ft.Colors.AMBER_300,
            padding=10,
            border_radius=8,
            visible=False
        )

        self.search_field = ft.TextField(
            hint_text="Enter EE ID, File Number or Name...",
            prefix_icon=ft.Icons.SEARCH,
            text_size=16,
            height=50,
            border_radius=8,
            border_color=SSA_GREEN,
            bgcolor=SSA_WHITE,
            expand=True,
            on_submit=self.execute_search
        )

        # --- PAY GROUP DROPDOWN ---
        self.pay_group_dropdown = ft.Dropdown(
            label="Pay Group",
            width=150,
            height=50,
            text_size=14,
            border_radius=8,
            border_color=SSA_GREEN,
            bgcolor=SSA_WHITE,
            options=[], 
            disabled=True,
        )

        search_btn = ft.ElevatedButton(
            "Search",
            icon=ft.Icons.SEARCH,
            style=ft.ButtonStyle(
                bgcolor=SSA_GREEN,
                color=SSA_WHITE,
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=20,
            ),
            on_click=self.execute_search,
        )

        # Botón de borrar búsqueda
        clear_btn = ft.IconButton(
            icon=ft.Icons.CLOSE,
            tooltip="Clear Search",
            icon_color=ft.Colors.RED_400,
            on_click=self.clear_search
        )

        self.main_content = ft.Column(
            [
                ft.Text("Quick Apps", size=20, weight=ft.FontWeight.BOLD, color=SSA_GREY),
                apps_row,
                ft.Divider(),
                ft.Text("Employee Search", size=20, weight=ft.FontWeight.BOLD, color=SSA_GREY),
                
                # Fila de Búsqueda
                ft.Row([self.search_field, self.pay_group_dropdown, search_btn, clear_btn]),
                
                # Fila de Chips de Estado (Filtro bonito)
                ft.Container(
                    content=self.status_chips_row,
                    padding=ft.padding.only(left=5, bottom=10)
                ),

                ft.Row([self.results_count, self.loading_indicator], alignment=ft.MainAxisAlignment.CENTER),
                self.results_warning,
                self.results_column,
            ],
            spacing=10,
            expand=True,
        )
        self.content = self.main_content

    def clear_search(self, e):
        """Limpia todos los campos y resultados, incluyendo chips."""
        self.search_field.value = ""
        self.pay_group_dropdown.value = None
        
        # Limpiar selección de chips
        self.selected_status = None
        for chip in self.status_chips_row.controls:
            chip.selected = False
            chip.label_style.color = SSA_GREY
        
        # FIX CRÍTICO: Verificar si estamos conectados a la página antes de actualizar
        if self.status_chips_row.page:
            self.status_chips_row.update()

        self.results_column.controls.clear()
        self.results_count.value = ""
        self.results_warning.visible = False
        
        if self.page:
            self.page.update()

    # ------------------------------- Search ---------------------------------

    def execute_search(self, e):
        query = self.search_field.value
        pg_val = self.pay_group_dropdown.value
        
        # Filtramos "Any" para que signifique 'sin filtro'
        pg_filter = pg_val if pg_val and pg_val != "Any" else None
        st_filter = self.selected_status
        
        if not query and not pg_filter and not st_filter:
            return
            
        self.loading_indicator.visible = True
        self.results_warning.visible = False
        self.results_column.controls.clear()
        self.results_count.value = "Searching..."
        self.page.update()

        threading.Thread(target=self._search_employee_thread, args=(query, pg_filter, st_filter), daemon=True).start()

    def _search_employee_thread(self, query, pg_filter, st_filter):
        results, limit_reached = self.employee_service.search_employee(
            query, 
            pay_group_filter=pg_filter, 
            status_filter=st_filter
        )
        
        self.loading_indicator.visible = False
        self.results_count.value = f"Found {len(results)} employees."
        self.results_warning.visible = limit_reached 
        
        cards = []
        if not results:
            cards.append(ft.Container(content=ft.Text("No employees found.", italic=True), alignment=ft.alignment.center, padding=20))
        else:
            for emp in results:
                cards.append(self._build_employee_card(emp))
        
        self.results_column.controls = cards
        
        # Try-catch por si el usuario cerró o cambió de vista mientras buscaba
        try:
            self.page.update()
        except: pass

    # --------------------------- Employee cards -----------------------------

    def _build_employee_card(self, emp):
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.PERSON, color=SSA_GREEN),
                            ft.Text(emp["full_name"], weight=ft.FontWeight.BOLD, size=16, expand=True),
                            ft.Container(
                                content=ft.Text(emp["status"], color=SSA_WHITE, size=10),
                                bgcolor=SSA_GREEN if emp["status"] == "Active" else ft.Colors.RED,
                                padding=5,
                                border_radius=5,
                            ),
                        ]
                    ),
                    ft.Divider(height=5),
                    ft.Row(
                        [
                            self._info_field("EE ID:", emp["id"]),
                            self._info_field("File #:", emp["file_number"]),
                            self._info_field("Pay Group:", emp["pay_group"]),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Row(
                        [
                            self._info_field("Email:", emp["email"]),
                            self._info_field("Dept:", emp["department"]),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Text(f"Job: {emp['job_title']}", size=12, color=ft.Colors.GREY_700, italic=True),
                ]
            ),
            padding=15,
            bgcolor=SSA_WHITE,
            border_radius=8,
            border=ft.border.all(1, SSA_BORDER),
            ink=True,
            on_click=lambda e, data=emp: self._open_employee_detail(data),
        )

    def _info_field(self, label, value):
        return ft.Column(
            [ft.Text(label, size=10, color=ft.Colors.GREY), ft.Text(str(value), size=12, weight=ft.FontWeight.W_500)],
            spacing=0,
        )

    # ----------------------------- Detail sheet -----------------------------

    def _copy_to_clipboard(self, value):
        self.page.set_clipboard(str(value))
        self.page.snack_bar = ft.SnackBar(ft.Text(f"Copied: {value}"))
        self.page.snack_bar.open = True
        self.page.update()

    def _copy_all_info(self, pretty_data):
        """Copia toda la información en formato texto plano."""
        lines = []
        for k, v in pretty_data:
            lines.append(f"{k}: {v}")
        full_text = "\n".join(lines)
        self.page.set_clipboard(full_text)
        self.page.snack_bar = ft.SnackBar(ft.Text("All information copied to clipboard"))
        self.page.snack_bar.open = True
        self.page.update()

    def _open_employee_detail(self, emp, highlighted_event=None):
        body_controls = []

        # 1. Conflictos
        pay_info = emp.get("pay_info") or {}
        grouped = (pay_info.get("grouped") or {}) if pay_info else {}
        if pay_info.get("needs_confirmation"):
            conflict_controls = []
            for key, group in grouped.items():
                values = group.get("values") or []
                if len(values) > 1:
                    conflict_controls.append(
                         ft.Column(
                            [
                                ft.Text(group.get("label", key), weight=ft.FontWeight.BOLD),
                                ft.Row(
                                    wrap=True,
                                    controls=[
                                        ft.Chip(
                                            label=ft.Text(opt),
                                            on_select=lambda e, v=opt, field=key, grp=group: self._confirm_pay_rate(emp, field, v, grp.get("label", field)),
                                        )
                                        for opt in values
                                    ],
                                    spacing=8,
                                    run_spacing=8,
                                ),
                                ft.Divider(),
                            ]
                        )
                    )
            if conflict_controls:
                body_controls.append(ft.Container(bgcolor=ft.Colors.AMBER_100, padding=10, border_radius=8, content=ft.Column([ft.Text("Multiple pay rates detected.", weight=ft.FontWeight.BOLD), *conflict_controls])))

        # 2. Selector "Time Machine"
        ch = emp.get("change_history") or {}
        parsed_history = ch.get("parsed") or []
        
        history_options = [ft.dropdown.Option("current", "Current Version")]
        for evt in parsed_history:
            evt_json = json.dumps(evt)
            label = f"{evt.get('date')} - {evt.get('field')} ({evt.get('user')})"
            history_options.append(ft.dropdown.Option(evt_json, label))

        def on_history_change(e):
            val = e.control.value
            if val == "current":
                self._open_employee_detail(emp, highlighted_event=None)
            else:
                try:
                    evt_data = json.loads(val)
                    self._open_employee_detail(emp, highlighted_event=evt_data)
                except: pass

        current_dd_value = json.dumps(highlighted_event) if highlighted_event else "current"

        history_dropdown = ft.Dropdown(
            label="Highlight Change (Time Machine)",
            options=history_options,
            value=current_dd_value,
            on_change=on_history_change,
            text_size=12,
            height=45,
            content_padding=10
        )
        
        # 3. Lista Principal
        pretty = self.employee_service.get_pretty_fields_for_detail(emp.get("_raw_fields") or {})
        
        kv_controls = []
        for label, val in pretty:
            is_match = False
            compare_text = None
            
            if highlighted_event:
                hist_field = highlighted_event.get("field")
                if hist_field and hist_field.lower() == label.lower():
                    is_match = True
                    old_val = highlighted_event.get("old")
                    compare_text = f"Was: {old_val}"

            kv_controls.append(
                self._kv_row(label, val, highlight=is_match, secondary_text=compare_text)
            )

        details_list = ft.ListView(expand=1, spacing=6, padding=0, controls=kv_controls)

        header = ft.Row(
            [
                ft.Column([
                    ft.Text(emp.get("full_name", "Employee"), weight=ft.FontWeight.BOLD, size=18),
                    ft.Text("Employee Details", size=12, color=ft.Colors.GREY)
                ], expand=True),
                
                # Botón Copiar Todo
                ft.IconButton(
                    icon=ft.Icons.COPY_ALL, 
                    tooltip="Copy All Info",
                    on_click=lambda e: self._copy_all_info(pretty)
                ),
                
                ft.IconButton(ft.Icons.CLOSE, on_click=lambda e: self._close_detail_sheet()),
            ]
        )

        content_column = ft.Column(
            [
                header, 
                ft.Divider(), 
                *body_controls, 
                history_dropdown, 
                ft.Text("Full Information", weight=ft.FontWeight.BOLD), 
                details_list
            ],
            spacing=10,
            expand=True,
        )

        self.detail_sheet = ft.Container(
            content=content_column,
            width=700,
            bgcolor=SSA_WHITE,
            padding=20,
            border=ft.border.only(left=ft.BorderSide(1, SSA_BORDER)),
        )

        self.page.overlay.clear()
        
        overlay_root = ft.Container(
            content=ft.Row([ft.Container(expand=True), self.detail_sheet], expand=True),
            expand=True,
            bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.BLACK),
            on_click=lambda e: self._close_detail_sheet(),
        )

        self.page.overlay.append(overlay_root)
        self.page.update()

    def _close_detail_sheet(self):
        self.page.overlay.clear()
        self.page.update()

    def _kv_row(self, key, value, highlight=False, secondary_text=None):
        val_content = [ft.Text(value, selectable=True, weight=ft.FontWeight.BOLD if highlight else ft.FontWeight.NORMAL)]
        
        bg_color = ft.Colors.TRANSPARENT
        if highlight:
            bg_color = ft.Colors.YELLOW_100 
            if secondary_text:
                val_content.append(
                    ft.Container(
                        content=ft.Text(secondary_text, size=11, color=ft.Colors.RED_700, weight=ft.FontWeight.BOLD),
                        bgcolor=ft.Colors.RED_50,
                        padding=2,
                        border_radius=4,
                        margin=ft.margin.only(top=2)
                    )
                )

        return ft.Container(
            content=ft.Row(
                [
                    ft.Text(key, weight=ft.FontWeight.BOLD, color=SSA_GREY, width=260),
                    ft.Column(val_content, spacing=0, expand=True),
                    # Botón Copiar Individual
                    ft.IconButton(
                        icon=ft.Icons.CONTENT_COPY, 
                        icon_size=14, 
                        icon_color=ft.Colors.GREY_400,
                        tooltip="Copy",
                        on_click=lambda e: self._copy_to_clipboard(value)
                    )
                ],
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.START # Alinear arriba para textos largos
            ),
            bgcolor=bg_color,
            padding=5,
            border_radius=5
        )

    def _confirm_pay_rate(self, emp, target_field_internal_name, chosen_value, field_label_friendly):
        try:
            sp_item_id = emp.get("sp_item_id")
            if not sp_item_id: raise ValueError("Item ID not found")

            real_user_name = self._get_current_user_name()
            raw_fields = emp.get("_raw_fields", {})
            old_val = raw_fields.get(target_field_internal_name, "Unknown")
            
            current_history_raw = emp.get("_raw_history_json", "")
            
            new_history_json = self.employee_service.append_history_entry(
                current_raw_json=current_history_raw,
                user_display_name=real_user_name,
                field_label=field_label_friendly,
                old_value=old_val,
                new_value=chosen_value
            )
            
            updates = {
                target_field_internal_name: chosen_value,
                self.employee_service.COL_MAP["CHANGE_HISTORY"]: new_history_json
            }

            self.employee_service.update_employee_fields(sp_item_id, updates)

            emp["_raw_fields"][target_field_internal_name] = chosen_value
            emp["_raw_history_json"] = new_history_json
            
            c = self.employee_service.COL_MAP
            new_pay_info = self.employee_service._compute_pay_info(
                emp["_raw_fields"].get(c["PAY_RATE"]),
                emp["_raw_fields"].get(c["PRIMARY_PAY_RATE"]),
                emp["_raw_fields"].get(c["HOURLY_RATE_2"]),
            )
            emp["pay_info"] = new_pay_info
            emp["change_history"] = self.employee_service._parse_change_history(new_history_json)

            self.page.snack_bar = ft.SnackBar(ft.Text(f"Updated {field_label_friendly} to {chosen_value}"))
            self.page.snack_bar.open = True

            self._close_detail_sheet()
            self._open_employee_detail(emp)

        except Exception as ex:
            self.page.snack_bar = ft.SnackBar(ft.Text(f"Error saving: {ex}"), bgcolor=ft.Colors.RED_200)
            self.page.snack_bar.open = True
            self.page.update()

    # ------------------------------- Apps -----------------------------------

    def _build_app_card(self, title, icon, on_click):
        return ft.Container(
            content=ft.Column(
                [ft.Icon(icon, size=30, color=SSA_GREEN), ft.Text(title, weight=ft.FontWeight.BOLD, color=SSA_GREY)],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            width=150,
            height=100,
            bgcolor=SSA_WHITE,
            border_radius=10,
            border=ft.border.all(1, SSA_BORDER),
            ink=True,
            on_click=on_click if on_click else None,
            opacity=1.0 if on_click else 0.5,
        )

    def go_to_timecards(self, e):
        # Al ir a otra sub-vista, también limpiamos para mantener estado fresco
        self.clear_search(None) 
        
        self.current_subview = TimecardView(self.page, self.watcher_service)
        back_btn = ft.IconButton(ft.Icons.ARROW_BACK, on_click=self.go_back_main)
        self.content = ft.Column(
            [
                ft.Row([back_btn, ft.Text("Back to Actions", weight=ft.FontWeight.BOLD)]),
                self.current_subview,
            ],
            expand=True,
        )
        self.page.update()

    def go_back_main(self, e):
        # FIX: Restaurar contenido ANTES de limpiar
        # Esto asegura que los controles (chips) vuelvan a estar en el árbol
        # antes de que clear_search intente actualizarlos.
        self.content = self.main_content
        
        # Limpieza al regresar al menú principal de Actions
        self.clear_search(None)
        
        self.page.update()