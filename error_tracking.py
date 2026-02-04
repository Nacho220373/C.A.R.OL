import sys
import functools
import threading
import traceback
from services.error_logger_service import ErrorLoggerService

<<<<<<< HEAD
# Instancia global del logger
=======
# Instancia global del logger (se inicializa al importar)
>>>>>>> 050048a87e330291b783c1b91c5b654cf7c42826
_logger = ErrorLoggerService()

def track_errors(context_message="Error in operation"):
    """
<<<<<<< HEAD
    Decorador para envolver métodos críticos.
    Garantiza que cualquier excepción sea capturada, logueada local y remotamente.
=======
    Decorador para envolver métodos de clase o funciones.
    Captura excepciones, las loguea y notifica al usuario si 'self' tiene 'notifier'.
>>>>>>> 050048a87e330291b783c1b91c5b654cf7c42826
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
<<<<<<< HEAD
                # 1. Identificación del usuario
                user_name = "Unknown"
                if args and hasattr(args[0], 'current_user') and args[0].current_user:
                    user_name = args[0].current_user.get('displayName', 'Unknown')
                
                # 2. Logueo Robusto (Local + Nube)
                error_ctx = f"{context_message} ({func.__name__})"
                _logger.log_error(e, context_msg=error_ctx, user=user_name)
                
                # 3. Notificación UI (No intrusiva)
                if args and hasattr(args[0], 'notifier'):
                    try:
                        args[0].notifier.send("Application Error", "An error occurred and has been logged.", "error")
                    except: pass
                
                # 4. Consola (Debug)
                print(f"❌ [TRACKED ERROR] {error_ctx}: {e}")
                traceback.print_exc()
                
=======
                # 1. Loguear silenciosamente en background
                user_name = "Unknown"
                
                # Intentar extraer usuario de 'self' (args[0]) si es una clase DashboardManager
                if args and hasattr(args[0], 'current_user') and args[0].current_user:
                    user_name = args[0].current_user.get('displayName', 'Unknown')
                
                # Llamada al servicio
                _logger.log_error(e, context_msg=f"{context_message} ({func.__name__})", user=user_name)
                
                # 2. Notificar UI si es posible
                if args and hasattr(args[0], 'notifier'):
                    try:
                        args[0].notifier.send("Application Error", f"Something went wrong. We are fixing it.\nDetails: {str(e)[:50]}...", "error")
                    except:
                        pass
                
                # 3. Importante: Imprimir en consola local para debug en desarrollo
                print(f"❌ EXCEPTION CAUGHT BY DECORATOR: {e}")
                traceback.print_exc()
                
                # No relanzamos el error para no crashear la UI, a menos que sea crítico
                # Retornamos None
>>>>>>> 050048a87e330291b783c1b91c5b654cf7c42826
                return None
        return wrapper
    return decorator

def setup_global_exception_handler():
    """
<<<<<<< HEAD
    Capa final de seguridad para errores no atrapados (Crashes).
    """
    def global_excepthook(exc_type, exc_value, exc_traceback):
=======
    Nivel 3: Catch-All definitivo.
    Atrapa errores no manejados que harían crashear la app.
    """
    def global_excepthook(exc_type, exc_value, exc_traceback):
        # Permitir interrupción de teclado (Ctrl+C)
>>>>>>> 050048a87e330291b783c1b91c5b654cf7c42826
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

<<<<<<< HEAD
        print("\n🔥 CRITICAL UNHANDLED CRASH 🔥")
        traceback.print_exception(exc_type, exc_value, exc_traceback)
        
        # Intento de logueo final
        try:
            _logger.log_error(exc_value, context_msg="CRITICAL APP CRASH (Uncaught)", user="System Crash")
            
            # Damos un pequeño respiro al thread de logging para intentar escribir en disco/red
            import time
            time.sleep(1.0) 
        except:
            print("Failed to log critical crash.")
        
    sys.excepthook = global_excepthook
    print("🛡️ Sistema de monitoreo de errores activo (Modo: Local + Cloud).")
=======
        print("🔥 CRITICAL UNHANDLED ERROR 🔥")
        traceback.print_exception(exc_type, exc_value, exc_traceback)
        
        # Loguear a SharePoint antes de morir
        try:
            _logger.log_error(exc_value, context_msg="CRITICAL CRASH (Excepthook)", user="System Crash")
        except:
            print("Could not log critical crash.")
        
    sys.excepthook = global_excepthook
    print("🛡️ Sistema de monitoreo de errores activo.")
>>>>>>> 050048a87e330291b783c1b91c5b654cf7c42826
