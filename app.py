import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
import pandas as pd
import click

# --- CONFIGURACIÓN INICIAL ---
basedir = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.config['SECRET_KEY'] = 'mi-clave-secreta-muy-dificil-de-adivinar'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'database.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

# --- MODELOS DE LA BASE DE DATOS ---
class Agente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario = db.Column(db.String(80), unique=True, nullable=False)
    clave_hash = db.Column(db.String(120), nullable=False)
    nombre_completo = db.Column(db.String(200), nullable=False)
    es_admin = db.Column(db.Boolean, default=False, nullable=False)
    esta_activo = db.Column(db.Boolean, default=True, nullable=False)
    dias_enero = db.Column(db.Integer, default=22)
    dias_julio = db.Column(db.Integer, default=5)
    dias_compensatorios_usados = db.Column(db.Integer, default=0)
    dias_compensatorios_inicial = db.Column(db.Integer, default=0)
    solicitudes = db.relationship('Solicitud', backref='agente', lazy=True, cascade="all, delete-orphan")

    # <-- CORREGIDO: Se añade la propiedad para calcular los días restantes.
    @property
    def dias_compensatorios_restantes(self):
        """Calcula dinámicamente los días compensatorios disponibles."""
        return self.dias_compensatorios_inicial - self.dias_compensatorios_usados

    def __repr__(self):
        return f'<Agente {self.usuario}>'

