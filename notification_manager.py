import flet as ft
import threading
import os
import sys
import json
import uuid
from datetime import datetime
from plyer import notification
from services.path_manager import PathManager

class NotificationManager:
    """
    Gestor centralizado de notificaciones.
    1. Notificaciones Nativas (Toast OS).
    2. SnackBar (Visual App).
    3. Historial Persistente (JSON) - CON FILTRO DE RELEVANCIA.
    """
    # Usamos ruta dinámica por usuario para evitar conflictos en red
    MAX_HISTORY = 50 

    def __init__(self, page: ft.Page):
        self.page = page
        self.notification_center = None 
        # Cargar ruta desde PathManager
        self.HISTORY_FILE = PathManager.get_notifications_history_path()
        self.history = self._load_history()

    def set_visual_center(self, center_instance):
        """Conecta con el componente visual para actualizar el badge."""
        self.notification_center = center_instance
        self._update_badge()

    def _load_history(self):
        if os.path.exists(self.HISTORY_FILE):
            try:
                with open(self.HISTORY_FILE, 'r') as f:
                    return json.load(f)
            except: return []
        return []

    def _save_history(self):
        try:
            if len(self.history) > self.MAX_HISTORY:
                self.history = self.history[:self.MAX_HISTORY]
            
            # Asegurar directorio antes de guardar
            os.makedirs(os.path.dirname(self.HISTORY_FILE), exist_ok=True)
            
            with open(self.HISTORY_FILE, 'w') as f:
                json.dump(self.history, f)
            
            self._update_badge()
        except Exception as e:
            print(f"Error guardando historial notificaciones: {e}")

    def _update_badge(self):
        if self.notification_center:
            unread = sum(1 for n in self.history if not n.get('read', False))
            self.notification_center.update_badge(unread)
            self.notification_center.refresh_list()

    def send(self, title, message, type="info"):
        """
        Envía notificación y decide inteligentemente si guardarla en el historial.
        """
        # --- FILTRO DE RELEVANCIA (LÓGICA NUEVA) ---
        # Solo guardamos en el historial lo que aporta valor a largo plazo (Novedades).
        # Descartamos ruido operativo (Calculando, Errores transitorios, Guardado).
        
        should_save = False
        t_lower = title.lower()
        
        # 1. Whitelist: Lo que SIEMPRE queremos en el centro de notificaciones
        if "new" in t_lower: should_save = True       # "New Item", "New Email" (Tu prioridad)
        if "cycle" in t_lower: should_save = True     # "Cycle Closed"
        if "reloaded" in t_lower: should_save = True  # "System Reloaded"
        if "emergency" in t_lower: should_save = True # "Emergency Mode"
        
        # 2. Blacklist: Lo que explícitamente NO queremos (aunque contenga palabras clave)
        # Esto asegura que "Error calculating" o similares no entren.
        if "calculating" in t_lower: should_save = False
        if "saving" in t_lower or "saved" in t_lower: should_save = False
        if "error" in t_lower or "failed" in t_lower: should_save = False # Evita el spam de errores de conexión/scripts
        
        if should_save:
            new_notif = {
                "id": str(uuid.uuid4()),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "title": title,
                "message": message,
                "type": type,
                "read": False
            }
            self.history.insert(0, new_notif)
            self._save_history()

        # --- FEEDBACK VISUAL (Siempre se ejecuta) ---
        # El usuario aún ve el popup momentáneo para saber que algo pasa, 
        # pero no ensucia su bandeja de entrada.
        
        icon = ft.Icons.INFO_OUTLINE
        color = ft.Colors.BLUE
        
        if type == "success":
            icon = ft.Icons.CHECK_CIRCLE_OUTLINE
            color = ft.Colors.GREEN
        elif type == "error":
            icon = ft.Icons.ERROR_OUTLINE
            color = ft.Colors.RED
        elif type == "warning":
            icon = ft.Icons.WARNING_AMBER_ROUNDED
            color = ft.Colors.ORANGE

        threading.Thread(target=self._send_native, args=(title, message), daemon=True).start()
        self._show_in_app_snackbar(title, message, icon, color)

    def mark_all_read(self):
        for n in self.history:
            n['read'] = True
        self._save_history()

    def mark_as_read(self, notif_id):
        for n in self.history:
            if n['id'] == notif_id:
                n['read'] = True
                break
        self._save_history()

    def delete_notification(self, notif_id):
        self.history = [n for n in self.history if n['id'] != notif_id]
        self._save_history()

    def clear_all_history(self):
        self.history = []
        self._save_history()

    def _send_native(self, title, message):
        try:
            # Usar PathManager para obtener la ruta de assets (Funciona en EXE y Dev)
            icon_path = os.path.join(PathManager.get_assets_path(), "app_icon.ico")
            if not os.path.exists(icon_path): icon_path = None

            notification.notify(
                title=title,
                message=message,
                app_name="C.A.R.O.L",
                app_icon=icon_path, 
                timeout=5
            )
        except Exception as e:
            print(f"⚠️ Error enviando notificación de escritorio: {e}")

    def _show_in_app_snackbar(self, title, message, icon, color):
        try:
            snack = ft.SnackBar(
                content=ft.Row([
                    ft.Icon(icon, color=ft.Colors.WHITE),
                    ft.Column([
                        ft.Text(title, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                        ft.Text(message, color=ft.Colors.WHITE, size=12)
                    ], spacing=2, expand=True)
                ], alignment=ft.MainAxisAlignment.START),
                bgcolor=color,
                duration=4000,
            )
            self.page.overlay.append(snack) 
            snack.open = True
            self.page.update()
        except Exception as e:
            print(f"Error mostrando snackbar: {e}")