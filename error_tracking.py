import sys
import functools
import threading
import traceback
from services.error_logger_service import ErrorLoggerService

# Instancia global del logger
_logger = ErrorLoggerService()

def track_errors(context_message="Error in operation"):
    """
    Decorador para envolver métodos críticos.
    Garantiza que cualquier excepción sea capturada, logueada local y remotamente.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
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
                
                return None
        return wrapper
    return decorator

def setup_global_exception_handler():
    """
    Capa final de seguridad para errores no atrapados (Crashes).
    """
    def global_excepthook(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

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