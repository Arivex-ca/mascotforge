"""Blobs sur mesure ecrits gratuitement par un agent."""
from __future__ import annotations

import copy
import io
import json
import re
import zipfile
from pathlib import Path

import pytest

from backend import blob
from mascotforge import cli
from mascotforge.client import MascotForgeClient


ROOT = Path(__file__).resolve().parents[1]
HORNED = json.loads((ROOT / "tests" / "fixtures" / "blob-deux-cornes.json").read_text(encoding="utf-8"))

HEADPHONES = {
    "name": "headphones",
    "anchor": "crown",
    "parts": [
        {
            "shape": "torus", "size": [1.2, 0.08], "material": "glossy-plastic",
            "at": [0, 0.08, 0], "rotate": [90, 0, 0], "arc": 180,
        },
        {
            "shape": "rounded-box", "size": [0.22, 0.42, 0.16, 0.06],
            "material": "knit", "anchor": "left-ear", "color": "lilac",
        },
        {
            "shape": "rounded-box", "size": [0.22, 0.42, 0.16, 0.06],
            "material": "knit", "anchor": "right-ear", "color": "lilac",
        },
    ],
}

ANIMAL_V2 = {
    "version": 2,
    "name": "Nola",
    "series": "animal",
    "animal": "bunny",
    "fabric": "knit",
    "color": "sky",
    "eyes": "dot",
    "cheeks": True,
    "accessories": ["glasses", HEADPHONES],
    "acc_color": "lilac",
    "states": [
        {"name": "sleeping", "like": "idle", "lid": 0.08, "breath": 4, "bob": 0},
        {
            "name": "celebrating", "like": "happy", "hop": 28, "hopSpeed": 2.4,
            "expression": "happy", "enterSparks": 6,
        },
    ],
}

CROWN = {
    "name": "crown",
    "anchor": "crown",
    "parts": [
        {"shape": "cylinder", "size": [0.72, 0.14], "material": "metal", "color": "mustard"},
        {
            "shape": "cone", "size": [0.14, 0.32], "material": "metal",
            "color": "#ffd873", "at": [0.16, 0.2, 0], "repeat": 5,
        },
    ],
}

BLOB_V2 = {
    "version": 2,
    "name": "Cornu royal",
    "series": "blob",
    "contour": HORNED["contour"],
    "material": "jelly",
    "color": "#8b5cf6",
    "eyes": "capsule",
    "cheeks": True,
    "accessories": [CROWN],
    "acc_color": "mustard",
    "states": [{"name": "sleeping", "like": "idle", "lid": 0.08, "breath": 4}],
}


def _api(test_client) -> MascotForgeClient:  # type: ignore[no-untyped-def]
    return MascotForgeClient(base_url="http://testserver", http_client=test_client)


def _messages(spec: dict) -> str:
    return " ".join(item["message"] for item in blob.check_spec(spec)["issues"])


def test_blob_guide_contains_complete_v2_animal_and_blob_examples(client):
    response = client.get("/api/engines/blob/guide")
    assert response.status_code == 200
    guide = response.json()["guide"]
    examples = [json.loads(raw) for raw in re.findall(r"```json\n(.*?)\n```", guide, re.DOTALL)]
    assert len(examples) >= 2
    assert {example["series"] for example in examples} >= {"animal", "blob"}
    assert all(blob.check_spec(example)["ok"] for example in examples)
    animal = next(example for example in examples if example["series"] == "animal")
    custom_blob = next(example for example in examples if example["series"] == "blob")
    assert {state["name"] for state in animal["states"]} == {"sleeping", "celebrating"}
    assert any(isinstance(item, dict) for item in animal["accessories"])
    assert custom_blob["contour"] and any(item.get("name") == "crown" for item in custom_blob["accessories"])


def test_blob_check_accepts_horns_and_returns_72_numeric_points(client):
    response = client.post("/api/engines/blob/specs/check", json={"spec": HORNED})
    assert response.status_code == 200
    report = response.json()
    assert report["ok"] and len(report["points"]) == 72
    assert all(len(point) == 2 and all(isinstance(value, float) for value in point) for point in report["points"])


