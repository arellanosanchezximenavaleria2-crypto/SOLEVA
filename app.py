import base64
import io
import os
import secrets
import gridfs
from PIL import Image, UnidentifiedImageError
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import urlparse

import qrcode
from bson import ObjectId
from bson.errors import InvalidId
from dotenv import load_dotenv
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for, Response
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import PyMongoError
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY') or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.getenv('SESSION_COOKIE_SECURE', '0') == '1', MAX_CONTENT_LENGTH=5*1024*1024)
URI = os.getenv('MONGO_URI', '')
DB_NAME = os.getenv('MONGO_DB', 'aura_skincare')
client = MongoClient(URI, serverSelectionTimeoutMS=5000, tz_aware=True) if URI else None
db = client[DB_NAME] if client is not None else None
fs = gridfs.GridFS(db, collection="imagenes_productos") if db is not None else None
CATEGORIAS = ['Limpieza', 'Tonificación', 'Sérums', 'Hidratación', 'Protección', 'Tratamientos']


def now(): return datetime.now(timezone.utc)
def oid(value):
    try: return ObjectId(value)
    except (InvalidId, TypeError): abort(404)
def money(v): return f'${float(v):,.2f}'
app.jinja_env.filters['money'] = money

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get('uid'):
            flash('Inicia sesión para continuar.', 'warning')
            return redirect(url_for('login'))
        return fn(*args, **kwargs)
    return wrapped

def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        user = db.usuarios.find_one({'_id': oid(session['uid'])})
        if not user or not user.get('admin'):
            abort(403)
        return fn(*args, **kwargs)
    return wrapped

@app.before_request
def csrf_protection():
    if 'csrf' not in session: session['csrf'] = secrets.token_hex(24)
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        if request.form.get('csrf') != session['csrf'] and request.headers.get('X-CSRF-Token') != session['csrf']:
            abort(400, description='Token de seguridad inválido.')
    if db is None and request.endpoint != 'estado':
        abort(503, description='Configura MONGO_URI en .env o en Render.')

@app.context_processor
def globals_template():
    user = None
    if db is not None and session.get('uid'):
        try: user = db.usuarios.find_one({'_id': oid(session['uid'])}, {'clave_hash': 0})
        except Exception: user = None
    return {'usuario': user, 'csrf': session.get('csrf'), 'categorias': CATEGORIAS, 'carrito_cantidad': sum(int(x) for x in session.get('carrito', {}).values())}


def liberar_vencidas():
    """Devuelve unidades de reservas vencidas; transición atómica evita doble devolución."""
    if db is None: return
    for r in db.reservas.find({'estado': 'activa', 'vence': {'$lte': now()}}).limit(200):
        actual = db.reservas.find_one_and_update({'_id': r['_id'], 'estado': 'activa'}, {'$set': {'estado': 'vencida', 'actualizada': now()}}, return_document=ReturnDocument.AFTER)
        if actual:
            for item in actual['items']:
                db.productos.update_one({'_id': item['producto_id']}, {'$inc': {'stock': item['cantidad']}})


def resumen_carrito():
    items = []
    for k, qty in session.get('carrito', {}).items():
        try: prod = db.productos.find_one({'_id': ObjectId(k)})
        except (InvalidId, TypeError): continue
        if prod and 1 <= int(qty) <= 20:
            items.append({'producto': prod, 'cantidad': int(qty), 'subtotal': round(prod['precio'] * int(qty), 2)})
    return items

@app.get('/api/estado')
def estado():
    try:
        if db is None: raise RuntimeError('MONGO_URI sin configurar')
        db.command('ping')
        return jsonify({'ok': True, 'servicio': 'AURA Skincare', 'mongo': 'conectado'})
    except Exception: return jsonify({'ok': False, 'mongo': 'no disponible'}), 503

