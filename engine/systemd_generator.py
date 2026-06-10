import os
import sys
import subprocess

# Paths
SYSTEMD_USER_DIR = os.path.expanduser("~/.config/systemd/user")
VAULT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PYTHON_PATH = sys.executable

def install():
    """Genera e carica i servizi utente systemd su Linux."""
    os.makedirs(SYSTEMD_USER_DIR, exist_ok=True)
    
    # 1. Servizio principale (Dashboard + Watcher + Scheduler)
    label_main = "secondbrain"
    service_file_main = os.path.join(SYSTEMD_USER_DIR, f"{label_main}.service")
    
    content_main = f"""[Unit]
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
    print(f"Generazione file di servizio systemd utente (Dashboard): {service_file_main}...")
    with open(service_file_main, "w", encoding="utf-8") as f:
        f.write(content_main)

    # 2. Servizio Telegram Bot
    label_tg = "secondbrain-telegram"
    service_file_tg = os.path.join(SYSTEMD_USER_DIR, f"{label_tg}.service")
    
    content_tg = f"""[Unit]
Description=Secondo Cervello Telegram Bot Daemon
After=network.target {label_main}.service

[Service]
Type=simple
WorkingDirectory={VAULT_PATH}
ExecStart={PYTHON_PATH} engine/telegram_bot.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
"""
    print(f"Generazione file di servizio systemd utente (Telegram): {service_file_tg}...")
    with open(service_file_tg, "w", encoding="utf-8") as f:
        f.write(content_tg)

    # 3. Servizio WhatsApp Syncer
    label_wa = "secondbrain-whatsapp"
    service_file_wa = os.path.join(SYSTEMD_USER_DIR, f"{label_wa}.service")
    import shutil
    node_path = shutil.which("node") or "/usr/bin/node"
    
    content_wa = f"""[Unit]
Description=Secondo Cervello WhatsApp Syncer Daemon
After=network.target

[Service]
Type=simple
WorkingDirectory={os.path.join(VAULT_PATH, "engine", "tools", "whatsapp_syncer")}
ExecStart={node_path} syncer.js
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
"""
    print(f"Generazione file di servizio systemd utente (WhatsApp): {service_file_wa}...")
    with open(service_file_wa, "w", encoding="utf-8") as f:
        f.write(content_wa)
        
    print("Ricaricamento dei demoni systemd utente...")
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    
    print(f"Abilitazione e avvio del servizio {label_main}...")
    subprocess.run(["systemctl", "--user", "enable", f"{label_main}.service"], capture_output=True)
    subprocess.run(["systemctl", "--user", "start", f"{label_main}.service"], capture_output=True)
    
    print(f"Abilitazione e avvio del servizio {label_tg}...")
    subprocess.run(["systemctl", "--user", "enable", f"{label_tg}.service"], capture_output=True)
    subprocess.run(["systemctl", "--user", "start", f"{label_tg}.service"], capture_output=True)

    print(f"Abilitazione del servizio {label_wa}...")
    res_enable_wa = subprocess.run(["systemctl", "--user", "enable", f"{label_wa}.service"], capture_output=True)
    
    print(f"\n-> Servizi {label_main}, {label_tg} e {label_wa} configurati con successo!")
    print("NOTA: Per assicurare che i servizi continuino a girare sul server anche dopo la disconnessione SSH,")
    print("esegui il seguente comando una sola volta sul tuo server:")
    print(f"    loginctl enable-linger {os.getlogin() if hasattr(os, 'getlogin') else 'tuo_utente'}")

def uninstall():
    """Arresta e rimuove i servizi utente systemd su Linux."""
    labels = ["secondbrain", "secondbrain-telegram", "secondbrain-whatsapp"]
    
    for label in labels:
        print(f"Arresto del servizio {label}...")
        subprocess.run(["systemctl", "--user", "stop", f"{label}.service"], capture_output=True)
        print(f"Disabilitazione del servizio {label}...")
        subprocess.run(["systemctl", "--user", "disable", f"{label}.service"], capture_output=True)
        
        service_file = os.path.join(SYSTEMD_USER_DIR, f"{label}.service")
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
