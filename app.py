import os
import uuid
import json
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

import gpxpy
import networkx as nx
from geopy.distance import geodesic
import folium

# Inicialización de extensiones
db = SQLAlchemy()
login_manager = LoginManager()

# ==================== MODELOS DE BASE DE DATOS ====================

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    cedula = db.Column(db.String(20), unique=True, nullable=False)
    role = db.Column(db.String(20), default='driver')  # admin, driver, technician, coordinator
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    driver_info = db.relationship('DriverInfo', backref='user', uselist=False, cascade="all, delete-orphan")
    routes_created = db.relationship('Route', backref='creator', lazy=True, foreign_keys='Route.creator_id')
    routes_driven = db.relationship('RouteCompletion', backref='driver', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    @property
    def is_admin(self):
        return self.role == 'admin'
    
    @property
    def is_technician(self):
        return self.role == 'technician'
    
    @property
    def is_coordinator(self):
        return self.role == 'coordinator'
    
    @property
    def is_driver(self):
        return self.role == 'driver'

    def __repr__(self):
        return f'<User {self.username}>'


class DriverInfo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    license_type = db.Column(db.String(20), nullable=False)
    active = db.Column(db.Boolean, default=True)
    vehicles = db.relationship('VehicleAssignment', backref='driver', lazy=True)


class Vehicle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    brand = db.Column(db.String(100), nullable=False)
    model = db.Column(db.String(100), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    plate_number = db.Column(db.String(20), unique=True, nullable=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    drivers = db.relationship('VehicleAssignment', backref='vehicle', lazy=True)


class VehicleAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver_info.id'), nullable=False)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=False)
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)
    active = db.Column(db.Boolean, default=True)


class Route(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    file_path = db.Column(db.String(200), nullable=False)
    gpx_path = db.Column(db.String(200), nullable=True)
    start_point = db.Column(db.String(100), nullable=True)
    end_point = db.Column(db.String(100), nullable=True)
    distance = db.Column(db.Float, nullable=True)
    active = db.Column(db.Boolean, default=True)
    completions = db.relationship('RouteCompletion', backref='route', lazy=True)
    
    def __repr__(self):
        return f'<Route {self.name}>'


class RouteCompletion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    route_id = db.Column(db.Integer, db.ForeignKey('route.id'), nullable=False)
    driver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=False)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default='pending')
    track_data = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    vehicle = db.relationship('Vehicle', backref='route_completions')


# ==================== DECORADORES DE AUTORIZACIÓN ====================

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Debes iniciar sesión para acceder a esta página.', 'danger')
                return redirect(url_for('login'))
            
            if current_user.role not in roles:
                flash('No tienes permisos para acceder a esta página.', 'danger')
                return redirect(url_for('dashboard'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def admin_required(f):
    return role_required('admin')(f)

def technician_required(f):
    return role_required('admin', 'technician')(f)

def coordinator_required(f):
    return role_required('admin', 'coordinator')(f)

def driver_required(f):
    return role_required('admin', 'driver')(f)


# ==================== FUNCIONES AUXILIARES ====================

def load_gpx_points(file_path):
    with open(file_path, 'r') as gpx_file:
        gpx = gpxpy.parse(gpx_file)
    points = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                points.append((point.latitude, point.longitude))
    return points

def optimize_route(file_paths):
    all_points = []
    for path in file_paths:
        all_points.extend(load_gpx_points(path))

    graph = nx.Graph()
    total_distance = 0
    
    for i in range(len(all_points) - 1):
        dist = geodesic(all_points[i], all_points[i + 1]).meters
        graph.add_edge(all_points[i], all_points[i + 1], weight=dist)
        total_distance += dist

    start = all_points[0]
    end = all_points[-1]
    
    try:
        optimal_path = nx.shortest_path(graph, source=start, target=end, weight='weight')
        return optimal_path, total_distance
    except nx.NetworkXNoPath:
        raise Exception("No se pudo encontrar una ruta entre los puntos de inicio y fin.")


# ==================== CREACIÓN DE LA APLICACIÓN ====================

def create_app():
    app = Flask(__name__)
    
    # Configuración
    app.config['SECRET_KEY'] = 'clave_secreta_para_flask'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = './uploads'
    
    # Crear directorios necesarios
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs('static/routes', exist_ok=True)
    
    # Inicializar extensiones
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    login_manager.login_message = 'Por favor inicia sesión para acceder a esta página'
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
    
    # Filtros de plantilla
    @app.template_filter('datetime_format')
    def datetime_format(value, format='%d/%m/%Y %H:%M'):
        if value is None:
            return "Fecha no disponible"
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                return value
        return value.strftime(format)

    @app.template_filter('distance_format')
    def distance_format(meters):
        if meters is None:
            return "N/A"
        if meters < 1000:
            return f"{int(meters)} m"
        else:
            return f"{meters/1000:.2f} km"

    # Contexto global para plantillas
    @app.context_processor
    def inject_globals():
        return {
            'now': datetime.now(),
            'current_year': datetime.now().year
        }

    # ==================== RUTAS PRINCIPALES ====================
    
    @app.route('/')
    def index():
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
        else:
            return redirect(url_for('login'))

    @app.route('/info')
    def system_info():
        """Página informativa del sistema (opcional)"""
        recent_routes = Route.query.filter_by(active=True).order_by(Route.created_at.desc()).limit(3).all()
        return render_template('index.html', routes=recent_routes)

    @app.route('/dashboard')
    @login_required
    def dashboard():
        try:
            if current_user.is_admin:
                print(f"Redirigiendo admin: {current_user.username}")
                return redirect(url_for('admin_dashboard'))
            elif current_user.is_technician:
                print(f"Redirigiendo técnico: {current_user.username}")
                return redirect(url_for('technician_dashboard'))
            elif current_user.is_coordinator:
                print(f"Redirigiendo coordinador: {current_user.username}")
                return redirect(url_for('coordinator_dashboard'))
            else:  # driver
                print(f"Redirigiendo chofer: {current_user.username}")
                return redirect(url_for('driver_dashboard'))
        except Exception as e:
            print(f"ERROR en dashboard redirect: {e}")
            import traceback
            traceback.print_exc()
            flash(f'Error al redirigir: {str(e)}', 'danger')
            return redirect(url_for('login'))

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
        
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            
            print(f"Intento de login: {username}")  # Debug
            
            user = User.query.filter_by(username=username, active=True).first()
            
            if user:
                print(f"Usuario encontrado: {user.username}, rol: {user.role}")  # Debug
                if user.check_password(password):
                    login_user(user)
                    flash('¡Inicio de sesión exitoso!', 'success')
                    print(f"Login exitoso para: {username}")  # Debug
                    return redirect(url_for('dashboard'))
                else:
                    print(f"Contraseña incorrecta para: {username}")  # Debug
                    flash('Usuario o contraseña incorrectos.', 'danger')
            else:
                print(f"Usuario no encontrado: {username}")  # Debug
                flash('Usuario o contraseña incorrectos.', 'danger')
        
        return render_template('login.html')

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        flash('Has cerrado sesión correctamente.', 'success')
        return redirect(url_for('login'))

    # ==================== RUTAS DE ADMINISTRADOR ====================
    
    @app.route('/admin/dashboard')
    @admin_required
    def admin_dashboard():
        try:
            total_users = User.query.filter_by(active=True).count()
            total_drivers = User.query.filter_by(role='driver', active=True).count()
            total_vehicles = Vehicle.query.filter_by(active=True).count()
            total_routes = Route.query.filter_by(active=True).count()
            
            # Obtener rutas con sus creadores de forma segura
            recent_routes = db.session.query(Route).join(User, Route.creator_id == User.id, isouter=True).order_by(Route.created_at.desc()).limit(5).all()
            
            print(f"DEBUG Dashboard: {total_users} usuarios, {total_routes} rutas, {len(recent_routes)} rutas recientes")  # Debug
            
            return render_template('admin/dashboard.html', 
                                 total_users=total_users,
                                 total_drivers=total_drivers,
                                 total_vehicles=total_vehicles, 
                                 total_routes=total_routes,
                                 recent_routes=recent_routes)
        except Exception as e:
            print(f"ERROR en admin_dashboard: {e}")  # Debug
            import traceback
            traceback.print_exc()  # Imprime el traceback completo
            flash(f'Error al cargar el dashboard: {str(e)}', 'danger')
            return render_template('admin/dashboard.html', 
                                 total_users=0,
                                 total_drivers=0,
                                 total_vehicles=0, 
                                 total_routes=0,
                                 recent_routes=[])

    @app.route('/admin/users')
    @admin_required
    def manage_users():
        users = User.query.filter_by(active=True).order_by(User.role, User.last_name).all()
        return render_template('admin/users.html', users=users)

    @app.route('/admin/create_user', methods=['GET', 'POST'])
    @admin_required
    def create_user():
        if request.method == 'POST':
            username = request.form.get('username')
            email = request.form.get('email')
            password = request.form.get('password')
            first_name = request.form.get('first_name')
            last_name = request.form.get('last_name')
            cedula = request.form.get('cedula')
            role = request.form.get('role')
            license_type = request.form.get('license_type')
            
            # Validaciones
            if User.query.filter_by(username=username).first():
                flash('El nombre de usuario ya existe.', 'danger')
                return redirect(url_for('create_user'))
            
            if User.query.filter_by(email=email).first():
                flash('El email ya está registrado.', 'danger')
                return redirect(url_for('create_user'))
            
            if User.query.filter_by(cedula=cedula).first():
                flash('La cédula ya está registrada.', 'danger')
                return redirect(url_for('create_user'))
            
            # Crear usuario
            new_user = User(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                cedula=cedula,
                role=role
            )
            new_user.set_password(password)
            
            db.session.add(new_user)
            db.session.flush()
            
            # Si es chofer, crear información adicional
            if role == 'driver' and license_type:
                driver_info = DriverInfo(
                    user_id=new_user.id,
                    license_type=license_type
                )
                db.session.add(driver_info)
            
            db.session.commit()
            flash(f'Usuario {role} creado exitosamente.', 'success')
            return redirect(url_for('manage_users'))
        
        return render_template('admin/create_user.html')

    @app.route('/admin/routes')
    @admin_required
    def manage_routes():
        try:
            routes = Route.query.filter_by(active=True).order_by(Route.created_at.desc()).all()
            print(f"DEBUG: Encontradas {len(routes)} rutas")  # Debug
            for route in routes:
                print(f"DEBUG: Ruta {route.id}: {route.name}, creador: {route.creator_id}")  # Debug
            return render_template('admin/routes.html', routes=routes)
        except Exception as e:
            print(f"ERROR en manage_routes: {e}")  # Debug
            flash(f'Error al cargar las rutas: {str(e)}', 'danger')
            return redirect(url_for('admin_dashboard'))

    @app.route('/admin/create_route', methods=['GET', 'POST'])
    @admin_required
    def create_route():
        if request.method == 'POST':
            files = request.files.getlist('gpx_files')
            route_name = request.form.get('route_name')
            route_description = request.form.get('route_description')
            
            if not route_name or not files:
                flash('Nombre de ruta y archivos GPX son requeridos.', 'danger')
                return redirect(url_for('create_route'))
            
            if Route.query.filter_by(name=route_name).first():
                flash('Ya existe una ruta con ese nombre.', 'danger')
                return redirect(url_for('create_route'))
            
            uploaded_files = []
            original_gpx_path = None
            
            for file in files:
                if file.filename.endswith('.gpx'):
                    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                    filename = secure_filename(f"{timestamp}_{file.filename}")
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(filepath)
                    uploaded_files.append(filepath)
                    
                    if not original_gpx_path:
                        original_gpx_path = filepath
            
            if not uploaded_files:
                flash('No se subieron archivos GPX válidos.', 'danger')
                return redirect(url_for('create_route'))
            
            try:
                optimal_path, total_distance = optimize_route(uploaded_files)
                
                # Crear mapa
                map_center = optimal_path[0]
                route_map = folium.Map(location=map_center, zoom_start=14)
                
                folium.PolyLine(optimal_path, color="blue", weight=5, opacity=0.8).add_to(route_map)
                folium.Marker(location=optimal_path[0], popup="Inicio", icon=folium.Icon(color="green")).add_to(route_map)
                folium.Marker(location=optimal_path[-1], popup="Fin", icon=folium.Icon(color="red")).add_to(route_map)
                
                map_filename = f"route_{uuid.uuid4().hex}.html"
                map_filepath = os.path.join('static', 'routes', map_filename)
                route_map.save(map_filepath)
                
                # Guardar en base de datos
                new_route = Route(
                    name=route_name,
                    description=route_description,
                    creator_id=current_user.id,
                    file_path=map_filepath,
                    gpx_path=original_gpx_path,
                    start_point=f"{optimal_path[0][0]},{optimal_path[0][1]}",
                    end_point=f"{optimal_path[-1][0]},{optimal_path[-1][1]}",
                    distance=total_distance
                )
                
                db.session.add(new_route)
                db.session.commit()
                
                flash(f'Ruta "{route_name}" creada exitosamente.', 'success')
                return redirect(url_for('manage_routes'))
                
            except Exception as e:
                flash(f'Error al procesar la ruta: {str(e)}', 'danger')
                return redirect(url_for('create_route'))
        
        return render_template('admin/create_route.html')

    @app.route('/admin/vehicles')
    @admin_required
    def manage_vehicles():
        vehicles = Vehicle.query.filter_by(active=True).order_by(Vehicle.brand).all()
        return render_template('admin/vehicles.html', vehicles=vehicles)

    @app.route('/admin/add_vehicle', methods=['GET', 'POST'])
    @admin_required
    def add_vehicle():
        if request.method == 'POST':
            brand = request.form.get('brand')
            model = request.form.get('model')
            year = request.form.get('year')
            plate_number = request.form.get('plate_number')
            
            if Vehicle.query.filter_by(plate_number=plate_number).first():
                flash('Ya existe un vehículo con esa placa.', 'danger')
                return redirect(url_for('add_vehicle'))
            
            new_vehicle = Vehicle(
                brand=brand,
                model=model,
                year=year,
                plate_number=plate_number
            )
            
            db.session.add(new_vehicle)
            db.session.commit()
            
            flash('Vehículo añadido correctamente.', 'success')
            return redirect(url_for('manage_vehicles'))
        
        return render_template('admin/add_vehicle.html')

    @app.route('/admin/view_route/<int:route_id>')
    @admin_required
    def admin_view_route(route_id):
        route = Route.query.get_or_404(route_id)
        
        try:
            with open(route.file_path, 'r', encoding='utf-8') as f:
                map_html = f.read()
        except Exception as e:
            map_html = "<p>No se pudo cargar el mapa</p>"
        
        completions = RouteCompletion.query.filter_by(route_id=route.id).order_by(RouteCompletion.completed_at.desc()).all()
        
        return render_template('admin/view_route.html',
                             route=route,
                             map_html=map_html,
                             completions=completions)

    @app.route('/admin/delete_route/<int:route_id>', methods=['POST'])
    @admin_required
    def delete_route(route_id):
        route = Route.query.get_or_404(route_id)
        
        # Eliminar el archivo de mapa si existe
        if route.file_path and os.path.exists(route.file_path):
            try:
                os.remove(route.file_path)
            except:
                pass
        
        # Eliminar el archivo GPX si existe
        if route.gpx_path and os.path.exists(route.gpx_path):
            try:
                os.remove(route.gpx_path)
            except:
                pass
        
        # Eliminar registro de la base de datos
        db.session.delete(route)
        db.session.commit()
        
        flash('Ruta eliminada correctamente.', 'success')
        return redirect(url_for('manage_routes'))

    # ==================== RUTAS DE TÉCNICO ====================
    
    @app.route('/technician/dashboard')
    @technician_required
    def technician_dashboard():
        users = User.query.filter_by(active=True).order_by(User.role, User.last_name).all()
        return render_template('technician/dashboard.html', users=users)

    @app.route('/technician/change_password/<int:user_id>', methods=['GET', 'POST'])
    @technician_required
    def change_user_password(user_id):
        user = User.query.get_or_404(user_id)
        
        if request.method == 'POST':
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')
            
            if new_password != confirm_password:
                flash('Las contraseñas no coinciden.', 'danger')
                return redirect(url_for('change_user_password', user_id=user_id))
            
            user.set_password(new_password)
            db.session.commit()
            
            flash(f'Contraseña de {user.username} actualizada correctamente.', 'success')
            return redirect(url_for('technician_dashboard'))
        
        return render_template('technician/change_password.html', user=user)

    @app.route('/technician/toggle_user/<int:user_id>', methods=['POST'])
    @technician_required
    def toggle_user_status(user_id):
        user = User.query.get_or_404(user_id)
        
        # No permitir ocultar administradores
        if user.is_admin:
            flash('No puedes ocultar usuarios administradores.', 'danger')
            return redirect(url_for('technician_dashboard'))
        
        user.active = not user.active
        db.session.commit()
        
        status = 'activado' if user.active else 'ocultado'
        flash(f'Usuario {user.username} {status} correctamente.', 'success')
        return redirect(url_for('technician_dashboard'))

    # ==================== RUTAS DE COORDINADOR ====================
    
    @app.route('/coordinator/dashboard')
    @coordinator_required
    def coordinator_dashboard():
        # Métricas
        total_routes = Route.query.filter_by(active=True).count()
        completed_routes = RouteCompletion.query.filter_by(status='completed').count()
        in_progress_routes = RouteCompletion.query.filter_by(status='in_progress').count()
        total_drivers = User.query.filter_by(role='driver', active=True).count()
        
        # Rutas recientes
        recent_completions = RouteCompletion.query.order_by(RouteCompletion.completed_at.desc()).limit(10).all()
        
        return render_template('coordinator/dashboard.html',
                             total_routes=total_routes,
                             completed_routes=completed_routes,
                             in_progress_routes=in_progress_routes,
                             total_drivers=total_drivers,
                             recent_completions=recent_completions)

    @app.route('/coordinator/routes')
    @coordinator_required
    def coordinator_view_routes():
        routes = Route.query.filter_by(active=True).order_by(Route.created_at.desc()).all()
        return render_template('coordinator/routes.html', routes=routes)

    @app.route('/coordinator/view_route/<int:route_id>')
    @coordinator_required
    def coordinator_view_route(route_id):
        route = Route.query.get_or_404(route_id)
        
        try:
            with open(route.file_path, 'r', encoding='utf-8') as f:
                map_html = f.read()
        except Exception as e:
            map_html = "<p>No se pudo cargar el mapa</p>"
        
        completions = RouteCompletion.query.filter_by(route_id=route.id).order_by(RouteCompletion.completed_at.desc()).all()
        
        return render_template('coordinator/view_route.html',
                             route=route,
                             map_html=map_html,
                             completions=completions)

    # ==================== RUTAS DE CHOFER ====================
    
    @app.route('/driver/dashboard')
    @driver_required
    def driver_dashboard():
        try:
            print(f"DEBUG: Accediendo a driver_dashboard para usuario {current_user.username}")
            
            driver_info = DriverInfo.query.filter_by(user_id=current_user.id).first()
            print(f"DEBUG: Driver info encontrado: {driver_info is not None}")
            
            # Obtener vehículos disponibles (no solo el asignado)
            available_vehicles = Vehicle.query.filter_by(active=True).all()
            print(f"DEBUG: Vehículos disponibles: {len(available_vehicles)}")
            
            available_routes = Route.query.filter_by(active=True).order_by(Route.created_at.desc()).all()
            print(f"DEBUG: Rutas disponibles: {len(available_routes)}")
            
            recent_completions = RouteCompletion.query.filter_by(
                driver_id=current_user.id
            ).order_by(RouteCompletion.completed_at.desc()).limit(5).all()
            print(f"DEBUG: Completions recientes: {len(recent_completions)}")
            
            in_progress = RouteCompletion.query.filter_by(
                driver_id=current_user.id, 
                status='in_progress'
            ).first()
            print(f"DEBUG: Ruta en progreso: {in_progress is not None}")
            
            return render_template('driver/dashboard.html',
                                 driver_info=driver_info,
                                 available_vehicles=available_vehicles,
                                 available_routes=available_routes,
                                 recent_completions=recent_completions,
                                 in_progress=in_progress)
        except Exception as e:
            print(f"ERROR en driver_dashboard: {e}")
            import traceback
            traceback.print_exc()
            flash(f'Error al cargar el dashboard: {str(e)}', 'danger')
            return redirect(url_for('login'))

    @app.route('/driver/route_history')
    @driver_required
    def driver_route_history():
        """Historial de rutas completadas por el chofer"""
        try:
            completions = RouteCompletion.query.filter_by(
                driver_id=current_user.id
            ).order_by(RouteCompletion.completed_at.desc()).all()
            
            return render_template('driver/route_history.html', completions=completions)
        except Exception as e:
            print(f"ERROR en driver_route_history: {e}")
            flash(f'Error al cargar el historial: {str(e)}', 'danger')
            return redirect(url_for('driver_dashboard'))

    @app.route('/driver/view_route/<int:route_id>')
    @driver_required
    def driver_view_route(route_id):
        """Ver una ruta específica"""
        try:
            route = Route.query.get_or_404(route_id)
            
            # Leer el contenido del archivo HTML del mapa
            try:
                with open(route.file_path, 'r', encoding='utf-8') as f:
                    map_html = f.read()
            except Exception as e:
                map_html = "<p>No se pudo cargar el mapa</p>"
            
            # Verificar si hay una ruta en progreso
            in_progress = RouteCompletion.query.filter_by(
                driver_id=current_user.id, 
                status='in_progress'
            ).first()
            
            # Obtener vehículos disponibles
            available_vehicles = Vehicle.query.filter_by(active=True).all()
            
            return render_template('driver/view_route.html',
                                 route=route,
                                 map_html=map_html,
                                 in_progress=in_progress,
                                 available_vehicles=available_vehicles)
        except Exception as e:
            print(f"ERROR en driver_view_route: {e}")
            flash(f'Error al cargar la ruta: {str(e)}', 'danger')
            return redirect(url_for('driver_dashboard'))

    @app.route('/driver/start_route/<int:route_id>', methods=['POST'])
    @driver_required
    def driver_start_route(route_id):
        """Iniciar una ruta con un vehículo seleccionado"""
        try:
            # Verificar si el chofer ya tiene una ruta en progreso
            existing_route = RouteCompletion.query.filter_by(
                driver_id=current_user.id, 
                status='in_progress'
            ).first()
            
            if existing_route:
                return jsonify({
                    'success': False, 
                    'message': 'Ya tienes una ruta en progreso. Debes completarla o cancelarla antes de iniciar otra.'
                }), 400
            
            # Verificar que la ruta exista
            route = Route.query.get_or_404(route_id)
            
            # Obtener el vehículo seleccionado del request
            data = request.json
            vehicle_id = data.get('vehicle_id') if data else None
            
            if not vehicle_id:
                return jsonify({'success': False, 'message': 'Debes seleccionar un vehículo'}), 400
            
            # Verificar que el vehículo exista
            vehicle = Vehicle.query.get(vehicle_id)
            if not vehicle:
                return jsonify({'success': False, 'message': 'El vehículo seleccionado no existe'}), 400
            
            # Crear nuevo registro de completado de ruta
            new_completion = RouteCompletion(
                route_id=route.id,
                driver_id=current_user.id,
                vehicle_id=vehicle.id,
                started_at=datetime.utcnow(),
                status='in_progress'
            )
            
            db.session.add(new_completion)
            db.session.commit()
            
            return jsonify({
                'success': True, 
                'message': f'Has iniciado la ruta {route.name}',
                'completion_id': new_completion.id
            })
            
        except Exception as e:
            print(f"ERROR en driver_start_route: {e}")
            return jsonify({'success': False, 'message': f'Error al iniciar la ruta: {str(e)}'}), 500

    @app.route('/driver/navigate/<int:route_id>')
    @driver_required
    def driver_navigate(route_id):
        """Navegación GPS para una ruta"""
        try:
            route = Route.query.get_or_404(route_id)
            
            # Verificar si hay una ruta en progreso para este chofer y esta ruta
            in_progress = RouteCompletion.query.filter_by(
                driver_id=current_user.id,
                route_id=route.id,
                status='in_progress'
            ).first()
            
            if not in_progress:
                flash('Debes iniciar la ruta antes de navegar.', 'warning')
                return redirect(url_for('driver_view_route', route_id=route_id))
            
            return render_template('driver/navigate.html',
                                 route=route,
                                 completion=in_progress)
        except Exception as e:
            print(f"ERROR en driver_navigate: {e}")
            flash(f'Error al cargar la navegación: {str(e)}', 'danger')
            return redirect(url_for('driver_dashboard'))

    @app.route('/driver/update_route_progress/<int:completion_id>', methods=['POST'])
    @driver_required
    def driver_update_route_progress(completion_id):
        """Actualizar el progreso de una ruta en navegación"""
        try:
            print(f"DEBUG: Actualizando progreso para completion_id: {completion_id}")
            
            # Obtener el registro de completado
            completion = RouteCompletion.query.get_or_404(completion_id)
            
            # Verificar que el chofer sea el propietario de este registro
            if completion.driver_id != current_user.id:
                print(f"DEBUG: Usuario {current_user.id} no autorizado para completion {completion_id}")
                return jsonify({'success': False, 'message': 'No tienes permiso para actualizar este registro'}), 403
            
            # Verificar que la ruta esté en progreso
            if completion.status != 'in_progress':
                print(f"DEBUG: Completion {completion_id} no está en progreso, estado: {completion.status}")
                return jsonify({'success': False, 'message': 'Esta ruta no está en progreso'}), 400
            
            # Obtener datos de posición del cuerpo de la solicitud
            data = request.json
            if not data or 'position' not in data:
                print("DEBUG: No se recibieron datos de posición")
                return jsonify({'success': False, 'message': 'Datos de posición requeridos'}), 400
            
            position = data['position']
            print(f"DEBUG: Posición recibida: {position}")
            
            # Actualizar datos de seguimiento
            if completion.track_data:
                track_data = json.loads(completion.track_data)
                track_data.append({
                    'lat': position['lat'],
                    'lng': position['lng'],
                    'timestamp': datetime.utcnow().isoformat()
                })
            else:
                track_data = [{
                    'lat': position['lat'],
                    'lng': position['lng'],
                    'timestamp': datetime.utcnow().isoformat()
                }]
            
            completion.track_data = json.dumps(track_data)
            db.session.commit()
            
            return jsonify({'success': True, 'message': 'Posición actualizada'})
            
        except Exception as e:
            print(f"ERROR en driver_update_route_progress: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'success': False, 'message': f'Error al actualizar progreso: {str(e)}'}), 500

    @app.route('/driver/complete_route/<int:completion_id>', methods=['POST'])
    @driver_required
    def driver_complete_route(completion_id):
        """Completar una ruta"""
        try:
            # Obtener el registro de completado
            completion = RouteCompletion.query.get_or_404(completion_id)
            
            # Verificar que el chofer sea el propietario de este registro
            if completion.driver_id != current_user.id:
                return jsonify({'success': False, 'message': 'No tienes permiso para actualizar este registro'}), 403
            
            # Verificar que la ruta esté en progreso
            if completion.status != 'in_progress':
                return jsonify({'success': False, 'message': 'Esta ruta no está en progreso'}), 400
            
            # Actualizar estado
            completion.status = 'completed'
            completion.completed_at = datetime.utcnow()
            
            # Obtener notas opcionales
            data = request.json
            if data and 'notes' in data:
                completion.notes = data['notes']
            
            db.session.commit()
            
            return jsonify({
                'success': True, 
                'message': f'Ruta completada exitosamente'
            })
            
        except Exception as e:
            print(f"ERROR en driver_complete_route: {e}")
            return jsonify({'success': False, 'message': f'Error al completar ruta: {str(e)}'}), 500

    @app.route('/driver/cancel_route/<int:completion_id>', methods=['POST'])
    @driver_required
    def driver_cancel_route(completion_id):
        """Cancelar una ruta"""
        try:
            # Obtener el registro de completado
            completion = RouteCompletion.query.get_or_404(completion_id)
            
            # Verificar que el chofer sea el propietario de este registro
            if completion.driver_id != current_user.id:
                return jsonify({'success': False, 'message': 'No tienes permiso para actualizar este registro'}), 403
            
            # Verificar que la ruta esté en progreso
            if completion.status != 'in_progress':
                return jsonify({'success': False, 'message': 'Esta ruta no está en progreso'}), 400
            
            # Actualizar estado
            completion.status = 'canceled'
            
            # Obtener razón opcional
            data = request.json
            if data and 'reason' in data:
                completion.notes = f"Cancelado: {data['reason']}"
            
            db.session.commit()
            
            return jsonify({
                'success': True, 
                'message': f'Ruta cancelada'
            })
            
        except Exception as e:
            print(f"ERROR en driver_cancel_route: {e}")
            return jsonify({'success': False, 'message': f'Error al cancelar ruta: {str(e)}'}), 500

    # ==================== UTILIDADES ====================
    
    @app.route('/routes/<path:filename>')
    def route_files(filename):
        return send_from_directory('static/routes', filename)

    @app.route('/uploads/<path:filename>')
    def uploaded_files(filename):
        return send_from_directory('uploads', filename)

    @app.route('/reset_database')
    def reset_database():
        """SOLO PARA DESARROLLO - Resetea la base de datos"""
        if app.debug:
            db.drop_all()
            db.create_all()
            
            # Crear usuarios por defecto
            admin = User(
                username='admin',
                email='admin@example.com',
                first_name='Administrador',
                last_name='Sistema',
                cedula='000000001',
                role='admin'
            )
            admin.set_password('admin123')
            
            tech = User(
                username='tecnico',
                email='tecnico@example.com',
                first_name='Técnico',
                last_name='Sistema',
                cedula='000000002',
                role='technician'
            )
            tech.set_password('tecnico123')
            
            coord = User(
                username='coordinador',
                email='coordinador@example.com',
                first_name='Coordinador',
                last_name='Sistema',
                cedula='000000003',
                role='coordinator'
            )
            coord.set_password('coordinador123')
            
            driver = User(
                username='chofer',
                email='chofer@example.com',
                first_name='Chofer',
                last_name='Prueba',
                cedula='000000004',
                role='driver'
            )
            driver.set_password('chofer123')
            
            db.session.add_all([admin, tech, coord, driver])
            db.session.flush()
            
            # Crear información de chofer
            driver_info = DriverInfo(
                user_id=driver.id,
                license_type='B'
            )
            db.session.add(driver_info)
            
            db.session.commit()
            
            flash('Base de datos reseteada correctamente. Usuarios creados: admin/admin123, tecnico/tecnico123, coordinador/coordinador123, chofer/chofer123', 'success')
        else:
            flash('Reset de base de datos solo disponible en modo debug.', 'danger')
        
        return redirect(url_for('login'))

    @app.route('/debug_users')
    def debug_users():
        """SOLO PARA DESARROLLO - Muestra los usuarios en la base de datos"""
        if app.debug:
            users = User.query.all()
            user_list = []
            for user in users:
                user_list.append({
                    'username': user.username,
                    'role': user.role,
                    'active': user.active,
                    'id': user.id
                })
            return jsonify({
                'total_users': len(users),
                'users': user_list
            })
        else:
            return jsonify({'error': 'Solo disponible en modo debug'})

    @app.route('/test')
    def test():
        """Ruta de prueba simple"""
        return jsonify({
            'status': 'OK',
            'message': 'El servidor está funcionando correctamente',
            'timestamp': datetime.now().isoformat()
        })

    @app.route('/debug_routes')
    def debug_routes():
        """SOLO PARA DESARROLLO - Muestra todas las rutas disponibles"""
        if app.debug:
            from flask import url_for
            routes_info = []
            for rule in app.url_map.iter_rules():
                routes_info.append({
                    'endpoint': rule.endpoint,
                    'methods': list(rule.methods),
                    'rule': str(rule)
                })
            return jsonify({
                'total_routes': len(routes_info),
                'routes': sorted(routes_info, key=lambda x: x['endpoint'])
            })
        else:
            return jsonify({'error': 'Solo disponible en modo debug'})
    

    # Crear base de datos y usuarios por defecto
    with app.app_context():
        db.create_all()
        
        # Verificar si ya existen usuarios, si no, crearlos
        if User.query.count() == 0:
            print("Creando usuarios por defecto...")
            
            # Crear usuarios por defecto
            admin = User(
                username='admin',
                email='admin@example.com',
                first_name='Administrador',
                last_name='Sistema',
                cedula='000000001',
                role='admin'
            )
            admin.set_password('admin123')
            
            tech = User(
                username='tecnico',
                email='tecnico@example.com',
                first_name='Técnico',
                last_name='Sistema',
                cedula='000000002',
                role='technician'
            )
            tech.set_password('tecnico123')
            
            coord = User(
                username='coordinador',
                email='coordinador@example.com',
                first_name='Coordinador',
                last_name='Sistema',
                cedula='000000003',
                role='coordinator'
            )
            coord.set_password('coordinador123')
            
            driver = User(
                username='chofer',
                email='chofer@example.com',
                first_name='Chofer',
                last_name='Prueba',
                cedula='000000004',
                role='driver'
            )
            driver.set_password('chofer123')
            
            db.session.add_all([admin, tech, coord, driver])
            db.session.flush()
            
            # Crear información de chofer
            driver_info = DriverInfo(
                user_id=driver.id,
                license_type='B'
            )
            db.session.add(driver_info)
            
            db.session.commit()
            print("Usuarios por defecto creados correctamente:")
            print("- admin / admin123 (Administrador)")
            print("- tecnico / tecnico123 (Técnico)")
            print("- coordinador / coordinador123 (Coordinador)")
            print("- chofer / chofer123 (Chofer)")
        else:
            print(f"Base de datos ya inicializada con {User.query.count()} usuarios")
    
    return app

# Punto de entrada
if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)