@app.get('/')
def inicio():
    liberar_vencidas()
    filtro = {'activo': {'$ne': False}}
    cat = request.args.get('categoria', '')
    busqueda = request.args.get('q', '').strip()[:70]
    if cat in CATEGORIAS: filtro['categoria'] = cat
    if busqueda: filtro['nombre'] = {'$regex': __import__('re').escape(busqueda), '$options': 'i'}
    productos = list(db.productos.find(filtro).sort('nombre', 1))
    return render_template('inicio.html', productos=productos, categoria=cat, q=busqueda)

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()[:80]
        correo = request.form.get('correo', '').strip().lower()[:150]
        clave = request.form.get('clave', '')
        if not nombre or '@' not in correo or len(clave) < 8:
            flash('Revisa el nombre, correo y contraseña (mínimo 8 caracteres).', 'danger')
        elif db.usuarios.find_one({'correo': correo}):
            flash('Ese correo ya está registrado.', 'danger')
        else:
            result = db.usuarios.insert_one({'nombre': nombre, 'correo': correo, 'clave_hash': generate_password_hash(clave), 'admin': False, 'creado': now()})
            session.clear(); session['uid'] = str(result.inserted_id); session['csrf'] = secrets.token_hex(24)
            return redirect(url_for('inicio'))
    return render_template('auth.html', modo='registro')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        correo = request.form.get('correo', '').strip().lower()
        user = db.usuarios.find_one({'correo': correo})
        if user and check_password_hash(user['clave_hash'], request.form.get('clave', '')):
            session.clear(); session['uid'] = str(user['_id']); session['csrf'] = secrets.token_hex(24)
            flash('Sesión iniciada.', 'success')
            return redirect(url_for('inicio'))
        flash('Credenciales incorrectas.', 'danger')
    return render_template('auth.html', modo='login')

@app.post('/salir')
def salir():
    session.clear()
    flash('Sesión cerrada.', 'success')
    return redirect(url_for('inicio'))

@app.get('/producto/<id>')
def detalle(id):
    prod = db.productos.find_one({'_id': oid(id), 'activo': {'$ne': False}})
    if not prod: abort(404)
    return render_template('detalle.html', p=prod)

@app.post('/carrito/agregar/<id>')
def agregar_carrito(id):
    prod = db.productos.find_one({'_id': oid(id), 'activo': {'$ne': False}})
    if not prod: abort(404)
    cantidad = max(1, min(20, int(request.form.get('cantidad', 1))))
    carrito = dict(session.get('carrito', {}))
    carrito[id] = min(20, int(carrito.get(id, 0)) + cantidad)
    session['carrito'] = carrito
    flash('Producto agregado al carrito.', 'success')
    return redirect(url_for('carrito'))

@app.post('/carrito/quitar/<id>')
def quitar_carrito(id):
    carrito = dict(session.get('carrito', {})); carrito.pop(id, None); session['carrito'] = carrito
    return redirect(url_for('carrito'))

@app.get('/carrito')
def carrito():
    liberar_vencidas()
    reserva = None
    if session.get('reserva_id'):
        try: reserva = db.reservas.find_one({'_id': ObjectId(session['reserva_id']), 'usuario_id': ObjectId(session['uid'])})
        except (InvalidId, TypeError, KeyError): pass
    items = resumen_carrito()
    return render_template('carrito.html', items=items, total=sum(x['subtotal'] for x in items), reserva=reserva, ahora=now())

@app.post('/reservar')
@login_required
def reservar():
    liberar_vencidas()
    items = resumen_carrito()
    if not items:
        flash('Tu carrito está vacío.', 'warning'); return redirect(url_for('carrito'))
    if db.reservas.find_one({'usuario_id': ObjectId(session['uid']), 'estado': 'activa'}):
        flash('Ya tienes una reserva activa.', 'warning'); return redirect(url_for('carrito'))
    apartados = []
    for item in items:
        p = item['producto']; qty = item['cantidad']
        actualizado = db.productos.find_one_and_update({'_id': p['_id'], 'stock': {'$gte': qty}, 'activo': {'$ne': False}}, {'$inc': {'stock': -qty}}, return_document=ReturnDocument.AFTER)
        if actualizado is None:
            for a in apartados: db.productos.update_one({'_id': a['producto_id']}, {'$inc': {'stock': a['cantidad']}})
            flash('Existencias insuficientes. No se realizó la reserva.', 'danger'); return redirect(url_for('carrito'))
        apartados.append({'producto_id': p['_id'], 'nombre': p['nombre'], 'precio': p['precio'], 'cantidad': qty})
    try:
        rid = db.reservas.insert_one({'usuario_id': ObjectId(session['uid']), 'items': apartados, 'total': round(sum(x['subtotal'] for x in items), 2), 'estado': 'activa', 'creada': now(), 'vence': now() + timedelta(seconds=15)}).inserted_id
    except Exception:
        for a in apartados: db.productos.update_one({'_id': a['producto_id']}, {'$inc': {'stock': a['cantidad']}})
        raise
    session['reserva_id'] = str(rid)
    flash('Productos apartados durante 5 minutos.', 'success')
    return redirect(url_for('carrito'))

