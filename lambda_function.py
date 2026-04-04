import json
import requests
import asyncio
import aiohttp
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# Global configuration
GAP = timedelta(days=100)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

async def fetch_all(session, urls):
    """Utility to fetch multiple URLs concurrently."""
    tasks = []
    for url in urls:
        if url:
            tasks.append(session.get(url, headers=HEADERS))
    
    responses = await asyncio.gather(*tasks, return_exceptions=True)
    
    results_map = {}
    for url, resp in zip(urls, responses):
        if isinstance(resp, Exception):
            continue
        try:
            results_map[url] = await resp.json()
        except:
            continue
    return results_map

async def get_linked_events():
    """Asynchronous version of LinkedEvents to prevent timeout with pagination."""
    start_date = date.today()
    end_date = start_date + GAP
    base_url = f'https://api.hel.fi/linkedevents/v1/event/?start={start_date}&end={end_date}&is_free=true&page_size=100'
    
    local_events = []
    
    async with aiohttp.ClientSession() as session:
        # Paginate through all events
        next_url = base_url
        while next_url:
            async with session.get(next_url, headers=HEADERS) as resp:
                if resp.status != 200:
                    break
                data = await resp.json()
                raw_results = data.get('data', [])

            # Filter out cancelled events and collect unique URLs for locations/keywords
            valid_results = [r for r in raw_results if r.get('event_status') not in ('EventCancelled', 'EventPostponed')]
            
            loc_urls = {r.get('location', {}).get('@id') for r in valid_results if r.get('location')}
            kw_urls = {k.get('@id') for r in valid_results for k in r.get('keywords', []) if k.get('@id')}
            
            # Fetch all location and keyword data at once
            details_map = await fetch_all(session, list(loc_urls | kw_urls))

            # Map everything into your uniform format
            for result in valid_results:
                # Parse time
                start_time_str = result.get('start_time') or ""
                date_val, time_val = (start_time_str.split('T') if 'T' in start_time_str else (start_time_str, None))

                # Get Location Data
                loc_url = (result.get('location') or {}).get('@id')
                loc_json = details_map.get(loc_url, {})
                coords = (loc_json.get('position') or {}).get('coordinates') or []
                
                # Get Keywords/Tags
                tags = []
                for kw in result.get('keywords') or []:
                    kw_json = details_map.get(kw.get('@id'), {})
                    name = (kw_json.get('name') or {}).get('en') or (kw_json.get('name') or {}).get('fi')
                    if name: tags.append(name)

                local_events.append({
                    'title': (result.get('name') or {}).get('en') or (result.get('name') or {}).get('fi'),
                    'description': (result.get('description') or {}).get('en') or (result.get('description') or {}).get('fi'),
                    'location': (coords[0][::-1] if isinstance(coords[0], list) else coords[::-1]) if coords else None,
                    'venue': (loc_json.get('name') or {}).get('en') or (loc_json.get('name') or {}).get('fi'),
                    'date': date_val,
                    'time': time_val,
                    'price': 0,
                    'img_url': [img.get('url') for img in (result.get('images') or [])],
                    'tags': tags,
                    'signup_link': (result.get('info_url') or {}).get('en') or (result.get('info_url') or {}).get('fi'),
                    'created_by': 'LinkedEvents',
                    'created_at': str(date.today())
                })
            
            # Check for next page (in meta object)
            next_url = data.get('meta', {}).get('next') if data else None
            
    return local_events

