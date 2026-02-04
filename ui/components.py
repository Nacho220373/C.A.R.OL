import flet as ft
<<<<<<< HEAD
from datetime import datetime, timezone
from ui.styles import SSA_GREEN

# --- OPTIMIZED COMPONENT: PASSIVE BADGE ---
# Refactorizado para eliminar threading interno y evitar saturación del GIL.
# Ahora es controlado por un Timer central en DashboardManager.
=======
import threading
import time
from datetime import datetime, timezone
from ui.styles import SSA_GREEN

# --- LIVE COMPONENT: SELF-UPDATING BADGE ---
>>>>>>> 050048a87e330291b783c1b91c5b654cf7c42826
class LiveStatBadge(ft.Container): 
    def __init__(self, calculator, limit_date, icon, default_text, default_color, completion_date=None):
        super().__init__()
        self.calculator = calculator
        self._limit_date = limit_date
<<<<<<< HEAD
        self._completion_date = completion_date
=======
        self._completion_date = completion_date # Nuevo estado interno
        self.page_ref = None 
>>>>>>> 050048a87e330291b783c1b91c5b654cf7c42826
        
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
        
<<<<<<< HEAD
        # Inicialización visual inmediata (sin hilos)
        self._refresh_visuals()
=======
        self.running = False
>>>>>>> 050048a87e330291b783c1b91c5b654cf7c42826

    @property
    def limit_date(self):
        return self._limit_date

    @limit_date.setter
    def limit_date(self, value):
        self._limit_date = value
<<<<<<< HEAD
        self._refresh_visuals()

=======
        self._check_visibility_and_run()

    # Nueva propiedad para manejar la fecha de fin externamente
>>>>>>> 050048a87e330291b783c1b91c5b654cf7c42826
    @property
    def completion_date(self):
        return self._completion_date

    @completion_date.setter
    def completion_date(self, value):
        self._completion_date = value
<<<<<<< HEAD
        self._refresh_visuals()

    @property
    def is_active(self):
        """Devuelve True si el contador debe seguir corriendo (Tiene límite y NO está completado)."""
        return bool(self._limit_date) and not bool(self._completion_date)

    def _refresh_visuals(self):
        """Recálculo inmediato para cambios de estado."""
        if not self._limit_date:
            self.visible = False
        else:
            self.visible = True
            # Calculamos el estado actual una vez
            now = datetime.now(timezone.utc)
            self.update_state(now)

    def update_state(self, now_dt):
        """
        Calcula el tiempo restante y actualiza las propiedades internas de los controles.
        IMPORTANTE: No llama a self.update(). Eso lo hace el Manager en lote.
        """
        if not self._limit_date: return

        # Si tiene fecha de fin, usamos esa para el cálculo estático
        # Si no, usamos 'now_dt'
        
        stat = self.calculator.calculate_time_left(
            self._limit_date, 
            now_dt, 
            completion_dt=self._completion_date
        )
        
        self._apply_style(stat)
=======
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
>>>>>>> 050048a87e330291b783c1b91c5b654cf7c42826

    def _apply_style(self, stat):
        col = stat['color']
        if col == "green": col = SSA_GREEN
        
<<<<<<< HEAD
        # Actualizamos propiedades solo si cambiaron (Micro-optimización)
        if self.text_control.value != stat['text']:
            self.text_control.value = stat['text']
        
        if self.text_control.color != col:
            self.text_control.color = col
            self.icon_control.color = col
        
        if stat['color'] == "red":
            new_bg = ft.Colors.RED_50
            new_border_col = ft.Colors.RED_200
        else:
            new_bg = ft.Colors.GREY_100
            new_border_col = ft.Colors.TRANSPARENT
            
        if self.bgcolor != new_bg: 
            self.bgcolor = new_bg
        
        # Flet border check simplificado
        if self.border.top.color != new_border_col:
            self.border = ft.border.all(1, new_border_col)
=======
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
>>>>>>> 050048a87e330291b783c1b91c5b654cf7c42826
