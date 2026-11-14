import os
import json
import uuid
import platform
import socket
from pathlib import Path
import typer
from rich.console import Console
from pydantic import BaseModel

console = Console()

# We store the config in the user's home directory under .preflight/
CONFIG_DIR = Path.home() / ".preflight"
CONFIG_FILE = CONFIG_DIR / "config.json"

class PreflightConfig(BaseModel):
    api_key: str
    user_id: str
    device_id: str
    device_name: str
    os_type: str

def get_hardware_uuid() -> str:
    """Generates a stable, unique ID based on the machine's hardware MAC address."""
    node = uuid.getnode()
    return f"dev-{uuid.UUID(int=node).hex[-12:]}"

def login_user(api_key: str) -> str:
    """
    Mock function to validate the API key against the cloud backend.
    In production, this would hit a Firebase Cloud Function to verify the key
    and return the associated user_id.
    """
    # For now, we will use a dummy user_id based on the key
    if not api_key:
        raise ValueError("API Key cannot be empty.")
    
    user_id = f"usr_{api_key[:8]}"
    return user_id

def register_device(user_id: str) -> str:
    """
    Registers this specific physical machine. Creates the local config.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    device_id = get_hardware_uuid()
    device_name = socket.gethostname()
    os_type = platform.system()
    
    # In production, you would push this device data to the Firestore `devices` collection here.
    
    config = PreflightConfig(
        api_key="mock_key_for_now", 
        user_id=user_id,
        device_id=device_id,
        device_name=device_name,
        os_type=os_type
    )
    
    with open(CONFIG_FILE, "w") as f:
        f.write(config.model_dump_json(indent=4))
        
    return device_id

def load_config() -> PreflightConfig:
    """Loads the config file. Fails if the user hasn't logged in yet."""
    if not CONFIG_FILE.exists():
        console.print("[red]Not authenticated. Please run 'preflight login' first.[/red]")
        raise typer.Exit(code=1)
        
    with open(CONFIG_FILE, "r") as f:
        data = json.load(f)
        return PreflightConfig(**data)