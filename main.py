import flet as ft
import time
import os
import ctypes
import sys
import traceback
from ui.dashboard_manager import DashboardManager
from ui.styles import SSA_BG, SSA_WHITE, SSA_GREY, SSA_GREEN, SSA_BORDER
from services.session_monitor import SessionMonitor

# --- NUEVO: Manejo global de errores ---
from error_tracking import setup_global_exception_handler, track_errors

from runtime_paths import resource_path

# --- PREPARACIÓN DE RUTAS ---
assets_path = resource_path("assets")

def main(page: ft.Page):
    # --- NIVEL 3: Instalar Catch-All Global ---
    setup_global_exception_handler()

    # --- TRUCO WINDOWS (Icono en barra de tareas) ---
    try:
        myappid = 'ssa.carol.dashboard.v2.dev' 
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception: pass

    page.title = "C.A.R.O.L"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = SSA_BG
    page.padding = 0 
    page.window_width = 1200
    page.window_height = 850
    
    # --- ICONO ---
    icon_path_abs = os.path.join(assets_path, "app_icon.ico")
    if os.path.exists(icon_path_abs): page.window_icon = icon_path_abs
    else: page.window_icon = "Icono.png"

    # =================================================================
    #                       COMPONENTES HEADER
    # =================================================================

    user_name_small = ft.Text("", size=14, weight=ft.FontWeight.BOLD, color=SSA_GREY, font_family="monospace")

    right_section = ft.Column(
        [user_name_small], 
        spacing=2, 
        horizontal_alignment=ft.CrossAxisAlignment.END,
        alignment=ft.MainAxisAlignment.CENTER
    )

    center_section = ft.Column([
        ft.Text("C.A.R.O.L", size=28, weight=ft.FontWeight.BOLD, color=SSA_GREY),
        ft.Text("Global Business Services", size=14, color=SSA_GREY)
    ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER)

    header = ft.Container(
        padding=ft.padding.symmetric(horizontal=20, vertical=15),
        bgcolor=SSA_WHITE,
        border=ft.border.only(bottom=ft.BorderSide(1, SSA_BORDER)),
        content=ft.Row(
            [
                ft.Image(src="logo.png", width=150, fit=ft.ImageFit.CONTAIN),
                center_section,
                right_section 
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER
        )
    )

    # =================================================================
    #                       ÁREA DE CONTENIDO
    # =================================================================

    welcome_large = ft.Text("", size=40, weight=ft.FontWeight.W_200, color=SSA_GREY, text_align=ft.TextAlign.CENTER)
    loading_spinner = ft.ProgressRing(color=SSA_GREEN, width=50, height=50)
    status_text = ft.Text("", color=SSA_GREY, text_align=ft.TextAlign.CENTER)
    
    loading_container = ft.Container(
        content=ft.Column([
            welcome_large,
            ft.Container(height=20),
            loading_spinner,
            ft.Container(height=10), 
            status_text
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER), 
        alignment=ft.alignment.center, 
        expand=True, 
        visible=False,
        bgcolor=SSA_BG
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

    # --- MANAGER ---
    # Protegido por el catch global, pero su lógica interna usa @track_errors
    manager = DashboardManager(page, tabs, loading_container, status_text, welcome_large, user_name_small)
    
    # Botones de Acción Global
    calendar_button = manager.build_calendar_button()
    close_cycle_button = manager.build_close_cycle_button() 
    help_button = manager.build_help_button() # Nuevo Botón de Ayuda

    content_area = ft.Stack(
        [
            tabs,
            ft.Container(
                content=ft.Row([close_cycle_button, calendar_button, help_button], spacing=10),
                right=10, 
                top=5
            ),
            loading_container
        ],
        expand=True
    )

    main_layout = ft.Column(
        [header, content_area],
        expand=True,
        spacing=0,
        visible=False,
        opacity=0,
        animate_opacity=1000
    )

    # =================================================================
    #                 LÓGICA DE MONITOREO DE SESIÓN
    # =================================================================

    def handle_relogin(e, dialog_ref):
        """Intenta reconectar y refrescar la aplicación."""
        # Cerramos el diálogo modal
        page.close(dialog_ref)
        
        # Mostramos cargando mientras se autentica
        status_text.value = "Re-autenticando con Microsoft..."
        loading_container.visible = True
        page.update()

        if monitor.force_relogin():
            main_layout.disabled = False
            page.update()
            
            # Reiniciamos carga de datos y notificamos éxito
            manager.load_data(silent=True)
            manager.notifier.send("Sesión Restaurada", "Se ha vuelto a conectar con éxito.", "success")
        else:
            # Si falla el relogin (ej. canceló el navegador), volvemos a mostrar la alerta
            on_session_lost()

    def on_session_lost():
        """Se dispara cuando el monitor detecta que el token expiró."""
        # Bloqueamos la UI principal para que el usuario no siga intentando acciones que fallarán
        main_layout.disabled = True 
        page.update()
        
        # Creamos y mostramos un diálogo MODAL (más efectivo que un banner)
        relogin_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("⚠️ Conexión Perdida"),
            content=ft.Text(
                "Tu sesión de Microsoft ha expirado o se ha perdido la conexión a internet.\n"
                "Por favor, haz clic en 'Re-conectar' para autenticarte nuevamente y guardar tu trabajo."
            ),
            actions=[
                ft.ElevatedButton(
                    "Re-conectar", 
                    on_click=lambda e: handle_relogin(e, relogin_dialog),
                    bgcolor=SSA_GREEN,
                    color=SSA_WHITE
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        page.open(relogin_dialog)
        page.update()

    # Inicializamos el Sentinel
    monitor = SessionMonitor(on_session_lost_callback=on_session_lost)

    # =================================================================
    #                       SPLASH SCREEN
    # =================================================================
    
    intro_logo = ft.Image(src="Icono.png", width=80, height=80, opacity=0, animate_opacity=1000)
    intro_title = ft.Text("", size=30, weight=ft.FontWeight.BOLD, color=SSA_GREY, text_align=ft.TextAlign.CENTER, font_family="monospace", animate_opacity=500)
    intro_subtitle = ft.Text("", size=20, weight=ft.FontWeight.W_500, color=SSA_GREEN, text_align=ft.TextAlign.CENTER)

    splash_container = ft.Container(content=ft.Column([intro_logo, intro_title, intro_subtitle], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=20), alignment=ft.alignment.center, expand=True, bgcolor=SSA_BG, opacity=1, animate_opacity=800)
    
    page.add(ft.Stack([main_layout, splash_container], expand=True))

    # Animación Intro
    try:
        # NIVEL 2: PROTECCIÓN DE CICLO DE VIDA (INIT)
        intro_logo.opacity = 1; page.update(); time.sleep(0.8)
        full_text = "Centralized Automation for Request Operations & Logic"; current_text = ""
        for char in full_text: current_text += char; intro_title.value = current_text + "|"; page.update(); time.sleep(0.05) 
        intro_title.value = current_text; page.update(); time.sleep(0.2)
        sub_text = "By Global Business Services Mexico"; current_sub = ""
        for char in sub_text: current_sub += char; intro_subtitle.value = current_sub; page.update(); time.sleep(0.06)
        time.sleep(1.0); intro_title.opacity = 0; page.update(); time.sleep(0.5) 
        intro_title.value = "C.A.R.O.L"; intro_title.size = 40; intro_title.color = SSA_GREY; page.update()
        intro_title.opacity = 1; page.update(); time.sleep(2.0); splash_container.opacity = 0; page.update(); time.sleep(0.8)
        splash_container.visible = False; main_layout.visible = True; page.update(); main_layout.opacity = 1; page.update()

        # --- INICIO ---
        manager.start()
        monitor.start() # Iniciamos el vigilante de sesión
        manager.load_data(limit_dates=1)
        
    except Exception as e:
        # Captura errores fatales en la carga inicial
        print(f"🔥 FATAL ERROR IN MAIN: {e}")
        traceback.print_exc()
        # Intentar reportar
        try:
            from services.error_logger_service import ErrorLoggerService
            ErrorLoggerService().log_error(e, context_msg="Main Init Crash", user="System")
        except: pass
        
        # UI de emergencia si es posible
        page.clean()
        page.add(ft.Text(f"CRITICAL ERROR:\n{str(e)}", color="red", size=20))

if __name__ == "__main__":
    ft.app(target=main, assets_dir=assets_path)