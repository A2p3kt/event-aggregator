import boto3
import json
from decimal import Decimal
from boto3.dynamodb.conditions import Attr
from datetime import date

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('HelsinkiEvents')

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

def lambda_handler(event, context):
    # 1. Fetch all upcoming events (today or later)
    today = str(date.today())
    response = table.scan(
        FilterExpression=Attr('date').gte(today)
    )
    items = response.get('Items', [])

    # 2. Sort by date and then by time
    items.sort(key=lambda x: (str(x.get('date') or ''), str(x.get('time') or '')))

    # 3. Return the response with CORS headers
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",  # Allows your website to call this
            "Access-Control-Allow-Methods": "GET, OPTIONS"
        },
        "body": json.dumps({"events": _json_safe(items)}, default=decimal_default)
    }