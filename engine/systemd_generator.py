import os
import sys
import subprocess

# Paths
SYSTEMD_USER_DIR = os.path.expanduser("~/.config/systemd/user")
VAULT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PYTHON_PATH = sys.executable

def install():
    """Genera e carica il servizio utente systemd su Linux."""
    label = "secondbrain"
    service_file = os.path.join(SYSTEMD_USER_DIR, f"{label}.service")
    
    os.makedirs(SYSTEMD_USER_DIR, exist_ok=True)
    
    # Template per il servizio systemd
    content = f"""[Unit]
Description=Secondo Cervello FastAPI Dashboard & Engine
After=network.target

[Service]
Type=simple
WorkingDirectory={VAULT_PATH}
ExecStart={PYTHON_PATH} -m uvicorn engine.dashboard:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
"""
    print(f"Generazione file di servizio systemd utente: {service_file}...")
    with open(service_file, "w", encoding="utf-8") as f:
        f.write(content)
        
    print("Ricaricamento dei demoni systemd utente...")
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    
    print(f"Abilitazione e avvio del servizio {label}...")
    res_enable = subprocess.run(["systemctl", "--user", "enable", f"{label}.service"], capture_output=True, text=True)
    res_start = subprocess.run(["systemctl", "--user", "start", f"{label}.service"], capture_output=True, text=True)
    
    if res_start.returncode == 0:
        print(f"\n-> Servizio {label} installato ed avviato in background con successo!")
        print("NOTA: Per assicurare che il servizio continui a girare sul server anche dopo la disconnessione SSH,")
        print("esegui il seguente comando una sola volta sul tuo server:")
        print(f"    loginctl enable-linger {os.getlogin() if hasattr(os, 'getlogin') else 'tuo_utente'}")
    else:
        print(f"Errore durante l'avvio del servizio: {res_start.stderr.strip()}")

def uninstall():
    """Arresta e rimuove il servizio utente systemd su Linux."""
    label = "secondbrain"
    service_file = os.path.join(SYSTEMD_USER_DIR, f"{label}.service")
    
    print(f"Arresto del servizio {label}...")
    subprocess.run(["systemctl", "--user", "stop", f"{label}.service"], capture_output=True)
    print(f"Disabilitazione del servizio {label}...")
    subprocess.run(["systemctl", "--user", "disable", f"{label}.service"], capture_output=True)
    
    if os.path.exists(service_file):
        os.remove(service_file)
        print(f"Rimosso file {service_file}.")
        
    print("Ricaricamento dei demoni systemd utente...")
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    print("Disinstallazione completata.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python systemd_generator.py [install|uninstall]")
        sys.exit(1)
        
    action = sys.argv[1]
    if action == "install":
        install()
    elif action == "uninstall":
        uninstall()
    else:
        print(f"Azione '{action}' non supportata.")
        sys.exit(1)
