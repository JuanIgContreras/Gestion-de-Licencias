import sys

from app import app, db, Agente, Solicitud

def eliminar_rechazadas(usuarios):
    total = 0
    for usuario in usuarios:
        agente = Agente.query.filter_by(usuario=usuario).first()
        if not agente:
            print(f"⚠️ No se encontró el agente '{usuario}'")
            continue

        solicitudes = Solicitud.query.filter_by(id_agente=agente.id, estado='Rechazada').all()
        if not solicitudes:
            print(f"✅ El agente '{usuario}' no tiene solicitudes rechazadas.")
            continue

        for s in solicitudes:
            print(f"🗑️ Eliminando solicitud ID {s.id} ({s.tipo_licencia}) de {usuario}")
            db.session.delete(s)
            total += 1

    db.session.commit()
    print(f"\n✅ Se eliminaron {total} solicitudes rechazadas en total.")

if __name__ == "__main__":
    # Uso: python eliminar_rechazadas.py <usuario1> <usuario2> ...
    usuarios = sys.argv[1:]
    if not usuarios:
        print("Uso: python eliminar_rechazadas.py <usuario1> <usuario2> ...")
        print("Ejemplo: python eliminar_rechazadas.py 40701957 18695335")
        sys.exit(1)

    # 🧩 AGREGAMOS EL CONTEXTO DE FLASK AQUÍ:
    with app.app_context():
        eliminar_rechazadas(usuarios)
