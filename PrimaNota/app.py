import os, re, sqlite3, threading, hashlib, shutil, json
from pathlib import Path
from datetime import datetime, date
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet
import base64, hashlib as _hashlib

BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "data"
ARCHIVE_DIR = BASE / "archive"
UPLOAD_DIR = BASE / "uploads"
DB_PATH = DATA_DIR / "documentale.sqlite3"
for p in (DATA_DIR, ARCHIVE_DIR, UPLOAD_DIR): p.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET", "change-me")
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024

_jobs = {}
_jobs_lock = threading.Lock()

def db():
    con = sqlite3.connect(DB_PATH, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    return con

def _fernet():
    raw = _hashlib.sha256(app.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(raw))

def enc(v):
    return _fernet().encrypt((v or "").encode()).decode() if v else ""

def dec(v):
    if not v: return ""
    try: return _fernet().decrypt(v.encode()).decode()
    except Exception: return ""

def init_db():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
          is_admin INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
          can_legacy INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS stores(
          id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
          share_path TEXT NOT NULL DEFAULT '', share_user TEXT NOT NULL DEFAULT '', share_password_enc TEXT NOT NULL DEFAULT '',
          active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS sys_files(
          id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), file_name TEXT NOT NULL,
          source_path TEXT NOT NULL, archive_path TEXT NOT NULL, business_date TEXT, register_no INTEGER,
          size_bytes INTEGER, mtime REAL, sha256 TEXT, imported_at TEXT NOT NULL,
          content_clean TEXT NOT NULL DEFAULT '', pos_total REAL, host_total REAL,
          fiscal_total REAL, annulli REAL, resi REAL, riscosso REAL, non_riscosso REAL, num_scontrini INTEGER,
          pos_preview TEXT NOT NULL DEFAULT '', fiscal_preview TEXT NOT NULL DEFAULT '',
          UNIQUE(store_id, source_path, size_bytes, mtime));
        CREATE VIRTUAL TABLE IF NOT EXISTS sys_files_fts USING fts5(content_clean, content='sys_files', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
        CREATE TRIGGER IF NOT EXISTS sys_files_ai AFTER INSERT ON sys_files BEGIN
          INSERT INTO sys_files_fts(rowid,content_clean) VALUES(new.id,new.content_clean); END;
        CREATE TRIGGER IF NOT EXISTS sys_files_ad AFTER DELETE ON sys_files BEGIN
          INSERT INTO sys_files_fts(sys_files_fts,rowid,content_clean) VALUES('delete',old.id,old.content_clean); END;
        CREATE TRIGGER IF NOT EXISTS sys_files_au AFTER UPDATE OF content_clean ON sys_files BEGIN
          INSERT INTO sys_files_fts(sys_files_fts,rowid,content_clean) VALUES('delete',old.id,old.content_clean);
          INSERT INTO sys_files_fts(rowid,content_clean) VALUES(new.id,new.content_clean); END;
        CREATE TABLE IF NOT EXISTS documents(
          id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), business_date TEXT NOT NULL,
          register_no INTEGER, doc_type TEXT NOT NULL, original_name TEXT NOT NULL, stored_path TEXT NOT NULL,
          uploaded_by INTEGER REFERENCES users(id), uploaded_at TEXT NOT NULL,
          worked INTEGER NOT NULL DEFAULT 0, worked_by INTEGER REFERENCES users(id), worked_at TEXT);
        CREATE TABLE IF NOT EXISTS notes(
          id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), business_date TEXT NOT NULL,
          note_type TEXT NOT NULL DEFAULT 'NOTA', body TEXT NOT NULL, created_by INTEGER REFERENCES users(id),
          created_at TEXT NOT NULL, closed INTEGER NOT NULL DEFAULT 0, closed_at TEXT);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '');
        ''')
        admin = os.environ.get("ADMIN_USER","admin")
        pw = os.environ.get("ADMIN_PASSWORD","CAMBIA_QUESTA_PASSWORD")
        if not c.execute("SELECT 1 FROM users WHERE username=?",(admin,)).fetchone():
            c.execute("INSERT INTO users(username,password_hash,is_admin,active,can_legacy,created_at) VALUES(?,?,?,?,?,?)",
                      (admin,generate_password_hash(pw),1,1,1,datetime.now().isoformat(timespec='seconds')))
init_db()

DOC_TYPES = {
 'CHIUSURA_FISCALE':'Chiusura fiscale','CHIUSURA_POS':'Chiusure POS bancari','RESI':'Resi',
 'TRANSAZIONI_ABORTITE':'Transazioni abortite','VERSAMENTO_CONTANTE':'Versamenti contante'
}

def login_required(fn):
    @wraps(fn)
    def w(*a,**k):
        if not session.get('uid'): return redirect(url_for('login', next=request.path))
        return fn(*a,**k)
    return w

def admin_required(fn):
    @wraps(fn)
    def w(*a,**k):
        if not session.get('uid'): return redirect(url_for('login'))
        if not session.get('is_admin'): return "Non autorizzato",403
        return fn(*a,**k)
    return w

def legacy_required(fn):
    @wraps(fn)
    def w(*a,**k):
        if not session.get('uid'): return redirect(url_for('login'))
        if not (session.get('is_admin') or session.get('can_legacy')): return "Modulo non abilitato",403
        return fn(*a,**k)
    return w

def clean_text(raw):
    raw = raw.lstrip('\ufeff')
    return '\n'.join((line[4:] if len(line)>=4 else '') for line in raw.splitlines())

def parse_date_register(name, clean):
    m = re.search(r'SysSpy\.(\d{8})\.(\d+)$', name, re.I)
    d=r=None
    if m:
        try: d=datetime.strptime(m.group(1),'%Y%m%d').date().isoformat()
        except: pass
        r=int(m.group(2))
    if not d:
        dm=re.search(r'\b(\d{2}/\d{2}/\d{4})\b',clean)
        if dm:
            try:d=datetime.strptime(dm.group(1),'%d/%m/%Y').date().isoformat()
            except:pass
    return d,r

def euro_val(txt):
    if txt is None:return None
    s=txt.strip().replace('.','').replace(',','.')
    try:return float(s)
    except:return None

def find_money(clean,label):
    m=re.search(r'^\s*'+re.escape(label)+r'\s+(?:EUR\s+)?(-?[\d\.]+,\d{2})\s*$',clean,re.I|re.M)
    return euro_val(m.group(1)) if m else None

def extract_block(lines, anchor, before=14, after=18):
    inds=[i for i,x in enumerate(lines) if anchor.lower() in x.lower()]
    if not inds:return ''
    i=inds[-1]
    return '\n'.join(lines[max(0,i-before):min(len(lines),i+after+1)]).strip('\n')

def parse_content(clean):
    lines=clean.splitlines()
    out={
      'pos_total':find_money(clean,'TOTALE POS'), 'host_total':find_money(clean,'TOTALE HOST'),
      'fiscal_total':find_money(clean,'TOTALE GIORNALIERO'), 'annulli':find_money(clean,'TOTALE ANNULLI'),
      'resi':find_money(clean,'TOTALE RESI'), 'riscosso':find_money(clean,'CORRISP. RISCOSSO'),
      'non_riscosso':find_money(clean,'CORRISP. NON RISCOSSI')}
    m=re.search(r'^\s*NUM\. SCONTRINI FISCALI\s+(\d+)\s*$',clean,re.I|re.M)
    out['num_scontrini']=int(m.group(1)) if m else None
    out['pos_preview']=extract_block(lines,'TOTALE POS EUR',16,8)
    out['fiscal_preview']=extract_block(lines,'TOTALE GIORNALIERO',6,20)
    return out

def resolve_source(store):
    p=store['share_path']
    if p.startswith('\\\\') or p.startswith('//'):
        return ('smb',p)
    return ('local',p)

def iter_store_files(store, stop_event=None):
    typ,p=resolve_source(store)
    if typ=='local':
        root=Path(p)
        if not root.exists(): raise RuntimeError(f'Percorso non disponibile: {p}')
        for f in root.rglob('*'):
            if stop_event and stop_event.is_set(): break
            if f.is_file() and re.match(r'^SysSpy\.\d{8}\.\d+$',f.name,re.I):
                st=f.stat(); yield str(f),f.name,st.st_size,st.st_mtime,lambda f=f:f.read_bytes()
    else:
        import smbclient
        user=store['share_user']; pwd=dec(store['share_password_enc'])
        smbclient.register_session(p.split('\\')[2] if p.startswith('\\') else p.split('/')[2], username=user, password=pwd)
        for root,dirs,files in smbclient.walk(p):
            if stop_event and stop_event.is_set(): break
            for name in files:
                if not re.match(r'^SysSpy\.\d{8}\.\d+$',name,re.I): continue
                full=root.rstrip('\\/')+'\\'+name
                st=smbclient.stat(full)
                yield full,name,st.st_size,st.st_mtime,lambda full=full:smbclient.open_file(full,'rb').read()

def import_store(store_id, full=False, job_id=None):
    stop=threading.Event()
    if job_id:
        with _jobs_lock:_jobs[job_id]={'state':'running','seen':0,'imported':0,'skipped':0,'errors':0,'message':'','stop':stop}
    with db() as c: store=c.execute('SELECT * FROM stores WHERE id=?',(store_id,)).fetchone()
    try:
        for source,name,size,mtime,reader in iter_store_files(store,stop):
            if stop.is_set(): break
            if job_id:
                with _jobs_lock:_jobs[job_id]['seen']+=1
            with db() as c:
                if not full and c.execute('SELECT 1 FROM sys_files WHERE store_id=? AND source_path=? AND size_bytes=? AND mtime=?',(store_id,source,size,mtime)).fetchone():
                    if job_id:
                        with _jobs_lock:_jobs[job_id]['skipped']+=1
                    continue
            try:
                b=reader(); sha=hashlib.sha256(b).hexdigest()
                try: raw=b.decode('utf-8-sig')
                except UnicodeDecodeError: raw=b.decode('cp1252',errors='replace')
                clean=clean_text(raw); bdate,reg=parse_date_register(name,clean); parsed=parse_content(clean)
                ymd=(bdate or 'senza_data').replace('-','')
                dest=ARCHIVE_DIR/str(store['code'])/ymd/str(reg or 'cassa')
                dest.mkdir(parents=True,exist_ok=True)
                ap=dest/name
                if not ap.exists() or hashlib.sha256(ap.read_bytes()).hexdigest()!=sha: ap.write_bytes(b)
                with db() as c:
                    c.execute('''INSERT OR REPLACE INTO sys_files(store_id,file_name,source_path,archive_path,business_date,register_no,size_bytes,mtime,sha256,imported_at,content_clean,pos_total,host_total,fiscal_total,annulli,resi,riscosso,non_riscosso,num_scontrini,pos_preview,fiscal_preview)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (store_id,name,source,str(ap),bdate,reg,size,mtime,sha,datetime.now().isoformat(timespec='seconds'),clean,parsed['pos_total'],parsed['host_total'],parsed['fiscal_total'],parsed['annulli'],parsed['resi'],parsed['riscosso'],parsed['non_riscosso'],parsed['num_scontrini'],parsed['pos_preview'],parsed['fiscal_preview']))
                if job_id:
                    with _jobs_lock:_jobs[job_id]['imported']+=1
            except Exception as e:
                if job_id:
                    with _jobs_lock:_jobs[job_id]['errors']+=1; _jobs[job_id]['message']=str(e)
        if job_id:
            with _jobs_lock:_jobs[job_id]['state']='stopped' if stop.is_set() else 'done'
    except Exception as e:
        if job_id:
            with _jobs_lock:_jobs[job_id]['state']='error'; _jobs[job_id]['message']=str(e)

