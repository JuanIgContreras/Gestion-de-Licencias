"""backup_db.py: backup consistente de SQLite y rotación de los más viejos."""
import os
import sqlite3

import backup_db


def _crear_base(path):
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)')
    conn.execute("INSERT INTO t (v) VALUES ('hola')")
    conn.commit()
    conn.close()


def test_hacer_backup_copia_los_datos(tmp_path):
    db = str(tmp_path / 'origen.db')
    _crear_base(db)
    destino = backup_db.hacer_backup(db_path=db, backup_dir=str(tmp_path / 'bk'))
    conn = sqlite3.connect(destino)
    assert conn.execute('SELECT v FROM t').fetchone()[0] == 'hola'
    conn.close()


def test_rotacion_conserva_solo_los_ultimos(tmp_path, monkeypatch):
    db = str(tmp_path / 'origen.db')
    _crear_base(db)
    bk = tmp_path / 'bk'
    bk.mkdir()
    for dia in range(1, 6):
        (bk / f'database-2026010{dia}-120000.db').write_bytes(b'viejo')
    monkeypatch.setattr(backup_db, 'DIAS_A_CONSERVAR', 3)

    nuevo = backup_db.hacer_backup(db_path=db, backup_dir=str(bk))

    restantes = sorted(os.listdir(bk))
    assert len(restantes) == 3
    assert os.path.basename(nuevo) in restantes
    assert 'database-20260101-120000.db' not in restantes


def test_hay_backup_de_hoy(tmp_path, monkeypatch):
    db = str(tmp_path / 'origen.db')
    _crear_base(db)
    bk = str(tmp_path / 'bk')
    monkeypatch.setattr(backup_db, 'BACKUP_DIR', bk)
    assert backup_db.hay_backup_de_hoy() is False
    backup_db.hacer_backup(db_path=db, backup_dir=bk)
    assert backup_db.hay_backup_de_hoy() is True
