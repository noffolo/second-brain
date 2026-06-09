import os
import sys
import subprocess
from engine.utils.markdown import load_settings

# Paths
LAUNCHAGENTS_DIR = os.path.expanduser("~/Library/LaunchAgents")
VAULT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PYTHON_PATH = sys.executable

def parse_cron_to_launchd(cron_str: str) -> str:
    """
    Mantiene la compatibilità con i test esistenti.
    Converte una cron string o intervallo in launchd plist snippet.
    """
    cron_str = cron_str.strip()
    if cron_str.isdigit():
        return f"    <key>StartInterval</key>\n    <integer>{cron_str}</integer>\n"
        
    parts = cron_str.split()
    if len(parts) != 5:
        return "    <key>StartInterval</key>\n    <integer>3600</integer>\n"
        
    minute, hour, mday, month, wday = parts
    xml_parts = []
    xml_parts.append("    <key>StartCalendarInterval</key>")
    xml_parts.append("    <dict>")
    if minute != "*":
        if minute.isdigit():
            xml_parts.append(f"        <key>Minute</key>\n        <integer>{int(minute)}</integer>")
    if hour != "*":
        if hour.isdigit():
            xml_parts.append(f"        <key>Hour</key>\n        <integer>{int(hour)}</integer>")
    if mday != "*":
        if mday.isdigit():
            xml_parts.append(f"        <key>Day</key>\n        <integer>{int(mday)}</integer>")
    if month != "*":
        if month.isdigit():
            xml_parts.append(f"        <key>Month</key>\n        <integer>{int(month)}</integer>")
    if wday != "*":
        if wday.isdigit():
            xml_parts.append(f"        <key>Weekday</key>\n        <integer>{int(wday)}</integer>")
    xml_parts.append("    </dict>\n")
    return "\n".join(xml_parts)

def install():
    """Generates and loads the single dashboard plist launch agent on macOS."""
    label = "com.secondbrain.dashboard"
    plist_path = os.path.join(LAUNCHAGENTS_DIR, f"{label}.plist")
    
    os.makedirs(LAUNCHAGENTS_DIR, exist_ok=True)
    
    log_dir = os.path.expanduser("~/Library/Logs/secondbrain")
    os.makedirs(log_dir, exist_ok=True)
    
    log_out = os.path.join(log_dir, f"{label}.out.log")
    log_err = os.path.join(log_dir, f"{label}.err.log")
    
    # Plist template for dashboard (keepalive = True)
    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{PYTHON_PATH}</string>
        <string>-m</string>
        <string>uvicorn</string>
        <string>engine.dashboard:app</string>
        <string>--host</string>
        <string>0.0.0.0</string>
        <string>--port</string>
        <string>8000</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{VAULT_PATH}</string>
    <key>StandardOutPath</key>
    <string>{log_out}</string>
    <key>StandardErrorPath</key>
    <string>{log_err}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
"""
    print(f"Generazione {plist_path} per demone unico della dashboard...")
    with open(plist_path, "w", encoding="utf-8") as f:
        f.write(content)
        
    print("Caricamento agente launchd della dashboard...")
    uid = os.getuid()
    cmd_unload = ["launchctl", "bootout", f"gui/{uid}/{label}"]
    cmd_load = ["launchctl", "bootstrap", f"gui/{uid}", plist_path]
    
    # Unload se già presente
    subprocess.run(cmd_unload, capture_output=True)
    
    # Carica il nuovo servizio
    res = subprocess.run(cmd_load, capture_output=True, text=True)
    if res.returncode == 0:
        print(f"Servizio {label} caricato ed avviato con successo in background.")
    else:
        print(f"Errore caricamento {label}: {res.stderr.strip()}")

def uninstall():
    """Unloads and deletes the dashboard plist launch agent and legacy ones on macOS."""
    label = "com.secondbrain.dashboard"
    plist_path = os.path.join(LAUNCHAGENTS_DIR, f"{label}.plist")
    
    uid = os.getuid()
    print(f"Disattivazione {label}...")
    cmd_unload = ["launchctl", "bootout", f"gui/{uid}/{label}"]
    subprocess.run(cmd_unload, capture_output=True)
    
    if os.path.exists(plist_path):
        os.remove(plist_path)
        print(f"Rimosso file {plist_path}.")
        
    # Rimozione dei vecchi plist legacy se rimasti nel sistema
    legacy_labels = ["com.secondbrain.sync", "com.secondbrain.reflect", "com.secondbrain.briefing", "com.secondbrain.dream"]
    for legacy in legacy_labels:
        legacy_plist = os.path.join(LAUNCHAGENTS_DIR, f"{legacy}.plist")
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{legacy}"], capture_output=True)
        if os.path.exists(legacy_plist):
            os.remove(legacy_plist)
            print(f"Rimosso file legacy {legacy_plist}.")
            
    print("Disinstallazione completata.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python plist_generator.py [install|uninstall]")
        sys.exit(1)
        
    action = sys.argv[1]
    if action == "install":
        install()
    elif action == "uninstall":
        uninstall()
    else:
        print(f"Azione '{action}' non supportata.")
        sys.exit(1)
