import json
import asyncio
import aiohttp
import math
import boto3
from decimal import Decimal
from datetime import date, datetime, timedelta, timezone

# Global configuration
GAP = timedelta(days=100)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
MAX_CONCURRENCY = 10
TABLE_NAME = "HelsinkiEvents"


def _calculate_ttl(date_str, time_str=None):
    """Compute TTL as event datetime + 24h (unix timestamp)."""
    try:
        if not date_str:
            base_dt = datetime.now(timezone.utc)
        else:
            clean_date = str(date_str).strip()
            clean_time = (time_str or "00:00:00").strip()

            if "T" in clean_date:
                dt_raw = clean_date.replace("Z", "+00:00")
            else:
                clean_time = clean_time.replace("Z", "")
                dt_raw = f"{clean_date}T{clean_time}"

            base_dt = datetime.fromisoformat(dt_raw)
            if base_dt.tzinfo is None:
                base_dt = base_dt.replace(tzinfo=timezone.utc)
            else:
                base_dt = base_dt.astimezone(timezone.utc)

        return int((base_dt + timedelta(hours=24)).timestamp())
    except Exception:
        return int((datetime.now(timezone.utc) + timedelta(hours=24)).timestamp())


def _to_dynamodb_types(value):
    """Convert Python values recursively into DynamoDB-safe types."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, list):
        return [_to_dynamodb_types(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_dynamodb_types(v) for k, v in value.items()}
    return value


def _chunk(items, size=25):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def upsert_events_to_dynamodb(events):
    """Upsert events into DynamoDB in 25-item batches."""
    table = boto3.resource("dynamodb").Table(TABLE_NAME)
    processed = 0
    key_schema = getattr(table, "key_schema", []) or []
    key_names = [key.get("AttributeName") for key in key_schema if key.get("AttributeName")]
    has_sort_key = any(key.get("KeyType") == "RANGE" for key in key_schema)
    batch_writer_kwargs = {"overwrite_by_pkeys": key_names} if has_sort_key and key_names else {}

    for batch in _chunk(events, 25):
        with table.batch_writer(**batch_writer_kwargs) as writer:
            for item in batch:
                if not item.get("id") or not item.get("date"):
                    continue
                writer.put_item(Item=_to_dynamodb_types(item))
                processed += 1

    return processed


async def fetch_json(session, sem, url):
    """Fetch a single JSON URL with concurrency limiting."""
    async with sem:
        async with session.get(url, headers=HEADERS) as resp:
            if resp.status != 200:
                return None
            try:
                return await resp.json()
            except Exception:
                return None

async def fetch_all(session, sem, urls):
    """Utility to fetch multiple URLs concurrently."""
    valid_urls = [url for url in urls if url]
    tasks = [fetch_json(session, sem, url) for url in valid_urls]
    responses = await asyncio.gather(*tasks, return_exceptions=True)

    results_map = {}
    for url, data in zip(valid_urls, responses):
        if isinstance(data, Exception) or not data:
            continue
        results_map[url] = data
    return results_map


async def get_linked_events(session, sem):
    """Fetch LinkedEvents with parallel pagination and one burst of nested lookups."""
    start_date = date.today()
    end_date = start_date + GAP
    page_size = 100
    base_url = f'https://api.hel.fi/linkedevents/v1/event/?start={start_date}&end={end_date}&is_free=true&page_size={page_size}'

    local_events = []

    first_page = await fetch_json(session, sem, base_url)
    if not first_page:
        return []

    all_results = list(first_page.get('data', []) or [])
    total_count = (first_page.get('meta') or {}).get('count') or len(all_results)
    total_pages = max(1, math.ceil(total_count / page_size))

    if total_pages > 1:
        page_urls = [
            f'https://api.hel.fi/linkedevents/v1/event/?start={start_date}&end={end_date}&is_free=true&page_size={page_size}&page={page}'
            for page in range(2, total_pages + 1)
        ]
        page_payloads = await asyncio.gather(*[fetch_json(session, sem, url) for url in page_urls])
        for payload in page_payloads:
            if payload:
                all_results.extend(payload.get('data', []) or [])

    valid_results = [r for r in all_results if r.get('event_status') not in ('EventCancelled', 'EventPostponed')]

    # Burst-fetch all nested location and keyword docs once.
    loc_urls = {r.get('location', {}).get('@id') for r in valid_results if r.get('location')}
    kw_urls = {k.get('@id') for r in valid_results for k in r.get('keywords', []) if k.get('@id')}
    details_map = await fetch_all(session, sem, list(loc_urls | kw_urls))

    for result in valid_results:
        start_time_str = result.get('start_time') or ""
        date_val, time_val = (start_time_str.split('T') if 'T' in start_time_str else (start_time_str, None))
        linked_id = result.get('id')

        loc_url = (result.get('location') or {}).get('@id')
        loc_json = details_map.get(loc_url, {})
        coords = (loc_json.get('position') or {}).get('coordinates') or []

        tags = []
        for kw in result.get('keywords') or []:
            kw_json = details_map.get(kw.get('@id'), {})
            name = (kw_json.get('name') or {}).get('en') or (kw_json.get('name') or {}).get('fi')
            if name:
                tags.append(name)

        local_events.append({
            'id': f"linked-{linked_id}" if linked_id else None,
            'start_time': start_time_str,
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
            'created_at': str(date.today()),
            'event_status': 'active',
            'ttl': _calculate_ttl(date_val, time_val)
        })

    return local_events


async def myhelsinki(session, sem):
    today = date.today()
    end_date = today + GAP
    results_list = []
    try:
        page_size = 50
        first_url = f"https://www.myhelsinki.fi/wp-json/mhb/v1/event_search?s=&page=1&lang=en&posts_per_page={page_size}&start_date={today}&end_date={end_date}"
        first_page = await fetch_json(session, sem, first_url)
        if not first_page:
            return []

        all_results = list(first_page.get('results') or [])
        total_pages = first_page.get('total_pages') or 1

        if total_pages > 1:
            page_urls = [
                f"https://www.myhelsinki.fi/wp-json/mhb/v1/event_search?s=&page={page}&lang=en&posts_per_page={page_size}&start_date={today}&end_date={end_date}"
                for page in range(2, total_pages + 1)
            ]
            page_payloads = await asyncio.gather(*[fetch_json(session, sem, url) for url in page_urls])
            for payload in page_payloads:
                if payload:
                    all_results.extend(payload.get('results') or [])

        for result in all_results:
            locations = result.get('locations') or []
            tags_data = result.get('tags') or []
            item_id = result.get('id') or result.get('ID')

            first_loc_obj = locations[0] if locations and isinstance(locations[0], dict) else {}
            loc_coords = first_loc_obj.get('location')
            venue_name = first_loc_obj.get('title')

            date_val = result.get('start_date')
            time_val = result.get('start_time_of_day')
            start_time_str = f"{date_val}T{time_val}" if date_val and time_val else date_val

            results_list.append({
                'id': f"myhel-{item_id}" if item_id else None,
                'start_time': start_time_str,
                'title': result.get('title'),
                'description': result.get('excerpt'),
                'location': loc_coords if loc_coords else None,
                'venue': venue_name if venue_name else None,
                'date': date_val,
                'time': time_val,
                'price': None,
                'img_url': result.get('image_url'),
                'tags': [tag.get('name') for tag in tags_data if isinstance(tag, dict)],
                'signup_link': result.get('external_url'),
                'created_by': 'MyHelsinki',
                'created_at': str(date.today()),
                'event_status': 'active',
                'ttl': _calculate_ttl(date_val, time_val)
            })
    except Exception as e:
        print(f"MyHelsinki error: {e}")
    return results_list


def _extract_luma_total_count(payload):
    """Best-effort total count extraction from Luma payload variants."""
    if not payload:
        return None
    if isinstance(payload.get('meta'), dict):
        return payload.get('meta', {}).get('count') or payload.get('meta', {}).get('total')
    return payload.get('count') or payload.get('total') or payload.get('total_count')


async def luma(session, sem):
    results_list = []
    try:
        page_size = 25
        base_url = f"https://api.lu.ma/discover/get-paginated-events?discover_place_api_id=discplace-gEii5B2Ju5KKRNH&pagination_limit={page_size}"
        first_page = await fetch_json(session, sem, base_url)
        if not first_page:
            return []

        all_entries = list(first_page.get('entries') or [])
        total_count = _extract_luma_total_count(first_page)

        if total_count:
            total_pages = max(1, math.ceil(total_count / page_size))
            if total_pages > 1:
                page_urls = [
                    f"{base_url}&pagination_page={page}"
                    for page in range(2, total_pages + 1)
                ]
                page_payloads = await asyncio.gather(*[fetch_json(session, sem, url) for url in page_urls])
                for payload in page_payloads:
                    if payload:
                        all_entries.extend(payload.get('entries') or [])
        elif first_page.get('has_more') and first_page.get('next_cursor'):
            # Fallback for cursor-only payloads where a total count is not provided.
            cursor = first_page.get('next_cursor')
            while cursor:
                page_payload = await fetch_json(session, sem, f"{base_url}&pagination_cursor={cursor}")
                if not page_payload:
                    break
                all_entries.extend(page_payload.get('entries') or [])
                if page_payload.get('has_more') and page_payload.get('next_cursor'):
                    cursor = page_payload.get('next_cursor')
                else:
                    cursor = None

        for result in all_entries:
            event_data = result.get('event') or {}
            ticket_info = result.get('ticket_info') or {}
            geo_info = event_data.get('geo_address_info') or {}
            coords = event_data.get('coordinate') or {}
            start_at = event_data.get('start_at') or ""
            date_val, time_val = (start_at.split('T') if 'T' in start_at else (start_at, None))

            venue = geo_info.get('address') or geo_info.get('full_address')
            event_api_id = event_data.get('api_id')
            signup_link = f"https://luma.com/helsinki?e={event_api_id}" if event_api_id else None

            results_list.append({
                'id': f"luma-{event_api_id}" if event_api_id else None,
                'start_time': start_at,
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
                'created_at': str(date.today()),
                'event_status': 'active',
                'ttl': _calculate_ttl(date_val, time_val)
            })
    except Exception as e:
        print(f"Luma error: {e}")
    return results_list


async def collect_events(requested_sources):
    all_events = []
    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    async with aiohttp.ClientSession() as session:
        tasks = []
        if "all" in requested_sources or "myhelsinki" in requested_sources:
            tasks.append(myhelsinki(session, sem))
        if "all" in requested_sources or "luma" in requested_sources:
            tasks.append(luma(session, sem))
        if "all" in requested_sources or "linked_events" in requested_sources:
            tasks.append(get_linked_events(session, sem))

        if tasks:
            results = await asyncio.gather(*tasks)
            for source_events in results:
                all_events.extend(source_events)

    processed_count = await asyncio.to_thread(upsert_events_to_dynamodb, all_events)
    return processed_count


def lambda_handler(event, context):
    query_params = event.get("queryStringParameters") or {}
    source_param = query_params.get("source", "all").lower()
    requested_sources = [s.strip() for s in source_param.split(",")]

    events_processed = asyncio.run(collect_events(requested_sources))

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*", # Required for CORS
            "Access-Control-Allow-Methods": "GET, OPTIONS", # Allows the browser to fetch
            "Access-Control-Allow-Headers": "Content-Type, User-Agent" # Allows the headers you are sending
        },
        "body": json.dumps({"status": "success", "events_processed": events_processed})
    }