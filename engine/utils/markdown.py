import os
import re
import yaml

# Regex for wikilinks like [[My Page]] or [[My Page|Display Text]]
# Supports nested brackets in both target and display text (e.g. [[Algorave [in serata]]])
WIKILINK_RE = re.compile(r'\[\[((?:[^\[\]|]|\[[^\]|]*\])+)(?:\|(?:[^\]]|\[[^\]]*\])+)?\]\]')

def parse_markdown(content: str) -> tuple[dict, str]:
    """
    Parses a markdown string containing YAML frontmatter.
    
    Args:
        content: The raw markdown content.
        
    Returns:
        A tuple of (frontmatter_dict, body_string).
    """
    if not content:
        return {}, ""
        
    # Match starting with --- (followed by carriage return / newline)
    # Then any content non-greedily
    # Then --- followed by optional carriage return / newline / end of string
    pattern = r"^---\r?\n(.*?)\r?\n---(?:\r?\n|$)"
    match = re.match(pattern, content, re.DOTALL)
    if match:
        fm_text = match.group(1)
        body = content[match.end():]
        try:
            fm_data = yaml.safe_load(fm_text) or {}
            return fm_data, body
        except yaml.YAMLError:
            pass
            
    return {}, content

def to_markdown(frontmatter: dict, body: str) -> str:
    """
    Serializes frontmatter dict and body string back into a markdown document.
    """
    if not frontmatter:
        return body
        
    try:
        fm_str = yaml.safe_dump(frontmatter, sort_keys=False, default_flow_style=False, allow_unicode=True, width=1000)
        return f"---\n{fm_str}---\n{body}"
    except Exception:
        return body

def extract_wikilinks(content: str) -> list[str]:
    """
    Extracts all target pages of Wikilinks in the text.
    For [[Page Name|Display]], returns 'Page Name'.
    Handles frontmatter YAML parsing to resolve double-escaped characters (like double single quotes).
    """
    if not content:
        return []
        
    targets = []
    
    # 1. Parse frontmatter to get clean strings unescaped by the YAML parser
    fm, body = parse_markdown(content)
    
    def extract_from_value(val):
        if isinstance(val, str):
            # Extract wikilinks from the clean string
            for match in WIKILINK_RE.findall(val):
                targets.append(match.strip())
        elif isinstance(val, list):
            for item in val:
                extract_from_value(item)
        elif isinstance(val, dict):
            for v in val.values():
                extract_from_value(v)
                
    extract_from_value(fm)
    
    # 2. Extract from the markdown body
    for match in WIKILINK_RE.findall(body):
        targets.append(match.strip())
        
    return list(dict.fromkeys(targets))

def load_settings(vault_path: str) -> dict:
    """
    Loads configuration settings from settings.md in the vault root.
    """
    settings_file = os.path.join(vault_path, "settings.md")
    default_settings = {
        "timing": {
            "sync_and_ingest": "3600",
            "weekly_reflection": "0 21 * * 0"
        },
        "sources": {
            "notion": {"enabled": False, "database_ids": []},
            "google_drive": {"enabled": False, "local_path": ""},
            "apple_mail": {
                "enabled": False,
                "mailbox": "SecondBrain",
                "attachments_dir": "raw/mail_attachments",
                "sync_all_accounts": False,
                "days_back": 30
            },
            "web": {
                "enabled": False,
                "urls": []
            },
            "meeting_agent": {
                "enabled": True,
                "meetings_dir": "Meetings",
                "people_dir": "People",
                "microthemes_dir": "Microthemes"
            }
        },
        "models": {
            "query_agent": "gemini-3.5-flash",
            "ingest_agent": "gemini-3.5-flash",
            "reflect_agent": "gemini-3.5-flash",
            "temperature": 0.2
        },
        "preferences": {
            "auto_commit": True,
            "git_author": "Second Brain Agent <agent@secondbrain.local>"
        }
    }
    
    if not os.path.exists(settings_file):
        return default_settings
        
    try:
        with open(settings_file, "r", encoding="utf-8") as f:
            content = f.read()
        fm, _ = parse_markdown(content)
        
        # Merge parsed frontmatter with defaults to ensure all keys are present
        if fm:
            for key in fm:
                if key in default_settings and isinstance(default_settings[key], dict) and isinstance(fm[key], dict):
                    # Deep merge one level
                    for subkey in fm[key]:
                        default_settings[key][subkey] = fm[key][subkey]
                else:
                    default_settings[key] = fm[key]
                    
    except Exception as e:
        print(f"Errore durante la lettura di settings.md: {e}. Vengono usate le impostazioni di default.")
        
    return default_settings
