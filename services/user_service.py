from ms_graph_client import MSGraphClient

class UserService:
    """
    Servicio dedicado a obtener información del perfil del usuario actual.
    Cumple con SRP (Single Responsibility Principle).
    """
    def __init__(self):
        self.client = MSGraphClient()

    def get_current_user(self):
        """
        Obtiene el perfil del usuario logueado (Me).
        Retorna un diccionario con 'displayName', 'givenName', 'mail', etc.
        """
        # Endpoint estándar de Graph para "Mi Perfil"
        endpoint = "/me"
        try:
            user_data = self.client.get(endpoint)
            if user_data and 'error' not in user_data:
                return user_data
            return None
        except Exception as e:
            print(f"⚠️ Error obteniendo usuario: {e}")
            return None