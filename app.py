import os
import io
import shutil
import secrets
from calendar import monthrange
from datetime import datetime, date, time, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file
import pandas as pd
import click

from extensions import db, bcrypt, csrf
from models import (
    CATEGORIAS, TIPOS_ACTIVIDAD, Agente, SaldoLicencia, Feriado, PeriodoVeda, LimiteCategoria,
    Solicitud, Novedad, RegistroActividad,
)
from motor_licencias import (
    CUTOFF_HORA, cargar_feriados, contar_dias_habiles, fecha_fin_para_n_dias_habiles,
    calcular_cutoff, recalcular_por_nuevo_feriado, _obtener_o_crear_saldo,
    _normalizar_categoria, _limite_categoria, _categoria_vencida, _crear_solicitud,
    buscar_superposicion, mensaje_superposicion,
    _sanitizar_mensaje,
)

MENSAJE_FUERA_DE_PLAZO = (
    'Fuera de plazo para solicitar esta solicitud, deberá informar al '
    'Director/Jefa de Personal por teléfono.'
)

# --- CONFIGURACIÓN INICIAL ---
basedir = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)

# La SECRET_KEY ya no queda escrita en el código fuente: se toma de la variable
# de entorno SECRET_KEY si existe, y si no se genera una sola vez y se guarda
# en un archivo local (excluido del repositorio) para que la sesión no se
# invalide cada vez que se reinicia la app.
_secret_key_path = os.path.join(basedir, '.secret_key')
if os.environ.get('SECRET_KEY'):
    _secret_key = os.environ['SECRET_KEY']
elif os.path.exists(_secret_key_path):
    with open(_secret_key_path, 'r') as f:
        _secret_key = f.read().strip()
else:
    _secret_key = secrets.token_hex(32)
    with open(_secret_key_path, 'w') as f:
        f.write(_secret_key)

app.config['SECRET_KEY'] = _secret_key

# La base de datos también se puede apuntar por variable de entorno —
# principalmente para que los tests (ver tests/conftest.py) corran contra un
# archivo temporal en vez de la base real. Sin DATABASE_URL, se usa
# database.db en el directorio del proyecto, como siempre.
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL', 'sqlite:///' + os.path.join(basedir, 'database.db')
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
bcrypt.init_app(app)
csrf.init_app(app)


# --- BITÁCORA DE ACTIVIDAD ---
def registrar_actividad(tipo, detalle, agente=None, actor_texto=None, commit=False):
    """Agrega una línea a la bitácora (ver RegistroActividad). Por defecto no
    hace commit: se suma a la transacción de la acción que se está registrando,
    así la acción y su registro se guardan juntos o no se guardan. Quien actuó
    sale del parámetro `agente`, o de la sesión, o de `actor_texto` si es
    alguien sin cuenta (ej. un intento de ingreso con un usuario inexistente)."""
    id_actor = None
    if actor_texto:
        nombre = actor_texto
    else:
        if agente is None and session.get('id_agente'):
            agente = db.session.get(Agente, session['id_agente'])
        id_actor = agente.id if agente else None
        nombre = agente.nombre_completo if agente else 'Sistema'
    db.session.add(RegistroActividad(
        id_actor=id_actor, actor=nombre[:200], tipo=tipo, detalle=detalle[:500],
    ))
    if commit:
        db.session.commit()


def _desc_solicitud(s, agente=None):
    """'NOMBRE (Categoría, 10/11/2026 al 12/11/2026, 3 día(s))' para el detalle."""
    ag = agente or s.agente
    etiqueta = CATEGORIAS.get(s.tipo_licencia, {}).get('label', s.tipo_licencia)
    fin = s.fecha_fin or s.fecha_inicio
    return (f'{ag.nombre_completo} ({etiqueta}, {s.fecha_inicio.strftime("%d/%m/%Y")} al '
            f'{fin.strftime("%d/%m/%Y")}, {s.dias_solicitados} día(s))')


def _registrar_rechazo(motivo, categoria, fecha_inicio=None, fecha_fin=None):
    """Intento bloqueado por el sistema (fuera de plazo, sin saldo, veda...)."""
    partes = [CATEGORIAS.get(categoria, {}).get('label', categoria or '?')]
    if fecha_inicio and fecha_fin:
        partes.append(f'{fecha_inicio.strftime("%d/%m/%Y")} al {fecha_fin.strftime("%d/%m/%Y")}')
    registrar_actividad('rechazo', f'{motivo} — {", ".join(partes)}', commit=True)


# --- MIGRACIÓN DE ESQUEMA ---
def migrar_esquema():
    """Migra database.db al esquema nuevo sin perder datos. Corre
    automáticamente al importar el módulo; cada paso está guardado por una
    comprobación de existencia (tabla/columna/fila), así que es seguro que
    se ejecute en cada arranque de la app."""
    with app.app_context():
        inspector = db.inspect(db.engine)
        tablas_actuales = inspector.get_table_names()

        # 1) Se elimina Permiso por completo (decisión del cliente). Se toma
        #    un backup automático de la base como red de seguridad operativa
        #    antes de un cambio destructivo, aunque no se pidió conservar
        #    los datos de permisos.
        if 'permiso' in tablas_actuales:
            # <-- CORREGIDO: antes esto asumía que la base siempre está en
            # basedir/database.db, ignorando DATABASE_URL (usada por los
            # tests y por cualquier despliegue con otra ruta). Se toma la
            # ruta real del archivo sqlite configurado.
            db_uri = app.config['SQLALCHEMY_DATABASE_URI']
            db_path = db_uri[len('sqlite:///'):] if db_uri.startswith('sqlite:///') else None
            if db_path and os.path.exists(db_path):
                backup_path = os.path.join(
                    os.path.dirname(db_path) or basedir,
                    f'database.backup-pre-licencias-{datetime.now():%Y%m%d%H%M%S}.db'
                )
                shutil.copy2(db_path, backup_path)
                print(f'[migracion] Backup de seguridad creado en {backup_path}')
            with db.engine.begin() as conn:
                conn.exec_driver_sql('DROP TABLE permiso')

        # 2) Crea las tablas nuevas (SaldoLicencia, Feriado, PeriodoVeda) si
        #    todavía no existen.
        db.create_all()

        inspector = db.inspect(db.engine)
        cols_agente = {c['name'] for c in inspector.get_columns('agente')}
        cols_solicitud = {c['name'] for c in inspector.get_columns('solicitud')}

        # 3) Columnas nuevas en agente / solicitud
        with db.engine.begin() as conn:
            if 'examen_estudio_habilitado' not in cols_agente:
                conn.exec_driver_sql(
                    'ALTER TABLE agente ADD COLUMN examen_estudio_habilitado BOOLEAN DEFAULT 0'
                )
            if 'ultimo_login' not in cols_agente:
                conn.exec_driver_sql('ALTER TABLE agente ADD COLUMN ultimo_login DATETIME')
            if 'fecha_fin' not in cols_solicitud:
                conn.exec_driver_sql('ALTER TABLE solicitud ADD COLUMN fecha_fin DATE')
            if 'es_oficio' not in cols_solicitud:
                conn.exec_driver_sql('ALTER TABLE solicitud ADD COLUMN es_oficio BOOLEAN DEFAULT 0')
            if 'constancia_aviso' not in cols_solicitud:
                conn.exec_driver_sql('ALTER TABLE solicitud ADD COLUMN constancia_aviso TEXT')
            if 'creado_en' not in cols_solicitud:
                conn.exec_driver_sql('ALTER TABLE solicitud ADD COLUMN creado_en DATETIME')
            if 'notificado' not in cols_solicitud:
                # DEFAULT 1 se aplica a las filas existentes: el historial no
                # genera notificaciones falsas al desplegar esta columna.
                conn.exec_driver_sql('ALTER TABLE solicitud ADD COLUMN notificado BOOLEAN DEFAULT 1')

        # 4) Backfill de fecha_fin/creado_en en solicitudes viejas, con la
        #    fórmula vieja (días corridos) porque son licencias históricas
        #    que ya se habían aprobado con ese criterio.
        pendientes_backfill = Solicitud.query.filter(Solicitud.fecha_fin.is_(None)).all()
        for s in pendientes_backfill:
            s.fecha_fin = s.fecha_inicio + timedelta(days=s.dias_solicitados - 1)
            if not s.creado_en:
                s.creado_en = datetime.combine(s.fecha_inicio, time(0, 0))
        if pendientes_backfill:
            db.session.commit()

        # 5) Migra los saldos viejos (dias_enero/dias_julio/compensatorios)
        #    a SaldoLicencia. Las columnas viejas ya no están en el modelo
        #    ORM (se dejaron físicamente en la tabla a propósito, sin
        #    DROP COLUMN, para no depender de la versión de SQLite), así que
        #    se leen con SQL crudo.
        existentes = {(s.id_agente, s.categoria) for s in SaldoLicencia.query.all()}
        columnas_viejas = {
            'dias_enero', 'dias_julio', 'dias_compensatorios_usados', 'dias_compensatorios_inicial'
        }

        if columnas_viejas.issubset(cols_agente):
            # <-- CORREGIDO: dias_enero/dias_julio son el saldo REMANENTE, no
            # el cupo total. Si existen dias_enero_inicial/dias_julio_inicial
            # (agregadas en una migración anterior) se usan como el cupo
            # verdadero y la diferencia con el remanente pasa a dias_usados;
            # así el dashboard muestra "6 de 22" en vez de "6 de 6".
            tiene_iniciales = {'dias_enero_inicial', 'dias_julio_inicial'}.issubset(cols_agente)
            if tiene_iniciales:
                columnas_sql = (
                    'id, dias_enero, dias_enero_inicial, dias_julio, dias_julio_inicial, '
                    'dias_compensatorios_usados, dias_compensatorios_inicial'
                )
            else:
                columnas_sql = 'id, dias_enero, dias_julio, dias_compensatorios_usados, dias_compensatorios_inicial'

            with db.engine.begin() as conn:
                filas = conn.exec_driver_sql(f'SELECT {columnas_sql} FROM agente').fetchall()

            for fila in filas:
                if tiene_iniciales:
                    agente_id, dias_enero, dias_enero_inicial, dias_julio, dias_julio_inicial, comp_usados, comp_inicial = fila
                else:
                    agente_id, dias_enero, dias_julio, comp_usados, comp_inicial = fila
                    dias_enero_inicial = dias_enero
                    dias_julio_inicial = dias_julio

                lao_asignados = dias_enero_inicial if dias_enero_inicial is not None else (dias_enero or 0)
                lao_usados = max(0, lao_asignados - (dias_enero or 0))
                invierno_asignados = dias_julio_inicial if dias_julio_inicial is not None else (dias_julio or 0)
                invierno_usados = max(0, invierno_asignados - (dias_julio or 0))

                valores = {
                    'LAO': (lao_asignados, lao_usados),
                    'INVIERNO': (invierno_asignados, invierno_usados),
                    'COMPENSATORIO': (comp_inicial or 0, comp_usados or 0),
                    'EXAMEN_ESTUDIO': (0, 0),
                }
                for categoria, (asignados, usados) in valores.items():
                    if (agente_id, categoria) not in existentes:
                        db.session.add(SaldoLicencia(
                            id_agente=agente_id, categoria=categoria,
                            dias_asignados=asignados, dias_usados=usados, dias_pendientes=0
                        ))
            db.session.commit()
        else:
            # Agentes creados ya con el esquema nuevo: asegura que cada uno
            # tenga sus 4 filas de saldo con el cupo por defecto.
            for agente in Agente.query.all():
                for codigo, meta in CATEGORIAS.items():
                    if (agente.id, codigo) not in existentes:
                        cupo = 0 if codigo == 'EXAMEN_ESTUDIO' else meta['cupo_default']
                        db.session.add(SaldoLicencia(
                            id_agente=agente.id, categoria=codigo, dias_asignados=cupo
                        ))
            db.session.commit()

        # 6) Normaliza tipo_licencia en solicitudes históricas que todavía
        #    tienen el texto libre del sistema anterior (ej. "Vacaciones
        #    Enero", "Compensatorios") en vez del código de categoría, para
        #    que se muestren con el nombre unificado en vez del texto viejo.
        #    Se persiste una sola vez por fila; una vez normalizada,
        #    _normalizar_categoria la devuelve igual (idempotente).
        sin_normalizar = [s for s in Solicitud.query.all() if s.tipo_licencia not in CATEGORIAS]
        cambios = False
        for s in sin_normalizar:
            categoria = _normalizar_categoria(s.tipo_licencia)
            if categoria:
                s.tipo_licencia = categoria
                cambios = True
        if cambios:
            db.session.commit()


