#!/usr/bin/env python2.7


from flask import Flask, render_template, request, redirect, url_for
from flask import flash, jsonify


# Database imports
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database_setup import Base, Restaurant, MenuItem, User

# Login imports
from flask import session as login_session
import random
import string

# Oauth2 imports
from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError
import httplib2
import json
from flask import make_response
import requests

# Create client Id
CLIENT_ID = json.loads(
    open('secrets.json', 'r').read())['web']['client_id']
APPLICATION_NAME = "Item Catalog"


# Use the Flask framework
app = Flask(__name__)

# Create the database engine
engine = create_engine(
    'sqlite:///restaurantmenuwithusers.db?check_same_thread=False')
Base.metadata.bind = engine

# Create the database session to apply CRUD
DBSession = sessionmaker(bind=engine)
session = DBSession()


# User Helper Functions

def createUser(login_session):
    """ This method creates a new user taking its info from the
        login session and save it to the database """

    newUser = User(name=login_session['username'], email=login_session[
                   'email'], picture=login_session['picture'])

    session.add(newUser)
    session.commit()
    user = session.query(User).filter_by(
        email=login_session['email']).one()

    return user.id


def getUserInfo(user_id):
    """ This method gets the info of a user """

    user = session.query(User).filter_by(
        id=user_id).one()

    return user


def getUserID(email):
    """ This method returns the user's Id """

    try:
        user = session.query(User).filter_by(
            email=email).one()

        return user.id
    except Exception:
        return None


def checkAuthorization(loginSession, restaurant):
    """ This method checks if a user is authorized to edit
    or delete a restaurant or an item """

    if restaurant.user_id != login_session['user_id']:
        return True
    else:
        return False


# Login page
# Create anti-forgery state token
@app.route('/login')
def showLogin():
    """ This method shows the login page to the user """

    # Generate random state
    state = ''.join(random.choice(string.ascii_uppercase + string.digits)
                    for x in xrange(32))

    login_session['state'] = state
    return render_template('login.html', STATE=state)


