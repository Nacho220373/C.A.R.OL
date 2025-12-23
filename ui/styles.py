import flet as ft

# --- SSA MARINE STYLE GUIDE ---
SSA_GREEN = "#84BD00"
SSA_GREY = "#59595B"
SSA_BG = "#f0f2f5"
SSA_WHITE = "#ffffff"
SSA_BORDER = "#e0e0e0"
SSA_RED_BADGE = "#FF3B30" 
SSA_LIGHT_GREEN = "#f4f9e5"
SSA_BLUE_NOTIF = "#007AFF"

# --- HELPER FUNCTIONS FOR COLORS ---
def get_status_color(status):
    if not status: return ft.Colors.GREY
    status = str(status).lower()
    if "done" in status or "completed" in status: return SSA_GREEN
    elif "progress" in status: return ft.Colors.BLUE
    elif "pending" in status or "hold" in status: return ft.Colors.ORANGE
    elif "new" in status or "open" in status: return ft.Colors.RED
    return ft.Colors.BLUE_GREY

def get_priority_color(priority):
    if not priority: return ft.Colors.GREY
    p = str(priority)
    if "1" in p: return ft.Colors.RED
    if "2" in p: return ft.Colors.ORANGE
    if "3" in p: return ft.Colors.AMBER
    if "4" in p: return SSA_GREEN 
    return ft.Colors.GREY

def get_category_color(category):
    if not category: return ft.Colors.GREY
    cat = str(category).lower()
    if "request" in cat: return ft.Colors.BLUE
    elif "staff" in cat or "movement" in cat: return ft.Colors.PURPLE
    elif "inquiry" in cat: return ft.Colors.ORANGE
    elif "information" in cat: return SSA_GREEN
    return ft.Colors.GREY