"""Calendario colectivo (privacidad), superposiciones, notificaciones al
agente, reporte de saldos/conexión y exportaciones a Excel."""
import datetime as dt
import io

import pandas as pd

from conftest import login_como
from extensions import db
from models import LimiteCategoria, SaldoLicencia, Solicitud


def _aprobar_licencia(client, app, admin_id, ag_id, fecha_inicio, fecha_fin, categoria='LAO'):
    login_como(client, ag_id, 'agente')  # el username no se valida para autorizar, solo id_agente
    client.post('/nueva-solicitud', data={
        'tipo_licencia': categoria, 'fecha_inicio': fecha_inicio.isoformat(), 'fecha_fin': fecha_fin.isoformat(),
    })
    with app.app_context():
        sol_id = Solicitud.query.filter_by(id_agente=ag_id, fecha_inicio=fecha_inicio).first().id
    login_como(client, admin_id, 'admin_test')
    client.post(f'/aprobar_solicitud/{sol_id}', data={})
    return sol_id


# --- CALENDARIO COLECTIVO ---

def test_calendario_no_expone_categoria_ni_motivo(app, client, admin_id, agente_id, proximo_dia_habil):
    lunes = proximo_dia_habil(14)
    _aprobar_licencia(client, app, admin_id, agente_id, lunes, lunes)

    login_como(client, agente_id, 'agente_test')
    r = client.get(f'/api/calendario/{lunes.year}/{lunes.month}')
    data = r.get_json()
    assert len(data['eventos']) >= 1
    for ev in data['eventos']:
        assert 'tipo' not in ev
        assert 'motivo' not in ev
        assert 'comentario' not in ev
    assert 'agente' in data['eventos'][0]


def test_calendario_incluye_feriados_del_mes(app, client, admin_id, agente_id):
    login_como(client, admin_id, 'admin_test')
    fecha = dt.date.today().replace(day=15) + dt.timedelta(days=32)
    fecha = fecha.replace(day=15)
    client.post('/admin/feriados/agregar', data={'fecha': fecha.isoformat(), 'descripcion': 'Feriado de prueba', 'tipo': 'Nacional'})

    login_como(client, agente_id, 'agente_test')
    r = client.get(f'/api/calendario/{fecha.year}/{fecha.month}')
    data = r.get_json()
    assert any(f['fecha'] == fecha.isoformat() for f in data['feriados'])


# --- SUPERPOSICIONES ---

def test_superposiciones_detecta_licencia_aprobada_de_otro_agente(app, client, admin_id, agente_id, crear_agente, proximo_dia_habil):
    otro_id = crear_agente('otro', saldos={'LAO': 22})
    lunes = proximo_dia_habil(14)
    _aprobar_licencia(client, app, admin_id, otro_id, lunes, lunes)

    login_como(client, agente_id, 'agente_test')
    r = client.get(f'/api/superposiciones?fecha_inicio={lunes.isoformat()}&fecha_fin={lunes.isoformat()}')
    data = r.get_json()
    assert len(data['agentes']) == 1


def test_superposiciones_no_incluye_al_propio_agente(app, client, admin_id, agente_id, proximo_dia_habil):
    lunes = proximo_dia_habil(14)
    _aprobar_licencia(client, app, admin_id, agente_id, lunes, lunes)

    login_como(client, agente_id, 'agente_test')
    r = client.get(f'/api/superposiciones?fecha_inicio={lunes.isoformat()}&fecha_fin={lunes.isoformat()}')
    data = r.get_json()
    assert data['agentes'] == []


# --- NOTIFICACIONES ---

def test_notificacion_aparece_una_sola_vez(app, client, admin_id, agente_id, proximo_dia_habil):
    lunes = proximo_dia_habil(14)
    _aprobar_licencia(client, app, admin_id, agente_id, lunes, lunes)

    login_como(client, agente_id, 'agente_test')
    r1 = client.get('/dashboard')
    assert '1 novedad' in r1.get_data(as_text=True)

    r2 = client.get('/dashboard')
    assert 'badge-pendientes' not in r2.get_data(as_text=True).split('Mis Solicitudes')[1][:300]


# --- REPORTE DE AGENTES ---

def test_reporte_muestra_nunca_sin_login_previo(app, client, admin_id, agente_id):
    login_como(client, admin_id, 'admin_test')
    r = client.get('/admin/reporte')
    assert 'Nunca' in r.get_data(as_text=True)


def test_exportar_reporte_incluye_columnas_esperadas(app, client, admin_id, agente_id):
    login_como(client, admin_id, 'admin_test')
    r = client.get('/admin/reporte/exportar')
    assert r.status_code == 200
    df = pd.read_excel(io.BytesIO(r.data))
    assert 'Agente' in df.columns
    assert 'Última Conexión' in df.columns
    assert 'Licencia Anual Ordinaria (LAO) - Disponibles' in df.columns
    assert len(df) == 2  # admin_id + agente_id


def test_exportar_mi_historial_agente(app, client, agente_id, admin_id, proximo_dia_habil):
    lunes = proximo_dia_habil(14)
    _aprobar_licencia(client, app, admin_id, agente_id, lunes, lunes)

    login_como(client, agente_id, 'agente_test')
    r = client.get('/mi-historial/exportar')
    assert r.status_code == 200
    df = pd.read_excel(io.BytesIO(r.data))
    assert len(df) == 1
    assert df.iloc[0]['Estado'] == 'Aprobada'


def test_reporte_muestra_disponible_real_de_categoria_vencida(app, client, admin_id, agente_id):
    with app.app_context():
        db.session.add(LimiteCategoria(categoria='INVIERNO', fecha_limite=dt.date.today() - dt.timedelta(days=1)))
        db.session.commit()

    login_como(client, admin_id, 'admin_test')

    r = client.get('/admin/reporte')
    html = r.get_data(as_text=True)
    assert '10 de 10' in html  # saldo INVIERNO del fixture: asignados=10, nada usado
    assert '(vencida)' in html

    r2 = client.get('/admin/reporte/exportar')
    df = pd.read_excel(io.BytesIO(r2.data))
    fila_agente = df[df['Agente'].notna()].iloc[-1]
    assert fila_agente['Licencia de Invierno (Feria) - Disponibles'] == 10
    assert fila_agente['Licencia de Invierno (Feria) - Vencida'] == 'Sí'


def test_reporte_no_muestra_disponibles_negativos(app, client, admin_id, agente_id):
    with app.app_context():
        s = SaldoLicencia.query.filter_by(id_agente=agente_id, categoria='LAO').first()
        s.dias_asignados = 0
        s.dias_usados = 22
        db.session.commit()

    login_como(client, admin_id, 'admin_test')
    assert '-22' not in client.get('/admin/reporte').get_data(as_text=True)
    df = pd.read_excel(io.BytesIO(client.get('/admin/reporte/exportar').data))
    assert (df['Licencia Anual Ordinaria (LAO) - Disponibles'] >= 0).all()


def test_reportes_bloqueados_para_no_admin(client, agente_id):
    login_como(client, agente_id, 'agente_test')
    r1 = client.get('/admin/reporte', follow_redirects=True)
    assert 'No tienes permiso' in r1.get_data(as_text=True)
    r2 = client.get('/admin/reporte/exportar', follow_redirects=True)
    assert 'No tienes permiso' in r2.get_data(as_text=True)
