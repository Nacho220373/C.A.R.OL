import threading
import time
from ms_graph_client import MSGraphClient

class SessionMonitor:
    """
    Componente Sentinel mejorado (SoC).
    Responsabilidad única: Vigilar la salud del token de MS Graph.
    Detecta activamente fallos en hilos secundarios.
    """
    def __init__(self, on_session_lost_callback):
        self.client = MSGraphClient()
        self.on_session_lost = on_session_lost_callback
        self.is_running = False
        self._consecutive_failures = 0
        self._max_failures = 1 # Disparo inmediato al detectar sesión muerta

    def start(self, interval=5): # <--- CAMBIO: Intervalo reducido a 5s para detección rápida
        """Monitorea la sesión con mayor frecuencia (cada 5 segundos)."""
        if self.is_running: return
        self.is_running = True
        threading.Thread(target=self._watch_loop, args=(interval,), daemon=True).start()

    def stop(self):
        self.is_running = False

    def _watch_loop(self, interval):
        while self.is_running:
            # Primero: Chequeo de banderas pasivas (¿falló el poller?)
            if not self.client.is_session_valid:
                print("🚨 Centinela detectó bandera de sesión inválida.")
                self._handle_failure()
                if not self.is_running: break

            # Segundo: Chequeo activo (Ping a Microsoft)
            try:
                # Una llamada ultra rápida a Graph
                status = self.client.get("/me")
                if status and 'error' not in status:
                    self._consecutive_failures = 0
                    self.client.is_session_valid = True
                else:
                    self._handle_failure()
            except Exception:
                self._handle_failure()
            
            time.sleep(interval)

    def _handle_failure(self):
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._max_failures:
            print("❌ Sesión declarada muerta por el Centinela.")
            self.is_running = False
            self.client.is_session_valid = False
            if self.on_session_lost:
                self.on_session_lost()

    def force_relogin(self):
        """Limpia el estado e invoca login interactivo."""
        self.client.access_token = None
        self.client.credential = None
        self.client.last_error_code = 0
        try:
            # Forzamos la obtención del token (esto abrirá el navegador)
            self.client._get_token()
            self._consecutive_failures = 0
            self.client.is_session_valid = True
            self.is_running = True # Reiniciar monitoreo
            return True
        except Exception as e:
            print(f"Error en relogin: {e}")
            return False