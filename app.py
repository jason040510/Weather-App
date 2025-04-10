import requests
from flask import Flask, render_template, request
from datetime import datetime, timedelta

app = Flask(__name__)

API_KEY = '769b38da606e51a58cde555827aeeda1'

def get_tomorrow_date_str(weather_data):
    if not weather_data:
        return None
    current_dt_utc = weather_data.get('current', {}).get('dt')
    timezone_offset = weather_data.get('timezone_offset')
    if current_dt_utc is None or timezone_offset is None:
        return None
    local_timestamp = current_dt_utc + timezone_offset
    local_dt = datetime.utcfromtimestamp(local_timestamp)
    tomorrow_local_dt = local_dt + timedelta(days=1)
    return tomorrow_local_dt.strftime('%Y-%m-%d')

@app.template_filter('datetimeformat')
def datetimeformat_filter(timestamp):
    return datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

def get_daily_aggregated_data(lat, lon, target_date_str, lang_code):
    """
    Calls the One Call 3.0 'day_summary' endpoint to retrieve aggregated weather data
    for a specific date. We add &lang={lang_code} so that the weather descriptions are
    returned in the chosen language (if the API supports it).
    """
    try:
        datetime.strptime(target_date_str, "%Y-%m-%d")  # Validate format
    except ValueError:
        return None
    
    url = (
        f"https://api.openweathermap.org/data/3.0/onecall/day_summary?"
        f"lat={lat}&lon={lon}&date={target_date_str}&units=imperial"
        f"&lang={lang_code}"  # <--- add lang param
        f"&appid={API_KEY}"
    )
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        return None

