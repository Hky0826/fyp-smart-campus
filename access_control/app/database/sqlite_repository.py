"""Cloud-synchronized identity store with model-compatible matching."""
from __future__ import annotations
import base64,json,secrets,sqlite3,threading,time
from array import array
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
import numpy as np
from ..domain import Embedding,IdentityMatch
from ..recognition.sface import SFaceRecognizer

def _sync_key(): return f"{int(time.time()*1000):x}-{secrets.token_hex(8)}"
def _utc(value=None):
    value=value or datetime.now(timezone.utc); return value.isoformat() if hasattr(value,'isoformat') else str(value)
def _decode(value):
    if value is None:return None
    if isinstance(value,(bytes,bytearray,memoryview)):return bytes(value)
    if isinstance(value,list):return array('f',(float(v) for v in value)).tobytes()
    if isinstance(value,str):
        try:return base64.b64decode(value.strip(),validate=True)
        except Exception:return None
    return None

class SQLiteIdentityRepository:
    def __init__(self,db_path):
        self.db_path=Path(db_path); self.db_path.parent.mkdir(parents=True,exist_ok=True); self._lock=threading.RLock(); self.initialize()
    def _connect(self):
        conn=sqlite3.connect(str(self.db_path),timeout=10); conn.row_factory=sqlite3.Row; conn.execute('PRAGMA foreign_keys=ON'); conn.execute('PRAGMA busy_timeout=5000'); return conn
    def initialize(self):
        with self._lock:
            conn=self._connect()
            try:
                conn.executescript((Path(__file__).with_name('schema.sql')).read_text(encoding='utf-8'))
                user_columns=self._columns(conn,'device_users')
                if 'display_name' not in user_columns:conn.execute('ALTER TABLE device_users ADD COLUMN display_name TEXT')
                if 'last_synced_at' not in user_columns:conn.execute('ALTER TABLE device_users ADD COLUMN last_synced_at TEXT')
                conn.commit()
            finally:conn.close()
    @staticmethod
    def _columns(conn,table): return {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}
    def compatible_embeddings(self,probe):
        conn=self._connect()
        try:
            rows=conn.execute('''SELECT u.user_id,COALESCE(u.display_name,CAST(u.user_id AS TEXT)) display_name,e.model_name,e.model_version,e.embedding_dimension,e.embedding,e.created_at FROM device_user_face_embeddings e JOIN device_users u ON u.user_id=e.user_id WHERE u.is_active=1 AND e.model_name=? AND e.model_version=? AND e.embedding_dimension=?''',(probe.model_name,probe.model_version,probe.dimension)).fetchall()
            return [(str(r['user_id']),r['display_name'],Embedding(np.frombuffer(r['embedding'],np.float32).copy(),r['model_name'],r['model_version'],r['embedding_dimension'],-1,0.0)) for r in rows]
        finally:conn.close()
    def find_match(self,embedding,threshold=.363):
        best=None
        for identity_id,name,reference in self.compatible_embeddings(embedding):
            score=SFaceRecognizer.similarity(embedding,reference)
            if score>=threshold and (best is None or score>best.similarity):best=IdentityMatch(identity_id,name,score,reference)
        return best
    def status(self):
        conn=self._connect()
        try:
            users=conn.execute('SELECT count(*) FROM device_users WHERE is_active=1').fetchone()[0]
            compatible=conn.execute("SELECT count(*) FROM device_user_face_embeddings WHERE model_name='opencv_sface'").fetchone()[0]
            return {'ok':True,'path':str(self.db_path),'active_users':users,'sface_templates':compatible}
        finally:conn.close()
    def log_authentication_event(self,user_id,auth_status,confidence_score,face_count=1,reason=None,timestamp=None,image_path=None,spoofing_checked=False,spoofing_passed=None):
        with self._lock:
            conn=self._connect()
            try:
                cur=conn.execute('''INSERT INTO device_auth_logs(sync_key,user_id,auth_status,confidence_score,face_count,reason,spoofing_checked,spoofing_passed,timestamp,image_path,sync_status) VALUES(?,?,?,?,?,?,?,?,?,?,0)''',(_sync_key(),None if user_id is None else int(user_id),auth_status.upper(),confidence_score,int(face_count),reason,int(spoofing_checked),None if spoofing_passed is None else int(spoofing_passed),_utc(timestamp),image_path)); conn.commit(); return int(cur.lastrowid)
            finally:conn.close()
    def get_unsynced_logs(self):
        conn=self._connect()
        try:return [dict(r) for r in conn.execute('SELECT * FROM device_auth_logs WHERE sync_status=0 ORDER BY timestamp,log_id').fetchall()]
        finally:conn.close()
    def mark_logs_as_synced(self,ids):
        ids=list(ids)
        if not ids:return
        conn=self._connect()
        try:conn.execute(f"UPDATE device_auth_logs SET sync_status=1,synced_at=CURRENT_TIMESTAMP WHERE log_id IN ({','.join('?'*len(ids))})",ids);conn.commit()
        finally:conn.close()
    def get_local_user_ids(self):
        conn=self._connect()
        try:return [r[0] for r in conn.execute('SELECT user_id FROM device_users').fetchall()]
        finally:conn.close()
    def delete_users_locally(self,ids):
        ids=list(map(int,ids))
        if not ids:return
        conn=self._connect()
        try:conn.execute(f"DELETE FROM device_users WHERE user_id IN ({','.join('?'*len(ids))})",ids);conn.commit()
        finally:conn.close()
    def deactivate_user_instantly(self,user_id):
        conn=self._connect()
        try:cur=conn.execute('UPDATE device_users SET is_active=0,last_synced_at=CURRENT_TIMESTAMP WHERE user_id=?',(int(user_id),));conn.commit();return cur.rowcount>0
        finally:conn.close()
    def get_last_sync_timestamp(self):
        conn=self._connect()
        try:
            row=conn.execute("SELECT val FROM sync_metadata WHERE key='last_sync_timestamp'").fetchone();return row[0] if row else None
        finally:conn.close()
    def update_last_sync_timestamp(self,value):
        conn=self._connect()
        try:conn.execute("INSERT INTO sync_metadata(key,val) VALUES('last_sync_timestamp',?) ON CONFLICT(key) DO UPDATE SET val=excluded.val",(str(value),));conn.commit()
        finally:conn.close()
    def save_users_delta(self,users):
        conn=self._connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            for user in users:
                uid=int(user['user_id']); conn.execute('INSERT INTO device_users(user_id,display_name,is_active,last_synced_at) VALUES(?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(user_id) DO UPDATE SET display_name=COALESCE(excluded.display_name,device_users.display_name),is_active=excluded.is_active,last_synced_at=CURRENT_TIMESTAMP',(uid,user.get('display_name') or user.get('name'),int(user.get('is_active',1))))
                template_keys=('embeddings','face_embeddings','user_face_embeddings','templates');has_template_payload=any(key in user for key in template_keys);payloads=[]
                for key in template_keys:
                    value=user.get(key)
                    if isinstance(value,list):payloads.extend(v if isinstance(v,dict) else {'embedding':v} for v in value)
                if has_template_payload:
                    conn.execute('DELETE FROM device_user_face_embeddings WHERE user_id=?',(uid,))
                    for index,p in enumerate(payloads):
                        blob=_decode(p.get('embedding_b64',p.get('embedding')))
                        if not blob:continue
                        model=p.get('model_name','legacy_unknown');version=p.get('model_version','legacy');dim=int(p.get('embedding_dimension') or len(blob)//4)
                        conn.execute('INSERT INTO device_user_face_embeddings(user_id,template_name,model_name,model_version,embedding_dimension,embedding,quality_metadata_json) VALUES(?,?,?,?,?,?,?)',(uid,p.get('template_name',f'template-{index+1}'),model,version,dim,blob,json.dumps(p.get('quality_metadata') or {})))
            conn.commit()
        except Exception:conn.rollback();raise
        finally:conn.close()
    def save_roles_delta(self,roles):
        conn=self._connect()
        try:
            for r in roles:conn.execute('INSERT INTO device_roles(role_id,role_name) VALUES(?,?) ON CONFLICT(role_id) DO UPDATE SET role_name=excluded.role_name,last_synced_at=CURRENT_TIMESTAMP',(int(r['role_id']),r['role_name']))
            conn.commit()
        finally:conn.close()
    def save_user_roles_delta(self,items):
        conn=self._connect()
        try:
            users={int(x['user_id']) for x in items}
            for uid in users:conn.execute('DELETE FROM device_user_roles WHERE user_id=?',(uid,))
            for x in items:conn.execute('INSERT OR IGNORE INTO device_user_roles(user_id,role_id) VALUES(?,?)',(int(x['user_id']),int(x['role_id'])))
            conn.commit()
        finally:conn.close()
    def save_rbac_delta(self,items):
        conn=self._connect()
        try:
            for x in items:conn.execute('INSERT INTO device_node_rbac(node_id,role_id) VALUES(?,?) ON CONFLICT(node_id,role_id) DO UPDATE SET last_synced_at=CURRENT_TIMESTAMP',(int(x['node_id']),int(x['role_id'])))
            conn.commit()
        finally:conn.close()