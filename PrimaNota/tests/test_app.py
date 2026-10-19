import os, re, sys, tempfile, importlib
from pathlib import Path
import pytest

HOME = tempfile.mkdtemp()
os.environ.update(PRIMANOTA_HOME=HOME, PRIMANOTA_NO_AUTO='1', APP_SECRET='test-secret', ADMIN_USER='admin', ADMIN_PASSWORD='adminpass')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_mod = importlib.import_module('app')
app = app_mod.app

SYSSPY = '\n'.join('0001' + l for l in [
    'NEGOZIO 5048', '28/05/2026', 'SCONTRINO 001074', 'TOTALE POS EUR      1.234,56',
    'TOTALE GIORNALIERO      2.000,00', 'NUM. SCONTRINI FISCALI   42'])


def token(client, url='/'):
    html = client.get(url).get_data(as_text=True)
    return re.search(r'name=csrf_token value="([^"]+)"', html).group(1)


@pytest.fixture
def client():
    c = app.test_client()
    t = token(c, '/login')
    r = c.post('/login', data={'username': 'admin', 'password': 'adminpass', 'csrf_token': t})
    assert r.status_code == 302
    return c


@pytest.fixture(scope='module')
def store():
    src = Path(HOME) / 'share5048'
    src.mkdir(exist_ok=True)
    (src / 'SysSpy.20260528.3').write_text(SYSSPY)
    with app_mod.db() as c:
        c.execute("INSERT OR IGNORE INTO stores(code,name,share_path) VALUES('5048','Motta',?)", (str(src),))
        sid = c.execute("SELECT id FROM stores WHERE code='5048'").fetchone()['id']
    app_mod.import_store(sid)
    return sid, src


def test_post_senza_csrf_rifiutato(client):
    assert client.post('/notes', data={}).status_code == 400


def test_redirect_esterno_dopo_login_bloccato():
    c = app.test_client()
    t = token(c, '/login')
    r = c.post('/login?next=//evil.example', data={'username': 'admin', 'password': 'adminpass', 'csrf_token': t})
    assert r.headers['Location'] == '/'


def test_import_estrae_totali_e_ricerca_parziale(client, store):
    with app_mod.db() as c:
        r = c.execute('SELECT * FROM sys_files').fetchone()
    assert r['business_date'] == '2026-05-28' and r['register_no'] == 3
    assert r['pos_total'] == 1234.56 and r['num_scontrini'] == 42
    html = client.get('/search?q=1074').get_data(as_text=True)
    assert 'SysSpy.20260528.3' in html
    assert client.get(f"/archive/{r['id']}/download").status_code == 200


def test_file_modificato_non_duplica(store):
    sid, src = store
    f = src / 'SysSpy.20260528.3'
    f.write_text(SYSSPY + '\n0001RIGA AGGIUNTA')
    os.utime(f, (1, 1))
    app_mod.import_store(sid)
    with app_mod.db() as c:
        assert c.execute('SELECT COUNT(*) n FROM sys_files WHERE store_id=?', (sid,)).fetchone()['n'] == 1


def test_data_non_valida_non_scrive_fuori(client, store):
    sid, _ = store
    t = token(client, '/documents')
    import io
    client.post('/documents', data={'csrf_token': t, 'store_id': sid, 'business_date': '../../x', 'doc_type': 'RESI',
                                    'file': (io.BytesIO(b'x'), 'a.pdf')}, content_type='multipart/form-data')
    assert not (Path(HOME) / 'x').exists()
    with app_mod.db() as c:
        assert c.execute('SELECT COUNT(*) n FROM documents').fetchone()['n'] == 0


def test_monitor_mostra_giorni_con_solo_note_o_sysspy(client, store):
    sid, _ = store
    t = token(client, '/notes')
    client.post('/notes', data={'csrf_token': t, 'store_id': sid, 'business_date': '2026-05-30', 'note_type': 'ANOMALIA', 'body': 'x'})
    html = client.get('/monitor?dal=2026-05-01&al=2026-05-31').get_data(as_text=True)
    assert '2026-05-28' in html and '2026-05-30' in html
    with app_mod.db() as c:
        nid = c.execute('SELECT id FROM notes').fetchone()['id']
    client.post(f'/notes/{nid}/close', data={'csrf_token': t})
    assert '2026-05-30' not in client.get('/monitor?dal=2026-05-01&al=2026-05-31').get_data(as_text=True)


def test_password_negozio_vuota_resta_invariata(client, store):
    t = token(client, '/admin/stores')
    client.post('/admin/stores', data={'csrf_token': t, 'code': 'X1', 'name': 'n', 'share_password': 'segreta'})
    client.post('/admin/stores', data={'csrf_token': t, 'code': 'X1', 'name': 'n2', 'share_password': ''})
    with app_mod.db() as c:
        enc = c.execute("SELECT share_password_enc FROM stores WHERE code='X1'").fetchone()[0]
    assert app_mod.dec(enc) == 'segreta'


def test_utente_disattivato_perde_accesso(client):
    t = token(client, '/admin/users')
    client.post('/admin/users', data={'csrf_token': t, 'username': 'mario', 'password': 'password1'})
    u = app.test_client()
    ut = token(u, '/login')
    u.post('/login', data={'username': 'mario', 'password': 'password1', 'csrf_token': ut})
    assert u.get('/').status_code == 200
    with app_mod.db() as c:
        uid = c.execute("SELECT id FROM users WHERE username='mario'").fetchone()['id']
    client.post(f'/admin/users/{uid}/toggle-active', data={'csrf_token': t})
    assert u.get('/').status_code == 302
