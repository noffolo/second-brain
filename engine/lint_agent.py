import os
import re
from engine.utils.markdown import load_settings, extract_wikilinks
from engine.tools.vault_tools import get_vault_path, append_to_log
from engine.git_ops import auto_commit

def run_lint() -> dict:
    """
    Scans the vault to find broken wikilinks and orphan pages.
    Logs the results in log.md and returns the statistics.
    """
    vault = get_vault_path()
    
    # 1. Map out all existing markdown files (excluding configuration/system files)
    system_files = ["settings.md", "agents.md", "chat.md", "index.md", "log.md", "README.md", "user_profile.md"]
    
    # Existing pages mapping: title_lowercase -> relative_path, and rel_path_no_ext_lowercase -> relative_path
    existing_pages = {}
    all_pages = []
    
    search_dirs = ["wiki", "CRM", "journal", "Meetings", "Microthemes"]
    for sdir in search_dirs:
        abs_sdir = os.path.join(vault, sdir)
        if not os.path.exists(abs_sdir):
            continue
        for root, _, files in os.walk(abs_sdir):
            for file in files:
                if file.endswith(".md") and not file.startswith("."):
                    abs_path = os.path.join(root, file)
                    rel_path = os.path.relpath(abs_path, vault)
                    
                    title = file.replace(".md", "")
                    existing_pages[title.lower()] = rel_path
                    
                    # Also map full relative path without extension
                    rel_path_no_ext = rel_path.replace(".md", "")
                    existing_pages[rel_path_no_ext.lower()] = rel_path
                    
                    all_pages.append(rel_path)
                    
    # Initialize link counts
    incoming_links = {rel_path: [] for rel_path in all_pages}
    broken_links = []
    
    # 2. Extract links and build graph
    for rel_path in all_pages:
        abs_path = os.path.join(vault, rel_path)
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
            
        links = extract_wikilinks(content)
        for link in links:
            # Check if this link target exists in existing_pages
            link_lower = link.lower()
            
            # Simple resolve: match by filename
            if link_lower in existing_pages:
                target_rel = existing_pages[link_lower]
                if target_rel != rel_path: # Don't count self-links
                    incoming_links[target_rel].append(rel_path)
            else:
                # Broken link
                broken_links.append((rel_path, link))
                
    # 3. Find orphan pages (0 incoming links)
    orphans = []
    for rel_path, incoming in incoming_links.items():
        # Exclude index or log files (already excluded since we search specific folders)
        # But we also check if it has zero incoming links
        if not incoming:
            # Check if it's not a synthesis page (synthesis reflections are naturally top-level)
            if not rel_path.startswith("wiki/synthesis"):
                orphans.append(rel_path)
                
    # 4. Generate report and write to log.md
    total_broken = len(broken_links)
    total_orphans = len(orphans)
    
    print(f"Lint completato. Link interrotti: {total_broken}, Pagine orfane: {total_orphans}")
    
    report_lines = []
    report_lines.append(f"[AI Lint] Verificato wiki. Link interrotti: {total_broken}, Pagine orfane: {total_orphans}")
    
    if total_broken > 0:
        report_lines.append("Link Interrotti rilevati:")
        for source, target in broken_links[:10]: # Log first 10
            report_lines.append(f"  - In '{source}': Link a [[{target}]] non risolto.")
        if total_broken > 10:
            report_lines.append(f"  - ... e altri {total_broken - 10} link interrotti.")
            
    if total_orphans > 0:
        report_lines.append("Pagine Orfane rilevate:")
        for orphan in orphans[:10]: # Log first 10
            report_lines.append(f"  - '{orphan}' non ha link in ingresso.")
        if total_orphans > 10:
            report_lines.append(f"  - ... e altre {total_orphans - 10} pagine orfane.")
            
    log_entry = "\n".join(report_lines)
    append_to_log(log_entry)
    
    # Git auto commit
    auto_commit(vault, f"[AI Lint] Eseguito audit wiki — Link interrotti: {total_broken}, Orfani: {total_orphans}")
    
    return {
        "broken_links_count": total_broken,
        "orphans_count": total_orphans,
        "broken_links": broken_links,
        "orphans": orphans
    }

if __name__ == "__main__":
    run_lint()
