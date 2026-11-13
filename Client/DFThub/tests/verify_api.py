"""Exercise replica submission payloads using an isolated, non-executing API."""
import io
import os
import sys
import tempfile
from pathlib import Path

SOURCE = Path(os.environ.get("DFTHUB_API_SOURCE", str(Path(__file__).resolve().parents[3] / "src/dfthub/api")))
with tempfile.TemporaryDirectory(prefix="dfthub-replica-api-") as temporary:
    root = Path(temporary)
    os.environ.update(DFTHUB_DATA_DIR=str(root), DFTHUB_WORKERS="0", DFTHUB_MAIL_SUPPRESS="1", JWT_SECRET="replica-test-secret-not-for-production-0000")
    sys.path.insert(0, str(SOURCE))
    import app
    assert app._QUEUE_WORKERS == 0
    assert Path(app.DATA_DIR).resolve() == root.resolve()
    common = root / "Work/common"
    common.mkdir(parents=True)
    (common / "default_weights.csv").write_text("Database,Description,Type,Source,Number,Inverse Weight\nRef,,BH,Reference,38,0.208536487179584\n")
    client = app.appx.test_client()
    registered = client.post("/api_dft/register", json={"username": "replica_test", "email": "replica@example.test", "password": "replica-password"})
    assert registered.status_code == 200, registered.get_json()
    headers = {"Authorization": "Bearer " + registered.get_json()["token"]}
    for basis in ("cc-pvtz", "cc-pvqz"):
        job = basis.replace("-", "_")
        work = f"Work/replica_test/{job}"
        uploaded = client.put("/api_dft/upload", headers=headers, data={"folder_dir": work + "/upload", "files": [
            (io.BytesIO(b"archive payload"), "Demo.tgz"),
            (io.BytesIO(b"0.0\n"), "Demo.ref"),
            (io.BytesIO(b"Database,Description,Type,Source,Number,Inverse Weight\nDemo,,,uploaded,,0.02\n"), "init_weight.csv"),
        ]})
        assert uploaded.status_code == 200, uploaded.get_json()
        response = client.post("/api_dft/submit", headers=headers, json={"mode": "new", "work_dir": work + "/", "weightFile": "weight_0", "basis": basis, "email": "replica@example.test", "reMark": "UI contract test"})
        assert response.status_code == 200, response.get_json()
        assert (root / work / "input/basis.txt").read_text().strip() == basis
        queued = app._task_queue.get()
        assert queued["cmd"][queued["cmd"].index("--basis") + 1] == basis
        print("PASS new", basis)

    base = root / work / "output/weight_0"
    (base / "INPUT").write_text("isolated optimization input")
    (base / "INPUT_ref").write_text("isolated reference input")
    weights = "Database\tDescription\tType\tSource\tNumber\tInverse Weight\nDemo\t\t\tuploaded\t\t0.01\nRef\t\tBH\tReference\t38\t0.208536487179584\n"
    uploaded = client.put("/api_dft/upload", headers=headers, data={"folder_dir": work + "/output/weight_1", "files": (io.BytesIO(weights.encode()), "weight.csv")})
    assert uploaded.status_code == 200
    optimized = client.post("/api_dft/submit", headers=headers, json={"mode": "optim", "work_dir": work, "weightFile": "weight_1"})
    assert optimized.status_code == 200, optimized.get_json()
    assert (root / work / "output/weight_1/weight.csv").read_text() == weights
    assert app._task_queue.get()["mode"] == "optim"
    print("PASS weight resubmission; no workers or emails executed")
