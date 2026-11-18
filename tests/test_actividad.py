"""Registro de actividad: qué se anota, que la página sea solo para admins,
que los filtros funcionen y que los registros sobrevivan a un agente borrado."""
import datetime as dt

from conftest import login_como
from extensions import db
from models import RegistroActividad, Solicitud


def _registros(app, **filtros):
    with app.app_context():
        q = RegistroActividad.query.filter_by(**filtros).order_by(RegistroActividad.id)
        return [(r.actor, r.tipo, r.detalle) for r in q.all()]


def _cargar(client, categoria, inicio, fin=None):
    return client.post('/nueva-solicitud', data={
        'tipo_licencia': categoria, 'fecha_inicio': inicio.isoformat(),
        'fecha_fin': (fin or inicio).isoformat(),
    }, follow_redirects=True)


# --- INGRESOS ---

def test_ingreso_correcto_y_cierre_de_sesion_quedan_registrados(app, client, crear_agente):
    crear_agente('juan', nombre_completo='PEREZ, JUAN', password='clave123')
    client.post('/', data={'username': 'juan', 'password': 'clave123'})
    client.get('/logout')
    regs = _registros(app, tipo='ingreso')
    assert ('PEREZ, JUAN', 'ingreso', 'Inició sesión') in regs
    assert ('PEREZ, JUAN', 'ingreso', 'Cerró sesión') in regs


def test_ingreso_fallido_queda_registrado_con_o_sin_cuenta(app, client, crear_agente):
    crear_agente('juan', nombre_completo='PEREZ, JUAN', password='clave123')
    client.post('/', data={'username': 'juan', 'password': 'mala'})
    client.post('/', data={'username': 'fantasma', 'password': 'x'})
    regs = _registros(app, tipo='ingreso')
    assert ('PEREZ, JUAN', 'ingreso', 'Ingreso fallido: contraseña incorrecta') in regs
    assert ('Usuario "fantasma"', 'ingreso', 'Ingreso fallido: el usuario "fantasma" no existe') in regs


def test_no_se_guarda_la_contrasena_en_ningun_registro(app, client, crear_agente):
    crear_agente('juan', password='clave123')
    client.post('/', data={'username': 'juan', 'password': 'secreta-que-no-debe-aparecer'})
    with app.app_context():
        assert not any('secreta-que-no-debe-aparecer' in r.detalle or 'secreta-que-no-debe-aparecer' in r.actor
                       for r in RegistroActividad.query.all())


# --- ACCIONES DEL ADMIN ---