@app.route('/', methods=['GET', 'POST'])
def index():
    results = []
    error = None

    if request.method == 'POST':
        # Read the user-selected language (default to 'en' if none)
        lang_code = request.form.get('lang', 'en').strip()

        # Optional target date
        target_date_input = request.form.get('target_date', '').strip()
        if target_date_input:
            try:
                datetime.strptime(target_date_input, "%Y-%m-%d")
            except ValueError:
                error = "Target date format error. Please use YYYY-MM-DD."
                return render_template('index.html', results=results, error=error)
        
        option = request.form.get('option', '')

        # ------------------------------------------------------------
        # Option 1: City, State, Country
        # ------------------------------------------------------------
        if option == 'option1':
            city = request.form.get('city', '').strip()
            state = request.form.get('state', '').strip()
            country = request.form.get('country', '').strip()
            
            query_parts = []
            if city:
                query_parts.append(city)
            if state:
                query_parts.append(state)
            if country:
                query_parts.append(country)
            
            if not query_parts:
                error = "Please enter at least one value (City, State, or Country) for Option 1."
            else:
                query_str = ','.join(query_parts)
                geocode_url = f"http://api.openweathermap.org/geo/1.0/direct?q={query_str}&limit=5&appid={API_KEY}"
                geo_resp = requests.get(geocode_url)
                
                if geo_resp.status_code == 200:
                    geo_data = geo_resp.json()
                    if not geo_data:
                        error = "No results found for the given City/State/Country."
                    else:
                        for item in geo_data:
                            lat = item.get('lat')
                            lon = item.get('lon')
                            
                            if target_date_input:
                                # Aggregated data for the target date
                                agg_data = get_daily_aggregated_data(lat, lon, target_date_input, lang_code)
                                if not agg_data:
                                    error = "Failed to retrieve aggregated weather data for the target date."
                                    continue
                                result = {
                                    'name': item.get('name'),
                                    'state': item.get('state', ''),
                                    'country': item.get('country', ''),
                                    'lat': lat,
                                    'lon': lon,
                                    'weather': agg_data
                                }
                            else:
                                # Original logic: One Call API (with language param)
                                onecall_url = (
                                    f"https://api.openweathermap.org/data/3.0/onecall?"
                                    f"lat={lat}&lon={lon}&units=imperial&exclude=minutely,hourly"
                                    f"&lang={lang_code}"  # <--- add lang param
                                    f"&appid={API_KEY}"
                                )
                                w_resp = requests.get(onecall_url)
                                weather_data = w_resp.json() if w_resp.status_code == 200 else None
                                
                                overview_data = {'today': None, 'tomorrow': None}
                                overview_today_url = (
                                    f"https://api.openweathermap.org/data/3.0/onecall/overview?"
                                    f"lat={lat}&lon={lon}&units=imperial"
                                    f"&lang={lang_code}"  # <--- add lang param
                                    f"&appid={API_KEY}"
                                )
                                o_today_resp = requests.get(overview_today_url)
                                if o_today_resp.status_code == 200:
                                    overview_data['today'] = o_today_resp.json()
                                
                                tomorrow_date_str = None
                                if weather_data:
                                    tomorrow_date_str = get_tomorrow_date_str(weather_data)
                                
                                if tomorrow_date_str:
                                    overview_tomorrow_url = (
                                        f"https://api.openweathermap.org/data/3.0/onecall/overview?"
                                        f"lat={lat}&lon={lon}&units=imperial"
                                        f"&date={tomorrow_date_str}"
                                        f"&lang={lang_code}"  # <--- add lang param
                                        f"&appid={API_KEY}"
                                    )
                                    o_tomorrow_resp = requests.get(overview_tomorrow_url)
                                    if o_tomorrow_resp.status_code == 200:
                                        overview_data['tomorrow'] = o_tomorrow_resp.json()
                                
                                result = {
                                    'name': item.get('name'),
                                    'state': item.get('state', ''),
                                    'country': item.get('country', ''),
                                    'lat': lat,
                                    'lon': lon,
                                    'weather': weather_data,
                                    'overview': overview_data,
                                    
                                }
                            results.append(result)
                else:
                    error = "Error accessing the geocoding service (Option 1)."
        
        # ------------------------------------------------------------
        # Option 2: ZIP Code, Country
        # ------------------------------------------------------------
        elif option == 'option2':
            zip_code = request.form.get('zip_code', '').strip()
            country_code = request.form.get('country_zip', '').strip()
            
            if not zip_code or not country_code:
                error = "Please enter both the ZIP Code and Country Code for Option 2."
            else:
                zip_url = f"http://api.openweathermap.org/geo/1.0/zip?zip={zip_code},{country_code}&appid={API_KEY}"
                zip_resp = requests.get(zip_url)
                
                if zip_resp.status_code == 200:
                    zip_data = zip_resp.json()
                    lat = zip_data.get('lat')
                    lon = zip_data.get('lon')
                    name = zip_data.get('name', '')
                    
                    if target_date_input:
                        agg_data = get_daily_aggregated_data(lat, lon, target_date_input, lang_code)
                        if not agg_data:
                            error = "Failed to retrieve aggregated weather data for the target date."
                        else:
                            result = {
                                'name': name,
                                'state': '',
                                'country': country_code,
                                'lat': lat,
                                'lon': lon,
                                'weather': agg_data
                            }
                    else:
                        onecall_url = (
                            f"https://api.openweathermap.org/data/3.0/onecall?"
                            f"lat={lat}&lon={lon}&units=imperial&exclude=minutely,hourly"
                            f"&lang={lang_code}"  # <--- add lang param
                            f"&appid={API_KEY}"
                        )
                        w_resp = requests.get(onecall_url)
                        weather_data = w_resp.json() if w_resp.status_code == 200 else None
                        
                        overview_data = {'today': None, 'tomorrow': None}
                        overview_today_url = (
                            f"https://api.openweathermap.org/data/3.0/onecall/overview?"
                            f"lat={lat}&lon={lon}&units=imperial"
                            f"&lang={lang_code}"  # <--- add lang param
                            f"&appid={API_KEY}"
                        )
                        o_today_resp = requests.get(overview_today_url)
                        if o_today_resp.status_code == 200:
                            overview_data['today'] = o_today_resp.json()
                        
                        tomorrow_date_str = None
                        if weather_data:
                            tomorrow_date_str = get_tomorrow_date_str(weather_data)
                        
                        if tomorrow_date_str:
                            overview_tomorrow_url = (
                                f"https://api.openweathermap.org/data/3.0/onecall/overview?"
                                f"lat={lat}&lon={lon}&units=imperial"
                                f"&date={tomorrow_date_str}"
                                f"&lang={lang_code}"  # <--- add lang param
                                f"&appid={API_KEY}"
                            )
                            o_tomorrow_resp = requests.get(overview_tomorrow_url)
                            if o_tomorrow_resp.status_code == 200:
                                overview_data['tomorrow'] = o_tomorrow_resp.json()
                        
                        result = {
                            'name': name,
                            'state': '',
                            'country': country_code,
                            'lat': lat,
                            'lon': lon,
                            'weather': weather_data,
                            'overview': overview_data
                        }
                    results.append(result)
                else:
                    error = "No results found for the given ZIP Code or an error occurred."
        else:
            error = "Please choose one of the available options."
    
    return render_template('index.html', results=results, error=error)

if __name__ == '__main__':
    app.run(debug=True)