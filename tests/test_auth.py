"""Login, CSRF, registro de última conexión, permisos de admin y cascada de
borrado de un agente."""
import datetime as dt

from conftest import login_como
from extensions import db
from models import Agente, SaldoLicencia, Solicitud


def test_login_correcto_redirige_al_dashboard(client, crear_agente):
    crear_agente('juan', password='clave123')
    r = client.post('/', data={'username': 'juan', 'password': 'clave123'})
    assert r.status_code == 302
    assert '/dashboard' in r.headers['Location']


def test_login_incorrecto_no_entra(client, crear_agente):
    crear_agente('juan', password='clave123')
    r = client.post('/', data={'username': 'juan', 'password': 'clave-mala'}, follow_redirects=True)
    assert 'incorrectos' in r.get_data(as_text=True)


def test_agente_inactivo_no_puede_entrar(app, client, crear_agente):
    ag_id = crear_agente('juan', password='clave123')
    with app.app_context():
        Agente.query.get(ag_id).esta_activo = False
        db.session.commit()
    r = client.post('/', data={'username': 'juan', 'password': 'clave123'}, follow_redirects=True)
    assert 'desactivada' in r.get_data(as_text=True)


def test_login_exitoso_registra_ultimo_login(app, client, crear_agente):
    ag_id = crear_agente('juan', password='clave123')
    with app.app_context():
        assert Agente.query.get(ag_id).ultimo_login is None

    client.post('/', data={'username': 'juan', 'password': 'clave123'})

    with app.app_context():
        assert Agente.query.get(ag_id).ultimo_login is not None


def test_csrf_bloquea_post_sin_token(app, client, admin_id):
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        login_como(client, admin_id, 'admin_test')
        r = client.post('/admin/nueva_novedad', data={'titulo': 'x', 'mensaje': 'y'})
        assert r.status_code == 400
    finally:
        app.config['WTF_CSRF_ENABLED'] = False


def test_no_admin_no_puede_entrar_al_panel_admin(client, agente_id):
    login_como(client, agente_id, 'agente_test')
    r = client.get('/admin', follow_redirects=True)
    assert 'No tienes permiso' in r.get_data(as_text=True)


def test_no_admin_no_puede_aprobar_solicitudes(client, agente_id, admin_id, proximo_dia_habil, app):
    login_como(client, agente_id, 'agente_test')
    dia = proximo_dia_habil(14)
    client.post('/nueva-solicitud', data={
        'tipo_licencia': 'LAO', 'fecha_inicio': dia.isoformat(), 'fecha_fin': dia.isoformat(),
    })
    with app.app_context():
        sol_id = Solicitud.query.filter_by(id_agente=agente_id).first().id

    # Sigue logueado como el propio agente (no admin) e intenta aprobarse a si mismo
    r = client.post(f'/aprobar_solicitud/{sol_id}', data={}, follow_redirects=True)
    assert 'Acción no autorizada' in r.get_data(as_text=True)
    with app.app_context():
        assert Solicitud.query.get(sol_id).estado == 'Pendiente'


def test_no_se_puede_eliminar_al_ultimo_admin(client, admin_id):
    login_como(client, admin_id, 'admin_test')
    r = client.post(f'/admin/eliminar-agente/{admin_id}', data={}, follow_redirects=True)
    assert 'No puedes eliminar tu propia cuenta' in r.get_data(as_text=True)


def test_eliminar_agente_borra_en_cascada_sus_solicitudes_y_saldos(app, client, admin_id, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    dia = proximo_dia_habil(14)
    client.post('/nueva-solicitud', data={
        'tipo_licencia': 'LAO', 'fecha_inicio': dia.isoformat(), 'fecha_fin': dia.isoformat(),
    })

    login_como(client, admin_id, 'admin_test')
    r = client.post(f'/admin/eliminar-agente/{agente_id}', data={})
    assert r.status_code == 302

    with app.app_context():
        assert Agente.query.get(agente_id) is None
        assert Solicitud.query.filter_by(id_agente=agente_id).count() == 0
        assert SaldoLicencia.query.filter_by(id_agente=agente_id).count() == 0
