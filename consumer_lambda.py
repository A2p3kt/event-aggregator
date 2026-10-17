import boto3
import json
import base64
import binascii
from decimal import Decimal
from boto3.dynamodb.conditions import Key
from datetime import datetime, timezone

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('HelsinkiEvents')
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS"
}

def decimal_default(obj):
    """Helper to convert Decimal to int/float for JSON."""
    if isinstance(obj, Decimal):
        return float(obj) if obj % 1 > 0 else int(obj)
    raise TypeError

def _json_safe(value):
    if isinstance(value, Decimal):
        return decimal_default(value)
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    return value

def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": HEADERS,
        "body": json.dumps(body, default=decimal_default)
    }

def _decode_next_token(token):
    try:
        padded_token = token + "=" * (-len(token) % 4)
        return json.loads(base64.urlsafe_b64decode(padded_token).decode("utf-8"))
    except (ValueError, TypeError, UnicodeDecodeError, binascii.Error) as exc:
        raise ValueError("next_token must be a valid continuation token") from exc

def _encode_next_token(last_evaluated_key):
    token_json = json.dumps(last_evaluated_key, default=decimal_default)
    return base64.urlsafe_b64encode(token_json.encode("utf-8")).decode("ascii").rstrip("=")

def lambda_handler(event, context):
    # Generate the current exact UTC time
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    query_parameters = (event or {}).get("queryStringParameters") or {}
    try:
        page_size = int(query_parameters.get("limit", DEFAULT_PAGE_SIZE))
    except (TypeError, ValueError):
        return _response(400, {"error": "limit must be an integer"})

    if not 1 <= page_size <= MAX_PAGE_SIZE:
        return _response(400, {"error": f"limit must be between 1 and {MAX_PAGE_SIZE}"})

    # Configure the Query using start_time
    query_kwargs = {
        'IndexName': 'EventStatusDateIndex',
        'KeyConditionExpression': Key('event_status').eq('active') & Key('start_time').gte(now),
        'Limit': page_size
    }

    next_token = query_parameters.get("next_token")
    if next_token:
        try:
            query_kwargs["ExclusiveStartKey"] = _decode_next_token(next_token)
        except ValueError as exc:
            return _response(400, {"error": str(exc)})

    response = table.query(**query_kwargs)
    body = {"events": _json_safe(response.get("Items", []))}
    last_evaluated_key = response.get("LastEvaluatedKey")
    if last_evaluated_key:
        body["next_token"] = _encode_next_token(last_evaluated_key)

    return _response(200, body)