migrar_esquema()

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
            registrar_actividad('ingreso', 'Ingreso bloqueado: la cuenta está desactivada',
                                agente=agente_encontrado, commit=True)
            flash('Tu cuenta ha sido desactivada. Contacta a RRHH.', 'danger')
            return redirect(url_for('login'))

        if agente_encontrado and bcrypt.check_password_hash(agente_encontrado.clave_hash, clave_form):
            session['id_agente'] = agente_encontrado.id
            session['usuario_agente'] = agente_encontrado.usuario
            agente_encontrado.ultimo_login = datetime.now()
            registrar_actividad('ingreso', 'Inició sesión', agente=agente_encontrado)
            db.session.commit()
            flash('¡Inicio de sesión exitoso!', 'success')
            return redirect(url_for('dashboard'))
        else:
            if agente_encontrado:
                registrar_actividad('ingreso', 'Ingreso fallido: contraseña incorrecta',
                                    agente=agente_encontrado, commit=True)
            else:
                registrar_actividad('ingreso', f'Ingreso fallido: el usuario "{usuario_form}" no existe',
                                    actor_texto=f'Usuario "{usuario_form}"', commit=True)
            flash('Usuario o contraseña incorrectos.', 'danger')
            return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    if session.get('id_agente'):
        registrar_actividad('ingreso', 'Cerró sesión', commit=True)
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

    # Notificaciones: solicitudes resueltas (aprobadas/rechazadas) desde la
    # última vez que el agente vio su dashboard. Se cuentan acá y se marcan
    # como vistas de inmediato, así el aviso solo aparece una vez.
    sin_notificar = [s for s in lista_solicitudes if s.estado != 'Pendiente' and not s.notificado]
    notificaciones_nuevas = len(sin_notificar)
    if sin_notificar:
        for s in sin_notificar:
            s.notificado = True
        db.session.commit()

    saldos_por_categoria = {
        s.categoria: s for s in SaldoLicencia.query.filter_by(id_agente=id_del_agente).all()
    }
    saldos_vista = []
    for codigo, meta in CATEGORIAS.items():
        if codigo == 'EXAMEN_ESTUDIO' and not agente_actual.examen_estudio_habilitado:
            continue
        saldo = saldos_por_categoria.get(codigo)
        asignados = saldo.dias_asignados if saldo else 0
        usados = saldo.dias_usados if saldo else 0
        pendientes = saldo.dias_pendientes if saldo else 0
        fecha_limite = _limite_categoria(codigo)
        vencida = fecha_limite is not None and date.today() > fecha_limite
        # <-- NUEVO: pasado el plazo de una categoría, los días no
        # solicitados se muestran en 0 (sin tocar asignados/usados: si el
        # admin extiende la fecha, vuelven a aparecer solos).
        disponibles = 0 if vencida else max(0, asignados - (usados + pendientes))
        saldos_vista.append({
            'categoria': codigo,
            'label': meta['label'],
            'asignados': asignados,
            'usados': usados,
            'pendientes': pendientes,
            'vencida': vencida,
            'fecha_limite': fecha_limite,
            'disponibles': disponibles,
        })

    lista_novedades = Novedad.query.order_by(Novedad.fecha_publicacion.desc()).all()
    total_pendientes_global = 0
    if agente_actual.es_admin:
        total_pendientes_global = Solicitud.query.filter_by(estado='Pendiente').count()

    categorias_agente = {
        codigo: meta for codigo, meta in CATEGORIAS.items()
        if (codigo != 'EXAMEN_ESTUDIO' or agente_actual.examen_estudio_habilitado)
        and not _categoria_vencida(codigo)
    }

    proximos_feriados = Feriado.query.filter(
        Feriado.fecha >= date.today()
    ).order_by(Feriado.fecha).limit(3).all()

    return render_template(
        'dashboard.html',
        agente=agente_actual,
        solicitudes=lista_solicitudes,
        conteos=conteos,
        saldos=saldos_vista,
        categorias=categorias_agente,
        categorias_todas=CATEGORIAS,
        novedades=lista_novedades,
        total_pendientes_global=total_pendientes_global,
        notificaciones_nuevas=notificaciones_nuevas,
        proximos_feriados=proximos_feriados,
    )


