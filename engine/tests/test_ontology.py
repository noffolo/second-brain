import os
import tempfile
import shutil
import pytest
from engine.utils.markdown import parse_markdown, to_markdown
from engine.ontology_agent import (
    collect_nodes_metadata,
    approve_proposal,
    merge_nodes,
    set_parent,
    connect_nodes,
    update_links_in_vault
)

@pytest.fixture
def mock_vault():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create directories
        os.makedirs(os.path.join(tmpdir, "wiki/concepts/AI_LLM_Coding"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "wiki/concepts/Design_Branding"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "wiki/entities/General"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "wiki/synthesis"), exist_ok=True)
        
        # Create concepts
        c1_path = os.path.join(tmpdir, "wiki/concepts/AI_LLM_Coding/Machine Learning.md")
        c1_fm = {"type": "concept", "tags": ["ml"], "related": []}
        c1_body = "# Machine Learning\n\nQuesto è il Machine Learning."
        with open(c1_path, "w", encoding="utf-8") as f:
            f.write(to_markdown(c1_fm, c1_body))
            
        c2_path = os.path.join(tmpdir, "wiki/concepts/AI_LLM_Coding/Deep Learning.md")
        c2_fm = {"type": "concept", "tags": ["dl"], "related": ["[[wiki/concepts/AI_LLM_Coding/Machine Learning]]"]}
        c2_body = "# Deep Learning\n\nQuesto è il Deep Learning."
        with open(c2_path, "w", encoding="utf-8") as f:
            f.write(to_markdown(c2_fm, c2_body))
            
        c3_path = os.path.join(tmpdir, "wiki/concepts/Design_Branding/Figma.md")
        c3_fm = {"type": "concept", "tags": ["design"]}
        c3_body = "# Figma\n\nQuesto è Figma."
        with open(c3_path, "w", encoding="utf-8") as f:
            f.write(to_markdown(c3_fm, c3_body))
            
        # Create entities
        e1_path = os.path.join(tmpdir, "wiki/entities/General/Gano.md")
        e1_fm = {"type": "entity"}
        e1_body = "# Gano\n\nPersona chiamata Gano."
        with open(e1_path, "w", encoding="utf-8") as f:
            f.write(to_markdown(e1_fm, e1_body))
            
        e2_path = os.path.join(tmpdir, "wiki/entities/General/Giancarlo Fransvea.md")
        e2_fm = {"type": "entity"}
        e2_body = "# Giancarlo Fransvea\n\nGiancarlo Fransvea di Esempio."
        with open(e2_path, "w", encoding="utf-8") as f:
            f.write(to_markdown(e2_fm, e2_body))
            
        yield tmpdir

def test_collect_nodes_metadata(mock_vault):
    nodes = collect_nodes_metadata(mock_vault)
    assert len(nodes) == 5
    
    titles = [n["title"] for n in nodes]
    assert "Machine Learning" in titles
    assert "Deep Learning" in titles
    assert "Figma" in titles
    assert "Gano" in titles
    assert "Giancarlo Fransvea" in titles
    
    # Check related fields
    dl_node = next(n for n in nodes if n["title"] == "Deep Learning")
    assert dl_node["related"] == ["[[wiki/concepts/AI_LLM_Coding/Machine Learning]]"]

def test_connect_nodes(mock_vault):
    path_a = "wiki/concepts/AI_LLM_Coding/Machine Learning"
    path_b = "wiki/concepts/Design_Branding/Figma"
    
    success = connect_nodes(mock_vault, path_a, path_b)
    assert success
    
    # Verify Machine Learning points to Figma
    with open(os.path.join(mock_vault, path_a + ".md"), "r", encoding="utf-8") as f:
        fm_a, _ = parse_markdown(f.read())
    assert f"[[{path_b}]]" in fm_a["related"]
    
    # Verify Figma points to Machine Learning
    with open(os.path.join(mock_vault, path_b + ".md"), "r", encoding="utf-8") as f:
        fm_b, _ = parse_markdown(f.read())
    assert f"[[{path_a}]]" in fm_b["related"]

