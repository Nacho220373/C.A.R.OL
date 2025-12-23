import os
import json
from sharepoint_requests_reader import SharePointRequestsReader
from dotenv import load_dotenv

load_dotenv()

def diagnose_brute_force():
    print("🧨 MODO FUERZA BRUTA: MOSTRAR TODO...")
    reader = SharePointRequestsReader()
    
    # Ruta directa construida manualmente como pediste
    base_path = os.getenv('TARGET_FOLDER_PATH', '')
    # Ajusta si tu .env ya tiene una barra al final o no
    specific_path = f"{base_path.rstrip('/')}/20251212/847"
    
    print(f"📍 Analizando ruta específica: {specific_path}")
    
    # Obtenemos los elementos dentro de la carpeta 847 (que deberían ser las solicitudes)
    items = reader._get_items(path=specific_path)
    
    if not items:
        print("❌ No se encontraron elementos en esa carpeta o la ruta no existe.")
        print("Verifica que la fecha '20251212' y la loc '847' existan en SharePoint.")
        return

    # Tomamos el primer ítem para inspeccionar sus columnas
    target_item = items[0]
    print(f"\n🔎 ANALIZANDO PRIMER ÍTEM ENCONTRADO: '{target_item.get('name')}'")
    print("="*80)
    
    fields = target_item.get('listItem', {}).get('fields', {})
    
    found_candidates = []
    
    # Imprimimos TODO excepto basura del sistema
    for key, value in fields.items():
        if not key.startswith("odata") and not key.startswith("_"):
            print(f"🔸 [{key}]:  {value}")
            
            # Buscamos candidatos para Conversation ID (texto largo con caracteres raros)
            if isinstance(value, str) and len(value) > 20 and ("=" in value or "_" in value):
                found_candidates.append(key)

    print("="*80)
    
    if found_candidates:
        print(f"\n💡 POSIBLES NOMBRES PARA CONVERSATION ID: {found_candidates}")
        print("Copia el nombre que está entre corchetes [] y pégalo en sharepoint_config.py")
    else:
        print("\n⚠️ No vi nada parecido a un ID largo. Revisa la lista manualmente.")

if __name__ == "__main__":
    diagnose_brute_force()