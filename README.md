# AURA Skincare ✿

Tienda educativa de productos para el cuidado de la piel, con diseño rosa y morado. **No procesa pagos reales.**

## Funciones
- Catálogo con búsqueda, filtros y 10 productos de muestra.
- Registro e inicio de sesión con contraseñas cifradas mediante hash.
- Carrito y reserva temporal de **5 minutos**; evita apartar más stock del disponible.
- Cancelación y vencimiento con devolución de existencias.
- Confirmación de compra simulada, historial y QR de verificación pública.
- Administración: crear, consultar, editar y desactivar productos.
- API GET `/api/productos` y diagnóstico GET `/api/estado`.
- Tema claro/oscuro y diseño adaptable a celulares.

## 1. Instalación (Windows / PowerShell)
Abre VS Code **en esta carpeta** (la que contiene `app.py`).

```powershell
py -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
```

Edita `.env` y sustituye `MONGO_URI` por la cadena real de MongoDB Atlas, `SECRET_KEY` por la clave generada y `MONGO_DB` por `aura_skincare`. **Nunca subas `.env` a GitHub**. En Atlas, crea usuario de base de datos y configura Network Access.

```powershell
python seed_demo.py
python crear_admin.py
python app.py
```

Visita http://127.0.0.1:5000 y comprueba http://127.0.0.1:5000/api/estado.

## 2. GitHub
Crea un repositorio **vacío** llamado `AURA-Skincare` en tu cuenta. Verifica primero que `.env` no aparece en `git status`.

```powershell
git init
git branch -M main
git add .
git status
git commit -m "Proyecto inicial AURA Skincare"
git remote add origin https://github.com/TU_USUARIO/AURA-Skincare.git
git push -u origin main
```

Si ya existe `origin`, usa `git remote set-url origin URL`. Para cambios posteriores:

```powershell
git add .
git commit -m "Actualizaciones del proyecto"
git push origin main
```

## 3. Render
- New → Web Service → conecta tu repositorio.
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 90`
- Variables: `MONGO_URI`, `MONGO_DB=aura_skincare`, `SECRET_KEY`, `PUBLIC_BASE_URL=https://TU-SERVICIO.onrender.com`, `SESSION_COOKIE_SECURE=1`, `FLASK_DEBUG=0`.
- Autoriza la conexión a MongoDB Atlas desde Render y verifica `/api/estado`.
- Ejecuta `seed_demo.py` y `crear_admin.py` **desde tu computadora conectada al mismo Atlas**, antes o después de publicar. No los pongas en el comando de inicio de Render.

## 4. Pruebas sugeridas
1. Catálogo y filtros. 2. Registro/login. 3. CRUD de administrador. 4. Agregar al carrito. 5. Reservar cinco minutos. 6. Intentar reservar el último producto desde otra cuenta. 7. Cancelar y comprobar stock. 8. Vencer y comprobar stock. 9. Confirmar y revisar pedido en Atlas. 10. Escanear QR desde celular y comprobar `/api/productos`.

## Notas de implementación
- La expiración se procesa al entrar en catálogo, carrito o iniciar una nueva reserva; no hay tarea periódica en segundo plano. El stock se libera cuando se procesa una solicitud posterior.
- La aplicación es una **base funcional educativa**; para tráfico concurrente elevado conviene usar transacciones MongoDB para coordinar de forma estricta reserva, stock y pedidos, además de controles avanzados (rate limiting, monitoreo y recuperación ante fallos).
- Cambiar `SECRET_KEY` cierra las sesiones existentes. No compartas claves ni contraseñas.
- Los emojis son ilustraciones temporales de producto; pueden reemplazarse por fotografías propias con licencia.


## Fotografías de productos (Velvet Skin)

El administrador puede cargar imágenes JPG, PNG o WEBP (hasta 4 MB) desde **Agregar** o **Editar**. Las fotografías se redimensionan y se guardan en **MongoDB Atlas GridFS**, dentro de la misma base configurada por `MONGO_DB`. Esto permite que las imágenes permanezcan disponibles al desplegar en Render, sin depender del disco temporal del servidor.

1. Instalar dependencias: `python -m pip install -r requirements.txt`.
2. Iniciar la aplicación: `python app.py`.
3. Iniciar sesión como administrador y abrir **Agregar** o **Inventario → Editar**.
4. Elegir la fotografía y guardar. Los productos anteriores siguen existiendo y pueden recibir imágenes mediante **Editar**.

No subir el archivo `.env` a GitHub; configurar `MONGO_URI`, `MONGO_DB` y `SECRET_KEY` como variables de entorno en Render. No es necesario renombrar la base `aura_skincare` para mostrar la marca Velvet Skin.
