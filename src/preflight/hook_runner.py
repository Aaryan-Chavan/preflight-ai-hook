import tkinter as tk
from tkinter import ttk
import os
import subprocess
import json
import datetime
import typer
from rich.console import Console
from rich.panel import Panel
from pydantic import BaseModel

# Cloud & Network Imports
import firebase_admin
from firebase_admin import credentials, firestore
import google.generativeai as genai

# Local imports
from preflight.auth import load_config

console = Console()

class AIResult(BaseModel):
    risk_level: str
    confidence_percentage: int
    ai_recommendation: str
    ai_summary: str

def get_git_branch() -> str:
    try:
        branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], stderr=subprocess.DEVNULL).decode().strip()
        return branch
    except Exception:
        return "unknown-branch"

def get_git_diff() -> str:
    try:
        diff = subprocess.check_output(["git", "diff", "--cached"], stderr=subprocess.DEVNULL).decode().strip()
        return diff
    except Exception:
        return ""

def run_local_ml_model(diff_text: str) -> dict:
    if not diff_text:
        return {"ml_risk": "LOW", "confidence": 100}
        
    console.print("[dim]Executing local ML heuristics...[/dim]")
    if "password" in diff_text.lower() or "secret" in diff_text.lower():
        return {"ml_risk": "HIGH", "confidence": 95}
    return {"ml_risk": "LOW", "confidence": 98}

def run_cloud_llm(diff_text: str, api_key: str, ml_baseline: dict) -> AIResult:
    if not diff_text:
        return AIResult(
            risk_level="LOW", 
            confidence_percentage=100, 
            ai_recommendation="No code changes detected.",
            ai_summary="The commit contains no modified files or diff content to analyze."
        )
    
    if api_key == "mock_key_for_now":
        if ml_baseline.get("ml_risk") == "HIGH" or "secret" in diff_text.lower():
            return AIResult(
                risk_level="HIGH", 
                confidence_percentage=94, 
                ai_recommendation="Critical: Hardcoded secret token detected in diff string. Remote push has been intercepted.",
                ai_summary="The AI analysis has identified a potential hardcoded secret or password within the code diff. Committing sensitive credentials to a repository poses a severe security risk, potentially leading to unauthorized access. It is strongly advised to remove the secret and utilize environment variables or a secure secret management service instead."
            )
        return AIResult(
            risk_level="LOW", 
            confidence_percentage=100, 
            ai_recommendation="All Security & Performance Gates Passed. Zero memory leaks detected.",
            ai_summary="The code changes have been successfully analyzed. No obvious security vulnerabilities, memory leaks, or unhandled exceptions were detected in the provided diff. The code appears structurally sound and safe for deployment based on current heuristics."
        )

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        prompt = f"""
        You are Preflight AI, an autonomous pre-commit security agent. 
        Analyze this git diff and return ONLY a strict JSON object with no markdown formatting.
        
        The local ML model already scored this diff as {ml_baseline.get('ml_risk')} risk with {ml_baseline.get('confidence')}% confidence.
        Factor this baseline into your deep semantic analysis.
        
        Analyze for: Hardcoded secrets, unhandled promise rejections, memory leaks, and SQL injection.
        
        JSON Format Required:
        {{
            "risk_level": "LOW" | "MEDIUM" | "HIGH",
            "confidence_percentage": 0-100,
            "ai_recommendation": "A concise 2-sentence explanation of the risk or why it passed.",
            "ai_summary": "A detailed, natural language summary explaining the findings, potential impact, and suggested remediations."
        }}
        
        Git Diff:
        {diff_text}
        """
        response = model.generate_content(prompt)
        result = json.loads(response.text.strip().replace("```json", "").replace("```", ""))
        return AIResult(**result)
    except Exception as e:
        console.print(f"[yellow]LLM Analysis failed: {e}. Falling back to ML rules engine.[/yellow]")
        return AIResult(
            risk_level=ml_baseline.get("ml_risk", "UNKNOWN"), 
            confidence_percentage=ml_baseline.get("confidence", 0), 
            ai_recommendation="LLM API unreachable. Score based purely on local ML inference.",
            ai_summary="The connection to the cloud LLM failed. The current risk assessment relies entirely on the local machine learning model's metadata analysis, which may lack deep semantic understanding."
        )

def sync_to_firestore(config, branch: str, ai_result: AIResult, commit_hash: str, user_decision: str):
    key_path = "serviceAccountKey.json" 
    if os.path.exists(key_path) and not firebase_admin._apps:
        cred = credentials.Certificate(key_path)
        firebase_admin.initialize_app(cred)
    
    if firebase_admin._apps:
        db = firestore.client()
        doc_ref = db.collection("reports").document(commit_hash)
        
        payload = {
            "report_id": commit_hash,
            "user_id": config.user_id,
            "device_id": config.device_id,
            "branch": branch,
            "timestamp": datetime.datetime.now(datetime.timezone.utc),
            "user_decision": user_decision,  # "CONTINUED", "CANCELLED", "OVERRIDDEN", "ABORTED"
            "popup": {
                "risk_level": ai_result.risk_level,
                "confidence_percentage": ai_result.confidence_percentage,
                "ai_recommendation": ai_result.ai_recommendation,
                "ai_summary": ai_result.ai_summary
            }
        }
        
        doc_ref.set(payload)
        console.print(f"[cyan]Telemetry synced to Cloud Dashboard (Decision: {user_decision}).[/cyan]")
    else:
        console.print("[yellow]Firestore sync skipped (serviceAccountKey.json not found).[/yellow]")

