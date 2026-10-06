"""Funcionalidades específicas del admin: feriados con recálculo retroactivo,
veda administrativa, plazos de vigencia por categoría, reclasificación al
aprobar y cierre de ejercicio."""
import datetime as dt

from conftest import login_como
from extensions import db
from models import Feriado, LimiteCategoria, PeriodoVeda, SaldoLicencia, Solicitud


def _saldo(app, id_agente, categoria):
    with app.app_context():
        s = SaldoLicencia.query.filter_by(id_agente=id_agente, categoria=categoria).first()
        return (s.dias_asignados, s.dias_usados, s.dias_pendientes)


# --- FERIADOS ---

def test_feriado_retroactivo_recalcula_solicitud_aprobada(app, client, admin_id, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    lunes = proximo_dia_habil(14)
    viernes = lunes + dt.timedelta(days=4)
    client.post('/nueva-solicitud', data={
        'tipo_licencia': 'LAO', 'fecha_inicio': lunes.isoformat(), 'fecha_fin': viernes.isoformat(),
    })
    with app.app_context():
        sol_id = Solicitud.query.filter_by(id_agente=agente_id).first().id

    login_como(client, admin_id, 'admin_test')
    client.post(f'/aprobar_solicitud/{sol_id}', data={})

    miercoles = lunes + dt.timedelta(days=2)
    r = client.post('/admin/feriados/agregar', data={
        'fecha': miercoles.isoformat(), 'descripcion': 'Asueto de prueba', 'tipo': 'Asueto',
    })
    assert r.status_code == 302

    with app.app_context():
        sol = Solicitud.query.get(sol_id)
        assert sol.dias_solicitados == 4  # 5 - 1 por el feriado nuevo
        # El miercoles feriado "corre" jueves y viernes un lugar cada uno,
        # pero como ya eran los dias 4 y 5, el 4to dia habil sigue cayendo
        # el mismo viernes: la fecha de fin no cambia en este caso.
        assert sol.fecha_fin == viernes

    _, usados, _ = _saldo(app, agente_id, 'LAO')
    assert usados == 4  # se le devolvio 1 dia


def test_feriado_retroactivo_al_final_del_rango_si_corre_la_fecha_fin(app, client, admin_id, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    lunes = proximo_dia_habil(14)
    viernes = lunes + dt.timedelta(days=4)
    client.post('/nueva-solicitud', data={
        'tipo_licencia': 'LAO', 'fecha_inicio': lunes.isoformat(), 'fecha_fin': viernes.isoformat(),
    })
    with app.app_context():
        sol_id = Solicitud.query.filter_by(id_agente=agente_id).first().id

    login_como(client, admin_id, 'admin_test')
    client.post(f'/aprobar_solicitud/{sol_id}', data={})

    # El feriado cae justo el ultimo dia (viernes): ahora si hay menos
    # margen para absorberlo y la fecha de fin se corre al jueves.
    r = client.post('/admin/feriados/agregar', data={
        'fecha': viernes.isoformat(), 'descripcion': 'Asueto de prueba', 'tipo': 'Asueto',
    })
    assert r.status_code == 302

    with app.app_context():
        sol = Solicitud.query.get(sol_id)
        assert sol.dias_solicitados == 4
        assert sol.fecha_fin == viernes - dt.timedelta(days=1)  # jueves

    _, usados, _ = _saldo(app, agente_id, 'LAO')
    assert usados == 4


def test_no_se_puede_cargar_feriado_duplicado(app, client, admin_id):
    login_como(client, admin_id, 'admin_test')
    fecha = dt.date.today() + dt.timedelta(days=10)
    client.post('/admin/feriados/agregar', data={'fecha': fecha.isoformat(), 'descripcion': 'A', 'tipo': 'Nacional'})
    r = client.post('/admin/feriados/agregar', data={'fecha': fecha.isoformat(), 'descripcion': 'B', 'tipo': 'Nacional'}, follow_redirects=True)
    assert 'Ya existe un feriado' in r.get_data(as_text=True)
    with app.app_context():
        assert Feriado.query.filter_by(fecha=fecha).count() == 1


def test_editar_feriado_cambia_descripcion_y_tipo(app, client, admin_id):
    login_como(client, admin_id, 'admin_test')
    fecha = dt.date.today() + dt.timedelta(days=10)
    client.post('/admin/feriados/agregar', data={'fecha': fecha.isoformat(), 'descripcion': 'Original', 'tipo': 'Nacional'})
    with app.app_context():
        feriado_id = Feriado.query.filter_by(fecha=fecha).first().id

    r = client.post(f'/admin/feriados/editar/{feriado_id}', data={
        'fecha': fecha.isoformat(), 'descripcion': 'Corregido', 'tipo': 'Provincial',
    })
    assert r.status_code == 302
    with app.app_context():
        feriado = Feriado.query.get(feriado_id)
        assert feriado.descripcion == 'Corregido'
        assert feriado.tipo == 'Provincial'
        assert feriado.fecha == fecha


def test_editar_feriado_cambia_fecha_y_recalcula_solicitud_aprobada(app, client, admin_id, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    lunes = proximo_dia_habil(14)
    viernes = lunes + dt.timedelta(days=4)
    client.post('/nueva-solicitud', data={
        'tipo_licencia': 'LAO', 'fecha_inicio': lunes.isoformat(), 'fecha_fin': viernes.isoformat(),
    })
    with app.app_context():
        sol_id = Solicitud.query.filter_by(id_agente=agente_id).first().id

    login_como(client, admin_id, 'admin_test')
    client.post(f'/aprobar_solicitud/{sol_id}', data={})

    otro_dia = lunes + dt.timedelta(days=20)
    client.post('/admin/feriados/agregar', data={
        'fecha': otro_dia.isoformat(), 'descripcion': 'Feriado mal cargado', 'tipo': 'Asueto',
    })
    with app.app_context():
        feriado_id = Feriado.query.filter_by(fecha=otro_dia).first().id

    miercoles = lunes + dt.timedelta(days=2)
    r = client.post(f'/admin/feriados/editar/{feriado_id}', data={
        'fecha': miercoles.isoformat(), 'descripcion': 'Fecha corregida', 'tipo': 'Asueto',
    })
    assert r.status_code == 302

    with app.app_context():
        feriado = Feriado.query.get(feriado_id)
        assert feriado.fecha == miercoles
        sol = Solicitud.query.get(sol_id)
        assert sol.dias_solicitados == 4  # se recalculo con la fecha nueva

    _, usados, _ = _saldo(app, agente_id, 'LAO')
    assert usados == 4


def test_no_se_puede_editar_feriado_a_fecha_ya_ocupada(app, client, admin_id):
    login_como(client, admin_id, 'admin_test')
    fecha_a = dt.date.today() + dt.timedelta(days=10)
    fecha_b = dt.date.today() + dt.timedelta(days=11)
    client.post('/admin/feriados/agregar', data={'fecha': fecha_a.isoformat(), 'descripcion': 'A', 'tipo': 'Nacional'})
    client.post('/admin/feriados/agregar', data={'fecha': fecha_b.isoformat(), 'descripcion': 'B', 'tipo': 'Nacional'})
    with app.app_context():
        feriado_b_id = Feriado.query.filter_by(fecha=fecha_b).first().id

    r = client.post(f'/admin/feriados/editar/{feriado_b_id}', data={
        'fecha': fecha_a.isoformat(), 'descripcion': 'B', 'tipo': 'Nacional',
    }, follow_redirects=True)
    assert 'Ya existe otro feriado' in r.get_data(as_text=True)
    with app.app_context():
        assert Feriado.query.get(feriado_b_id).fecha == fecha_b


# --- VEDA ADMINISTRATIVA ---

def test_veda_bloquea_solicitud_normal_pero_no_carga_de_oficio(app, client, admin_id, agente_id, proximo_dia_habil):
    lunes = proximo_dia_habil(30)
    login_como(client, admin_id, 'admin_test')
    client.post('/admin/veda/agregar', data={
        'fecha_inicio': lunes.isoformat(),
        'fecha_fin': (lunes + dt.timedelta(days=4)).isoformat(),
        'motivo': 'Liquidación de sueldos',
    })

    login_como(client, agente_id, 'agente_test')
    r = client.post('/nueva-solicitud', data={
        'tipo_licencia': 'LAO', 'fecha_inicio': lunes.isoformat(), 'fecha_fin': lunes.isoformat(),
    }, follow_redirects=True)
    assert 'No se pueden cargar solicitudes' in r.get_data(as_text=True)
    with app.app_context():
        assert Solicitud.query.filter_by(id_agente=agente_id).count() == 0

    login_como(client, admin_id, 'admin_test')
    r = client.post('/admin/carga-oficio', data={
        'id_agente': str(agente_id), 'categoria': 'LAO',
        'fecha_inicio': lunes.isoformat(), 'fecha_fin': lunes.isoformat(),
        'constancia_aviso': 'Autorizado durante la veda',
    })
    assert r.status_code == 302
    with app.app_context():
        assert Solicitud.query.filter_by(id_agente=agente_id, es_oficio=True).count() == 1


# --- PLAZOS DE VIGENCIA POR CATEGORÍA ---

def test_categoria_vencida_bloquea_nueva_solicitud_y_muestra_disponibles_en_cero(app, client, agente_id, proximo_dia_habil):
    with app.app_context():
        db.session.add(LimiteCategoria(categoria='INVIERNO', fecha_limite=dt.date.today() - dt.timedelta(days=1)))
        db.session.commit()

    login_como(client, agente_id, 'agente_test')
    dia = proximo_dia_habil(14)
    r = client.post('/nueva-solicitud', data={
        'tipo_licencia': 'INVIERNO', 'fecha_inicio': dia.isoformat(), 'fecha_fin': dia.isoformat(),
    }, follow_redirects=True)
    assert 'venció' in r.get_data(as_text=True)

    r2 = client.get('/dashboard')
    assert 'Plazo vencido' in r2.get_data(as_text=True)


def test_prorroga_de_plazo_restablece_la_categoria(app, client, admin_id, agente_id, proximo_dia_habil):
    with app.app_context():
        db.session.add(LimiteCategoria(categoria='INVIERNO', fecha_limite=dt.date.today() - dt.timedelta(days=1)))
        db.session.commit()

    login_como(client, admin_id, 'admin_test')
    nueva_fecha = dt.date.today() + dt.timedelta(days=30)
    r = client.post('/admin/limites/guardar', data={'limite_INVIERNO': nueva_fecha.isoformat()})
    assert r.status_code == 302

    login_como(client, agente_id, 'agente_test')
    dia = proximo_dia_habil(14)
    r = client.post('/nueva-solicitud', data={
        'tipo_licencia': 'INVIERNO', 'fecha_inicio': dia.isoformat(), 'fecha_fin': dia.isoformat(),
    })
    assert r.status_code == 302
    with app.app_context():
        assert Solicitud.query.filter_by(id_agente=agente_id, tipo_licencia='INVIERNO').count() == 1


def test_limite_vacio_elimina_el_plazo(app, client, admin_id):
    with app.app_context():
        db.session.add(LimiteCategoria(categoria='INVIERNO', fecha_limite=dt.date.today()))
        db.session.commit()

    login_como(client, admin_id, 'admin_test')
    r = client.post('/admin/limites/guardar', data={'limite_INVIERNO': ''})
    assert r.status_code == 302
    with app.app_context():
        assert LimiteCategoria.query.filter_by(categoria='INVIERNO').first() is None


# --- RECLASIFICACIÓN AL APROBAR ---

def test_admin_reclasifica_categoria_al_aprobar(app, client, admin_id, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    lunes = proximo_dia_habil(14)
    client.post('/nueva-solicitud', data={
        'tipo_licencia': 'LAO', 'fecha_inicio': lunes.isoformat(), 'fecha_fin': lunes.isoformat(),
    })
    with app.app_context():
        sol_id = Solicitud.query.filter_by(id_agente=agente_id).first().id

    login_como(client, admin_id, 'admin_test')
    r = client.post(f'/aprobar_solicitud/{sol_id}', data={'categoria': 'INVIERNO'})
    assert r.status_code == 302

    with app.app_context():
        sol = Solicitud.query.get(sol_id)
        assert sol.tipo_licencia == 'INVIERNO'
        assert sol.estado == 'Aprobada'

    _, usados_lao, pendientes_lao = _saldo(app, agente_id, 'LAO')
    _, usados_inv, _ = _saldo(app, agente_id, 'INVIERNO')
    assert pendientes_lao == 0 and usados_lao == 0
    assert usados_inv == 1


def test_reclasificacion_sin_saldo_en_la_nueva_categoria_es_rechazada(app, client, admin_id, crear_agente, proximo_dia_habil):
    ag_id = crear_agente('sin_invierno', saldos={'LAO': 22, 'INVIERNO': 0})
    login_como(client, ag_id, 'sin_invierno')
    lunes = proximo_dia_habil(14)
    client.post('/nueva-solicitud', data={
        'tipo_licencia': 'LAO', 'fecha_inicio': lunes.isoformat(), 'fecha_fin': lunes.isoformat(),
    })
    with app.app_context():
        sol_id = Solicitud.query.filter_by(id_agente=ag_id).first().id

    login_como(client, admin_id, 'admin_test')
    r = client.post(f'/aprobar_solicitud/{sol_id}', data={'categoria': 'INVIERNO'}, follow_redirects=True)
    assert 'No se pudo reclasificar' in r.get_data(as_text=True)

    with app.app_context():
        sol = Solicitud.query.get(sol_id)
        assert sol.estado == 'Pendiente'
        assert sol.tipo_licencia == 'LAO'
    _, _, pendientes_lao = _saldo(app, ag_id, 'LAO')
    assert pendientes_lao == 1  # la reserva original sigue intacta


# --- CIERRE DE EJERCICIO ---

def test_cierre_de_ejercicio_resetea_usados_y_respeta_asignados(app, client, admin_id, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    lunes = proximo_dia_habil(14)
    client.post('/nueva-solicitud', data={
        'tipo_licencia': 'LAO', 'fecha_inicio': lunes.isoformat(), 'fecha_fin': lunes.isoformat(),
    })
    with app.app_context():
        sol_id = Solicitud.query.filter_by(id_agente=agente_id).first().id

    login_como(client, admin_id, 'admin_test')
    client.post(f'/aprobar_solicitud/{sol_id}', data={})

    r = client.post('/admin/cerrar-ejercicio', data={})
    assert r.status_code == 302

    asignados, usados, pendientes = _saldo(app, agente_id, 'LAO')
    assert asignados == 22  # el cupo no se toca
    assert usados == 0
    assert pendientes == 0


def test_cierre_de_ejercicio_se_bloquea_con_pendientes_abiertas(app, client, admin_id, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    lunes = proximo_dia_habil(14)
    client.post('/nueva-solicitud', data={
        'tipo_licencia': 'LAO', 'fecha_inicio': lunes.isoformat(), 'fecha_fin': lunes.isoformat(),
    })

    login_como(client, admin_id, 'admin_test')
    r = client.post('/admin/cerrar-ejercicio', data={}, follow_redirects=True)
    assert 'no se puede cerrar el ejercicio' in r.get_data(as_text=True).lower()

    asignados, usados, pendientes = _saldo(app, agente_id, 'LAO')
    assert pendientes == 1  # no se toco nada
