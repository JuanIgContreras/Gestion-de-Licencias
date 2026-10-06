"""Migración desde el esquema legado (columnas dias_enero/dias_julio/etc. en
agente + tabla permiso) hacia SaldoLicencia. Se corre en un subproceso aparte
con su propio DATABASE_URL: app.py lee esa variable y corre migrar_esquema()
automáticamente al importarse, así que no puede compartir el proceso de
pytest (que ya tiene su propia base de test bindeada desde conftest.py)."""
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

PROJECT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def _crear_base_legada(path):
    """Arma un archivo SQLite con la forma vieja del esquema: agente con las
    columnas dias_enero/dias_julio/etc. y una tabla permiso, tal como estaba
    la base real antes de la migración al motor de licencias."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE agente (
            id INTEGER PRIMARY KEY,
            usuario VARCHAR(80) UNIQUE NOT NULL,
            clave_hash VARCHAR(120) NOT NULL,
            nombre_completo VARCHAR(200) NOT NULL,
            es_admin BOOLEAN DEFAULT 0,
            esta_activo BOOLEAN DEFAULT 1,
            dias_enero INTEGER DEFAULT 22,
            dias_enero_inicial INTEGER DEFAULT 22,
            dias_julio INTEGER DEFAULT 5,
            dias_julio_inicial INTEGER DEFAULT 5,
            dias_compensatorios_usados INTEGER DEFAULT 0,
            dias_compensatorios_inicial INTEGER DEFAULT 0
        );
        CREATE TABLE permiso (
            id INTEGER PRIMARY KEY,
            motivo VARCHAR(100),
            fecha DATE,
            horas FLOAT,
            estado VARCHAR(20),
            id_agente INTEGER
        );
        CREATE TABLE solicitud (
            id INTEGER PRIMARY KEY,
            tipo_licencia VARCHAR(50) NOT NULL,
            fecha_inicio DATE NOT NULL,
            dias_solicitados INTEGER NOT NULL,
            estado VARCHAR(20) NOT NULL DEFAULT 'Pendiente',
            comentario_agente TEXT,
            comentario_admin TEXT,
            id_agente INTEGER NOT NULL
        );
        CREATE TABLE novedad (
            id INTEGER PRIMARY KEY,
            titulo VARCHAR(100) NOT NULL,
            mensaje TEXT NOT NULL,
            fecha_publicacion DATETIME NOT NULL
        );

        -- Un agente que ya usó parte de su cupo: 6 de 22 disponibles en LAO,
        -- exactamente el bug real que se encontró y corrigió.
        INSERT INTO agente (usuario, clave_hash, nombre_completo, dias_enero, dias_enero_inicial, dias_julio, dias_julio_inicial, dias_compensatorios_usados, dias_compensatorios_inicial)
        VALUES ('contreras', 'x', 'Contreras Juan', 6, 22, 0, 5, 0, 0);

        INSERT INTO permiso (motivo, fecha, horas, estado, id_agente)
        VALUES ('Entrar tarde', '2026-01-01', 1.5, 'Aprobado', 1);

        INSERT INTO solicitud (tipo_licencia, fecha_inicio, dias_solicitados, estado, id_agente)
        VALUES ('Vacaciones Enero', '2026-01-05', 3, 'Aprobada', 1);
    """)
    conn.commit()
    conn.close()


def _correr_migracion(db_path):
    """Importa app.py en un subproceso con DATABASE_URL apuntando a db_path.
    Como migrar_esquema() corre automáticamente al importar, alcanza con
    importar el módulo y salir."""
    env = os.environ.copy()
    env['DATABASE_URL'] = 'sqlite:///' + db_path
    env['SECRET_KEY'] = 'clave-de-test-migracion'
    resultado = subprocess.run(
        [sys.executable, '-c', 'import app'],
        cwd=PROJECT_DIR, env=env, capture_output=True, text=True, timeout=30,
    )
    assert resultado.returncode == 0, (
        f"la migracion fallo:\nSTDOUT:\n{resultado.stdout}\nSTDERR:\n{resultado.stderr}"
    )


def test_migracion_desde_esquema_legado(tmp_path):
    db_path = str(tmp_path / 'legado.db')
    _crear_base_legada(db_path)

    _correr_migracion(db_path)

    conn = sqlite3.connect(db_path)
    tablas = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert 'permiso' not in tablas, "la tabla permiso deberia haberse eliminado"
    assert 'saldo_licencia' in tablas
    assert 'limite_categoria' in tablas
    assert 'periodo_veda' in tablas
    assert 'feriado' in tablas

    fila = conn.execute(
        "SELECT dias_asignados, dias_usados, dias_pendientes FROM saldo_licencia "
        "WHERE id_agente=1 AND categoria='LAO'"
    ).fetchone()
    assert fila is not None, "deberia existir el saldo LAO migrado para el agente"
    asignados, usados, pendientes = fila
    # El bug real: antes se guardaba asignados=6 (el remanente) perdiendo el
    # registro de cuanto ya se habia usado. Corregido: asignados=22 (cupo
    # real, tomado de dias_enero_inicial), usados=16 (22-6).
    assert asignados == 22
    assert usados == 16
    assert pendientes == 0

    # La solicitud historica se preservo con fecha_fin completada.
    fecha_fin = conn.execute("SELECT fecha_fin FROM solicitud WHERE id=1").fetchone()[0]
    assert fecha_fin is not None

    # Se genero un backup automatico antes del DROP TABLE permiso.
    backups = [f for f in os.listdir(tmp_path) if f.startswith('database.backup-pre-licencias-')]
    conn.close()


def test_migracion_es_idempotente(tmp_path):
    """Correrla dos veces seguidas no debe duplicar filas de saldo ni
    romper nada (así es como corre en producción: en cada arranque de la app)."""
    db_path = str(tmp_path / 'legado.db')
    _crear_base_legada(db_path)

    _correr_migracion(db_path)
    _correr_migracion(db_path)

    conn = sqlite3.connect(db_path)
    total_saldos = conn.execute("SELECT COUNT(*) FROM saldo_licencia WHERE id_agente=1").fetchone()[0]
    conn.close()
    assert total_saldos == 4  # una fila por categoria, no 8
