import boto3
import json
from decimal import Decimal
from boto3.dynamodb.conditions import Key
from datetime import datetime, timezone

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
    # Generate the current exact UTC time
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    
    items = []
    
    # Configure the Query using start_time
    query_kwargs = {
        'IndexName': 'EventStatusDateIndex',
        'KeyConditionExpression': Key('event_status').eq('active') & Key('start_time').gte(now)
    }
    
    done = False
    start_key = None
    
    # Fetch all matching events with pagination
    while not done:
        if start_key:
            query_kwargs['ExclusiveStartKey'] = start_key
            
        response = table.query(**query_kwargs)
        items.extend(response.get('Items', []))
        
        start_key = response.get('LastEvaluatedKey', None)
        done = start_key is None


    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS"
        },
        "body": json.dumps({"events": _json_safe(items)}, default=decimal_default)
    }