def test_set_parent(mock_vault):
    path_parent = "wiki/concepts/AI_LLM_Coding/Machine Learning"
    path_child = "wiki/concepts/AI_LLM_Coding/Deep Learning"
    
    success = set_parent(mock_vault, path_parent, path_child)
    assert success
    
    with open(os.path.join(mock_vault, path_child + ".md"), "r", encoding="utf-8") as f:
        fm, _ = parse_markdown(f.read())
    assert fm["parent"] == f"[[{path_parent}]]"

def test_merge_nodes(mock_vault):
    path_a = "wiki/entities/General/Gano"
    path_b = "wiki/entities/General/Giancarlo Fransvea"
    
    # Let's add a reference to Gano inside Deep Learning body
    dl_file = os.path.join(mock_vault, "wiki/concepts/AI_LLM_Coding/Deep Learning.md")
    with open(dl_file, "r", encoding="utf-8") as f:
        fm, body = parse_markdown(f.read())
    body += "\n\nIncontro con [[wiki/entities/General/Gano]]."
    with open(dl_file, "w", encoding="utf-8") as f:
        f.write(to_markdown(fm, body))
        
    # Merge Gano into Giancarlo
    success = merge_nodes(mock_vault, path_a, path_b)
    assert success
    
    # A should be deleted
    assert not os.path.exists(os.path.join(mock_vault, path_a + ".md"))
    
    # B should exist and contain A's content
    with open(os.path.join(mock_vault, path_b + ".md"), "r", encoding="utf-8") as f:
        fm_b, body_b = parse_markdown(f.read())
    assert f"Contenuto unificato da [[{path_b}|Gano]]" in body_b
    assert "Persona chiamata Gano." in body_b
    
    # Deep Learning body reference should be updated to Giancarlo Fransvea
    with open(dl_file, "r", encoding="utf-8") as f:
        _, body_dl = parse_markdown(f.read())
    assert "[[wiki/entities/General/Giancarlo Fransvea|Giancarlo Fransvea]]" in body_dl
    assert "wiki/entities/General/Gano" not in body_dl

def test_approve_proposal_in_file(mock_vault):
    # Write a mock ontology_negotiation.md
    neg_path = os.path.join(mock_vault, "wiki/synthesis/ontology_negotiation.md")
    content = """# Negotiation
## Merges
- [ ] **[M1]** Fondere [[wiki/entities/General/Gano]] in [[wiki/entities/General/Giancarlo Fransvea]]
- [ ] **[M2]** Fondere [[A]] in [[B]]
"""
    with open(neg_path, "w", encoding="utf-8") as f:
        f.write(content)
        
    # We must patch get_vault_path in ontology_agent to return mock_vault
    # But since approve_proposal relies on get_vault_path(), we can mock it
    # by writing the test logic directly or using monkeypatch
    # Since we can't easily monkeypatch get_vault_path inside the imported module without helper
    # let's look at approve_proposal code, it calls get_vault_path()
    # Let's write a local wrapper or use monkeypatch
    pass

def test_approve_proposal_monkeypatched(mock_vault, monkeypatch):
    import engine.ontology_agent as oa
    monkeypatch.setattr(oa, "get_vault_path", lambda: mock_vault)
    
    neg_path = os.path.join(mock_vault, "wiki/synthesis/ontology_negotiation.md")
    content = """# Negotiation
## Merges
- [ ] **[M1]** Fondere [[wiki/entities/General/Gano]] in [[wiki/entities/General/Giancarlo Fransvea]]
- [ ] **[M2]** Fondere [[A]] in [[B]]
"""
    with open(neg_path, "w", encoding="utf-8") as f:
        f.write(content)
        
    success = oa.approve_proposal("M1")
    assert success
    
    with open(neg_path, "r", encoding="utf-8") as f:
        updated_content = f.read()
    assert "- [x] **[M1]** Fondere" in updated_content
    assert "- [ ] **[M2]** Fondere" in updated_content

