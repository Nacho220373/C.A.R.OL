import flet as ft
import threading
import time
from datetime import datetime, timezone
from ui.styles import SSA_GREEN

# --- LIVE COMPONENT: SELF-UPDATING BADGE ---
class LiveStatBadge(ft.Container): 
    def __init__(self, calculator, limit_date, icon, default_text, default_color, completion_date=None):
        super().__init__()
        self.calculator = calculator
        self._limit_date = limit_date
        self._completion_date = completion_date # Nuevo estado interno
        self.page_ref = None 
        
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

    @property
    def limit_date(self):
        return self._limit_date

    @limit_date.setter
    def limit_date(self, value):
        self._limit_date = value
        self._check_visibility_and_run()

    # Nueva propiedad para manejar la fecha de fin externamente
    @property
    def completion_date(self):
        return self._completion_date

    @completion_date.setter
    def completion_date(self, value):
        self._completion_date = value
        self._check_visibility_and_run()

    def _check_visibility_and_run(self):
        # Si no hay fecha límite, el badge se apaga/oculta
        if not self._limit_date:
            self.running = False
            self.visible = False # Ocultar visualmente
            if self.page: self.update()
            return

        self.visible = True
        
        # Si YA se completó, calculamos una vez y detenemos el hilo
        if self._completion_date:
            self.running = False
            # Forzamos un cálculo estático
            stat = self.calculator.calculate_time_left(self._limit_date, datetime.now(timezone.utc), self._completion_date)
            self._apply_style(stat)
            if self.page: self.update()
        else:
            # Si no está completo, aseguramos que el hilo corra
            if not self.running:
                self.running = True
                if self.page: 
                    threading.Thread(target=self.update_timer, daemon=True).start()

    def _apply_style(self, stat):
        col = stat['color']
        if col == "green": col = SSA_GREEN
        
        self.text_control.value = stat['text']
        self.text_control.color = col
        self.icon_control.color = col
        
        if stat['color'] == "red":
            self.bgcolor = ft.Colors.RED_50
            self.border = ft.border.all(1, ft.Colors.RED_200)
        else:
            self.bgcolor = ft.Colors.GREY_100
            self.border = ft.border.all(1, ft.Colors.TRANSPARENT)

    def did_mount(self):
        self.page_ref = self.page
        self._check_visibility_and_run()

    def will_unmount(self):
        self.running = False

    def update_timer(self):
        while self.running:
            try:
                if not self.page_ref or not self._limit_date or self._completion_date:
                    self.running = False
                    break

                now = datetime.now(timezone.utc)
                # Pasamos None como completion_date porque estamos en modo vivo
                new_stat = self.calculator.calculate_time_left(self._limit_date, now, None)
                self._apply_style(new_stat)
                self.update()
                time.sleep(1)
            except Exception:
                self.running = False