@app.context_processor
def ctx(): return {'DOC_TYPES':DOC_TYPES}

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        with db() as c:u=c.execute('SELECT * FROM users WHERE username=? AND active=1',(request.form['username'].strip(),)).fetchone()
        if u and check_password_hash(u['password_hash'],request.form['password']):
            session.clear();session.update(uid=u['id'],username=u['username'],is_admin=bool(u['is_admin']),can_legacy=bool(u['can_legacy']))
            return redirect(request.args.get('next') or url_for('dashboard'))
        flash('Credenziali non valide','error')
    return render_template('login.html')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    with db() as c:
        stores=c.execute('SELECT * FROM stores WHERE active=1 ORDER BY code').fetchall()
        total=c.execute('SELECT COUNT(*) n FROM sys_files').fetchone()['n']
        docs=c.execute('SELECT COUNT(*) n FROM documents').fetchone()['n']
        notes=c.execute("SELECT COUNT(*) n FROM notes WHERE closed=0").fetchone()['n']
    return render_template('dashboard.html',stores=stores,total=total,docs=docs,notes=notes)

@app.route('/monitor')
@login_required
def monitor():
    dal=request.args.get('dal') or date.today().isoformat(); al=request.args.get('al') or dal
    with db() as c:
        rows=c.execute('''WITH d AS (SELECT store_id,business_date,
        SUM(doc_type='CHIUSURA_FISCALE') cf,SUM(doc_type='CHIUSURA_POS') pos,SUM(doc_type='RESI') resi,SUM(doc_type='TRANSAZIONI_ABORTITE') abort,
        SUM(doc_type='VERSAMENTO_CONTANTE') vers,SUM(doc_type='VERSAMENTO_CONTANTE' AND worked=0) vers_open
        FROM documents WHERE business_date BETWEEN ? AND ? GROUP BY store_id,business_date),
        s AS (SELECT store_id,business_date,COUNT(*) sys,COUNT(DISTINCT register_no) casse FROM sys_files WHERE business_date BETWEEN ? AND ? GROUP BY store_id,business_date),
        n AS (SELECT store_id,business_date,COUNT(*) note FROM notes WHERE closed=0 AND business_date BETWEEN ? AND ? GROUP BY store_id,business_date)
        SELECT st.code,st.name,COALESCE(d.business_date,s.business_date,n.business_date) business_date,
        COALESCE(cf,0) cf,COALESCE(pos,0) pos,COALESCE(resi,0) resi,COALESCE(abort,0) abort,COALESCE(vers,0) vers,COALESCE(vers_open,0) vers_open,
        COALESCE(sys,0) sys,COALESCE(casse,0) casse,COALESCE(note,0) note
        FROM stores st LEFT JOIN d ON d.store_id=st.id LEFT JOIN s ON s.store_id=st.id AND (d.business_date IS NULL OR s.business_date=d.business_date)
        LEFT JOIN n ON n.store_id=st.id AND COALESCE(d.business_date,s.business_date)=n.business_date
        WHERE st.active=1 AND COALESCE(d.business_date,s.business_date,n.business_date) IS NOT NULL ORDER BY business_date DESC,st.code''',(dal,al,dal,al,dal,al)).fetchall()
    return render_template('monitor.html',rows=rows,dal=dal,al=al)

