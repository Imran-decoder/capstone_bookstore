import boto3
import os
import sys
import argparse
from botocore.exceptions import ClientError
from decimal import Decimal
from werkzeug.security import generate_password_hash

# =======================
# AWS CONFIGURATION
# =======================
AWS_REGION = "us-east-1"
SNS_TOPIC_ARN = "arn:aws:sns:us-east-1:148761657981:bookstore_notification"

DYNAMODB_BOOKS_TABLE = "BookBazaarBooks"
DYNAMODB_USERS_TABLE = "BookBazaarUsers"
DYNAMODB_ORDERS_TABLE = "BookBazaarOrders"


# =======================
# AWS CORE APP
# =======================
class AWSApp:
    """Central point for AWS resource management."""

    def __init__(self):
        self.region = AWS_REGION
        self._dynamodb = None
        self._sns = None

    def check_iam_permission(self, user_role, resource):
        permissions = {
            "admin": ["*"],
            "seller": ["books:add", "books:delete", "sales:view"],
            "buyer": ["books:view", "orders:create"]
        }
        allowed = permissions.get(user_role, [])
        return "*" in allowed or resource in allowed

    @property
    def dynamodb(self):
        if self._dynamodb is None:
            self._dynamodb = boto3.resource("dynamodb", region_name=self.region)
        return self._dynamodb

    @property
    def sns(self):
        if self._sns is None:
            self._sns = boto3.client("sns", region_name=self.region)
        return self._sns


aws_app = AWSApp()


# =======================
# SNS NOTIFIER
# =======================
class SNSNotifier:
    def __init__(self, aws_instance=None):
        self.aws = aws_instance or aws_app
        self.topic_arn = SNS_TOPIC_ARN

    def send(self, email, message):
        try:
            self.aws.sns.publish(
                TopicArn=self.topic_arn,
                Message=message,
                Subject="BookBazaar Notification"
            )
            print(f"[SNS] Notification sent to {email}")
        except ClientError as e:
            print(f"[SNS ERROR] {e.response['Error']['Message']}")


# =======================
# DYNAMODB REPOSITORIES
# =======================
class DynamoBookRepository:
    def __init__(self, aws_instance=None):
        self.aws = aws_instance or aws_app
        self.table = self.aws.dynamodb.Table(DYNAMODB_BOOKS_TABLE)

    def get_paginated(self, limit=8, last_key=None):
        try:
            params = {
                "IndexName": "TypeIndex",
                "KeyConditionExpression": boto3.dynamodb.conditions.Key("type").eq("book"),
                "Limit": limit
            }
            if last_key:
                params["ExclusiveStartKey"] = last_key

            res = self.table.query(**params)
            return res.get("Items", []), res.get("LastEvaluatedKey")
        except ClientError as e:
            print(e)
            return [], None

    def add(self, book):
        book["type"] = "book"
        if "price" in book:
            book["price"] = Decimal(str(book["price"]))
        self.table.put_item(Item=book)


class DynamoUserRepository:
    def __init__(self, aws_instance=None):
        self.aws = aws_instance or aws_app
        self.table = self.aws.dynamodb.Table(DYNAMODB_USERS_TABLE)

    def get_by_email(self, email):
        res = self.table.scan(
            FilterExpression=boto3.dynamodb.conditions.Attr("email").eq(email)
        )
        items = res.get("Items", [])
        return items[0] if items else None

    def add(self, user):
        self.table.put_item(Item=user)


class DynamoOrderRepository:
    def __init__(self, aws_instance=None):
        self.aws = aws_instance or aws_app
        self.table = self.aws.dynamodb.Table(DYNAMODB_ORDERS_TABLE)

    def add(self, order):
        if "total_price" in order:
            order["total_price"] = Decimal(str(order["total_price"]))
        self.table.put_item(Item=order)


# =======================
# AWS SETUP / VERIFY
# =======================
def verify_aws():
    print("Verifying AWS Integration")
    print("-" * 30)

    boto3.client("sts").get_caller_identity()
    print("[OK] AWS credentials")

    DynamoBookRepository().table.scan(Limit=1)
    print("[OK] DynamoDB")

    SNSNotifier().send("test@example.com", "AWS Verification")
    print("[OK] SNS")


# =======================
# DATABASE SEED
# =======================
def seed_db():
    import csv

    base = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base, "data")

    users = DynamoUserRepository()
    books = DynamoBookRepository()
    orders = DynamoOrderRepository()

    user_map = {}
    with open(os.path.join(data_dir, "users.csv")) as f:
        for i, row in enumerate(csv.DictReader(f), 1):
            uid = f"u{i}"
            users.add({
                "id": uid,
                "username": row["username"],
                "email": row["email"],
                "role": row["role"],
                "password_hash": generate_password_hash(row["password"])
            })
            user_map[row["username"]] = uid

    with open(os.path.join(data_dir, "books.csv")) as f:
        for i, row in enumerate(csv.DictReader(f), 1):
            books.add({
                "id": f"b{i}",
                "title": row["title"],
                "author": row["author"],
                "price": float(row["price"]),
                "stock": int(row["stock"]),
                "seller_id": user_map.get(row["seller_username"], "u1")
            })

    with open(os.path.join(data_dir, "orders.csv")) as f:
        for i, row in enumerate(csv.DictReader(f), 1):
            orders.add({
                "id": f"o{i}",
                "user_id": user_map.get(row["buyer_username"], "u1"),
                "total_price": float(row["total_price"]),
                "status": row["status"]
            })

    print("✓ Database seeded")


# =======================
# RUN FLASK SERVER
# =======================
def run_server():
    print("Starting BookBazaar Web Server...")
    print("http://<EC2-PUBLIC-IP>:5000")

    project_root = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, project_root)

    from app import create_app
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=False)


# =======================
# CLI
# =======================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", default="run",
                        choices=["run", "verify", "seed"])
    args = parser.parse_args()

    if args.command == "verify":
        verify_aws()
    elif args.command == "seed":
        seed_db()
    else:
        run_server()