def test_v2_accepts_animal_named_blob_and_custom_blob():
    animal = blob.compile_spec(ANIMAL_V2)
    assert animal["series"] == "animal"
    assert animal["config"]["shape"] == "bunny"
    assert animal["config"]["material"] == "knit"
    assert animal["config"]["accessory"] == "glasses headphones"
    assert list(animal["accessories"]) == ["headphones"]
    assert list(animal["states"]) == ["sleeping", "celebrating"]

    named = copy.deepcopy(BLOB_V2)
    named.pop("contour")
    named["shape"] = "cloud"
    assert blob.compile_spec(named)["config"]["shape"] == "cloud"

    custom = blob.compile_spec(BLOB_V2)
    assert custom["shape"].startswith("custom-") and len(custom["points"]) == 72


def test_v2_accepts_pause_badge_for_human_approval():
    waiting = copy.deepcopy(ANIMAL_V2)
    waiting["states"] = [
        {
            "name": "waiting-for-approval",
            "like": "idle",
            "gaze": [0, 0],
            "badge": "pause",
            "badgeColor": "#F5CF62",
        }
    ]

    report = blob.check_spec(waiting)
    assert report["ok"], report["issues"]
    compiled = blob.compile_spec(waiting)
    assert compiled["states"]["waiting-for-approval"]["badge"] == "pause"


def test_v1_remains_valid_and_compiles_without_v2_declarations():
    compiled = blob.compile_spec(HORNED)
    assert compiled["series"] == "blob"
    assert compiled["states"] == {}
    assert compiled["accessories"] == {}


def test_blob_check_rejects_crossing_thin_small_large_and_out_of_bounds():
    crossing = copy.deepcopy(HORNED)
    crossing["contour"] = {
        "base": {"kind": "round", "width": 1.1357, "height": 0.2789, "roundness": 4.4439},
        "bumps": [
            {"angle": 160.61, "height": -0.404, "width": 36.87},
            {"angle": 84.34, "height": -0.42, "width": 77.61},
        ],
    }
    assert "se croise" in _messages(crossing)

    thin = copy.deepcopy(HORNED)
    thin["contour"] = {"base": {"kind": "oval", "width": 0.2, "height": 1.2, "roundness": 2}, "bumps": []}
    assert "trop fin" in _messages(thin)

    small = copy.deepcopy(HORNED)
    small["contour"] = {"base": {"kind": "round", "width": 0.25, "height": 0.25, "roundness": 2}, "bumps": []}
    assert "trop petit" in _messages(small)

    large = copy.deepcopy(HORNED)
    large["contour"] = {"base": {"kind": "round", "width": 1.5, "height": 1.5, "roundness": 2}, "bumps": [{"angle": 0, "height": 1.2, "width": 30}]}
    assert "trop grand" in _messages(large)

    bounded = copy.deepcopy(HORNED)
    bounded["contour"]["bumps"][0]["width"] = 2
    assert "hors bornes" in _messages(bounded)


def test_blob_check_detects_a_crossing_created_by_the_rendered_cubic_curve():
    points = [
        [0.14972269447744863, 0.0],
        [0.4070976327949263, 1.2529176824759611],
        [-0.7640325416058574, 0.5551021342566809],
        [-1.0626818214740117, -0.7720835370390698],
        [0.04803582152524493, -0.1478390571029351],
    ]
    assert not blob._polyline_self_intersects(points)
    assert blob._self_intersects(points)


def test_v2_rejects_wrong_series_shape_material_and_top_level_fields():
    wrong_series = copy.deepcopy(ANIMAL_V2)
    wrong_series["series"] = "robot"
    assert "serie" in _messages(wrong_series).lower()

    wrong_animal = copy.deepcopy(ANIMAL_V2)
    wrong_animal["animal"] = "rabbit"
    assert "animal" in _messages(wrong_animal).lower()

    wrong_fabric = copy.deepcopy(ANIMAL_V2)
    wrong_fabric["fabric"] = "jelly"
    assert "tissu" in _messages(wrong_fabric).lower()

    both = copy.deepcopy(BLOB_V2)
    both["shape"] = "cloud"
    assert "shape ou contour" in _messages(both)

    extra = copy.deepcopy(ANIMAL_V2)
    extra["script"] = "alert(1)"
    assert "champ inconnu" in _messages(extra).lower()

    bad_acc_color = copy.deepcopy(ANIMAL_V2)
    bad_acc_color["acc_color"] = "javascript:red"
    assert "couleur" in _messages(bad_acc_color).lower()

    built_in_on_blob = copy.deepcopy(BLOB_V2)
    built_in_on_blob["accessories"] = ["glasses"]
    assert "animaux 3d" in _messages(built_in_on_blob).lower()


