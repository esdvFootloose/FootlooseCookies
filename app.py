from flask import Flask, request, jsonify, abort, redirect, url_for, Response
from werkzeug.contrib.fixers import ProxyFix
from flask_sqlalchemy import SQLAlchemy
import yaml
import requests
from functools import wraps
import random
from datetime import datetime
from pytz import timezone
import binascii
import os
from flask_migrate import Migrate
from secret import secret_key
from sqlalchemy.sql import func
from subprocess import check_output
from flask_selfdoc import Autodoc

app = Flask(__name__)
app.secret_key = secret_key
app.wsgi_app = ProxyFix(app.wsgi_app)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['FOOKIE_CONFIG_FILE'] = "config.yaml"
app.jinja_env.add_extension('jinja2.ext.do')
db = SQLAlchemy(app)
migrate = Migrate(app, db)
auto = Autodoc(app)

configs = {}

## DB models
class Rating(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rating = db.Column(db.Integer, nullable=False) #0-5
    user = db.Column(db.String(64), nullable=False)
    cookie = db.Column(db.Integer, db.ForeignKey('cookie.id'), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)
    session = db.Column(db.Integer, db.ForeignKey('session.id'), nullable=False)

class Cookie(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False)
    img = db.Column(db.String(512), nullable=True)
    ratings = db.relationship('Rating', backref='Cookie', lazy=True)
    sessions = db.relationship('Session', backref='Cookie', lazy=True)

    def to_dict(self):
        return {
            'id'   : self.id,
            'name' : self.name,
            'img'  : self.img,
        }


class Session(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(8), nullable=False, unique=True)
    user = db.Column(db.String(64), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)
    ratings = db.relationship('Rating', backref='Session', lazy=True)
    cookie = db.Column(db.Integer, db.ForeignKey('cookie.id'), nullable=False)

@app.before_first_request
def init():
    global configs
    db.create_all()
    with open(app.config['FOOKIE_CONFIG_FILE'], "r") as stream:
        configs = yaml.load(stream)


## util funcs
def validate_img_url(url):
    try:
        r = requests.get(url)
    except:
        return False
    if r.status_code != 200:
        return False
    if r.headers['Content-Type'].split('/')[0].lower() != "image":
        return False

    return True

def validate_session(session):
    if datetime.now().timestamp() > session.timestamp.timestamp() + configs['sessiontimeout']:
        return False
    return True

def generate_token():
    #TODO: make better, too simple
    return binascii.hexlify(os.urandom(4)).decode()

def admin_required(func):
    @wraps(func)
    def func_wrapper(*args, **kwargs):
        fookie = request.headers.get('FOOKIE', None)
        if fookie is None or fookie not in configs['adminkeys']:
            return abort(403)
        return func(*args, **kwargs)
    return func_wrapper

def login_required(func):
    @wraps(func)
    def func_wrapper(*args, **kwargs):
        user = request.headers.get('USER', None)
        if user is None:
            return abort(403)
        return func(*args, **kwargs)
    return func_wrapper

## end points
@app.route('/')
def index():
    return 'welcome'

### cookies endpoints

@app.route('/cookies/')
@app.route('/cookies/list/')
@auto.doc()
def cookie_list():
    """lists all cookies with parameters as list of dicts"""
    return jsonify([c.to_dict() for c in Cookie.query.all()])

@app.route('/cookies/suggest/')
@auto.doc()
@login_required
def cookie_suggest():
    user = request.headers.get('USER')
    try:
        selected_cookie = random.choice(Cookie.query.all())
    except:
        return abort(404)

    token = generate_token()

    new_session = Session(token=token, user=user, cookie=selected_cookie.id, timestamp=datetime.now(timezone('Europe/Amsterdam')))

    db.session.add(new_session)
    db.session.commit()

    response = Response(selected_cookie.name)
    response.headers['img'] = selected_cookie.img
    response.headers['session_token'] = token

    return response

@app.route('/cookies/add/', methods=['PUT'])
@auto.doc()
@admin_required
@auto.doc()
def cookie_add():
    """add cookie, formdata: img (image url) and name (name of cookie), admin header auth required"""
    if 'img' not in request.form or 'name' not in request.form:
        return abort(400)

    if not validate_img_url(request.form['img']):
        return abort(400)

    if Cookie.query.filter_by(name=request.form['name']).count() != 0:
        return abort(400)

    new_cookie = Cookie(name=request.form['name'], img=request.form['img'])
    db.session.add(new_cookie)
    db.session.commit()

    return "OK"

@app.route('/cookies/', methods=['DELETE'])
@auto.doc()
@admin_required
def cookie_admin():
    """various actions on cookies. for example delete: formdata: name, admin header auth required"""

    #TODO: also  support deletion on cookie by id
    if Cookie.query.filter_by(name=request.form['name']).count() != 1:
        return abort(404)

    my_cookie = Cookie.query.filter_by(name=request.form['name']).first()

    if request.method == "DELETE":
        db.session.delete(my_cookie)
        db.session.commit()

    return "OK"

@app.route('/cookies/rate/<token>/', methods=['PUT'])
@auto.doc()
@login_required
def cookie_rating(token):
    user = request.headers.get('USER')
    if 'rating' not in request.form:
        return abort(400)

    try:
        rating = int(request.form['rating'])
        if rating < 0 or rating > 5:
            return abort(400)
    except:
        return abort(400)

    if Session.query.filter_by(token=token).count() != 1:
        return abort(404)

    my_session = Session.query.filter_by(token=token).first()

    if not validate_session(my_session):
        return abort(403)

    ## if only session owner can rate enable this
    # if Rating.query.filter_by(user=user, session = my_session.id).count() != 0:
    #     return abort(403)

    db.session.add(Rating(rating=rating, session=my_session.id, user=user, cookie=my_session.cookie, timestamp=datetime.now(timezone('Europe/Amsterdam'))))
    db.session.commit()

    return "OK"

@app.route('/cookies/<int:cookie_id>/stats/')
@auto.doc()
@login_required
def cookie_stats(cookie_id):
    cookie = Cookie.query.filter_by(id=cookie_id).first_or_404()

    return jsonify({
        'cookie' : [cookie.name, cookie.img],
        'numrating' : Rating.query.filter_by(cookie=cookie.id).count(),
        'avgrating' : db.session.query(func.avg(Rating.rating)).filter(Rating.cookie == cookie.id).first()[0]
    })

### session endpoints
@app.route('/session/<token>/stats/')
@auto.doc()
@login_required
def session_stats(token):
    # user = request.headers.get('USER')
    session = Session.query.filter_by(token=token).first_or_404()
    cookie = Cookie.query.filter_by(id=session.cookie).first_or_404()

    return jsonify({
        'cookie' : [cookie.name, cookie.img],
        'numrating' : Rating.query.filter_by(session=session.id).count(),
        'avgrating' : db.session.query(func.avg(Rating.rating)).filter(Rating.session == session.id).first()[0]
    })

### util endpoints
@app.route('/docs/')
def documentation():
    # return auto.html()
    docs = auto.generate()
    for ep in docs:
        ep['args'] = list(ep['args'])
    return jsonify(docs)

### administrative
@app.route('/admin/traffic/<key>/')
def admin_traffic(key):
    if key not in configs['adminkeys']:
        return abort(403)

    with open(os.devnull, 'w') as devnull:
        if app.config['DEBUG']:
            answer = check_output(['ssh', 'footloosedirectflask', 'sudo', 'generate_traffic_report'], stderr=devnull).decode().strip()
        else:
            answer = check_output(['sudo', 'generate_traffic_report'], stderr=devnull).decode().strip()

    return redirect(answer, code=302)