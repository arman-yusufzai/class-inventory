"""Basic Inventory System - backend.

Local:   pip install -r requirements.txt
         python backend.py   ->  http://127.0.0.1:5000
Render:  build   pip install -r requirements.txt
         start   gunicorn backend:app
         env     ALLOWED_ORIGIN = your Netlify URL (optional, default allows all)
                 DATA_FILE      = path on a persistent disk (optional)
"""
import json
import os
from dataclasses import dataclass, asdict

from flask import Flask, jsonify, request, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.environ.get("DATA_FILE", os.path.join(BASE_DIR, "inventory.json"))
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")


@dataclass
class Item:
    id: int
    name: str
    category: str
    quantity: int
    price: float
    low_stock_at: int = 5

    @property
    def is_low(self) -> bool:
        return self.quantity <= self.low_stock_at

    def to_dict(self) -> dict:
        d = asdict(self)
        d["is_low"] = self.is_low
        return d


class Inventory:
    """Holds items in memory and saves them to a JSON file."""

    def __init__(self, path: str):
        self.path = path
        self.items: dict[int, Item] = {}
        self.next_id = 1
        self._load()

    # ---------- persistence ----------
    def _load(self):
        if not os.path.exists(self.path):
            return
        with open(self.path, "r", encoding="utf-8") as f:
            for raw in json.load(f):
                item = Item(**raw)
                self.items[item.id] = item
        self.next_id = max(self.items, default=0) + 1

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump([asdict(i) for i in self.items.values()], f, indent=2)

    # ---------- operations ----------
    @staticmethod
    def _validate(data: dict) -> dict:
        name = str(data.get("name", "")).strip()
        if not name:
            raise ValueError("Name is required.")
        try:
            quantity = int(data.get("quantity", 0))
            price = float(data.get("price", 0))
            low = int(data.get("low_stock_at", 5))
        except (TypeError, ValueError):
            raise ValueError("Quantity, price and low-stock level must be numbers.")
        if quantity < 0 or price < 0 or low < 0:
            raise ValueError("Numbers cannot be negative.")
        return {
            "name": name,
            "category": str(data.get("category", "")).strip() or "General",
            "quantity": quantity,
            "price": round(price, 2),
            "low_stock_at": low,
        }

    def add(self, data: dict) -> Item:
        item = Item(id=self.next_id, **self._validate(data))
        self.items[item.id] = item
        self.next_id += 1
        self._save()
        return item

    def update(self, item_id: int, data: dict) -> Item:
        if item_id not in self.items:
            raise KeyError("Item not found.")
        item = Item(id=item_id, **self._validate({**asdict(self.items[item_id]), **data}))
        self.items[item_id] = item
        self._save()
        return item

    def remove(self, item_id: int):
        if item_id not in self.items:
            raise KeyError("Item not found.")
        del self.items[item_id]
        self._save()

    def search(self, query: str = "") -> list:
        q = query.lower().strip()
        return [
            i for i in self.items.values()
            if not q or q in i.name.lower() or q in i.category.lower()
        ]

    def summary(self) -> dict:
        items = self.items.values()
        return {
            "total_items": len(self.items),
            "total_units": sum(i.quantity for i in items),
            "total_value": round(sum(i.quantity * i.price for i in items), 2),
            "low_stock": sum(1 for i in items if i.is_low),
        }


# ---------- Flask API ----------
app = Flask(__name__)
inventory = Inventory(DATA_FILE)


@app.after_request
def allow_cors(resp):  # lets the Netlify-hosted index.html call this API
    resp.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return resp


@app.route("/")
def home():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/api/items", methods=["GET"])
def list_items():
    items = inventory.search(request.args.get("q", ""))
    return jsonify({
        "items": [i.to_dict() for i in sorted(items, key=lambda i: i.name.lower())],
        "summary": inventory.summary(),
    })


@app.route("/api/items", methods=["POST"])
def add_item():
    try:
        item = inventory.add(request.get_json(force=True))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(item.to_dict()), 201


@app.route("/api/items/<int:item_id>", methods=["PUT"])
def update_item(item_id):
    try:
        item = inventory.update(item_id, request.get_json(force=True))
    except KeyError as e:
        return jsonify({"error": e.args[0]}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(item.to_dict())


@app.route("/api/items/<int:item_id>", methods=["DELETE"])
def delete_item(item_id):
    try:
        inventory.remove(item_id)
    except KeyError as e:
        return jsonify({"error": e.args[0]}), 404
    return jsonify({"deleted": item_id})


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    # Render sets PORT; locally this falls back to 5000.
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1" or "PORT" not in os.environ)