@app.route('/archive')
@login_required
def archive():
    store_id=request.args.get('store_id',''); dal=request.args.get('dal',''); al=request.args.get('al','')
    q='''SELECT f.*,s.code store_code,s.name store_name FROM sys_files f JOIN stores s ON s.id=f.store_id WHERE 1=1'''; args=[]
    if store_id:q+=' AND f.store_id=?';args.append(store_id)
    if dal:q+=' AND f.business_date>=?';args.append(dal)
    if al:q+=' AND f.business_date<=?';args.append(al)
    q+=' ORDER BY f.business_date DESC,s.code,f.register_no LIMIT 1000'
    with db() as c: rows=c.execute(q,args).fetchall();stores=c.execute('SELECT * FROM stores WHERE active=1 ORDER BY code').fetchall()
    return render_template('archive.html',rows=rows,stores=stores)

@app.route('/archive/<int:file_id>')
@login_required
def archive_detail(file_id):
    with db() as c:r=c.execute('SELECT f.*,s.code store_code,s.name store_name FROM sys_files f JOIN stores s ON s.id=f.store_id WHERE f.id=?',(file_id,)).fetchone()
    if not r:return 'Non trovato',404
    return render_template('archive_detail.html',r=r)

@app.route('/search')
@login_required
def search():
    term=request.args.get('q','').strip();store_id=request.args.get('store_id','');rows=[]
    with db() as c:
        stores=c.execute('SELECT * FROM stores WHERE active=1 ORDER BY code').fetchall()
        if term:
            # FTS for words; LIKE fallback covers punctuation/receipt numbers exactly.
            q='''SELECT f.*,s.code store_code,s.name store_name FROM sys_files f JOIN stores s ON s.id=f.store_id WHERE (f.content_clean LIKE ?)''';args=['%'+term+'%']
            if store_id:q+=' AND f.store_id=?';args.append(store_id)
            q+=' ORDER BY f.business_date DESC LIMIT 500'; rows=c.execute(q,args).fetchall()
    return render_template('search.html',term=term,rows=rows,stores=stores,store_id=store_id)

