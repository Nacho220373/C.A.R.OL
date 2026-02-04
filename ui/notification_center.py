import flet as ft
from ui.styles import SSA_GREEN, SSA_GREY, SSA_WHITE, SSA_BORDER, SSA_RED_BADGE

class NotificationCenter(ft.UserControl):
    def __init__(self, page: ft.Page):
        super().__init__()
        self.page = page
        self.manager = None 
        
        # Estado local
        self.show_panel = False
        self.filter_mode = "unread" 
        
        # Referencia al Stack principal para cambiar su tamaño dinámicamente
        self.main_stack = None 
        
        # Componentes UI
        self.badge_text = ft.Text("0", size=10, color="white", weight=ft.FontWeight.BOLD)
        self.badge_container = ft.Container(
            content=self.badge_text,
            bgcolor=SSA_RED_BADGE,
            border_radius=10,
            width=18, height=18,
            alignment=ft.alignment.center,
            visible=False
        )
        
        self.notif_list = ft.ListView(expand=True, spacing=2, padding=5)
        
        # Panel flotante
        self.panel_container = ft.Container(
            width=350,
            height=450,
            bgcolor=SSA_WHITE,
            border=ft.border.all(1, SSA_BORDER),
            border_radius=10,
            shadow=ft.BoxShadow(
                blur_radius=15,
                color=ft.colors.with_opacity(0.2, ft.colors.BLACK),
                offset=ft.Offset(0, 5)
            ),
            padding=10,
            visible=False,
            # Posicionamiento absoluto relativo al stack padre (self.main_stack)
            right=0, 
            top=45 
        )

    def set_manager(self, manager):
        self.manager = manager
        if self.manager:
            unread = sum(1 for n in self.manager.history if not n.get('read', False))
            self.update_badge(unread)

    def update_badge(self, count):
        self.badge_text.value = str(count) if count < 99 else "99+"
        self.badge_container.visible = (count > 0)
        try:
            if self.badge_text.page: self.badge_text.update()
            if self.badge_container.page: self.badge_container.update()
        except Exception: pass 

    def refresh_list(self):
        if not self.show_panel or not self.manager: return
        
        self.notif_list.controls.clear()
        data = self.manager.history
        if self.filter_mode == "unread":
            data = [n for n in data if not n.get('read', False)]
            
        if not data:
            self.notif_list.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Icon(ft.Icons.NOTIFICATIONS_OFF_OUTLINED, size=40, color=ft.Colors.GREY_300),
                        ft.Text("No notifications", color=ft.Colors.GREY_400)
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    alignment=ft.alignment.center,
                    padding=20
                )
            )
        else:
            for n in data:
                self.notif_list.controls.append(self._create_item(n))
        try:
            if self.notif_list.page: self.notif_list.update()
        except: pass

    def _create_item(self, notif):
        icon = ft.Icons.INFO
        color = ft.Colors.BLUE
        if notif['type'] == 'success': icon, color = ft.Icons.CHECK_CIRCLE, SSA_GREEN
        elif notif['type'] == 'error': icon, color = ft.Icons.ERROR, ft.Colors.RED
        elif notif['type'] == 'warning': icon, color = ft.Icons.WARNING, ft.Colors.ORANGE

        is_unread = not notif.get('read', False)
        bg_color = ft.Colors.BLUE_50 if is_unread else ft.Colors.WHITE

        return ft.Container(
            content=ft.Row([
                ft.Icon(icon, color=color, size=20),
                ft.Column([
                    ft.Text(notif['title'], weight=ft.FontWeight.BOLD, size=13, color=SSA_GREY),
                    ft.Text(notif['message'], size=11, color=ft.Colors.GREY_600, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(notif['timestamp'], size=9, color=ft.Colors.GREY_400)
                ], spacing=1, expand=True),
                ft.Column([
                    ft.IconButton(
                        ft.Icons.CHECK if is_unread else ft.Icons.DELETE_OUTLINE, 
                        icon_size=16, 
                        icon_color=SSA_GREEN if is_unread else ft.Colors.GREY_400,
                        tooltip="Mark Read" if is_unread else "Delete",
                        on_click=lambda e, nid=notif['id'], read=is_unread: self._handle_item_action(nid, read)
                    )
                ])
            ], alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.START),
            padding=10,
            border_radius=5,
            bgcolor=bg_color,
            border=ft.border.only(bottom=ft.BorderSide(1, ft.Colors.GREY_100))
        )

    def _handle_item_action(self, nid, is_read_action):
        if self.manager:
            if is_read_action:
                self.manager.mark_as_read(nid)
            else:
                self.manager.delete_notification(nid)

    def toggle_panel(self, e):
        self.show_panel = not self.show_panel
        self.panel_container.visible = self.show_panel
        
        # --- FIX BLOQUEO UI ---
        # Cambiamos dinámicamente el tamaño del Stack contenedor.
        # Si está cerrado -> 50x50 (solo campana).
        # Si está abierto -> 360x500 (panel completo).
        if self.main_stack:
            self.main_stack.width = 360 if self.show_panel else 50
            self.main_stack.height = 500 if self.show_panel else 50
            self.main_stack.update()

        if self.show_panel:
            self.refresh_list()

    def set_filter(self, mode):
        self.filter_mode = mode
        self.refresh_list()
        self.update()

    def mark_all_read(self, e):
        if self.manager: self.manager.mark_all_read()

    def clear_all(self, e):
        if self.manager: self.manager.clear_all_history()

    def build(self):
        # Botón de Campana
        bell_btn = ft.Stack([
            ft.IconButton(ft.Icons.NOTIFICATIONS, icon_color=SSA_GREY, on_click=self.toggle_panel, bgcolor=ft.Colors.WHITE),
            ft.Container(self.badge_container, right=5, top=5)
        ])

        # Contenido del Panel
        header = ft.Row([
            ft.Text("Notifications", weight=ft.FontWeight.BOLD, color=SSA_GREY),
            ft.Container(expand=True),
            ft.IconButton(ft.Icons.CLOSE, icon_size=16, on_click=self.toggle_panel)
        ])

        tabs = ft.Row([
            ft.TextButton("Unread", on_click=lambda e: self.set_filter("unread"), style=ft.ButtonStyle(color=SSA_GREEN if self.filter_mode=="unread" else ft.Colors.GREY)),
            ft.TextButton("All / History", on_click=lambda e: self.set_filter("all"), style=ft.ButtonStyle(color=SSA_GREEN if self.filter_mode=="all" else ft.Colors.GREY)),
        ], alignment=ft.MainAxisAlignment.CENTER)

        actions = ft.Row([
            ft.TextButton("Mark all read", on_click=self.mark_all_read, visible=(self.filter_mode=="unread")),
            ft.TextButton("Clear History", on_click=self.clear_all, visible=(self.filter_mode=="all"), style=ft.ButtonStyle(color=ft.Colors.RED)),
        ], alignment=ft.MainAxisAlignment.END)

        self.panel_container.content = ft.Column([
            header,
            ft.Divider(height=1),
            tabs,
            self.notif_list,
            ft.Divider(height=1),
            actions
        ], spacing=5)

        # --- FIX ERROR POSICIONAMIENTO & BLOQUEO ---
        # 1. self.panel_container es hijo directo del Stack (corrige error "containerControl...")
        # 2. Iniciamos con width=50, height=50 (corrige bloqueo de botones inferiores)
        self.main_stack = ft.Stack([
            self.panel_container, 
            ft.Container(content=bell_btn, right=0, top=0) 
        ], width=50, height=50) 
        
        return self.main_stack