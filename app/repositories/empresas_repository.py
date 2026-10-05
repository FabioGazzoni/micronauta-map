import boto3
from boto3.dynamodb.types import TypeDeserializer

_deserializer = TypeDeserializer()


def scan_habilitadas(table_arn: str) -> list[dict]:
    """
    Businesses con is_downloaded=true, solo con nombre y sub-empresas. Se usa
    el ARN como TableName porque la tabla es de otra cuenta (acceso por
    política de recursos de la tabla).
    """
    region = table_arn.split(":")[3]
    client = boto3.client("dynamodb", region_name=region)

    items = []
    for page in client.get_paginator("scan").paginate(
        TableName=table_arn,
        FilterExpression="is_downloaded = :t",
        ExpressionAttributeValues={":t": {"BOOL": True}},
        ProjectionExpression="id, #n, download_data.sub_empresas",
        ExpressionAttributeNames={"#n": "name"},
    ):
        items.extend(page["Items"])

    return [deserialize(item) for item in items]


def deserialize(item: dict) -> dict:
    """Formato DynamoDB ({"S": ...}, {"N": ...}) -> dict de Python."""
    return {k: _deserializer.deserialize(v) for k, v in item.items()}
