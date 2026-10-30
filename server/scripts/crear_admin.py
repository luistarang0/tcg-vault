"""
Crea (o designa) al ÚNICO administrador de TCG Vault.

El administrador entra por el login normal (con todas sus defensas) y es el único
que ve /admin: la bitácora de seguridad con filtros por fecha. La base garantiza
que exista como máximo uno (índice único ux_users_un_admin).

La contraseña se pide en la terminal sin mostrarse (getpass): nunca se pasa por
argumento ni queda en el historial, el código o un archivo.

Uso (desde server/, con el .venv activado):
    python scripts/crear_admin.py --usuario admin --correo admin@tcgvault.mx
    python scripts/crear_admin.py --promover luis_demo           # cuenta existente -> admin
    python scripts/crear_admin.py --usuario admin --correo … --reemplazar   # quita al admin actual
    python scripts/crear_admin.py --ver                          # quién es el admin

Por defecto usa la DATABASE_URL de server/.env (rama dev de Neon). Para producción,
pasa la cadena de la rama main con --url (se toma de Vercel → Storage → Neon).
"""
import argparse
import getpass
import os
import re
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(SERVER / ".env")


def pedir_contrasena() -> str:
    while True:
        p1 = getpass.getpass("Contraseña del administrador (mín. 12 caracteres, no se muestra): ")
        if len(p1) < 12:
            print("  Muy corta. Usa al menos 12 caracteres.")
            continue
        if p1 != getpass.getpass("Repítela: "):
            print("  No coinciden, intenta de nuevo.")
            continue
        return p1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", help="DATABASE_URL a usar (por defecto la de server/.env)")
    ap.add_argument("--usuario", help="nombre de la cuenta nueva de administrador")
    ap.add_argument("--correo", help="correo de la cuenta nueva")
    ap.add_argument("--promover", metavar="USUARIO", help="convierte una cuenta existente en administrador")
    ap.add_argument("--reemplazar", action="store_true", help="si ya hay un admin, le quita el rol")
    ap.add_argument("--ver", action="store_true", help="muestra quién es el administrador y sale")
    a = ap.parse_args()
    if a.url:
        os.environ["DATABASE_URL"] = a.url          # antes de importar app.config

    from app.auth import hash_password             # noqa: E402
    from app.pg import get_pg                      # noqa: E402  (crea la columna si falta)

    with get_pg() as conn:
        actual = conn.execute("SELECT id, username, email FROM users WHERE is_admin").fetchone()
        if a.ver:
            print(f"Administrador: {actual['username']} <{actual['email']}>" if actual else "No hay administrador.")
            return
        if not a.promover and not (a.usuario and a.correo):
            sys.exit("Indica --usuario y --correo (cuenta nueva) o --promover USUARIO.")
        if actual and not a.reemplazar:
            sys.exit(f"Ya existe un administrador ({actual['username']}). Usa --reemplazar para cambiarlo.")

        with conn.transaction():
            if actual:
                conn.execute("UPDATE users SET is_admin = false WHERE id = %s", (actual["id"],))
                conn.execute("DELETE FROM sessions WHERE user_id = %s", (actual["id"],))   # cierra su sesión
                print(f"  {actual['username']} ya no es administrador.")
            if a.promover:
                fila = conn.execute("UPDATE users SET is_admin = true WHERE lower(username) = lower(%s) "
                                    "RETURNING username", (a.promover,)).fetchone()
                if fila is None:
                    sys.exit(f"No existe la cuenta {a.promover}.")    # sale sin confirmar la transacción
                print(f"Listo: {fila['username']} es el administrador.")
                return
            if not re.fullmatch(r"[\w.-]{3,24}", a.usuario):
                sys.exit("El usuario debe tener de 3 a 24 letras, números, punto, guion o guion bajo.")
            if conn.execute("SELECT 1 FROM users WHERE lower(username) = lower(%s) OR lower(email) = lower(%s)",
                            (a.usuario, a.correo)).fetchone():
                sys.exit("Ese usuario o correo ya existe. Usa --promover para convertirlo en admin.")
            password_hash = hash_password(pedir_contrasena())
            # Sin puntos ni sobre inicial: el administrador no participa en el mercado
            conn.execute("INSERT INTO users (username, email, password_hash, is_admin, last_bonus) "
                         "VALUES (%s, %s, %s, true, (now() AT TIME ZONE 'UTC')::date)",
                         (a.usuario, a.correo.lower(), password_hash))
            print(f"Listo: {a.usuario} es el administrador. Entra por /entrar y abre /admin.")


if __name__ == "__main__":
    main()
