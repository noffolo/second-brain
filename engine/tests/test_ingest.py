import os
import pytest
from engine.utils.markdown import to_markdown
from engine.ingest_agent import load_aliases_map, extract_candidate_entities, WikiIngestResponse

def test_load_aliases_map(tmp_path):
    # Setup temporary directories
    entities_dir = tmp_path / "wiki" / "entities"
    crm_dir = tmp_path / "CRM"
    
    os.makedirs(entities_dir, exist_ok=True)
    os.makedirs(crm_dir, exist_ok=True)
    
    # 1. Create a concept note (should be ignored by load_aliases_map)
    concepts_dir = tmp_path / "wiki" / "concepts"
    os.makedirs(concepts_dir, exist_ok=True)
    with open(concepts_dir / "Deep Learning.md", "w") as f:
        f.write("---\ntype: concept\n---\n# Deep Learning")
        
    # 2. Create an entity note with aliases
    with open(entities_dir / "Andrej Karpathy.md", "w") as f:
        content = to_markdown({"type": "entity", "aliases": ["Karpathy", "A. Karpathy"]}, "# Andrej Karpathy")
        f.write(content)
        
    # 3. Create a CRM note with aliases
    with open(crm_dir / "Alessandro Tartaglia.md", "w") as f:
        content = to_markdown({"type": "crm_contact", "name": "Alessandro Tartaglia", "aliases": ["AT", "Tartaglia"]}, "# Alessandro Tartaglia")
        f.write(content)
        
    # Run load_aliases_map
    aliases_map = load_aliases_map(str(tmp_path))
    
    # Assertions
    assert "andrej karpathy" in aliases_map
    assert "karpathy" in aliases_map
    assert "a. karpathy" in aliases_map
    
    assert "alessandro tartaglia" in aliases_map
    assert "at" in aliases_map
    assert "tartaglia" in aliases_map
    
    # Check ignored concept
    assert "deep learning" not in aliases_map
    
    # Verify values mapped
    assert aliases_map["at"]["canonical"] == "Alessandro Tartaglia"
    assert aliases_map["at"]["type"] == "crm"
    assert "CRM/Alessandro Tartaglia.md" in aliases_map["at"]["path"]
    
    assert aliases_map["karpathy"]["canonical"] == "Andrej Karpathy"
    assert aliases_map["karpathy"]["type"] == "entities"

def test_extract_candidate_entities():
    aliases_map = {
        "andrej karpathy": {"canonical": "Andrej Karpathy", "path": "wiki/entities/Andrej Karpathy.md"},
        "karpathy": {"canonical": "Andrej Karpathy", "path": "wiki/entities/Andrej Karpathy.md"},
        "alessandro tartaglia": {"canonical": "Alessandro Tartaglia", "path": "CRM/Alessandro Tartaglia.md"},
        "at": {"canonical": "Alessandro Tartaglia", "path": "CRM/Alessandro Tartaglia.md"},
        "cnr": {"canonical": "Consiglio Nazionale delle Ricerche", "path": "wiki/entities/CNR.md"}
    }
    
    # Test text containing exact names
    text1 = "Ieri ho parlato con Andrej Karpathy e con Alessandro Tartaglia presso la sede del CNR."
    candidates = extract_candidate_entities(text1, aliases_map)
    canonical_names = [c["canonical"] for c in candidates]
    
    assert "Andrej Karpathy" in canonical_names
    assert "Alessandro Tartaglia" in canonical_names
    assert "Consiglio Nazionale delle Ricerche" in canonical_names
    
    # Test text with minor typo (fuzzy match)
    text2 = "Abbiamo fatto una riunione con Alessandro Tartagla."
    candidates2 = extract_candidate_entities(text2, aliases_map)
    assert len(candidates2) == 1
    assert candidates2[0]["canonical"] == "Alessandro Tartaglia"

def test_pydantic_validation():
    # Valid JSON response
    valid_json = """{
        "is_noise": false,
        "source_summary": {
            "title": "Unione Sindacale di Base",
            "summary": "Riassunto del comunicato sindacale",
            "key_points": ["Punto 1", "Punto 2"],
            "tags": ["sindacato", "lavoro"]
        },
        "concepts": [],
        "entities": [
            {
                "name": "USB",
                "description": "Unione Sindacale di Base",
                "is_existing": true,
                "canonical_name": "USB"
            }
        ]
    }"""
    
    response = WikiIngestResponse.model_validate_json(valid_json)
    assert response.is_noise is False
    assert response.source_summary.title == "Unione Sindacale di Base"
    assert response.entities[0].name == "USB"
    assert response.entities[0].is_existing is True

def test_resolve_category_folder(tmp_path):
    from engine.ingest_agent import resolve_category_folder
    
    # Setup folders
    sources_dir = tmp_path / "wiki" / "sources"
    os.makedirs(sources_dir / "FF3300" / "USB", exist_ok=True)
    os.makedirs(sources_dir / "La_Scuola_Open_Source", exist_ok=True)
    os.makedirs(sources_dir / "General", exist_ok=True)
    
    # Test cases
    # 1. Exact last segment match: "Sindacati/USB" -> "FF3300/USB"
    res1 = resolve_category_folder(str(tmp_path), "sources", "Sindacati/USB")
    assert res1 == "FF3300/USB"
    
    # 2. Fuzzy overlap match: "Didattica/Scuola_Aperta" -> "La_Scuola_Open_Source" (shares "Scuola")
    res2 = resolve_category_folder(str(tmp_path), "sources", "Didattica/Scuola_Aperta")
    assert res2 == "La_Scuola_Open_Source"
    
    # 3. Default fallback when no match: "AI_LLM_Coding" -> "AI_LLM_Coding"
    res3 = resolve_category_folder(str(tmp_path), "sources", "AI_LLM_Coding")
    assert res3 == "AI_LLM_Coding"
