"""Carga productos iniciales sin duplicarlos. Ejecutar tras configurar .env."""
from app import db
from catalogo_seed import PRODUCTOS
if db is None:
    raise SystemExit('Configura MONGO_URI en .env')
db.command('ping')
db.usuarios.create_index('correo', unique=True)
db.pedidos.create_index('qr_token', unique=True, sparse=True)
for item in PRODUCTOS:
    db.productos.update_one({'nombre': item['nombre']}, {'$setOnInsert': {**item, 'activo': True}}, upsert=True)
print('Productos listos:', db.productos.count_documents({'activo': {'$ne': False}}))
