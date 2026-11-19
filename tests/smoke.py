#!/usr/bin/env python3
"""geodatalab smoke test — run inside the workbench (any backend).

    python tests/smoke.py [profile]          # pixi / host
    ./geodatalab.sh exec python /opt/geodatalab/smoke.py   # container

Profile defaults to $GDL_PROFILE. Imports every package the profile promises
and runs one tiny operation for the important ones. Exit code 1 on failure.
"""
from __future__ import annotations

import importlib
import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")

profile = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GDL_PROFILE", "lab")
backend = os.environ.get("GDL_BACKEND", "container")

GIS = [
    "geopandas", "rasterio", "rioxarray", "xarray", "jupyterlab", "jupytergis",
    "ipykernel", "folium", "ipyleaflet", "matplotlib", "matplotlib_scalebar",
    "rasterstats", "seaborn", "bokeh", "dask", "scipy", "sqlalchemy", "duckdb",
    "sklearn", "skimage", "xrspatial", "libpysal", "esda", "mgwr", "momepy",
    "whitebox", "whitebox_workflows", "pdal",
]
REQUIRED = {
    "kitchen": GIS,
    "lab": GIS + ["netCDF4", "h5py", "grass.script"],
    "institute": GIS + ["netCDF4", "h5py", "grass.script", "rpy2"],
    "r+julia": ["jupyterlab", "ipykernel", "pandas", "numpy", "matplotlib", "scipy"],
}
if profile not in REQUIRED:
    sys.exit(f"unknown profile {profile!r}")

modules = list(REQUIRED[profile])
expected_missing: dict[str, str] = {}
if backend == "container":
    modules.append("pylasr")
    if profile in ("lab", "institute"):
        modules.append("PySAGA.saga_api")
else:
    expected_missing["pylasr"] = "lasR not packaged for conda-forge"
    if profile in ("lab", "institute"):
        expected_missing["PySAGA"] = "SAGA not on conda-forge"

# ── functional checks ─────────────────────────────────────────────────────────

def chk_geopandas():
    import geopandas as gpd
    from shapely.geometry import Point
    g = gpd.GeoSeries([Point(-8.6, 41.1)], crs=4326).to_crs(3763).buffer(100)
    assert 31_000 < g.area.iloc[0] < 32_000

def chk_rasterio():
    import numpy as np, rasterio
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin
    with MemoryFile() as mf:
        with mf.open(driver="GTiff", width=4, height=4, count=1, dtype="float32",
                     crs="EPSG:3763", transform=from_origin(0, 4, 1, 1)) as ds:
            ds.write(np.ones((1, 4, 4), "float32"))
        with mf.open() as ds:
            assert ds.read(1).sum() == 16
    return f"{rasterio.__version__} (GDAL {rasterio.__gdal_version__})"

def chk_sklearn():
    import numpy as np
    from sklearn.cluster import KMeans
    x = np.r_[np.zeros((10, 2)), np.ones((10, 2)) * 5]
    assert len(set(KMeans(2, n_init=3, random_state=0).fit_predict(x))) == 2

def chk_skimage():
    import numpy as np
    from skimage import filters
    assert filters.gaussian(np.eye(8), sigma=1).shape == (8, 8)

def chk_xrspatial():
    import numpy as np, xarray as xr
    from xrspatial import slope
    dem = xr.DataArray(np.add.outer(np.arange(10.0), np.arange(10.0)),
                       dims=("y", "x"), coords={"y": np.arange(10.0), "x": np.arange(10.0)})
    assert float(slope(dem)[5, 5]) > 0

def chk_esda():
    import numpy as np
    from libpysal.weights import lat2W
    from esda.moran import Moran
    w = lat2W(5, 5)
    m = Moran(np.arange(25.0), w, permutations=0)
    assert m.I > 0.5

def chk_duckdb():
    import duckdb
    # duckdb 2.0: relations no longer have fetchone() — use fetchall()/execute()
    assert duckdb.sql("select 41 + 1").fetchall()[0][0] == 42
    return duckdb.__version__

def chk_pdal():
    import pdal
    import json
    p = pdal.Pipeline(json.dumps({"pipeline": [
        {"type": "readers.faux", "mode": "constant", "count": 10,
         "bounds": "([0, 1], [0, 1], [0, 1])"},
        {"type": "filters.stats"},
    ]}))
    assert p.execute() == 10
    return pdal.__version__

def chk_saga():
    from PySAGA import saga_api as s
    s.SG_Initialize_Environment(True, True)
    n = s.SG_Get_Tool_Library_Manager().Get_Count()
    assert n > 0, "no SAGA tool libraries loaded"
    return f"{s.SAGA_API_Get_Version().split()[-1]}, {n} libs"

def chk_grass():
    import grass.script  # noqa: F401
    import shutil, subprocess
    exe = shutil.which("grass")
    return subprocess.run([exe, "--version"], capture_output=True, text=True).stdout.split("\n")[0] if exe else "no grass exe"

CHECKS = {
    "geopandas": chk_geopandas, "rasterio": chk_rasterio, "sklearn": chk_sklearn,
    "skimage": chk_skimage, "xrspatial": chk_xrspatial, "esda": chk_esda,
    "duckdb": chk_duckdb, "pdal": chk_pdal, "PySAGA.saga_api": chk_saga,
    "grass.script": chk_grass,
}

# ── run ───────────────────────────────────────────────────────────────────────

print(f"geodatalab smoke test — profile={profile} backend={backend} python={sys.version.split()[0]}\n")
failed = 0
for mod in modules:
    t0 = time.time()
    try:
        m = importlib.import_module(mod)
        detail = getattr(m, "__version__", "")
        if mod in CHECKS:
            extra = CHECKS[mod]()
            detail = extra or detail
        print(f"  ok    {mod:<22} {detail}  ({time.time() - t0:.1f}s)")
    except Exception as exc:  # noqa: BLE001
        failed += 1
        print(f"  FAIL  {mod:<22} {type(exc).__name__}: {exc}")

for mod, why in expected_missing.items():
    print(f"  skip  {mod:<22} expected on {backend}: {why}")

print("\nworkbench layout:")
for var in ("GDL_ROOT", "GDL_WORKSPACE", "GDL_DATA"):
    val = os.environ.get(var)
    ok = val and os.path.isdir(val)
    print(f"  {'ok  ' if ok else 'warn'}  {var}={val}")
for var, val in sorted(os.environ.items()):
    if var.startswith("GDL_DATA_"):
        print(f"  {'ok  ' if os.path.isdir(val) else 'warn'}  {var}={val}"
              f"{'  (empty)' if os.path.isdir(val) and not os.listdir(val) else ''}")

print(f"\n{'FAILED' if failed else 'PASSED'}: {len(modules) - failed}/{len(modules)} modules")
sys.exit(1 if failed else 0)
