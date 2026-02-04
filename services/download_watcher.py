import os
import time
import threading
from datetime import datetime

class DownloadWatcherService:
    """
    Servicio que monitorea la carpeta de descargas del usuario buscando
    reportes específicos (PDFs) generados por ADP.
    """
    def __init__(self, processing_callback=None):
        self.download_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        self._watching = False
        self._target_pc = None
        self._target_loc = None
        # Guardamos el callback global por si se necesita, aunque TimecardView usará el suyo propio
        self._callback = processing_callback 
        self._monitor_thread = None

    def start(self):
        """
        Método de compatibilidad para main.py. 
        En la nueva arquitectura, el watcher se inicia realmente cuando la UI solicita 'expect_report'.
        """
        print("⚠️ [DownloadWatcher] Servicio inicializado en modo espera. Aguardando tarea de Timecard...")

    def expect_report(self, pc_number, location, on_found_callback=None):
        """
        Configura el watcher para esperar un reporte específico.
        
        Args:
            pc_number (str): Número de PC a buscar.
            location (str): Ubicación (contexto).
            on_found_callback (callable): Función a ejecutar al encontrar el archivo.
        """
        print(f"👀 Watcher ARMADO para PC: {pc_number}")
        self._target_pc = str(pc_number)
        self._target_loc = location
        # Priorizamos el callback específico de la tarea, si no hay, usamos el global
        self._callback = on_found_callback if on_found_callback else self._callback
        self._watching = True
        
        # Reiniciar hilo si ya existe o iniciar uno nuevo
        if self._monitor_thread and self._monitor_thread.is_alive():
            return 
            
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop(self):
        """Detiene el monitoreo."""
        self._watching = False
        self._target_pc = None
        print("🛑 Watcher detenido.")

    def _monitor_loop(self):
        """Bucle principal de monitoreo."""
        print("🕵️‍♂️ Iniciando vigilancia de descargas...")
        
        # Marcamos el tiempo de inicio para ignorar archivos viejos
        start_time = time.time()
        
        while self._watching:
            try:
                # Buscar archivo candidato
                found_path = self._scan_for_file(start_time)
                
                if found_path:
                    print(f"🎯 ¡ARCHIVO ENCONTRADO! -> {found_path}")
                    
                    # Esperar un momento para asegurar que la descarga terminó (escritura finalizada)
                    self._wait_for_write_finish(found_path)
                    
                    # Ejecutar callback
                    if self._callback:
                        try:
                            self._callback(found_path)
                        except Exception as e:
                            print(f"❌ Error ejecutando callback del watcher: {e}")
                    
                    # Detener vigilancia una vez encontrado (One-shot)
                    self._watching = False
                    self._target_pc = None
                    break
                    
            except Exception as e:
                print(f"⚠️ Error en bucle de watcher: {e}")
            
            time.sleep(2) # Revisar cada 2 segundos

    def _scan_for_file(self, start_timestamp):
        """Busca archivos recientes que coincidan con el patrón esperado."""
        if not self._target_pc: return None
        
        try:
            files = os.listdir(self.download_dir)
            candidates = []
            
            for f in files:
                # Ignorar archivos temporales o de sistema
                if f.endswith('.crdownload') or f.endswith('.tmp') or f.startswith('~$'):
                    continue
                
                full_path = os.path.join(self.download_dir, f)
                if not os.path.isfile(full_path):
                    continue

                # Criterio 1: Modificado DESPUÉS de que armamos el watcher
                mtime = os.path.getmtime(full_path)
                if mtime < start_timestamp:
                    continue
                
                # Criterio 2: Nombre coincide
                name_lower = f.lower()
                target_pc_clean = self._target_pc.replace("-", "") 
                
                # Patrones comunes de reportes de ADP
                is_match = (
                    ("punc" in name_lower and "detail" in name_lower) or 
                    (target_pc_clean in name_lower) or
                    ("report" in name_lower and ".pdf" in name_lower) 
                )
                
                if is_match and f.lower().endswith('.pdf'):
                    candidates.append((full_path, mtime))
            
            # Si hay candidatos, devolver el más reciente
            if candidates:
                candidates.sort(key=lambda x: x[1], reverse=True)
                return candidates[0][0]
                
        except Exception as e:
            pass
            
        return None

    def _wait_for_write_finish(self, file_path, timeout=5):
        """Espera a que el tamaño del archivo se estabilice (descarga completa)."""
        start_size = -1
        retries = 0
        while retries < timeout:
            try:
                current_size = os.path.getsize(file_path)
                if current_size == start_size and current_size > 0:
                    return # Tamaño estable
                start_size = current_size
            except:
                pass
            time.sleep(1)
            retries += 1