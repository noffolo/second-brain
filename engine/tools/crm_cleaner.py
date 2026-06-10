import os
import re
from engine.utils.markdown import parse_markdown, to_markdown
from engine.tools.vault_tools import get_vault_path

def clean_crm_contacts():
    vault = get_vault_path()
    print(f"Avvio pulizia contatti CRM in: {vault}...")

    # 1. Costruiamo l'insieme di tutti i titoli e file attivi nel vault (escluso CRM)
    all_files_in_vault = set()
    for root, dirs, files in os.walk(vault):
        rel_dir = os.path.relpath(root, vault)
        if rel_dir.startswith("CRM") or rel_dir == "CRM" or rel_dir.startswith("."):
            continue
        for f in files:
            if f.endswith(".md") and not f.startswith("."):
                all_files_in_vault.add(f)
                all_files_in_vault.add(f[:-3])

    crm_dir = os.path.join(vault, "CRM")
    if not os.path.exists(crm_dir):
        print("Cartella CRM non trovata!")
        return

    crm_files = [os.path.join(crm_dir, f) for f in os.listdir(crm_dir) if f.endswith(".md") and f != "index.md" and not f.startswith(".")]
    cleaned_count = 0

    for filepath in crm_files:
        filename = os.path.basename(filepath)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            fm, body = parse_markdown(content)
            if not fm:
                continue

            # A. Filtro dei bullet points sotto "Attività e Storico Partecipazioni"
            lines = body.splitlines()
            new_lines = []
            in_activities_section = False
            remaining_activities = 0

            for line in lines:
                stripped = line.strip()
                if stripped.startswith("## Attività e Storico Partecipazioni"):
                    in_activities_section = True
                    new_lines.append(line)
                    continue
                elif stripped.startswith("## ") or stripped.startswith("# ") or stripped.startswith("### "):
                    in_activities_section = False
                    new_lines.append(line)
                    continue

                if in_activities_section and stripped.startswith("- "):
                    # Estrae il nome del file sorgente
                    match = re.search(r"Fonte:\s*`([^`]+)`", line, re.IGNORECASE)
                    if match:
                        source_name = match.group(1).strip()
                        if source_name in all_files_in_vault or os.path.basename(source_name) in all_files_in_vault:
                            new_lines.append(line)
                            remaining_activities += 1
                    else:
                        new_lines.append(line)
                else:
                    new_lines.append(line)

            body = "\n".join(new_lines) + "\n"

            # B. Pulisci le sezioni di aggiornamento "### Aggiornamento da [[Title]]"
            pattern = r"(###\s+Aggiornamento\s+da\s+\[\[([^\]|]+)(?:\|[^\]]*)?\]\])"
            matches = re.findall(pattern, body, re.IGNORECASE)

            to_remove_headers = []
            for full_match, title_or_path in matches:
                title = os.path.basename(title_or_path).strip()
                if title not in all_files_in_vault:
                    to_remove_headers.append(full_match)

            if to_remove_headers:
                for header in to_remove_headers:
                    esc_header = re.escape(header)
                    section_pattern = rf"{esc_header}.*?(?=\n#+ |$)"
                    body = re.sub(section_pattern, "", body, flags=re.DOTALL)
                body = re.sub(r"\n{3,}", "\n\n", body).strip() + "\n"

            # C. Aggiorna interactions_count
            old_count = fm.get("interactions_count", 0)
            fm["interactions_count"] = remaining_activities

            new_content = to_markdown(fm, body)
            if new_content != content or old_count != remaining_activities:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(new_content)
                cleaned_count += 1
        except Exception as e:
            print(f"Errore durante la pulizia di {filename}: {e}")

    print(f"Pulizia completata. Aggiornati {cleaned_count} contatti CRM.")
