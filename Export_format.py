import json
from flask import jsonify, make_response, request
import csv
import io

def export_json(records, details):
    """Return JSON data for records + details."""
    # Convert sqlite3.Row objects to dict
    data = {
        "records": [dict(r) for r in records],
        "details": [dict(d) for d in details]
    }
    # Use Flask's `jsonify` for convenience
    return jsonify(data)
def export_csv(records, details):
    # Convert to CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)

    # Write header row for main records
    writer.writerow(["Records Table"])
    writer.writerow(["id", "location", "date_from", "date_to", "created_at", "updated_at"])
    for r in records:
        writer.writerow([
            r['id'], r['location'], r['date_from'],
            r['date_to'], r['created_at'], r['updated_at']
        ])

    writer.writerow([])  # blank line
    writer.writerow(["Details Table"])
    writer.writerow([
        "id", "record_id", "obs_date", "morning_temp", "afternoon_temp",
        "evening_temp", "night_temp", "min_temp", "max_temp", "humidity",
        "wind_speed", "clouds", "precipitation"
    ])
    for d in details:
        writer.writerow([
            d['id'], d['record_id'], d['obs_date'], d['morning_temp'], d['afternoon_temp'],
            d['evening_temp'], d['night_temp'], d['min_temp'], d['max_temp'], d['humidity'],
            d['wind_speed'], d['clouds'], d['precipitation']
        ])

    csv_output = output.getvalue()
    response = make_response(csv_output)
    response.headers['Content-Disposition'] = 'attachment; filename=weather_export.csv'
    response.headers['Content-Type'] = 'text/csv'
    return response

def export_xml(records, details):
    xml_parts = []
    xml_parts.append('<weather_export>')

    xml_parts.append('  <records>')
    for r in records:
        xml_parts.append('    <record>')
        xml_parts.append(f"      <id>{r['id']}</id>")
        xml_parts.append(f"      <location>{r['location']}</location>")
        xml_parts.append(f"      <date_from>{r['date_from']}</date_from>")
        xml_parts.append(f"      <date_to>{r['date_to']}</date_to>")
        xml_parts.append(f"      <created_at>{r['created_at']}</created_at>")
        xml_parts.append(f"      <updated_at>{r['updated_at']}</updated_at>")
        xml_parts.append('    </record>')
    xml_parts.append('  </records>')

    xml_parts.append('  <details>')
    for d in details:
        xml_parts.append('    <detail>')
        xml_parts.append(f"      <record_id>{d['record_id']}</record_id>")
        xml_parts.append(f"      <obs_date>{d['obs_date']}</obs_date>")
        xml_parts.append(f"      <morning_temp>{d['morning_temp']}</morning_temp>")
        xml_parts.append(f"      <afternoon_temp>{d['afternoon_temp']}</afternoon_temp>")
        xml_parts.append(f"      <evening_temp>{d['evening_temp']}</evening_temp>")
        xml_parts.append(f"      <night_temp>{d['night_temp']}</night_temp>")
        xml_parts.append(f"      <min_temp>{d['min_temp']}</min_temp>")
        xml_parts.append(f"      <max_temp>{d['max_temp']}</max_temp>")
        xml_parts.append(f"      <humidity>{d['humidity']}</humidity>")
        xml_parts.append(f"      <wind_speed>{d['wind_speed']}</wind_speed>")
        xml_parts.append(f"      <clouds>{d['clouds']}</clouds>")
        xml_parts.append(f"      <precipitation>{d['precipitation']}</precipitation>")
        xml_parts.append('    </detail>')
    xml_parts.append('  </details>')

    xml_parts.append('</weather_export>')
    xml_output = "\n".join(xml_parts)

    response = make_response(xml_output)
    response.headers['Content-Type'] = 'application/xml'
    response.headers['Content-Disposition'] = 'attachment; filename=weather_export.xml'
    return response