@app.route('/documents',methods=['GET','POST'])
@login_required
def documents():
    if request.method=='POST':
        f=request.files.get('file'); store_id=int(request.form['store_id']); bdate=request.form['business_date']; typ=request.form['doc_type']; reg=request.form.get('register_no') or None
        if not f or typ not in DOC_TYPES: flash('Dati non validi','error');return redirect(url_for('documents'))
        dest=UPLOAD_DIR/str(store_id)/bdate/typ;dest.mkdir(parents=True,exist_ok=True)
        safe=re.sub(r'[^A-Za-z0-9._-]+','_',f.filename); path=dest/(datetime.now().strftime('%H%M%S_')+safe);f.save(path)
        with db() as c:c.execute('INSERT INTO documents(store_id,business_date,register_no,doc_type,original_name,stored_path,uploaded_by,uploaded_at) VALUES(?,?,?,?,?,?,?,?)',(store_id,bdate,reg,typ,f.filename,str(path),session['uid'],datetime.now().isoformat(timespec='seconds')))
        flash('Documento archiviato','ok');return redirect(url_for('documents'))
    with db() as c:stores=c.execute('SELECT * FROM stores WHERE active=1 ORDER BY code').fetchall();rows=c.execute('SELECT d.*,s.code store_code FROM documents d JOIN stores s ON s.id=d.store_id ORDER BY d.uploaded_at DESC LIMIT 300').fetchall()
    return render_template('documents.html',stores=stores,rows=rows)

