"""Motor de días hábiles administrativos y helpers de negocio del sistema de
licencias: cómputo de días hábiles, corte horario de antelación, recálculo
por feriados retroactivos, mecánica de saldos y sanitización de HTML.

Extraído de app.py para poder testear esta lógica de forma aislada, sin
levantar rutas HTTP ni una sesión de Flask.
"""
from datetime import date, datetime, time, timedelta

import bleach

from extensions import db
from models import CATEGORIAS, Feriado, LimiteCategoria, SaldoLicencia, Solicitud

CUTOFF_HORA = time(20, 0)

# Etiquetas permitidas en el mensaje de una Novedad (editor de texto enriquecido
# del panel de admin). Sin atributos: evita que se cuele un onerror=/href=
# javascript: aunque el admin pegue HTML desde otro lado.
NOVEDAD_TAGS_PERMITIDAS = ['b', 'strong', 'i', 'em', 'u', 'ul', 'ol', 'li', 'br', 'p', 'div', 'span']


def _sanitizar_mensaje(html: str) -> str:
    return bleach.clean(html or '', tags=NOVEDAD_TAGS_PERMITIDAS, attributes={}, strip=True)


# --- MOTOR DE DÍAS HÁBILES ADMINISTRATIVOS ---
def cargar_feriados() -> set:
    """Devuelve el set de fechas feriado cargadas (nacionales, provinciales,
    municipales y asuetos: todos se tratan igual a los fines del cómputo)."""
    return {f.fecha for f in Feriado.query.all()}


def es_dia_habil(fecha: date, feriados: set) -> bool:
    return fecha.weekday() < 5 and fecha not in feriados


def contar_dias_habiles(fecha_inicio: date, fecha_fin: date, feriados: set) -> int:
    dias = 0
    actual = fecha_inicio
    while actual <= fecha_fin:
        if es_dia_habil(actual, feriados):
            dias += 1
        actual += timedelta(days=1)
    return dias


def fecha_fin_para_n_dias_habiles(fecha_inicio: date, n: int, feriados: set) -> date:
    """Dado un fecha_inicio y una cantidad objetivo de días hábiles, devuelve
    la fecha en la que se completan. Usada para recalcular una licencia
    cuando se declara un feriado retroactivo dentro de su rango."""
    if n <= 0:
        return fecha_inicio - timedelta(days=1)
    contados = 0
    actual = fecha_inicio
    while True:
        if es_dia_habil(actual, feriados):
            contados += 1
            if contados == n:
                return actual
        actual += timedelta(days=1)


def dia_habil_anterior(fecha: date, feriados: set) -> date:
    d = fecha - timedelta(days=1)
    while not es_dia_habil(d, feriados):
        d -= timedelta(days=1)
    return d


def calcular_cutoff(fecha_inicio: date, feriados: set) -> datetime:
    """Corte de carga: CUTOFF_HORA del último día hábil administrativo previo a
    fecha_inicio."""
    return datetime.combine(dia_habil_anterior(fecha_inicio, feriados), CUTOFF_HORA)


def recalcular_por_nuevo_feriado(fecha_feriado: date) -> list:
    """Se llama justo después de agregar un Feriado nuevo. Busca Solicitud
    Aprobada cuyo rango contenga esa fecha, resta 1 día hábil, recalcula
    fecha_fin y devuelve 1 día al saldo del agente. Si el resultado quedaría
    en 0 días hábiles, no se toca automáticamente: se marca para revisión
    manual del admin (no se puede eliminar en silencio una licencia aprobada)."""
    if fecha_feriado.weekday() >= 5:
        return []

    afectadas = Solicitud.query.filter(
        Solicitud.estado == 'Aprobada',
        Solicitud.fecha_inicio <= fecha_feriado,
        Solicitud.fecha_fin >= fecha_feriado,
    ).all()
    if not afectadas:
        return []

    feriados = cargar_feriados()  # ya incluye el nuevo, se llama post-commit
    resultado = []
    for s in afectadas:
        nuevos_dias = s.dias_solicitados - 1
        # Normaliza categorías legadas ("Vacaciones Enero", etc.) para no
        # acreditar el día devuelto a una categoría fantasma.
        categoria = _normalizar_categoria(s.tipo_licencia)
        if categoria:
            s.tipo_licencia = categoria
        saldo = _obtener_o_crear_saldo(s.id_agente, categoria or s.tipo_licencia)
        if nuevos_dias <= 0:
            s.comentario_admin = (s.comentario_admin or '') + \
                f' [REVISAR: el feriado del {fecha_feriado.strftime("%d/%m/%Y")} deja esta licencia en 0 días hábiles]'
        else:
            s.dias_solicitados = nuevos_dias
            s.fecha_fin = fecha_fin_para_n_dias_habiles(s.fecha_inicio, nuevos_dias, feriados)
            saldo.dias_usados = max(0, saldo.dias_usados - 1)
        resultado.append(s)

    db.session.commit()
    return resultado


