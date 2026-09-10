"""Actualiza la base de datos desde agentes.xlsx e historial_licencias.xlsx.

Antes este script escribia los excels directamente en la base con pandas
(`to_sql(..., if_exists="replace")`), pero lo hacia sobre tablas llamadas
"agentes" y "historial_licencias" que no son las que usa la app (los modelos
de SQLAlchemy usan "agente" y "solicitud"). Es decir, no actualizaba nada de
lo que la aplicacion realmente lee, y si los nombres se hubieran corregido a
secas, un `if_exists="replace"` habria borrado las tablas reales (con los
hashes de contraseña, ids referenciados por licencias/permisos, etc.).

Ahora reutiliza exactamente la misma logica que los comandos
`flask import-agents` / `flask import-history` (altas sin duplicar usuarios,
contraseña temporal = usuario, actualizacion de saldos de dias), asi que es
seguro correrlo mas de una vez.
"""
import os

from app import app, import_agents_command, import_history_command

base_path = os.path.dirname(os.path.abspath(__file__))
archivo_agentes = os.path.join(base_path, "agentes.xlsx")
archivo_historial = os.path.join(base_path, "historial_licencias.xlsx")

with app.app_context():
    print("=== Importando agentes ===")
    import_agents_command.callback(archivo_agentes)

    print("\n=== Importando historial de licencias ===")
    import_history_command.callback(archivo_historial)

print("\nBase de datos actualizada correctamente.")
