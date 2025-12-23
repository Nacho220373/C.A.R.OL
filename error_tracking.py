import sys
import functools
import threading
import traceback
from services.error_logger_service import ErrorLoggerService

# Instancia global del logger (se inicializa al importar)
_logger = ErrorLoggerService()

def track_errors(context_message="Error in operation"):
    """
    Decorador para envolver métodos de clase o funciones.
    Captura excepciones, las loguea y notifica al usuario si 'self' tiene 'notifier'.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
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
                return None
        return wrapper
    return decorator

def setup_global_exception_handler():
    """
    Nivel 3: Catch-All definitivo.
    Atrapa errores no manejados que harían crashear la app.
    """
    def global_excepthook(exc_type, exc_value, exc_traceback):
        # Permitir interrupción de teclado (Ctrl+C)
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        print("🔥 CRITICAL UNHANDLED ERROR 🔥")
        traceback.print_exception(exc_type, exc_value, exc_traceback)
        
        # Loguear a SharePoint antes de morir
        try:
            _logger.log_error(exc_value, context_msg="CRITICAL CRASH (Excepthook)", user="System Crash")
        except:
            print("Could not log critical crash.")
        
    sys.excepthook = global_excepthook
    print("🛡️ Sistema de monitoreo de errores activo.")