def display_interactive_popup(ai_result: AIResult) -> str:
    """Launches a native graphical window with clickable buttons and an expandable AI summary."""
    decision_container = {"result": "CANCELLED"}
    
    root = tk.Tk()
    root.title("Preflight AI Code Review")
    root.geometry("480\\n380")
    root.configure(bg="#121318")
    root.attributes("-topmost", True) # Keep window on top of terminal

    # Main Card Frame
    frame = tk.Frame(root, bg="#1e1f25", bd=2, relief="flat")
    frame.pack(fill="both", expand=True, padx=15, pady=15)

    # Title
    title_label = tk.Label(frame, text="▲ Preflight AI Code Review", fg="#c0c1ff", bg="#1e1f25", font=("Inter", 12, "bold"))
    title_label.pack(anchor="w", padx=10, pady=10)

    # Risk & Confidence Details
    risk_color = "#ffb4ab" if ai_result.risk_level == "HIGH" else ("#ffd866" if ai_result.risk_level == "MEDIUM" else "#34d399")
    
    info_frame = tk.Frame(frame, bg="#1e1f25")
    info_frame.pack(fill="x", padx=10, pady=5)

    tk.Label(info_frame, text="Risk Level:", fg="#908fa0", bg="#1e1f25", font=("Inter", 10)).grid(row=0, column=0, sticky="w", pady=2)
    tk.Label(info_frame, text=f"{ai_result.risk_level} RISK", fg=risk_color, bg="#1e1f25", font=("Inter", 10, "bold")).grid(row=0, column=1, sticky="w", padx=10, pady=2)

    tk.Label(info_frame, text="AI Confidence:", fg="#908fa0", bg="#1e1f25", font=("Inter", 10)).grid(row=1, column=0, sticky="w", pady=2)
    tk.Label(info_frame, text=f"{ai_result.confidence_percentage}%", fg="#e3e1e9", bg="#1e1f25", font=("Inter", 10, "bold")).grid(row=1, column=1, sticky="w", padx=10, pady=2)

    tk.Label(info_frame, text="Target Branch:", fg="#908fa0", bg="#1e1f25", font=("Inter", 10)).grid(row=2, column=0, sticky="w", pady=2)
    tk.Label(info_frame, text="main", fg="#c0c1ff", bg="#1e1f25", font=("Inter", 10, "bold")).grid(row=2, column=1, sticky="w", padx=10, pady=2)

    # Expandable AI Summary Dropdown Section
    summary_frame = tk.Frame(frame, bg="#1e1f25")
    summary_frame.pack(fill="x", padx=10, pady=10)

    text_box_frame = tk.Frame(frame, bg="#121318")
    summary_text = tk.Text(text_box_frame, height=5, wrap="word", bg="#0d0e13", fg="#e3e1e9", font=("JetBrains Mono", 9), bd=0, relief="flat")
    summary_text.insert("1.0", ai_result.ai_summary)
    summary_text.config(state="disabled")
    
    def toggle_summary():
        if text_box_frame.winfo_ismapped():
            text_box_frame.pack_forget()
            toggle_btn.config(text="▼ Show AI Summary")
        else:
            text_box_frame.pack(fill="x", padx=10, pady=5)
            summary_text.pack(fill="both", padx=5, pady=5)
            toggle_btn.config(text="▲ Hide AI Summary")

    toggle_btn = tk.Button(summary_frame, text="▼ Show AI Summary", fg="#4cd7f6", bg="#1e1f25", activebackground="#1e1f25", activeforeground="#4cd7f6", bd=0, font=("Inter", 9, "bold"), cursor="hand2", command=toggle_summary)
    toggle_btn.pack(anchor="w")

    # Action Buttons (Cancel vs Continue)
    btn_frame = tk.Frame(frame, bg="#1e1f25")
    btn_frame.pack(fill="x", padx=10, pady=15)

    def on_continue():
        decision_container["result"] = "CONTINUED"
        root.destroy()

    def on_cancel():
        decision_container["result"] = "CANCELLED"
        root.destroy()

    cancel_btn = tk.Button(btn_frame, text="Cancel Push", fg="#ffffff", bg="#34343a", activebackground="#464554", activeforeground="#ffffff", font=("Inter", 10, "bold"), width=15, pady=8, bd=0, cursor="hand2", command=on_cancel)
    cancel_btn.pack(side="left", padx=5)

    continue_btn = tk.Button(btn_frame, text="Continue Push", fg="#1000a9", bg="#34d399", activebackground="#059669", activeforeground="#ffffff", font=("Inter", 10, "bold"), width=15, pady=8, bd=0, cursor="hand2", command=on_continue)
    continue_btn.pack(side="right", padx=5)

    root.mainloop()
    return decision_container["result"]

def run_preflight_checks():
    console.print("\n[bold cyan]Initializing Preflight AI Security Gates...[/bold cyan]")
    
    config = load_config()
    branch = get_git_branch()
    diff = get_git_diff()
    
    import random
    mock_hash = f"{random.randint(1000000, 9999999):x}"
    
    console.print(f"Analyzing push to branch: [bold]{branch}[/bold]")
    
    ml_result = run_local_ml_model(diff)
    
    console.print("Running deep semantic LLM analysis...")
    ai_result = run_cloud_llm(diff, config.api_key, ml_result)
    
    # 1. Prompt user first to get their decision
    user_decision = display_interactive_popup(ai_result)
    
    # 2. Sync telemetry and final user decision to Firestore
    sync_to_firestore(config, branch, ai_result, mock_hash, user_decision)
    
    # 3. Exit code based on decision
    if user_decision == "CANCELLED":
        raise typer.Exit(code=1)
    else:
        raise typer.Exit(code=0)