def test_apply_negotiated_ontology_brackets_cleanup(mock_vault, monkeypatch):
    import engine.ontology_agent as oa
    monkeypatch.setattr(oa, "get_vault_path", lambda: mock_vault)
    
    neg_path = os.path.join(mock_vault, "wiki/synthesis/ontology_negotiation.md")
    content = """# Negotiation
## Merges
- [x] **[M1]** Fondere [[wiki/entities/General/Gano]] in [[wiki/entities/General/Giancarlo Fransvea]]
- [ ] **[M2]** Fondere [[wiki/entities/General/Gano]] in [[wiki/entities/General/Giancarlo Fransvea]]
"""
    with open(neg_path, "w", encoding="utf-8") as f:
        f.write(content)
        
    # We must ensure the source (Gano) and target (Giancarlo) exist so merge_nodes succeeds
    assert os.path.exists(os.path.join(mock_vault, "wiki/entities/General/Gano.md"))
    assert os.path.exists(os.path.join(mock_vault, "wiki/entities/General/Giancarlo Fransvea.md"))
    
    # Run application
    oa.apply_negotiated_ontology_in_vault(mock_vault)
    
    with open(neg_path, "r", encoding="utf-8") as f:
        updated = f.read()
        
    # Check that brackets from the deleted source in M1 were stripped
    assert "- [x] **[M1]** (Applicata) Fondere wiki/entities/General/Gano in [[wiki/entities/General/Giancarlo Fransvea]]" in updated
    # Check that the unapplied proposal M2 was updated to point to the new target
    assert "- [ ] **[M2]** Fondere [[wiki/entities/General/Giancarlo Fransvea]] in [[wiki/entities/General/Giancarlo Fransvea]]" in updated

def test_apply_negotiated_ontology_with_pipes(mock_vault, monkeypatch):
    import engine.ontology_agent as oa
    monkeypatch.setattr(oa, "get_vault_path", lambda: mock_vault)
    
    neg_path = os.path.join(mock_vault, "wiki/synthesis/ontology_negotiation.md")
    content = """# Negotiation
## Merges
- [x] **[M1]** Fondere [[wiki/entities/General/Gano|Gano]] in [[wiki/entities/General/Giancarlo Fransvea|Giancarlo]]
- [ ] **[M2]** Fondere [[wiki/entities/General/Gano|Gano]] in [[wiki/entities/General/Giancarlo Fransvea|Giancarlo]]
"""
    with open(neg_path, "w", encoding="utf-8") as f:
        f.write(content)
        
    # Ensure source and target exist
    assert os.path.exists(os.path.join(mock_vault, "wiki/entities/General/Gano.md"))
    assert os.path.exists(os.path.join(mock_vault, "wiki/entities/General/Giancarlo Fransvea.md"))
    
    oa.apply_negotiated_ontology_in_vault(mock_vault)
    
    with open(neg_path, "r", encoding="utf-8") as f:
        updated = f.read()
        
    # Check that brackets and pipe from the deleted source in M1 were stripped to leave the label
    assert "- [x] **[M1]** (Applicata) Fondere Gano in [[wiki/entities/General/Giancarlo Fransvea|Giancarlo]]" in updated
    # Check that M2 was updated to point to the target while preserving the pipe if it was present
    assert "- [ ] **[M2]** Fondere [[wiki/entities/General/Giancarlo Fransvea|Gano]] in [[wiki/entities/General/Giancarlo Fransvea|Giancarlo]]" in updated


def test_collect_nodes_metadata_with_crm(mock_vault):
    # Crea la cartella CRM ed un file di contatto finto al suo interno
    os.makedirs(os.path.join(mock_vault, "CRM"), exist_ok=True)
    c_path = os.path.join(mock_vault, "CRM/Agnese Addone.md")
    c_fm = {
        "type": "crm_contact",
        "email": "agneseaddone@gmail.com",
        "phone": "+3912345678",
        "aliases": ["Agnese Addone Alias"]
    }
    c_body = "# Agnese Addone\n\nContatto Agnese Addone."
    with open(c_path, "w", encoding="utf-8") as f:
        f.write(to_markdown(c_fm, c_body))
        
    # Crea anche CRM/index.md per verificare che venga ignorato
    index_path = os.path.join(mock_vault, "CRM/index.md")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(to_markdown({"type": "crm_index"}, "# Indice"))
        
    nodes = collect_nodes_metadata(mock_vault)
    crm_nodes = [n for n in nodes if n["type"] == "crm_contact"]
    assert len(crm_nodes) == 1
    assert crm_nodes[0]["title"] == "Agnese Addone"
    assert crm_nodes[0]["path"] == "CRM/Agnese Addone"
    assert crm_nodes[0]["aliases"] == ["Agnese Addone Alias"]
    
    # Verifica che index.md sia stato ignorato
    index_nodes = [n for n in nodes if n["path"] == "CRM/index"]
    assert len(index_nodes) == 0