class Solicitud(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tipo_licencia = db.Column(db.String(50), nullable=False)
    fecha_inicio = db.Column(db.Date, nullable=False)
    dias_solicitados = db.Column(db.Integer, nullable=False)
    estado = db.Column(db.String(20), nullable=False, default='Pendiente')
    comentario_agente = db.Column(db.Text, nullable=True)
    id_agente = db.Column(db.Integer, db.ForeignKey('agente.id', ondelete='CASCADE'), nullable=False)
    comentario_admin = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<Solicitud {self.id} - {self.tipo_licencia}>'

class Novedad(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(100), nullable=False)
    mensaje = db.Column(db.Text, nullable=False)
    fecha_publicacion = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<Novedad {self.titulo}>'

# --- RUTAS DE LA APLICACIÓN ---
@app.route('/', methods=['GET', 'POST'])
def login():
    if 'id_agente' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        usuario_form = request.form['username']
        clave_form = request.form['password']
        agente_encontrado = Agente.query.filter_by(usuario=usuario_form).first()
        
        if agente_encontrado and not agente_encontrado.esta_activo:
            flash('Tu cuenta ha sido desactivada. Contacta a RRHH.', 'danger')
            return redirect(url_for('login'))

        if agente_encontrado and bcrypt.check_password_hash(agente_encontrado.clave_hash, clave_form):
            session['id_agente'] = agente_encontrado.id
            session['usuario_agente'] = agente_encontrado.usuario
            flash('¡Inicio de sesión exitoso!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Usuario o contraseña incorrectos.', 'danger')
            return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('id_agente', None)
    session.pop('usuario_agente', None)
    flash('Has cerrado la sesión exitosamente.', 'success')
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'id_agente' not in session:
        flash('Por favor, inicia sesión para acceder a esta página.', 'warning')
        return redirect(url_for('login'))
    
    id_del_agente = session['id_agente']
    agente_actual = Agente.query.get(id_del_agente)
    if not agente_actual:
        return redirect(url_for('logout'))
    lista_solicitudes = Solicitud.query.filter_by(id_agente=id_del_agente).order_by(Solicitud.fecha_inicio.desc()).all()
    
    conteos = {
        'aprobadas': sum(1 for sol in lista_solicitudes if sol.estado == 'Aprobada'),
        'pendientes': sum(1 for sol in lista_solicitudes if sol.estado == 'Pendiente'),
        'rechazadas': sum(1 for sol in lista_solicitudes if sol.estado == 'Rechazada')
    }
    
    lista_novedades = Novedad.query.order_by(Novedad.fecha_publicacion.desc()).all()
    
    return render_template('dashboard.html', 
                            agente=agente_actual, 
                            solicitudes=lista_solicitudes, 
                            conteos=conteos,
                            novedades=lista_novedades)

@app.route('/nueva-solicitud', methods=['POST'])
def nueva_solicitud():
    if 'id_agente' not in session:
        flash('Debes iniciar sesión para realizar esta acción.', 'warning')
        return redirect(url_for('login'))

    id_del_agente = session['id_agente']
    agente_actual = Agente.query.get(id_del_agente)
    
    tipo = request.form.get('tipo_licencia')
    fecha_str = request.form.get('fecha_inicio')
    dias = request.form.get('dias_solicitados')
    comentario = request.form.get('comentario_agente')

    if not tipo or not fecha_str or not dias:
        flash('Faltan datos en el formulario.', 'danger')
        return redirect(url_for('dashboard'))

    dias_int = int(dias)

    if 'enero' in tipo.lower() and dias_int > agente_actual.dias_enero:
        flash(f'No tienes suficientes días de Enero. Disponibles: {agente_actual.dias_enero}.', 'danger')
        return redirect(url_for('dashboard'))
    elif 'julio' in tipo.lower() and dias_int > agente_actual.dias_julio:
        flash(f'No tienes suficientes días de Julio. Disponibles: {agente_actual.dias_julio}.', 'danger')
        return redirect(url_for('dashboard'))
    # <-- CORREGIDO: Se valida contra los días restantes.
    elif 'compensatorio' in tipo.lower() and dias_int > agente_actual.dias_compensatorios_restantes:
        flash(f'No tienes suficientes días compensatorios. Disponibles: {agente_actual.dias_compensatorios_restantes}.', 'danger')
        return redirect(url_for('dashboard'))

    fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    nueva_solicitud_db = Solicitud(
        tipo_licencia=tipo,
        fecha_inicio=fecha_obj,
        dias_solicitados=dias_int,
        comentario_agente=comentario,
        id_agente=id_del_agente,
        estado='Pendiente'
    )

    db.session.add(nueva_solicitud_db)
    db.session.commit()
    flash('Tu solicitud de licencia ha sido enviada correctamente.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/mi-perfil', methods=['GET', 'POST'])
def mi_perfil():
    if 'id_agente' not in session:
        flash('Debes iniciar sesión para ver tu perfil.', 'warning')
        return redirect(url_for('login'))

    id_del_agente = session['id_agente']
    agente_a_editar = Agente.query.get(id_del_agente)

    if request.method == 'POST':
        nuevo_usuario = request.form.get('nombre_usuario')
        if nuevo_usuario and nuevo_usuario != agente_a_editar.usuario:
            existente = Agente.query.filter_by(usuario=nuevo_usuario).first()
            if existente and existente.id != agente_a_editar.id:
                flash('Ese nombre de usuario ya está en uso.', 'danger')
                return redirect(url_for('mi_perfil'))
            agente_a_editar.usuario = nuevo_usuario
            session['usuario_agente'] = nuevo_usuario
            flash('Nombre de usuario actualizado.', 'success')

        password_actual = request.form.get('password_actual')
        nueva_password = request.form.get('nueva_password')
        confirmar_password = request.form.get('confirmar_password')

        if password_actual and nueva_password and confirmar_password:
            if not bcrypt.check_password_hash(agente_a_editar.clave_hash, password_actual):
                flash('La contraseña actual es incorrecta.', 'danger')
                return redirect(url_for('mi_perfil'))
            if nueva_password != confirmar_password:
                flash('Las nuevas contraseñas no coinciden.', 'danger')
                return redirect(url_for('mi_perfil'))
            agente_a_editar.clave_hash = bcrypt.generate_password_hash(nueva_password).decode('utf-8')
            flash('Contraseña actualizada correctamente.', 'success')
        
        db.session.commit()
        return redirect(url_for('mi_perfil'))

    return render_template('mi_perfil.html', agente=agente_a_editar)


# --- RUTAS DE ADMINISTRADOR ---
@app.route('/admin')
def panel_admin():
    if 'id_agente' not in session or not Agente.query.get(session['id_agente']).es_admin:
        flash('No tienes permiso para acceder a esta página.', 'danger')
        return redirect(url_for('dashboard'))
    
    admin_actual = Agente.query.get(session['id_agente'])
    solicitudes_pendientes = Solicitud.query.filter_by(estado='Pendiente').order_by(Solicitud.fecha_inicio).all()
    solicitudes_aprobadas = Solicitud.query.filter_by(estado='Aprobada').order_by(Solicitud.fecha_inicio.desc()).all()
    solicitudes_rechazadas = Solicitud.query.filter_by(estado='Rechazada').order_by(Solicitud.fecha_inicio.desc()).all()
    lista_novedades = Novedad.query.order_by(Novedad.fecha_publicacion.desc()).all()
    lista_de_agentes = Agente.query.order_by(Agente.nombre_completo).all()
    
    return render_template('admin_panel.html', 
                            pendientes=solicitudes_pendientes,
                            aprobadas=solicitudes_aprobadas,
                            rechazadas=solicitudes_rechazadas,
                            novedades=lista_novedades,
                            agentes=lista_de_agentes,
                            admin_id=admin_actual.id)

@app.route('/admin/crear-agente', methods=['POST'])
def crear_agente():
    if 'id_agente' not in session or not Agente.query.get(session['id_agente']).es_admin:
        flash('Acción no autorizada.', 'danger')
        return redirect(url_for('login'))

    nombre = request.form.get('nombre_completo')
    usuario = request.form.get('usuario')
    es_admin = request.form.get('es_admin') == 'on'
    
    if not nombre or not usuario:
        flash('Nombre completo y usuario son campos obligatorios.', 'danger')
        return redirect(url_for('panel_admin'))

    if Agente.query.filter_by(usuario=usuario).first():
        flash(f'El nombre de usuario "{usuario}" ya está en uso. Por favor, elige otro.', 'danger')
        return redirect(url_for('panel_admin'))

    try:
        clave_hash = bcrypt.generate_password_hash(usuario).decode('utf-8')
        nuevo_agente = Agente(
            nombre_completo=nombre,
            usuario=usuario,
            clave_hash=clave_hash,
            es_admin=es_admin,
            dias_enero=int(request.form.get('dias_enero', 22)),
            dias_julio=int(request.form.get('dias_julio', 5)),
            dias_compensatorios_inicial=int(request.form.get('dias_compensatorios', 0))
        )
        db.session.add(nuevo_agente)
        db.session.commit()
        flash(f"El agente '{nombre}' ha sido creado. Su contraseña es su nombre de usuario.", 'success')
    except Exception as e:
        db.session.rollback()
        flash(f"Ocurrió un error al crear el agente: {e}", 'danger')

    return redirect(url_for('panel_admin'))

@app.route('/admin/eliminar-agente/<int:id_agente>', methods=['POST'])
def eliminar_agente(id_agente):
    if 'id_agente' not in session or not Agente.query.get(session['id_agente']).es_admin:
        flash('Acción no autorizada.', 'danger')
        return redirect(url_for('login'))

    admin_actual = Agente.query.get(session['id_agente'])
    agente_a_eliminar = Agente.query.get_or_404(id_agente)

    if admin_actual.id == agente_a_eliminar.id:
        flash('No puedes eliminar tu propia cuenta de administrador.', 'danger')
        return redirect(url_for('panel_admin'))
    
    if agente_a_eliminar.es_admin:
        total_admins = Agente.query.filter_by(es_admin=True).count()
        if total_admins <= 1:
            flash('Acción no permitida. No se puede eliminar la última cuenta de administrador.', 'danger')
            return redirect(url_for('panel_admin'))

    try:
        nombre_eliminado = agente_a_eliminar.nombre_completo
        db.session.delete(agente_a_eliminar)
        db.session.commit()
        flash(f'El agente "{nombre_eliminado}" y todas sus solicitudes han sido eliminados permanentemente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ocurrió un error al eliminar el agente: {e}', 'danger')
        
    return redirect(url_for('panel_admin'))


@app.route('/admin/toggle-agente/<int:id_agente>', methods=['POST'])
def toggle_agente(id_agente):
    if 'id_agente' not in session:
        return jsonify({'success': False, 'error': 'Acceso no autorizado.'}), 401

    admin_actual = Agente.query.get(session['id_agente'])
    if not admin_actual or not admin_actual.es_admin:
        return jsonify({'success': False, 'error': 'No tienes permiso para esta acción.'}), 403

    agente_a_modificar = Agente.query.get_or_404(id_agente)

    if agente_a_modificar.id == admin_actual.id:
        return jsonify({'success': False, 'error': 'Acción no permitida: No puedes desactivar tu propia cuenta.'}), 403

    agente_a_modificar.esta_activo = not agente_a_modificar.esta_activo
    
    try:
        db.session.commit()
        nuevo_estado_texto = "Activo" if agente_a_modificar.esta_activo else "Inactivo"
        nuevo_estado_clase = "approved" if agente_a_modificar.esta_activo else "rejected"
        nuevo_boton_texto = "Desactivar" if agente_a_modificar.esta_activo else "Activar"
        nuevo_boton_clase = "deactivate" if agente_a_modificar.esta_activo else "activate"
        
        return jsonify({
            'success': True,
            'message': f"La cuenta de '{agente_a_modificar.nombre_completo}' ha sido actualizada.",
            'nuevo_estado_texto': nuevo_estado_texto,
            'nuevo_estado_clase': nuevo_estado_clase,
            'nuevo_boton_texto': nuevo_boton_texto,
            'nuevo_boton_clase': nuevo_boton_clase
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f"Error al actualizar el estado del agente: {e}"}), 500

@app.route('/admin/editar-agente/<int:id_agente>', methods=['POST'])
def editar_agente(id_agente):
    if 'id_agente' not in session:
        flash('Debes iniciar sesión para realizar esta acción.', 'warning')
        return redirect(url_for('login'))

    admin_actual = Agente.query.get(session['id_agente'])
    if not admin_actual or not admin_actual.es_admin:
        flash('No tienes permiso para acceder a esta funcionalidad.', 'danger')
        return redirect(url_for('dashboard'))

    agente_a_editar = Agente.query.get_or_404(id_agente)

    nuevo_usuario = request.form.get('usuario')
    es_admin_form = request.form.get('es_admin') == 'on'

    existente = Agente.query.filter(Agente.usuario == nuevo_usuario, Agente.id != id_agente).first()
    if existente:
        flash(f"El nombre de usuario '{nuevo_usuario}' ya está en uso. No se guardaron los cambios.", 'danger')
        return redirect(url_for('panel_admin'))

    if agente_a_editar.es_admin and not es_admin_form:
        total_admins = Agente.query.filter_by(es_admin=True).count()
        if total_admins <= 1:
            flash('Acción no permitida: No se puede quitar el rol de administrador a la última cuenta de administrador.', 'danger')
            return redirect(url_for('panel_admin'))

    try:
        agente_a_editar.nombre_completo = request.form.get('nombre_completo')
        agente_a_editar.usuario = nuevo_usuario
        agente_a_editar.dias_enero = int(request.form.get('dias_enero'))
        agente_a_editar.dias_julio = int(request.form.get('dias_julio'))
        # <-- CORREGIDO: Se actualiza el valor inicial, no los usados.
        agente_a_editar.dias_compensatorios_inicial = int(request.form.get('dias_compensatorios'))
        agente_a_editar.es_admin = es_admin_form

        nueva_clave = request.form.get('nueva_clave')
        if nueva_clave:
            agente_a_editar.clave_hash = bcrypt.generate_password_hash(nueva_clave).decode('utf-8')

        db.session.commit()
        flash(f"Los datos de '{agente_a_editar.nombre_completo}' han sido actualizados.", 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al actualizar el agente: {e}', 'danger')

    return redirect(url_for('panel_admin'))

@app.route('/aprobar_solicitud/<int:id_solicitud>', methods=['POST'])
def aprobar_solicitud(id_solicitud):
    if 'id_agente' not in session or not Agente.query.get(session['id_agente']).es_admin:
        flash('Acción no autorizada.', 'danger')
        return redirect(url_for('login'))

    solicitud = Solicitud.query.get_or_404(id_solicitud)
    agente = solicitud.agente
    
    comentario_del_admin = request.form.get('comentario_admin')
    solicitud.comentario_admin = comentario_del_admin

    tipo_licencia = solicitud.tipo_licencia.lower()

    if 'enero' in tipo_licencia:
        if agente.dias_enero >= solicitud.dias_solicitados:
            agente.dias_enero -= solicitud.dias_solicitados
            solicitud.estado = 'Aprobada'
            flash(f"Solicitud de {agente.nombre_completo} APROBADA.", 'success')
        else:
            solicitud.estado = 'Rechazada'
            flash(f"Solicitud RECHAZADA por falta de días.", 'danger')
    elif 'julio' in tipo_licencia:
        if agente.dias_julio >= solicitud.dias_solicitados:
            agente.dias_julio -= solicitud.dias_solicitados
            solicitud.estado = 'Aprobada'
            flash(f"Solicitud de {agente.nombre_completo} APROBADA.", 'success')
        else:
            solicitud.estado = 'Rechazada'
            flash(f"Solicitud RECHAZADA por falta de días.", 'danger')
    # <-- CORREGIDO: Lógica de aprobación para compensatorios.
    elif 'compensatorio' in tipo_licencia:
        if agente.dias_compensatorios_restantes >= solicitud.dias_solicitados:
            agente.dias_compensatorios_usados += solicitud.dias_solicitados
            solicitud.estado = 'Aprobada'
            flash(f"Solicitud de {agente.nombre_completo} APROBADA.", 'success')
        else:
            solicitud.estado = 'Rechazada'
            flash(f"Solicitud RECHAZADA por falta de días.", 'danger')
    else:
        # Para otros tipos de licencia que no descuentan días
        solicitud.estado = 'Aprobada'
        flash(f"Solicitud de {agente.nombre_completo} APROBADA.", 'success')

    db.session.commit()
    return redirect(url_for('panel_admin'))

@app.route('/rechazar_solicitud/<int:id_solicitud>', methods=['POST'])
def rechazar_solicitud(id_solicitud):
    if 'id_agente' not in session or not Agente.query.get(session['id_agente']).es_admin:
        flash('Acción no autorizada.', 'danger')
        return redirect(url_for('login'))
    
    solicitud = Solicitud.query.get_or_404(id_solicitud)
    solicitud.estado = 'Rechazada'

    comentario_del_admin = request.form.get('comentario_admin')
    solicitud.comentario_admin = comentario_del_admin

    db.session.commit()
    flash(f"La solicitud de {solicitud.agente.nombre_completo} ha sido RECHAZADA.", 'warning')
    return redirect(url_for('panel_admin'))

@app.route('/admin/rectificar-solicitud/<int:id_solicitud>', methods=['POST'])
def rectificar_solicitud(id_solicitud):
    if 'id_agente' not in session or not Agente.query.get(session['id_agente']).es_admin:
        flash('Acción no autorizada.', 'danger')
        return redirect(url_for('login'))

    solicitud = Solicitud.query.get_or_404(id_solicitud)
    agente = solicitud.agente
    estado_anterior = solicitud.estado

    if estado_anterior == 'Aprobada':
        tipo_licencia = solicitud.tipo_licencia.lower()
        if 'enero' in tipo_licencia:
            agente.dias_enero += solicitud.dias_solicitados
        elif 'julio' in tipo_licencia:
            agente.dias_julio += solicitud.dias_solicitados
        # <-- CORREGIDO: Se devuelven los días restando de los usados.
        elif 'compensatorio' in tipo_licencia:
            agente.dias_compensatorios_usados -= solicitud.dias_solicitados

    solicitud.estado = 'Pendiente'
    solicitud.comentario_admin = None
    
    db.session.commit()

    flash(f'La solicitud de {agente.nombre_completo} ha sido movida a Pendientes.', 'info')
    return redirect(url_for('panel_admin'))

@app.route('/admin/nueva_novedad', methods=['POST'])
def publicar_novedad():
    if 'id_agente' not in session or not Agente.query.get(session['id_agente']).es_admin:
        flash('Acción no autorizada.', 'danger')
        return redirect(url_for('login'))
    titulo = request.form['titulo']
    mensaje = request.form['mensaje']
    nueva_novedad = Novedad(titulo=titulo, mensaje=mensaje)
    db.session.add(nueva_novedad)
    db.session.commit()
    flash('La novedad ha sido publicada exitosamente.', 'success')
    return redirect(url_for('panel_admin'))

@app.route('/admin/editar-novedad/<int:id_novedad>', methods=['POST'])
def editar_novedad(id_novedad):
    if 'id_agente' not in session or not Agente.query.get(session['id_agente']).es_admin:
        flash('Acción no autorizada.', 'danger')
        return redirect(url_for('login'))

    novedad_a_editar = Novedad.query.get_or_404(id_novedad)
    novedad_a_editar.titulo = request.form.get('titulo')
    novedad_a_editar.mensaje = request.form.get('mensaje')
    db.session.commit()
    
    flash('La novedad ha sido actualizada exitosamente.', 'success')
    return redirect(url_for('panel_admin'))

@app.route('/admin/eliminar_novedad/<int:id_novedad>', methods=['POST'])
def eliminar_novedad(id_novedad):
    if 'id_agente' not in session or not Agente.query.get(session['id_agente']).es_admin:
        flash('Acción no autorizada.', 'danger')
        return redirect(url_for('login'))
    
    novedad_a_eliminar = Novedad.query.get_or_404(id_novedad)
    db.session.delete(novedad_a_eliminar)
    db.session.commit()
    
    flash('La novedad ha sido eliminada exitosamente.', 'success')
    return redirect(url_for('panel_admin'))

# --- COMANDOS DE LA CLI ---
@app.cli.command('init-db')
def init_db_command():
    """Limpia los datos existentes y crea las tablas vacías."""
    db.drop_all()
    db.create_all()
    print('¡Base de datos inicializada con las tablas vacías!')


@app.cli.command('import-agents')
@click.argument('filepath')
def import_agents_command(filepath):
    """Importa agentes y sus días disponibles desde un archivo .xlsx."""
    try:
        df = pd.read_excel(filepath).fillna('')
        print(f"Archivo '{filepath}' leído correctamente. {len(df)} agentes encontrados.")
    except Exception as e:
        print(f"Error al leer el archivo de Excel: {e}")
        return

    agentes_importados = 0
    agentes_omitidos = 0

    for index, row in df.iterrows():
        usuario = str(row.get('usuario', ''))
        if not usuario:
            continue 

        existente = Agente.query.filter_by(usuario=usuario).first()
        if existente:
            print(f"Omitiendo: El usuario '{usuario}' ya existe.")
            agentes_omitidos += 1
            continue

        es_admin_val = str(row.get('es_admin', 'No')).lower()
        es_admin = es_admin_val in ['si', 's', 'true', '1']

        try:
            dias_e = int(row.get('dias_enero') if row.get('dias_enero') != '' else Agente.dias_enero.default)
            dias_j = int(row.get('dias_julio') if row.get('dias_julio') != '' else Agente.dias_julio.default)
            # <-- CORREGIDO: Se lee el valor del excel.
            dias_c = int(row.get('dias_compensatorios') if row.get('dias_compensatorios') != '' else Agente.dias_compensatorios_inicial.default)
        except (ValueError, TypeError):
            print(f"Alerta: Datos de días no válidos para '{usuario}'. Usando valores por defecto.")
            dias_e = Agente.dias_enero.default
            dias_j = Agente.dias_julio.default
            dias_c = Agente.dias_compensatorios_inicial.default
        
        clave_hash = bcrypt.generate_password_hash(usuario).decode('utf-8')
        
        nuevo_agente = Agente(
            usuario=usuario,
            nombre_completo=row['nombre_completo'],
            clave_hash=clave_hash,
            es_admin=es_admin,
            dias_enero=dias_e,
            dias_julio=dias_j,
            dias_compensatorios_inicial=dias_c
        )
        db.session.add(nuevo_agente)
        agentes_importados += 1
        print(f"Importando: {nuevo_agente.nombre_completo} con días ({dias_e}, {dias_j}, {dias_c})...")

    if agentes_importados > 0:
        db.session.commit()
        print("\n¡Importación completada!")
        print(f"Agentes nuevos creados: {agentes_importados}")
        print(f"Agentes omitidos (ya existían): {agentes_omitidos}")
        print(f"IMPORTANTE: La contraseña temporal para cada nuevo agente es su propio nombre de usuario.")
    else:
        print("\nNo se importaron nuevos agentes.")


@app.cli.command('import-history')
@click.argument('filepath')
def import_history_command(filepath):
    """
    Importa el historial de licencias aprobadas desde un archivo .xlsx,
    crea los registros y actualiza los saldos de días de los agentes.
    """
    try:
        df = pd.read_excel(filepath)
        print(f"Archivo de historial '{filepath}' leído. {len(df)} registros encontrados.")
    except Exception as e:
        print(f"Error al leer el archivo de Excel: {e}")
        return

    registros_importados = 0
    agentes_actualizados = set()

    for index, row in df.iterrows():
        usuario = row.get('usuario')
        tipo_licencia = row.get('tipo_licencia')
        dias = row.get('dias_solicitados')
        fecha_inicio_obj = row.get('fecha_inicio')

        if not all([usuario, tipo_licencia, dias, fecha_inicio_obj]):
            print(f"Omitiendo fila {index+2}: Faltan datos.")
            continue
        
        agente = Agente.query.filter_by(usuario=str(usuario)).first()
        if not agente:
            print(f"Omitiendo registro para el usuario '{usuario}': No se encontró en la base de datos.")
            continue

        try:
            dias_int = int(dias)
            
            solicitud_historica = Solicitud(
                id_agente=agente.id,
                tipo_licencia=tipo_licencia,
                fecha_inicio=fecha_inicio_obj.date(),
                dias_solicitados=dias_int,
                estado='Aprobada',
                comentario_admin='Carga histórica de sistema anterior.'
            )
            db.session.add(solicitud_historica)
            
            tipo_licencia_lower = tipo_licencia.lower()
            if 'enero' in tipo_licencia_lower:
                agente.dias_enero -= dias_int
            elif 'julio' in tipo_licencia_lower:
                agente.dias_julio -= dias_int
            # <-- CORREGIDO: Se suman los días históricos a la cuenta de usados.
            elif 'compensatorio' in tipo_licencia_lower:
                agente.dias_compensatorios_usados += dias_int
            
            registros_importados += 1
            agentes_actualizados.add(agente.nombre_completo)

        except Exception as e:
            print(f"Error procesando registro para '{usuario}': {e}")
            db.session.rollback()
            continue

    if registros_importados > 0:
        db.session.commit()
        print("\n¡Importación de historial completada!")
        print(f"Total de registros de licencias importados: {registros_importados}")
        print(f"Total de agentes con saldos actualizados: {len(agentes_actualizados)}")
    else:
        print("\nNo se importaron nuevos registros históricos.")

# --- INICIAR LA APLICACIÓN ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False)