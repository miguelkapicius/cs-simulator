"""Pacote para embarcar no jogo: só dados de runtime, sem nenhuma identidade real, e o build reprova se vazar."""
import hashlib
import json
import zipfile

import pytest

from pipeline import package_game as pg
from pipeline.package_game import Identities

IDENT = Identities(names={"max", "dgt"}, teams={"FURIA", "9z"})


def kinds(text):
    return {k for k, _ in pg.find_leaks(text, IDENT)}


def test_scanner_flags_every_kind_of_identity():
    assert kinds('{"player": "76561198216891576"}') == {"steamid"}
    assert kinds('{"demo": "furia-vs-9z-m1.dem"}') >= {"demo_file", "team"}
    assert kinds('{"build": "14188 (1.41.8.8, ESL Pro League)"}') == {"event"}
    assert kinds('{"t": "FURIA"}') == {"team"}
    assert kinds('{"id": "furia-vs-9z-m1-ancient#1"}') == {"team"}
    assert kinds('{"p": "dgt"}') == {"nickname"}


def test_scanner_ignores_json_keys_that_only_look_like_a_nickname():
    assert kinds('{"max": 3, "min": 1}') == set()
    assert kinds('{"k": "max"}') == {"nickname"}


def test_scanner_respects_word_boundaries():
    assert kinds("furiatest a9zb") == set()
    assert kinds("a 9z b") == {"team"}


def test_clean_text_has_no_leaks():
    assert pg.find_leaks('{"map": "de_mirage", "players": ["e00", "e01"], "club": "club_3fa9"}', IDENT) == []


def test_sanitize_hides_team_names_in_round_ids_but_keeps_the_round_number():
    out = pg.sanitize({"id": "furia-vs-9z-m1-ancient-3ecad8#12", "t_buy": "full"}, IDENT)
    assert out["t_buy"] == "full"
    base, _, n = out["id"].partition("#")
    assert n == "12" and base.startswith("m") and not pg.find_leaks(out["id"], IDENT)


def test_sanitize_is_stable_and_keeps_distinct_rounds_distinct():
    a = pg.sanitize("furia-vs-9z-m1-ancient-3ecad8#1", IDENT)
    assert a == pg.sanitize("furia-vs-9z-m1-ancient-3ecad8#1", IDENT)
    assert pg.sanitize("furia-vs-9z-m2-nuke-aaaaaa#1", IDENT) != a
    assert pg.sanitize(a, IDENT) == a


def test_sanitize_hides_event_names_in_keys_and_values_without_merging_keys():
    out = pg.sanitize({"14190 (1.41.9.0, Thunderpick)": "ref", "14188 (1.41.8.8, ESL Pro League)": "Thunderpick"}, IDENT)
    assert len(out) == 2 and not pg.find_leaks(json.dumps(out), IDENT)


def test_sanitize_leaves_innocent_data_untouched():
    doc = {"a": [1, 2.5, None, True], "b": {"c": "Alley", "max": 3}}
    assert pg.sanitize(doc, IDENT) == doc


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("dist")
    return pg.build(out), out


def test_package_contains_exactly_the_runtime_allowlist(built):
    path, _ = built
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
    expected = {"artifacts/" + a for a in pg.ARTIFACTS} | {"reference/" + r for r in pg.REFERENCE} \
        | {"VERSION", "MANIFEST.json", "PACKAGE.md"}
    assert names == expected
    for forbidden in ("player_profiles", "sharded", "examples", "test_vectors", "calibration_targets", "CHANGELOG", "docs/"):
        assert not any(forbidden in n for n in names), forbidden


def test_every_file_in_the_package_is_free_of_real_identities(built):
    path, _ = built
    ident = pg.load_identities()
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            assert pg.find_leaks(z.read(n).decode("utf-8"), ident) == [], n


def test_manifest_hashes_match_the_files(built):
    path, _ = built
    with zipfile.ZipFile(path) as z:
        manifest = json.loads(z.read("MANIFEST.json"))
        assert set(manifest["files"]) == set(z.namelist()) - {"MANIFEST.json"}
        for name, info in manifest["files"].items():
            data = z.read(name)
            assert info["bytes"] == len(data) and info["sha256"] == hashlib.sha256(data).hexdigest()


def test_sanitized_artifacts_keep_their_structure(built):
    path, _ = built
    real = json.load(open(pg.ARTIFACTS_DIR / "tactics_playbook.json", encoding="utf-8"))
    with zipfile.ZipFile(path) as z:
        out = json.loads(z.read("artifacts/tactics_playbook.json"))
    assert set(out) == set(real) and set(out["maps"]) == set(real["maps"])
    for m in real["maps"]:
        assert len(out["maps"][m]["rounds"]) == len(real["maps"][m]["rounds"])
        assert len({r["id"] for r in out["maps"][m]["rounds"]}) == len(real["maps"][m]["rounds"])


def test_package_is_reproducible(built, tmp_path):
    path, _ = built
    again = pg.build(tmp_path)
    assert path.read_bytes() == again.read_bytes()


def test_build_fails_and_leaves_no_zip_when_something_leaks(tmp_path, monkeypatch):
    monkeypatch.setattr(pg, "sanitize", lambda obj, ident: obj)
    with pytest.raises(pg.LeakError):
        pg.build(tmp_path)
    assert list(tmp_path.glob("*.zip")) == []
