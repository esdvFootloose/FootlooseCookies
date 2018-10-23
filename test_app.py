import os
import tempfile
import pytest
import app
import json

@pytest.fixture
def client():
    db_fd, dbtmpfile =  tempfile.mkstemp()
    app.app.config['SQLALCHEMY_DATABASE_URI'] = "sqlite:///" + dbtmpfile
    config_fd, app.app.config['FOOKIE_CONFIG_FILE'] = tempfile.mkstemp()

    app.app.config['TESTING'] = True

    client = app.app.test_client()

    with open(app.app.config['FOOKIE_CONFIG_FILE'], 'w') as stream:
        stream.write("""
adminkeys:
  - FRANK

sessiontimeout: 3600""")

    with app.app.app_context():
        app.init()

    yield client

    os.close(db_fd)
    os.unlink(dbtmpfile)
    os.close(config_fd)
    os.unlink(app.app.config['FOOKIE_CONFIG_FILE'])



def test_cookie_list_empty(client):

    data = json.loads(client.get("/cookies/").get_data(as_text=True))
    assert data == []
    data = json.loads(client.get("/cookies/list/").get_data(as_text=True))
    assert data == []

def test_cookie_add(client):
    name = "delicious test cookie"
    img = "https://images-gmi-pmc.edge-generalmills.com/087d17eb-500e-4b26-abd1-4f9ffa96a2c6.jpg"
    cookie = app.Cookie(name=name, img=img, id=1)

    #not possible to add without admin auth
    r = client.put('/cookies/add/',
                data={'img' : img, 'name' : name})
    assert r.status_code == 403

    #normally add cookie
    r = client.put('/cookies/add/',
                data={'img' : img, 'name' : name},
                headers={'FOOKIE' : 'FRANK'})
    assert r.status_code == 200

    #is it in the list
    data = json.loads(client.get("/cookies/").get_data(as_text=True))
    assert type(data) == list
    assert len(data) == 1
    assert data[0] == cookie.to_dict()

    #not possible to add duplicate cookie
    r = client.put('/cookies/add/',
                data={'img' : img, 'name' : name},
                headers={'FOOKIE' : 'FRANK'})
    assert r.status_code == 400

    # not possible to add with non img link
    r = client.put('/cookies/add/',
                data={'img' : "https://www.google.nl/", 'name' : name},
                headers={'FOOKIE' : 'FRANK'})
    assert r.status_code == 400


def test_cookie_delete(client):
    name = "delicious test cookie"
    img = "https://images-gmi-pmc.edge-generalmills.com/087d17eb-500e-4b26-abd1-4f9ffa96a2c6.jpg"

    #input cookie in test db
    r = client.put('/cookies/add/',
                data={'img' : img, 'name' : name},
                headers={'FOOKIE' : 'FRANK'})
    assert r.status_code == 200

    #not possible to delete without admin auth
    r = client.delete('/cookies/',
                      data={'name' : name})
    assert r.status_code == 403

    #not possible to delete non existing cookie
    r = client.delete('/cookies/',
                      data={'name': name + "WRONG"},
                      headers={'FOOKIE': 'FRANK'})
    assert r.status_code == 404

    #delete cookie, list is empty again
    r = client.delete('/cookies/',
                      data={'name': name},
                      headers={'FOOKIE': 'FRANK'})
    assert r.status_code == 200
    assert r.data.decode() == "OK"

    r = client.get('/cookies/')
    data = json.loads(client.get("/cookies/").get_data(as_text=True))
    assert data == []