from flask import Flask, render_template, Response, jsonify, request, redirect, url_for, session
import cv2
import numpy as np
from tensorflow.keras.models import load_model # type: ignore
from flask_socketio import SocketIO, emit
import os
import io, base64
from datetime import datetime
import json

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production'
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=10000000)

# Load emotion model
model_path = os.path.join(os.path.dirname(__file__), '../src/emotion_model.h5')
emotion_model = load_model(model_path, compile=False)

# Emotion labels
emotion_labels = ['Angry', 'Disgust', 'Fear', 'Happy', 'Sad', 'Surprise', 'Neutral']

# Load face cascade
cascade_path = os.path.join(os.path.dirname(__file__), '../src/haarcascade_frontalface_default.xml')
face_cascade = cv2.CascadeClassifier(cascade_path)

# Store latest emotion data
latest_emotions = {label: 0 for label in emotion_labels}

# Analysis Constants
REACTION_MAPPING = {
    'Happy': ['Positive', 'Amused', 'Satisfied'],
    'Sad': ['Disappointed', 'Concerned', 'Unhappy'],
    'Surprise': ['Startled', 'Impressed', 'Shocked'],
    'Angry': ['Frustrated', 'Hostile', 'Aggressive'],
    'Fear': ['Anxious', 'Nervous', 'Apprehensive'],
    'Disgust': ['Repelled', 'Displeased', 'Averse'],
    'Neutral': ['Calm', 'Attentive', 'Analytical']
}

class ReactionAnalyst:
    def __init__(self):
        self.history = []
        
    def interpret(self, emotions, confidence):
        dominant = max(emotions, key=emotions.get)
        intensity = "High" if confidence > 70 else "Moderate" if confidence > 40 else "Low"
        
        # Logic for complex reactions
        if dominant == 'Happy' and emotions['Surprise'] > 20:
            insight = "User is pleasantly surprised"
        elif dominant == 'Neutral' and emotions['Happy'] > 10:
            insight = "User is slightly positive"
        elif emotions['Angry'] > 15 or emotions['Disgust'] > 15:
            insight = "User shows signs of disapproval"
        elif dominant == 'Neutral' and confidence > 80:
            insight = "User is focused and concentrated"
        else:
            insight = f"User appears {REACTION_MAPPING.get(dominant, [''])[0]}"
            
        return {
            'intensity': intensity,
            'insight': insight,
            'sentiment': "Positive" if dominant in ['Happy', 'Surprise'] else "Negative" if dominant in ['Angry', 'Sad', 'Fear', 'Disgust'] else "Neutral"
        }

analyst = ReactionAnalyst()

def process_frame(frame_data):
    try:
        encoded_data = frame_data.split(',')[1]
        nparr = np.frombuffer(base64.b64decode(encoded_data), np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            return None, None

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Balanced Detection (Faster)
        faces = face_cascade.detectMultiScale(gray, 1.3, 5) 

        results = []
        emotion_data = {label: 0 for label in emotion_labels}

        if len(faces) == 0:
            return [], emotion_data

        for (x, y, w, h) in faces:
            roi_gray = gray[y:y+h, x:x+w]
            roi_gray = cv2.resize(roi_gray, (64, 64))
            roi_gray = roi_gray / 255.0
            roi_gray = np.reshape(roi_gray, (1, 64, 64, 1))

            preds = emotion_model.predict(roi_gray, verbose=0)
            emotion_idx = np.argmax(preds)
            emotion = emotion_labels[emotion_idx]
            confidence = float(preds[0][emotion_idx] * 100)
            
            face_emotions = {label: float(preds[0][i] * 100) for i, label in enumerate(emotion_labels)}
            
            # Synchronize with Intelligence Analyst
            analysis = analyst.interpret(face_emotions, confidence)

            results.append({
                'box': [int(x), int(y), int(w), int(h)],
                'emotion': emotion,
                'confidence': confidence,
                'emotions': face_emotions,
                'analysis': analysis
            })
            
            # Aggregate for global dashboard
            for label, val in face_emotions.items():
                emotion_data[label] = max(emotion_data[label], val)

        return results, emotion_data
    except Exception as e:
        print(f"Intelligence Error: {e}")
        return None, None

@socketio.on('process_frame')
def handle_frame(data):
    results, emotion_data = process_frame(data['image'])
    if results:
        emit('emotion_results', {
            'faces': results,
            'global_emotions': emotion_data
        })

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        username = request.form.get('username')
        password = request.form.get('password')
        
        # In this demo, we ensure all fields are provided
        if email and username and password:
            session['user'] = username
            return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        if username and email and password:
            session['user'] = username
            return redirect(url_for('dashboard'))
    return render_template('register.html')

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html', username=session.get('user'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('home'))

@app.route('/get_emotions')
def get_emotions():
    return jsonify(latest_emotions)

@app.route('/capture', methods=['POST'])
def capture():
    try:
        data = request.get_json()
        img_data = data.get('image', '')
        if not img_data.startswith('data:image'):
            return jsonify({'error': 'invalid image data'}), 400

        header, encoded = img_data.split(',', 1)
        img_bytes = base64.b64decode(encoded)

        save_dir = os.path.join(os.path.dirname(__file__), 'static', 'captures')
        os.makedirs(save_dir, exist_ok=True)
        filename = f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        path = os.path.join(save_dir, filename)

        with open(path, 'wb') as f:
            f.write(img_bytes)

        return jsonify({'filename': f'static/captures/{filename}'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    socketio.run(app, debug=True, host='0.0.0.0', port=port)

