import jinja2
import matplotlib
import matplotlib.pyplot as plt
import os
import pytz
import requests
import sqlite3

from pprint import PrettyPrinter
from datetime import datetime, timedelta
from dotenv import load_dotenv
from flask import Flask, render_template, request, send_file
from geopy.geocoders import Nominatim
from io import BytesIO
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas

################################################################################
## SETUP
################################################################################

app = Flask(__name__)

load_dotenv()
API_KEY = os.getenv('API_KEY')

# Settings for image endpoint
# Written with help from http://dataviztalk.blogspot.com/2016/01/serving-matplotlib-plot-that-follows.html
matplotlib.use('agg')
plt.style.use('ggplot')

my_loader = jinja2.ChoiceLoader([
    app.jinja_loader,
    jinja2.FileSystemLoader('data'),
])
app.jinja_loader = my_loader

pp = PrettyPrinter(indent=4)

################################################################################
## ROUTES
################################################################################

@app.route('/')
def home():
    """Displays the homepage with forms for current or historical data."""

    dateNow = datetime.now()
    context = {
        'min_date': (dateNow - timedelta(days=5)),
        'max_date': dateNow
    }
    return render_template('home.html', **context)

def get_letter_for_units(units):
    """Returns a shorthand letter for the given units."""
    return 'F' if units == 'imperial' else 'C' if units == 'metric' else 'K'

@app.route('/results')
def results():
    """Displays results for current weather conditions."""

    city = request.args.get('city')
    units = request.args.get('units')
    url = 'http://api.openweathermap.org/data/2.5/weather'
    latitude, longitude = get_lat_lon(city)

    params = {
        "lat": latitude,
        "lon": longitude,
        "appid": API_KEY,
        "units": units
    }

    result_json = requests.get(url, params=params).json()
    weather = result_json.get('weather')

    context = {
        'date': datetime.now(),
        'city': result_json['name'],
        'description': weather[0]['description'],
        'temp': result_json['main']['temp'],
        'humidity': result_json['main']['humidity'],
        'wind_speed': result_json['wind']['speed'],
        'sunrise': datetime.utcfromtimestamp(int(result_json['sys']['sunrise'])).strftime('%Y-%m-%d %H:%M %p'),
        'sunset': datetime.utcfromtimestamp(int(result_json['sys']['sunset'])).strftime('%Y-%m-%d %H:%M %p'),
        'units_letter': get_letter_for_units(units),
        'icon': weather[0]['icon']
    }
    #Used to get sunrise and sunset: https://stackoverflow.com/questions/7064531/sunrise-sunset-times-in-c/19706933
    return render_template('results.html', **context)

def get_min_temp(results):
    """Returns the minimum temp for the given hourly weather objects."""

    min=results[0]['temp']
    for result in results:
        if(result['temp']<min):
            min=result['temp']
        
    return min

def get_max_temp(results):
    """Returns the maximum temp for the given hourly weather objects."""

    max=results[0]['temp']
    for result in results:
        if(result['temp']>=max):
            max=result['temp']
        
    return max

def get_lat_lon(city_name):
    geolocator = Nominatim(user_agent='Weather Application')
    location = geolocator.geocode(city_name)
    if location is not None:
        return location.latitude, location.longitude
    return 0, 0