def test_aprobar_rechazar_devolver_y_eliminar_quedan_registrados(app, client, admin_id, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    lunes = proximo_dia_habil(14)
    for i in range(3):
        _cargar(client, 'LAO', lunes + dt.timedelta(days=i))
    with app.app_context():
        ids = [s.id for s in Solicitud.query.filter_by(id_agente=agente_id).order_by(Solicitud.fecha_inicio)]

    login_como(client, admin_id, 'admin_test')
    client.post(f'/aprobar_solicitud/{ids[0]}', data={})
    client.post(f'/rechazar_solicitud/{ids[1]}', data={'comentario_admin': 'no corresponde'})
    client.post(f'/admin/eliminar-solicitud/{ids[2]}', data={})
    client.post(f'/admin/rectificar-solicitud/{ids[0]}', data={})

    detalles = [d for _, t, d in _registros(app, tipo='solicitud')]
    assert any(d.startswith('Aprobó la solicitud de agente_test') for d in detalles)
    assert any(d.startswith('Rechazó la solicitud de agente_test') and 'motivo: no corresponde' in d for d in detalles)
    assert any(d.startswith('Eliminó la solicitud pendiente de agente_test') for d in detalles)
    assert any(d.startswith('Devolvió a Pendientes') and 'estaba Aprobada' in d for d in detalles)
    assert all(actor == 'admin_test' for actor, t, _ in _registros(app, tipo='solicitud'))


def test_carga_de_oficio_registra_la_constancia(app, client, admin_id, agente_id, proximo_dia_habil):
    login_como(client, admin_id, 'admin_test')
    lunes = proximo_dia_habil(14)
    client.post('/admin/carga-oficio', data={
        'id_agente': str(agente_id), 'categoria': 'LAO', 'fecha_inicio': lunes.isoformat(),
        'fecha_fin': lunes.isoformat(), 'constancia_aviso': 'Llamó por gripe',
    })
    detalle = _registros(app, tipo='solicitud')[0][2]
    assert detalle.startswith('Carga de oficio: agente_test') and 'constancia: Llamó por gripe' in detalle


def test_cambios_de_agentes_feriados_veda_y_novedades_quedan_registrados(app, client, admin_id, agente_id):
    login_como(client, admin_id, 'admin_test')
    client.post(f'/admin/editar-agente/{agente_id}', data={
        'nombre_completo': 'agente_test', 'usuario': 'agente_test', 'cupo_LAO': '20',
    })
    client.post(f'/admin/toggle-agente/{agente_id}')
    fecha = dt.date.today() + dt.timedelta(days=40)
    client.post('/admin/feriados/agregar', data={'fecha': fecha.isoformat(), 'descripcion': 'Prueba', 'tipo': 'Asueto'})
    client.post('/admin/veda/agregar', data={
        'fecha_inicio': fecha.isoformat(), 'fecha_fin': fecha.isoformat(), 'motivo': 'Sueldos'})
    client.post('/admin/nueva_novedad', data={'titulo': 'Aviso', 'mensaje': 'hola'})

    todos = {t: [d for _, tt, d in _registros(app) if tt == t] for t in ('agente', 'calendario', 'novedad')}
    assert any('Editó los datos de agente_test' in d and 'cupo Licencia Anual Ordinaria (LAO)' in d for d in todos['agente'])
    assert any(d.startswith('Desactivó la cuenta de agente_test') for d in todos['agente'])
    assert any(d.startswith('Agregó el feriado') for d in todos['calendario'])
    assert any(d.startswith('Agregó un período de veda') for d in todos['calendario'])
    assert any(d == 'Publicó la novedad "Aviso"' for d in todos['novedad'])


# --- INTENTOS RECHAZADOS ---

def test_intento_fuera_de_plazo_y_superpuesto_quedan_registrados(app, client, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    _cargar(client, 'LAO', dt.date.today())
    lunes = proximo_dia_habil(14)
    _cargar(client, 'LAO', lunes)
    _cargar(client, 'LAO', lunes)

    detalles = [d for _, t, d in _registros(app, tipo='rechazo')]
    assert any(d.startswith('Fuera de plazo') for d in detalles)
    assert any('Ya tenés una solicitud pendiente' in d for d in detalles)
    assert all(actor == 'agente_test' for actor, _, _ in _registros(app, tipo='rechazo'))


# --- PÁGINA ---

def test_la_pagina_es_solo_para_admins(client, agente_id):
    login_como(client, agente_id, 'agente_test')
    r = client.get('/admin/actividad', follow_redirects=True)
    assert 'No tienes permiso' in r.get_data(as_text=True)


def test_la_pagina_muestra_registros_y_filtra(app, client, admin_id, agente_id):
    with app.app_context():
        db.session.add_all([
            RegistroActividad(fecha=dt.datetime(2026, 1, 10, 9, 0), id_actor=admin_id, actor='admin_test',
                              tipo='solicitud', detalle='Aprobó algo de enero'),
            RegistroActividad(fecha=dt.datetime(2026, 3, 10, 9, 0), id_actor=agente_id, actor='agente_test',
                              tipo='rechazo', detalle='Fuera de plazo de marzo'),
        ])
        db.session.commit()
    login_como(client, admin_id, 'admin_test')

    html = client.get('/admin/actividad').get_data(as_text=True)
    assert 'Aprobó algo de enero' in html and 'Fuera de plazo de marzo' in html

    html = client.get('/admin/actividad?tipo=rechazo').get_data(as_text=True)
    assert 'Fuera de plazo de marzo' in html and 'Aprobó algo de enero' not in html

    html = client.get(f'/admin/actividad?persona={admin_id}').get_data(as_text=True)
    assert 'Aprobó algo de enero' in html and 'Fuera de plazo de marzo' not in html

    html = client.get('/admin/actividad?desde=2026-02-01&hasta=2026-12-31').get_data(as_text=True)
    assert 'Fuera de plazo de marzo' in html and 'Aprobó algo de enero' not in html


def test_la_pagina_pagina_los_resultados(app, client, admin_id):
    with app.app_context():
        for i in range(60):
            db.session.add(RegistroActividad(id_actor=admin_id, actor='admin_test', tipo='novedad',
                                             detalle=f'Registro numero {i:03d}'))
        db.session.commit()
    login_como(client, admin_id, 'admin_test')
    p1 = client.get('/admin/actividad').get_data(as_text=True)
    p2 = client.get('/admin/actividad?pagina=2').get_data(as_text=True)
    assert 'Registro numero 059' in p1 and 'Registro numero 000' not in p1
    assert 'Registro numero 000' in p2 and 'Registro numero 059' not in p2
    assert 'Página 1 de 2' in p1


def test_los_registros_sobreviven_si_se_elimina_al_agente(app, client, admin_id, crear_agente):
    otro = crear_agente('otro', nombre_completo='GOMEZ, ANA')
    login_como(client, admin_id, 'admin_test')
    client.post(f'/admin/toggle-agente/{otro}')
    client.post(f'/admin/eliminar-agente/{otro}')
    with app.app_context():
        assert db.session.get(__import__('models').Agente, otro) is None
    detalles = [d for _, _, d in _registros(app, tipo='agente')]
    assert any('Desactivó la cuenta de GOMEZ, ANA' in d for d in detalles)
    assert any(d.startswith('Eliminó al agente GOMEZ, ANA') for d in detalles)


def test_la_app_no_ofrece_ninguna_ruta_para_borrar_o_editar_registros(client, admin_id):
    login_como(client, admin_id, 'admin_test')
    for metodo in ('post', 'put', 'delete'):
        assert getattr(client, metodo)('/admin/actividad').status_code == 405
    assert client.post('/admin/actividad/eliminar/1').status_code == 404