@app.route('/documents/<int:doc_id>/worked',methods=['POST'])
@login_required
def worked(doc_id):
    with db() as c:c.execute("UPDATE documents SET worked=1,worked_by=?,worked_at=? WHERE id=? AND doc_type='VERSAMENTO_CONTANTE'",(session['uid'],datetime.now().isoformat(timespec='seconds'),doc_id))
    return redirect(url_for('documents'))

@app.route('/notes',methods=['GET','POST'])
@login_required
def notes():
    if request.method=='POST':
        with db() as c:c.execute('INSERT INTO notes(store_id,business_date,note_type,body,created_by,created_at) VALUES(?,?,?,?,?,?)',(request.form['store_id'],request.form['business_date'],request.form['note_type'],request.form['body'].strip(),session['uid'],datetime.now().isoformat(timespec='seconds')))
        return redirect(url_for('notes'))
    with db() as c:stores=c.execute('SELECT * FROM stores WHERE active=1 ORDER BY code').fetchall();rows=c.execute('SELECT n.*,s.code store_code,u.username FROM notes n JOIN stores s ON s.id=n.store_id LEFT JOIN users u ON u.id=n.created_by ORDER BY n.created_at DESC LIMIT 300').fetchall()
    return render_template('notes.html',stores=stores,rows=rows)

@app.route('/admin/stores',methods=['GET','POST'])
@admin_required
def admin_stores():
    if request.method=='POST':
        code=request.form['code'].strip();name=request.form['name'].strip();path=request.form.get('share_path','').strip();user=request.form.get('share_user','').strip();pw=request.form.get('share_password','')
        with db() as c:c.execute('INSERT OR REPLACE INTO stores(id,code,name,share_path,share_user,share_password_enc,active) VALUES((SELECT id FROM stores WHERE code=?),?,?,?,?,?,1)',(code,code,name,path,user,enc(pw)))
        return redirect(url_for('admin_stores'))
    with db() as c:rows=c.execute('SELECT id,code,name,share_path,share_user,active FROM stores ORDER BY code').fetchall()
    return render_template('admin_stores.html',rows=rows)

