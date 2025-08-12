# Sistema de Optimización de Rutas

Sistema web para la optimización y seguimiento de rutas con navegación GPS en tiempo real.

## Características

- 🚗 **Gestión de usuarios** con 4 roles: Administrador, Técnico, Coordinador, Chofer
- 📍 **Optimización de rutas** desde archivos GPX
- 🗺️ **Navegación GPS** en tiempo real estilo Waze
- 📊 **Panel de métricas** y análisis de recorridos
- 🚛 **Gestión de vehículos** y asignaciones
- 📱 **Diseño responsive** para móviles y tablets

## Roles del Sistema

### 👑 Administrador
- Gestión completa de usuarios, rutas y vehículos
- Creación de rutas optimizadas desde archivos GPX
- Acceso a todas las métricas y estadísticas

### 🔧 Técnico
- Cambio de contraseñas de usuarios
- Activar/desactivar usuarios (excepto administradores)

### 📊 Coordinador
- Visualización de métricas y estadísticas
- Revisión de mapas y recorridos
- Análisis de rendimiento

### 🚗 Chofer
- Selección de rutas disponibles
- Elección de vehículo para el recorrido
- Navegación GPS en tiempo real
- Completar o cancelar recorridos

## Instalación Local

1. **Clonar el repositorio**
   ```bash
   git clone https://github.com/tu-usuario/ruta-optimizada.git
   cd ruta-optimizada
   ```

2. **Crear entorno virtual**
   ```bash
   python -m venv myenv
   source myenv/bin/activate  # En Windows: myenv\Scripts\activate
   ```

3. **Instalar dependencias**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configurar variables de entorno**
   ```bash
   cp .env.example .env
   # Editar .env con tus configuraciones
   ```

5. **Ejecutar la aplicación**
   ```bash
   python app.py
   ```

6. **Acceder al sistema**
   - URL: `http://localhost:5000`
   - Para resetear la DB: `http://localhost:5000/reset_database`

## Credenciales por Defecto

```
Administrador: admin / admin123
Técnico: tecnico / tecnico123
Coordinador: coordinador / coordinador123
Chofer: chofer / chofer123
```

## Despliegue en Render

### Opción 1: Usando render.yaml (Recomendado)

1. **Subir a GitHub**
   ```bash
   git add .
   git commit -m "Initial commit"
   git push origin main
   ```

2. **Conectar con Render**
   - Ve a [Render.com](https://render.com)
   - Conecta tu repositorio de GitHub
   - Render detectará automáticamente el archivo `render.yaml`

3. **Configurar variables de entorno en Render**
   - `FLASK_ENV=production`
   - `SECRET_KEY` (se genera automáticamente)
   - `DATABASE_URL` (se configura automáticamente con PostgreSQL)

### Opción 2: Configuración Manual

1. **Crear Web Service**
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn --bind 0.0.0.0:$PORT app:app`
   - Environment: `Python`

2. **Crear PostgreSQL Database**
   - En Render, crear nueva base de datos PostgreSQL
   - Copiar la URL de conexión

3. **Variables de entorno**
   ```
   FLASK_ENV=production
   SECRET_KEY=tu_clave_secreta_aqui
   DATABASE_URL=postgresql://...
   ```

## Despliegue en Heroku

1. **Instalar Heroku CLI**

2. **Crear aplicación**
   ```bash
   heroku create tu-app-name
   ```

3. **Agregar PostgreSQL**
   ```bash
   heroku addons:create heroku-postgresql:hobby-dev
   ```

4. **Configurar variables**
   ```bash
   heroku config:set FLASK_ENV=production
   heroku config:set SECRET_KEY=tu_clave_secreta
   ```

5. **Desplegar**
   ```bash
   git push heroku main
   ```

## Estructura del Proyecto

```
ruta_optimizada/
├── app.py                 # Aplicación principal
├── requirements.txt       # Dependencias Python
├── render.yaml           # Configuración para Render
├── Procfile              # Configuración para Heroku
├── .env.example          # Variables de entorno ejemplo
├── .gitignore            # Archivos a ignorar en Git
├── templates/            # Plantillas HTML
├── static/              # Archivos estáticos (CSS, JS)
├── uploads/             # Archivos GPX subidos
└── routes/              # Mapas generados
```

## Tecnologías Utilizadas

- **Backend**: Flask, SQLAlchemy, Flask-Login
- **Frontend**: Bootstrap 5, jQuery, Font Awesome
- **Mapas**: Leaflet, Folium
- **GPS**: Geolocation API del navegador
- **Optimización**: NetworkX, Geopy
- **Base de datos**: SQLite (desarrollo), PostgreSQL (producción)

## Contribuir

1. Fork el proyecto
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request

## Licencia

Este proyecto está bajo la Licencia MIT. Ver el archivo `LICENSE` para más detalles.

## Soporte

Para soporte, abre un issue en GitHub o contacta al equipo de desarrollo.# gad_yantzaza
