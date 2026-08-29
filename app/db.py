import boto3
from botocore.exceptions import ClientError
from .config import settings

class DynamoDBRepository:
    def __init__(self):
        self.dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
        self.table = self.dynamodb.Table(settings.dynamodb_table)

    def get(self, short_code: str):
        response = self.table.get_item(Key={"shortCode": short_code}, ConsistentRead=True)
        return response.get("Item")

    def put(self, item: dict):
        self.table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(shortCode)",
        )

    def increment_clicks(self, short_code: str):
        try:
            response = self.table.update_item(
                Key={"shortCode": short_code},
                UpdateExpression="SET clickCount = if_not_exists(clickCount, :zero) + :one",
                ExpressionAttributeValues={":zero": 0, ":one": 1},
                ReturnValues="UPDATED_NEW",
            )
            return response.get("Attributes", {}).get("clickCount", 1)
        except ClientError:
            return None

    def delete(self, short_code: str):
        response = self.table.update_item(
            Key={"shortCode": short_code},
            UpdateExpression="SET isActive = :false",
            ExpressionAttributeValues={":false": False},
            ReturnValues="ALL_NEW",
        )
        return response.get("Attributes")
