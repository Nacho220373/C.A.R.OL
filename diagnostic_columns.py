import os
import json
from sharepoint_requests_reader import SharePointRequestsReader
from dotenv import load_dotenv

load_dotenv()

def diagnose_brute_force():
    print("🧨 MODO FUERZA BRUTA: MOSTRAR TODO...")
    reader = SharePointRequestsReader()
    
    # Ruta directa a la carpeta 911
    base_path = os.getenv('TARGET_FOLDER_PATH', '')
    specific_path = f"{base_path.rstrip('/')}/20251205/911"
    
    print(f"📍 Analizando carpeta: {specific_path}")
    items = reader._get_items(path=specific_path)
    
    if not items:
        print("❌ No se encontraron elementos.")
        return

    # Buscamos ESPECÍFICAMENTE la carpeta que modificaste en la foto
    target_name = "Re- Michael Hlavach vacation hours not paid"
    target_item = None
    
    for item in items:
        fields = item.get('listItem', {}).get('fields', {})
        if fields.get('FileLeafRef') == target_name:
            target_item = item
            break
    
    if not target_item:
        print(f"❌ No encontré la carpeta '{target_name}'.")
        print("Listando lo que sí encontré por si acaso:")
        for i in items:
            print(f" - {i.get('listItem', {}).get('fields', {}).get('FileLeafRef')}")
        return

    print(f"\n✅ CARPETA ENCONTRADA: {target_name}")
    print("👇 AQUÍ ESTÁN TODOS LOS CAMPOS QUE TIENE (BUSCA TU DATO AQUÍ):")
    print("="*60)
    
    fields = target_item.get('listItem', {}).get('fields', {})
    
    # Imprimimos TODO excepto basura del sistema
    for key, value in fields.items():
        if not key.startswith("odata") and not key.startswith("_") and value:
            # Resaltamos si parece una fecha o texto largo
            print(f"🔸 [{key}]:  {value}")

    print("="*60)
    print("🔎 INSTRUCCIONES:")
    print("1. Busca en la lista de arriba el valor que esperas (ej. una fecha y hora futura).")
    print("2. El nombre que está entre corchetes [] a la izquierda de ese valor ES EL NOMBRE REAL.")
    print("3. Copia ese nombre y ponlo en sharepoint_config.py")

if __name__ == "__main__":
    diagnose_brute_force()