"""Delete only temporary fixture jobs using the existing authenticated API."""
import os
import sys
import tempfile
from pathlib import Path

source = Path(os.getenv('DFTHUB_API_SOURCE', '/home/hpc/DFT-hub-v2/Api/api/app/DFT_Hub/src'))
with tempfile.TemporaryDirectory(prefix='dfthub-delete-contract-') as temporary:
    root = Path(temporary)
    os.environ.update(DFTHUB_DATA_DIR=str(root), DFTHUB_WORKERS='0', DFTHUB_MAIL_SUPPRESS='1', JWT_SECRET='isolated-delete-test-secret-not-production-123')
    sys.path.insert(0, str(source))
    import app
    assert Path(app.DATA_DIR).resolve() == root.resolve()
    assert app._QUEUE_WORKERS == 0
    client = app.appx.test_client()
    def register(name):
        response = client.post('/api_dft/register', json={'username': name, 'email': name + '@example.test', 'password': 'test-password'})
        assert response.status_code == 200, response.get_json()
        return {'Authorization': 'Bearer ' + response.get_json()['token']}
    alice = register('delete_alice')
    bob = register('delete_bob')
    target = root / 'Work/delete_alice/finished'
    (target / 'output/weight_0').mkdir(parents=True)
    (target / 'output/weight_0/Mue').write_text('Input\t0.59\n')
    keep = root / 'Work/delete_alice/keep'
    keep.mkdir()
    protected = root / 'Work/delete_bob/protected'
    protected.mkdir()
    assert client.delete('/api_dft/delete/Work/delete_alice/finished').status_code == 401
    assert client.delete('/api_dft/delete/Work/delete_bob/protected', headers=alice).status_code == 403
    assert protected.exists()
    result = client.delete('/api_dft/delete/Work/delete_alice/finished', headers=alice)
    assert result.status_code == 200, result.get_json()
    assert not target.exists() and keep.exists() and protected.exists()
    assert client.delete('/api_dft/delete/Work/delete_alice/finished', headers=alice).status_code == 404
    print('PASS deletion: authenticated exact target, recursive results removal, sibling preservation, cross-user rejection, no production data touched')
