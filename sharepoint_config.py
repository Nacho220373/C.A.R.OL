# Mapeo entre nombres internos de SharePoint y nombres de nuestra App
# CORREGIDO: Nombres reales obtenidos por diagnóstico de fuerza bruta

COLUMN_MAP = {
    "status": "Status",
    "category": "Payroll_Category",
    "priority": "Priority_Level",
    
    # ¡AQUÍ ESTABA EL CULPABLE!
    "reply_limit": "Due_Date_SLO", 
    
    "resolve_limit": "Resolve_Time_Limit", 
    
    "created_at": "Created",
    "modified_at": "Modified",
    
    # Metadatos del sistema
    "item_count": "ItemChildCount", 
    "request_name": "FileLeafRef"
}

# Valores esperados para prioridades
PRIORITY_MAP = {
    "1": "High",
    "2": "Medium-High",
    "3": "Medium-Low",
    "4": "Low"
}