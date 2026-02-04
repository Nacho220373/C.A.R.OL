import flet as ft
from datetime import datetime, timezone
from ui.styles import SSA_GREEN

# --- OPTIMIZED COMPONENT: PASSIVE BADGE ---
# Refactorizado para eliminar threading interno y evitar saturación del GIL.
# Ahora es controlado por un Timer central en DashboardManager.
class LiveStatBadge(ft.Container): 
    def __init__(self, calculator, limit_date, icon, default_text, default_color, completion_date=None):
        super().__init__()
        self.calculator = calculator
        self._limit_date = limit_date
        self._completion_date = completion_date
        
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
        
        # Inicialización visual inmediata (sin hilos)
        self._refresh_visuals()

    @property
    def limit_date(self):
        return self._limit_date

    @limit_date.setter
    def limit_date(self, value):
        self._limit_date = value
        self._refresh_visuals()

    @property
    def completion_date(self):
        return self._completion_date

    @completion_date.setter
    def completion_date(self, value):
        self._completion_date = value
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

    def _apply_style(self, stat):
        col = stat['color']
        if col == "green": col = SSA_GREEN
        
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