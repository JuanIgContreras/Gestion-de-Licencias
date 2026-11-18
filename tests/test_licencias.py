"""Ciclo de vida de una Solicitud: crear, aprobar, rechazar, rectificar,
editar, eliminar. Mecánica de saldos (asignados - usados - pendientes)."""
import datetime as dt

from conftest import login_como
from extensions import db
from models import SaldoLicencia, Solicitud


def _saldo(app, id_agente, categoria):
    with app.app_context():
        s = SaldoLicencia.query.filter_by(id_agente=id_agente, categoria=categoria).first()
        return (s.dias_asignados, s.dias_usados, s.dias_pendientes, s.dias_disponibles)


def test_nueva_solicitud_reserva_dias_en_pendientes(app, client, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    lunes = proximo_dia_habil(14)
    viernes = lunes + dt.timedelta(days=4)

    r = client.post('/nueva-solicitud', data={
        'tipo_licencia': 'LAO', 'fecha_inicio': lunes.isoformat(), 'fecha_fin': viernes.isoformat(),
    })
    assert r.status_code == 302

    asignados, usados, pendientes, disponibles = _saldo(app, agente_id, 'LAO')
    assert pendientes == 5
    assert usados == 0
    assert disponibles == 22 - 5


def test_nueva_solicitud_sin_saldo_suficiente_es_rechazada(app, client, crear_agente, proximo_dia_habil):
    ag_id = crear_agente('sin_saldo', saldos={'LAO': 2})
    login_como(client, ag_id, 'sin_saldo')
    lunes = proximo_dia_habil(14)
    viernes = lunes + dt.timedelta(days=4)  # pide 5 dias habiles, solo tiene 2

    r = client.post('/nueva-solicitud', data={
        'tipo_licencia': 'LAO', 'fecha_inicio': lunes.isoformat(), 'fecha_fin': viernes.isoformat(),
    }, follow_redirects=True)
    assert 'suficientes días disponibles' in r.get_data(as_text=True)
    with app.app_context():
        assert Solicitud.query.filter_by(id_agente=ag_id).count() == 0


def test_aprobar_mueve_de_pendientes_a_usados(app, client, admin_id, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    lunes = proximo_dia_habil(14)
    client.post('/nueva-solicitud', data={
        'tipo_licencia': 'LAO', 'fecha_inicio': lunes.isoformat(), 'fecha_fin': lunes.isoformat(),
    })
    with app.app_context():
        sol_id = Solicitud.query.filter_by(id_agente=agente_id).first().id

    login_como(client, admin_id, 'admin_test')
    r = client.post(f'/aprobar_solicitud/{sol_id}', data={})
    assert r.status_code == 302

    with app.app_context():
        sol = Solicitud.query.get(sol_id)
        assert sol.estado == 'Aprobada'
        assert sol.notificado is False
    _, usados, pendientes, _ = _saldo(app, agente_id, 'LAO')
    assert usados == 1 and pendientes == 0


def test_rechazar_libera_dias_pendientes(app, client, admin_id, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    lunes = proximo_dia_habil(14)
    client.post('/nueva-solicitud', data={
        'tipo_licencia': 'LAO', 'fecha_inicio': lunes.isoformat(), 'fecha_fin': lunes.isoformat(),
    })
    with app.app_context():
        sol_id = Solicitud.query.filter_by(id_agente=agente_id).first().id

    login_como(client, admin_id, 'admin_test')
    r = client.post(f'/rechazar_solicitud/{sol_id}', data={})
    assert r.status_code == 302

    with app.app_context():
        assert Solicitud.query.get(sol_id).estado == 'Rechazada'
    _, usados, pendientes, disponibles = _saldo(app, agente_id, 'LAO')
    assert usados == 0 and pendientes == 0 and disponibles == 22


def test_no_se_puede_gestionar_una_solicitud_ya_resuelta(app, client, admin_id, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    lunes = proximo_dia_habil(14)
    client.post('/nueva-solicitud', data={
        'tipo_licencia': 'LAO', 'fecha_inicio': lunes.isoformat(), 'fecha_fin': lunes.isoformat(),
    })
    with app.app_context():
        sol_id = Solicitud.query.filter_by(id_agente=agente_id).first().id

    login_como(client, admin_id, 'admin_test')
    client.post(f'/aprobar_solicitud/{sol_id}', data={})
    r = client.post(f'/aprobar_solicitud/{sol_id}', data={}, follow_redirects=True)
    assert 'ya fue gestionada' in r.get_data(as_text=True)


def test_rectificar_aprobada_devuelve_usados_a_pendientes(app, client, admin_id, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    lunes = proximo_dia_habil(14)
    client.post('/nueva-solicitud', data={
        'tipo_licencia': 'LAO', 'fecha_inicio': lunes.isoformat(), 'fecha_fin': lunes.isoformat(),
    })
    with app.app_context():
        sol_id = Solicitud.query.filter_by(id_agente=agente_id).first().id

    login_como(client, admin_id, 'admin_test')
    client.post(f'/aprobar_solicitud/{sol_id}', data={})
    r = client.post(f'/admin/rectificar-solicitud/{sol_id}', data={})
    assert r.status_code == 302

    with app.app_context():
        sol = Solicitud.query.get(sol_id)
        assert sol.estado == 'Pendiente'
        assert sol.notificado is True
    _, usados, pendientes, _ = _saldo(app, agente_id, 'LAO')
    assert usados == 0 and pendientes == 1


def test_eliminar_solicitud_pendiente_libera_dias(app, client, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    lunes = proximo_dia_habil(14)
    client.post('/nueva-solicitud', data={
        'tipo_licencia': 'LAO', 'fecha_inicio': lunes.isoformat(), 'fecha_fin': lunes.isoformat(),
    })
    with app.app_context():
        sol_id = Solicitud.query.filter_by(id_agente=agente_id).first().id

    r = client.post(f'/eliminar_solicitud/{sol_id}', data={})
    assert r.status_code == 302
    with app.app_context():
        assert Solicitud.query.get(sol_id) is None
    _, _, pendientes, disponibles = _saldo(app, agente_id, 'LAO')
    assert pendientes == 0 and disponibles == 22


def test_no_se_puede_eliminar_una_solicitud_ajena(app, client, crear_agente, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    lunes = proximo_dia_habil(14)
    client.post('/nueva-solicitud', data={
        'tipo_licencia': 'LAO', 'fecha_inicio': lunes.isoformat(), 'fecha_fin': lunes.isoformat(),
    })
    with app.app_context():
        sol_id = Solicitud.query.filter_by(id_agente=agente_id).first().id

    otro_id = crear_agente('otro_agente')
    login_como(client, otro_id, 'otro_agente')
    r = client.post(f'/eliminar_solicitud/{sol_id}', data={}, follow_redirects=True)
    assert 'No tienes permiso' in r.get_data(as_text=True)
    with app.app_context():
        assert Solicitud.query.get(sol_id) is not None


def test_admin_puede_eliminar_solicitud_pendiente_y_libera_dias(app, client, admin_id, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    lunes = proximo_dia_habil(14)
    client.post('/nueva-solicitud', data={
        'tipo_licencia': 'LAO', 'fecha_inicio': lunes.isoformat(), 'fecha_fin': lunes.isoformat(),
    })
    with app.app_context():
        sol_id = Solicitud.query.filter_by(id_agente=agente_id).first().id

    login_como(client, admin_id, 'admin_test')
    r = client.post(f'/admin/eliminar-solicitud/{sol_id}', data={})
    assert r.status_code == 302
    with app.app_context():
        assert Solicitud.query.get(sol_id) is None
    _, _, pendientes, disponibles = _saldo(app, agente_id, 'LAO')
    assert pendientes == 0 and disponibles == 22


def test_admin_no_puede_eliminar_solicitud_ya_gestionada(app, client, admin_id, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    lunes = proximo_dia_habil(14)
    client.post('/nueva-solicitud', data={
        'tipo_licencia': 'LAO', 'fecha_inicio': lunes.isoformat(), 'fecha_fin': lunes.isoformat(),
    })
    with app.app_context():
        sol_id = Solicitud.query.filter_by(id_agente=agente_id).first().id

    login_como(client, admin_id, 'admin_test')
    client.post(f'/aprobar_solicitud/{sol_id}', data={})
    r = client.post(f'/admin/eliminar-solicitud/{sol_id}', data={}, follow_redirects=True)
    assert 'Solo pueden eliminarse solicitudes pendientes' in r.get_data(as_text=True)
    with app.app_context():
        assert Solicitud.query.get(sol_id) is not None
    assert _saldo(app, agente_id, 'LAO')[1] == 1  # los días usados no se tocaron


def test_agente_comun_no_puede_usar_la_eliminacion_de_admin(app, client, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    lunes = proximo_dia_habil(14)
    client.post('/nueva-solicitud', data={
        'tipo_licencia': 'LAO', 'fecha_inicio': lunes.isoformat(), 'fecha_fin': lunes.isoformat(),
    })
    with app.app_context():
        sol_id = Solicitud.query.filter_by(id_agente=agente_id).first().id

    r = client.post(f'/admin/eliminar-solicitud/{sol_id}', data={})
    assert r.status_code == 302
    with app.app_context():
        assert Solicitud.query.get(sol_id) is not None


def test_disponibles_nunca_es_negativo_si_usados_supera_asignados(app, agente_id):
    with app.app_context():
        s = SaldoLicencia.query.filter_by(id_agente=agente_id, categoria='LAO').first()
        s.dias_asignados = 0
        s.dias_usados = 22
        db.session.commit()
    assert _saldo(app, agente_id, 'LAO')[3] == 0


def test_editar_solicitud_pendiente_cambia_fechas_y_categoria(app, client, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    lunes = proximo_dia_habil(14)
    client.post('/nueva-solicitud', data={
        'tipo_licencia': 'LAO', 'fecha_inicio': lunes.isoformat(), 'fecha_fin': lunes.isoformat(),
    })
    with app.app_context():
        sol_id = Solicitud.query.filter_by(id_agente=agente_id).first().id

    lunes2 = proximo_dia_habil(30)
    viernes2 = lunes2 + dt.timedelta(days=4)
    r = client.post('/editar-solicitud-modal', data={
        'id_solicitud': sol_id, 'tipo_licencia': 'INVIERNO',
        'fecha_inicio': lunes2.isoformat(), 'fecha_fin': viernes2.isoformat(),
        'comentario_agente': 'cambio de planes',
    })
    assert r.status_code == 302

    with app.app_context():
        sol = Solicitud.query.get(sol_id)
        assert sol.tipo_licencia == 'INVIERNO'
        assert sol.dias_solicitados == 5

    _, _, pendientes_lao, _ = _saldo(app, agente_id, 'LAO')
    _, _, pendientes_inv, _ = _saldo(app, agente_id, 'INVIERNO')
    assert pendientes_lao == 0
    assert pendientes_inv == 5


def test_corte_de_antelacion_rechaza_solicitud_para_hoy(app, client, agente_id):
    login_como(client, agente_id, 'agente_test')
    hoy = dt.date.today()
    r = client.post('/nueva-solicitud', data={
        'tipo_licencia': 'LAO', 'fecha_inicio': hoy.isoformat(), 'fecha_fin': hoy.isoformat(),
    }, follow_redirects=True)
    assert 'Fuera de plazo' in r.get_data(as_text=True)
    with app.app_context():
        assert Solicitud.query.filter_by(id_agente=agente_id).count() == 0


def test_carga_de_oficio_acepta_pese_al_corte(app, client, admin_id, agente_id):
    login_como(client, admin_id, 'admin_test')
    hoy = dt.date.today()
    r = client.post('/admin/carga-oficio', data={
        'id_agente': str(agente_id), 'categoria': 'LAO',
        'fecha_inicio': hoy.isoformat(), 'fecha_fin': hoy.isoformat(),
        'constancia_aviso': 'Aviso telefónico de prueba',
    })
    assert r.status_code == 302
    with app.app_context():
        sol = Solicitud.query.filter_by(id_agente=agente_id).first()
        assert sol.estado == 'Aprobada'
        assert sol.es_oficio is True
        assert sol.notificado is False


def test_carga_de_oficio_doble_submit_no_duplica(app, client, admin_id, agente_id):
    login_como(client, admin_id, 'admin_test')
    hoy = dt.date.today()
    datos = {
        'id_agente': str(agente_id), 'categoria': 'LAO',
        'fecha_inicio': hoy.isoformat(), 'fecha_fin': hoy.isoformat(),
        'constancia_aviso': 'Aviso telefónico de prueba',
    }
    r1 = client.post('/admin/carga-oficio', data=datos)
    r2 = client.post('/admin/carga-oficio', data=datos, follow_redirects=True)
    assert r1.status_code == 302
    assert 'ya se había registrado' in r2.get_data(as_text=True)
    with app.app_context():
        assert Solicitud.query.filter_by(id_agente=agente_id, es_oficio=True).count() == 1


def test_carga_de_oficio_sin_constancia_es_rechazada(app, client, admin_id, agente_id):
    login_como(client, admin_id, 'admin_test')
    hoy = dt.date.today()
    r = client.post('/admin/carga-oficio', data={
        'id_agente': str(agente_id), 'categoria': 'LAO',
        'fecha_inicio': hoy.isoformat(), 'fecha_fin': hoy.isoformat(),
    }, follow_redirects=True)
    assert 'constancia' in r.get_data(as_text=True).lower()
    with app.app_context():
        assert Solicitud.query.filter_by(id_agente=agente_id).count() == 0


def test_examen_estudio_bloqueado_sin_habilitacion(app, client, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    dia = proximo_dia_habil(14)
    r = client.post('/nueva-solicitud', data={
        'tipo_licencia': 'EXAMEN_ESTUDIO', 'fecha_inicio': dia.isoformat(), 'fecha_fin': dia.isoformat(),
    }, follow_redirects=True)
    assert 'No tenés habilitada' in r.get_data(as_text=True)


def test_examen_estudio_funciona_una_vez_habilitado(app, client, crear_agente, proximo_dia_habil):
    ag_id = crear_agente('con_examen', examen_estudio_habilitado=True, saldos={'EXAMEN_ESTUDIO': 20})
    login_como(client, ag_id, 'con_examen')
    dia = proximo_dia_habil(14)
    r = client.post('/nueva-solicitud', data={
        'tipo_licencia': 'EXAMEN_ESTUDIO', 'fecha_inicio': dia.isoformat(), 'fecha_fin': dia.isoformat(),
    })
    assert r.status_code == 302
    with app.app_context():
        assert Solicitud.query.filter_by(id_agente=ag_id, tipo_licencia='EXAMEN_ESTUDIO').count() == 1


# --- SUPERPOSICIÓN DE SOLICITUDES DEL MISMO AGENTE ---

def _cargar(client, categoria, inicio, fin=None):
    return client.post('/nueva-solicitud', data={
        'tipo_licencia': categoria, 'fecha_inicio': inicio.isoformat(),
        'fecha_fin': (fin or inicio).isoformat(),
    }, follow_redirects=True)


def _cantidad(app, id_agente):
    with app.app_context():
        return Solicitud.query.filter_by(id_agente=id_agente).count()


def test_agente_no_puede_cargar_dos_solicitudes_para_el_mismo_dia(app, client, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    lunes = proximo_dia_habil(14)
    _cargar(client, 'LAO', lunes)
    r = _cargar(client, 'INVIERNO', lunes)
    assert 'Ya tenés una solicitud pendiente' in r.get_data(as_text=True)
    assert _cantidad(app, agente_id) == 1
    assert _saldo(app, agente_id, 'INVIERNO')[2] == 0  # no reservó días


def test_admin_no_puede_cargar_de_oficio_lo_que_el_agente_ya_cargo(app, client, admin_id, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    lunes = proximo_dia_habil(14)
    _cargar(client, 'LAO', lunes)

    login_como(client, admin_id, 'admin_test')
    r = client.post('/admin/carga-oficio', data={
        'id_agente': str(agente_id), 'categoria': 'LAO',
        'fecha_inicio': lunes.isoformat(), 'fecha_fin': lunes.isoformat(),
        'constancia_aviso': 'Aviso telefónico',
    }, follow_redirects=True)
    assert 'ya tiene una solicitud pendiente' in r.get_data(as_text=True)
    assert _cantidad(app, agente_id) == 1
    assert _saldo(app, agente_id, 'LAO')[1] == 0  # no se descontó nada de usados


def test_superposicion_parcial_es_rechazada_y_dias_contiguos_no(app, client, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    lunes = proximo_dia_habil(14)
    _cargar(client, 'LAO', lunes, lunes + dt.timedelta(days=2))  # lun-mié

    r = _cargar(client, 'LAO', lunes + dt.timedelta(days=2), lunes + dt.timedelta(days=4))  # mié-vie
    assert 'entre el' in r.get_data(as_text=True) or 'Ya tenés una solicitud' in r.get_data(as_text=True)
    assert _cantidad(app, agente_id) == 1

    _cargar(client, 'LAO', lunes + dt.timedelta(days=3), lunes + dt.timedelta(days=4))  # jue-vie, contiguo
    assert _cantidad(app, agente_id) == 2


def test_solicitud_rechazada_no_bloquea_una_nueva_para_el_mismo_dia(app, client, admin_id, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    lunes = proximo_dia_habil(14)
    _cargar(client, 'LAO', lunes)
    with app.app_context():
        sol_id = Solicitud.query.filter_by(id_agente=agente_id).first().id
    login_como(client, admin_id, 'admin_test')
    client.post(f'/rechazar_solicitud/{sol_id}', data={'comentario_admin': 'no'})

    login_como(client, agente_id, 'agente_test')
    _cargar(client, 'LAO', lunes)
    assert _cantidad(app, agente_id) == 2


def test_coincidir_solo_en_fin_de_semana_no_cuenta_como_superposicion(app, client, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    lunes = proximo_dia_habil(14)
    sabado = lunes + dt.timedelta(days=5)
    _cargar(client, 'LAO', lunes, sabado)  # lun-sáb: 5 días hábiles
    # sáb-lun siguiente: comparte solo el sábado, que no es hábil
    _cargar(client, 'LAO', sabado, lunes + dt.timedelta(days=7))
    assert _cantidad(app, agente_id) == 2


def test_editar_solicitud_no_puede_pisar_otra_pero_si_conservar_sus_fechas(app, client, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    lunes = proximo_dia_habil(14)
    martes = lunes + dt.timedelta(days=1)
    _cargar(client, 'LAO', lunes)
    _cargar(client, 'LAO', martes)
    with app.app_context():
        id_martes = Solicitud.query.filter_by(id_agente=agente_id, fecha_inicio=martes).first().id

    r = client.post('/editar-solicitud-modal', data={
        'id_solicitud': id_martes, 'tipo_licencia': 'LAO',
        'fecha_inicio': lunes.isoformat(), 'fecha_fin': lunes.isoformat(),
    }, follow_redirects=True)
    assert 'Ya tenés una solicitud pendiente' in r.get_data(as_text=True)
    with app.app_context():
        assert Solicitud.query.get(id_martes).fecha_inicio == martes

    r2 = client.post('/editar-solicitud-modal', data={
        'id_solicitud': id_martes, 'tipo_licencia': 'LAO',
        'fecha_inicio': martes.isoformat(), 'fecha_fin': martes.isoformat(),
        'comentario_agente': 'sin cambios de fecha',
    }, follow_redirects=True)
    assert 'actualizada correctamente' in r2.get_data(as_text=True)


def test_no_se_puede_devolver_a_pendientes_una_rechazada_que_pisa_otra_activa(app, client, admin_id, agente_id, proximo_dia_habil):
    login_como(client, agente_id, 'agente_test')
    lunes = proximo_dia_habil(14)
    _cargar(client, 'LAO', lunes)
    with app.app_context():
        rechazada_id = Solicitud.query.filter_by(id_agente=agente_id).first().id
    login_como(client, admin_id, 'admin_test')
    client.post(f'/rechazar_solicitud/{rechazada_id}', data={'comentario_admin': 'no'})

    login_como(client, agente_id, 'agente_test')
    _cargar(client, 'LAO', lunes)  # nueva activa para el mismo día

    login_como(client, admin_id, 'admin_test')
    r = client.post(f'/admin/rectificar-solicitud/{rechazada_id}', data={}, follow_redirects=True)
    assert 'No se puede volver a Pendientes' in r.get_data(as_text=True)
    with app.app_context():
        assert Solicitud.query.get(rechazada_id).estado == 'Rechazada'
