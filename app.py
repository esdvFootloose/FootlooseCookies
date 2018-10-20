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

app = Flask(__name__)
app.secret_key = 'FootlooseIsAwesome'
app.wsgi_app = ProxyFix(app.wsgi_app)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.jinja_env.add_extension('jinja2.ext.do')
db = SQLAlchemy(app)
migrate = Migrate(app, db)

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
    with open("config.yaml", "r") as stream:
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

## end points
@app.route('/')
def index():
    return 'welcome'

@app.route('/cookies/list/')
def cookie_list():
    return jsonify([(c.name, c.img) for c in Cookie.query.all()])

@app.route('/cookies/suggest/')
def cookie_suggest():
    try:
        selected_cookie = random.choice(Cookie.query.all())
    except:
        return abort(404)

    token = generate_token()

    new_session = Session(token=token, user="No user recorded", cookie=selected_cookie.id, timestamp=datetime.now(timezone('Europe/Amsterdam')))

    db.session.add(new_session)
    db.session.commit()

    response = Response(selected_cookie.name)
    response.headers['img'] = selected_cookie.img
    response.headers['session_token'] = token

    return response

@app.route('/cookies/add/', methods=['PUT'])
@admin_required
def cookie_add():
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
@admin_required
def cookie_admin():

    if Cookie.query.filter_by(name=request.form['name']).count() != 1:
        return abort(404)

    my_cookie = Cookie.query.filter_by(name=request.form['name']).first()

    if request.method == "DELETE":
        db.session.delete(my_cookie)
        db.session.commit()

    return "OK"

@app.route('/cookies/rate/<token>/', methods=['PUT'])
def cookie_rating(token):
    if 'user' not in request.form or 'rating' not in request.form:
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

    if Rating.query.filter_by(user= request.form['user'], session = my_session.id).count() != 0:
        return abort(403)

    db.session.add(Rating(rating=rating, session=my_session.id, user=request.form['user'], cookie=my_session.cookie, timestamp=datetime.now(timezone('Europe/Amsterdam'))))
    db.session.commit()

    return "OK"