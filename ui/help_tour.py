import flet as ft
<<<<<<< HEAD
import json
import os
from ui.styles import SSA_GREEN, SSA_GREY, SSA_BG
from services.path_manager import PathManager
=======
from ui.styles import SSA_GREEN, SSA_GREY, SSA_BG
>>>>>>> 050048a87e330291b783c1b91c5b654cf7c42826

class HelpTourDialog(ft.AlertDialog):
    """
    Componente visual del Tour de Ayuda.
    Responsabilidad: Mostrar pasos y capturar la preferencia 'No volver a mostrar'.
    """
    def __init__(self, page, on_dismiss_callback=None):
        super().__init__()
        self.page_ref = page
        self.modal = True
        self.current_step = 0
        self.on_dismiss_callback = on_dismiss_callback 
<<<<<<< HEAD
        self.prefs_path = PathManager.get_user_prefs_path()
        
        # Cargar preferencia inicial si existe
        initial_value = False
        if os.path.exists(self.prefs_path):
            try:
                with open(self.prefs_path, "r") as f:
                    prefs = json.load(f)
                    initial_value = prefs.get("hide_tour", False)
            except: pass

        # Checkbox para la preferencia del usuario
        self.dont_show_checkbox = ft.Checkbox(
            label="Don't show again", 
            value=initial_value, 
            label_style=ft.TextStyle(size=12, color=SSA_GREY),
            on_change=self.save_preference # Guardado inmediato al cambiar
=======
        
        # Checkbox para la preferencia del usuario
        self.dont_show_checkbox = ft.Checkbox(
            label="Don't show again", 
            value=False, 
            label_style=ft.TextStyle(size=12, color=SSA_GREY)
>>>>>>> 050048a87e330291b783c1b91c5b654cf7c42826
        )

        # --- CONTENIDO DEL TOUR (EN INGLÉS) ---
        self.steps = [
            {
                "title": "👋 Welcome to C.A.R.O.L!",
                "content": ft.Column([
                    ft.Text("Centralized Automation for Request Operations & Logic", weight="bold", color=SSA_GREY),
                    ft.Text("This tool helps you manage payroll requests efficiently and in real-time.", size=14),
                    ft.Container(height=10),
                    ft.Icon(ft.Icons.AUTO_AWESOME, size=50, color=SSA_GREEN),
                    ft.Text("Your changes sync instantly with the team!", italic=True, size=12)
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            },
            {
                "title": "🚦 Priority Traffic Light",
                "content": ft.Column([
                    ft.Text("Colors indicate the urgency of each request based on SLA:", weight="bold"),
                    ft.Row([ft.Icon(ft.Icons.CIRCLE, color="green"), ft.Text("On Time (> 4 hours)")]),
                    ft.Row([ft.Icon(ft.Icons.CIRCLE, color="yellow"), ft.Text("Warning (< 4 hours)")]),
                    ft.Row([ft.Icon(ft.Icons.CIRCLE, color="orange"), ft.Text("Urgent (< 2 hours)")]),
                    ft.Row([ft.Icon(ft.Icons.CIRCLE, color="red"), ft.Text("Overdue")]),
                    ft.Text("Keep everything green!", color=SSA_GREEN, weight="bold")
                ])
            },
            {
                "title": "📩 Unread Emails & Badges",
                "content": ft.Column([
                    ft.Text("Notice a red number on the top right of a card?", weight="bold"),
                    ft.Container(
                        content=ft.Row([
                            ft.Container(
                                content=ft.Text("3", color="white", weight="bold", size=12),
                                bgcolor="red", padding=5, border_radius=10
                            ),
                            ft.Text("= Unread emails for this request.")
                        ]),
                        padding=5
                    ),
                    ft.Text("This indicates how many new emails you haven't opened yet inside that specific request. Click the card to view them!", size=13)
                ])
            },
            {
                "title": "🏷️ Categorization & Status",
                "content": ft.Column([
                    ft.Text("How to manage requests:", weight="bold"),
                    ft.Text("1. Default Status: All new requests start as 'Pending'.", size=13),
                    ft.Text("2. Categorize: Just select the correct Category (e.g., 'Inquiry', 'Staff Movements').", size=13),
                    ft.Container(height=5),
                    ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.LIGHTBULB, color="amber"),
                            ft.Text("The Priority Matrix automatically sets the Priority and deadlines based on the category you choose!", size=12, italic=True, expand=True)
<<<<<<< HEAD
                        ], alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.CENTER),
=======
                        ], alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.START),
>>>>>>> 050048a87e330291b783c1b91c5b654cf7c42826
                        bgcolor=SSA_BG, padding=10, border_radius=8, width=400
                    )
                ], spacing=5)
            },
            {
                "title": "🛠️ Card Actions",
                "content": ft.Column([
                    ft.Text("Click on any card to:", weight="bold"),
                    ft.ListTile(leading=ft.Icon(ft.Icons.TOUCH_APP), title=ft.Text("View details and attached files")),
                    ft.ListTile(leading=ft.Icon(ft.Icons.EDIT), title=ft.Text("Change Status, Priority, or Category")),
                    ft.Text("Remember: Everything is saved automatically.", italic=True, size=12, color=SSA_GREY)
                ], spacing=0)
            },
            {
                "title": "🚑 Emergency Mode (Outlook)",
                "content": ft.Column([
                    ft.Text("Is the 'New Outlook' failing you?", weight="bold", color=ft.Colors.RED_400),
                    ft.Text("If you see a grey window, errors when replying/forwarding, or it just won't load:", size=13),
                    ft.Container(height=5),
                    ft.ListTile(
                        leading=ft.Icon(ft.Icons.MEDICAL_SERVICES, color="green"),
                        title=ft.Text("Click the Emergency Button inside the request details.", size=13, weight=ft.FontWeight.BOLD),
                        subtitle=ft.Text("This will force-open the email using Classic Outlook to get you back to work immediately.", size=12)
                    )
                ], spacing=5)
            },
            {
                "title": "⚡ Smart Sync",
                "content": ft.Column([
                    ft.Text("No need to refresh the page.", weight="bold"),
                    ft.Text("C.A.R.O.L uses 'Smart Polling'. If a teammate changes a request or a new email arrives, you will see it update on your screen in less than 5 seconds."),
                ])
            },
            {
                "title": "✅ You're Ready!",
                "content": ft.Column([
                    ft.Text("That's it! If you ever need a refresher, just click the help button."),
                    ft.Container(height=20),
                    ft.ElevatedButton("Start Working", on_click=self.close_tour, bgcolor=SSA_GREEN, color="white")
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)
            }
        ]

        self.title = ft.Text(self.steps[0]["title"], color=SSA_GREY, weight="bold")
        # Ajuste de altura y ancho para asegurar que todo el contenido quepa cómodamente
        self.content = ft.Container(content=self.steps[0]["content"], width=420, height=380) 
        
        self.btn_next = ft.TextButton("Next >", on_click=self.next_step)
        self.btn_prev = ft.TextButton("< Back", on_click=self.prev_step, visible=False)
        
        # Acciones con el Checkbox integrado
        self.actions = [
            ft.Column([
                ft.Divider(),
                ft.Row([
                    self.dont_show_checkbox, 
                    ft.Row([self.btn_prev, self.btn_next]) 
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
            ])
        ]
        self.actions_alignment = ft.MainAxisAlignment.CENTER

<<<<<<< HEAD
    def save_preference(self, e):
        """Guarda la preferencia localmente usando PathManager"""
        prefs = {"hide_tour": self.dont_show_checkbox.value}
        try:
            # Asegurar directorio
            os.makedirs(os.path.dirname(self.prefs_path), exist_ok=True)
            with open(self.prefs_path, "w") as f:
                json.dump(prefs, f)
        except Exception as ex:
            print(f"Error saving prefs: {ex}")

=======
>>>>>>> 050048a87e330291b783c1b91c5b654cf7c42826
    def update_view(self):
        step = self.steps[self.current_step]
        self.title.value = step["title"]
        self.content.content = step["content"]
        
        self.btn_prev.visible = (self.current_step > 0)
        self.btn_next.text = "Next >" if self.current_step < len(self.steps) - 1 else ""
        self.btn_next.visible = (self.current_step < len(self.steps) - 1)
        
        self.page_ref.update()

    def next_step(self, e):
        if self.current_step < len(self.steps) - 1:
            self.current_step += 1
            self.update_view()

    def prev_step(self, e):
        if self.current_step > 0:
            self.current_step -= 1
            self.update_view()

    def close_tour(self, e):
        self.open = False
        self.page_ref.update()
<<<<<<< HEAD
        # Notificar al manager sobre la decisión del usuario (Mantenemos compatibilidad)
=======
        # Notificar al manager sobre la decisión del usuario
>>>>>>> 050048a87e330291b783c1b91c5b654cf7c42826
        if self.on_dismiss_callback:
            self.on_dismiss_callback(dont_show_again=self.dont_show_checkbox.value)