@app.route('/nueva-solicitud', methods=['POST'])
def nueva_solicitud():
    if 'id_agente' not in session:
        flash('Debes iniciar sesión para realizar esta acción.', 'warning')
        return redirect(url_for('login'))

    agente_actual = Agente.query.get(session['id_agente'])

    categoria = request.form.get('tipo_licencia')
    fecha_inicio_str = request.form.get('fecha_inicio')
    fecha_fin_str = request.form.get('fecha_fin')
    comentario = request.form.get('comentario_agente')

    if not categoria or not fecha_inicio_str or not fecha_fin_str:
        flash('Faltan datos en el formulario.', 'danger')
        return redirect(url_for('dashboard'))

    if categoria in CATEGORIAS and _categoria_vencida(categoria):
        fecha_limite = _limite_categoria(categoria)
        _registrar_rechazo('Plazo de la categoría vencido', categoria)
        flash(
            f'El plazo para solicitar {CATEGORIAS[categoria]["label"]} venció el '
            f'{fecha_limite.strftime("%d/%m/%Y")}. Consultá con RRHH si corresponde una excepción.',
            'danger'
        )
        return redirect(url_for('dashboard'))

    try:
        fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
        fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Las fechas ingresadas no son válidas.', 'danger')
        return redirect(url_for('dashboard'))

    feriados = cargar_feriados()

    # Regla de antelación: corte a la hora de CUTOFF_HORA del último día hábil previo.
    cutoff = calcular_cutoff(fecha_inicio, feriados)
    if datetime.now() > cutoff:
        _registrar_rechazo('Fuera de plazo', categoria, fecha_inicio, fecha_fin)
        flash(MENSAJE_FUERA_DE_PLAZO, 'fuera-plazo')
        return redirect(url_for('dashboard'))

    # Veda administrativa: los agentes no pueden cargar solicitudes propias
    # en estos rangos (ej. liquidación de sueldos).
    veda = PeriodoVeda.query.filter(
        PeriodoVeda.fecha_inicio <= fecha_fin,
        PeriodoVeda.fecha_fin >= fecha_inicio
    ).first()
    if veda:
        _registrar_rechazo(f'Período de veda ({veda.motivo})', categoria, fecha_inicio, fecha_fin)
        flash(
            f'No se pueden cargar solicitudes entre el {veda.fecha_inicio.strftime("%d/%m/%Y")} y el '
            f'{veda.fecha_fin.strftime("%d/%m/%Y")} ({veda.motivo}). Consultá con RRHH.',
            'danger'
        )
        return redirect(url_for('dashboard'))

    solicitud, error = _crear_solicitud(agente_actual, categoria, fecha_inicio, fecha_fin, comentario)
    if error:
        _registrar_rechazo(f'Solicitud no aceptada ("{error}")', categoria, fecha_inicio, fecha_fin)
        flash(error, 'danger')
        return redirect(url_for('dashboard'))

    db.session.commit()
    flash('Tu solicitud de licencia ha sido enviada correctamente.', 'success')
    return redirect(url_for('dashboard'))


# --- EDITAR SOLICITUD (solo si está pendiente) ---
@app.route('/editar-solicitud-modal', methods=['POST'])
def editar_solicitud_modal():
    if 'id_agente' not in session:
        flash('Debes iniciar sesión para realizar esta acción.', 'warning')
        return redirect(url_for('login'))

    id_solicitud = request.form.get('id_solicitud')
    solicitud = Solicitud.query.get_or_404(id_solicitud)

    if solicitud.id_agente != session['id_agente'] or solicitud.estado != 'Pendiente':
        flash('No podés editar esta solicitud.', 'danger')
        return redirect(url_for('dashboard'))

    agente_actual = solicitud.agente
    categoria_nueva = request.form.get('tipo_licencia')
    fecha_inicio_str = request.form.get('fecha_inicio')
    fecha_fin_str = request.form.get('fecha_fin')
    comentario = request.form.get('comentario_agente', '')

    if categoria_nueva in CATEGORIAS and _categoria_vencida(categoria_nueva):
        fecha_limite = _limite_categoria(categoria_nueva)
        _registrar_rechazo('Edición rechazada: plazo de la categoría vencido', categoria_nueva)
        flash(
            f'El plazo para {CATEGORIAS[categoria_nueva]["label"]} venció el '
            f'{fecha_limite.strftime("%d/%m/%Y")}. Consultá con RRHH si corresponde una excepción.',
            'danger'
        )
        return redirect(url_for('dashboard'))

    try:
        fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
        fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        flash('Las fechas ingresadas no son válidas.', 'danger')
        return redirect(url_for('dashboard'))

    feriados = cargar_feriados()
    cutoff = calcular_cutoff(fecha_inicio, feriados)
    if datetime.now() > cutoff:
        _registrar_rechazo('Edición fuera de plazo', categoria_nueva, fecha_inicio, fecha_fin)
        flash(MENSAJE_FUERA_DE_PLAZO, 'fuera-plazo')
        return redirect(url_for('dashboard'))

    veda = PeriodoVeda.query.filter(
        PeriodoVeda.fecha_inicio <= fecha_fin,
        PeriodoVeda.fecha_fin >= fecha_inicio
    ).first()
    if veda:
        _registrar_rechazo(f'Edición rechazada: período de veda ({veda.motivo})', categoria_nueva,
                           fecha_inicio, fecha_fin)
        flash(
            f'No se pueden cargar solicitudes entre el {veda.fecha_inicio.strftime("%d/%m/%Y")} y el '
            f'{veda.fecha_fin.strftime("%d/%m/%Y")} ({veda.motivo}).',
            'danger'
        )
        return redirect(url_for('dashboard'))

    # Libera la reserva vieja antes de validar la nueva (si la categoría no
    # cambió, saldo_viejo y saldo_nuevo terminan siendo la misma fila).
    saldo_viejo = _obtener_o_crear_saldo(solicitud.id_agente, solicitud.tipo_licencia)
    saldo_viejo.dias_pendientes = max(0, saldo_viejo.dias_pendientes - solicitud.dias_solicitados)

    if categoria_nueva not in CATEGORIAS:
        db.session.rollback()
        flash('Categoría de licencia inválida.', 'danger')
        return redirect(url_for('dashboard'))
    if categoria_nueva == 'EXAMEN_ESTUDIO' and not agente_actual.examen_estudio_habilitado:
        db.session.rollback()
        _registrar_rechazo('Edición rechazada: categoría no habilitada', categoria_nueva, fecha_inicio, fecha_fin)
        flash(f'No tenés habilitada la categoría {CATEGORIAS["EXAMEN_ESTUDIO"]["label"]}.', 'danger')
        return redirect(url_for('dashboard'))

    dias_habiles = contar_dias_habiles(fecha_inicio, fecha_fin, feriados)
    if dias_habiles <= 0:
        db.session.rollback()
        flash('El rango elegido no contiene días hábiles administrativos.', 'danger')
        return redirect(url_for('dashboard'))

    choque = buscar_superposicion(solicitud.id_agente, fecha_inicio, fecha_fin, feriados,
                                  excluir_id=solicitud.id)
    if choque:
        db.session.rollback()
        existente, inicio, fin = choque
        msg = mensaje_superposicion(agente_actual, existente, inicio, fin)
        _registrar_rechazo(f'Edición rechazada ("{msg}")', categoria_nueva, fecha_inicio, fecha_fin)
        flash(msg, 'danger')
        return redirect(url_for('dashboard'))

    saldo_nuevo = _obtener_o_crear_saldo(solicitud.id_agente, categoria_nueva)
    if saldo_nuevo.dias_disponibles < dias_habiles:
        db.session.rollback()
        _registrar_rechazo('Edición rechazada: sin días suficientes', categoria_nueva, fecha_inicio, fecha_fin)
        flash(
            f'No tenés suficientes días disponibles en {CATEGORIAS[categoria_nueva]["label"]}. '
            f'Disponibles: {saldo_nuevo.dias_disponibles}.',
            'danger'
        )
        return redirect(url_for('dashboard'))

    solicitud.tipo_licencia = categoria_nueva
    solicitud.fecha_inicio = fecha_inicio
    solicitud.fecha_fin = fecha_fin
    solicitud.dias_solicitados = dias_habiles
    solicitud.comentario_agente = comentario
    saldo_nuevo.dias_pendientes += dias_habiles

    db.session.commit()
    flash('La solicitud fue actualizada correctamente.', 'success')
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