# Gconnect route
@app.route('/gconnect', methods=['POST'])
def gconnect():
    """ This method allows the user to login using google plus """

    # Validate state token
    # The token sent from the user should be
    # the same as the token sent from the server
    if request.args.get('state') != login_session['state']:
        # The tokens is not match
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    # Obtain authorization code
    code = request.data

    try:
        # Upgrade the authorization code into a credentials object
        oauth_flow = flow_from_clientsecrets('client_secrets.json', scope='')
        oauth_flow.redirect_uri = 'postmessage'
        credentials = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        response = make_response(
            json.dumps('Failed to upgrade the authorization code.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Check that the access token is valid.
    access_token = credentials.access_token
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s'
           % access_token)
    h = httplib2.Http()
    result = json.loads(h.request(url, 'GET')[1])
    # If there was an error in the access token info, abort.
    if result.get('error') is not None:
        response = make_response(json.dumps(result.get('error')), 500)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is used for the intended user.
    gplus_id = credentials.id_token['sub']
    if result['user_id'] != gplus_id:
        response = make_response(
            json.dumps("Token's user ID doesn't match given user ID."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is valid for this app.
    if result['issued_to'] != CLIENT_ID:
        response = make_response(
            json.dumps("Token's client ID does not match app's."), 401)
        print "Token's client ID does not match app's."
        response.headers['Content-Type'] = 'application/json'
        return response

    stored_access_token = login_session.get('access_token')
    stored_gplus_id = login_session.get('gplus_id')

    if stored_access_token is not None and gplus_id == stored_gplus_id:
        response = make_response(
            json.dumps('Current user is already connected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Store the access token in the session for later use.
    login_session['access_token'] = credentials.access_token
    login_session['gplus_id'] = gplus_id

    # Get user info
    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': credentials.access_token, 'alt': 'json'}
    answer = requests.get(userinfo_url, params=params)

    data = answer.json()

    login_session['username'] = data['name']
    login_session['picture'] = data['picture']
    login_session['email'] = data['email']
    # ADD PROVIDER TO LOGIN SESSION
    login_session['provider'] = 'google'

    # see if user exists, if it doesn't make a new one
    user_id = getUserID(data["email"])
    if not user_id:
        user_id = createUser(login_session)

    login_session['user_id'] = user_id

    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ''' " style = "width: 300px; height: 300px;
                    border-radius: 150px;-webkit-border-radius: 150px;
                    -moz-border-radius: 150px;"> '''
    flash("you are now logged in as %s" % login_session['username'])
    return output


# Disconnect route => Logout
@app.route('/gdisconnect')
def gdisconnect():
    """ This method disconnects a connected user
    and resets the login session """

    # only disconnect a connected user
    credentials = login_session.get('credentials')

    if credentials is None:
        response = make_response(
            json.dumps('Current user not connected.'), 401)
        response.headers['Content-type'] = 'application/json'
        return response
    # execute HTTP GET request to revoke current token
    access_token = credentials.access_token
    url = 'https://accounts.google.com/o/oauth2/revoke?token=%s' % access_token  # noqa
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]

    if result['status'] == '200':
        # reset the user's session
        del login_session['credentials']
        del login_session['gplus_id']
        del login_session['username']
        del login_session['email']
        del login_session['picture']

        response = make_response(json.dumps('Successfully disconnected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response

    else:
        # token given is invalid
        response = make_response(
            json.dumps('Failed to revoke token for given user.'), 400)
        response.headers['Content-Type'] = 'application/json'
        return response


# Get all restaurants route
@app.route('/', methods=['GET'])
@app.route('/restaurants')
def showRestaurants():
    """ This method should retrieve all restaurants
    from the database and show them to the users """

    restaurants = session.query(Restaurant)
    return render_template('restaurants.html', restaurants=restaurants)


# Create restaurant route
@app.route(
    '/restaurant/new',
    methods=['GET', 'POST'])
def newRestaurant():
    """ This method should Create a new restaurant
    and save it to the database """

    if 'username' not in login_session:
        return redirect('/login')

    if request.method == 'POST':
        newRestaurant = Restaurant(
            name=request.form['name'])

        session.add(newRestaurant)
        session.commit()
        flash(
            'Restaurant " %s " is Successfully Created!'
            % newRestaurant.name)
        return redirect(url_for('showRestaurants'))
    else:
        return render_template('newRestaurant.html')


# Edit restaurant route
@app.route(
    '/restaurant/<int:restaurant_id>/edit',
    methods=['GET', 'POST'])
def editRestaurant(restaurant_id):
    """ This method should Update or Edit a restaurant
    and save the changes to the database """

    if 'username' not in login_session:
        return redirect('/login')

    editedRestaurant = session.query(Restaurant).filter_by(
        id=restaurant_id).one()

    # Check if the user is authorized or not
    if checkAuthorization(login_session, editedRestaurant):
        return """<script>function myFunction()
                    {alert('You are not authorized to edit this restaurant.
                     Please create your own restaurant in order to edit.');}
                    </script><body onload='myFunction()''>"""

    if request.method == 'POST':
        if request.form['name']:
            editedRestaurant.name = request.form['name']
        session.add(editedRestaurant)
        session.commit()

        flash(
            'Restaurant " %s " is Successfully Edited!'
            % editedRestaurant.name)
        return redirect(url_for('showRestaurants'))
    else:
        return render_template(
            'editRestaurant.html', restaurant=editedRestaurant)


# Delete restaurant route
@app.route(
    '/restaurant/<int:restaurant_id>/delete',
    methods=['GET', 'POST', 'Delete'])
def deleteRestaurant(restaurant_id):
    """ This method should Delete a restaurant from the database """

    if 'username' not in login_session:
        return redirect('/login')

    deletedRestaurant = session.query(Restaurant).filter_by(
        id=restaurant_id).one()

    # Check if the user is authorized or not
    if checkAuthorization(login_session, deletedRestaurant):
        return """<script>function myFunction()
                    {alert('You are not authorized to delete this restaurant.
                     Please create your own restaurant in order to delete.');}
                    </script><body onload='myFunction()''>"""

    if request.method == 'POST':
        session.delete(deletedRestaurant)
        session.commit()

        flash(
            'Restaurant " %s " is Successfully Deleted!'
            % deletedRestaurant.name)
        return redirect(url_for('showRestaurants'))
    else:
        return render_template(
            'deleteRestaurant.html', restaurant=deletedRestaurant)


# Show the menu of a restaurant route
@app.route(
    '/restaurant/<int:restaurant_id>/',
    methods=['GET', 'POST'])
@app.route(
    '/restaurant/<int:restaurant_id>/menu/',
    methods=['GET', 'POST'])
def showMenu(restaurant_id):
    """ This method should retrieve all the menu items
    of a restaurants from the database and show them to the users """

    restaurant = session.query(Restaurant).filter_by(
        id=restaurant_id).one()

    items = session.query(MenuItem).filter_by(
        restaurant_id=restaurant_id).all()

    return render_template('menu.html', items=items, restaurant=restaurant)


# Create new menu item route
@app.route(
    '/restaurant/<int:restaurant_id>/menu/new',
    methods=['GET', 'POST'])
def newMenuItem(restaurant_id):
    """ This method should Create a new menu item for a restaurant
    and save it to the database """

    if 'username' not in login_session:
        return redirect('/login')

    restaurant = session.query(Restaurant).filter_by(
        id=restaurant_id).one()

    # Check if the user is authorized or not
    if checkAuthorization(login_session, restaurant):
        return """<script>function myFunction()
                {alert('You are not authorized to add menu items
                to this restaurant. Please create your own restaurant
                in order to add items.');}
                </script><body onload='myFunction()''>"""

    if request.method == 'POST':
        newItem = MenuItem(
            name=request.form['name'],
            price=request.form['price'],
            description=request.form['description'],
            course=request.form['course'],
            restaurant_id=restaurant_id)
        session.add(newItem)
        session.commit()

        flash('Menu Item " %s " is Successfully Added!' % newItem.name)
        return redirect(url_for('showMenu', restaurant_id=restaurant_id))
    else:
        return render_template(
            'newMenuItem.html', restaurant=restaurant)


# Edit a menu item route
@app.route(
    '/restaurant/<int:restaurant_id>/menu/<int:menu_id>/edit',
    methods=['GET', 'POST', 'PUT'])
def editMenuItem(restaurant_id, menu_id):
    """ This method should Update or Edit a menu item of a restaurant
    and save the changes to the database """

    if 'username' not in login_session:
        return redirect('/login')

    restaurant = session.query(Restaurant).filter_by(
        id=restaurant_id).one()

    # Check if the user is authorized or not
    if checkAuthorization(login_session, restaurant):
        return """<script>function myFunction()
            {alert('You are not authorized to edit menu items
            of this restaurant. Please create your own restaurant
            in order to edit items.');}
            </script><body onload='myFunction()''>"""

    editedItem = session.query(MenuItem).filter_by(
        id=menu_id, restaurant_id=restaurant.id).one()

    if request.method == 'POST':
        editedItem.name = request.form['name']
        editedItem.price = request.form['price']
        editedItem.description = request.form['description']
        editedItem.course = request.form['course']
        session.add(editedItem)
        session.commit()

        flash('Menu Item " %s " is Successfully Edited!' % editedItem.name)
        return redirect(url_for('showMenu', restaurant_id=restaurant_id))
    else:
        return render_template(
            'editMenuItem.html', restaurant=restaurant, item=editedItem)


# Delete a menu item route
@app.route(
    '/restaurant/<int:restaurant_id>/menu/<int:menu_id>/delete',
    methods=['GET', 'POST', 'Delete'])
def deleteMenuItem(restaurant_id, menu_id):
    """ This method should Delete a menu item of a restaurant
    from the database """

    if 'username' not in login_session:
        return redirect('/login')

    restaurant = session.query(Restaurant).filter_by(
        id=restaurant_id).one()

    # Check if the user is authorized or not
    if checkAuthorization(login_session, restaurant):
        return """<script>function myFunction()
                {alert('You are not authorized to delete menu items
                of this restaurant. Please create your own restaurant
                 in order to delete items.');}
                </script><body onload='myFunction()''>"""

    deletedItem = session.query(MenuItem).filter_by(
        id=menu_id, restaurant_id=restaurant.id).one()

    if request.method == 'POST':
        session.delete(deletedItem)
        session.commit()

        flash('Menu Item " %s " is Successfully Deleted!' % deletedItem.name)
        return redirect(url_for('showMenu', restaurant_id=restaurant_id))
    else:
        return render_template(
            'deleteMenuItem.html', restaurant=restaurant, item=deletedItem)


# API Endpoints

# JSON route for all restaurants
@app.route('/restaurants/JSON')
def restaurantsJSON():
    """ Method to provide all restaurants as a JSON object """

    restaurants = session.query(Restaurant)
    return jsonify(Restaurants=[i.serialize for i in restaurants])


# JSON route for a specific restaurant
@app.route('/restaurants/<int:restaurant_id>/JSON')
def restaurantJSON(restaurant_id):
    """ Method to provide a specific restaurant as a JSON object """

    restaurant = session.query(Restaurant).filter_by(
        id=restaurant_id).one()

    return jsonify(Restaurant=restaurant.serialize)


# JSON route for all menu items
@app.route('/restaurant/<int:restaurant_id>/menu/JSON')
def restaurantMenuJSON(restaurant_id):
    """ Method to provide all menu items
    of a restaurant as a JSON object """

    items = session.query(MenuItem).filter_by(
        restaurant_id=restaurant_id).all()

    return jsonify(MenuItems=[i.serialize for i in items])


# JSON route for a specific menu item
@app.route('/restaurant/<int:restaurant_id>/<int:menu_id>/JSON')
def menuItemJSON(restaurant_id, menu_id):
    """ Method to provide a specific menu item
    of a restaurant as a JSON object """

    item = session.query(MenuItem).filter_by(
        id=menu_id).one()

    return jsonify(MenuItem=item.serialize)


if __name__ == '__main__':
    app.secret_key = 'super_secret_key'
    app.debug = True
    app.run(host='0.0.0.0', port=5000)
