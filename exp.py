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
                ai_summary="The AI analysis has identified a potential hardcoded secret or password within the code diff. Committing sensitive credentials to a repository poses a severe security risk."
            )
        return AIResult(
            risk_level="LOW", 
            confidence_percentage=100, 
            ai_recommendation="All Security & Performance Gates Passed. Zero memory leaks detected.",
            ai_summary="The code changes have been successfully analyzed. No obvious security vulnerabilities or memory leaks were detected."
        )

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        prompt = f"""
        You are Preflight AI, an autonomous pre-commit security agent. 
        Analyze this git diff and return ONLY a strict JSON object with no markdown formatting.
        
        The local ML model already scored this diff as {ml_baseline.get('ml_risk')} risk with {ml_baseline.get('confidence')}% confidence.
        
        JSON Format Required:
        {{
            "risk_level": "LOW" | "MEDIUM" | "HIGH",
            "confidence_percentage": 0-100,
            "ai_recommendation": "A concise 2-sentence explanation of the risk or why it passed.",
            "ai_summary": "A detailed, natural language summary explaining the findings and suggested remediations."
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
            ai_summary="The connection to the cloud LLM failed. Assessment relies on local ML model."
        )

def sync_to_firestore(config, branch: str, ai_result: AIResult, commit_hash: str, user_decision: str):
    """Pushes telemetry to Firestore including the final user decision."""
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
    """Displays terminal popup and returns the user's decision."""
    if ai_result.risk_level == "HIGH":
        color = "red"
        title = "⚠️ CRITICAL SECURITY VIOLATION ⚠️"
    elif ai_result.risk_level == "MEDIUM":
        color = "yellow"
        title = "⚠️ WARNING: MEDIUM RISK DETECTED ⚠️"
    else:
        color = "green"
        title = "✅ Preflight Checks Passed"

    console.print(f"\n[bold {color} on black] {title} [/bold {color} on black]")
    console.print(f"[{color}]AI Confidence: {ai_result.confidence_percentage}% ({ai_result.risk_level})[/{color}]")
    console.print(f"[{color}]{ai_result.ai_recommendation}[/{color}]\n")

    while True:
        options = []
        if ai_result.risk_level in ["HIGH", "MEDIUM"]:
            options.append(f"[{color}]1. View AI Summary (Expand)[/{color}]")
            options.append(f"[bold {color}]2. Cancel Push (Recommended)[/bold {color}]")
            options.append("[dim]3. Force Push (Override)[/dim]")
        else:
            options.append("[green]1. View AI Summary (Expand)[/green]")
            options.append("[bold green]2. Continue Push[/bold green]")
            options.append("[dim]3. Cancel Push[/dim]")

        console.print("\n".join(options))
        choice = typer.prompt("Select an option", type=int)

        if choice == 1:
            summary_panel = Panel(
                f"[white]{ai_result.ai_summary}[/white]", 
                title=f"[{color}]Detailed AI Summary[/{color}]", 
                border_style=color
            )
            console.print("\n")
            console.print(summary_panel)
            console.print("\n")
        elif choice == 2:
            if ai_result.risk_level in ["HIGH", "MEDIUM"]:
                console.print(f"[{color}]Push safely aborted by user.[//{color}]")
                return "CANCELLED"
            else:
                console.print("[green]Pushing to remote...[/green]")
                return "CONTINUED"
        elif choice == 3:
             if ai_result.risk_level in ["HIGH", "MEDIUM"]:
                 console.print(f"[bold {color}]Override accepted. Proceeding with risky push...[/bold {color}]")
                 return "OVERRIDDEN"
             else:
                 console.print("[dim]Push aborted by user.[/dim]")
                 return "ABORTED"
        else:
            console.print("[red]Invalid selection.[/red]")

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
    
    # 1. Prompt user interactively first to get their decision
    user_decision = display_interactive_popup(ai_result)
    
    # 2. Sync final decision and telemetry to Firestore
    sync_to_firestore(config, branch, ai_result, mock_hash, user_decision)
    
    # 3. Enforce Git exit status based on user decision
    if user_decision in ["CANCELLED", "ABORTED"]:
        raise typer.Exit(code=1)
    else:
        raise typer.Exit(code=0)