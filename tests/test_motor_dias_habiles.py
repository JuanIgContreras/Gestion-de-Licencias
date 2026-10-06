"""Motor de días hábiles: funciones puras, no necesitan tocar la base."""
import datetime as dt

from motor_licencias import (
    calcular_cutoff, contar_dias_habiles, dia_habil_anterior, es_dia_habil,
    fecha_fin_para_n_dias_habiles,
)

VIERNES_ANTERIOR = dt.date(2026, 10, 2)  # viernes de la semana previa a LUNES
LUNES = dt.date(2026, 10, 5)
MARTES = dt.date(2026, 10, 6)
MIERCOLES = dt.date(2026, 10, 7)
JUEVES = dt.date(2026, 10, 8)
VIERNES = dt.date(2026, 10, 9)
SABADO = dt.date(2026, 10, 10)
DOMINGO = dt.date(2026, 10, 11)
LUNES_SIGUIENTE = dt.date(2026, 10, 12)


def test_fin_de_semana_no_es_habil():
    assert not es_dia_habil(SABADO, set())
    assert not es_dia_habil(DOMINGO, set())


def test_dia_de_semana_sin_feriado_es_habil():
    assert es_dia_habil(LUNES, set())
    assert es_dia_habil(VIERNES, set())


def test_feriado_entre_semana_no_es_habil():
    assert not es_dia_habil(MIERCOLES, {MIERCOLES})


def test_contar_dias_habiles_lunes_a_viernes_sin_feriados():
    assert contar_dias_habiles(LUNES, VIERNES, set()) == 5


def test_contar_dias_habiles_atraviesa_un_fin_de_semana():
    # Viernes a lunes siguiente: solo 2 dias habiles (viernes y lunes), el
    # sabado y domingo en el medio no cuentan.
    assert contar_dias_habiles(VIERNES, LUNES_SIGUIENTE, set()) == 2


def test_contar_dias_habiles_con_un_feriado_en_el_medio():
    assert contar_dias_habiles(LUNES, VIERNES, {MIERCOLES}) == 4


def test_contar_dias_habiles_rango_de_un_solo_dia():
    assert contar_dias_habiles(LUNES, LUNES, set()) == 1
    assert contar_dias_habiles(SABADO, SABADO, set()) == 0


def test_fecha_fin_para_n_dias_habiles_sin_feriados():
    # Lunes + 5 dias habiles (sin feriados) = viernes de esa semana
    assert fecha_fin_para_n_dias_habiles(LUNES, 5, set()) == VIERNES


def test_fecha_fin_para_n_dias_habiles_salta_fin_de_semana():
    # Viernes + 2 dias habiles = viernes y el lunes siguiente (salta el finde)
    assert fecha_fin_para_n_dias_habiles(VIERNES, 2, set()) == LUNES_SIGUIENTE


def test_fecha_fin_para_n_dias_habiles_salta_feriado():
    # Lunes + 4 dias habiles con el miercoles feriado = viernes (el feriado
    # empuja el conteo un dia mas alla: lun, mar, (mie feriado), jue, vie)
    assert fecha_fin_para_n_dias_habiles(LUNES, 4, {MIERCOLES}) == VIERNES


def test_fecha_fin_para_cero_dias_es_invalida():
    assert fecha_fin_para_n_dias_habiles(LUNES, 0, set()) == LUNES - dt.timedelta(days=1)


def test_dia_habil_anterior_a_un_lunes_es_el_viernes_previo():
    assert dia_habil_anterior(LUNES, set()) == VIERNES_ANTERIOR


def test_dia_habil_anterior_salta_un_feriado():
    # El dia habil anterior a jueves, con miercoles feriado, es martes.
    assert dia_habil_anterior(JUEVES, {MIERCOLES}) == MARTES


def test_calcular_cutoff_para_un_lunes_es_el_viernes_previo_a_las_20():
    cutoff = calcular_cutoff(LUNES, set())
    assert cutoff.date() == VIERNES_ANTERIOR
    assert cutoff.hour == 20 and cutoff.minute == 0
