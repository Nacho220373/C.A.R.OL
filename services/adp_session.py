import threading
import time
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from services.cleanup_service import CleanupService  # Importamos el servicio
import logging
from services.path_manager import PathManager # Importamos el gestor de rutas

class ADPSession:
    """
    MASTER CONTROLLER (Singleton)
    Responsabilidad Única: Infraestructura del Navegador.
    Gestiona el ciclo de vida, mantiene el navegador abierto y detecta el contexto.
    Incluye: PERSISTENCIA DE PERFIL (Memoria) y GESTIÓN DE PESTAÑAS.
    """
    _instance = None
    _lock = threading.Lock()
    
    ADP_DASHBOARD_URL = "https://my.adp.com/?legacySOR=Vantage#/dashboard/main?npcr=true"

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ADPSession, cls).__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized: return
        self._initialized = True
        self.driver = None
        self.logger = logging.getLogger("ADPSession")
        
        # Mantenemos descargas en carpeta local del usuario (esto estaba OK)
        self.download_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        
        # CAMBIO CRÍTICO: Usar PathManager para el perfil de Chrome
        # Esto asegura que apunte a %APPDATA%/CAROL/adp_user_data, seguro para redes.
        self.user_data_dir = PathManager.get_chrome_profile_path()
        
        # Variable para trackear la pestaña de ADP
        self.adp_tab_handle = None

    def get_driver(self):
        """Devuelve la instancia activa del driver o lanza una nueva si murió."""
        if self.driver:
            try:
                # Ping ligero para ver si la ventana sigue viva
                _ = self.driver.window_handles
                return self.driver
            except Exception:
                self.logger.warning("⚠️ Navegador detectado muerto o desconectado. Reiniciando instancia...")
                self.driver = None
                self.adp_tab_handle = None # Reset handle
        
        return self._launch_browser()

    def _launch_browser(self):
        """Lanza un nuevo proceso de Chrome con memoria persistente."""
        print("🔧 (Master) Inicializando nuevo navegador Chrome con Persistencia...")
        
        if not os.path.exists(self.user_data_dir):
            try: os.makedirs(self.user_data_dir)
            except: pass

        options = Options()
        options.add_argument("--start-maximized")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        
        # Persistencia de usuario
        options.add_argument(f"user-data-dir={self.user_data_dir}")
        
        prefs = {
            "download.default_directory": self.download_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
            "profile.default_content_setting_values.automatic_downloads": 1
        }
        options.add_experimental_option("prefs", prefs)
        
        # IMPORTANTE: Mantenemos detach=True para que no se cierre solo si falla el script,
        # pero usaremos el cleanup_service para cerrarlo ordenadamente al salir de la App.
        options.add_experimental_option("detach", True) 

        try:
            self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
            
            # --- NUEVA LÓGICA DE PID (INICIO) ---
            # Solo agregamos esto para registrar el proceso
            if self.driver.service.process:
                pid = self.driver.service.process.pid
                CleanupService.register_pid(pid)
                print(f"🔐 [Session] Chrome PID {pid} registrado para limpieza.")
            # --- NUEVA LÓGICA DE PID (FIN) ---
            
            return self.driver
        except Exception as e:
            print(f"❌ Error lanzando navegador: {e}")
            if "user-data-dir" in str(e):
                print("⚠️ Falló carga de perfil (Bloqueado). Intentando modo incógnito de emergencia...")
                try:
                    options = Options()
                    options.add_experimental_option("detach", True)
                    self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
                    
                    # --- NUEVA LÓGICA DE PID (EMERGENCIA) ---
                    if self.driver.service.process:
                        pid = self.driver.service.process.pid
                        CleanupService.register_pid(pid)
                        print(f"🔐 [Session] Chrome PID {pid} (Emergency) registrado.")
                    # ----------------------------------------

                    return self.driver
                except: pass
            return None

    def focus_browser(self):
        """Intenta traer la ventana al frente."""
        if self.driver:
            try:
                self.driver.minimize_window()
                self.driver.maximize_window()
            except: pass

    def ensure_dashboard_context(self):
        """
        Gestión Inteligente de Pestañas y Contexto.
        """
        driver = self.get_driver()
        if not driver: return False, "BrowserLaunchFailed"
        
        try:
            current_handles = driver.window_handles
            
            # 1. Recuperar o Asignar Pestaña de Trabajo (ADP Tab)
            if self.adp_tab_handle and self.adp_tab_handle in current_handles:
                driver.switch_to.window(self.adp_tab_handle)
            else:
                # ESTRATEGIA: Si solo hay 1 pestaña (la corporativa), abrimos una nueva
                if len(current_handles) == 1:
                    print("📑 (Master) Abriendo segunda pestaña limpia para ADP...")
                    driver.execute_script("window.open('about:blank', '_blank');")
                    time.sleep(0.5)
                    current_handles = driver.window_handles 
                    self.adp_tab_handle = current_handles[-1] 
                    driver.switch_to.window(self.adp_tab_handle)
                    driver.get(self.ADP_DASHBOARD_URL)
                
                else:
                    # Buscar si alguna es ADP
                    found = False
                    for h in current_handles:
                        driver.switch_to.window(h)
                        if "my.adp.com" in driver.current_url:
                            self.adp_tab_handle = h
                            found = True
                            break
                    
                    if not found:
                        self.adp_tab_handle = current_handles[-1]
                        driver.switch_to.window(self.adp_tab_handle)
            
            # 2. Verificar Estado
            current_url = driver.current_url.lower()
            
            is_login = any(k in current_url for k in ["login", "signin", "oauth", "authorize"])
            is_expired = "sessionlogoff" in current_url
            
            if is_login or is_expired:
                return False, "LoginRequired"

            if "my.adp.com" in current_url:
                return True, "ActiveSession"

            print("🧭 (Master) Navegando a ADP Dashboard...")
            driver.get(self.ADP_DASHBOARD_URL)
            self.focus_browser()
            time.sleep(3)
            
            current_url = driver.current_url.lower()
            if any(k in current_url for k in ["login", "signin", "oauth", "authorize", "sessionlogoff"]):
                return False, "LoginRequired"
            
            return True, "Ready"

        except Exception as e:
            print(f"❌ (Master) Error de contexto: {e}")
            try: driver.quit() 
            except: pass
            self.driver = None
            self.adp_tab_handle = None
            return False, "ContextError"

    def close(self):
        """Cierra el navegador y libera el recurso."""
        if self.driver:
            try: 
                print("🛑 (Master) Cerrando instancia de Chrome...")
                self.driver.quit()
            except: pass
            self.driver = None
            self.adp_tab_handle = None