@app.route('/mi-historial/exportar')
def exportar_mi_historial():
    if 'id_agente' not in session:
        flash('Debes iniciar sesión para realizar esta acción.', 'warning')
        return redirect(url_for('login'))

    agente_actual = Agente.query.get(session['id_agente'])
    solicitudes = Solicitud.query.filter_by(id_agente=session['id_agente']).order_by(Solicitud.fecha_inicio.desc()).all()

    filas = []
    for s in solicitudes:
        filas.append({
            'Categoría': CATEGORIAS.get(s.tipo_licencia, {}).get('label', s.tipo_licencia),
            'Fecha Inicio': s.fecha_inicio.strftime('%d/%m/%Y'),
            'Fecha Fin': s.fecha_fin.strftime('%d/%m/%Y') if s.fecha_fin else '',
            'Días Hábiles': s.dias_solicitados,
            'Estado': s.estado,
            'Carga de Oficio': 'Sí' if s.es_oficio else 'No',
            'Comentario': s.comentario_agente or '',
            'Comentario de RRHH': s.comentario_admin or '',
        })

    df = pd.DataFrame(filas)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Mi Historial')
    buffer.seek(0)

    nombre_archivo = f'mi_historial_{agente_actual.usuario}_{date.today().strftime("%Y%m%d")}.xlsx'
    return send_file(
        buffer,
        as_attachment=True,
        download_name=nombre_archivo,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


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

    saldos_por_agente = {}
    for s in SaldoLicencia.query.all():
        saldos_por_agente.setdefault(s.id_agente, {})[s.categoria] = s

    feriados = Feriado.query.order_by(Feriado.fecha).all()
    periodos_veda = PeriodoVeda.query.order_by(PeriodoVeda.fecha_inicio).all()
    limites = {l.categoria: l.fecha_limite for l in LimiteCategoria.query.all()}

    total_licencias_pendientes = len(solicitudes_pendientes)

    return render_template(
        'admin_panel.html',
        pendientes=solicitudes_pendientes,
        aprobadas=solicitudes_aprobadas,
        rechazadas=solicitudes_rechazadas,
        novedades=lista_novedades,
        agentes=lista_de_agentes,
        admin_id=admin_actual.id,
        total_licencias_pendientes=total_licencias_pendientes,
        categorias=CATEGORIAS,
        saldos_por_agente=saldos_por_agente,
        feriados=feriados,
        periodos_veda=periodos_veda,
        limites=limites,
    )


def _filas_reporte_saldos():
    """Arma, para cada agente, el saldo (disponibles/asignados) de cada
    categoría. A diferencia del dashboard del agente, acá se muestra el
    disponible REAL incluso si la categoría está vencida — el admin necesita
    ver cuántos días le quedaban al agente para poder decidir sobre una
    prórroga; el agente en su propio dashboard sigue viendo 0 (ver
    REGLAS_DE_NEGOCIO.md). Se reutiliza tanto para la vista en pantalla como
    para la exportación a Excel."""
    agentes = Agente.query.order_by(Agente.nombre_completo).all()
    saldos_por_agente = {}
    for s in SaldoLicencia.query.all():
        saldos_por_agente.setdefault(s.id_agente, {})[s.categoria] = s

    vencidas = {codigo: _categoria_vencida(codigo) for codigo in CATEGORIAS}

    filas = []
    for agente in agentes:
        saldos_ag = saldos_por_agente.get(agente.id, {})
        categorias_fila = {}
        for codigo in CATEGORIAS:
            saldo = saldos_ag.get(codigo)
            asignados = saldo.dias_asignados if saldo else 0
            usados = saldo.dias_usados if saldo else 0
            pendientes = saldo.dias_pendientes if saldo else 0
            disponibles = max(0, asignados - (usados + pendientes))
            habilitada = codigo != 'EXAMEN_ESTUDIO' or agente.examen_estudio_habilitado
            categorias_fila[codigo] = {
                'asignados': asignados,
                'disponibles': disponibles,
                'habilitada': habilitada,
                'vencida': vencidas[codigo],
            }
        filas.append({'agente': agente, 'categorias': categorias_fila})

    return filas


@app.route('/admin/reporte')
def reporte_saldos():
    if 'id_agente' not in session or not Agente.query.get(session['id_agente']).es_admin:
        flash('No tienes permiso para acceder a esta página.', 'danger')
        return redirect(url_for('dashboard'))

    return render_template(
        'reporte_saldos.html',
        filas=_filas_reporte_saldos(),
        categorias=CATEGORIAS,
        generado_en=datetime.now(),
    )


@app.route('/admin/reporte/exportar')
def exportar_reporte_saldos():
    if 'id_agente' not in session or not Agente.query.get(session['id_agente']).es_admin:
        flash('No tienes permiso para acceder a esta página.', 'danger')
        return redirect(url_for('dashboard'))

    filas_planas = []
    for fila in _filas_reporte_saldos():
        agente = fila['agente']
        registro = {
            'Agente': agente.nombre_completo,
            'Usuario': agente.usuario,
            'Estado': 'Activo' if agente.esta_activo else 'Inactivo',
            'Última Conexión': agente.ultimo_login.strftime('%d/%m/%Y %H:%M') if agente.ultimo_login else 'Nunca',
        }
        for codigo, meta in CATEGORIAS.items():
            c = fila['categorias'][codigo]
            if c['habilitada']:
                registro[f'{meta["label"]} - Disponibles'] = c['disponibles']
                registro[f'{meta["label"]} - Asignados'] = c['asignados']
                registro[f'{meta["label"]} - Vencida'] = 'Sí' if c['vencida'] else ''
            else:
                registro[f'{meta["label"]} - Disponibles'] = ''
                registro[f'{meta["label"]} - Asignados'] = ''
                registro[f'{meta["label"]} - Vencida'] = ''
        filas_planas.append(registro)

    df = pd.DataFrame(filas_planas)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Reporte de Agentes')
    buffer.seek(0)

    nombre_archivo = f'reporte_agentes_{date.today().strftime("%Y%m%d")}.xlsx'
    return send_file(
        buffer,
        as_attachment=True,
        download_name=nombre_archivo,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


REGISTROS_POR_PAGINA = 50


def _fecha_o_none(texto):
    try:
        return datetime.strptime(texto, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


@app.route('/admin/actividad')
def registro_actividad():
    if 'id_agente' not in session or not Agente.query.get(session['id_agente']).es_admin:
        flash('No tienes permiso para acceder a esta página.', 'danger')
        return redirect(url_for('dashboard'))

    desde = _fecha_o_none(request.args.get('desde'))
    hasta = _fecha_o_none(request.args.get('hasta'))
    persona = request.args.get('persona', type=int)
    tipo = request.args.get('tipo') if request.args.get('tipo') in TIPOS_ACTIVIDAD else None

    consulta = RegistroActividad.query
    if desde:
        consulta = consulta.filter(RegistroActividad.fecha >= datetime.combine(desde, time.min))
    if hasta:
        consulta = consulta.filter(RegistroActividad.fecha <= datetime.combine(hasta, time.max))
    if persona:
        consulta = consulta.filter(RegistroActividad.id_actor == persona)
    if tipo:
        consulta = consulta.filter(RegistroActividad.tipo == tipo)

    total = consulta.count()
    total_paginas = max(1, -(-total // REGISTROS_POR_PAGINA))
    pagina = min(max(1, request.args.get('pagina', 1, type=int)), total_paginas)
    registros = (
        consulta.order_by(RegistroActividad.fecha.desc(), RegistroActividad.id.desc())
        .offset((pagina - 1) * REGISTROS_POR_PAGINA).limit(REGISTROS_POR_PAGINA).all()
    )

    # Personas para el filtro: salen de la propia bitácora, así también aparecen
    # quienes ya fueron eliminados del sistema.
    personas = (
        db.session.query(RegistroActividad.id_actor, db.func.max(RegistroActividad.actor))
        .filter(RegistroActividad.id_actor.isnot(None))
        .group_by(RegistroActividad.id_actor)
        .order_by(db.func.max(RegistroActividad.actor))
        .all()
    )

    return render_template(
        'actividad.html',
        registros=registros, total=total, pagina=pagina, total_paginas=total_paginas,
        personas=personas, tipos=TIPOS_ACTIVIDAD,
        filtros={
            'desde': desde.isoformat() if desde else None,
            'hasta': hasta.isoformat() if hasta else None,
            'persona': persona or None,
            'tipo': tipo,
        },
    )


@app.route('/admin/carga-oficio', methods=['POST'])
def carga_oficio():
    if 'id_agente' not in session or not Agente.query.get(session['id_agente']).es_admin:
        flash('Acción no autorizada.', 'danger')
        return redirect(url_for('login'))

    id_agente = request.form.get('id_agente')
    categoria = request.form.get('categoria')
    fecha_inicio_str = request.form.get('fecha_inicio')
    fecha_fin_str = request.form.get('fecha_fin')
    constancia_aviso = request.form.get('constancia_aviso')
    comentario_admin = request.form.get('comentario_admin')

    if not id_agente or not categoria or not fecha_inicio_str or not fecha_fin_str or not constancia_aviso:
        flash('Todos los campos son obligatorios, incluida la constancia del aviso.', 'danger')
        return redirect(url_for('panel_admin'))

    agente = Agente.query.get_or_404(int(id_agente))

    try:
        fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
        fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Las fechas ingresadas no son válidas.', 'danger')
        return redirect(url_for('panel_admin'))

    # Protección contra doble-submit (doble click, Enter repetido, reintento
    # de red): si ya existe una carga de oficio idéntica para este agente
    # cargada en los últimos 15 segundos, no se crea una segunda.
    duplicado = Solicitud.query.filter_by(
        id_agente=agente.id, tipo_licencia=categoria, fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin, es_oficio=True,
    ).filter(Solicitud.creado_en >= datetime.now() - timedelta(seconds=15)).first()
    if duplicado:
        flash(f'Esa carga de oficio ya se había registrado para {agente.nombre_completo}.', 'warning')
        return redirect(url_for('panel_admin'))

    solicitud, error = _crear_solicitud(
        agente, categoria, fecha_inicio, fecha_fin, comentario=None,
        es_oficio=True, constancia_aviso=constancia_aviso, comentario_admin=comentario_admin
    )
    if error:
        _registrar_rechazo(f'Carga de oficio no aceptada para {agente.nombre_completo} ("{error}")',
                           categoria, fecha_inicio, fecha_fin)
        flash(error, 'danger')
        return redirect(url_for('panel_admin'))

    registrar_actividad(
        'solicitud',
        f'Carga de oficio: {_desc_solicitud(solicitud, agente)} — constancia: {constancia_aviso}'
    )
    db.session.commit()
    flash(f'Carga de oficio registrada para {agente.nombre_completo}.', 'success')
    return redirect(url_for('panel_admin'))


@app.route('/admin/feriados/agregar', methods=['POST'])
def agregar_feriado():
    if 'id_agente' not in session or not Agente.query.get(session['id_agente']).es_admin:
        flash('Acción no autorizada.', 'danger')
        return redirect(url_for('login'))

    fecha_str = request.form.get('fecha')
    descripcion = request.form.get('descripcion')
    tipo = request.form.get('tipo', 'Nacional')

    if not fecha_str or not descripcion:
        flash('Faltan datos del feriado.', 'danger')
        return redirect(url_for('panel_admin'))

    try:
        fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Fecha inválida.', 'danger')
        return redirect(url_for('panel_admin'))

    if Feriado.query.filter_by(fecha=fecha).first():
        flash('Ya existe un feriado cargado para esa fecha.', 'warning')
        return redirect(url_for('panel_admin'))

    db.session.add(Feriado(fecha=fecha, descripcion=descripcion, tipo=tipo))
    registrar_actividad('calendario', f'Agregó el feriado {fecha.strftime("%d/%m/%Y")} ({descripcion}, {tipo})')
    db.session.commit()

    afectadas = recalcular_por_nuevo_feriado(fecha)
    if afectadas:
        flash(
            f'Feriado agregado. Se recalcularon {len(afectadas)} solicitud(es) aprobada(s) que incluían esa fecha.',
            'info'
        )
    else:
        flash('Feriado agregado correctamente.', 'success')

    return redirect(url_for('panel_admin'))


@app.route('/admin/feriados/editar/<int:id_feriado>', methods=['POST'])
def editar_feriado(id_feriado):
    if 'id_agente' not in session or not Agente.query.get(session['id_agente']).es_admin:
        flash('Acción no autorizada.', 'danger')
        return redirect(url_for('login'))

    feriado = Feriado.query.get_or_404(id_feriado)

    fecha_str = request.form.get('fecha')
    descripcion = request.form.get('descripcion')
    tipo = request.form.get('tipo', 'Nacional')

    if not fecha_str or not descripcion:
        flash('Faltan datos del feriado.', 'danger')
        return redirect(url_for('panel_admin'))

    try:
        fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Fecha inválida.', 'danger')
        return redirect(url_for('panel_admin'))

    otro = Feriado.query.filter(Feriado.fecha == fecha, Feriado.id != id_feriado).first()
    if otro:
        flash('Ya existe otro feriado cargado para esa fecha.', 'warning')
        return redirect(url_for('panel_admin'))

    fecha_cambio = fecha != feriado.fecha
    anterior = f'{feriado.fecha.strftime("%d/%m/%Y")} ({feriado.descripcion})'
    feriado.fecha = fecha
    feriado.descripcion = descripcion
    feriado.tipo = tipo
    registrar_actividad(
        'calendario',
        f'Editó el feriado {anterior}: ahora {fecha.strftime("%d/%m/%Y")} ({descripcion}, {tipo})'
    )
    db.session.commit()

    # Si se movió la fecha, la nueva fecha se trata igual que un feriado
    # recién agregado: puede caer dentro de una licencia aprobada y
    # recalcularla. La fecha vieja no se recalcula al revés (tampoco lo
    # hace eliminar_feriado): si una licencia se achicó por el feriado
    # anterior, mover o borrar el feriado no le devuelve el día
    # automáticamente — eso requiere revisión manual del admin.
    if fecha_cambio:
        afectadas = recalcular_por_nuevo_feriado(fecha)
        if afectadas:
            flash(
                f'Feriado actualizado. Se recalcularon {len(afectadas)} solicitud(es) aprobada(s) '
                f'que incluían la nueva fecha.',
                'info'
            )
        else:
            flash('Feriado actualizado correctamente.', 'success')
    else:
        flash('Feriado actualizado correctamente.', 'success')

    return redirect(url_for('panel_admin'))


@app.route('/admin/feriados/importar', methods=['POST'])
def importar_feriados():
    if 'id_agente' not in session or not Agente.query.get(session['id_agente']).es_admin:
        flash('Acción no autorizada.', 'danger')
        return redirect(url_for('login'))

    archivo = request.files.get('archivo')
    if not archivo or archivo.filename == '':
        flash('Tenés que elegir un archivo.', 'danger')
        return redirect(url_for('panel_admin'))

    try:
        if archivo.filename.lower().endswith('.csv'):
            df = pd.read_csv(archivo)
        else:
            df = pd.read_excel(archivo)
    except Exception as e:
        flash(f'No se pudo leer el archivo: {e}', 'danger')
        return redirect(url_for('panel_admin'))

    importados = 0
    omitidos = 0
    fechas_nuevas = []

    for _, row in df.iterrows():
        fecha_raw = row.get('fecha')
        descripcion = row.get('descripcion')
        tipo = row.get('tipo') if pd.notna(row.get('tipo')) else 'Nacional'

        if pd.isna(fecha_raw) or pd.isna(descripcion):
            omitidos += 1
            continue

        fecha_parseada = pd.to_datetime(fecha_raw, dayfirst=True, errors='coerce')
        if pd.isna(fecha_parseada):
            omitidos += 1
            continue
        fecha = fecha_parseada.date()

        if Feriado.query.filter_by(fecha=fecha).first():
            omitidos += 1
            continue

        db.session.add(Feriado(fecha=fecha, descripcion=str(descripcion), tipo=str(tipo)))
        fechas_nuevas.append(fecha)
        importados += 1

    registrar_actividad(
        'calendario', f'Importó feriados desde archivo ({importados} nuevos, {omitidos} omitidos)'
    )
    db.session.commit()

    total_recalculadas = 0
    for fecha in fechas_nuevas:
        total_recalculadas += len(recalcular_por_nuevo_feriado(fecha))

    flash(
        f'Importación completa: {importados} feriados nuevos, {omitidos} omitidos '
        f'(ya existían o datos inválidos). {total_recalculadas} solicitud(es) recalculada(s).',
        'success'
    )
    return redirect(url_for('panel_admin'))


@app.route('/admin/feriados/eliminar/<int:id_feriado>', methods=['POST'])
def eliminar_feriado(id_feriado):
    if 'id_agente' not in session or not Agente.query.get(session['id_agente']).es_admin:
        flash('Acción no autorizada.', 'danger')
        return redirect(url_for('login'))

    feriado = Feriado.query.get_or_404(id_feriado)
    registrar_actividad(
        'calendario', f'Eliminó el feriado {feriado.fecha.strftime("%d/%m/%Y")} ({feriado.descripcion})'
    )
    db.session.delete(feriado)
    db.session.commit()
    flash('Feriado eliminado.', 'success')
    return redirect(url_for('panel_admin'))


@app.route('/admin/veda/agregar', methods=['POST'])
def agregar_veda():
    if 'id_agente' not in session or not Agente.query.get(session['id_agente']).es_admin:
        flash('Acción no autorizada.', 'danger')
        return redirect(url_for('login'))

    fecha_inicio_str = request.form.get('fecha_inicio')
    fecha_fin_str = request.form.get('fecha_fin')
    motivo = request.form.get('motivo')

    if not fecha_inicio_str or not fecha_fin_str or not motivo:
        flash('Faltan datos del período de veda.', 'danger')
        return redirect(url_for('panel_admin'))

    try:
        fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
        fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Fechas inválidas.', 'danger')
        return redirect(url_for('panel_admin'))

    if fecha_fin < fecha_inicio:
        flash('La fecha de fin no puede ser anterior a la de inicio.', 'danger')
        return redirect(url_for('panel_admin'))

    db.session.add(PeriodoVeda(fecha_inicio=fecha_inicio, fecha_fin=fecha_fin, motivo=motivo))
    registrar_actividad(
        'calendario',
        f'Agregó un período de veda del {fecha_inicio.strftime("%d/%m/%Y")} al '
        f'{fecha_fin.strftime("%d/%m/%Y")} ({motivo})'
    )
    db.session.commit()
    flash('Período de veda agregado.', 'success')
    return redirect(url_for('panel_admin'))


@app.route('/admin/veda/eliminar/<int:id_veda>', methods=['POST'])
def eliminar_veda(id_veda):
    if 'id_agente' not in session or not Agente.query.get(session['id_agente']).es_admin:
        flash('Acción no autorizada.', 'danger')
        return redirect(url_for('login'))

    veda = PeriodoVeda.query.get_or_404(id_veda)
    registrar_actividad(
        'calendario',
        f'Eliminó el período de veda del {veda.fecha_inicio.strftime("%d/%m/%Y")} al '
        f'{veda.fecha_fin.strftime("%d/%m/%Y")} ({veda.motivo})'
    )
    db.session.delete(veda)
    db.session.commit()
    flash('Período de veda eliminado.', 'success')
    return redirect(url_for('panel_admin'))


@app.route('/admin/limites/guardar', methods=['POST'])
def guardar_limites():
    if 'id_agente' not in session or not Agente.query.get(session['id_agente']).es_admin:
        flash('Acción no autorizada.', 'danger')
        return redirect(url_for('login'))

    cambios = 0
    for codigo in CATEGORIAS:
        valor = request.form.get(f'limite_{codigo}', '').strip()
        limite_actual = LimiteCategoria.query.filter_by(categoria=codigo).first()

        if not valor:
            if limite_actual:
                db.session.delete(limite_actual)
                cambios += 1
            continue

        try:
            fecha = datetime.strptime(valor, '%Y-%m-%d').date()
        except ValueError:
            flash(f'Fecha inválida para {CATEGORIAS[codigo]["label"]}.', 'danger')
            continue

        if limite_actual:
            if limite_actual.fecha_limite != fecha:
                limite_actual.fecha_limite = fecha
                cambios += 1
        else:
            db.session.add(LimiteCategoria(categoria=codigo, fecha_limite=fecha))
            cambios += 1

    if cambios:
        registrar_actividad('plazos', f'Actualizó los plazos de vigencia ({cambios} cambio(s))')
    db.session.commit()
    if cambios:
        flash('Plazos de vigencia actualizados.', 'success')
    else:
        flash('No hubo cambios en los plazos.', 'info')
    return redirect(url_for('panel_admin'))


@app.route('/admin/cerrar-ejercicio', methods=['POST'])
def cerrar_ejercicio():
    if 'id_agente' not in session or not Agente.query.get(session['id_agente']).es_admin:
        flash('Acción no autorizada.', 'danger')
        return redirect(url_for('login'))

    pendientes_abiertas = Solicitud.query.filter_by(estado='Pendiente').count()
    if pendientes_abiertas > 0:
        registrar_actividad(
            'rechazo',
            f'Cierre de ejercicio bloqueado: hay {pendientes_abiertas} solicitud(es) pendiente(s)',
            commit=True
        )
        flash(
            f'No se puede cerrar el ejercicio: hay {pendientes_abiertas} solicitud(es) pendiente(s) sin '
            f'resolver. Aprobalas o rechazalas antes de continuar.',
            'danger'
        )
        return redirect(url_for('panel_admin'))

    SaldoLicencia.query.update({SaldoLicencia.dias_usados: 0, SaldoLicencia.dias_pendientes: 0})
    registrar_actividad(
        'plazos', 'Cerró el ejercicio: reinició los días usados y pendientes de todos los agentes'
    )
    db.session.commit()
    flash(
        'Ejercicio cerrado: los saldos no gozados de las 4 categorías vencieron y se reiniciaron. '
        'Los cupos asignados de cada agente no se modificaron.',
        'success'
    )
    return redirect(url_for('panel_admin'))


@app.route('/admin/crear-agente', methods=['POST'])
def crear_agente():
    if 'id_agente' not in session or not Agente.query.get(session['id_agente']).es_admin:
        flash('Acción no autorizada.', 'danger')
        return redirect(url_for('login'))

    nombre = request.form.get('nombre_completo')
    usuario = request.form.get('usuario')
    es_admin = request.form.get('es_admin') == 'on'
    examen_estudio_habilitado = request.form.get('examen_estudio_habilitado') == 'on'

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
            examen_estudio_habilitado=examen_estudio_habilitado,
        )
        db.session.add(nuevo_agente)
        db.session.flush()  # necesitamos nuevo_agente.id para los saldos

        for codigo, meta in CATEGORIAS.items():
            cupo = int(request.form.get(f'cupo_{codigo}', meta['cupo_default']))
            db.session.add(SaldoLicencia(id_agente=nuevo_agente.id, categoria=codigo, dias_asignados=cupo))

        registrar_actividad(
            'agente', f'Creó el agente {nombre} (usuario {usuario}{", administrador" if es_admin else ""})'
        )
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
        registrar_actividad('agente', f'Eliminó al agente {nombre_eliminado} y todas sus solicitudes')
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
        registrar_actividad(
            'agente',
            f'{"Activó" if agente_a_modificar.esta_activo else "Desactivó"} la cuenta de '
            f'{agente_a_modificar.nombre_completo}'
        )
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
    examen_estudio_form = request.form.get('examen_estudio_habilitado') == 'on'

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
        nombre_anterior = agente_a_editar.nombre_completo
        nombre_nuevo = request.form.get('nombre_completo')
        cambios = []
        if nombre_nuevo != agente_a_editar.nombre_completo:
            cambios.append('nombre')
        if nuevo_usuario != agente_a_editar.usuario:
            cambios.append('usuario')
        if es_admin_form != bool(agente_a_editar.es_admin):
            cambios.append('rol de administrador')
        if examen_estudio_form != bool(agente_a_editar.examen_estudio_habilitado):
            cambios.append(f'habilitación de {CATEGORIAS["EXAMEN_ESTUDIO"]["label"]}')

        agente_a_editar.nombre_completo = nombre_nuevo
        agente_a_editar.usuario = nuevo_usuario
        agente_a_editar.es_admin = es_admin_form
        agente_a_editar.examen_estudio_habilitado = examen_estudio_form

        for codigo in CATEGORIAS:
            cupo_str = request.form.get(f'cupo_{codigo}')
            if cupo_str is None or cupo_str == '':
                continue
            saldo = _obtener_o_crear_saldo(agente_a_editar.id, codigo)
            if int(cupo_str) != saldo.dias_asignados:
                cambios.append(f'cupo {CATEGORIAS[codigo]["label"]}')
            saldo.dias_asignados = int(cupo_str)

        nueva_clave = request.form.get('nueva_clave')
        if nueva_clave:
            agente_a_editar.clave_hash = bcrypt.generate_password_hash(nueva_clave).decode('utf-8')
            cambios.append('contraseña')

        registrar_actividad(
            'agente',
            f'Editó los datos de {nombre_anterior} ' +
            (f'(cambió: {", ".join(cambios)})' if cambios else '(sin cambios)')
        )
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
    if solicitud.estado != 'Pendiente':
        flash('Esta solicitud ya fue gestionada.', 'warning')
        return redirect(url_for('panel_admin'))

    agente = solicitud.agente
    solicitud.comentario_admin = request.form.get('comentario_admin')

    categoria_original = _normalizar_categoria(solicitud.tipo_licencia) or solicitud.tipo_licencia
    solicitud.tipo_licencia = categoria_original

    # <-- NUEVO: el admin puede reclasificar la categoría de la licencia a
    # discreción justo antes de aprobarla (ej. pidieron LAO pero corresponde
    # Invierno). Si no viene un valor válido en el form, se mantiene la
    # categoría original tal cual venía.
    categoria_elegida = request.form.get('categoria')
    categoria_final = categoria_elegida if categoria_elegida in CATEGORIAS else categoria_original

    saldo_original = _obtener_o_crear_saldo(agente.id, categoria_original)

    if categoria_final != categoria_original:
        saldo_nuevo = _obtener_o_crear_saldo(agente.id, categoria_final)
        if saldo_nuevo.dias_disponibles < solicitud.dias_solicitados:
            flash(
                f'No se pudo reclasificar a {CATEGORIAS[categoria_final]["label"]}: '
                f'{agente.nombre_completo} no tiene suficientes días disponibles en esa categoría '
                f'(disponibles: {saldo_nuevo.dias_disponibles}, se necesitan: {solicitud.dias_solicitados}).',
                'danger'
            )
            return redirect(url_for('panel_admin'))
        saldo_original.dias_pendientes = max(0, saldo_original.dias_pendientes - solicitud.dias_solicitados)
        saldo_nuevo.dias_usados += solicitud.dias_solicitados
        solicitud.tipo_licencia = categoria_final
    else:
        saldo_original.dias_pendientes = max(0, saldo_original.dias_pendientes - solicitud.dias_solicitados)
        saldo_original.dias_usados += solicitud.dias_solicitados

    solicitud.estado = 'Aprobada'
    solicitud.notificado = False

    detalle = f'Aprobó la solicitud de {_desc_solicitud(solicitud, agente)}'
    if categoria_final != categoria_original:
        detalle += (f' (reclasificada de {CATEGORIAS[categoria_original]["label"]} '
                    f'a {CATEGORIAS[categoria_final]["label"]})')
    registrar_actividad('solicitud', detalle)

    db.session.commit()
    if categoria_final != categoria_original:
        flash(
            f"Solicitud de {agente.nombre_completo} APROBADA, reclasificada de "
            f"{CATEGORIAS[categoria_original]['label']} a {CATEGORIAS[categoria_final]['label']}.",
            'success'
        )
    else:
        flash(f"Solicitud de {agente.nombre_completo} APROBADA.", 'success')
    return redirect(url_for('panel_admin'))

@app.route('/rechazar_solicitud/<int:id_solicitud>', methods=['POST'])
def rechazar_solicitud(id_solicitud):
    if 'id_agente' not in session or not Agente.query.get(session['id_agente']).es_admin:
        flash('Acción no autorizada.', 'danger')
        return redirect(url_for('login'))

    solicitud = Solicitud.query.get_or_404(id_solicitud)
    if solicitud.estado != 'Pendiente':
        flash('Esta solicitud ya fue gestionada.', 'warning')
        return redirect(url_for('panel_admin'))

    categoria = _normalizar_categoria(solicitud.tipo_licencia) or solicitud.tipo_licencia
    solicitud.tipo_licencia = categoria
    saldo = _obtener_o_crear_saldo(solicitud.id_agente, categoria)
    saldo.dias_pendientes = max(0, saldo.dias_pendientes - solicitud.dias_solicitados)

    solicitud.estado = 'Rechazada'
    solicitud.notificado = False
    solicitud.comentario_admin = request.form.get('comentario_admin')

    detalle = f'Rechazó la solicitud de {_desc_solicitud(solicitud)}'
    if solicitud.comentario_admin:
        detalle += f' — motivo: {solicitud.comentario_admin}'
    registrar_actividad('solicitud', detalle)

    db.session.commit()
    flash(f"La solicitud de {solicitud.agente.nombre_completo} ha sido RECHAZADA.", 'warning')
    return redirect(url_for('panel_admin'))

@app.route('/admin/rectificar-solicitud/<int:id_solicitud>', methods=['POST'])
def rectificar_solicitud(id_solicitud):
    if 'id_agente' not in session or not Agente.query.get(session['id_agente']).es_admin:
        flash('Acción no autorizada.', 'danger')
        return redirect(url_for('login'))

    solicitud = Solicitud.query.get_or_404(id_solicitud)
    estado_anterior = solicitud.estado

    if estado_anterior == 'Rechazada':
        choque = buscar_superposicion(
            solicitud.id_agente, solicitud.fecha_inicio, solicitud.fecha_fin or solicitud.fecha_inicio,
            cargar_feriados(), excluir_id=solicitud.id,
        )
        if choque:
            existente, inicio, fin = choque
            msg = 'No se puede volver a Pendientes: ' + mensaje_superposicion(
                solicitud.agente, existente, inicio, fin, es_oficio=True)
            registrar_actividad('rechazo', f'{msg} — {_desc_solicitud(solicitud)}', commit=True)
            flash(msg, 'warning')
            return redirect(url_for('panel_admin'))

    # <-- CORREGIDO: las solicitudes históricas (migradas del sistema
    # anterior) tienen tipo_licencia en texto libre ("Vacaciones Enero", etc.)
    # en vez de un código de CATEGORIAS. Sin normalizar, el saldo se
    # acreditaba/debitaba contra una categoría fantasma que el dashboard
    # nunca muestra, y encima con dias_usados/dias_pendientes en None
    # (recién inicializados al persistir), lo que tiraba un 500. Se
    # normaliza y se deja guardado el código correcto de una vez.
    categoria = _normalizar_categoria(solicitud.tipo_licencia)
    if categoria is None:
        flash(
            f'No se pudo identificar la categoría de licencia "{solicitud.tipo_licencia}" para '
            f'devolver los días automáticamente. Revisá el saldo del agente a mano.',
            'danger'
        )
        return redirect(url_for('panel_admin'))
    solicitud.tipo_licencia = categoria

    saldo = _obtener_o_crear_saldo(solicitud.id_agente, categoria)

    if estado_anterior == 'Aprobada':
        saldo.dias_usados = max(0, saldo.dias_usados - solicitud.dias_solicitados)
    # Si venía de Rechazada no hay nada que devolver: ya se había liberado
    # de dias_pendientes al rechazarla. En ambos casos se vuelve a reservar.
    saldo.dias_pendientes += solicitud.dias_solicitados

    solicitud.estado = 'Pendiente'
    solicitud.notificado = True
    solicitud.comentario_admin = None

    registrar_actividad(
        'solicitud',
        f'Devolvió a Pendientes la solicitud de {_desc_solicitud(solicitud)} (estaba {estado_anterior})'
    )

    db.session.commit()

    flash(f'La solicitud de {solicitud.agente.nombre_completo} ha sido movida a Pendientes.', 'info')
    return redirect(url_for('panel_admin'))

@app.route('/eliminar_solicitud/<int:id_solicitud>', methods=['POST'])
def eliminar_solicitud(id_solicitud):
    if 'id_agente' not in session:
        flash('Debes iniciar sesión para realizar esta acción.', 'warning')
        return redirect(url_for('login'))

    solicitud = Solicitud.query.get_or_404(id_solicitud)

    if solicitud.id_agente != session['id_agente']:
        flash('No tienes permiso para eliminar esta solicitud.', 'danger')
        return redirect(url_for('dashboard'))
    if solicitud.estado != 'Pendiente':
        flash('Solo pueden eliminarse solicitudes pendientes.', 'warning')
        return redirect(url_for('dashboard'))

    try:
        saldo = _obtener_o_crear_saldo(solicitud.id_agente, solicitud.tipo_licencia)
        saldo.dias_pendientes = max(0, saldo.dias_pendientes - solicitud.dias_solicitados)
        db.session.delete(solicitud)
        db.session.commit()
        flash('La solicitud ha sido eliminada correctamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar la solicitud: {e}', 'danger')

    return redirect(url_for('dashboard'))


@app.route('/admin/eliminar-solicitud/<int:id_solicitud>', methods=['POST'])
def admin_eliminar_solicitud(id_solicitud):
    if 'id_agente' not in session or not Agente.query.get(session['id_agente']).es_admin:
        flash('Acción no autorizada.', 'danger')
        return redirect(url_for('login'))

    solicitud = Solicitud.query.get_or_404(id_solicitud)
    if solicitud.estado != 'Pendiente':
        flash('Solo pueden eliminarse solicitudes pendientes. Si ya fue gestionada, devolvela a Pendientes primero.', 'warning')
        return redirect(url_for('panel_admin'))

    nombre = solicitud.agente.nombre_completo
    categoria = _normalizar_categoria(solicitud.tipo_licencia) or solicitud.tipo_licencia
    saldo = _obtener_o_crear_saldo(solicitud.id_agente, categoria)
    saldo.dias_pendientes = max(0, saldo.dias_pendientes - solicitud.dias_solicitados)
    registrar_actividad('solicitud', f'Eliminó la solicitud pendiente de {_desc_solicitud(solicitud)}')
    db.session.delete(solicitud)
    db.session.commit()

    flash(f'La solicitud de {nombre} fue eliminada y se liberaron sus días reservados.', 'success')
    return redirect(url_for('panel_admin'))


@app.route('/admin/nueva_novedad', methods=['POST'])
def publicar_novedad():
    if 'id_agente' not in session or not Agente.query.get(session['id_agente']).es_admin:
        flash('Acción no autorizada.', 'danger')
        return redirect(url_for('login'))
    titulo = request.form['titulo']
    mensaje = _sanitizar_mensaje(request.form['mensaje'])
    nueva_novedad = Novedad(titulo=titulo, mensaje=mensaje)
    db.session.add(nueva_novedad)
    registrar_actividad('novedad', f'Publicó la novedad "{titulo}"')
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
    novedad_a_editar.mensaje = _sanitizar_mensaje(request.form.get('mensaje'))
    registrar_actividad('novedad', f'Editó la novedad "{novedad_a_editar.titulo}"')
    db.session.commit()

    flash('La novedad ha sido actualizada exitosamente.', 'success')
    return redirect(url_for('panel_admin'))

@app.route('/admin/eliminar_novedad/<int:id_novedad>', methods=['POST'])
def eliminar_novedad(id_novedad):
    if 'id_agente' not in session or not Agente.query.get(session['id_agente']).es_admin:
        flash('Acción no autorizada.', 'danger')
        return redirect(url_for('login'))

    novedad_a_eliminar = Novedad.query.get_or_404(id_novedad)
    registrar_actividad('novedad', f'Eliminó la novedad "{novedad_a_eliminar.titulo}"')
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
    """Importa agentes y sus cupos de licencia desde un archivo .xlsx.

    Columnas esperadas: usuario, nombre_completo, es_admin (Si/No),
    examen_estudio (Si/No, opcional), y opcionalmente cupo_lao, cupo_invierno,
    cupo_compensatorio, cupo_examen_estudio (si faltan, se usa el cupo por
    defecto de cada categoría).
    """
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
        examen_val = str(row.get('examen_estudio', 'No')).lower()
        examen_habilitado = examen_val in ['si', 's', 'true', '1']

        clave_hash = bcrypt.generate_password_hash(usuario).decode('utf-8')

        nuevo_agente = Agente(
            usuario=usuario,
            nombre_completo=row['nombre_completo'],
            clave_hash=clave_hash,
            es_admin=es_admin,
            examen_estudio_habilitado=examen_habilitado,
        )
        db.session.add(nuevo_agente)
        db.session.flush()

        cupos_log = []
        for codigo, meta in CATEGORIAS.items():
            valor = row.get(f'cupo_{codigo.lower()}')
            try:
                cupo = int(valor) if valor != '' else meta['cupo_default']
            except (ValueError, TypeError):
                cupo = meta['cupo_default']
            db.session.add(SaldoLicencia(id_agente=nuevo_agente.id, categoria=codigo, dias_asignados=cupo))
            cupos_log.append(f'{codigo}={cupo}')

        agentes_importados += 1
        print(f"Importando: {nuevo_agente.nombre_completo} con cupos ({', '.join(cupos_log)})...")

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
    crea los registros y descuenta el saldo (dias_usados) correspondiente.
    """
    try:
        df = pd.read_excel(filepath)

        # Convierte fechas mixtas (Excel datetime y texto dd/mm/yyyy)
        df['fecha_inicio'] = pd.to_datetime(
            df['fecha_inicio'],
            format='%d/%m/%Y',
            errors='coerce'
        ).fillna(
            pd.to_datetime(df['fecha_inicio'], errors='coerce')
        )

        print(f"Archivo de historial '{filepath}' leído. {len(df)} registros encontrados.")

    except Exception as e:
        print(f"Error al leer el archivo de Excel: {e}")
        return

    registros_importados = 0
    agentes_actualizados = set()
    feriados = cargar_feriados()

    for index, row in df.iterrows():

        usuario = str(row.get('usuario', '')).strip()
        tipo_licencia = row.get('tipo_licencia')
        dias = row.get('dias_solicitados')
        fecha_inicio_obj = row.get('fecha_inicio')

        if not usuario:
            print(f"Omitiendo fila {index + 2}: usuario vacío.")
            continue

        if pd.isna(fecha_inicio_obj):
            print(f"Omitiendo fila {index + 2}: fecha inválida.")
            continue

        if pd.isna(tipo_licencia):
            print(f"Omitiendo fila {index + 2}: tipo de licencia vacío.")
            continue

        if pd.isna(dias):
            print(f"Omitiendo fila {index + 2}: días solicitados vacíos.")
            continue

        agente = Agente.query.filter_by(usuario=usuario).first()

        if not agente:
            print(f"Omitiendo registro para el usuario '{usuario}': No se encontró en la base de datos.")
            continue

        try:
            dias_int = int(dias)
            fecha_inicio = fecha_inicio_obj.date()
            fecha_fin = fecha_fin_para_n_dias_habiles(fecha_inicio, dias_int, feriados)

            solicitud_historica = Solicitud(
                id_agente=agente.id,
                tipo_licencia=str(tipo_licencia),
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                dias_solicitados=dias_int,
                estado='Aprobada',
                comentario_admin='Carga histórica de sistema anterior.',
                creado_en=datetime.combine(fecha_inicio, time(0, 0)),
            )

            db.session.add(solicitud_historica)

            tipo_lower = str(tipo_licencia).lower()
            if tipo_lower in (c.lower() for c in CATEGORIAS):
                categoria = str(tipo_licencia).upper()
            elif 'enero' in tipo_lower:
                categoria = 'LAO'
            elif 'julio' in tipo_lower or 'invierno' in tipo_lower:
                categoria = 'INVIERNO'
            elif 'compensatorio' in tipo_lower:
                categoria = 'COMPENSATORIO'
            elif 'examen' in tipo_lower or 'estudio' in tipo_lower:
                categoria = 'EXAMEN_ESTUDIO'
            else:
                categoria = None

            if categoria:
                saldo = _obtener_o_crear_saldo(agente.id, categoria)
                saldo.dias_usados += dias_int

            registros_importados += 1
            agentes_actualizados.add(agente.nombre_completo)

        except Exception as e:
            print(f"Error procesando registro para '{usuario}': {e}")
            continue

    try:
        db.session.commit()

        print("\n¡Importación de historial completada!")
        print(f"Total de registros de licencias importados: {registros_importados}")
        print(f"Total de agentes con saldos actualizados: {len(agentes_actualizados)}")

    except Exception as e:
        db.session.rollback()
        print(f"Error al guardar los cambios: {e}")


@app.route('/api/superposiciones')
def api_superposiciones():
    """Nombres de agentes con licencia aprobada solapada con el rango dado
    (sin exponer categoría), para la alerta no bloqueante del formulario."""
    if 'id_agente' not in session:
        return jsonify({'error': 'No autorizado'}), 401

    fecha_inicio_str = request.args.get('fecha_inicio')
    fecha_fin_str = request.args.get('fecha_fin')
    if not fecha_inicio_str or not fecha_fin_str:
        return jsonify({'agentes': []})

    try:
        fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
        fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'agentes': []})

    solicitudes = Solicitud.query.filter(
        Solicitud.estado == 'Aprobada',
        Solicitud.fecha_inicio <= fecha_fin,
        Solicitud.fecha_fin >= fecha_inicio,
        Solicitud.id_agente != session['id_agente']
    ).all()

    nombres = sorted({s.agente.nombre_completo for s in solicitudes})
    return jsonify({'agentes': nombres})


@app.route('/api/calendario/<int:year>/<int:month>')
def obtener_licencias_calendario(year, month):
    """Retorna las licencias aprobadas y los feriados de un mes. No incluye
    la categoría de la licencia: el calendario colectivo es solo
    "Apellido y Nombre - Ausente/Licencia", sin exponer motivo ni tipo."""
    if 'id_agente' not in session:
        return jsonify({'error': 'No autorizado'}), 401

    primer_dia = date(year, month, 1)
    ultimo_dia = date(year, month, monthrange(year, month)[1])

    licencias_aprobadas = Solicitud.query.filter(
        Solicitud.estado == 'Aprobada',
        Solicitud.fecha_inicio <= ultimo_dia,
        Solicitud.fecha_fin >= primer_dia,
    ).all()

    eventos = []
    for licencia in licencias_aprobadas:
        inicio_visible = max(licencia.fecha_inicio, primer_dia)
        fin_visible = min(licencia.fecha_fin, ultimo_dia)
        eventos.append({
            'id': licencia.id,
            'agente': licencia.agente.nombre_completo,
            'fecha_inicio': inicio_visible.strftime('%Y-%m-%d'),
            'fecha_fin': fin_visible.strftime('%Y-%m-%d'),
            'dias_totales': licencia.dias_solicitados,
        })

    feriados_mes = Feriado.query.filter(
        Feriado.fecha >= primer_dia, Feriado.fecha <= ultimo_dia
    ).all()
    feriados_json = [
        {'fecha': f.fecha.strftime('%Y-%m-%d'), 'descripcion': f.descripcion}
        for f in feriados_mes
    ]

    return jsonify({'eventos': eventos, 'feriados': feriados_json})

# --- INICIAR LA APLICACIÓN ---
if __name__ == '__main__':
    # Backup automático al arrancar (una vez por día); ver backup_db.py.
    import backup_db
    if not backup_db.hay_backup_de_hoy():
        try:
            print(f'[backup] {backup_db.hacer_backup()}')
        except Exception as e:
            print(f'[backup] ERROR: {e}')

    # waitress es un servidor apto para producción (gunicorn no corre en Windows).
    from waitress import serve
    serve(app, host='0.0.0.0', port=5001, threads=8)