@app.route('/forecast_results')
def forecast_results():
    """Displays results for future weather conditions."""

    date = request.args.get('date')
    date_obj = datetime.strptime(date, '%Y-%m-%d')
    city = request.args.get('city')
    date_in_seconds = date_obj.strftime('%s')
    units = request.args.get('units')
    latitude, longitude = get_lat_lon(city)

    url = 'https://api.openweathermap.org/data/2.5/onecall'
    params = {
        'dt' : date_in_seconds,
        'units' : units,
        'appid': API_KEY,
        'lat': latitude,
        'lon': longitude,
        
    }
    result_json = requests.get(url, params=params).json()
    result_current = result_json['current']
    current_day_list = []
    days = result_json['daily']

    for day in days:
        current_day_list.append(datetime.fromtimestamp(day['dt']).strftime('%A, %B %d, %Y'))

    context = {
        'date': date_obj,
        'city': city,
        'description': result_current['weather'][0]['description'],
        'temp': result_current['temp'],
        'humidity': result_current['humidity'],
        'wind_speed': result_current['wind_speed'],
        'sunrise': datetime.fromtimestamp(result_current['sunrise']).strftime('%I:%M %p'),
        'sunset': datetime.fromtimestamp(result_current['sunset']).strftime('%I:%M %p'),
        'units_letter': get_letter_for_units(units),
        'icon': result_current['weather'][0]['icon'],
        'days': days,
        'day_list': current_day_list

    }

    return render_template('forecast_results.html', **context)

@app.route('/historical_results')
def historical_results():
    """Displays historical weather forecast for a given day."""
   
    city = request.args.get('city')
    date = request.args.get('date')
    units = request.args.get('units')
    date_obj = datetime.strptime(date, '%Y-%m-%d')
    date_in_seconds = date_obj.strftime('%s')
    latitude, longitude = get_lat_lon(city)

    url = 'http://api.openweathermap.org/data/2.5/onecall/timemachine'
    params = {
        'dt' : date_in_seconds,
        'units' : units,
        'appid': API_KEY,
        'lat': latitude,
        'lon': longitude,
    }

    result_json = requests.get(url, params=params).json()
    result_current = result_json['current']
    result_hourly = result_json['hourly']

    context = {
        'city': city,
        'date': date_obj,
        'lat': latitude,
        'lon': longitude,
        'units': units,
        'units_letter': get_letter_for_units(units), 
        'description': result_current['weather'][0]['description'],
        'temp': result_current['temp'],
        'min_temp': get_min_temp(result_hourly),
        'max_temp': get_max_temp(result_hourly),
        'icon': result_current['weather'][0]['icon'],
        'sunrise': datetime.fromtimestamp(result_current['sunrise']).strftime('%I:%M %p'),
        'sunset': datetime.fromtimestamp(result_current['sunset']).strftime('%I:%M %p')
    }

    return render_template('historical_results.html', **context)


################################################################################
## IMAGES
################################################################################

def create_image_file(xAxisData, yAxisData, xLabel, yLabel):
    """
    Creates and returns a line graph with the given data.
    Written with help from http://dataviztalk.blogspot.com/2016/01/serving-matplotlib-plot-that-follows.html
    """
    fig, _ = plt.subplots()
    plt.plot(xAxisData, yAxisData)
    plt.xlabel(xLabel)
    plt.ylabel(yLabel)
    canvas = FigureCanvas(fig)
    img = BytesIO()
    fig.savefig(img)
    img.seek(0)
    return send_file(img, mimetype='image/png')

@app.route('/graph/<lat>/<lon>/<units>/<date>')
def graph(lat, lon, units, date):
    """
    Returns a line graph with data for the given location & date.
    @param lat The latitude.
    @param lon The longitude.
    @param units The units (imperial, metric, or kelvin)
    @param date The date, in the format %Y-%m-%d.
    """
    date_obj = datetime.strptime(date, '%Y-%m-%d')
    date_in_seconds = date_obj.strftime('%s')


    url = 'http://api.openweathermap.org/data/2.5/onecall/timemachine'
    params = {
        'appid': API_KEY,
        'lat': lat,
        'lon': lon,
        'units': units,
        'dt': date_in_seconds
    }

    result_json = requests.get(url, params=params).json()
    hour_results = result_json['hourly']
    hours = range(24)
    temps = [r['temp'] for r in hour_results]
    image = create_image_file(
        hours,
        temps,
        'Hour',
        f'Temperature ({get_letter_for_units(units)})'
    )
    return image


if __name__ == '__main__':
    app.run(debug=True)
