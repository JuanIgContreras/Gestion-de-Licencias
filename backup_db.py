"""Backup de la base de datos con rotación.

Uso:  python backup_db.py          (hace un backup y borra los más viejos)

Usa la API de backup de SQLite, que es segura aunque la app esté corriendo
y escribiendo en la base en ese momento (a diferencia de copiar el archivo).
Los backups quedan en la carpeta backups/ con el formato
database-AAAAMMDD-HHMMSS.db y se conservan los últimos DIAS_A_CONSERVAR.
"""
import os
import sqlite3
import sys
from datetime import datetime

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, 'database.db')
BACKUP_DIR = os.path.join(BASE_DIR, 'backups')
DIAS_A_CONSERVAR = 30
PREFIJO = 'database-'


def _backups_existentes(backup_dir=None):
    backup_dir = backup_dir or BACKUP_DIR
    if not os.path.isdir(backup_dir):
        return []
    return sorted(
        f for f in os.listdir(backup_dir) if f.startswith(PREFIJO) and f.endswith('.db')
    )


def hay_backup_de_hoy():
    hoy = datetime.now().strftime('%Y%m%d')
    return any(f.startswith(f'{PREFIJO}{hoy}-') for f in _backups_existentes())


def hacer_backup(db_path=DB_PATH, backup_dir=BACKUP_DIR):
    """Crea un backup verificado y rota los viejos. Devuelve la ruta creada."""
    os.makedirs(backup_dir, exist_ok=True)
    destino = os.path.join(backup_dir, f'{PREFIJO}{datetime.now():%Y%m%d-%H%M%S}.db')

    origen = sqlite3.connect(db_path)
    copia = sqlite3.connect(destino)
    try:
        origen.backup(copia)
    finally:
        copia.close()
        origen.close()

    verificacion = sqlite3.connect(destino)
    try:
        resultado = verificacion.execute('PRAGMA integrity_check').fetchone()[0]
    finally:
        verificacion.close()
    if resultado != 'ok':
        os.remove(destino)
        raise RuntimeError(f'El backup no pasó la verificación de integridad: {resultado}')

    existentes = _backups_existentes(backup_dir)
    for viejo in existentes[:-DIAS_A_CONSERVAR]:
        os.remove(os.path.join(backup_dir, viejo))

    return destino


if __name__ == '__main__':
    try:
        print(f'Backup creado: {hacer_backup()}')
    except Exception as e:
        print(f'ERROR al hacer el backup: {e}', file=sys.stderr)
        sys.exit(1)
