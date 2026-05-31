from flask import Flask, jsonify
import webbrowser

app = Flask(__name__)

# ROOT ROUTE (OpenAPI Spec)
@app.route("/", methods=["GET"])
def root():
    return jsonify({
        "openapi": "3.0.0",
        "info": {
            "title": "Jarvis Tools",
            "version": "1.0.0"
        },
        "paths": {
            "/open_youtube": {
                "get": {
                    "summary": "Open YouTube",
                    "operationId": "openYoutube",
                    "responses": {
                        "200": {
                            "description": "Success"
                        }
                    }
                }
            }
        }
    })

# TOOL ROUTE
@app.route("/open_youtube", methods=["GET"])
def open_youtube():
    webbrowser.open("https://youtube.com")

    return jsonify({
        "status": "success",
        "message": "YouTube opened"
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)