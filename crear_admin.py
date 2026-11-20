"""Crea o actualiza administrador mediante variables locales; nunca publica contraseñas."""
import os
from getpass import getpass
from werkzeug.security import generate_password_hash
from app import db
if db is None: raise SystemExit('Configura MONGO_URI')
correo = input('Correo del administrador: ').strip().lower()
clave = getpass('Contraseña nueva (mínimo 8 caracteres): ')
if '@' not in correo or len(clave) < 8: raise SystemExit('Datos inválidos')
db.usuarios.update_one({'correo': correo}, {'$set': {'admin': True, 'clave_hash': generate_password_hash(clave), 'nombre': 'Administración AURA'}}, upsert=True)
print('Administrador configurado correctamente.')