@app.post('/reservas/cancelar')
@login_required
def cancelar():
    liberar_vencidas()
    try: rid = ObjectId(session.get('reserva_id', ''))
    except (InvalidId, TypeError): return redirect(url_for('carrito'))
    r = db.reservas.find_one_and_update({'_id': rid, 'usuario_id': ObjectId(session['uid']), 'estado': 'activa'}, {'$set': {'estado': 'cancelada', 'actualizada': now()}}, return_document=ReturnDocument.AFTER)
    if r:
        for i in r['items']: db.productos.update_one({'_id': i['producto_id']}, {'$inc': {'stock': i['cantidad']}})
        flash('Reserva cancelada. Existencias devueltas.', 'success')
    session.pop('reserva_id', None)
    return redirect(url_for('carrito'))

@app.post('/reservas/confirmar')
@login_required
def confirmar():
    liberar_vencidas()
    try: rid = ObjectId(session.get('reserva_id', ''))
    except (InvalidId, TypeError): return redirect(url_for('carrito'))
    r = db.reservas.find_one_and_update({'_id': rid, 'usuario_id': ObjectId(session['uid']), 'estado': 'activa', 'vence': {'$gt': now()}}, {'$set': {'estado': 'confirmada', 'actualizada': now()}}, return_document=ReturnDocument.AFTER)
    if not r:
        flash('La reserva venció o ya fue procesada.', 'danger'); return redirect(url_for('carrito'))
    token = secrets.token_urlsafe(24)
    db.pedidos.insert_one({'reserva_id': rid, 'usuario_id': ObjectId(session['uid']), 'items': r['items'], 'total': r['total'], 'fecha': now(), 'estado': 'Simulada', 'qr_token': token})
    session['carrito'] = {}; session.pop('reserva_id', None)
    flash('Compra simulada registrada correctamente.', 'success')
    return redirect(url_for('mis_compras'))

@app.get('/mis-compras')
@login_required
def mis_compras():
    pedidos = list(db.pedidos.find({'usuario_id': ObjectId(session['uid'])}).sort('fecha', -1))
    base = os.getenv('PUBLIC_BASE_URL', '').rstrip('/') or request.url_root.rstrip('/')
    for pedido in pedidos:
        url = base + url_for('verificar_pedido', token=pedido['qr_token'])
        qr = qrcode.QRCode(box_size=5, border=2); qr.add_data(url); qr.make(fit=True)
        buf = io.BytesIO(); qr.make_image(fill_color='#45235f', back_color='white').save(buf, format='PNG')
        pedido['qr_b64'] = base64.b64encode(buf.getvalue()).decode()
    return render_template('compras.html', pedidos=pedidos)

@app.get('/verificar-pedido/<token>')
def verificar_pedido(token):
    pedido = db.pedidos.find_one({'qr_token': token})
    if not pedido: abort(404)
    return render_template('verificar.html', pedido=pedido)

@app.route('/admin/productos/nuevo', methods=['GET', 'POST'])
@admin_required
def nuevo():
    if request.method == 'POST': return guardar_producto(None)
    return render_template('form_producto.html', p=None)

@app.route('/admin/productos/<id>/editar', methods=['GET', 'POST'])
@admin_required
def editar(id):
    p = db.productos.find_one({'_id': oid(id)})
    if not p: abort(404)
    if request.method == 'POST': return guardar_producto(p)
    return render_template('form_producto.html', p=p)

