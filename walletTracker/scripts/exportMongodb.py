from pymongo import MongoClient
from bson.json_util import dumps
import os

client = MongoClient("mongodb+srv://andrewliu:xGMymy8wQ2vaL2No@cluster0.famk0m5.mongodb.net/hyperliquid?retryWrites=true&w=majority&authSource=admin")
db = client["hyperliquid"]

os.makedirs("mongo_backup", exist_ok=True)

for name in db.list_collection_names():
    cursor = db[name].find({})
    path = os.path.join("mongo_backup", f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write(dumps(cursor))