def myhelsinki():
    today = date.today()
    end_date = today + GAP
    results_list = []
    try:
        page = 1
        while True:
            url = f"https://www.myhelsinki.fi/wp-json/mhb/v1/event_search?s=&page={page}&lang=en&posts_per_page=50&start_date={today}&end_date={end_date}"
            response = requests.get(url, headers=HEADERS)
            data = response.json()
            
            results = data.get('results') or []
            if not results:
                break

            for result in results:
                locations = result.get('locations') or []
                tags_data = result.get('tags') or []
                
                first_loc_obj = locations[0] if locations and isinstance(locations[0], dict) else {}
                
                loc_coords = first_loc_obj.get('location') 
                venue_name = first_loc_obj.get('title')
                
                results_list.append({
                    'title': result.get('title'),
                    'description': result.get('excerpt'),
                    'location': loc_coords if loc_coords else None,
                    'venue': venue_name if venue_name else None,
                    'date': result.get('start_date'),
                    'time': result.get('start_time_of_day'),
                    'price': None,
                    'img_url': result.get('image_url'),
                    'tags': [tag.get('name') for tag in tags_data if isinstance(tag, dict)],
                    'signup_link': result.get('external_url'),
                    'created_by': 'MyHelsinki',
                    'created_at': str(date.today())
                })
            
            page += 1
    except Exception as e:
        print(f"MyHelsinki error: {e}")
    return results_list

def luma():
    results_list = []
    try:
        base_url = "https://api.lu.ma/discover/get-paginated-events?discover_place_api_id=discplace-gEii5B2Ju5KKRNH&pagination_limit=25"
        url = base_url
        
        while url:
            response = requests.get(url, headers=HEADERS)
            data = response.json()

            for result in data.get('entries') or []:
                event_data = result.get('event') or {}
                ticket_info = result.get('ticket_info') or {}
                geo_info = event_data.get('geo_address_info') or {}
                coords = event_data.get('coordinate') or {}
                start_at = event_data.get('start_at') or ""
                date_val, time_val = (start_at.split('T') if 'T' in start_at else (start_at, None))

                # Extract venue name from address or full_address
                venue = geo_info.get('address') or geo_info.get('full_address')
                
                # Extract event API ID for signup link
                event_api_id = event_data.get('api_id')
                signup_link = f"https://luma.com/helsinki?e={event_api_id}" if event_api_id else None

                results_list.append({
                    'title': event_data.get('name'),
                    'description': event_data.get('description'),
                    'location': [coords.get('latitude'), coords.get('longitude')] if coords.get('latitude') and coords.get('longitude') else None,
                    'venue': venue,
                    'date': date_val,
                    'time': time_val,
                    'price': 0 if ticket_info.get('is_free') else ticket_info.get('price'),
                    'img_url': event_data.get('cover_url'),
                    'tags': None,
                    'signup_link': signup_link,
                    'created_by': 'Luma',
                    'created_at': str(date.today())
                })
            
            # Check for next page using cursor-based pagination
            next_cursor = data.get('next_cursor')
            if next_cursor and data.get('has_more'):
                url = f"{base_url}&pagination_cursor={next_cursor}"
            else:
                url = None
    except Exception as e:
        print(f"Luma error: {e}")
    return results_list

def lambda_handler(event, context):
    all_events = []
    query_params = event.get("queryStringParameters") or {}
    source_param = query_params.get("source", "all").lower()
    
    requested_sources = [s.strip() for s in source_param.split(",")]
    
    # We use ThreadPool for the sync scrapers and asyncio for the heavy one
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {}
        
        if "all" in requested_sources or "myhelsinki" in requested_sources:
            futures[executor.submit(myhelsinki)] = "myhelsinki"
        if "all" in requested_sources or "luma" in requested_sources:
            futures[executor.submit(luma)] = "luma"
            
        for future in as_completed(futures):
            all_events.extend(future.result())

    # LinkedEvents is special because we use the async version for speed
    if "all" in requested_sources or "linked_events" in requested_sources:
        linked_data = asyncio.run(get_linked_events())
        all_events.extend(linked_data)

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*", # Required for CORS
            "Access-Control-Allow-Methods": "GET, OPTIONS", # Allows the browser to fetch
            "Access-Control-Allow-Headers": "Content-Type, User-Agent" # Allows the headers you are sending
        },
        "body": json.dumps(all_events)
    }