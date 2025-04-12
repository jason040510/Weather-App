import requests, json, sqlite3, pytz, Export_format
from flask import Flask, render_template, request, redirect, url_for, g, flash
from datetime import datetime, timedelta, timezone


app = Flask(__name__)
app.secret_key = '123456789' 

API_KEY = '769b38da606e51a58cde555827aeeda1'
DATABASE = 'weather.db'


### HELPER FUNCTIONS
@app.route('/export_records', methods=['GET','POST'])
def export_records():
    """Export all weather records (and possibly details) in the chosen format."""
    export_format = request.args.get('format', 'json').lower()  # default JSON
    db = get_db()
    rec_cur = db.execute("SELECT * FROM weather_records ORDER BY created_at DESC")
    records = rec_cur.fetchall()
    details_cur = db.execute("SELECT * FROM weather_details ORDER BY record_id, obs_date")
    details = details_cur.fetchall()

    if export_format == 'json':
        return Export_format.export_json(records, details)
    elif export_format == 'xml':
        return Export_format.export_xml(records, details)
    elif export_format == 'csv':
        return Export_format.export_csv(records, details)
    else:
        return "Unsupported format requested.", 400

@app.template_filter("est_time")
def est_time_filter(timestamp_str):
    if not timestamp_str:
        return ""
    try:
        # Parse the DB timestamp (assuming '%Y-%m-%d %H:%M:%S' format in UTC)
        dt_utc = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
        # Mark it as UTC
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
        # Convert to US/Eastern
        eastern = pytz.timezone("US/Eastern")
        dt_est = dt_utc.astimezone(eastern)
        return dt_est.strftime('%Y-%m-%d %H:%M:%S %Z')
    except ValueError:
        return timestamp_str
    
@app.template_filter("loads")
def loads_filter(s):
    if s:
        return json.loads(s)
    return []

@app.template_filter('datetimeformat')
def datetimeformat_filter(timestamp):
    try:
        dt = datetime.utcfromtimestamp(timestamp)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except (TypeError, ValueError):
        return timestamp

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

def generate_date_list(date_from_str, date_to_str):
    date_list = []
    current_date = datetime.strptime(date_from_str, '%Y-%m-%d')
    end_date = datetime.strptime(date_to_str, '%Y-%m-%d')
    while current_date <= end_date:
        date_list.append(current_date.strftime('%Y-%m-%d'))
        current_date += timedelta(days=1)
    return date_list

def get_daily_aggregated_data(lat, lon, target_date_str, lang_code='en'):
    try:
        datetime.strptime(target_date_str, "%Y-%m-%d")  
    except ValueError:
        return None
    url = (
        f"https://api.openweathermap.org/data/3.0/onecall/day_summary?"
        f"lat={lat}&lon={lon}&date={target_date_str}&units=imperial"
        f"&lang={lang_code}&appid={API_KEY}"
    )
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    return None


### DATABASE (CRUD) SETUP

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row  # allow column access by name
    return db

