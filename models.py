"""Modelos de la base de datos y las constantes de categorías de licencia.

Extraído de app.py para poder importar los modelos (en tests, en scripts de
mantenimiento) sin necesidad de levantar toda la aplicación Flask.
"""
from datetime import datetime

from extensions import db

# --- CATEGORÍAS DE LICENCIA ---
# El sistema gestiona exclusivamente licencias por días completos, agrupadas
# en estas 4 categorías fijas. "Permisos" (franquicias horarias) ya no existe.
CATEGORIAS = {
    'LAO':            {'label': 'Licencia Anual Ordinaria (LAO)', 'cupo_default': 22},
    'INVIERNO':       {'label': 'Licencia de Invierno (Feria)',   'cupo_default': 10},
    'COMPENSATORIO':  {'label': 'Compensatorios',                 'cupo_default': 0},
    'EXAMEN_ESTUDIO': {'label': 'Examen / Estudio',               'cupo_default': 20},
}


class Agente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario = db.Column(db.String(80), unique=True, nullable=False)
    clave_hash = db.Column(db.String(120), nullable=False)
    nombre_completo = db.Column(db.String(200), nullable=False)
    es_admin = db.Column(db.Boolean, default=False, nullable=False)
    esta_activo = db.Column(db.Boolean, default=True, nullable=False)
    # Examen/Estudio es la única categoría que no está disponible para todos:
    # el admin tiene que habilitarla agente por agente.
    examen_estudio_habilitado = db.Column(db.Boolean, default=False, nullable=False)
    ultimo_login = db.Column(db.DateTime, nullable=True)
    solicitudes = db.relationship('Solicitud', backref='agente', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f'<Agente {self.usuario}>'


class SaldoLicencia(db.Model):
    """Saldo de una categoría de licencia para un agente.

    Reemplaza a las columnas fijas dias_enero/dias_julio/dias_compensatorios_*
    que tenía Agente: una fila por agente+categoría, con la mecánica
    disponibles = asignados - (usados + pendientes).
    """
    id_agente = db.Column(db.Integer, db.ForeignKey('agente.id', ondelete='CASCADE'), primary_key=True)
    categoria = db.Column(db.String(20), primary_key=True)
    dias_asignados = db.Column(db.Integer, nullable=False, default=0)
    dias_usados = db.Column(db.Integer, nullable=False, default=0)
    dias_pendientes = db.Column(db.Integer, nullable=False, default=0)

    agente = db.relationship('Agente', backref=db.backref('saldos', cascade='all, delete-orphan'))

    @property
    def dias_disponibles(self):
        return max(0, self.dias_asignados - (self.dias_usados + self.dias_pendientes))

    def __repr__(self):
        return f'<SaldoLicencia agente={self.id_agente} {self.categoria}>'


class Feriado(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.Date, unique=True, nullable=False)
    descripcion = db.Column(db.String(150), nullable=False)
    tipo = db.Column(db.String(20), default='Nacional')  # Nacional / Provincial / Municipal / Asueto

    def __repr__(self):
        return f'<Feriado {self.fecha} {self.descripcion}>'


class PeriodoVeda(db.Model):
    """Rango de fechas donde los agentes no pueden cargar solicitudes propias
    (ej. liquidación de sueldos). Solo el admin puede registrar de oficio."""
    id = db.Column(db.Integer, primary_key=True)
    fecha_inicio = db.Column(db.Date, nullable=False)
    fecha_fin = db.Column(db.Date, nullable=False)
    motivo = db.Column(db.String(200), nullable=False)

    def __repr__(self):
        return f'<PeriodoVeda {self.fecha_inicio} - {self.fecha_fin}>'


class LimiteCategoria(db.Model):
    """Fecha límite de vigencia opcional para una categoría (ej. Invierno
    vence el 30/09). Pasada esa fecha: el agente ya no puede cargar ni editar
    solicitudes de esa categoría, y sus días disponibles se muestran en 0 —
    sin tocar asignados/usados, así que una prórroga (mover la fecha) hace
    que todo vuelva a la normalidad solo. Ausencia de fila = sin límite. El
    admin sigue pudiendo cargar de oficio en esa categoría después del
    vencimiento."""
    categoria = db.Column(db.String(20), primary_key=True)
    fecha_limite = db.Column(db.Date, nullable=False)

    def __repr__(self):
        return f'<LimiteCategoria {self.categoria} hasta {self.fecha_limite}>'


class Solicitud(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tipo_licencia = db.Column(db.String(50), nullable=False)  # código de CATEGORIAS
    fecha_inicio = db.Column(db.Date, nullable=False)
    fecha_fin = db.Column(db.Date, nullable=True)
    dias_solicitados = db.Column(db.Integer, nullable=False)  # días hábiles del rango
    estado = db.Column(db.String(20), nullable=False, default='Pendiente')
    comentario_agente = db.Column(db.Text, nullable=True)
    comentario_admin = db.Column(db.Text, nullable=True)
    id_agente = db.Column(db.Integer, db.ForeignKey('agente.id', ondelete='CASCADE'), nullable=False)
    # Carga de oficio: válvula de escape del admin para cargar fuera de término
    es_oficio = db.Column(db.Boolean, default=False, nullable=False)
    constancia_aviso = db.Column(db.Text, nullable=True)
    creado_en = db.Column(db.DateTime, nullable=True)
    # False apenas el admin aprueba/rechaza (o carga de oficio): le muestra al
    # agente un aviso de "novedad" en su próxima visita al dashboard, que se
    # marca como visto automáticamente al mostrarlo una vez.
    notificado = db.Column(db.Boolean, default=True, nullable=False)

    def __repr__(self):
        return f'<Solicitud {self.id} - {self.tipo_licencia}>'


class Novedad(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(100), nullable=False)
    mensaje = db.Column(db.Text, nullable=False)
    fecha_publicacion = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<Novedad {self.titulo}>'
