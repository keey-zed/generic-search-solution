from app import create_app
from flask_cors import CORS

app = create_app()
CORS(app)

if __name__ == "__main__":
    # ✅ Waitress instead of Flask dev server
    #from waitress import serve

    # threads: increase if you have many concurrent users/requests
    #serve(app, host="0.0.0.0", port=5000, threads=8)
    app.run(host="0.0.0.0", port=5000, debug=True)
