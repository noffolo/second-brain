import os
import subprocess
from engine.utils.markdown import load_settings

def auto_commit(vault_path: str, message: str) -> bool:
    """
    Stages all changes in the vault and commits them with the given message.
    Reads preferences.auto_commit and preferences.git_author from settings.md.
    """
    settings = load_settings(vault_path)
    preferences = settings.get("preferences", {})
    
    if not preferences.get("auto_commit", True):
        print("Git auto_commit disabilitato nelle impostazioni.")
        return False
        
    git_author = preferences.get("git_author", "Second Brain Agent <agent@secondbrain.local>")
    
    # Check if vault is a git repository
    if not os.path.exists(os.path.join(vault_path, ".git")):
        print(f"Directory {vault_path} non è un repository Git. Salto commit.")
        return False
        
    try:
        # We try using git command line via subprocess as it is always installed on macOS
        # and doesn't depend on GitPython virtualenv quirks
        
        # 1. Add all changed files (excluding gitignored ones)
        subprocess.run(["git", "add", "."], cwd=vault_path, check=True, capture_output=True)
        
        # 2. Check if there are changes to commit
        status_res = subprocess.run(
            ["git", "status", "--porcelain"], cwd=vault_path, check=True, capture_output=True, text=True
        )
        if not status_res.stdout.strip():
            # No changes to commit
            return True
            
        # 3. Commit changes with author spec
        commit_cmd = ["git", "commit", "-m", message]
        
        # Parse author name and email
        if git_author and " <" in git_author and git_author.endswith(">"):
            parts = git_author.split(" <")
            name = parts[0].strip()
            email = parts[1][:-1].strip()
            commit_cmd.extend(["--author", f"{name} <{email}>"])
            
        res = subprocess.run(commit_cmd, cwd=vault_path, check=True, capture_output=True, text=True)
        print(f"Commit effettuato: {message}")
        return True
        
    except Exception as e:
        print(f"Errore durante l'operazione Git auto_commit: {e}")
        return False

def export_clean_codebase(vault_path: str, target_dir: str) -> bool:
    """
    Esporta la codebase pulita (solo i file tracciati in Git) in una directory di destinazione.
    Questo crea una copia pulita del motore senza dati personali del vault (wiki, CRM, diari),
    pronta per essere pubblicata o tracciata in un repository pubblico.
    """
    import shutil
    target_dir = os.path.abspath(target_dir)
    vault_path = os.path.abspath(vault_path)
    
    if target_dir == vault_path:
        print("Errore: la directory di destinazione coincide con la directory corrente.")
        return False
        
    print(f"Esportazione codebase pulita in: {target_dir}...")
    try:
        # Ottieni la lista dei file tracciati in Git senza escape dei caratteri non-ASCII
        res = subprocess.run(
            ["git", "-c", "core.quotepath=false", "ls-files"], cwd=vault_path, check=True, capture_output=True, text=True
        )
        tracked_files = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        
        if not tracked_files:
            print("Errore: nessun file tracciato nel repository Git corrente.")
            return False
            
        os.makedirs(target_dir, exist_ok=True)
        
        for rel_path in tracked_files:
            src_file = os.path.join(vault_path, rel_path)
            dest_file = os.path.join(target_dir, rel_path)
            
            # Crea le sottodirectory necessarie
            os.makedirs(os.path.dirname(dest_file), exist_ok=True)
            
            # Copia il file preservando i metadati
            shutil.copy2(src_file, dest_file)
            
        print(f"Esportati con successo {len(tracked_files)} file in {target_dir}.")
        return True
    except Exception as e:
        print(f"Errore durante l'esportazione: {e}")
        return False
