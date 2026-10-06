"""Fixtures compartidas por toda la suite.

Importante: DATABASE_URL se fija ANTES de importar app.py, porque ese módulo
lee la variable de entorno a nivel de módulo (al definir
SQLALCHEMY_DATABASE_URI) y corre migrar_esquema() automáticamente al
importarse. Esto es lo que garantiza que los tests nunca toquen database.db,
la base real: cada sesión de tests usa su propio archivo temporal.
"""
import datetime as dt
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

_db_fd, _db_path = tempfile.mkstemp(suffix='.db')
os.close(_db_fd)
os.environ['DATABASE_URL'] = 'sqlite:///' + _db_path
os.environ.setdefault('SECRET_KEY', 'clave-de-test-nunca-usar-en-produccion')

import app as flask_app_module  # noqa: E402
import motor_licencias as motor  # noqa: E402
from extensions import db, bcrypt  # noqa: E402
from models import CATEGORIAS, Agente, SaldoLicencia  # noqa: E402


@pytest.fixture(scope='session')
def app():
    flask_app_module.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    yield flask_app_module.app
    try:
        os.remove(_db_path)
    except OSError:
        pass


@pytest.fixture(autouse=True)
def base_limpia(app):
    """Cada test arranca con las tablas vacías, para que ninguno dependa de
    datos dejados por otro test (ni por la migración de columnas legadas,
    que no aplica acá: el esquema nace limpio desde los modelos actuales)."""
    with app.app_context():
        db.drop_all()
        db.create_all()
    yield


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def crear_agente(app):
    """Factory: crear_agente(usuario, es_admin=False, saldos={'LAO': 22}, ...)
    Devuelve el id del agente creado (no el objeto ORM: se evita el clásico
    DetachedInstanceError de usar una instancia fuera de su app_context)."""
    def _crear(usuario, nombre_completo=None, es_admin=False,
               examen_estudio_habilitado=False, saldos=None, password=None):
        with app.app_context():
            agente = Agente(
                usuario=usuario,
                nombre_completo=nombre_completo or usuario,
                clave_hash=bcrypt.generate_password_hash(password or usuario).decode('utf-8'),
                es_admin=es_admin,
                examen_estudio_habilitado=examen_estudio_habilitado,
            )
            db.session.add(agente)
            db.session.flush()

            saldos = saldos or {}
            for codigo, meta in CATEGORIAS.items():
                cupo = saldos.get(codigo, meta['cupo_default'])
                db.session.add(SaldoLicencia(id_agente=agente.id, categoria=codigo, dias_asignados=cupo))

            db.session.commit()
            return agente.id
    return _crear


@pytest.fixture
def admin_id(crear_agente):
    return crear_agente('admin_test', es_admin=True)


@pytest.fixture
def agente_id(crear_agente):
    return crear_agente('agente_test', saldos={'LAO': 22, 'INVIERNO': 10, 'COMPENSATORIO': 5})


def login_como(client, id_agente, usuario):
    """Setea la sesión directamente (sin pasar por /login) — más rápido y no
    depende de contraseñas en texto plano dentro de los tests."""
    with client.session_transaction() as sess:
        sess['id_agente'] = id_agente
        sess['usuario_agente'] = usuario


@pytest.fixture
def proximo_dia_habil():
    """Devuelve una función que encuentra el próximo LUNES hábil a partir de
    hoy + n días, respetando los feriados YA cargados en la base de test (si
    los hay). Siempre un lunes (no cualquier día hábil) para que los tests
    puedan sumar días corridos con seguridad y seguir dentro de la misma
    semana laboral (ej. lunes + 4 = viernes de esa semana)."""
    def _buscar(dias_desde_hoy=14):
        with flask_app_module.app.app_context():
            feriados = motor.cargar_feriados()
        fecha = dt.date.today() + dt.timedelta(days=dias_desde_hoy)
        while fecha.weekday() != 0 or not motor.es_dia_habil(fecha, feriados):
            fecha += dt.timedelta(days=1)
        return fecha
    return _buscar
