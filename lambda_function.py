import json
import requests
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# Global variables
events = []
GAP = timedelta(days=30)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

def myhelsinki():
    today = date.today()
    end_date = today + GAP
    try:
        initial_url = (
            "https://www.myhelsinki.fi/wp-json/mhb/v1/event_search"
            f"?s=&page=1&lang=en&posts_per_page=100&start_date={today}&end_date={end_date}"
        )
        response = requests.get(initial_url, headers=HEADERS)
        response.raise_for_status()
        initial_data = response.json()
        total_pages = initial_data.get('total_pages') or 1

        for page_number in range(1, total_pages + 1):
            url = f'https://www.myhelsinki.fi/wp-json/mhb/v1/event_search?s=&page={page_number}&lang=en&posts_per_page=100&start_date={today}&end_date={end_date}'
            page_response = requests.get(url, headers=HEADERS)
            page_response.raise_for_status()
            page_data = page_response.json()

            for result in page_data.get('results') or []:
                locations = result.get('locations') or []
                tags_data = result.get('tags') if isinstance(result.get('tags'), list) else []
                events.append({
                    'title': result.get('title'),
                    'description': result.get('excerpt'),
                    'location': [loc.get('location') for loc in locations if isinstance(loc, dict)],
                    'venue': [loc.get('title') for loc in locations if isinstance(loc, dict)],
                    'date': result.get('start_date'),
                    'time': result.get('start_time_of_day'),
                    'price': None,
                    'img_url': result.get('image_url'),
                    'tags': [tag.get('name') for tag in tags_data if isinstance(tag, dict)],
                    'signup_link': result.get('external_url'),
                    'created_by': None,
                    'created_at': None
                })
    except Exception as e:
        print(f"MyHelsinki error: {e}")

def luma():
    try:
        url = "https://api.lu.ma/discover/get-paginated-events?discover_place_api_id=discplace-gEii5B2Ju5KKRNH&pagination_limit=50"
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        data = response.json()

        for result in data.get('entries') or []:
            event_data = result.get('event') or {}
            ticket_info = result.get('ticket_info') or {}
            coordinates = event_data.get('coordinate') or {}

            start_at = event_data.get('start_at') or ""
            date_data, time_data = None, None
            if 'T' in start_at:
                date_data, time_data = start_at.split('T', 1)
            elif start_at:
                date_data = start_at

            events.append({
                'title': event_data.get('name'),
                'description': None,
                'location': [coordinates.get('latitude'), coordinates.get('longitude')],
                'venue': None,
                'date': date_data,
                'time': time_data,
                'price': 0 if ticket_info.get('is_free') else ticket_info.get('price'),
                'img_url': event_data.get('cover_url'),
                'tags': None,
                'signup_link': f"https://lu.ma/{event_data.get('url')}" if event_data.get('url') else None,
                'created_by': None,
                'created_at': None
            })
    except Exception as e:
        print(f"Luma error: {e}")

def linked_events():
    try:
        start_date = date.today()
        end_date = start_date + GAP
        url = f'https://api.hel.fi/linkedevents/v1/event/?start={start_date}&end={end_date}&is_free=true'

        while url:
            response = requests.get(url, headers=HEADERS)
            response.raise_for_status()
            data = response.json()
            url = (data.get('meta') or {}).get('next')

            for result in data.get('data', []):
                if result.get('event_status') in ('EventCancelled', 'EventPostponed'):
                    continue

                location_data = []
                venue_data = ''
                keywords = []

                start_time_str = result.get('start_time')
                date_data, time_data = None, None
                if start_time_str:
                    if 'T' in start_time_str:
                        date_data, time_data = start_time_str.split('T', 1)
                    else:
                        date_data = start_time_str

                location_url = (result.get('location') or {}).get('@id')
                if location_url:
                    try:
                        loc_resp = requests.get(location_url)
                        loc_resp.raise_for_status()
                        loc_json = loc_resp.json()
                        if loc_json:
                            coords = (loc_json.get('position') or {}).get('coordinates') or []
                            location_data = coords[::-1]
                            venue_data = ((loc_json.get('name') or {}).get('en') or
                                          (loc_json.get('name') or {}).get('fi'))
                    except Exception as e:
                        print(f"Error fetching location {location_url}: {str(e)}")

                for link in result.get('keywords') or []:
                    keyword_url = link.get('@id')
                    if keyword_url:
                        try:
                            key_resp = requests.get(keyword_url)
                            key_resp.raise_for_status()
                            key_json = key_resp.json()
                            if key_json:
                                keyword = ((key_json.get('name') or {}).get('en') or
                                           (key_json.get('name') or {}).get('fi'))
                                keywords.append(keyword)
                        except Exception as e:
                            print(f"Error fetching keyword {keyword_url}: {str(e)}")

                events.append({
                    'title': ((result.get('name') or {}).get('en') or
                              (result.get('name') or {}).get('fi')),
                    'description': ((result.get('description') or {}).get('en') or
                                    (result.get('description') or {}).get('fi')),
                    'location': location_data,
                    'venue': venue_data,
                    'date': date_data,
                    'time': time_data,
                    'price': 0,
                    'img_url': [image.get('url') for image in (result.get('images') or [])],
                    'tags': keywords,
                    'signup_link': ((result.get('info_url') or {}).get('en') or
                                    (result.get('info_url') or {}).get('fi')),
                    'created_by': None,
                    'created_at': None
                })
    except Exception as e:
        print(f"LinkedEvents error: {e}")

# Map source names to functions for easy calling
SOURCE_FUNCTIONS = {
    "myhelsinki": myhelsinki,
    "luma": luma,
    "linked_events": linked_events
}

def lambda_handler(event, context):
    global events
    events = []  # clear previous events

    # Get the 'source' query param, allow multiple separated by commas
    query_params = event.get("queryStringParameters") or {}
    sources_param = query_params.get("source", "").lower()

    if not sources_param:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Missing 'source' query parameter"})
        }

    # Split sources by comma, trim whitespace
    requested_sources = [s.strip() for s in sources_param.split(",")]

    # If 'all' is present, run all sources
    if "all" in requested_sources:
        requested_sources = list(SOURCE_FUNCTIONS.keys())

    # Filter out invalid sources
    valid_sources = [src for src in requested_sources if src in SOURCE_FUNCTIONS]

    if not valid_sources:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "No valid source specified"})
        }

    # Use ThreadPoolExecutor to fetch sources in parallel
    with ThreadPoolExecutor(max_workers=len(valid_sources)) as executor:
        futures = {executor.submit(SOURCE_FUNCTIONS[src]): src for src in valid_sources}

        for future in as_completed(futures):
            src = futures[future]
            try:
                future.result()
            except Exception as e:
                print(f"Error executing {src}: {e}")

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(events)
    }
