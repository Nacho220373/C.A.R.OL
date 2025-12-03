import threading
import flet as ft
from plyer import notification

class NotificationManager:
    """
    Servicio dedicado a manejar la comunicación con el usuario.
    Responsabilidad: Mostrar alertas visuales (App) y del sistema (OS).
    """
    def __init__(self, page: ft.Page):
        self.page = page

    def send(self, title: str, message: str, type: str = "info"):
        """
        Envía una notificación dual: Sistema Operativo y Snackbar en App.
        """
        # 1. Notificación de Escritorio (En hilo separado para no congelar la UI)
        threading.Thread(
            target=self._send_os_notification,
            args=(title, message),
            daemon=True
        ).start()

        # 2. Notificación en la App (Snackbar)
        self._show_in_app_snackbar(title, message, type)

    def _send_os_notification(self, title, message):
        try:
            notification.notify(
                title=title,
                message=message,
                app_name="C.A.R.O.L",
                app_icon="assets/app_icon.ico",  # Asegúrate de tener un .ico válido o quitar esta línea si falla
                timeout=10
            )
        except Exception as e:
            print(f"⚠️ Error enviando notificación de escritorio: {e}")

    def _show_in_app_snackbar(self, title, message, type):
        # Definir colores según el tipo
        bg_color = "#007AFF" # Azul por defecto
        if type == "success": bg_color = "#84BD00" # SSA Green
        elif type == "error": bg_color = "#FF3B30" # Rojo
        elif type == "warning": bg_color = "#FF9500" # Naranja

        snack_content = ft.Row([
            ft.Icon(ft.Icons.NOTIFICATIONS_ACTIVE, color="white"),
            ft.Column([
                ft.Text(title, weight="bold", color="white", size=14),
                ft.Text(message, color="white", size=12)
            ], spacing=2, alignment=ft.MainAxisAlignment.CENTER)
        ], alignment=ft.MainAxisAlignment.START)

        self.page.snack_bar = ft.SnackBar(
            content=snack_content,
            bgcolor=bg_color,
            behavior=ft.SnackBarBehavior.FLOATING,
            duration=5000,
            margin=ft.margin.all(20),
            action="Dismiss",
            action_color="white"
        )
        self.page.snack_bar.open = True
        self.page.update()