def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        # Main record table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS weather_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                location TEXT NOT NULL,
                lat REAL,
                lon REAL,
                date_from TEXT NOT NULL,
                date_to TEXT NOT NULL,
                query_params TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Daily weather details table 
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS weather_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id INTEGER NOT NULL,
                obs_date TEXT NOT NULL,
                morning_temp REAL,
                afternoon_temp REAL,
                evening_temp REAL,
                night_temp REAL,
                min_temp REAL,
                max_temp REAL,
                humidity REAL,
                wind_speed REAL,
                clouds REAL,
                precipitation REAL,
                FOREIGN KEY (record_id) REFERENCES weather_records(id)
            )
        ''')
        db.commit()

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

### ROUTES

### EXISTING WEATHER SEARCH ROUTE ("/")
### -------------------------

@app.route('/', methods=['GET', 'POST'])
def index():
    results = []
    error = None

    if request.method == 'POST':
        lang_code = request.form.get('lang', 'en').strip()
        target_date_input = request.form.get('target_date', '').strip()
        if target_date_input:
            try:
                datetime.strptime(target_date_input, "%Y-%m-%d")
            except ValueError:
                error = "Target date format error. Please use YYYY-MM-DD."
                return render_template('index.html', results=results, error=error)
        
        option = request.form.get('option', '')
        # Option 1: City, State, Country
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
                                onecall_url = (
                                    f"https://api.openweathermap.org/data/3.0/onecall?"
                                    f"lat={lat}&lon={lon}&units=imperial&exclude=minutely,hourly"
                                    f"&lang={lang_code}&appid={API_KEY}"
                                )
                                w_resp = requests.get(onecall_url)
                                weather_data = w_resp.json() if w_resp.status_code == 200 else None
                                overview_data = {'today': None, 'tomorrow': None}
                                overview_today_url = (
                                    f"https://api.openweathermap.org/data/3.0/onecall/overview?"
                                    f"lat={lat}&lon={lon}&units=imperial"
                                    f"&lang={lang_code}&appid={API_KEY}"
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
                                        f"&date={tomorrow_date_str}&lang={lang_code}&appid={API_KEY}"
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
                                    'overview': overview_data
                                }
                            results.append(result)
                else:
                    error = "Error accessing the geocoding service (Option 1)."
        # Option 2: ZIP Code, Country
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
                            f"&lang={lang_code}&appid={API_KEY}"
                        )
                        w_resp = requests.get(onecall_url)
                        weather_data = w_resp.json() if w_resp.status_code == 200 else None
                        overview_data = {'today': None, 'tomorrow': None}
                        overview_today_url = (
                            f"https://api.openweathermap.org/data/3.0/onecall/overview?"
                            f"lat={lat}&lon={lon}&units=imperial"
                            f"&lang={lang_code}&appid={API_KEY}"
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
                                f"&date={tomorrow_date_str}&lang={lang_code}&appid={API_KEY}"
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

@app.route('/records')
def records():
    """List all weather records including a count of daily forecasts."""
    db = get_db()
    query = """
        SELECT wr.*,
               COUNT(wd.id) AS forecast_count
        FROM weather_records wr
        LEFT JOIN weather_details wd ON wr.id = wd.record_id
        GROUP BY wr.id
        ORDER BY wr.created_at DESC
    """
    cur = db.execute(query)
    rows = cur.fetchall()
    return render_template('records.html', records=rows)

@app.route('/record/<int:record_id>')
def view_record(record_id):
    """Detailed view: display daily forecasts for a given record."""
    db = get_db()
    rec_cur = db.execute("SELECT * FROM weather_records WHERE id = ?", (record_id,))
    record = rec_cur.fetchone()
    if not record:
        return "Record not found", 404
    details_cur = db.execute(
        "SELECT * FROM weather_details WHERE record_id = ? ORDER BY obs_date",
        (record_id,)
    )
    details = details_cur.fetchall()
    return render_template('record_detail.html', record=record, details=details)

@app.route('/record/new', methods=['GET', 'POST'])
def create_record():
    """
    Create a new weather record.
    Supports Option 1 (City, State, Country) or Option 2 (ZIP Code, Country).
    """
    error = None
    if request.method == 'POST':
        date_from = request.form.get('date_from', '').strip()
        date_to = request.form.get('date_to', '').strip()
        option = request.form.get('option', '')
        if not date_from or not date_to:
            error = "Please fill in the Start and End Dates."
            return render_template('record_form.html', error=error)
        try:
            dt_from = datetime.strptime(date_from, "%Y-%m-%d")
            dt_to = datetime.strptime(date_to, "%Y-%m-%d")
        except ValueError:
            error = "Date format error. Use YYYY-MM-DD."
            return render_template('record_form.html', error=error)
        if dt_from > dt_to:
            error = "Start date must be earlier than or equal to end date."
            return render_template('record_form.html', error=error)

        lat = None
        lon = None
        query_params = None
        location_input = ""

        if option == 'option1':
            city = request.form.get('city', '').strip()
            state = request.form.get('state', '').strip()
            country = request.form.get('country', '').strip()
            if not city and not state and not country:
                error = "Please enter at least one value (City, State, or Country)."
                return render_template('record_form.html', error=error)
            query_str = ",".join([val for val in [city, state, country] if val])
            geocode_url = f"http://api.openweathermap.org/geo/1.0/direct?q={query_str}&limit=1&appid={API_KEY}"
            geo_resp = requests.get(geocode_url)
            if geo_resp.status_code != 200 or not geo_resp.json():
                error = "Location not found. Please check your input."
                return render_template('record_form.html', error=error)
            geo_data = geo_resp.json()[0]
            lat = geo_data.get('lat')
            lon = geo_data.get('lon')
            query_params = json.dumps(geo_data)
            location_input = f"{query_str}"
        elif option == 'option2':
            zip_code = request.form.get('zip_code', '').strip()
            country_zip = request.form.get('country_zip', '').strip()
            if not zip_code or not country_zip:
                error = "Please enter both the ZIP Code and Country Code."
                return render_template('record_form.html', error=error)
            zip_url = f"http://api.openweathermap.org/geo/1.0/zip?zip={zip_code},{country_zip}&appid={API_KEY}"
            zip_resp = requests.get(zip_url)
            if zip_resp.status_code != 200 or not zip_resp.json():
                error = "Zip code location not found. Please check your input."
                return render_template('record_form.html', error=error)
            zip_data = zip_resp.json()
            lat = zip_data.get('lat')
            lon = zip_data.get('lon')
            query_params = json.dumps(zip_data)
            location_input = f"{zip_code}, {country_zip}"
        else:
            error = "Please choose one of the available options."
            return render_template('record_form.html', error=error)

        db = get_db()
        cur = db.execute(
            """
            INSERT INTO weather_records (location, lat, lon, date_from, date_to, query_params)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (location_input, lat, lon, date_from, date_to, query_params)
        )
        db.commit()
        record_id = cur.lastrowid

        all_dates = generate_date_list(date_from, date_to)
        for day_str in all_dates:
            daily_data = get_daily_aggregated_data(lat, lon, day_str, 'en')
            if daily_data:
                morning_temp = daily_data.get('temperature', {}).get('morning')
                afternoon_temp = daily_data.get('temperature', {}).get('afternoon')
                evening_temp = daily_data.get('temperature', {}).get('evening')
                night_temp = daily_data.get('temperature', {}).get('night')
                min_temp = daily_data.get('temperature', {}).get('min')
                max_temp = daily_data.get('temperature', {}).get('max')
                humidity = None
                if isinstance(daily_data.get('humidity', {}).get('afternoon'), (int, float)):
                    humidity = daily_data.get('humidity', {}).get('afternoon')
                wind_speed = None
                if isinstance(daily_data.get('wind'), dict):
                    if isinstance(daily_data.get('wind').get('max'), dict):
                        wind_speed = daily_data.get('wind').get('max').get('speed')
                    else:
                        wind_speed = daily_data.get('wind').get('speed')
                clouds = None
                if isinstance(daily_data.get('cloud_cover'), dict):
                    clouds = daily_data.get('cloud_cover').get('afternoon')
                precipitation = None
                if isinstance(daily_data.get('precipitation'), dict):
                    precipitation = daily_data.get('precipitation').get('total')
                
                db.execute(
                    """
                    INSERT INTO weather_details
                        (record_id, obs_date, morning_temp, afternoon_temp, evening_temp,
                         night_temp, min_temp, max_temp, humidity, wind_speed, clouds, precipitation)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (record_id, day_str, morning_temp, afternoon_temp, evening_temp,
                     night_temp, min_temp, max_temp, humidity, wind_speed, clouds, precipitation)
                )
                db.commit()
        flash("Record created successfully.", "success")
        return redirect(url_for('records'))
    return render_template('record_form.html', error=error)

@app.route('/record/<int:record_id>/update', methods=['GET', 'POST'])
def update_record(record_id):
    """Update the main record (location and date range). This route re-fetches daily data using the API."""
    db = get_db()
    cur = db.execute("SELECT * FROM weather_records WHERE id = ?", (record_id,))
    record = cur.fetchone()
    if not record:
        return "Record not found", 404
    error = None
    if request.method == 'POST':
        date_from = request.form.get('date_from', '').strip()
        date_to = request.form.get('date_to', '').strip()
        option = request.form.get('option', '')
        if not date_from or not date_to:
            error = "Please fill in the Start and End Dates."
            return render_template('record_form.html', error=error, record=record)
        try:
            dt_from = datetime.strptime(date_from, "%Y-%m-%d")
            dt_to = datetime.strptime(date_to, "%Y-%m-%d")
        except ValueError:
            error = "Date format error. Use YYYY-MM-DD."
            return render_template('record_form.html', error=error, record=record)
        if dt_from > dt_to:
            error = "Start date must be earlier than or equal to end date."
            return render_template('record_form.html', error=error, record=record)
        
        lat = None
        lon = None
        query_params = None
        location_input = ""

        if option == 'option1':
            city = request.form.get('city', '').strip()
            state = request.form.get('state', '').strip()
            country = request.form.get('country', '').strip()
            if not city and not state and not country:
                error = "Please provide City, State, or Country."
                return render_template('record_form.html', error=error, record=record)
            query_str = ",".join([val for val in [city, state, country] if val])
            geocode_url = f"http://api.openweathermap.org/geo/1.0/direct?q={query_str}&limit=1&appid={API_KEY}"
            geo_resp = requests.get(geocode_url)
            if geo_resp.status_code != 200 or not geo_resp.json():
                error = "Location not found."
                return render_template('record_form.html', error=error, record=record)
            geo_data = geo_resp.json()[0]
            lat = geo_data.get('lat')
            lon = geo_data.get('lon')
            query_params = json.dumps(geo_data)
            location_input = f"{query_str}"
        elif option == 'option2':
            zip_code = request.form.get('zip_code', '').strip()
            country_zip = request.form.get('country_zip', '').strip()
            if not zip_code or not country_zip:
                error = "Please enter both the ZIP Code and Country Code."
                return render_template('record_form.html', error=error, record=record)
            zip_url = f"http://api.openweathermap.org/geo/1.0/zip?zip={zip_code},{country_zip}&appid={API_KEY}"
            zip_resp = requests.get(zip_url)
            if zip_resp.status_code != 200 or not zip_resp.json():
                error = "Zip code location not found."
                return render_template('record_form.html', error=error, record=record)
            zip_data = zip_resp.json()
            lat = zip_data.get('lat')
            lon = zip_data.get('lon')
            query_params = json.dumps(zip_data)
            location_input = f"{zip_code}, {country_zip}"
        else:
            error = "Please pick Option 1 or Option 2."
            return render_template('record_form.html', error=error, record=record)

        db.execute(
            """
            UPDATE weather_records
               SET location = ?,
                   lat = ?,
                   lon = ?,
                   date_from = ?,
                   date_to = ?,
                   query_params = ?,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (location_input, lat, lon, date_from, date_to, query_params, record_id)
        )
        db.commit()

        db.execute("DELETE FROM weather_details WHERE record_id = ?", (record_id,))
        db.commit()

        all_dates = generate_date_list(date_from, date_to)
        for day_str in all_dates:
            daily_data = get_daily_aggregated_data(lat, lon, day_str, 'en')
            if daily_data:
                morning_temp = daily_data.get('temperature', {}).get('morning')
                afternoon_temp = daily_data.get('temperature', {}).get('afternoon')
                evening_temp = daily_data.get('temperature', {}).get('evening')
                night_temp = daily_data.get('temperature', {}).get('night')
                min_temp = daily_data.get('temperature', {}).get('min')
                max_temp = daily_data.get('temperature', {}).get('max')
                humidity = None
                if isinstance(daily_data.get('humidity', {}).get('afternoon'), (int, float)):
                    humidity = daily_data.get('humidity', {}).get('afternoon')
                wind_speed = None
                if isinstance(daily_data.get('wind'), dict):
                    if isinstance(daily_data.get('wind').get('max'), dict):
                        wind_speed = daily_data.get('wind').get('max').get('speed')
                    else:
                        wind_speed = daily_data.get('wind').get('speed')
                clouds = None
                if isinstance(daily_data.get('cloud_cover'), dict):
                    clouds = daily_data.get('cloud_cover').get('afternoon')
                precipitation = None
                if isinstance(daily_data.get('precipitation'), dict):
                    precipitation = daily_data.get('precipitation').get('total')
                
                db.execute(
                    """
                    INSERT INTO weather_details
                        (record_id, obs_date, morning_temp, afternoon_temp, evening_temp,
                         night_temp, min_temp, max_temp, humidity, wind_speed, clouds, precipitation)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (record_id, day_str, morning_temp, afternoon_temp, evening_temp,
                     night_temp, min_temp, max_temp, humidity, wind_speed, clouds, precipitation)
                )
                db.commit()

        flash("Record updated successfully.", "success")
        return redirect(url_for('records'))
    return render_template('record_form.html', error=error, record=record)

@app.route('/record/<int:record_id>/edit_details', methods=['GET', 'POST'])
def edit_record_details(record_id):
    """
    Allow the user to update individual daily weather details stored in the database.
    The form displays the forecasts in editable fields.
    """
    db = get_db()
    # Retrieve the main record (for context)
    rec_cur = db.execute("SELECT * FROM weather_records WHERE id = ?", (record_id,))
    record = rec_cur.fetchone()
    if not record:
        return "Record not found", 404

    # Retrieve the daily details for this record
    details_cur = db.execute("SELECT * FROM weather_details WHERE record_id = ? ORDER BY obs_date", (record_id,))
    details = details_cur.fetchall()

    if request.method == 'POST':
        # For each detail row, update the values from form fields.
        for detail in details:
            detail_id = detail['id']
            # Expect field names like forecast_{{ detail.id }}_morning_temp, etc.
            morning_temp = request.form.get(f"forecast_{detail_id}_morning_temp")
            afternoon_temp = request.form.get(f"forecast_{detail_id}_afternoon_temp")
            evening_temp = request.form.get(f"forecast_{detail_id}_evening_temp")
            night_temp = request.form.get(f"forecast_{detail_id}_night_temp")
            min_temp = request.form.get(f"forecast_{detail_id}_min_temp")
            max_temp = request.form.get(f"forecast_{detail_id}_max_temp")
            humidity = request.form.get(f"forecast_{detail_id}_humidity")
            wind_speed = request.form.get(f"forecast_{detail_id}_wind_speed")
            clouds = request.form.get(f"forecast_{detail_id}_clouds")
            precipitation = request.form.get(f"forecast_{detail_id}_precipitation")
            
            # Convert numeric fields where possible; otherwise leave as None.
            def to_float(val):
                try:
                    return float(val)
                except (TypeError, ValueError):
                    return None

            db.execute(
                """
                UPDATE weather_details 
                   SET morning_temp = ?,
                       afternoon_temp = ?,
                       evening_temp = ?,
                       night_temp = ?,
                       min_temp = ?,
                       max_temp = ?,
                       humidity = ?,
                       wind_speed = ?,
                       clouds = ?,
                       precipitation = ?
                 WHERE id = ?
                """,
                (to_float(morning_temp), to_float(afternoon_temp), to_float(evening_temp),
                 to_float(night_temp), to_float(min_temp), to_float(max_temp),
                 to_float(humidity), to_float(wind_speed), to_float(clouds), to_float(precipitation),
                 detail_id)
            )
        db.commit()
        flash("Daily weather details updated successfully.", "success")
        return redirect(url_for('view_record', record_id=record_id))

    return render_template('record_details_edit.html', record=record, details=details)

@app.route('/record/<int:record_id>/delete', methods=['GET','POST'])
def delete_record(record_id):
    db = get_db()
    db.execute("DELETE FROM weather_details WHERE record_id = ?", (record_id,))
    db.execute("DELETE FROM weather_records WHERE id = ?", (record_id,))
    db.commit()
    flash("Record deleted successfully.", "success")
    return redirect(url_for('records'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)