@app.route('/admin/users',methods=['GET','POST'])
@admin_required
def admin_users():
    if request.method=='POST':
        user=request.form['username'].strip();pw=request.form['password'];adm=1 if request.form.get('is_admin') else 0;leg=1 if request.form.get('can_legacy') else 0
        with db() as c:c.execute('INSERT INTO users(username,password_hash,is_admin,active,can_legacy,created_at) VALUES(?,?,?,?,?,?)',(user,generate_password_hash(pw),adm,1,leg,datetime.now().isoformat(timespec='seconds')))
        return redirect(url_for('admin_users'))
    with db() as c:rows=c.execute('SELECT * FROM users ORDER BY username').fetchall()
    return render_template('admin_users.html',rows=rows)

@app.route('/admin/users/<int:uid>/toggle-legacy',methods=['POST'])
@admin_required
def toggle_legacy(uid):
    with db() as c:c.execute('UPDATE users SET can_legacy=1-can_legacy WHERE id=?',(uid,))
    return redirect(url_for('admin_users'))

@app.route('/admin/import/<int:store_id>',methods=['POST'])
@admin_required
def start_import(store_id):
    jid=f'{store_id}-{int(datetime.now().timestamp())}'; full=request.form.get('full')=='1'
    threading.Thread(target=import_store,args=(store_id,full,jid),daemon=True).start()
    return redirect(url_for('import_status',job_id=jid))

@app.route('/admin/import/status/<job_id>')
@admin_required
def import_status(job_id): return render_template('import_status.html',job_id=job_id)
@app.route('/api/jobs/<job_id>')
@admin_required
def job_api(job_id):
    with _jobs_lock:
        j=_jobs.get(job_id)
        if not j:return jsonify({'state':'missing'}),404
        return jsonify({k:v for k,v in j.items() if k!='stop'})
@app.route('/api/jobs/<job_id>/stop',methods=['POST'])
@admin_required
def job_stop(job_id):
    with _jobs_lock:
        if job_id in _jobs:_jobs[job_id]['stop'].set()
    return jsonify({'ok':True})

@app.route('/admin/legacy-settings',methods=['GET','POST'])
@admin_required
def legacy_settings():
    if request.method=='POST':
        vals={k:request.form.get(k,'') for k in ['mssql_host','mssql_db','mssql_user','mssql_port']};vals['mssql_password_enc']=enc(request.form.get('mssql_password',''))
        with db() as c:
            for k,v in vals.items():c.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)',(k,v))
        flash('Configurazione salvata','ok')
    with db() as c:s={r['key']:r['value'] for r in c.execute('SELECT * FROM settings')}
    return render_template('legacy_settings.html',s=s)

def get_setting(k,default=''):
    with db() as c:r=c.execute('SELECT value FROM settings WHERE key=?',(k,)).fetchone()
    return r['value'] if r else default

@app.route('/legacy/matricole',methods=['GET','POST'])
@legacy_required
def legacy_matricole():
    rows=[];err='';dal=request.form.get('dal') or date.today().isoformat();al=request.form.get('al') or dal
    if request.method=='POST':
        try:
            import pymssql
            con=pymssql.connect(server=get_setting('mssql_host'),port=int(get_setting('mssql_port','1433') or 1433),user=get_setting('mssql_user'),password=dec(get_setting('mssql_password_enc')),database=get_setting('mssql_db','Scontrini'),login_timeout=10,timeout=300,as_dict=True)
            cur=con.cursor(as_dict=True);cur.execute('EXEC dbo.RicercaMatricole @DataInizio=%s, @DataFine=%s',(dal+' 00:00:00',al+' 23:59:59'));rows=cur.fetchall();con.close()
        except Exception as e:err=str(e)
    return render_template('legacy_matricole.html',rows=rows,err=err,dal=dal,al=al)

@app.route('/health')
def health():return {'ok':True}
