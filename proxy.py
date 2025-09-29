import os
import time
import traceback
import requests
import base64
import uuid

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

API_BASE = "https://api.tripo3d.ai/v2/openapi"
API_KEY = os.getenv("TRIPO_API_KEY")
IMGBB_API_KEY = os.getenv("IMGBB_API_KEY")

UPLOAD_FOLDER = os.path.join("static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
CORS(app)

def save_base64_image(base64_data):
    header, encoded = base64_data.split(",", 1)
    ext = header.split("/")[1].split(";")[0]
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    with open(filepath, "wb") as f:
        f.write(base64.b64decode(encoded))
    return filepath

def upload_to_imgbb(filepath):
    with open(filepath, "rb") as f:
        image_data = f.read()
    encoded_string = base64.b64encode(image_data).decode("utf-8")
    url = "https://api.imgbb.com/1/upload"
    payload = {
        "key": IMGBB_API_KEY,
        "image": encoded_string,
    }
    response = requests.post(url, data=payload)
    response.raise_for_status()
    json_response = response.json()
    if not json_response.get("success"):
        raise Exception(f"ImgBB upload failed: {json_response.get('error', {}).get('message', 'Unknown error')}")
    return json_response["data"]["url"]

def create_task(image_url, texture="standard", texture_alignment="original_image"):
    payload = {
        "type": "generation",
        "model": "image-to-3d",
        "input": {
            "image_url": image_url,
            "texture": texture,
            "texture_alignment": texture_alignment
        }
    }
    print(">>> Payload:", payload)
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    resp = requests.post(f"{API_BASE}/task", json=payload, headers=headers)
    print(f">>> Response {resp.status_code}:", resp.text)
    resp.raise_for_status()
    return resp.json()["data"]["task_id"]



def poll_task(task_id, max_retry=60, interval=3):
    headers = {"Authorization": f"Bearer {API_KEY}"}
    for _ in range(max_retry):
        resp = requests.get(f"{API_BASE}/task/{task_id}", headers=headers)
        resp.raise_for_status()
        d = resp.json().get("data", {})
        status = d.get("status")
        if status == "success":
            return d.get("output", {})
        if status in ("fail", "error"):
            raise Exception(f"Task failed: {resp.text}")
        time.sleep(interval)
    raise TimeoutError("Task polling timeout")

@app.route("/tripo", methods=["POST"])
def tripo():
    try:
        j = request.get_json(force=True)
        image_uri = j.get("image_url") or j.get("image_base64")
        if not image_uri:
            return jsonify(error="Missing image data"), 400

        if image_uri.startswith("data:image/"):
            print(">>> Detected Base64 image, saving locally...")
            local_path = save_base64_image(image_uri)
            print(">>> Saved locally:", local_path)
            print(">>> Uploading to ImgBB...")
            image_uri = upload_to_imgbb(local_path)
            print(">>> ImgBB URL:", image_uri)

        task_id = create_task(image_uri)
        output = poll_task(task_id)

        model_url = output.get("model_mesh", {}).get("url")
        preview_url = output.get("rendered_image", {}).get("url")
        return jsonify(model_url=model_url, preview_url=preview_url)

    except Exception as e:
        traceback.print_exc()
        return jsonify(error=str(e)), 500

@app.route("/")
def home():
    return send_from_directory("static", "index.html")

@app.route("/static/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

if __name__ == "__main__":
    app.run(debug=True)
