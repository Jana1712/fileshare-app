import os
import random
import string
import time
import threading
from flask import Flask, request, send_file, render_template, abort, url_for
from werkzeug.utils import secure_filename

app = Flask(__name__)


UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

UPLOAD_FOLDER_PATH = os.path.abspath(UPLOAD_FOLDER)

DEFAULT_MAX_FILE_SIZE = 25  # MB
DEFAULT_LINK_EXPIRY = 15    # minutes


MAX_FILE_SIZE_MB = DEFAULT_MAX_FILE_SIZE
LINK_EXPIRY_MINUTES = DEFAULT_LINK_EXPIRY


app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE_MB * 1024 * 1024
LINK_EXPIRY_SECONDS = LINK_EXPIRY_MINUTES * 60


app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')


file_links = {}

def generate_random_string(length=8):
    """Generate random ID for each file link"""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

@app.errorhandler(413)
def file_too_large(e):
    return f"File is too large. Max limit is {MAX_FILE_SIZE_MB} MB.", 413

@app.route("/", methods=["GET", "POST"])
def upload():
    global MAX_FILE_SIZE_MB, LINK_EXPIRY_MINUTES, LINK_EXPIRY_SECONDS
    
    if request.method == "POST":
        
        if 'update_settings' in request.form:
            try:
                new_size = int(request.form.get('max_file_size', DEFAULT_MAX_FILE_SIZE))
                new_expiry = int(request.form.get('link_expiry', DEFAULT_LINK_EXPIRY))
                
                
                if new_size < 1 or new_size > 100:
                    return render_template("index.html", link=None, error="File size must be between 1 and 100 MB",
                                         max_file_size=MAX_FILE_SIZE_MB, 
                                         link_expiry=LINK_EXPIRY_MINUTES)
                
                if new_expiry < 1 or new_expiry > 1440:
                    return render_template("index.html", link=None, error="Expiry time must be between 1 and 1440 minutes",
                                         max_file_size=MAX_FILE_SIZE_MB, 
                                         link_expiry=LINK_EXPIRY_MINUTES)
                
                
                MAX_FILE_SIZE_MB = new_size
                LINK_EXPIRY_MINUTES = new_expiry
                app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE_MB * 1024 * 1024
                LINK_EXPIRY_SECONDS = LINK_EXPIRY_MINUTES * 60
                
                return render_template("index.html", link=None, error=None, 
                                      max_file_size=MAX_FILE_SIZE_MB, 
                                      link_expiry=LINK_EXPIRY_MINUTES,
                                      settings_updated=True)
            
            except ValueError:
                return render_template("index.html", link=None, error="Invalid settings values",
                                     max_file_size=MAX_FILE_SIZE_MB, 
                                     link_expiry=LINK_EXPIRY_MINUTES)
        
        
        if 'file' not in request.files:
            return render_template("index.html", link=None, error="No file selected", 
                                 max_file_size=MAX_FILE_SIZE_MB, 
                                 link_expiry=LINK_EXPIRY_MINUTES)

        file = request.files['file']
        if file.filename == "":
            return render_template("index.html", link=None, error="No file selected",
                                 max_file_size=MAX_FILE_SIZE_MB, 
                                 link_expiry=LINK_EXPIRY_MINUTES)

        
        current_expiry = int(request.form.get('link_expiry', LINK_EXPIRY_MINUTES))
        current_max_size = int(request.form.get('max_file_size', MAX_FILE_SIZE_MB))

        
        file.seek(0, os.SEEK_END)
        file_length = file.tell()
        file.seek(0)
        
        if file_length > current_max_size * 1024 * 1024:
            return render_template("index.html", link=None, error=f"File is too large. Max limit is {current_max_size} MB.",
                                 max_file_size=MAX_FILE_SIZE_MB, 
                                 link_expiry=LINK_EXPIRY_MINUTES)

        
        filename = secure_filename(file.filename)
        unique_filename = f"{int(time.time())}_{filename}"
        filepath = os.path.join(UPLOAD_FOLDER_PATH, unique_filename)
        
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        try:
            file.save(filepath)
        except Exception as e:
            return render_template("index.html", link=None, error=f"Error saving file: {e}",
                                 max_file_size=MAX_FILE_SIZE_MB, 
                                 link_expiry=LINK_EXPIRY_MINUTES)

        
        random_id = generate_random_string()
        file_links[random_id] = {
            "path": filepath,
            "time": time.time(),
            "expiry": current_expiry * 60,
            "filename": filename
        }

        share_link = url_for('download', random_id=random_id, _external=True)
        
        return render_template("index.html", link=share_link, error=None,
                             max_file_size=MAX_FILE_SIZE_MB, 
                             link_expiry=LINK_EXPIRY_MINUTES,
                             file_expiry=current_expiry)

    return render_template("index.html", link=None, error=None,
                         max_file_size=MAX_FILE_SIZE_MB, 
                         link_expiry=LINK_EXPIRY_MINUTES)

@app.route("/download/<random_id>")
def download(random_id):
    """Serve the file if link is still valid"""
    file_info = file_links.get(random_id)
    if not file_info:
        return "Invalid or expired link", 404

    if time.time() - file_info["time"] > file_info["expiry"]:
        try:
            if os.path.exists(file_info["path"]):
                os.remove(file_info["path"])
        except:
            pass
        del file_links[random_id]
        return "Link has expired", 410

    if not os.path.exists(file_info["path"]):
        del file_links[random_id]
        return "File not found", 404
    
    return send_file(
        file_info["path"], 
        as_attachment=True, 
        download_name=file_info["filename"],
        mimetype='application/octet-stream'
    )

def cleanup_expired_files():
    """Periodically remove expired files"""
    while True:
        now = time.time()
        expired_keys = []
        for key, info in list(file_links.items()):
            if now - info["time"] > info["expiry"]:
                try:
                    if os.path.exists(info["path"]):
                        os.remove(info["path"])
                except:
                    pass
                expired_keys.append(key)

        for key in expired_keys:
            try:
                del file_links[key]
            except:
                pass

        time.sleep(60)

threading.Thread(target=cleanup_expired_files, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
