import os
import sys

class PathManager:
    """
    Controla centralizadamente las rutas para asegurar que:
    1. La APP corre desde la red (o carpeta de desarrollo).
    2. Los DATOS (Cookies, JSONs) se guardan en el PC local del usuario (%APPDATA%).
    """
    
    @staticmethod
    def get_app_root():
        """Devuelve la ruta donde está el ejecutable (Red) o el script (Dev)"""
        if getattr(sys, 'frozen', False):
            # Si es EXE, es la carpeta donde está el archivo .exe
            return os.path.dirname(sys.executable)
        else:
            # Si es Python normal, es la carpeta raíz del proyecto
            return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    @staticmethod
    def get_local_data_dir():
        r"""
        Devuelve la ruta local rápida y segura para datos de usuario.
        Ejemplo: C:\Users\Usuario\AppData\Roaming\CAROL
        """
        app_data = os.getenv('APPDATA')
        local_dir = os.path.join(app_data, "CAROL")
        
        if not os.path.exists(local_dir):
            try:
                os.makedirs(local_dir)
            except OSError:
                # Fallback por si acaso falla APPDATA
                return os.path.join(os.path.expanduser("~"), ".carol_data")
            
        return local_dir

    @staticmethod
    def get_assets_path():
        """Maneja los assets empaquetados dentro del EXE"""
        if getattr(sys, 'frozen', False):
            # PyInstaller descomprime los assets en una carpeta temporal _MEIPASS
            return os.path.join(sys._MEIPASS, "assets")
        else:
            return os.path.join(PathManager.get_app_root(), "assets")

    @staticmethod
    def get_env_path():
        """Busca el archivo .env siempre junto al ejecutable/script (Carpeta de RED)"""
        return os.path.join(PathManager.get_app_root(), ".env")

    @staticmethod
    def get_chrome_profile_path():
        """Ruta para guardar la sesión de Chrome en local (Velocidad máxima y evita conflictos)"""
        return os.path.join(PathManager.get_local_data_dir(), "adp_user_data")

    @staticmethod
    def get_user_prefs_path():
        """Ruta local para guardar preferencias (ej. Tour visto)"""
        return os.path.join(PathManager.get_local_data_dir(), "user_prefs.json")

    @staticmethod
    def get_notifications_history_path():
        """Ruta local para historial de notificaciones"""
        return os.path.join(PathManager.get_local_data_dir(), "notifications_history.json")