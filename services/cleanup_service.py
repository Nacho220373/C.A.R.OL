import os
import signal
import subprocess
import psutil
import logging

class CleanupService:
    """
    Servicio de limpieza robusto (Strategy: Hide & Kill + PID Locking).
    Se encarga de terminar procesos huérfanos de Chrome/WebDriver para evitar
    el error 'SessionNotCreatedException' y liberar recursos.
    """
    _registered_pids = set()

    @classmethod
    def register_pid(cls, pid):
        """Registra un PID específico para ser terminado al cerrar."""
        if pid:
            cls._registered_pids.add(pid)
            print(f"🧹 [Cleanup] Proceso registrado para limpieza: {pid}")

    @classmethod
    def cleanup(cls, force_all=False):
        """
        Ejecuta la rutina de limpieza.
        1. Intenta matar los PIDs registrados específicamente.
        2. (Opcional) Si force_all=True, barre con todos los chrome.exe/chromedriver.exe (Plan C).
        """
        print("🧹 [Cleanup] Iniciando rutina de limpieza...")

        # 1. Matar PIDs específicos (Cirugía)
        if cls._registered_pids:
            for pid in list(cls._registered_pids):
                cls._kill_pid(pid)
            cls._registered_pids.clear()
        
        # 2. Matar Drivers huérfanos (Siempre es seguro matar chromedriver.exe)
        cls._kill_by_name("chromedriver.exe")

        # 3. Limpieza preventiva agresiva (Solo si se solicita explícitamente)
        if force_all:
            print("⚠️ [Cleanup] Ejecutando limpieza agresiva de Chrome...")
            cls._kill_by_name("chrome.exe")

    @staticmethod
    def _kill_pid(pid):
        """Mata un proceso por su PID usando taskkill /F (Windows)."""
        try:
            # Verificamos si existe antes de disparar
            if psutil.pid_exists(pid):
                # Usamos subprocess con CREATE_NO_WINDOW para que sea silencioso
                subprocess.Popen(
                    f"taskkill /F /PID {pid} /T", 
                    shell=True, 
                    stdout=subprocess.DEVNULL, 
                    stderr=subprocess.DEVNULL
                )
                print(f"💀 [Cleanup] PID {pid} eliminado.")
            else:
                pass # Ya estaba muerto
        except Exception as e:
            print(f"⚠️ Error matando PID {pid}: {e}")

    @staticmethod
    def _kill_by_name(process_name):
        """Mata procesos por nombre usando taskkill /F."""
        try:
            subprocess.Popen(
                f"taskkill /F /IM {process_name} /T", 
                shell=True, 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL
            )
        except Exception:
            pass

    @classmethod
    def register(cls):
        """Registra el cleanup en atexit (Red de seguridad)."""
        import atexit
        atexit.register(lambda: cls.cleanup())