@app.get('/imagenes/productos/<id>')
def imagen_producto(id):
    try:
        archivo = fs.get(oid(id))
    except (gridfs.errors.NoFile, InvalidId):
        abort(404)
    respuesta = Response(archivo.read(), mimetype=archivo.content_type)
    respuesta.headers['Cache-Control'] = 'public, max-age=86400'
    respuesta.headers['X-Content-Type-Options'] = 'nosniff'
    return respuesta


def guardar_producto(p):
    try:
        nombre = request.form.get('nombre', '').strip()[:100]
        precio = round(float(request.form.get('precio', '0')), 2)
        stock = int(request.form.get('stock', '0'))
        categoria = request.form.get('categoria', '')
        if not nombre or precio <= 0 or stock < 0 or categoria not in CATEGORIAS:
            raise ValueError()
        data = {'nombre': nombre, 'precio': precio, 'stock': stock,
                'categoria': categoria, 'descripcion': request.form.get('descripcion', '').strip()[:500],
                'activo': True}
    except (ValueError, OverflowError):
        flash('Revisa los campos del producto.', 'danger')
        return redirect(request.url)

    archivo = request.files.get('imagen')
    imagen_nueva = None
    if archivo and archivo.filename:
        contenido = archivo.read()
        if len(contenido) > 4 * 1024 * 1024:
            flash('La imagen no puede superar 4 MB.', 'danger')
            return redirect(request.url)
        try:
            img = Image.open(io.BytesIO(contenido))
            img.verify()
            img = Image.open(io.BytesIO(contenido))
            if img.format not in ('JPEG', 'PNG', 'WEBP'):
                raise ValueError('Formato no admitido')
            img.thumbnail((1200, 1200))
            if img.mode not in ('RGB', 'RGBA'):
                img = img.convert('RGB')
            salida = io.BytesIO()
            formato = 'PNG' if img.mode == 'RGBA' else 'JPEG'
            img.save(salida, format=formato, quality=85, optimize=True)
            imagen_nueva = (salida.getvalue(), 'image/png' if formato == 'PNG' else 'image/jpeg')
        except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError):
            flash('Selecciona una imagen JPG, PNG o WEBP válida.', 'danger')
            return redirect(request.url)

    anterior = p.get('imagen_id') if p else None
    try:
        if imagen_nueva:
            data['imagen_id'] = fs.put(imagen_nueva[0], content_type=imagen_nueva[1])
        if p:
            db.productos.update_one({'_id': p['_id']}, {'$set': data, '$unset': {'emoji': ''}})
        else:
            db.productos.insert_one(data)
    except PyMongoError:
        if imagen_nueva and data.get('imagen_id'):
            fs.delete(data['imagen_id'])
        flash('No se pudo guardar el producto. Inténtalo de nuevo.', 'danger')
        return redirect(request.url)
    if anterior and imagen_nueva:
        try: fs.delete(anterior)
        except gridfs.errors.NoFile: pass
    flash('Producto guardado.', 'success')
    return redirect(url_for('inventario'))

@app.post('/admin/productos/<id>/eliminar')
@admin_required
def eliminar(id):
    db.productos.update_one({'_id': oid(id)}, {'$set': {'activo': False}})
    flash('Producto desactivado (se conserva el historial).', 'success')
    return redirect(url_for('inventario'))

@app.get('/inventario')
@admin_required
def inventario():
    return render_template('inventario.html', productos=list(db.productos.find({'activo': {'$ne': False}}).sort('nombre', 1)))

@app.get('/api/productos')
def api_productos():
    datos = list(db.productos.find({'activo': {'$ne': False}}, {'nombre': 1, 'categoria': 1, 'precio': 1, 'stock': 1, 'descripcion': 1, 'imagen_id': 1}))
    for x in datos:
        x['_id'] = str(x['_id'])
        x['imagen_url'] = url_for('imagen_producto', id=str(x['imagen_id'])) if x.get('imagen_id') else None
        x.pop('imagen_id', None)
    return jsonify({'total': len(datos), 'productos': datos})

@app.get('/ayuda')
def ayuda(): return render_template('ayuda.html')

@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(503)
def error(e): return render_template('error.html', mensaje=getattr(e, 'description', str(e)), codigo=e.code), e.code

if __name__ == '__main__':
    app.run(debug=os.getenv('FLASK_DEBUG', '0') == '1')