def test_v2_rejects_state_names_inheritance_settings_and_bounds():
    built_in = copy.deepcopy(ANIMAL_V2)
    built_in["states"] = [{"name": "idle", "like": "idle"}]
    assert "integre" in _messages(built_in).lower()

    missing_parent = copy.deepcopy(ANIMAL_V2)
    missing_parent["states"] = [{"name": "sleeping", "like": "unknown"}]
    assert "like" in _messages(missing_parent)

    conflicting_gaze = copy.deepcopy(ANIMAL_V2)
    conflicting_gaze["states"] = [{"name": "searching", "like": "idle", "gaze": [0, 0], "scan": [-1, 1, 0, 2]}]
    assert "gaze" in _messages(conflicting_gaze) and "scan" in _messages(conflicting_gaze)

    bad_bound = copy.deepcopy(ANIMAL_V2)
    bad_bound["states"] = [{"name": "sleeping", "like": "idle", "lid": 0.01}]
    assert "0.04" in _messages(bad_bound)

    bad_scan = copy.deepcopy(ANIMAL_V2)
    bad_scan["states"] = [{"name": "searching", "like": "idle", "scan": [0.5, -0.5, 0, 2]}]
    assert "minX" in _messages(bad_scan)

    orphan_speed = copy.deepcopy(ANIMAL_V2)
    orphan_speed["states"] = [{"name": "celebrating", "like": "idle", "hopSpeed": 2}]
    assert "requires" in _messages(orphan_speed)

    fractional_sparks = copy.deepcopy(ANIMAL_V2)
    fractional_sparks["states"] = [{"name": "celebrating", "like": "happy", "enterSparks": 2.5}]
    assert "entier" in _messages(fractional_sparks).lower()

    too_many = copy.deepcopy(ANIMAL_V2)
    too_many["states"] = [{"name": f"state-{index}", "like": "idle"} for index in range(33)]
    assert "32" in _messages(too_many)


def test_v2_rejects_accessory_structure_vectors_counts_and_shape_rules():
    bad_anchor = copy.deepcopy(ANIMAL_V2)
    bad_anchor["accessories"][1]["anchor"] = "head"
    assert "anchor" in _messages(bad_anchor).lower()

    too_many_parts = copy.deepcopy(ANIMAL_V2)
    too_many_parts["accessories"][1]["parts"] = [copy.deepcopy(HEADPHONES["parts"][0]) for _ in range(17)]
    assert "16" in _messages(too_many_parts)

    too_many_instances = copy.deepcopy(ANIMAL_V2)
    repeated = copy.deepcopy(HEADPHONES["parts"][0])
    repeated["repeat"] = 12
    too_many_instances["accessories"][1]["parts"] = [copy.deepcopy(repeated) for _ in range(6)]
    assert "64" in _messages(too_many_instances)

    bad_repeat = copy.deepcopy(ANIMAL_V2)
    bad_repeat["accessories"][1]["parts"][0]["repeat"] = 13
    assert "repeat" in _messages(bad_repeat)

    bad_offset = copy.deepcopy(ANIMAL_V2)
    bad_offset["accessories"][1]["parts"][0]["at"] = [0, 3, 0]
    assert "-2" in _messages(bad_offset)

    bad_torus = copy.deepcopy(ANIMAL_V2)
    bad_torus["accessories"][1]["parts"][0]["size"] = [1, 0.5]
    assert "moitie" in _messages(bad_torus).lower()

    bad_capsule = copy.deepcopy(ANIMAL_V2)
    bad_capsule["accessories"][1]["parts"][0] = {
        "shape": "capsule", "size": [0.5, 0.4], "material": "felt",
    }
    assert "diametre" in _messages(bad_capsule).lower()

    bad_radius = copy.deepcopy(ANIMAL_V2)
    bad_radius["accessories"][1]["parts"][1]["size"] = [0.2, 0.4, 0.1, 0.11]
    assert "rayon" in _messages(bad_radius).lower()

    bad_arc = copy.deepcopy(ANIMAL_V2)
    bad_arc["accessories"][1]["parts"][1]["arc"] = 180
    assert "torus" in _messages(bad_arc).lower()

    bad_color = copy.deepcopy(ANIMAL_V2)
    bad_color["accessories"][1]["parts"][0]["color"] = "red"
    assert "color" in _messages(bad_color).lower()


