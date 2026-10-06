"""Novedades: sanitización del HTML del editor enriquecido, para que no se
cuele un script ni un atributo peligroso."""
from conftest import login_como
from models import Novedad


def test_publicar_novedad_conserva_formato_basico(app, client, admin_id):
    login_como(client, admin_id, 'admin_test')
    r = client.post('/admin/nueva_novedad', data={
        'titulo': 'Aviso', 'mensaje': '<b>Importante:</b> <u>reunión</u> mañana',
    })
    assert r.status_code == 302
    with app.app_context():
        n = Novedad.query.filter_by(titulo='Aviso').first()
        assert '<b>Importante:</b>' in n.mensaje
        assert '<u>reunión</u>' in n.mensaje


def test_publicar_novedad_elimina_script(app, client, admin_id):
    login_como(client, admin_id, 'admin_test')
    client.post('/admin/nueva_novedad', data={
        'titulo': 'Malicioso', 'mensaje': '<script>alert(1)</script>texto',
    })
    with app.app_context():
        n = Novedad.query.filter_by(titulo='Malicioso').first()
        assert '<script>' not in n.mensaje
        assert 'texto' in n.mensaje  # el texto se conserva, el tag no


def test_publicar_novedad_elimina_atributos_peligrosos(app, client, admin_id):
    login_como(client, admin_id, 'admin_test')
    client.post('/admin/nueva_novedad', data={
        'titulo': 'Con onclick', 'mensaje': '<b onclick="alert(1)">negrita</b>',
    })
    with app.app_context():
        n = Novedad.query.filter_by(titulo='Con onclick').first()
        assert 'onclick' not in n.mensaje
        assert '<b>negrita</b>' in n.mensaje


def test_publicar_novedad_elimina_link_javascript(app, client, admin_id):
    login_como(client, admin_id, 'admin_test')
    client.post('/admin/nueva_novedad', data={
        'titulo': 'Link malicioso', 'mensaje': '<a href="javascript:alert(1)">click</a>',
    })
    with app.app_context():
        n = Novedad.query.filter_by(titulo='Link malicioso').first()
        assert 'javascript:' not in n.mensaje
        assert '<a' not in n.mensaje  # <a> no esta en la lista de tags permitidos


def test_editar_novedad_tambien_sanitiza(app, client, admin_id):
    login_como(client, admin_id, 'admin_test')
    client.post('/admin/nueva_novedad', data={'titulo': 'Original', 'mensaje': 'texto plano'})
    with app.app_context():
        n_id = Novedad.query.filter_by(titulo='Original').first().id

    client.post(f'/admin/editar-novedad/{n_id}', data={
        'titulo': 'Editada', 'mensaje': '<script>alert(2)</script><i>cursiva</i>',
    })
    with app.app_context():
        n = Novedad.query.get(n_id)
        assert '<script>' not in n.mensaje
        assert '<i>cursiva</i>' in n.mensaje


def test_novedad_se_muestra_con_formato_en_el_dashboard(app, client, admin_id, agente_id):
    login_como(client, admin_id, 'admin_test')
    client.post('/admin/nueva_novedad', data={'titulo': 'Aviso', 'mensaje': '<b>texto en negrita</b>'})

    login_como(client, agente_id, 'agente_test')
    r = client.get('/dashboard')
    texto = r.get_data(as_text=True)
    assert '<b>texto en negrita</b>' in texto
