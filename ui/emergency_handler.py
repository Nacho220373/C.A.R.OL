import flet as ft
import traceback

class EmergencyHandler:
    """
    Gestor Global de Atajos de Emergencia.
    Ahora soporta un 'Hard Reset' Global que reconstruye toda la aplicación.
    """
    _listeners = []
    _global_reset_callback = None

    @classmethod
    def bind_global_reset(cls, callback):
        """Asigna la función maestra de reinicio (normalmente desde main.py)."""
        cls._global_reset_callback = callback
        print("🔧 Emergency Handler: Reset Global Vinculado.")

    @classmethod
    def register(cls, callback):
        """(Deprecado/Secundario) Registra listeners locales."""
        if callback not in cls._listeners:
            cls._listeners.append(callback)

    @classmethod
    def unregister(cls, callback):
        if callback in cls._listeners:
            cls._listeners.remove(callback)

    @classmethod
    def handle_event(cls, e: ft.KeyboardEvent, page: ft.Page):
        """Manejador central de eventos de teclado."""
        # Detectar F5 o Ctrl+R
        if e.key == "F5" or (e.key == "R" and e.ctrl):
            print("\n🚨 GLOBAL EMERGENCY RESET TRIGGERED (F5/Ctrl+R)")
            
            # 1. PRIORIDAD TOTAL: Si hay un reset global, úsalo y olvida lo demás.
            if cls._global_reset_callback:
                try:
                    print("   -> Ejecutando PROTOCOLO DE REINICIO GLOBAL...")
                    cls._global_reset_callback()
                    # Si el global funciona, no necesitamos ejecutar listeners locales
                    # porque la UI completa se va a destruir y regenerar.
                    return 
                except Exception as ex:
                    print(f"   🔥 CRITICAL FAILURE IN GLOBAL RESET: {ex}")
                    traceback.print_exc()
            
            # 2. Fallback (Comportamiento antiguo): Limpieza local si no hay global
            if page.dialog:
                try:
                    page.dialog.open = False
                    page.update()
                except: pass
                page.dialog = None
            
            for callback in cls._listeners:
                try: callback()
                except: pass

            try:
                page.snack_bar = ft.SnackBar(ft.Text("Vista reiniciada (Modo Local)."), bgcolor=ft.Colors.ORANGE_800)
                page.snack_bar.open = True
                page.update()
            except: pass