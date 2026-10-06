"""Instancias de extensiones sin ligar a una app todavía.

Separado de app.py para que models.py y motor_licencias.py puedan importar
`db` sin crear una dependencia circular con app.py (que es quien las liga
a la instancia de Flask con `.init_app(app)`).
"""
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_wtf import CSRFProtect

db = SQLAlchemy()
bcrypt = Bcrypt()
csrf = CSRFProtect()
