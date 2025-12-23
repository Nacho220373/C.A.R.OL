import os
import subprocess
import winreg
import time
import threading

class OutlookLegacyService:
    """
    Servicio de contingencia para abrir correos utilizando Outlook Clásico.
    Manipula temporalmente el registro de Windows para evitar forzar Outlook New (PWA).
    Responsabilidad (SRP): Interacción de bajo nivel con el SO y Outlook.
    """
    
    REG_PATH = r"Software\Microsoft\Office\16.0\Outlook\Preferences"
    REG_VALUE_NAME = "UseNewOutlook"

    def __init__(self):
        self._outlook_exe_path = None

    def _find_outlook_executable(self):
        """Busca la ruta de OUTLOOK.EXE en lugares estándar y claves de registro."""
        if self._outlook_exe_path and os.path.exists(self._outlook_exe_path):
            return self._outlook_exe_path

        # 1. Búsqueda por Registro (Más fiable)
        rutas_registro = [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE",
            r"SOFTWARE\Microsoft\Office\16.0\Outlook\InstallRoot"
        ]
        
        for ruta_clave in rutas_registro:
            try:
                # Intentamos leer tanto en HKEY_LOCAL_MACHINE normal como en WOW6432Node (para Office 32-bit en OS 64-bit)
                for hkey_base in [winreg.HKEY_LOCAL_MACHINE]: # Podríamos agregar más flags si fuera necesario
                    try:
                        clave = winreg.OpenKey(hkey_base, ruta_clave)
                        valor, _ = winreg.QueryValueEx(clave, "Path" if "InstallRoot" in ruta_clave else "")
                        winreg.CloseKey(clave)
                        
                        exe = os.path.join(valor, "OUTLOOK.EXE") if "OUTLOOK.EXE" not in str(valor).upper() else valor
                        if os.path.exists(exe):
                            self._outlook_exe_path = exe
                            return exe
                    except: continue
            except: continue
        
        # 2. Rutas comunes (Fallback)
        rutas_comunes = [
            r"C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE",
            r"C:\Program Files (x86)\Microsoft Office\root\Office16\OUTLOOK.EXE",
            r"C:\Program Files\Microsoft Office\Office16\OUTLOOK.EXE",
            r"C:\Program Files (x86)\Microsoft Office\Office16\OUTLOOK.EXE"
        ]
        for r in rutas_comunes:
            if os.path.exists(r):
                self._outlook_exe_path = r
                return r
                
        return None

    def _manage_registry(self, action, saved_value=None):
        """
        Manipula el switch 'UseNewOutlook' en el registro.
        action: 'read', 'disable_new', 'restore'
        """
        try:
            # HKEY_CURRENT_USER es seguro de modificar sin permisos de admin elevados en la mayoría de casos empresariales
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.REG_PATH, 0, winreg.KEY_ALL_ACCESS)
        except FileNotFoundError:
            # Si la clave no existe, asumimos que no hay bloqueo de New Outlook o no se puede modificar
            return 0
        except Exception as e:
            print(f"⚠️ Error accediendo al registro: {e}")
            return 0

        try:
            if action == 'read':
                try:
                    val, _ = winreg.QueryValueEx(key, self.REG_VALUE_NAME)
                    return val
                except FileNotFoundError:
                    return 0 # Por defecto asumimos 0 si no existe

            elif action == 'disable_new':
                # Forzamos 0 (Clásico)
                winreg.SetValueEx(key, self.REG_VALUE_NAME, 0, winreg.REG_DWORD, 0)

            elif action == 'restore':
                if saved_value is not None:
                    winreg.SetValueEx(key, self.REG_VALUE_NAME, 0, winreg.REG_DWORD, saved_value)
        
        except Exception as e:
            print(f"⚠️ Error manipulando valor de registro: {e}")
        finally:
            winreg.CloseKey(key)

    def launch_classic(self, file_path):
        """
        Orquesta el lanzamiento seguro:
        1. Guarda estado actual.
        2. Fuerza modo clásico.
        3. Lanza proceso.
        4. Restaura estado (Siempre).
        """
        outlook_exe = self._find_outlook_executable()
        if not outlook_exe:
            return False, "Outlook Classic executable not found."

        if not os.path.exists(file_path):
            return False, "File path does not exist."

        print(f"🚑 Iniciando protocolo de emergencia para: {os.path.basename(file_path)}")
        original_state = self._manage_registry('read')
        
        try:
            # 1. Hack
            self._manage_registry('disable_new')
            # Pequeña pausa para que el sistema 'sienta' el cambio
            time.sleep(0.5)
            
            # 2. Lanzamiento con flag /eml explícito
            # El flag /eml fuerza a Outlook a tratar el archivo como un correo suelto
            subprocess.Popen([outlook_exe, '/eml', file_path])
            
            # Esperamos un poco para asegurar que Outlook lea la config al arrancar
            time.sleep(3) 
            
            return True, "Launched in Classic Mode."

        except Exception as e:
            return False, str(e)
        
        finally:
            # 3. Restauración (CRÍTICO: Esto debe ejecutarse siempre)
            self._manage_registry('restore', original_state)
            print("✅ Configuración de registro restaurada.")