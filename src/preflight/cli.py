import typer
import webbrowser
import json
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from rich.console import Console

from preflight.auth import login_user, register_device
from preflight.installer import install_git_hook
from preflight.hook_runner import run_preflight_checks

app = typer.Typer(help="Preflight AI - Autonomous Pre-commit Quality Gates & Telemetry")
console = Console()

def launch_firebase_setup_gui() -> dict:
    """Launches a Tkinter window to collect Firebase credentials from the user."""
    config_data = {}
    
    root = tk.Tk()
    root.title("Preflight AI - Self-Hosted Database Setup")
    root.geometry("500x400")
    root.configure(bg="#121318")
    root.attributes("-topmost", True)
    
    # Center window
    root.eval('tk::PlaceWindow . center')

    # Main Frame
    frame = tk.Frame(root, bg="#1e1f25", bd=2, relief="flat")
    frame.pack(fill="both", expand=True, padx=20, pady=20)

    # Title & Description
    tk.Label(frame, text="▲ Configure Private Telemetry DB", fg="#c0c1ff", bg="#1e1f25", font=("Inter", 12, "bold")).pack(anchor="w", pady=(0, 5))
    tk.Label(frame, text="To keep your code telemetry strictly private, Preflight AI\nruns on your own Firebase instance.", fg="#908fa0", bg="#1e1f25", font=("Inter", 9), justify="left").pack(anchor="w", pady=(0, 15))

    # Form Fields
    fields = [
        ("Firebase API Key", "apiKey"),
        ("Firebase Project ID", "projectId"),
        ("Firebase Messaging Sender ID", "messagingSenderId"),
        ("Firebase App ID", "appId")
    ]
    
    entries = {}
    
    for label_text, key_name in fields:
        row_frame = tk.Frame(frame, bg="#1e1f25")
        row_frame.pack(fill="x", pady=5)
        tk.Label(row_frame, text=label_text, fg="#e3e1e9", bg="#1e1f25", font=("Inter", 9, "bold"), width=25, anchor="w").pack(side="left")
        entry = tk.Entry(row_frame, bg="#0d0e13", fg="#c0c1ff", insertbackground="#c0c1ff", font=("JetBrains Mono", 9), bd=1, relief="solid", highlightthickness=1, highlightcolor="#4cd7f6")
        entry.pack(side="left", fill="x", expand=True, padx=5)
        entries[key_name] = entry

    def on_submit():
        for key in entries:
            val = entries[key].get().strip()
            if not val:
                messagebox.showerror("Error", "All fields are required.", parent=root)
                return
            config_data[key] = val
        root.destroy()

    def on_cancel():
        root.destroy()

    # Buttons
    btn_frame = tk.Frame(frame, bg="#1e1f25")
    btn_frame.pack(fill="x", pady=20)
    
    tk.Button(btn_frame, text="Cancel", fg="#ffffff", bg="#34343a", activebackground="#464554", activeforeground="#ffffff", font=("Inter", 10, "bold"), width=12, pady=6, bd=0, cursor="hand2", command=on_cancel).pack(side="left", padx=5)
    tk.Button(btn_frame, text="Save & Connect", fg="#1000a9", bg="#4cd7f6", activebackground="#009eb9", activeforeground="#ffffff", font=("Inter", 10, "bold"), width=15, pady=6, bd=0, cursor="hand2", command=on_submit).pack(side="right", padx=5)

    root.mainloop()
    return config_data

@app.command()
def init(api_key: str = typer.Option(None, help="Provide API key directly (optional)")):
    """One-Step Setup: Authenticate, register device, connect DB, and install Git hook."""
    console.print("\n[bold cyan]🚀 Initializing Preflight AI Workspace...[/bold cyan]")
    
    # 1. Automatic Login & Device Registration
    config_dir = Path.home() / ".preflight"
    config_dir.mkdir(exist_ok=True)
    config_path = config_dir / "config.json"
    
    if not config_path.exists():
        console.print("[yellow]Authentication required.[/yellow]")
        if not api_key:
            api_key = typer.prompt("Please enter your Preflight API Key (or Gemini Key)", hide_input=True)
        
        console.print("[dim]Registering hardware and verifying credentials...[/dim]")
        user_id = login_user(api_key)
        device_id = register_device(user_id)
        console.print(f"[green]✔ Successfully authenticated! Device ID: {device_id}[/green]")
    else:
        console.print("[green]✔ Device already authenticated.[/green]")

    # 2. Self-Hosted Database Configuration via GUI
    fb_config_path = config_dir / "firebase.json"
    if not fb_config_path.exists():
        console.print("\n[bold yellow]Launching Self-Hosted Database Setup UI...[/bold yellow]")
        fb_config = launch_firebase_setup_gui()
        
        if not fb_config:
            console.print("[bold red]✘ Database setup cancelled. Preflight AI requires a private database to operate.[/bold red]")
            raise typer.Exit(code=1)
            
        with open(fb_config_path, "w") as f:
            json.dump(fb_config, f)
        console.print("[green]✔ Private database linked successfully.[/green]")
    else:
        console.print("[green]✔ Private database configuration verified.[/green]")

    # 3. Automatic Hook Installation
    console.print("\n[dim]Scanning local Git repository...[/dim]")
    try:
        install_git_hook()
        console.print("[bold green]✔ Pre-push hook injected successfully![/bold green]")
        console.print("[cyan]Your repository is now secured by Preflight AI.[/cyan]\n")
    except Exception as e:
        console.print(f"[bold red]✘ Hook installation failed: {e}[/bold red]")
        raise typer.Exit(code=1)
        
    # 4. Automatic Dashboard Prompt
    open_dash = typer.confirm("Do you want to open your live dashboard now?", default=True)
    if open_dash:
        dashboard()

@app.command(name="run-hook", hidden=True)
def run_hook():
    """Internal command triggered automatically by Git. Hidden from help menu."""
    try:
        run_preflight_checks()
    except Exception as e:
        console.print(f"[red]Preflight Error: {e}[/red]")
        raise typer.Exit(code=1)

@app.command()
def dashboard():
    """Opens the live Preflight Telemetry Dashboard in your default browser."""
    fb_config_path = Path.home() / ".preflight" / "firebase.json"
    
    if not fb_config_path.exists():
        console.print("[red]✘ Database not configured. Please run `preflight init` first.[/red]")
        raise typer.Exit(code=1)
        
    with open(fb_config_path, "r") as f:
        fb_config = json.load(f)
        
    template_path = Path(__file__).parent / "templates" / "dashboard.html"
    
    if not template_path.exists():
        console.print("[red]✘ Dashboard template not found in installation.[/red]")
        raise typer.Exit(code=1)
        
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()
        
    html = html.replace("YOUR_API_KEY_HERE", fb_config.get("apiKey", ""))
    html = html.replace("YOUR_PROJECT_ID", fb_config.get("projectId", ""))
    html = html.replace("YOUR_SENDER_ID", fb_config.get("messagingSenderId", ""))
    html = html.replace("YOUR_APP_ID", fb_config.get("appId", ""))
    
    live_path = Path.home() / ".preflight" / "live_dashboard.html"
    with open(live_path, "w", encoding="utf-8") as f:
        f.write(html)
        
    console.print("[cyan]Launching Private Telemetry Dashboard...[/cyan]")
    webbrowser.open(f"file://{live_path.absolute()}")

if __name__ == "__main__":
    app()
