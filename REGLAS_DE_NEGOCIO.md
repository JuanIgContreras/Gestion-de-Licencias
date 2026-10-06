# Reglas de negocio — Sistema de Gestión de Licencias

Este documento describe **qué hace el sistema y por qué**, en términos de
reglas de negocio, independientemente del código que las implementa. Sirve
como referencia para RRHH y para cualquier persona que continúe el
mantenimiento del sistema sin haber participado de las decisiones originales.

Para el detalle técnico de cómo está armado el código, ver el apéndice al
final de este documento.

---

## 1. Alcance

El sistema gestiona **exclusivamente licencias por días completos**. No
existe ningún concepto de permisos por horas, franquicias horarias ni
salidas particulares — esa funcionalidad existió en una versión anterior del
sistema y fue eliminada por completo a pedido explícito.

## 2. Categorías de licencia

Hay 4 categorías fijas, cada una con un cupo de días configurable **por
agente** desde el panel de administrador:

| Categoría | Cupo provisorio por defecto | Disponibilidad |
|---|---|---|
| **LAO** (Licencia Anual Ordinaria) | 22 días | Todos los agentes |
| **Invierno** (Feria) | 10 días | Todos los agentes |
| **Compensatorios** | 0 días | Todos los agentes |
| **Examen / Estudio** | 20 días | Solo los agentes que el administrador habilite explícitamente, uno por uno |

El cupo de cada categoría es independiente por agente: el administrador
puede darle a un agente puntual más o menos días que el valor provisorio de
la tabla, sin afectar a los demás.

## 3. Cómputo en días hábiles administrativos

Los días de licencia se cuentan **de lunes a viernes, excluyendo los
feriados cargados en el sistema** (nacionales, provinciales, municipales o
asuetos — todos se tratan igual a los fines del cómputo). Un rango que
atraviesa un fin de semana o un feriado no cuenta esos días: por ejemplo, de
viernes a lunes siguiente son 2 días hábiles, no 4.

El fraccionamiento mínimo es de 1 día hábil.

Los feriados se cargan a mano desde el panel de administrador, o
importando un archivo Excel/CSV con columnas `fecha`, `descripcion` y,
opcionalmente, `tipo`.

## 4. Mecánica de saldos

Cada agente tiene, por categoría, tres contadores:

- **Asignados**: el cupo configurado por el administrador.
- **Usados**: los días de licencias ya aprobadas.
- **Pendientes**: los días reservados por solicitudes que todavía no fueron
  resueltas por el administrador.

```
Disponibles = Asignados − (Usados + Pendientes)
```

**Al enviar una solicitud**, los días pasan de inmediato a "Pendientes" —
quedan reservados aunque el administrador todavía no la haya revisado, así
que no se puede pedir dos veces el mismo saldo. Si el administrador
**rechaza** la solicitud, o el propio agente la **cancela** (solo se puede
mientras sigue pendiente), esos días vuelven de inmediato a disponibles. Si
el administrador la **aprueba**, los días pasan de "Pendientes" a "Usados".

## 5. Regla de antelación (corte de las 20:00hs)

Los agentes no pueden solicitar licencias para el mismo día ni fuera de
término. Toda solicitud debe cargarse **a más tardar el último día hábil
previo hasta las 20:00hs**. Por ejemplo, para ausentarse un lunes, el corte
es el viernes anterior a las 20:00hs (o el día hábil anterior a ese, si el
viernes fuera feriado).

El formulario bloquea las fechas inválidas y muestra un cartel explicando la
regla antes de que el agente intente cargar.

### Válvula de escape: Carga de Oficio

El administrador cuenta con una opción de **Carga de Oficio** para registrar
una licencia el mismo día o fuera de término, para una ausencia excepcional
avisada por teléfono. Al usarla, el sistema **exige** dejar constancia por
escrito del aviso (quién avisó, cuándo, por qué). La solicitud queda
directamente en estado Aprobada — no pasa por una segunda revisión, ya que
es el propio administrador quien la está autorizando.

## 6. Veda administrativa

El administrador puede definir **períodos de veda**: rangos de fechas donde
los agentes no pueden cargar solicitudes propias (por ejemplo, durante la
liquidación de sueldos). Durante esos rangos, solo el administrador puede
registrar licencias, usando Carga de Oficio.

## 7. Plazos de vigencia por categoría (y prórroga)

Cada categoría puede tener, opcionalmente, una **fecha límite** configurada
por el administrador (por ejemplo, Invierno vence el 30/09). Pasado ese
plazo:

- El agente **ya no puede solicitar** esa categoría (ni cargar una nueva
  solicitud, ni editar una pendiente hacia esa categoría).
- Sus días **disponibles se muestran en 0** en el dashboard, aunque el cupo
  y lo ya usado no se tocan por abajo.

Si más adelante se decide una **prórroga**, alcanza con que el administrador
mueva la fecha límite hacia adelante (o la borre por completo para quitar el
límite) — los días vuelven a estar disponibles automáticamente, sin ninguna
acción adicional. El administrador, vía Carga de Oficio, siempre puede
seguir cargando en una categoría vencida: el límite frena al agente, no al
administrador.