def test_blob_export_contains_v2_declarations_and_vendor_only_for_animals(client):
    response = client.post("/api/engines/blob/specs/export", json={"spec": ANIMAL_V2})
    assert response.status_code == 200, response.text
    animal_archive = zipfile.ZipFile(io.BytesIO(client.get(response.json()["download_url"]).content))
    animal_names = set(animal_archive.namelist())
    manifest = json.loads(animal_archive.read("mascot/manifest.json"))
    assert manifest["engine"] == "blob"
    assert list(manifest["engine_states"]) == ["sleeping", "celebrating"]
    assert list(manifest["engine_accessories"]) == ["headphones"]
    assert manifest["engine_three_src"] == "engines/vendor/three.module.min.js"
    assert "mascot/engines/vendor/three.module.min.js" in animal_names
    assert "mascot/engines/vendor/three.LICENSE.txt" in animal_names

    response = client.post("/api/engines/blob/specs/export", json={"spec": HORNED})
    assert response.status_code == 200, response.text
    archive = zipfile.ZipFile(io.BytesIO(client.get(response.json()["download_url"]).content))
    names = set(archive.namelist())
    manifest = json.loads(archive.read("mascot/manifest.json"))
    assert manifest["engine"] == "blob"
    assert len(manifest["engine_shape"]["points"]) == 72
    assert manifest["engine_config"]["shape"].startswith("custom-")
    assert b"AgentMascot.defineShape" in archive.read("mascot/engines/agent-mascot.js")
    assert not any("vendor/" in name for name in names)

    legacy = client.post("/api/engines/blob/export", json={"config": {"shape": "cloud"}})
    assert legacy.status_code == 200


def test_blob_cli_check_preview_and_export(client, monkeypatch, tmp_path, capsys):
    spec_file = tmp_path / "cornes.json"
    spec_file.write_text(json.dumps(HORNED), encoding="utf-8")
    bad_file = tmp_path / "bad.json"
    bad = copy.deepcopy(HORNED)
    bad["contour"]["base"]["width"] = 9
    bad_file.write_text(json.dumps(bad), encoding="utf-8")
    monkeypatch.setattr(blob, "render_agent_sheet", lambda _spec: b"\x89PNG\r\n\x1a\nblob")
    api = _api(client)

    guide_file = tmp_path / "guide.md"
    assert cli.main(["blob", "guide", "--out", str(guide_file)], client=api) == 0
    capsys.readouterr()
    assert "sleeping" in guide_file.read_text(encoding="utf-8")

    assert cli.main(["blob", "check", str(spec_file), "--json"], client=api) == 0
    assert json.loads(capsys.readouterr().out)["ok"]
    assert cli.main(["blob", "check", str(bad_file), "--json"], client=api) == 2
    assert not json.loads(capsys.readouterr().out)["ok"]

    sheet = tmp_path / "sheet.png"
    assert cli.main(["blob", "preview", str(spec_file), "--out", str(sheet)], client=api) == 0
    capsys.readouterr()
    assert sheet.read_bytes().startswith(b"\x89PNG")

    out = tmp_path / "export"
    assert cli.main(["blob", "export", str(spec_file), "--out", str(out)], client=api) == 0
    capsys.readouterr()
    assert json.loads((out / "mascot" / "manifest.json").read_text())["engine_shape"]["points"]


def test_blob_preview_api_reports_validation_and_renderer_errors(client, monkeypatch):
    invalid = copy.deepcopy(HORNED)
    invalid["color"] = "javascript:alert(1)"
    response = client.post("/api/engines/blob/specs/preview", json={"spec": invalid})
    assert response.status_code == 422
    assert response.json()["issues"]

    def fail(_spec: dict) -> bytes:
        raise blob.BlobRenderError("delai depasse")

    monkeypatch.setattr(blob, "render_agent_sheet", fail)
    response = client.post("/api/engines/blob/specs/preview", json={"spec": HORNED})
    assert response.status_code == 503
    assert "Blob Atelier" in response.json()["detail"]


@pytest.mark.skipif(blob._browser() is None, reason="Chrome ou Edge absent")
def test_real_v2_animal_preview_uses_local_three(tmp_path):
    try:
        out = blob.render_sheet(ANIMAL_V2, tmp_path / "animal-v2.png")
    except blob.BlobRenderError as exc:
        pytest.skip(f"rendu Blob Atelier indisponible ici : {exc}")
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert out.stat().st_size > 50_000
