"""Source authoring preserves identity, diagnostics, and permission boundaries."""

from test_image_jobs import upload
from test_template_logic_integration import accounts as account_fixture
from test_template_logic_integration import document

from app.logic_authoring import reconcile_program, source_diagnostic
from app.logic_engine import LogicError
from app.logic_schema import Program
from app.logic_source import compile_source
from app.template_logic import logic_fields, logic_targets

accounts = account_fixture


def compile_for(doc, source):
    return compile_source(source, logic_fields(doc), logic_targets(doc))


def test_reconciliation_preserves_distinct_equal_nodes_and_splits_changed_shared_nodes():
    doc = document()
    old = compile_for(doc, "text1.height = 12; text2.height = 12;")
    old.bindings[0].expression.node_id = "first"
    old.bindings[1].expression.node_id = "second"
    new = reconcile_program(old, compile_for(doc, "text1.height = 12; text2.height = 12;"))
    assert [binding.expression.node_id for binding in new.bindings] == ["first", "second"]
    old.bindings[1].expression.node_id = "first"
    new = reconcile_program(old, compile_for(doc, "text1.height = 14; text2.height = 12;"))
    assert new.bindings[0].expression.node_id != "first"
    assert new.bindings[1].expression.node_id == "first"


def test_reconciliation_keeps_call_identity_and_unchanged_sibling():
    doc = document()
    old = reconcile_program(Program(), compile_for(doc, "text1.height = if(enabled, 12, 14);"))
    new = reconcile_program(old, compile_for(doc, "text1.height = if(enabled, 10, 14);"))
    assert new.bindings[0].expression.node_id == old.bindings[0].expression.node_id
    assert new.bindings[0].expression.kind == "call"
    assert old.bindings[0].expression.kind == "call"
    assert (
        new.bindings[0].expression.arguments[2].node_id
        == old.bindings[0].expression.arguments[2].node_id
    )


def test_source_diagnostic_uses_browser_offsets():
    source = '// 😀\nlet title = "😀"; unknown'
    offset = source.index("unknown")
    issue = source_diagnostic(LogicError("Unknown variable", offset=offset), source)
    assert issue["from"] == offset + 2
    assert issue["to"] == offset + 3
    assert issue["line"] == 2
    assert issue["column"] == 19
    assert source_diagnostic(LogicError("Invalid token", offset=2), "\ud800 ?")["from"] == 2


def test_compile_endpoint_reports_errors_without_replacing_program(client):
    raw = document().model_dump(mode="json")
    original = raw["logic"]
    source = "// keep this comment\nlet amount = quantity * 2; text1.height = amount;"
    result = client.post("/api/logic/compile", json={"document": raw, "source": source})
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["valid"] and not body["diagnostics"]
    assert body["catalog"]["values"]["amount"] == 6
    assert body["program"]["bindings"][0]["target"] == "title-id"
    assert raw["logic"] == original
    for invalid in ("text1.height = true;", "let a = b; let b = a;", "text1.height = fetch(3);"):
        result = client.post("/api/logic/compile", json={"document": raw, "source": invalid})
        assert result.status_code == 200
        assert not result.json()["valid"]
        assert result.json()["diagnostics"][0]["severity"] == "error"
        assert "program" not in result.json()


def test_compile_length_mode_and_saved_source_metadata(client):
    raw = document(automatic=True).model_dump(mode="json")
    source = "label.length_mm = 50;"
    result = client.post("/api/logic/compile", json={"document": raw, "source": source}).json()
    assert not result["valid"]
    assert "automatic label length" in result["diagnostics"][0]["message"]
    raw["auto_length"] = False
    result = client.post("/api/logic/compile", json={"document": raw, "source": source}).json()
    assert result["valid"]
    raw["logic"] = result["program"]
    raw["logic_editor"] = {"version": 1, "nodes": [], "source": "// Preserved\n" + source}
    inspected = client.post("/api/logic/inspect", json=raw).json()
    assert inspected["source"] == "// Preserved\n" + source
    raw["logic_editor"]["source"] = "label.length_mm = 90;"
    assert client.post("/api/logic/inspect", json=raw).json()["source"] == result["formatted"]
    raw["logic_editor"]["source"] = "invalid"
    assert client.post("/api/logic/inspect", json=raw).json()["source"] == result["formatted"]


def test_compile_image_literals_require_asset_access(accounts):
    _, alice, bob = accounts
    image, _ = upload(alice)
    raw = document(source="", image=True).model_dump(mode="json")
    body = {"document": raw, "source": f'picture.image_asset = image("{image}");'}
    response = alice.post("/api/logic/compile", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["valid"]
    assert bob.post("/api/logic/compile", json=body).status_code == 403
    body["source"] = 'picture.image_asset = image("https://example.com/photo.png");'
    assert not alice.post("/api/logic/compile", json=body).json()["valid"]


def test_saved_source_equivalence_ignores_declaration_order_and_numeric_spelling(client):
    raw = document("let a = 1; let b = 2; text1.height = a + b;").model_dump(mode="json")
    raw["logic"]["variables"]["a"]["value"] = 1
    source = "// order is independent\nlet b = 2.0; let a = 1; text1.height = a + b;"
    raw["logic_editor"] = {"version": 1, "nodes": [], "source": source}
    response = client.post("/api/logic/inspect", json=raw)
    assert response.status_code == 200, response.text
    assert response.json()["source"] == source
