from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNAS = ROOT / "tests" / "js" / "min_zoom_harness.js"
FIT_HARNAS = ROOT / "tests" / "js" / "fit_bounds_harness.js"


def _min_zoom_aanroepen(bounds_zoom: float) -> list[float]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node ontbreekt; de minZoom-regressietest voert app.js in Node uit")
    result = subprocess.run(
        [node, str(HARNAS), str(bounds_zoom)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    ("bounds_zoom", "verwacht"),
    [(6.25, 6), (4.75, 4), (7.75, 7), (6.0, 6)],
)
def test_hoofdkaart_minzoom_is_geheel_getal(bounds_zoom: float, verwacht: int) -> None:
    """markercluster tekent bij addLayers niets als de minZoom van de kaart een fractie is."""
    aanroepen = _min_zoom_aanroepen(bounds_zoom)
    assert aanroepen, "initMainMap roept mainMap.setMinZoom niet aan"
    assert aanroepen[-1] == verwacht, (
        f"setMinZoom kreeg {aanroepen[-1]} bij getBoundsZoom {bounds_zoom}; "
        f"verwacht {verwacht}, anders verschijnen geüploade foto's niet op de hoofdkaart"
    )


def _fit_bounds_aanroepen(punten: list[dict]) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node ontbreekt; de fitBounds-test voert app.js in Node uit")
    result = subprocess.run(
        [node, str(FIT_HARNAS), json.dumps(punten)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return json.loads(result.stdout)


def test_hoofdkaart_zoomt_in_op_alle_gemelde_fotos() -> None:
    punten = [
        {"id": 1, "name": "a", "lat": 52.1, "lon": 4.5},
        {"id": 2, "name": "b", "lat": 52.6, "lon": 5.1},
        {"id": 3, "name": "c", "lat": 51.9, "lon": 4.9},
    ]
    resultaat = _fit_bounds_aanroepen(punten)
    assert len(resultaat["calls"]) == 1, "fitBounds hoort na het laden precies één keer te lopen"
    aanroep = resultaat["calls"][0]
    assert aanroep["points"] == [[p["lat"], p["lon"]] for p in punten]
    assert aanroep["options"]["padding"], "kleine padding ontbreekt"
    assert aanroep["options"]["maxZoom"] <= 14


def test_hoofdkaart_enkele_foto_heeft_zoomlimiet() -> None:
    resultaat = _fit_bounds_aanroepen([{"id": 1, "name": "a", "lat": 52.1, "lon": 4.5}])
    assert len(resultaat["calls"]) == 1
    assert resultaat["calls"][0]["options"]["maxZoom"] <= 14


def test_hoofdkaart_zonder_fotos_houdt_standaardweergave() -> None:
    resultaat = _fit_bounds_aanroepen([])
    assert resultaat["calls"] == []


def test_kaartspelden_hebben_minimaal_44_px_raakvlak() -> None:
    """Fotomarkers en de versleepbare locatiespeld delen pinIcon; breed én hoog minimaal 44 px."""
    js = (ROOT / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "app" / "static" / "css" / "style.css").read_text(encoding="utf-8")
    breedte, hoogte = map(int, re.search(r"iconSize: \[(\d+), (\d+)\],\n\s+iconAnchor", js).groups())
    anker_x, anker_y = map(int, re.search(r"iconAnchor: \[(\d+), (\d+)\]", js).groups())
    assert breedte >= 44 and hoogte >= 44
    assert (anker_x, anker_y) == (breedte // 2, hoogte), "de punt moet onderaan het midden liggen"
    svg_breedte = int(re.search(r'viewBox="0 0 32 42" width="(\d+)"', js).group(1))
    assert svg_breedte <= breedte
    assert re.search(r"\.pin svg \{[^}]*margin: 0 auto", css), "svg moet in het raakvlak gecentreerd staan"