def _obtener_o_crear_saldo(id_agente: int, categoria: str) -> SaldoLicencia:
    saldo = SaldoLicencia.query.filter_by(id_agente=id_agente, categoria=categoria).first()
    if not saldo:
        # <-- CORREGIDO: los default=0 de la columna solo se aplican recién al
        # hacer flush/INSERT. Si no se inicializan acá, dias_usados/dias_pendientes
        # quedan en None en el objeto Python y cualquier resta/suma posterior
        # (ej. al rectificar una solicitud) tira TypeError antes de llegar a guardarse.
        saldo = SaldoLicencia(id_agente=id_agente, categoria=categoria,
                               dias_asignados=0, dias_usados=0, dias_pendientes=0)
        db.session.add(saldo)
    return saldo


def _normalizar_categoria(tipo_licencia: str):
    """Mapea texto legado del sistema anterior (ej. "Vacaciones Enero") al
    código de categoría correspondiente. Si ya es un código válido lo
    devuelve tal cual; si no se puede identificar, devuelve None."""
    if tipo_licencia in CATEGORIAS:
        return tipo_licencia
    texto = (tipo_licencia or '').lower()
    if 'enero' in texto:
        return 'LAO'
    if 'julio' in texto or 'invierno' in texto:
        return 'INVIERNO'
    if 'compensatorio' in texto:
        return 'COMPENSATORIO'
    if 'examen' in texto or 'estudio' in texto:
        return 'EXAMEN_ESTUDIO'
    return None


def _limite_categoria(categoria: str):
    """Fecha límite de vigencia de una categoría, o None si no tiene."""
    limite = LimiteCategoria.query.filter_by(categoria=categoria).first()
    return limite.fecha_limite if limite else None


def _categoria_vencida(categoria: str) -> bool:
    """True si la categoría tiene una fecha límite y ya pasó."""
    fecha_limite = _limite_categoria(categoria)
    return fecha_limite is not None and date.today() > fecha_limite


def _crear_solicitud(agente, categoria, fecha_inicio, fecha_fin, comentario,
                      es_oficio=False, constancia_aviso=None, comentario_admin=None):
    """Valida y crea una Solicitud. Devuelve (solicitud, error) — si hay
    error, solicitud es None y no se agregó nada a la sesión. No valida el
    corte horario (CUTOFF_HORA) ni la veda administrativa: eso lo resuelve el caller
    (nueva_solicitud lo valida siempre; la carga de oficio del admin lo
    salta a propósito, es la válvula de escape)."""
    if categoria not in CATEGORIAS:
        return None, 'Categoría de licencia inválida.'
    if categoria == 'EXAMEN_ESTUDIO' and not agente.examen_estudio_habilitado:
        return None, f"No tenés habilitada la categoría {CATEGORIAS['EXAMEN_ESTUDIO']['label']}."
    if fecha_fin < fecha_inicio:
        return None, 'La fecha de fin no puede ser anterior a la fecha de inicio.'

    feriados = cargar_feriados()
    dias_habiles = contar_dias_habiles(fecha_inicio, fecha_fin, feriados)
    if dias_habiles <= 0:
        return None, 'El rango elegido no contiene días hábiles administrativos.'

    saldo = _obtener_o_crear_saldo(agente.id, categoria)
    if saldo.dias_disponibles < dias_habiles:
        return None, (f'No tenés suficientes días disponibles en {CATEGORIAS[categoria]["label"]}. '
                       f'Disponibles: {saldo.dias_disponibles}.')

    estado = 'Aprobada' if es_oficio else 'Pendiente'
    solicitud = Solicitud(
        tipo_licencia=categoria,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        dias_solicitados=dias_habiles,
        comentario_agente=comentario,
        comentario_admin=comentario_admin,
        id_agente=agente.id,
        estado=estado,
        es_oficio=es_oficio,
        constancia_aviso=constancia_aviso,
        creado_en=datetime.now(),
        # Si ya nace Aprobada (carga de oficio), hay una novedad para
        # mostrarle al agente; si nace Pendiente, todavía no hay nada que notificar.
        notificado=not es_oficio,
    )
    db.session.add(solicitud)

    if es_oficio:
        saldo.dias_usados += dias_habiles
    else:
        saldo.dias_pendientes += dias_habiles

    return solicitud, None