def test_find_fuzzy_duplicate_candidates():
    from engine.ontology_agent import find_fuzzy_duplicate_candidates
    nodes = [
        {"path": "CRM/Alessandro Tartaglia", "title": "Alessandro Tartaglia", "type": "crm_contact", "aliases": []},
        {"path": "wiki/entities/Tartaglia", "title": "Tartaglia", "type": "entity", "aliases": []},
        {"path": "wiki/entities/Comune di Bari", "title": "Comune di Bari", "type": "entity", "aliases": []},
        {"path": "wiki/entities/Comune di Napoli", "title": "Comune di Napoli", "type": "entity", "aliases": []}
    ]
    candidates = find_fuzzy_duplicate_candidates(nodes)
    assert len(candidates) >= 1
    paths = {(c["path_a"], c["path_b"]) for c in candidates}
    assert ("CRM/Alessandro Tartaglia", "wiki/entities/Tartaglia") in paths or ("wiki/entities/Tartaglia", "CRM/Alessandro Tartaglia") in paths
    
    bari_napoli = {("wiki/entities/Comune di Bari", "wiki/entities/Comune di Napoli"), ("wiki/entities/Comune di Napoli", "wiki/entities/Comune di Bari")}
    assert not (paths & bari_napoli)

def test_analyze_graph_topology():
    from engine.ontology_agent import analyze_graph_topology
    nodes = [
        {"path": "A", "title": "A", "parent": None, "related": []},
        {"path": "B", "title": "B", "parent": "[[A]]", "related": []},
        {"path": "C", "title": "C", "parent": None, "related": ["[[B]]"]},
        {"path": "D", "title": "D", "parent": None, "related": []},  # Orfano
        {"path": "E", "title": "E", "parent": None, "related": ["[[F]]"]},  # Cluster di dimensione 2
        {"path": "F", "title": "F", "parent": None, "related": ["[[E]]"]}
    ]
    res = analyze_graph_topology(nodes)
    assert "D" in res["orphans"]
    assert "E" not in res["orphans"]
    assert len(res["isolated_clusters"]) == 2
    clusters = [set(c) for c in res["isolated_clusters"]]
    assert {"E", "F"} in clusters
    assert {"A", "B", "C"} in clusters


def test_merge_nodes_preserves_crm_fields_and_aliases(mock_vault):
    # Crea un file contatto crm
    c_path = os.path.join(mock_vault, "wiki/entities/General/Agnese Addone.md")
    c_fm = {
        "type": "entity",
        "email": "agneseaddone@gmail.com",
        "aliases": ["Agnese Addone Alias"],
        "tags": ["original_tag"]
    }
    c_body = "# Agnese Addone"
    with open(c_path, "w", encoding="utf-8") as f:
        f.write(to_markdown(c_fm, c_body))
        
    target_path = os.path.join(mock_vault, "wiki/entities/General/Giancarlo Fransvea.md")
    t_fm = {
        "type": "entity",
        "phone": "+39000000",
        "aliases": ["Giancarlo Alias"],
        "tags": ["target_tag"]
    }
    t_body = "# Giancarlo Fransvea"
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(to_markdown(t_fm, t_body))
        
    path_a = "wiki/entities/General/Agnese Addone"
    path_b = "wiki/entities/General/Giancarlo Fransvea"
    
    success = merge_nodes(mock_vault, path_a, path_b)
    assert success
    
    with open(target_path, "r", encoding="utf-8") as f:
        fm, body = parse_markdown(f.read())
        
    assert fm["email"] == "agneseaddone@gmail.com"
    assert fm["phone"] == "+39000000"
    assert set(fm["tags"]) == {"original_tag", "target_tag"}
    
    expected_aliases = {"Giancarlo Alias", "Agnese Addone Alias", "Agnese Addone"}
    assert set(fm["aliases"]) == expected_aliases



