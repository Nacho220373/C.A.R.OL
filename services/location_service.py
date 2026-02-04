import pandas as pd
import io
import os
from ms_graph_client import MSGraphClient
from dotenv import load_dotenv

load_dotenv()

class LocationService:
    def __init__(self):
        self.client = MSGraphClient()
        self.site_id = os.getenv('SHAREPOINT_SITE_ID')
        # Ruta RELATIVA dentro de la librería "Documents"
        self.file_path = os.getenv('LOCATIONS_FILE_PATH', 'General/locations.xlsx')
        self.valid_locations = set()
        self.locations_db = [] # Lista para guardar objetos {code, display}
        self.drive_id = None

    def _get_drive_id(self):
        if self.drive_id: return self.drive_id
        
        endpoint = f"/sites/{self.site_id}/drives"
        drives = self.client.get(endpoint)
        
        if not drives: return None

        for drive in drives.get('value', []):
            if drive['name'] in ["Documents", "Shared Documents", "Documentos"]:
                self.drive_id = drive['id']
                return self.drive_id
        
        self.drive_id = drives['value'][0]['id']
        return self.drive_id

    def load_locations(self):
        """Descarga el Excel desde SharePoint y extrae Código (Col A) y Nombre (Col B)."""
        print("🌍 Cargando ubicaciones desde SharePoint...")
        drive_id = self._get_drive_id()
        if not drive_id:
            print("❌ No se encontró el Drive ID para cargar ubicaciones.")
            return

        # Limpiamos la ruta para que sea válida en la URL
        clean_path = self.file_path.strip("/")
        endpoint = f"/sites/{self.site_id}/drives/{drive_id}/root:/{clean_path}:/content"
        
        content_bytes = self.client.get_content(endpoint)
        
        if not content_bytes:
            print(f"❌ No se pudo descargar el archivo de ubicaciones: {self.file_path}")
            return

        try:
            # Leemos el Excel desde los bytes en memoria
            df = pd.read_excel(io.BytesIO(content_bytes), sheet_name="Locations")
            
            self.valid_locations = set()
            self.locations_db = []

            # Iteramos filas para extraer Col A (Código) y Col B (Nombre)
            for index, row in df.iterrows():
                try:
                    # Columna A (índice 0) -> Código
                    code_val = row.iloc[0]
                    code = str(code_val).strip()
                    # Si es vacío o 'nan', saltar
                    if not code or code.lower() == 'nan': continue
                    
                    # Columna B (índice 1) -> Nombre
                    name = ""
                    if len(row) > 1:
                        name_val = row.iloc[1]
                        if str(name_val).lower() != 'nan':
                            name = str(name_val).strip()
                    
                    # 1. Guardamos solo el código para validaciones lógicas
                    self.valid_locations.add(code)
                    
                    # 2. Guardamos el par {code, display} para la UI
                    # Resultado visual: "003 Norfolk"
                    display_text = f"{code} {name}".strip()
                    self.locations_db.append({"code": code, "display": display_text})
                    
                except Exception:
                    continue
            
            # Ordenamos por código para que la lista se vea limpia
            self.locations_db.sort(key=lambda x: x['code'])
            
            print(f"✅ Éxito: {len(self.valid_locations)} ubicaciones válidas cargadas desde hoja 'Locations'.")
            
        except Exception as e:
            print(f"❌ Error procesando el Excel de ubicaciones: {e}")

    def get_locations_for_generation(self):
        """
        Lee el Excel completo para generar las timecards.
        Filtra descripciones 'General' y retorna lista con PayGroup.
        """
        print("🌍 [Generation] Cargando datos maestros de ubicaciones...")
        drive_id = self._get_drive_id()
        if not drive_id: return []

        clean_path = self.file_path.strip("/")
        endpoint = f"/sites/{self.site_id}/drives/{drive_id}/root:/{clean_path}:/content"
        content_bytes = self.client.get_content(endpoint)
        
        if not content_bytes: return []

        try:
            # Leemos buscando encabezados específicos
            df = pd.read_excel(io.BytesIO(content_bytes), sheet_name="Locations")
            
            # Normalizar columnas (strip spaces)
            df.columns = df.columns.str.strip()
            
            # Búsqueda flexible de columnas
            col_code = next((c for c in df.columns if "location" in c.lower() and "code" in c.lower()), None)
            col_desc = next((c for c in df.columns if "description" in c.lower()), None)
            col_pg = next((c for c in df.columns if "pay" in c.lower() and "group" in c.lower()), None)
            
            if not (col_code and col_desc and col_pg):
                print(f"❌ Error: No se encontraron las columnas requeridas (Location Code, Description, Pay Group). Encontradas: {list(df.columns)}")
                return []

            results = []
            for _, row in df.iterrows():
                # Obtener descripción
                desc = str(row.get(col_desc, '')).strip()
                
                # FILTRO: Excluir si la descripción es "General"
                if "general" in desc.lower(): 
                    continue
                
                code = str(row.get(col_code, '')).strip()
                pg = str(row.get(col_pg, '')).strip()
                
                if code and code.lower() != 'nan':
                    results.append({
                        "code": code,
                        "description": desc,
                        "pay_group": pg
                    })
            
            print(f"✅ {len(results)} ubicaciones listas para generación (General excluido).")
            return results

        except Exception as e:
            print(f"❌ Error leyendo ubicaciones para generación: {e}")
            return []

    def is_valid(self, location_code):
        if not location_code: return False
        # Si la lista está vacía (error de carga), asumimos todo válido para no bloquear trabajo
        if not self.valid_locations: return True 
        return str(location_code).strip() in self.valid_locations

    def get_all_locations(self):
        """Retorna la lista rica de objetos para los Dropdowns."""
        if self.locations_db:
            return self.locations_db
        # Fallback seguro por si falló la carga extendida
        return [{"code": l, "display": l} for l in sorted(list(self.valid_locations))]