import flet as ft
from datetime import datetime, timedelta
import calendar

class CalendarView(ft.Container):
    def __init__(self, available_dates_str: list[str], on_range_selected, on_dismiss=None):
        """
        :param available_dates_str: Lista de strings 'YYYYMMDD' que existen en SP.
        :param on_range_selected: Callback(start_date, end_date)
        :param on_dismiss: Callback opcional para cerrar el calendario sin cambios.
        """
<<<<<<< HEAD
        super().__init__()
        
        # Opciones visuales del contenedor
        self.width = 320
        self.height = 350
        self.padding = 10
        self.bgcolor = "white"
        self.border_radius = 10
        self.border = ft.border.all(1, "#e0e0e0")
        self.shadow = ft.BoxShadow(blur_radius=10, color=ft.Colors.with_opacity(0.1, "black"))
=======
        super().__init__(
            width=320,
            height=350,
            padding=10,
            bgcolor="white",
            border_radius=10,
            border=ft.border.all(1, "#e0e0e0"),
            shadow=ft.BoxShadow(blur_radius=10, color=ft.Colors.with_opacity(0.1, "black"))
        )
>>>>>>> 050048a87e330291b783c1b91c5b654cf7c42826
        
        self.on_range_selected = on_range_selected
        self.on_dismiss = on_dismiss
        
        # Parsear fechas disponibles
        self.available_dates = set()
        for d_str in available_dates_str:
            try:
                dt = datetime.strptime(d_str, "%Y%m%d").date()
                self.available_dates.add(dt)
            except:
                pass

        self.current_month = datetime.now().date().replace(day=1)
        self.selected_start = None
        self.selected_end = None
        
        # Grid del calendario
        self.calendar_grid = ft.GridView(
            runs_count=7, # 7 días
            max_extent=40,
            child_aspect_ratio=1.0,
            spacing=5,
            run_spacing=5,
        )
        
        self.month_label = ft.Text(
            self.current_month.strftime("%B %Y"), 
            size=16, weight=ft.FontWeight.BOLD
        )

        self.content = self._build_layout()
        
        # Llenamos el calendario inicial. 
        if self.page:
            self.update_calendar()
        else:
            # Si no hay página aún, llenamos los controles pero sin llamar a self.update()
            self._fill_calendar_controls()

    def _build_layout(self):
        # Cabecera: < Mes >  [X]
        header = ft.Row(
            [
                # Controles de Navegación
                ft.Row([
                    ft.IconButton(ft.Icons.CHEVRON_LEFT, on_click=self.prev_month, icon_size=20),
                    self.month_label,
                    ft.IconButton(ft.Icons.CHEVRON_RIGHT, on_click=self.next_month, icon_size=20),
                ], alignment=ft.MainAxisAlignment.START, spacing=0),
                
                # Botón de Cerrar (Si se proporcionó callback)
                ft.IconButton(ft.Icons.CLOSE, on_click=lambda e: self.on_dismiss() if self.on_dismiss else None, icon_size=18, tooltip="Close")
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN
        )
        
        # Días de la semana
        weekdays = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
        week_header = ft.Row(
            [ft.Text(day, size=12, weight="bold", color="grey", text_align="center", width=35) for day in weekdays],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN
        )

        return ft.Column([header, week_header, self.calendar_grid], spacing=10)

    def _fill_calendar_controls(self):
        """Lógica pura de llenado de controles, separada del update() de Flet."""
        self.calendar_grid.controls.clear()
        
        year = self.current_month.year
        month = self.current_month.month
        
        # Obtener matriz del mes
        cal = calendar.monthcalendar(year, month)
        
        self.month_label.value = self.current_month.strftime("%B %Y")
        
        for week in cal:
            for day in week:
                if day == 0:
                    self.calendar_grid.controls.append(ft.Container(width=35, height=35))
                    continue
                
                date_obj = datetime(year, month, day).date()
                
                # --- ESTILOS VISUALES AJUSTADOS ---
                bg_color = ft.Colors.TRANSPARENT
                
                # Por defecto: negro normal (disponible)
                text_color = ft.Colors.BLACK 
                font_weight = ft.FontWeight.NORMAL
                
                # 1. ¿Está en SharePoint? (Resaltado sutil para indicar "datos seguros")
                if date_obj in self.available_dates:
                    bg_color = "#E8F5E9" # Verde muy claro
                    text_color = "#2E7D32" # Verde oscuro
                    font_weight = ft.FontWeight.BOLD

                # 2. ¿Está seleccionado? (Sobrescribe todo)
                if self.selected_start:
                    if self.selected_end:
                        # Rango
                        if self.selected_start <= date_obj <= self.selected_end:
                            bg_color = "#84BD00" # SSA Green
                            text_color = "white"
                            font_weight = ft.FontWeight.BOLD
                    else:
                        # Solo inicio
                        if date_obj == self.selected_start:
                            bg_color = "#84BD00"
                            text_color = "white"
                            font_weight = ft.FontWeight.BOLD

                # Botón del día
                btn = ft.Container(
                    content=ft.Text(str(day), color=text_color, weight=font_weight),
                    alignment=ft.alignment.center,
                    width=35, height=35,
                    bgcolor=bg_color,
                    border_radius=5,
                    on_click=lambda e, d=date_obj: self.on_day_click(d),
                    ink=True
                )
                self.calendar_grid.controls.append(btn)

    def update_calendar(self):
        self._fill_calendar_controls()
        if self.page:
            self.update()

    def prev_month(self, e):
        first = self.current_month.replace(day=1)
        prev = first - timedelta(days=1)
        self.current_month = prev.replace(day=1)
        self.update_calendar()

    def next_month(self, e):
        days_in_month = calendar.monthrange(self.current_month.year, self.current_month.month)[1]
        next_m = self.current_month + timedelta(days=days_in_month + 1)
        self.current_month = next_m.replace(day=1)
        self.update_calendar()

    def on_day_click(self, date_obj):
        # Lógica de selección de rango
        if self.selected_start is None:
            # Primer clic: Selecciona inicio
            self.selected_start = date_obj
            self.selected_end = None
        
        elif self.selected_start and self.selected_end is None:
            # Segundo clic: Define el final o reinicia
            if date_obj < self.selected_start:
                # Si clic atrás, reinicia el inicio
                self.selected_start = date_obj
            elif date_obj == self.selected_start:
                # Clic en la misma fecha -> Rango de un solo día
                self.selected_end = date_obj
                self.on_range_selected(self.selected_start, self.selected_end)
            else:
                # Clic adelante -> Cierra el rango
                self.selected_end = date_obj
                self.on_range_selected(self.selected_start, self.selected_end)
        
        else:
            # Tercer clic (ya había rango): Reinicia todo con nueva fecha inicio
            self.selected_start = date_obj
            self.selected_end = None
        
        self.update_calendar()