## 8. Recálculo automático por feriado retroactivo

Si se declara un asueto de último momento (se carga un feriado nuevo) y esa
fecha cae dentro de una licencia **ya aprobada**, el sistema:

1. Resta 1 día hábil de esa solicitud.
2. Recalcula su fecha de fin.
3. Devuelve 1 día al saldo del agente (a "Usados", que baja en 1).

Si el resultado dejara a la licencia en 0 días hábiles, el sistema **no la
borra automáticamente** — se le agrega un comentario de "REVISAR" para que
el administrador la resuelva a mano, porque eliminar en silencio una
licencia ya aprobada podría ocultar un error.

## 9. Reclasificación de categoría al aprobar

Al revisar una solicitud pendiente, el administrador puede **cambiar la
categoría** a discreción antes de aprobarla (por ejemplo, el agente pidió
LAO pero corresponde Invierno). El sistema valida que haya saldo suficiente
en la categoría nueva; si no lo hay, rechaza la reclasificación con un
mensaje claro y la solicitud queda pendiente sin tocar nada.

## 10. Cierre de ejercicio (31/12)

Es una acción manual del administrador (no ocurre sola). Al ejecutarla:

- Los saldos **usados y pendientes** de las 4 categorías, de todos los
  agentes, se reinician a 0 — los días no gozados durante el año se pierden,
  tal como corresponde a una licencia anual.
- Los **cupos asignados** de cada agente no se modifican: siguen siendo el
  valor configurado por el administrador.
- Se **bloquea** si queda alguna solicitud pendiente sin resolver en
  cualquier agente, para no perder la reserva de una solicitud todavía en
  trámite. El administrador tiene que aprobar o rechazar todo lo pendiente
  antes de poder cerrar el ejercicio.

## 11. Notificaciones al agente

Cuando el administrador aprueba, rechaza, o carga de oficio una solicitud,
el agente ve un aviso ("N novedades") junto a "Mis Solicitudes" la próxima
vez que entra al sistema. El aviso se marca como visto automáticamente al
mostrarse una vez — no vuelve a aparecer hasta que haya algo nuevo que
avisar.

## 12. Calendario colectivo y privacidad

Todos los agentes pueden consultar un calendario compartido con las
ausencias aprobadas de sus compañeros. Por una decisión explícita de
privacidad, esa vista **solo muestra el nombre del agente y que está
ausente** — nunca la categoría de la licencia ni ningún comentario o motivo.
Esa información solo la ve el administrador desde el panel de gestión.

Al cargar una nueva solicitud, el agente ve además un aviso (no bloqueante)
si ya hay compañeros con licencia aprobada en esas mismas fechas — con el
mismo criterio de privacidad, solo nombres.

## 13. Seguridad

- Todos los formularios están protegidos contra CSRF.
- El mensaje de las Novedades admite negrita/cursiva/subrayado/listas desde
  un editor simple, pero el HTML se **sanitiza en el servidor** antes de
  guardarse: solo se permiten esas etiquetas, sin atributos — cualquier
  script o atributo peligroso (`onclick`, `javascript:`, etc.) se elimina
  automáticamente, aunque se haya pegado desde otro lado.
- Las contraseñas se guardan con hash (bcrypt), nunca en texto plano. La
  contraseña temporal de un agente recién creado es su propio nombre de
  usuario.
- Se registra la **fecha y hora de la última conexión** de cada agente,
  visible para el administrador en el Reporte de Agentes.

---

## Apéndice técnico

### Estructura del código

- `extensions.py` — instancias de Flask-SQLAlchemy, Flask-Bcrypt y
  Flask-WTF sin ligar a la app todavía (evita import circular).
- `models.py` — todos los modelos de la base de datos y el diccionario
  `CATEGORIAS`.
- `motor_licencias.py` — el motor de días hábiles, el corte de antelación,
  el recálculo por feriado retroactivo, la mecánica de saldos y la
  sanitización de HTML. Es la lógica de negocio "pura", separada de las
  rutas HTTP.
- `app.py` — la app de Flask en sí: configuración, migración de esquema, y
  todas las rutas (`@app.route`) y comandos de CLI (`@app.cli.command`).

### Cómo correr los tests

```bash
pip install -r requirements-dev.txt
pytest
```

Los tests corren contra un archivo SQLite temporal (nunca contra
`database.db`, la base real) — `tests/conftest.py` fija la variable de
entorno `DATABASE_URL` antes de importar `app.py`. Cada test arranca con las
tablas vacías, así que ninguno depende de datos dejados por otro.

### Migración de esquema

`migrar_esquema()`, en `app.py`, corre automáticamente al levantar la app.
Es aditiva e idempotente: agrega columnas/tablas que falten sin borrar
datos, y es segura de correr en cada arranque. Si alguna vez hace falta
agregar un campo nuevo a un modelo existente, el patrón a seguir es el
mismo: agregar la columna al modelo en `models.py`, y un
`ALTER TABLE ... ADD COLUMN` guardado por una comprobación de existencia
dentro de `migrar_esquema()`.
