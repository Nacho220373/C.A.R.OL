# Mapeo entre nombres internos de SharePoint y nombres de nuestra App

COLUMN_MAP = {
    "status": "Status",
    "category": "Payroll_Category",
    "priority": "Priority_Level",
    
    "reply_limit": "Due_Date_SLO", 
    "resolve_limit": "Resolve_Time_Limit", 
    
    # --- NUEVAS COLUMNAS DE TIEMPO REAL ---
    "reply_time": "Reply_Time",      # Cuándo se respondió realmente
    "resolve_time": "Resolve_Time",  # Cuándo se resolvió realmente
    
    "created_at": "Created",
    "modified_at": "Modified",
    
    # NOMBRE CORREGIDO SEGÚN DIAGNÓSTICO
    "conversation_id": "ConversationID",  
    
    # Metadatos del sistema
    "item_count": "ItemChildCount", 
    "request_name": "FileLeafRef",
    
    # --- NUEVO CAMPO ---
    # En la API de Graph, "Modified By" se llama internamente "Editor"
    "editor": "Editor" 
}

# Valores esperados para prioridades
PRIORITY_MAP = {
    "1": "High",
    "2": "Medium-High",
    "3": "Medium-Low",
    "4": "Low"
}

# Valores para categorías
CATEGORY_MAP = {
    "Request": "Request",
    "Staff Movements": "Staff Movements",
    "Inquiry": "Inquiry",
    "Information": "Information"
}